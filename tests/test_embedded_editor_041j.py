"""0.4.1j The command editor opens inside the Commands page, not a new window."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

import main
from luxai import command_registry


class EmbeddedEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.folder = tempfile.TemporaryDirectory()
        base = Path(cls.folder.name)
        (base / "config.json").write_text(json.dumps({
            "microphone_enabled": False, "tts_enabled": False, "online_agent_enabled": False,
            "ui_animations": False, "minimize_to_tray": False, "ui_language": "ru",
            "local_llm_fallback_enabled": False}), encoding="utf-8")
        cls.patches = [mock.patch.object(main, "CONFIG", base / "config.json"),
                       mock.patch.object(command_registry, "REGISTRY_FILE", base / "commands.json")]
        for patch in cls.patches:
            patch.start()
        with (mock.patch("sounddevice.query_devices", return_value=[]),
              mock.patch.object(main.MainWindow, "_ocr_setup_worker"),
              mock.patch.object(main.MainWindow, "_startup_ai_checks")):
            cls.window = main.MainWindow()
        cls.window.resize(1100, 700)
        cls.window.show()
        cls.app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.window._quitting = True
        cls.window.close()
        cls.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        for patch in reversed(cls.patches):
            patch.stop()
        cls.folder.cleanup()

    def test_new_command_is_embedded_with_header_and_back(self):
        window, page = self.window, self.window.commands_page
        window.show_page(1)
        editor = page.new_command()
        self.app.processEvents()
        self.assertFalse(editor.isWindow())  # not a separate window
        self.assertIs(page.views.currentWidget(), editor)
        self.assertIn("Команды   |   Новая команда", window.header_title.text())
        self.assertTrue(window.window_header.back_button.isVisible())
        self.assertFalse(any(widget.isVisible() for widget in editor._header_widgets))
        window._header_back()  # header arrow = Cancel
        self.app.processEvents()
        self.assertIsNone(page.editor)
        self.assertIs(page.views.currentWidget(), page.library_view)
        self.assertNotIn("Новая команда", window.header_title.text())
        self.assertFalse(window.window_header.back_button.isVisible())

    def test_saving_inside_the_page_stores_the_command(self):
        page = self.window.commands_page
        self.window.show_page(1)
        editor = page.new_command()
        editor.title_field.setText("Встроенный редактор")
        editor.phrase_chips.add_value("встроенный редактор тест") if hasattr(editor.phrase_chips, "add_value") \
            else editor.phrase_field.setText("встроенный редактор тест")
        with mock.patch.object(editor, "get_data", return_value={
                "title": "Встроенный редактор", "action": "time", "phrases": ["встроенный редактор тест"]}):
            editor.accept()
        self.app.processEvents()
        self.assertIsNone(page.editor)
        titles = [entry["title"] for entry in page.registry.entries()]
        self.assertIn("Встроенный редактор", titles)


if __name__ == "__main__":
    unittest.main()
