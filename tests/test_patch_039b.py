"""0.3.9b regressions: modal recorder, compact chat and contextual commands."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QDialog, QToolButton

from luxai.command_registry import CommandRegistry
from luxai.ui_chat_composer import ChatPromptEdit
from luxai.ui_command_editor import CommandEditor, RecordingOverlay
from luxai.ui_commands import CommandsPage


class Patch039bTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.registry = CommandRegistry(Path(self.temp.name) / "user_commands.json")
        self.registry.save_custom({
            "id": "user_test_039b", "title": "Test personal",
            "category": "Мои команды", "action": "time",
            "phrases": ["test personal command"], "enabled": True,
        })

    def test_modal_recording_overlay_buttons_are_clickable(self):
        overlay = RecordingOverlay()
        self.addCleanup(overlay.close)
        self.assertIsInstance(overlay, QDialog)
        self.assertEqual(overlay.windowModality(), Qt.WindowModality.ApplicationModal)
        stopped, cancelled = [], []
        overlay.stop_requested.connect(lambda: stopped.append(True))
        overlay.cancel_requested.connect(lambda: cancelled.append(True))
        overlay.show()
        self.app.processEvents()
        buttons = overlay.findChildren(__import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton)
        self.assertEqual(len(buttons), 2)
        self.assertTrue(all(button.isEnabled() for button in buttons))
        QTest.mouseClick(buttons[1], Qt.MouseButton.LeftButton)
        QTest.mouseClick(buttons[0], Qt.MouseButton.LeftButton)
        self.assertEqual(stopped, [True])
        self.assertEqual(cancelled, [True])

    def test_stop_button_restores_a_modal_command_editor(self):
        editor = CommandEditor()
        self.addCleanup(editor.close)
        editor.setWindowModality(Qt.WindowModality.ApplicationModal)
        editor.show()
        self.app.processEvents()
        with mock.patch("luxai.command_recording.ActionRecorder") as recorder_class:
            recorder = recorder_class.return_value
            recorder.start.return_value = True
            recorder.error = ""
            recorder.active = True
            recorder.stop.return_value = [{"action": "press_key", "target": "f2"}]
            editor.record_button.click()
            self.app.processEvents()
            overlay = editor._record_overlay
            self.assertIsNotNone(overlay)
            self.assertTrue(overlay.isVisible())
            buttons = overlay.findChildren(
                __import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton)
            QTest.mouseClick(buttons[1], Qt.MouseButton.LeftButton)
            self.app.processEvents()
            self.assertIsNone(editor._record_overlay)
            self.assertIsNone(editor._recorder)
            self.assertTrue(editor.isVisible())
            recorder.stop.assert_called_once()
            self.assertEqual(editor.steps[-1]["target"], "f2")

    def test_chat_prompt_is_multiline_and_enter_sends(self):
        edit = ChatPromptEdit()
        self.addCleanup(edit.close)
        sent = []
        edit.returnPressed.connect(lambda: sent.append(edit.text()))
        edit.setText("Start")
        QTest.keyClick(edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        QTest.keyClicks(edit, "next")
        self.assertIn("\nnext", edit.text())
        QTest.keyClick(edit, Qt.Key.Key_Return)
        self.assertEqual(sent, ["Start\nnext"])

    def test_tree_has_hover_actions_and_right_file_buttons(self):
        page = CommandsPage(self.registry)
        self.addCleanup(page.close)
        self.assertEqual(page.tree.topLevelItem(0).childCount() > 0, True)
        personal = page.tree.topLevelItem(1).child(0)
        self.assertEqual(personal.text(0), "Test personal")
        self.assertIsInstance(page.tree.itemWidget(personal, 3), QToolButton)
        self.assertTrue(page.import_button.isEnabled())
        self.assertTrue(page.export_button.isEnabled())
        self.assertFalse(page.edit.isVisible())
        self.assertFalse(page.remove.isVisible())

    def test_custom_groups_survive_registry_restart(self):
        self.registry.add_group("My shortcuts", "folders")
        self.registry.add_group("Daily", "collections")
        fresh = CommandRegistry(self.registry.path)
        self.assertIn("My shortcuts", fresh.groups["folders"])
        self.assertIn("Daily", fresh.groups["collections"])
        page = CommandsPage(fresh)
        self.addCleanup(page.close)
        names = [page.tree.topLevelItem(i).text(0)
                 for i in range(page.tree.topLevelItemCount())]
        self.assertIn("My shortcuts", names)
        self.assertIn("Daily", names)

    def test_json_import_is_inert_and_does_not_replace_existing_records(self):
        export = Path(self.temp.name) / "commands_export.json"
        payload = {"version": 1, "commands": [{
            "id": "override", "title": "Imported command",
            "action": "time", "phrases": ["imported test"], "enabled": True,
        }]}
        export.write_text(json.dumps(payload), encoding="utf-8")
        page = CommandsPage(self.registry)
        self.addCleanup(page.close)
        with mock.patch.object(QFileDialog, "getOpenFileName", return_value=(str(export), "JSON")):
            page.import_commands()
        self.assertEqual(len(self.registry.custom), 2)
        imported = next(item for item in self.registry.custom if item["title"] == "Imported command")
        self.assertFalse(imported["enabled"])
        self.assertNotEqual(imported["id"], "override")
        self.assertEqual(self.registry.custom[0]["id"], "user_test_039b")

    def test_editor_has_two_column_form_with_right_buttons(self):
        editor = CommandEditor()
        self.addCleanup(editor.close)
        self.assertFalse(editor.editor_nav.isVisible())
        self.assertIs(editor.save_button.parentWidget(), editor.sidebar)
        self.assertIs(editor.cancel_button.parentWidget(), editor.sidebar)


if __name__ == "__main__":
    unittest.main()
