"""Offscreen PySide6 smoke tests for command editor and action picker."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QDialog
    from luxai.ui_action_picker import ActionOptionsDialog, ActionPicker
    from luxai.ui_command_editor import CommandEditor
    from luxai.ui_commands import CommandsPage
    from luxai.command_registry import CommandRegistry
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class QtActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_picker_opens_and_filters_categories(self):
        picker = ActionPicker()
        self.assertEqual(picker.windowTitle(), "Добавить действие")
        self.assertEqual(picker.category_list.count(), 10)
        self.assertIn("open_app", picker._buttons)
        picker.category_list.setCurrentRow(2)
        self.assertIn("type_text", picker._buttons)
        self.assertNotIn("open_website", picker._buttons)
        picker.search.setText("Enter")
        self.assertIn("press_enter", picker._buttons)
        picker.close()

    def test_sensitive_actions_are_disabled_in_palette(self):
        picker = ActionPicker()
        picker.category_list.setCurrentRow(1)
        self.assertIn("run_cmd", picker._buttons)
        self.assertFalse(picker._buttons["run_cmd"].isEnabled())
        self.assertFalse(picker._buttons["run_powershell"].isEnabled())
        picker._choose_action("open_website")
        self.assertTrue(picker.add_button.isEnabled())
        picker.close()

    def test_parameter_dialog_validates_website(self):
        config = ActionOptionsDialog("open_website")
        config.target.setText("https://www.wikipedia.org/")
        config._accept()
        self.assertEqual(config.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(config.data["target"], "https://www.wikipedia.org/")

    def test_editor_lists_and_moves_selected_actions(self):
        dialog = CommandEditor()
        self.assertEqual(dialog.actions_list.count(), 0)
        dialog.title_field.setText("Мой набор")
        dialog.phrase_field.setText("запусти рабочий набор")
        dialog.steps = [
            {"action": "open_app", "target": "telegram", "location": "desktop"},
            {"action": "wait_seconds", "target": "2", "location": "desktop"},
        ]
        dialog._refresh_steps(1)
        dialog.move_action(-1)
        self.assertEqual(dialog.steps[0]["action"], "wait_seconds")
        dialog._validate_accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(len(dialog.get_data()["steps"]), 2)

    def test_library_uses_new_visual_editor_and_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = CommandRegistry(Path(directory) / "commands.json")
            view = CommandsPage(registry)
            self.assertGreater(view.tree.topLevelItemCount(), 0)
            self.assertTrue(hasattr(view, "new_command"))
            self.assertGreaterEqual(view.tree.topLevelItem(0).childCount(), 1)
            view.close()


if __name__ == "__main__":
    unittest.main()
