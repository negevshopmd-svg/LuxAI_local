"""0.3.7d: protect draft API keys while preferences auto-save."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class SettingsAutoSave037dTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("PySide6 not installed")
        cls.app = QApplication.instance() or QApplication([])

    def window(self):
        import main
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        filename = Path(folder.name) / "config.json"
        filename.write_text(
            '{"microphone_enabled": false, "tts_enabled": false, '
            '"online_agent_enabled": false}', encoding="utf-8",
        )
        patcher = mock.patch.object(main, "CONFIG", filename)
        patcher.start()
        self.addCleanup(patcher.stop)
        with (mock.patch("sounddevice.query_devices", return_value=[]),
              mock.patch("main.MainWindow._ocr_setup_worker")):
            window = main.MainWindow()
        self.addCleanup(window.close)
        return window, filename

    def test_no_save_button_and_unrelated_edit_does_not_save_draft_key(self):
        import main
        from PySide6.QtWidgets import QPushButton
        window, filename = self.window()
        window.show_page(4)
        panel = window.settings_panel
        self.assertFalse(any(
            "Сохранить настройки" in button.text()
            for button in panel.findChildren(QPushButton)
        ))
        panel.api_key_entry.setText("not-yet-finished-secret")
        panel.weather_city.setText("Bălți")
        with mock.patch.object(main, "store_api_key") as storage:
            panel.flush_auto_save()
        storage.assert_not_called()
        self.assertEqual(
            json.loads(filename.read_text(encoding="utf-8"))["weather_city"], "Bălți"
        )
        self.assertEqual(panel.api_key_entry.text(), "not-yet-finished-secret")

    def test_api_key_persists_when_editing_finishes(self):
        import main
        window, _ = self.window()
        panel = window.settings_panel
        panel.api_key_entry.setText("complete-secret")
        self.assertFalse(panel._autosave_timer.isActive())
        with (
            mock.patch.object(main, "store_api_key") as store,
            mock.patch.object(main, "get_api_key", return_value="complete-secret"),
        ):
            panel.api_key_entry.editingFinished.emit()
            self.assertTrue(panel._autosave_timer.isActive())
            panel.flush_auto_save()
        store.assert_called_once_with(
            "complete-secret", panel.online_provider.currentData()
        )
        self.assertEqual(panel.api_key_entry.text(), "")
        self.assertFalse(panel._autosave_timer.isActive())

    def test_an_explicit_successful_api_check_can_store_key_draft(self):
        import main
        window, _ = self.window()
        panel = window.settings_panel
        panel.api_key_entry.setText("verified-secret")
        self.assertEqual(panel.api_key_ready_for_save(), "")
        with (
            mock.patch.object(main, "store_api_key") as store,
            mock.patch.object(main, "get_api_key", return_value="verified-secret"),
        ):
            self.assertTrue(window.save_settings(allow_api_key=True))
        store.assert_called_once_with(
            "verified-secret", panel.online_provider.currentData()
        )
        self.assertFalse(panel.api_key_entry.text())

    def test_auto_saved_settings_reappear_on_a_new_window(self):
        first, filename = self.window()
        first.settings_panel.weather_city.setText("Orhei")
        first.settings_panel.flush_auto_save()
        self.assertEqual(json.loads(filename.read_text(encoding="utf-8"))["weather_city"], "Orhei")
        first.close()
        with (mock.patch("sounddevice.query_devices", return_value=[]),
              mock.patch("main.MainWindow._ocr_setup_worker")):
            reopened = __import__("main").MainWindow()
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.settings_panel.weather_city.text(), "Orhei")


if __name__ == "__main__":
    unittest.main()
