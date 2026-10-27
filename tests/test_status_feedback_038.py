"""Important outcomes remain visible after header status becomes transient."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


class StatusFeedback038Tests(unittest.TestCase):
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
        self.folder = Path(folder.name)
        self.filename = self.folder / "config.json"
        self.filename.write_text(json.dumps({
            "microphone_enabled": False, "tts_enabled": False,
            "online_agent_enabled": False, "response_language": "ro",
            "ui_language": "ro", "ui_accent": "#873eff",
        }), encoding="utf-8")
        patcher = mock.patch.object(main, "CONFIG", self.filename)
        patcher.start()
        self.addCleanup(patcher.stop)
        with (mock.patch("sounddevice.query_devices", return_value=[]),
              mock.patch.object(main.MainWindow, "_ocr_setup_worker")):
            self.window = main.MainWindow()
        self.addCleanup(self.window.close)

    def assert_visible_result(self, expected):
        window = self.window
        self.assertTrue(window.mic_status.isHidden())
        self.assertTrue(window.chat_activity.isHidden())
        self.assertTrue(window.home_page.history_activity.isHidden())
        self.assertIn(expected, window.log.toPlainText())
        self.assertIn(expected, window.home_history.toPlainText())
        self.assertEqual(window.history[-1], ("Jarvis", expected))

    def test_failed_config_write_is_visible_once_per_attempt_and_keeps_old_settings(self):
        import main
        from luxai.ui_i18n import tr
        original = dict(self.window.cfg)
        self.window.settings_panel.online_model.setText("different-model")
        with mock.patch.object(main, "save_config", side_effect=OSError("disk full")):
            self.assertFalse(self.window.save_settings())
        self.assertEqual(self.window.cfg, original)
        self.assertEqual(len(self.window.history), 1)
        self.assert_visible_result(tr("Ошибка сохранения config.json."))
        # Avoid an unrelated successful autosave during fixture cleanup.
        self.window.settings_panel.mark_auto_saved()

    def test_local_ai_installer_missing_file_and_process_failure_are_visible(self):
        import main
        import subprocess
        with (mock.patch.object(main.sys, "platform", "win32"),
              mock.patch.object(main, "BASE", self.folder),
              mock.patch.object(subprocess, "CREATE_NEW_CONSOLE", 16, create=True),
              mock.patch.object(subprocess, "Popen") as launch):
            self.window.install_local_ai()
            launch.assert_not_called()
            self.assert_visible_result("install_local_ai.bat missing. Run Update.bat.")
            (self.folder / "install_local_ai.bat").write_text("@exit /b 0", encoding="utf-8")
            launch.side_effect = OSError("not executable")
            self.window.install_local_ai()
            self.assert_visible_result("Could not launch local AI installer: OSError")
        self.assertEqual(len(self.window.history), 2)

    def test_explicit_installer_success_reports_launch_without_claiming_installation(self):
        import main
        import subprocess
        script = self.folder / "install_local_ai.bat"
        script.write_text("@exit /b 0", encoding="utf-8")
        with (mock.patch.object(main.sys, "platform", "win32"),
              mock.patch.object(main, "BASE", self.folder),
              mock.patch.object(subprocess, "CREATE_NEW_CONSOLE", 16, create=True),
              mock.patch.object(subprocess, "Popen") as launch):
            self.window.install_local_ai()
        launch.assert_called_once_with(["cmd.exe", "/c", str(script)],
                                       cwd=str(self.folder), creationflags=16)
        self.assert_visible_result(
            "Installing GGUF support in a separate console. Refresh models after completion.")

    def test_unsupported_installer_reports_visible_outcome(self):
        import main
        with mock.patch.object(main.sys, "platform", "linux"):
            self.window.install_local_ai()
        self.assert_visible_result("This installer is supported only on Windows.")

    def test_voice_failure_after_command_finishes_remains_visible_without_recursive_speech(self):
        window = self.window
        with mock.patch.object(window, "_queue_speech") as speech:
            window._on_tts_played(False, window._speech_generation)
        speech.assert_not_called()
        self.assert_visible_result("Vocea nu este disponibilă. Verifică voice_error.log.")
        count = len(window.history)
        window._on_tts_played(False, window._speech_generation - 1)
        window._on_tts_played(True, window._speech_generation)
        self.assertEqual(len(window.history), count)

    def test_confirmation_uses_selected_accent_and_preserves_warning_semantics(self):
        import main
        window = self.window
        window.cfg["confirm_all_actions"] = True
        dialog = mock.Mock()
        dialog.exec.return_value = main.QMessageBox.StandardButton.No
        factory = mock.Mock(return_value=dialog)
        factory.StandardButton = main.QMessageBox.StandardButton
        with (mock.patch.object(main, "QMessageBox", factory),
              mock.patch.object(main, "icon") as icon,
              mock.patch.object(main, "set_button_icon"),
              mock.patch.object(main.QTimer, "singleShot")):
            window.confirm_action("Închide War Thunder")
            icon.assert_called_once_with("circle-help", color="#873eff")
            icon.reset_mock()
            window.confirm_action("⚠ Șterge fișierul")
            icon.assert_called_once_with("circle-alert", color="#e5bd69")
