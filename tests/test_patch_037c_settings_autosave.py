"""0.3.7c: automatic Settings persistence, without a Save button."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class SettingsAutoSaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("PySide6 not available")
        cls.app = QApplication.instance() or QApplication([])

    def settings(self, saved=None):
        from PySide6.QtWidgets import QPushButton
        from luxai.settings_panel import SettingsPanel
        calls = []
        panel = SettingsPanel(
            {"microphone_enabled": False, "voice_volume": 80, **(saved or {})},
            on_save=lambda: calls.append(panel.collect()),
            on_pick_model=lambda: None,
            on_test_voice=lambda: None,
        )
        self.addCleanup(panel.close)
        return panel, calls

    def test_no_save_button_and_no_initial_autosave(self):
        from PySide6.QtWidgets import QPushButton
        panel, calls = self.settings()
        self.assertFalse(any("Сохранить настройки" in w.text()
                             for w in panel.findChildren(QPushButton)))
        self.assertFalse(panel._autosave_timer.isActive())
        panel.flush_auto_save()
        self.assertEqual(calls, [])

    def test_multiple_controls_debounce_as_one_saved_snapshot(self):
        panel, calls = self.settings()
        panel.animations.setChecked(not panel.animations.isChecked())
        panel.voice_volume.setValue(61)
        panel.weather_city.setText("Bălți")
        self.assertTrue(panel._autosave_timer.isActive())
        panel.flush_auto_save()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["voice_volume"], 61)
        self.assertEqual(calls[0]["weather_city"], "Bălți")
        self.assertFalse(panel._autosave_timer.isActive())
        panel.flush_auto_save()
        self.assertEqual(len(calls), 1)

    def test_search_and_live_diagnostics_do_not_trigger_save(self):
        panel, calls = self.settings()
        panel.search.setText("микрофон")
        panel.audio_level.setValue(55)
        panel.audio_feedback.setText("Уровень проверен")
        self.assertFalse(panel._autosave_timer.isActive())
        panel.flush_auto_save()
        self.assertEqual(calls, [])

    def test_api_secret_not_saved_per_keypress_but_committed_after_editing(self):
        panel, calls = self.settings()
        panel.api_key_entry.setText("sk-example-key")
        self.assertFalse(panel._autosave_timer.isActive())
        panel.api_key_entry.editingFinished.emit()
        self.assertTrue(panel._autosave_timer.isActive())
        panel.flush_auto_save()
        self.assertEqual(len(calls), 1)
        self.assertNotIn("api_key", calls[0])

    def test_failed_save_remains_dirty_and_can_be_retried(self):
        from luxai.settings_panel import SettingsPanel
        called = []
        panel = SettingsPanel(
            {"microphone_enabled": False},
            on_save=lambda: called.append(1) or (False if len(called) == 1 else True),
            on_pick_model=lambda: None, on_test_voice=lambda: None,
        )
        self.addCleanup(panel.close)
        panel.animations.setChecked(False)
        panel.flush_auto_save()
        self.assertEqual(len(called), 1)
        panel._queue_auto_save()
        panel.flush_auto_save()
        self.assertEqual(len(called), 2)

    def window(self):
        import main
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        filename = Path(temp.name) / "config.json"
        filename.write_text(
            '{"microphone_enabled":false,"tts_enabled":false,'
            '"online_agent_enabled":false}', encoding="utf-8",
        )
        p = mock.patch.object(main, "CONFIG", filename)
        p.start()
        self.addCleanup(p.stop)
        with (mock.patch("sounddevice.query_devices", return_value=[]),
              mock.patch("main.MainWindow._ocr_setup_worker")):
            window = main.MainWindow()
        self.addCleanup(window.close)
        return window, filename

    def test_main_applies_and_persists_settings_without_button(self):
        window, filename = self.window()
        window.show_page(4)
        panel = window.settings_panel
        panel.animations.setChecked(False)
        panel.weather_city.setText("Orhei")
        panel.flush_auto_save()
        disk = json.loads(filename.read_text(encoding="utf-8"))
        self.assertEqual(disk["weather_city"], "Orhei")
        self.assertFalse(disk["ui_animations"])
        self.assertFalse(window.cfg["ui_animations"])
        self.assertFalse(panel._autosave_timer.isActive())

    def test_leaving_settings_flushes_debounce_and_does_not_double_save(self):
        import main
        window, filename = self.window()
        window.show_page(4)
        panel = window.settings_panel
        panel.weather_city.setText("Cahul")
        self.assertTrue(panel._autosave_timer.isActive())
        with mock.patch.object(main, "save_config", wraps=main.save_config) as save:
            window.show_page(0)
        self.assertEqual(save.call_count, 1)
        self.assertEqual(json.loads(filename.read_text(encoding="utf-8"))["weather_city"], "Cahul")
        self.assertFalse(panel._autosave_timer.isActive())

    def test_close_flushes_last_pending_edit(self):
        window, filename = self.window()
        panel = window.settings_panel
        panel.weather_city.setText("Soroca")
        self.assertTrue(panel._autosave_timer.isActive())
        window.close()
        self.assertEqual(json.loads(filename.read_text(encoding="utf-8"))["weather_city"], "Soroca")


if __name__ == "__main__":
    unittest.main()
