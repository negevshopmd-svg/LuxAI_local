"""Production page navigation and read-only local AI placement stay connected."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

import main
from luxai import command_registry
from luxai.ui_i18n import get_ui_language, set_ui_language


class Release093dIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.language = get_ui_language()
        cls.folder = tempfile.TemporaryDirectory()
        cls.base = Path(cls.folder.name)
        config = cls.base / "config.json"
        config.write_text(json.dumps({
            "microphone_enabled": False, "tts_enabled": False,
            "online_agent_enabled": False, "ui_animations": False,
            "minimize_to_tray": False, "ui_language": "ru",
            "local_llm_fallback_enabled": True, "llm_model_path": "",
        }), encoding="utf-8")
        cls.config_patch = mock.patch.object(main, "CONFIG", config)
        cls.registry_patch = mock.patch.object(command_registry, "REGISTRY_FILE", cls.base / "commands.json")
        cls.config_patch.start()
        cls.registry_patch.start()
        with (mock.patch("sounddevice.query_devices", return_value=[]),
              mock.patch.object(main.MainWindow, "_ocr_setup_worker")):
            cls.window = main.MainWindow()
        cls.window.resize(1000, 700)
        cls.window.show()
        cls.app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.window._quitting = True
        cls.window.close()
        assert cls.window._local_ai_monitor._closed
        cls.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        cls.registry_patch.stop()
        cls.config_patch.stop()
        cls.folder.cleanup()
        set_ui_language(cls.language)

    def test_agent_empty_state_opens_real_chat_page(self):
        window = self.window
        window.show_page(1)
        window.commands_page.agent_tab.click()
        self.app.processEvents()
        self.assertTrue(window.commands_page.agent_tab.isChecked())
        self.assertTrue(window.commands_page.open_chat_button.isVisible())
        window.commands_page.open_chat_button.click()
        self.assertEqual(window.pages.currentIndex(), 3)

    def test_addons_has_read_only_local_status_and_settings_keeps_model_selection(self):
        window = self.window
        window.show_page(2)
        deadline = time.monotonic() + 3
        while window._local_ai_monitor.current.state == "checking" and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertEqual(window._local_ai_monitor.current.state, "no_model")
        buttons = window.pages.widget(2).findChildren(QPushButton)
        self.assertEqual(buttons, [window.cloud_check_button])
        self.assertTrue(window.local_ai_indicator.isVisible())
        self.assertTrue(hasattr(window.settings_panel, "model_select"))
        self.assertIn(".gguf", window.local_ai_details.text())

    def test_local_status_retranslates_without_changing_voice_language(self):
        window = self.window
        voice_language = window.cfg.get("language")
        window.cfg["ui_language"] = "ro"
        window.apply_ui_language()
        window.show_page(2)
        self.app.processEvents()
        self.assertIn("AI local", window.local_ai_indicator.text())
        self.assertFalse(any("А" <= char <= "я" for char in window.local_ai_details.text()))
        self.assertEqual(window.cfg.get("language"), voice_language)


if __name__ == "__main__":
    unittest.main()
