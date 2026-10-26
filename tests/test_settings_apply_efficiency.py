"""Autosaving preferences should not repeatedly rebuild the whole interface."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


class SettingsApplyEfficiencyTests(unittest.TestCase):
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
        self.filename = Path(folder.name) / "config.json"
        self.filename.write_text(json.dumps({
            "microphone_enabled": False, "tts_enabled": False,
            "online_agent_enabled": False, "online_timeout": 60,
            "ui_theme": "dark", "ui_language": "ru",
        }), encoding="utf-8")
        patcher = mock.patch.object(main, "CONFIG", self.filename)
        patcher.start()
        self.addCleanup(patcher.stop)
        with (mock.patch("sounddevice.query_devices", return_value=[]),
              mock.patch.object(main.MainWindow, "_ocr_setup_worker")):
            self.window = main.MainWindow()
        self.addCleanup(self.window.close)

    def test_weather_and_api_timeout_save_without_appearance_or_language_rebuild(self):
        window = self.window
        panel = window.settings_panel
        with (mock.patch.object(window, "apply_appearance", wraps=window.apply_appearance) as appearance,
              mock.patch.object(window, "apply_ui_language", wraps=window.apply_ui_language) as language,
              mock.patch.object(window.commands_page, "refresh", wraps=window.commands_page.refresh) as commands):
            panel.weather_city.setText("Cahul")
            panel.flush_auto_save()
            panel.online_timeout.setValue(61)
            panel.flush_auto_save()
        saved = json.loads(self.filename.read_text(encoding="utf-8"))
        self.assertEqual(saved["weather_city"], "Cahul")
        self.assertEqual(saved["online_timeout"], 61)
        appearance.assert_not_called()
        language.assert_not_called()
        commands.assert_not_called()

    def test_theme_and_language_changes_still_apply_live(self):
        window = self.window
        panel = window.settings_panel
        window.show_page(4)
        with (mock.patch.object(window, "apply_appearance", wraps=window.apply_appearance) as appearance,
              mock.patch.object(window, "apply_ui_language", wraps=window.apply_ui_language) as language):
            panel.theme.setCurrentIndex(panel.theme.findData("light"))
            panel.flush_auto_save()
            appearance.assert_called_once_with()
            language.assert_not_called()
            appearance.reset_mock()
            panel.ui_language.setCurrentIndex(panel.ui_language.findData("ro"))
            panel.flush_auto_save()
            language.assert_called_once_with()
            appearance.assert_not_called()
        saved = json.loads(self.filename.read_text(encoding="utf-8"))
        self.assertEqual(saved["ui_theme"], "light")
        self.assertEqual(saved["ui_language"], "ro")
        self.assertIn("Setări", window.header_title.text())

    def test_unchanged_appearance_does_not_repolish_all_application_widgets(self):
        with mock.patch.object(self.app, "setStyleSheet", wraps=self.app.setStyleSheet) as setter:
            self.window.apply_appearance()
            self.window.apply_appearance()
        setter.assert_not_called()

    def test_theme_refresh_updates_open_dialog_icons_without_closed_window_traversal(self):
        import main
        from PySide6.QtWidgets import QDialog, QPushButton
        from luxai.icons import set_button_icon
        opened, closed = QDialog(), QDialog()
        self.addCleanup(opened.close)
        self.addCleanup(closed.close)
        button = QPushButton("Test", opened)
        set_button_icon(button, "settings")
        previous = button.icon().cacheKey()
        opened.show()
        closed.hide()
        self.window.cfg["ui_theme"] = "light"
        with mock.patch.object(main, "refresh_icons", wraps=main.refresh_icons) as refresh:
            self.window.apply_appearance()
        refreshed = [call.args[0] for call in refresh.call_args_list]
        self.assertIn(opened, refreshed)
        self.assertNotIn(closed, refreshed)
        self.assertNotEqual(button.icon().cacheKey(), previous)


if __name__ == "__main__":
    unittest.main()
