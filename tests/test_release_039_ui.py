"""Navigation preferences persist without altering settings or screen actions."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from luxai.ui_i18n import get_ui_language, set_ui_language, tr


class Release039UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import main
        self.main = main
        self.addCleanup(set_ui_language, get_ui_language())
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.config = Path(folder.name) / "config.json"
        self.initial = {
            "microphone_enabled": False, "tts_enabled": False,
            "online_agent_enabled": False, "ui_language": "ru",
            "language": "ro", "response_language": "en",
            "ui_theme": "dark", "ui_animations": False,
            "llm_model_path": "", "personal_extension": {"keep": 42},
        }
        patcher = mock.patch.object(main, "CONFIG", self.config)
        patcher.start()
        self.addCleanup(patcher.stop)

    def window(self, collapsed):
        self.config.write_text(json.dumps({**self.initial, "ui_sidebar_collapsed": collapsed}), encoding="utf-8")
        with (mock.patch("sounddevice.query_devices", return_value=[]),
              mock.patch.object(self.main.MainWindow, "_ocr_setup_worker")):
            window = self.main.MainWindow()
        self.addCleanup(window.close)
        return window

    def test_saved_sidebar_state_restores_without_initial_config_save(self):
        for collapsed in (True, False):
            with self.subTest(collapsed=collapsed):
                with mock.patch.object(self.main, "save_config", wraps=self.main.save_config) as save:
                    window = self.window(collapsed)
                    self.app.processEvents()
                    self.assertEqual(window.sidebar.width(), 76 if collapsed else 177)
                    save.assert_not_called()
                window.close()

    def test_user_toggle_persists_only_sidebar_preference_and_survives_restart(self):
        window = self.window(False)
        window.show()
        self.app.processEvents()
        window.settings_panel.api_key_entry.setText("unfinished-private-draft")
        with (mock.patch.object(window, "save_settings") as settings,
              mock.patch.object(self.main, "store_api_key") as store):
            QTest.mouseClick(window.sidebar.collapse, Qt.MouseButton.LeftButton)
            settings.assert_not_called()
            store.assert_not_called()
        saved = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertIs(saved["ui_sidebar_collapsed"], True)
        for key, value in self.initial.items():
            self.assertEqual(saved[key], value, key)
        self.assertNotIn("unfinished-private-draft", self.config.read_text(encoding="utf-8"))
        self.assertEqual(window.settings_panel.api_key_entry.text(), "unfinished-private-draft")
        window.settings_panel.api_key_entry.clear()
        window.close()
        with (mock.patch("sounddevice.query_devices", return_value=[]),
              mock.patch.object(self.main.MainWindow, "_ocr_setup_worker")):
            reopened = self.main.MainWindow()
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.sidebar.width(), 76)
        self.assertIs(reopened.cfg["ui_sidebar_collapsed"], True)

    def test_failed_sidebar_save_restores_previous_ui_and_settings(self):
        window = self.window(True)
        previous = self.config.read_bytes()
        with mock.patch.object(self.main, "save_config", side_effect=OSError("read only")):
            window.sidebar.toggle_collapsed()
        self.assertEqual(window.sidebar.width(), 76)
        self.assertIs(window.cfg["ui_sidebar_collapsed"], True)
        self.assertEqual(self.config.read_bytes(), previous)

    def test_addons_omits_screenshot_ocr_cards_but_screen_handlers_remain(self):
        window = self.window(False)
        addons = window.pages.widget(2)
        for language in ("ru", "en", "ro"):
            with self.subTest(language=language):
                panel = window.settings_panel
                panel.ui_language.setCurrentIndex(panel.ui_language.findData(language))
                panel.flush_auto_save()
                labels = {label.text() for label in addons.findChildren(QLabel)}
                self.assertNotIn(tr("Снимок экрана", language), labels)
                self.assertNotIn(tr("Распознавание текста (OCR)", language), labels)
                self.assertNotIn(tr("Выбрать локальную AI-модель", language), labels)
                self.assertIn(window.local_ai_indicator, addons.findChildren(QLabel))
                self.assertTrue(hasattr(window.settings_panel, "model_select"))
                self.assertTrue(callable(window.pick_model))
                self.assertTrue(callable(window.screen_action))
                self.assertTrue(callable(window.ocr_action))


if __name__ == "__main__":
    unittest.main()
