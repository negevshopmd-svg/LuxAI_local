"""Editing older saved actions preserves them until explicit replacement."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication, QDialog

from luxai.command_registry import CommandRegistry, checked_command
from luxai.ui_command_editor import CommandEditor
from luxai.ui_i18n import get_ui_language, set_ui_language


class LegacyEditor093cTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        language = get_ui_language()
        set_ui_language("ru")
        self.addCleanup(set_ui_language, language)

    def editor(self, command):
        editor = CommandEditor(command)
        self.addCleanup(editor.close)
        return editor

    def legacy(self):
        return checked_command({
            "id": "learned_special", "title": "My special game", "category": "Games",
            "action": "steam_verified", "target": "Special game", "appid": 1234,
            "phrases": ["launch special"], "enabled": True, "learned": True,
        })

    def test_time_builtin_can_change_title_and_phrases_then_save_without_action_loss(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = CommandRegistry(Path(folder) / "commands.json")
            original = next(entry for entry in registry.entries() if entry["action"] == "time")
            editor = self.editor(original)
            self.assertFalse(editor._legacy)
            editor.title_field.setText("My time command")
            editor.phrase_field.setText("personal time phrase")
            self.assertTrue(editor.save_button.isEnabled())
            saved = registry.save_command(editor.get_data())
            registry.reload()
            reopened = next(entry for entry in registry.entries() if entry["id"] == original["id"])
            self.assertEqual(reopened, saved)
            self.assertEqual(saved["action"], "time")
            self.assertEqual(saved["title"], "My time command")
            self.assertIn("personal time phrase", saved["phrases"])

    def test_cancel_replacement_keeps_legacy_appid_and_updated_title_phrases(self):
        editor = self.editor(self.legacy())
        editor.title_field.setText("Renamed special")
        editor.phrase_field.setText("new game phrase")
        before = checked_command(editor.get_data())
        with mock.patch("luxai.ui_command_editor.ActionPicker") as picker_class:
            picker_class.return_value.exec.return_value = QDialog.DialogCode.Rejected
            editor.replace_action_button.click()
        self.assertTrue(editor._legacy)
        self.assertEqual(checked_command(editor.get_data()), before)
        self.assertEqual(editor.get_data()["appid"], 1234)
        self.assertFalse(editor.add_button.isEnabled())
        self.assertTrue(editor.save_button.isEnabled())

    def test_accepted_replacement_becomes_validated_macro_and_enables_editing(self):
        editor = self.editor(self.legacy())
        replacement = {"action": "open_app", "target": "telegram"}
        with mock.patch("luxai.ui_command_editor.ActionPicker") as picker_class:
            picker = picker_class.return_value
            picker.exec.return_value = QDialog.DialogCode.Accepted
            picker.step = replacement
            editor.replace_action_button.click()
        self.assertFalse(editor._legacy)
        self.assertTrue(editor.legacy_panel.isHidden())
        self.assertTrue(editor.add_button.isEnabled())
        self.assertTrue(editor.record_button.isEnabled())
        self.assertTrue(editor.ai_button.isEnabled())
        self.assertTrue(editor.save_button.isEnabled())
        payload = checked_command(editor.get_data())
        self.assertEqual(payload["steps"], [{
            "action": "open_app", "target": "telegram", "location": "desktop"}])
        self.assertEqual(payload["action"], "open_app")
        self.assertIsNone(payload["appid"])
        self.assertEqual(payload["title"], "My special game")
        editor.save_button.click()
        self.assertEqual(editor.result(), QDialog.DialogCode.Accepted)

    def test_invalid_picker_replacement_preserves_original_action(self):
        editor = self.editor(self.legacy())
        before = checked_command(editor.get_data())
        with mock.patch("luxai.ui_command_editor.ActionPicker") as picker_class:
            picker = picker_class.return_value
            picker.exec.return_value = QDialog.DialogCode.Accepted
            picker.step = {"action": "powershell", "target": "unsafe"}
            editor.replace_action_button.click()
        self.assertTrue(editor._legacy)
        self.assertEqual(checked_command(editor.get_data()), before)
        self.assertTrue(editor.save_button.isEnabled())
        self.assertFalse(editor.action_feedback.isHidden())


if __name__ == "__main__":
    unittest.main()
