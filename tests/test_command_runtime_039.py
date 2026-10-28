"""Manual, scheduled and chained commands use one confirmed execution route."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

import main
from luxai import command_registry
from luxai.command_registry import checked_command
from luxai.command_triggers import CommandTriggerEngine
from luxai.ui_i18n import get_ui_language, set_ui_language


def entry(identifier="user_runtime", **options):
    data = {"id": identifier, "title": "Runtime test", "action": "time", "target": "",
            "phrases": ["runtime phrase"], "enabled": True}
    data.update(options)
    return checked_command(data)


class CommandRuntime039Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.language = get_ui_language()
        cls.temporary = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temporary.name)
        config = cls.folder / "config.json"
        config.write_text(json.dumps({
            "microphone_enabled": False, "tts_enabled": False,
            "ui_animations": False, "online_agent_enabled": False,
            "ui_language": "ru", "language": "ru", "response_language": "ru",
            "minimize_to_tray": False, "confirm_all_actions": False,
        }), encoding="utf-8")
        cls.config_patch = mock.patch.object(main, "CONFIG", config)
        cls.registry_patch = mock.patch.object(command_registry, "REGISTRY_FILE", cls.folder / "commands.json")
        cls.config_patch.start()
        cls.registry_patch.start()
        try:
            with (mock.patch("sounddevice.query_devices", return_value=[]),
                  mock.patch.object(main.MainWindow, "_ocr_setup_worker")):
                cls.window = main.MainWindow()
        except Exception:
            cls.registry_patch.stop()
            cls.config_patch.stop()
            cls.temporary.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.window._quitting = True
        cls.window.close()
        cls.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        cls.registry_patch.stop()
        cls.config_patch.stop()
        cls.temporary.cleanup()
        set_ui_language(cls.language)

    def setUp(self):
        self.window._closed = False
        self.window._processing = False
        self.window._active_text = None
        self.window._command_queue = []
        self.window._pending_agent_task = None
        self.window._pending_discord_message = None
        self.window._adaptive_runtime = None
        self.window._macro_context = None
        self.window.dictation_active = False
        self.window.command_registry.custom = []
        self.window.command_registry.disabled_builtins.clear()

    def test_native_thread_hotkey_is_dispatched_on_qt_ui_thread(self):
        import threading
        from PySide6.QtCore import QThread
        from PySide6.QtTest import QTest
        received = []
        with mock.patch.object(self.window._trigger_engine, "handle_hotkey",
                side_effect=lambda identifier: received.append((identifier, QThread.currentThread()))):
            worker = threading.Thread(target=lambda: self.window.command_hotkey.emit("thread-test"))
            worker.start()
            worker.join(timeout=1)
            QTest.qWait(30)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0][0], "thread-test")
        self.assertIs(received[0][1], self.window.thread())

    def test_manual_draft_without_voice_phrase_executes_exact_entry(self):
        draft = entry(voice_enabled=False, phrases=[], steps=[{"action": "speak_text", "target": "Draft action"}])
        with (mock.patch.object(self.window, "run_command") as voice_route,
              mock.patch.object(self.window, "_execute_registered") as execute):
            self.window.run_saved_command(draft)
        voice_route.assert_not_called()
        execute.assert_called_once_with("Runtime test", draft)

    def test_scheduled_entry_uses_same_direct_queue_and_preserves_pending_work(self):
        scheduled = self.window.command_registry.save_custom(entry(
            voice_enabled=False, phrases=[], schedule={"mode": "daily", "time": "12:00"},
        ))
        engine = CommandTriggerEngine(self.window.command_registry, self.window.run_command_entry,
                                      state_path=self.folder / "schedule-state.json")
        engine.poll(datetime(2026, 10, 28, 11, 59, 59))
        self.window._processing = True
        self.window._command_queue = [{"parts": [], "answers": [], "routes": [], "original_text": "existing work"}]
        with mock.patch.object(self.window, "_execute_registered") as execute:
            engine.poll(datetime(2026, 10, 28, 12, 0))
            execute.assert_not_called()
            self.assertEqual(self.window._command_queue[0]["original_text"], "existing work")
            queued = self.window._command_queue[1]
            self.assertEqual(queued["saved_entry"], scheduled)
            self.window._command_queue.pop(0)
            self.window._processing = False
            self.window._dispatch_command()
        execute.assert_called_once_with("Runtime test", scheduled)

    def test_per_command_confirmation_forces_prompt_and_decline_prevents_steps(self):
        guarded = entry(ask_before_run=True, steps=[{"action": "hotkey", "target": "ctrl+s"}])
        with (mock.patch.object(self.window, "confirm_action", return_value=False) as confirm,
              mock.patch.object(self.window, "_run_saved_steps") as steps,
              mock.patch.object(self.window.agent, "execute_plan") as execute,
              mock.patch.object(self.window, "_resolved_command") as result):
            self.window._execute_registered("runtime phrase", guarded)
        self.assertTrue(confirm.call_args.kwargs["force"])
        steps.assert_not_called()
        execute.assert_not_called()
        self.assertIn("отменена", result.call_args.args[1])

    def test_chain_opt_out_rejects_whole_compound_before_execution(self):
        self.window.command_registry.save_custom(entry("first", phrases=["first command"], allow_chaining=False))
        self.window.command_registry.save_custom(entry("second", phrases=["second command"]))
        with (mock.patch.object(self.window, "apply_settings"),
              mock.patch.object(self.window, "_execute_registered") as execute):
            self.window.run_command("first command потом second command")
        execute.assert_not_called()
        self.assertEqual(self.window._command_queue, [])

    def test_opted_in_chain_preserves_execution_order(self):
        self.window.command_registry.save_custom(entry("first", phrases=["first command"]))
        self.window.command_registry.save_custom(entry("second", phrases=["second command"]))
        executed = []

        def complete_step(text, saved):
            executed.append(saved["id"])
            self.window._processing = False
            if not self.window._command_queue[0]["parts"]:
                self.window._command_queue.pop(0)
            self.window._dispatch_command()

        with (mock.patch.object(self.window, "apply_settings"),
              mock.patch.object(self.window, "_execute_registered", side_effect=complete_step)):
            self.window.run_command("first command потом second command")
        self.assertEqual(executed, ["first", "second"])
        self.assertEqual(self.window._command_queue, [])

    def test_disabled_manual_and_automatic_entries_do_not_execute(self):
        disabled = entry(enabled=False, hotkey="ctrl+alt+t", schedule={"mode": "daily", "time": "12:00"})
        self.window.command_registry.custom = [disabled]
        engine = CommandTriggerEngine(self.window.command_registry, self.window.run_command_entry, state_path=None)
        with mock.patch.object(self.window, "_execute_registered") as execute:
            self.window.run_saved_command(disabled)
            engine.handle_hotkey(disabled["id"])
            engine.poll(datetime(2026, 10, 28, 11, 59, 59))
            engine.poll(datetime(2026, 10, 28, 12, 0))
        execute.assert_not_called()
        self.assertEqual(self.window._command_queue, [])

    def test_actual_trigger_callback_cancels_stale_queued_command(self):
        for change in ("disabled", "removed", "edited"):
            with self.subTest(change=change):
                scheduled = self.window.command_registry.save_custom(entry(
                    "trigger_" + change, voice_enabled=False, phrases=[],
                    schedule={"mode": "daily", "time": "12:00"},
                ))
                self.window._processing = True
                self.window._command_queue = [{"parts": [], "answers": [], "routes": [], "original_text": "existing work"}]
                self.window._trigger_engine.callback(scheduled)
                self.assertEqual(self.window._command_queue[1]["triggered_id"], scheduled["id"])
                if change == "disabled":
                    self.window.command_registry.set_enabled(scheduled["id"], False)
                elif change == "removed":
                    self.window.command_registry.remove_custom(scheduled["id"])
                else:
                    self.window.command_registry.save_custom(dict(scheduled, title="Updated command"))
                self.window._command_queue.pop(0)
                self.window._processing = False
                with (mock.patch.object(self.window, "_execute_registered") as execute,
                      mock.patch.object(self.window, "_resolved_command") as result):
                    self.window._dispatch_command()
                execute.assert_not_called()
                self.assertIn("отключена до запуска", result.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
