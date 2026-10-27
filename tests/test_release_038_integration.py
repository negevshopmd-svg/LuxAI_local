"""Exercise release behavior at the Qt routing/presentation boundary."""
import json
from pathlib import Path
import tempfile
from types import MethodType, SimpleNamespace
import unittest
from unittest import mock

from test_games_multilingual import LAUNCH_VARIANTS, CLOSE_VARIANTS


class Release038PresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import main
        from luxai.ui_i18n import get_ui_language, set_ui_language
        self.addCleanup(set_ui_language, get_ui_language())
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        filename = Path(folder.name) / "config.json"
        filename.write_text(json.dumps({
            "microphone_enabled": False, "tts_enabled": False,
            "online_agent_enabled": False, "ui_theme": "dark", "ui_language": "ro",
            "response_language": "ro", "ui_accent": "#3978f6",
        }), encoding="utf-8")
        patcher = mock.patch.object(main, "CONFIG", filename)
        patcher.start()
        self.addCleanup(patcher.stop)
        with (mock.patch("sounddevice.query_devices", return_value=[]),
              mock.patch.object(main.MainWindow, "_ocr_setup_worker")):
            self.window = main.MainWindow()
        self.addCleanup(self.window.close)

    def test_progress_is_transient_inside_both_chats_and_absent_from_header(self):
        import main
        window = self.window
        self.assertTrue(window.mic_status.isHidden())
        window.mic_status.setText("Настройки сохранены.")
        self.assertTrue(window.chat_activity.isHidden())
        self.assertTrue(window.home_page.history_activity.isHidden())
        initial = list(window.history)
        for answer in ("War Thunder a fost închis.", "Eroare verificată.", "Acțiune anulată.", ""):
            with self.subTest(answer=answer), mock.patch.object(main.QTimer, "singleShot"):
                window._processing, window._active_text = True, "Închide War Thunder"
                window._command_queue = [{"parts": [], "answers": [], "routes": [],
                                          "original_text": "Închide War Thunder"}]
                window.mic_status.setText("Execut și verific… <fără marcaj HTML>")
                for label in (window.chat_activity, window.home_page.history_activity):
                    self.assertFalse(label.isHidden())
                    self.assertEqual(label.text(), "Execut și verific… <fără marcaj HTML>")
                self.assertEqual(window.history, initial)
                window._resolved_command("Închide War Thunder", answer)
                window._finish_command_group()
                for label in (window.chat_activity, window.home_page.history_activity):
                    self.assertTrue(label.isHidden())
                    self.assertEqual(label.text(), "")
                if answer:
                    initial.append(("Jarvis", answer))
                self.assertEqual(window.history, initial)
                self.assertNotIn("Execut și verific", window.log.toPlainText())

    def test_starting_command_applies_pending_accent_and_recolors_existing_history(self):
        import main
        window = self.window
        window.append_message("Tu", "Mesaj vechi", "#4388f9")
        window.append_message("Jarvis", "Răspuns vechi", "#a5b9dc")
        window.command.setText("Ciornă păstrată")
        window.command.setCursorPosition(6)
        history = list(window.history)
        accent = window.settings_panel.accent
        accent.setCurrentIndex(accent.findData("#873eff"))
        # A command may start during the autosave debounce interval.
        with (mock.patch.object(main.QTimer, "singleShot"),
              mock.patch.object(window, "_dispatch_command")):
            window.run_command("Închide War Thunder")
        self.assertEqual(window.home_page.avatar._accent, "#873eff")
        self.assertIn("#873eff", window.log.toHtml().lower())
        self.assertIn("#873eff", window.home_history.toHtml().lower())
        self.assertEqual(window.command.text(), "Ciornă păstrată")
        self.assertEqual(window.command.cursorPosition(), 6)
        self.assertEqual(window.history, history)
        self.assertTrue(window.mic_status.isHidden())

    def test_api_activity_clears_even_when_result_was_for_outdated_settings(self):
        window = self.window
        window._api_test_running = True
        window.mic_status.setText("Проверяю подключение к API…")
        self.assertFalse(window.chat_activity.isHidden())
        window._api_test_requested_signature = ("obsolete",)
        window._on_api_test_result("gemini", False, "Outdated result", None)
        self.assertTrue(window.chat_activity.isHidden())


class Release038NativeRoutingTests(unittest.TestCase):
    def window(self, phrase, language):
        import main
        registry = mock.Mock()
        registry.disabled_match.return_value = False
        registry.match.return_value = None
        window = SimpleNamespace(
            cfg={"response_language": language, "tts_enabled": False},
            _processing=False, _closed=False, _active_text=None, _current_route="",
            _command_queue=[{"parts": [phrase], "answers": [], "routes": [], "original_text": phrase}],
            _pending_discord_message=None, _pending_agent_task=None,
            _adaptive_runtime=None, _adaptive_token=None, _last_visual_goal=None,
            _last_visual_goal_at=0.0, dictation_active=False,
            command_wizard=SimpleNamespace(active=False), command_registry=registry,
            online_planner=mock.Mock(), agent=mock.Mock(), mic_status=mock.Mock(),
            _start_native_plan=mock.Mock(), _start_adaptive_task=mock.Mock(),
            _start_visual_reasoner=mock.Mock(), _resolved_command=mock.Mock(),
            _execute_registered=mock.Mock(), confirm_action=mock.Mock(return_value=True),
            _native_plan_worker=mock.Mock(), direct_task_ready=mock.Mock(),
            _error_message=lambda error: f"Native error: {error}",
        )
        window._dispatch_command = MethodType(main.MainWindow._dispatch_command, window)
        return window

    def test_every_game_launch_and_close_variant_selects_native_plan_before_cloud(self):
        for corpus, action in ((LAUNCH_VARIANTS, "launch_game"), (CLOSE_VARIANTS, "close_app")):
            for language, phrases in corpus.items():
                for phrase in phrases:
                    with self.subTest(language=language, phrase=phrase):
                        window = self.window(phrase, language)
                        window._dispatch_command()
                        window._start_native_plan.assert_called_once_with(
                            phrase, {"action": action, "target": "warthunder"})
                        window._start_adaptive_task.assert_not_called()
                        window._start_visual_reasoner.assert_not_called()
                        window.agent.handle.assert_not_called()
                        window._resolved_command.assert_not_called()

    def test_manual_saved_request_retains_priority(self):
        window = self.window("Închide War Thunder", "ro")
        saved = {"builtin": False, "action": "open_app", "target": "notepad"}
        window.command_registry.match.return_value = saved
        window._dispatch_command()
        window._start_native_plan.assert_not_called()
        window._execute_registered.assert_called_once_with("Închide War Thunder", saved)

    def test_approval_stays_on_qt_thread_and_executor_receives_frozen_plan(self):
        import main
        phrase = "Închide War Thunder"
        window = self.window(phrase, "ro")
        plan = {"action": "close_app", "target": "warthunder"}
        with mock.patch.object(main.threading, "Thread") as thread:
            main.MainWindow._start_native_plan(window, phrase, plan)
        window.confirm_action.assert_called_once_with("Închide War Thunder")
        thread.return_value.start.assert_called_once_with()
        self.assertIsNot(thread.call_args.kwargs["args"][1], plan)
        self.assertEqual(thread.call_args.kwargs["args"][1], plan)
        window.agent.execute_plan.return_value = "War Thunder a fost închis."
        main.MainWindow._native_plan_worker(window, phrase, plan)
        callback = window.agent.execute_plan.call_args.kwargs["confirm_callback"]
        self.assertTrue(callback("Native backend confirmation"))
        window._closed = True
        self.assertFalse(callback("Obsolete request"))
        window.confirm_action.assert_called_once()
        window.direct_task_ready.emit.assert_called_once_with(phrase, "native", "War Thunder a fost închis.")

    def test_cancelled_native_command_never_spawns_executor(self):
        import main
        window = self.window("Închide War Thunder", "ro")
        window.confirm_action.return_value = False
        with mock.patch.object(main.threading, "Thread") as thread:
            main.MainWindow._start_native_plan(window, "Închide War Thunder", {"action": "close_app", "target": "warthunder"})
        thread.assert_not_called()
        window._resolved_command.assert_called_once_with("Închide War Thunder", "Acțiune anulată.")
