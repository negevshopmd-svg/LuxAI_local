"""0.3.9a regressions for the Luxify-style composer and unlimited user macros."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QToolButton

from luxai.command_registry import BUILTINS, CommandRegistry, checked_command
from luxai.default_commands import BUILTINS as SHIPPED_DEFAULTS
from luxai.command_recording import RecordingBuffer
from luxai.ui_command_editor import CommandEditor, InfoButton
from luxai.ui_commands import CommandsPage
from luxai.ui_attachments import AttachmentTray


class Patch039aTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_default_library_is_separate_from_personal_entries(self):
        self.assertIs(BUILTINS, SHIPPED_DEFAULTS)
        with tempfile.TemporaryDirectory() as folder:
            registry = CommandRegistry(Path(folder) / "commands.json")
            registry.save_custom({
                "title": "Personal command", "id": "personal_command",
                "action": "time", "phrases": ["personal phrase"],
                "category": "Приложения", "enabled": True,
            })
            page = CommandsPage(registry)
            self.addCleanup(page.close)
            defaults = page.tree.topLevelItem(0)
            self.assertIn("Команды по умолчанию", defaults.text(0))
            self.assertGreater(defaults.childCount(), 0)
            personal = [
                page.tree.topLevelItem(i)
                for i in range(1, page.tree.topLevelItemCount())
            ]
            self.assertTrue(any(
                group.child(j).text(0) == "Personal command"
                for group in personal for j in range(group.childCount())
            ))

    def test_saved_macro_has_no_old_eight_action_ceiling(self):
        steps = [{"action": "wait_seconds", "target": "1", "location": "desktop"}
                 for _ in range(19)]
        data = checked_command({
            "id": "custom_many_steps", "title": "Many steps",
            "action": "wait_seconds", "voice_enabled": False,
            "phrases": [], "steps": steps,
        })
        self.assertEqual(len(data["steps"]), 19)
        editor = CommandEditor()
        self.addCleanup(editor.close)
        editor.title_field.setText("Many steps")
        editor.voice_enabled.setChecked(False)
        editor.steps = steps
        editor._refresh_steps()
        self.assertEqual(editor.counter.text(), "19")
        self.assertEqual(len(editor._validated_data()["steps"]), 19)
        self.assertTrue(editor.add_button.isEnabled())
        self.assertTrue(editor.record_button.isEnabled())

    def test_native_recording_can_continue_past_eight_steps(self):
        buffer = RecordingBuffer(max_actions=None, own_pid=-1)
        buffer.begin()
        for _ in range(20):
            buffer.record_key("f2", foreground_pid=1024)
        self.assertEqual(buffer.count, 20)
        self.assertTrue(buffer.active)
        self.assertEqual(len(buffer.stop()), 20)

    def test_composer_starts_compact_and_info_buttons_have_help(self):
        tray = AttachmentTray()
        self.addCleanup(tray.close)
        self.assertEqual(tray.add_button.text(), "+")
        self.assertFalse(tray.route_hint.isVisible())
        self.assertFalse(tray.remove_button.isVisible())
        editor = CommandEditor()
        self.addCleanup(editor.close)
        info_buttons = editor.findChildren(InfoButton)
        self.assertGreaterEqual(len(info_buttons), 3)
        self.assertTrue(all(button.toolTip() for button in info_buttons))
        self.assertTrue(all(isinstance(button, QToolButton) for button in info_buttons))


if __name__ == "__main__":
    unittest.main()
