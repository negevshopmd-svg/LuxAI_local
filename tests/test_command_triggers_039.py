"""Saved-command matching, trigger boundaries and restart-safe scheduling."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import sys
import time
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

from luxai.command_registry import CommandRegistry, checked_command, phrase_matches
from luxai.command_triggers import (
    CommandTriggerEngine, WindowsHotkeyListener, normalize_hotkey,
    validate_event, validate_schedule,
    headphones_connected,
)
from luxai.command_recording import ActionRecorder, RecordingBuffer


def command(**fields):
    data = {"id": "user_test", "title": "Test", "action": "time", "target": "", "phrases": ["clock"]}
    data.update(fields)
    return checked_command(data)


class CommandMetadata039Tests(unittest.TestCase):
    def test_optional_words_only_modify_edges_and_never_match_substrings_or_negations(self):
        item = command(phrases=["телеграм", "telegram"], optional_words=["открой", "пожалуйста", "open", "please"])
        for text in ("телеграм", "Jarvis, открой телеграм пожалуйста", "please open telegram please", "OPEN TELEGRAM!"):
            self.assertTrue(phrase_matches(item, text), text)
        for text in ("не открой телеграм", "открой телеграм и удали файл", "telegrammer", "открой мой телеграм", "please"):
            self.assertFalse(phrase_matches(item, text), text)

    def test_metadata_round_trips_and_manual_only_commands_need_no_voice_phrase(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "commands.json"
            registry = CommandRegistry(path)
            saved = registry.save_custom(command(
                phrases=[], voice_enabled=False, optional_words=["please"],
                hotkey="Ctrl+ALT+T", schedule={"mode": "weekly", "time": "12:03", "weekdays": [4, 0, 4]},
                event={"type": "app_started", "app": "telegram"},
                ask_before_run=True, allow_chaining=False,
            ))
            again = CommandRegistry(path).custom[0]
            self.assertEqual(again, saved)
            self.assertEqual(again["hotkey"], "ctrl+alt+t")
            self.assertEqual(again["schedule"]["weekdays"], [0, 4])
            self.assertTrue(again["ask_before_run"])
            self.assertFalse(again["allow_chaining"])

    def test_voice_disabled_and_disabled_custom_commands_cannot_fall_through(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = CommandRegistry(Path(temp) / "commands.json")
            item = registry.save_custom(command(voice_enabled=False))
            self.assertIsNone(registry.match("clock"))
            self.assertTrue(registry.disabled_match("clock"))
            self.assertEqual(registry.match("clock", source="manual")["id"], item["id"])
            registry.set_enabled(item["id"], False)
            self.assertIsNone(registry.match("clock", source="manual"))

    def test_legacy_entries_keep_voice_and_chaining_defaults(self):
        item = command()
        self.assertTrue(item["voice_enabled"])
        self.assertTrue(item["allow_chaining"])
        self.assertFalse(item["ask_before_run"])
        self.assertEqual(item["schedule"], {})

    def test_chain_opt_out_is_applied_before_any_member_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = CommandRegistry(Path(temp) / "commands.json")
            registry.save_custom(command(id="first", phrases=["one"], allow_chaining=False))
            registry.save_custom(command(id="second", phrases=["two"]))
            self.assertTrue(registry.chain_blocked("one потом two"))
            self.assertFalse(registry.chain_blocked("one"))
            self.assertEqual(registry.match_chain("one потом two"), [])
            self.assertEqual([x["id"] for x in registry.match_chain("two потом two")], ["second", "second"])
            self.assertEqual(registry.match_chain("two потом missing"), [])
            self.assertEqual(registry.match_chain("one")[0]["id"], "first")

    def test_invalid_options_and_trigger_data_are_rejected(self):
        for fields in ({"voice_enabled": "false"}, {"optional_words": ["\n"]},
                       {"phrases": []}, {"hotkey": "f"}, {"hotkey": "q"},
                       {"hotkey": "ctrl+ctrl+t"}, {"hotkey": "alt+f4"},
                       {"schedule": {"mode": "daily", "time": "24:00"}},
                       {"schedule": {"mode": "once", "time": "12:00", "date": "2026-02-30"}},
                       {"schedule": {"mode": "weekly", "time": "12:00", "weekdays": [True]}},
                       {"event": {"type": "run_script", "app": "cmd"}}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                command(**fields)
        self.assertEqual(normalize_hotkey("Ctrl+F"), "ctrl+f")
        self.assertEqual(normalize_hotkey("F12"), "f12")


class TriggerEngine039Tests(unittest.TestCase):
    def engine(self, entries, path=None):
        registry = mock.Mock()
        registry.entries.return_value = entries
        callback = mock.Mock()
        engine = CommandTriggerEngine(registry, callback, state_path=path)
        return engine, callback

    def test_daily_schedule_crosses_due_time_once_and_survives_restart(self):
        item = command(schedule={"mode": "daily", "time": "12:00"})
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "state.json"
            engine, callback = self.engine([item], state)
            before = datetime(2026, 10, 28, 11, 59, 59)
            engine.poll(before)
            engine.poll(before + timedelta(seconds=1))
            engine.poll(before + timedelta(seconds=2))
            callback.assert_called_once()
            again, callback = self.engine([item], state)
            again.poll(before)
            again.poll(before + timedelta(seconds=1))
            callback.assert_not_called()
            again.poll(datetime(2026, 10, 29, 11, 59, 59))
            again.poll(datetime(2026, 10, 29, 12, 0, 0))
            callback.assert_called_once()

    def test_startup_sleep_and_backward_clock_changes_never_catch_up(self):
        item = command(schedule={"mode": "daily", "time": "12:00"})
        engine, callback = self.engine([item])
        engine.poll(datetime(2026, 10, 28, 12, 0, 30))
        engine.poll(datetime(2026, 10, 28, 12, 0, 31))
        engine.poll(datetime(2026, 10, 29, 11, 59, 0))
        engine.poll(datetime(2026, 10, 29, 12, 10, 0))
        engine.poll(datetime(2026, 10, 29, 11, 58, 0))
        callback.assert_not_called()

    def test_weekly_and_once_match_only_configured_date(self):
        wednesday = datetime(2026, 10, 28, 11, 59, 59)
        for schedule, expected in (({"mode": "weekly", "time": "12:00", "weekdays": [2]}, 1),
                                   ({"mode": "weekly", "time": "12:00", "weekdays": [3]}, 0),
                                   ({"mode": "once", "time": "12:00", "date": "2026-10-28"}, 1),
                                   ({"mode": "once", "time": "12:00", "date": "2026-10-29"}, 0)):
            engine, callback = self.engine([command(schedule=schedule)])
            engine.poll(wednesday)
            engine.poll(wednesday + timedelta(seconds=1))
            self.assertEqual(callback.call_count, expected, schedule)

    def test_application_and_headphone_events_require_real_transitions(self):
        engine, callback = self.engine([
            command(id="apps", event={"type": "app_started", "app": "telegram"}),
            command(id="headphones", event={"type": "headphones_connected"}),
        ])
        start = datetime(2026, 10, 28, 12)
        engine.poll(start, apps={"telegram"}, headphones=True)
        callback.assert_not_called()  # Already running/connected at startup.
        engine.poll(start + timedelta(seconds=1), apps=set(), headphones=False)
        engine.poll(start + timedelta(seconds=2), apps={"telegram"}, headphones=True)
        self.assertEqual([call.args[0]["id"] for call in callback.call_args_list], ["apps", "headphones"])
        engine.poll(start + timedelta(seconds=3), apps={"telegram"}, headphones=True)
        self.assertEqual(callback.call_count, 2)

    def test_hotkey_revalidates_entry_and_debounces(self):
        entry = command(hotkey="ctrl+alt+t", voice_enabled=False, phrases=[])
        engine, callback = self.engine([entry])
        with mock.patch("luxai.command_triggers.time.monotonic", side_effect=[1.0, 1.1, 2.0]):
            engine.handle_hotkey(entry["id"])
            engine.handle_hotkey(entry["id"])
            engine.registry.entries.return_value = [dict(entry, enabled=False)]
            engine.handle_hotkey(entry["id"])
        callback.assert_called_once()

    def test_no_device_scans_when_no_event_command_requests_them(self):
        engine, callback = self.engine([command()])
        with mock.patch("luxai.command_triggers.running_applications") as processes, mock.patch("luxai.command_triggers.headphones_connected") as audio:
            engine.poll()
        processes.assert_not_called()
        audio.assert_not_called()
        callback.assert_not_called()

    def test_windows_headphone_event_reads_live_endpoint_state_without_restart(self):
        comtypes = ModuleType("comtypes")
        comtypes.CoInitialize, comtypes.CoUninitialize = mock.Mock(), mock.Mock()
        pycaw = ModuleType("pycaw.pycaw")
        utilities = mock.Mock()
        pycaw.AudioUtilities = utilities
        utilities.GetAllDevices.return_value = [SimpleNamespace(state=2, FriendlyName="Headphones USB")]
        with (mock.patch.dict(sys.modules, {"comtypes": comtypes, "pycaw.pycaw": pycaw}),
              mock.patch("luxai.command_triggers.sys.platform", "win32")):
            self.assertFalse(headphones_connected())
            utilities.GetAllDevices.return_value = [SimpleNamespace(state=1, FriendlyName="Headphones USB")]
            self.assertTrue(headphones_connected())
        self.assertEqual(comtypes.CoInitialize.call_count, 2)
        self.assertEqual(comtypes.CoUninitialize.call_count, 2)

    def test_simultaneous_event_and_schedule_start_one_command(self):
        engine, callback = self.engine([command(
            schedule={"mode": "daily", "time": "12:00"},
            event={"type": "app_started", "app": "telegram"},
        )])
        engine.poll(datetime(2026, 10, 28, 11, 59, 59), apps=set())
        engine.poll(datetime(2026, 10, 28, 12, 0), apps={"telegram"})
        callback.assert_called_once()

    def test_slow_device_scan_never_blocks_poll_and_only_one_scan_runs(self):
        engine, callback = self.engine([command(event={"type": "headphones_connected"})])
        started, release = threading.Event(), threading.Event()

        def blocked_driver():
            started.set()
            release.wait(timeout=2)
            return False

        with mock.patch("luxai.command_triggers.headphones_connected", side_effect=blocked_driver) as scan:
            try:
                engine.poll(datetime(2026, 10, 28, 12))
                self.assertTrue(started.wait(timeout=1))
                engine.poll(datetime(2026, 10, 28, 12, 0, 1))
                self.assertEqual(scan.call_count, 1)
            finally:
                release.set()
                engine._probe_thread.join(timeout=1)
        callback.assert_not_called()

    def test_nonwindows_shortcuts_report_unsupported_without_starting_thread(self):
        listener = WindowsHotkeyListener(mock.Mock())
        with mock.patch("luxai.command_triggers.sys.platform", "linux"):
            listener.sync([command(hotkey="ctrl+alt+t")])
        self.assertIn("user_test", listener.errors)
        self.assertIsNone(listener._thread)
        self.assertTrue(listener.last_error)

    @unittest.skipUnless(sys.platform == "win32", "Native Windows hotkey lifecycle")
    def test_windows_hotkey_listener_releases_native_thread(self):
        listener = WindowsHotkeyListener(mock.Mock())
        try:
            listener.sync([command(hotkey="ctrl+alt+f11")])
            deadline = time.monotonic() + 2
            while listener._thread_id is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertIsNotNone(listener._thread_id)
            # A runner may already own the combination. Both outcomes must
            # leave a live listener that reports any registration conflict.
            self.assertTrue(listener._thread.is_alive())
        finally:
            listener.stop()
        self.assertFalse(listener._thread.is_alive())


class Recording039Tests(unittest.TestCase):
    def buffer(self, cap=8):
        buffer = RecordingBuffer(cap, own_pid=10)
        buffer.begin()
        return buffer

    def test_plain_text_and_jarvis_controls_are_not_recorded(self):
        buffer = self.buffer()
        for key in "MyPassword123":
            buffer.record_key(key, foreground_pid=20)
        buffer.record_key("space", foreground_pid=20)
        buffer.record_key("backspace", foreground_pid=20)
        buffer.record_click(20, 40, foreground_pid=10)
        buffer.record_key("f1", foreground_pid=10)
        self.assertEqual(buffer.stop(), [])

    def test_opt_in_game_keys_record_qwe_as_actions_only_in_game_foreground(self):
        buffer = RecordingBuffer(8, own_pid=10, record_game_keys=True)
        buffer.begin()
        for key in "password":
            buffer.record_key(key, foreground_pid=20, foreground_is_game=False)
        for key in "qwe1":
            buffer.record_key(key, foreground_pid=30, foreground_is_game=True)
        buffer.record_key("q", foreground_pid=10, foreground_is_game=True)
        self.assertEqual([(step["action"], step["target"]) for step in buffer.stop()],
                         [("press_key", key) for key in "qwe1"])
        default = self.buffer()
        for key in "qwe1":
            default.record_key(key, foreground_pid=30, foreground_is_game=True)
        self.assertEqual(default.stop(), [])

    def test_recorded_steps_are_validated_and_never_executed(self):
        buffer = self.buffer()
        with mock.patch("luxai.desktop_actions.execute_desktop_step") as execute:
            buffer.record_click(200, 300, "right", foreground_pid=20)
            buffer.record_key("s", ["ctrl"], foreground_pid=20)
            buffer.record_key("f1", foreground_pid=20)
            buffer.record_scroll(200, 300, -3, foreground_pid=20)
            steps = buffer.stop()
        self.assertEqual([step["action"] for step in steps],
                         ["mouse_move", "mouse_right_click", "hotkey", "press_key", "mouse_move", "mouse_scroll"])
        execute.assert_not_called()
        self.assertEqual(steps[2]["target"], "ctrl+s")

    def test_cap_never_leaves_a_partial_click_or_records_after_stop(self):
        buffer = self.buffer(3)
        buffer.record_click(200, 300, foreground_pid=20)
        buffer.record_click(220, 320, foreground_pid=20)
        self.assertFalse(buffer.active)
        self.assertEqual(len(buffer.steps), 2)
        self.assertTrue(buffer.error)
        buffer.record_key("f1", foreground_pid=20)
        self.assertEqual(len(buffer.stop()), 2)

    def test_escape_stops_and_platform_failure_does_not_keep_listener(self):
        buffer = self.buffer()
        buffer.record_key("esc", foreground_pid=10)
        self.assertFalse(buffer.active)
        recorder = ActionRecorder()
        with mock.patch("luxai.command_recording.sys.platform", "linux"):
            self.assertFalse(recorder.start())
        self.assertFalse(recorder.active)
        self.assertIsNone(recorder._thread)
        self.assertTrue(recorder.error)

    @unittest.skipUnless(sys.platform == "win32", "Native Windows recording lifecycle")
    def test_windows_recorder_installs_and_removes_native_hooks_without_playback(self):
        recorder = ActionRecorder()
        try:
            self.assertTrue(recorder.start(), recorder.error)
            self.assertTrue(recorder.active)
        finally:
            recorder.stop()
        self.assertFalse(recorder.active)
        self.assertFalse(recorder._thread.is_alive())


if __name__ == "__main__":
    unittest.main()
