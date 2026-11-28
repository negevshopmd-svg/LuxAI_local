"""0.4.4c: faster and smarter commands — the early answer, local quick actions, the Russian recognition prompt.

Measured (tests/command_bench, real-time fake microphone, Whisper medium, Russian commands read by Piper):
time from the last word to the command 6.37 s → 4.52 s; word errors 37.8 % → 23.3 % with the prompt.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from luxai import early_command, quick_actions, voice_rules  # noqa: E402


class PromptTests(unittest.TestCase):
    def test_russian_gets_a_command_prompt(self):
        options = voice_rules.recognition_options("ru", 1)
        self.assertEqual(options["initial_prompt"], voice_rules.RUSSIAN_PROMPT)
        self.assertIn("Открой", voice_rules.RUSSIAN_PROMPT)
        self.assertEqual(options["beam_size"], 1)  # beam 3 was not better and is slower (measured)
        self.assertEqual(voice_rules.recognition_options("ro", 1)["initial_prompt"], voice_rules.ROMANIAN_PROMPT)
        self.assertIsNone(voice_rules.recognition_options("en", 1)["initial_prompt"])


class QuickParseTests(unittest.TestCase):
    def test_whole_phrases_in_three_languages(self):
        cases = {
            "Сделай громче": ("volume_up", 10), "Громче": ("volume_up", 10), "Прибавь звук": ("volume_up", 10),
            "Сделай тише на 20%": ("volume_down", 20), "Делай тише на 20%": ("volume_down", 20),
            "Turn the volume up": ("volume_up", 10), "Dă mai tare": ("volume_up", 10),
            "Mai încet cu 15 procente": ("volume_down", 15), "Выключи звук": ("mute", None),
            "Пауза": ("media_play_pause", None), "Следующий трек": ("media_next", None),
            "Следующий тригг.": ("media_next", None), "Next track": ("media_next", None),
            "Предыдущий трек": ("media_previous", None), "Закрой окно": ("win_close", None),
            "Închide fereastra": ("win_close", None), "Сверни все окна": ("show_desktop", None),
            "Джарвис, следующий трек пожалуйста": ("media_next", None),
        }
        for text, (action, step) in cases.items():
            command = quick_actions.parse(text)
            self.assertIsNotNone(command, text)
            self.assertEqual(command["action"], action, text)
            if step is not None:
                self.assertEqual(command["step"], step, text)

    def test_other_requests_are_left_alone(self):
        for text in ("Выключи звук в дискорде", "Пауза в дискорде", "Сделай громче музыку в спотифае",
                     "Сделай скриншот", "Paused?", "Расскажи почему небо синее", "", "x" * 200):
            self.assertIsNone(quick_actions.parse(text), text)

    def test_a_huge_number_is_capped(self):
        self.assertEqual(quick_actions.parse("Сделай громче на 999")["step"], 100)


class QuickRunTests(unittest.TestCase):
    def test_volume_is_changed_and_read_back_within_bounds(self):
        level = {"value": 95}

        def volume(value=None):
            if value is not None:
                level["value"] = value
            return level["value"]
        with mock.patch("luxai.windows_volume.windows_volume", side_effect=volume):
            self.assertEqual(quick_actions.run({"action": "volume_up", "step": 10}, "ro"), "Volum 100%.")
            self.assertEqual(quick_actions.run({"action": "volume_down", "step": 150}, "en"), "Volume 0%.")

    def test_media_keys_and_windows(self):
        with mock.patch("luxai.extensions_runtime.press_virtual_key") as key:
            self.assertEqual(quick_actions.run({"action": "media_next"}, "ru"), "Следующий трек.")
        key.assert_called_once_with(0xB0)
        self.assertIn("Не вижу окна", quick_actions.run({"action": "win_close"}, "ru", hwnd=0))
        with mock.patch("luxai.action_circle.window_action", return_value="own_window"):
            self.assertIn("Jarvis", quick_actions.run({"action": "win_close"}, "en", hwnd=42))

    def test_a_failure_is_said_not_raised(self):
        with mock.patch("luxai.windows_volume.windows_volume", side_effect=OSError("no device")):
            self.assertIn("OSError", quick_actions.run({"action": "volume_up", "step": 10}, "en"))


class EarlyCommandTests(unittest.TestCase):
    def test_known_commands_are_complete_questions_and_messages_are_not(self):
        registry = SimpleNamespace(match=lambda text, prefix, **_k: {"id": "x"} if "мой режим" in text else None)
        for text in ("Сделай громче", "Открой калькулятор", "Поставь таймер на 5 минут", "Какая сегодня погода",
                     "Включи мой режим", "Open YouTube", "Deschide YouTube", "Следующий трек"):
            self.assertTrue(early_command.complete(text, registry), text)
        for text in ("Напиши Ане в дискорд привет", "Открой ютуб и потом включи музыку",
                     "Объясни как работает фотосинтез", "Открой калькулятор,", "", "Открой " + "очень " * 12):
            self.assertFalse(early_command.complete(text, registry), text)

    def test_prefix_mode_and_a_broken_registry(self):
        self.assertFalse(early_command.complete("Сделай громче", prefix_required=True))
        self.assertTrue(early_command.complete("Джарвис, сделай громче", prefix_required=True))
        broken = SimpleNamespace(match=mock.Mock(side_effect=RuntimeError))
        self.assertTrue(early_command.complete("Сделай громче", broken))


FRAME = 480


class FakeStream:
    stop = None  # the listener's stop event: set when the prepared audio is over

    def __init__(self, audio, *args, callback=None, **kwargs):
        self.audio, self.callback, self.active = audio, callback, True
        self.done = FakeStream.stop  # this stream's own listener (a later test must not be stopped by it)

    def __enter__(self):
        def play():
            for index in range(0, len(self.audio), FRAME):
                time.sleep(0.003)  # 10x faster than real time
                chunk = self.audio[index:index + FRAME]
                if len(chunk) == FRAME:
                    self.callback(chunk.reshape(-1, 1), FRAME, None, None)
            time.sleep(0.5)
            if self.done is not None:
                self.done.set()
        threading.Thread(target=play, daemon=True).start()
        return self

    def __exit__(self, *args):
        return False


class FakeModel:
    def __init__(self, text):
        self.text, self.calls = text, []

    def transcribe(self, audio, **kwargs):
        self.calls.append(len(audio))
        return [SimpleNamespace(text=self.text)], None


class ListenerTests(unittest.TestCase):
    def listener(self, model, accept):
        from luxai import voice
        item = voice.VoiceListener.__new__(voice.VoiceListener)
        item.status_callback = item.level_callback = item.capture_allowed = None
        item.interrupt_predicate = voice.is_stop_speech_command
        item.preserve_interrupt_text = False
        item._stop_event = threading.Event()
        item.language, item.beam_size, item.speech_pause, item.sensitivity = "ru", 1, 2.3, 1.0
        item.microphone_device, item._device_info = 0, {"name": "test", "default_samplerate": 16000}
        item.model, item.early_accept, item.early_pause = model, accept, voice.EARLY_PAUSE_SECONDS
        return item

    def run_listener(self, item, audio):
        from luxai import voice
        heard = []
        FakeStream.stop = item._stop_event
        with mock.patch.object(voice.sd, "InputStream", lambda *a, **k: FakeStream(audio, *a, **k)), \
                mock.patch.object(voice.VoiceListener, "_frame_detected",
                                  lambda self, chunk, rms, *_a: rms > 0.05):
            generator = item.listen()
            for text in generator:
                heard.append(text)
                break
            item._stop_event.set()
            generator.close()
        return heard

    @staticmethod
    def audio(*pieces):
        """(seconds, loud?) pieces → audio."""
        return np.concatenate([np.full(int(16000 * seconds), 0.3 if loud else 0.0, dtype=np.float32)
                               for seconds, loud in pieces])

    def test_a_complete_command_is_taken_at_the_short_pause(self):
        model = FakeModel("Сделай громче")
        item = self.listener(model, lambda text: True)
        audio = self.audio((0.3, False), (1.0, True), (1.0, False))  # only 1 s of silence: less than the 2.3 s pause
        self.assertEqual(self.run_listener(item, audio), ["Сделай громче"])
        self.assertEqual(len(model.calls), 1)  # one pass, not two

    def test_not_a_command_waits_for_the_whole_pause_and_reuses_the_pass(self):
        model = FakeModel("Расскажи что-нибудь интересное")
        item = self.listener(model, lambda text: False)
        self.assertEqual(self.run_listener(item, self.audio((0.3, False), (1.0, True), (1.0, False))), [])
        model = FakeModel("Расскажи что-нибудь интересное")
        item = self.listener(model, lambda text: False)
        heard = self.run_listener(item, self.audio((0.3, False), (1.0, True), (3.0, False)))
        self.assertEqual(heard, ["Расскажи что-нибудь интересное"])
        self.assertEqual(len(model.calls), 1)  # the early pass is reused at the end of the pause

    def test_speaking_on_after_the_short_pause_drops_the_early_guess(self):
        model = FakeModel("whatever")
        accepted = []
        item = self.listener(model, lambda text: accepted.append(text) or False)
        audio = self.audio((0.3, False), (1.0, True), (0.7, False), (1.0, True), (3.0, False))
        self.run_listener(item, audio)
        self.assertGreaterEqual(len(model.calls), 2)
        self.assertGreater(model.calls[-1], model.calls[0])  # the final pass covers the whole phrase

    def test_without_a_predicate_it_behaves_as_before(self):
        model = FakeModel("Сделай громче")
        item = self.listener(model, None)
        self.assertEqual(self.run_listener(item, self.audio((0.3, False), (1.0, True), (1.0, False))), [])


class RouteTests(unittest.TestCase):
    def test_quick_actions_run_locally_and_quietly(self):
        import main
        resolved = []
        host = SimpleNamespace(cfg={"response_language": "ru"}, _command_queue=[{"parts": []}], _current_route="",
                               _last_external_hwnd=7, _resolved_command=lambda text, answer: resolved.append(answer))
        with mock.patch("luxai.quick_actions.run", return_value="Следующий трек.") as run:
            self.assertTrue(main.MainWindow._route_quick_action(host, "следующий трек"))
        run.assert_called_once()
        self.assertEqual(run.call_args.args[2], 7)  # the window that was in front, not Jarvis
        self.assertTrue(host._command_queue[0]["quiet"])
        self.assertEqual(resolved, ["Следующий трек."])
        self.assertFalse(main.MainWindow._route_quick_action(host, "расскажи анекдот"))

    def test_quiet_groups_are_not_spoken(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn('origin.get("speak", True) and not group.get("quiet")', source)


if __name__ == "__main__":
    unittest.main()
