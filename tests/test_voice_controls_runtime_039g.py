"""Hold-to-speak gates captured audio and mode phrases control real runtime state."""
from __future__ import annotations

from collections import deque
import sys
import threading
import types
import unittest
from unittest import mock

import numpy as np

import main
from luxai import voice


class VoiceControlsRuntime039gTests(unittest.TestCase):
    def fake_window(self, config=None):
        window = types.SimpleNamespace(
            cfg={"prefix_enabled": True, **(config or {})},
            dictation_active=False,
            _command_queue=[{"parts": ["second step"]}],
            _processing=True, _active_text="first step", _current_route="saved",
            _macro_context={"index": 1}, _adaptive_token="old-task",
            _adaptive_runtime=types.SimpleNamespace(cancel_event=threading.Event()),
            _pending_agent_task=None, _pending_discord_message={"message": "draft"},
            _attachment_token=2, _attachment_active=object(),
            pending_confirmation_dialog=mock.Mock(), pending_confirmation_result=None,
            command_wizard=types.SimpleNamespace(active=False, cancel=mock.Mock()),
            mic_status=mock.Mock(), mic=mock.Mock(), home_quiet=mock.Mock(),
            stop_speaking=mock.Mock(), sync_quiet=mock.Mock(), sync_prefix=mock.Mock(),
            toggle_mic=mock.Mock(), append_message=mock.Mock(), run_command=mock.Mock(),
        )
        window.stop_command_chain = types.MethodType(main.MainWindow.stop_command_chain, window)
        window._handle_mode_control = types.MethodType(main.MainWindow._handle_mode_control, window)
        return window

    def test_spoken_custom_stop_cancels_remaining_steps_dialog_and_workers(self):
        window = self.fake_window({"command_stop_phrases": "cancel all"})
        runtime = window._adaptive_runtime
        dialog = window.pending_confirmation_dialog
        main.MainWindow.handle_voice(window, "Jarvis, cancel all!")
        self.assertTrue(runtime.cancel_event.is_set())
        self.assertEqual(window._command_queue, [])
        self.assertIsNone(window._macro_context)
        self.assertIsNone(window._active_text)
        self.assertFalse(window._processing)
        self.assertEqual(window._attachment_token, 3)
        self.assertIsNone(window._pending_discord_message)
        self.assertFalse(window.pending_confirmation_result)
        dialog.done.assert_called_once_with(0)
        window.stop_speaking.assert_called_once()
        window.run_command.assert_not_called()

    def test_mode_phrases_run_before_wake_filter_and_use_existing_switches(self):
        for phrase, action in (("перейди в режим префикса", "prefix"),
                               ("перейди в тихий режим", "quiet"),
                               ("выключи микрофон", "microphone")):
            with self.subTest(action=action):
                window = self.fake_window()
                main.MainWindow.handle_voice(window, phrase)
                if action == "prefix":
                    window.sync_prefix.assert_called_once_with(True)
                elif action == "quiet":
                    window.sync_quiet.assert_called_once_with(True)
                    window.stop_speaking.assert_called_once()
                else:
                    window.mic.setChecked.assert_called_once_with(False)
                    window.toggle_mic.assert_called_once_with(False)
                window.run_command.assert_not_called()

    def test_old_macro_timer_cannot_advance_new_command_after_stop(self):
        old_context, new_context = {}, {}
        window = types.SimpleNamespace(_macro_context=old_context, _next_macro_step=mock.Mock())
        with mock.patch.object(main.QTimer, "singleShot") as timer:
            main.MainWindow._schedule_macro_step(window, 30000, old_context)
        window._macro_context = new_context
        timer.call_args.args[1]()
        window._next_macro_step.assert_not_called()

    def test_cancelled_result_cannot_complete_a_different_active_request(self):
        window = self.fake_window()
        window.stop_command_chain()
        new_group = {"parts": ["next"], "answers": [], "routes": []}
        window._command_queue = [new_group]
        window._processing = True
        window._active_text = "new request"
        main.MainWindow._resolved_command(window, "first step", "late result")
        self.assertEqual(new_group, {"parts": ["next"], "answers": [], "routes": []})
        self.assertTrue(window._processing)

    def test_delayed_native_worker_does_not_run_after_its_macro_is_stopped(self):
        window = types.SimpleNamespace(_closed=False, _macro_context=None)
        with mock.patch("luxai.desktop_actions.execute_desktop_step") as execute:
            main.MainWindow._macro_worker(window, {"action": "mouse_click", "target": "1"}, 1, {"text": "old"})
        execute.assert_not_called()

    def test_old_visual_result_cannot_click_for_a_new_macro(self):
        window = types.SimpleNamespace(_macro_context={"index": 1})
        result = {"macro_context": {"index": 1}, "capture": object(), "point": [0.5, 0.5], "count": 1}
        with mock.patch.object(main, "click_visual_target") as click:
            main.MainWindow._on_visual_step_ready(window, 1, result, "")
        click.assert_not_called()

    def test_queued_macro_errors_cannot_finish_a_replacement_macro(self):
        old_context = {"index": 1}
        window = types.SimpleNamespace(_macro_context={"index": 1})
        handlers = (
            main.MainWindow._on_discord_draft_ready,
            main.MainWindow._on_discord_open_ready,
            main.MainWindow._on_discord_review_ready,
            main.MainWindow._on_discord_send_ready,
            main.MainWindow._on_research_notepad_ready,
            main.MainWindow._on_visual_step_ready,
        )
        for handler in handlers:
            with self.subTest(handler=handler.__name__):
                # Every handler must return before reading another macro's
                # UI fields, even for an old error with no result object.
                handler(window, 1, None, "cancelled", old_context)
        main.MainWindow._on_macro_step_ready(window, 1, False, "cancelled", old_context)

    def test_repeated_text_does_not_accept_cancelled_cloud_or_local_results(self):
        window = types.SimpleNamespace(_command_generation=2)
        main.MainWindow._on_online_plan(window, "same request", {"action": "open_app"}, 1)
        main.MainWindow._on_local_reply(window, "same request", "late reply", 1)
        main.MainWindow._on_direct_macro_ready(window, "same request", {"steps": []}, "", 1)

    def test_hold_gate_is_sampled_at_capture_and_finishes_after_key_release(self):
        frame = (0.02 * np.sin(np.arange(480) * 2 * np.pi * 440 / 16000)).astype(np.float32)
        blocked = np.tile(frame * 8, 12)
        held = np.tile(frame, 12)
        released = np.zeros(480 * 90, dtype=np.float32)
        samples = np.concatenate((blocked, released, held, released))
        states = deque([False] * 102 + [True] * 12 + [False] * 90)
        model = mock.Mock()
        model.transcribe.return_value = ([types.SimpleNamespace(text="accepted held speech")], None)
        device = {"name": "Mock mic", "max_input_channels": 1, "default_samplerate": 16000}

        class Stream:
            active = True
            def __init__(self, **settings):
                self.callback = settings["callback"]
            def __enter__(self):
                for offset in range(0, len(samples), 480):
                    chunk = samples[offset:offset + 480].reshape(-1, 1)
                    self.callback(chunk, len(chunk), None, False)
                return self
            def __exit__(self, *_):
                pass

        voice.playback_active.clear()
        with (mock.patch.dict(sys.modules, {
                  "faster_whisper": types.SimpleNamespace(WhisperModel=mock.Mock(return_value=model)),
                  "webrtcvad": None}),
              mock.patch.object(voice.sd, "query_devices", return_value=device),
              mock.patch.object(voice.sd, "check_input_settings"),
              mock.patch.object(voice.sd, "InputStream", Stream)):
            listener = voice.VoiceListener(language="ru", capture_allowed=lambda: states.popleft())
            generator = listener.listen()
            try:
                self.assertEqual(next(generator), "accepted held speech")
            finally:
                generator.close()
        self.assertEqual(model.transcribe.call_count, 1)
        # The blocked section was much louder than held speech. It cannot
        # appear in Whisper's normalized utterance, even after key release.
        captured = model.transcribe.call_args.args[0]
        self.assertAlmostEqual(float(np.max(np.abs(captured))), 0.1, places=5)
        self.assertEqual(len(states), 0)


if __name__ == "__main__":
    unittest.main()
