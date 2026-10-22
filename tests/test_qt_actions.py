"""Offscreen PySide6 smoke tests for command editor and action picker."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QDialog
except ImportError:
    QApplication = None
else:
    # Missing application dependencies must FAIL tests rather than be silently
    # misreported as "PySide6 not installed".
    from luxai.ui_action_picker import ActionOptionsDialog, ActionPicker
    from luxai.ui_command_editor import CommandEditor
    from luxai.ui_commands import CommandsPage
    from luxai.command_registry import CommandRegistry


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class QtActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_main_dispatch_routes_unknown_voice_action_to_gemini_before_local(self):
        import types
        from unittest import mock
        from main import MainWindow

        record = {"parts": ["Открой Firefox"], "answers": [], "routes": []}
        fake = types.SimpleNamespace(
            _processing=False, _closed=False, _command_queue=[record],
            cfg={"language": "ru", "online_provider": "gemini", "wake_prefix": "Jarvis"},
            command_registry=types.SimpleNamespace(
                disabled_match=lambda text, prefix: False,
                match=lambda text, prefix: None,
            ),
            agent=types.SimpleNamespace(
                handle_fast=mock.Mock(return_value="WRONG LOCAL"),
                history=[],
            ),
            online_planner=types.SimpleNamespace(
                enabled=lambda: True,
            ),
            mic_status=types.SimpleNamespace(setText=mock.Mock()),
            _online_thread=lambda *_: None,
            _resolved_command=mock.Mock(),
        )
        with mock.patch("main.threading.Thread") as thread:
            MainWindow._dispatch_command(fake)
        self.assertEqual(fake._active_text, "Открой Firefox")
        self.assertEqual(fake._processing, True)
        fake.agent.handle_fast.assert_not_called()
        fake._resolved_command.assert_not_called()
        thread.assert_called_once()
        self.assertIn("JarvisCloudFirst", str(thread.call_args))
        self.assertIn("онлайн-планировщик", fake.mic_status.setText.call_args.args[0])

    def test_main_dispatch_does_not_use_gguf_to_claim_failed_file_operation(self):
        import types
        from unittest import mock
        from main import MainWindow

        fake = types.SimpleNamespace(
            _processing=False, _closed=False,
            _command_queue=[{"parts": ["Переименуй этот файл"], "answers": [], "routes": []}],
            cfg={"language": "ru", "online_provider": "gemini", "wake_prefix": "Jarvis"},
            command_registry=types.SimpleNamespace(
                disabled_match=lambda *_: False,
                match=lambda *_: None,
            ),
            agent=types.SimpleNamespace(
                handle_fast=mock.Mock(return_value=None),
                history=[],
            ),
            online_planner=types.SimpleNamespace(enabled=lambda: False),
            mic_status=types.SimpleNamespace(setText=mock.Mock()),
            _resolved_command=mock.Mock(),
            _start_local_chat=mock.Mock(),
        )
        import types as pytypes
        fake._safe_local_fallback = pytypes.MethodType(MainWindow._safe_local_fallback, fake)
        MainWindow._dispatch_command(fake)
        fake._start_local_chat.assert_not_called()
        fake._resolved_command.assert_called_once()
        self.assertIn("Системное действие НЕ выполнено", fake._resolved_command.call_args.args[1])

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

    def test_terminal_actions_have_explicit_parameter_dialog(self):
        picker = ActionPicker()
        picker.category_list.setCurrentRow(1)
        self.assertIn("run_cmd", picker._buttons)
        self.assertTrue(picker._buttons["run_cmd"].isEnabled())
        self.assertTrue(picker._buttons["run_powershell"].isEnabled())
        picker._choose_action("run_cmd")
        self.assertTrue(picker.add_button.isEnabled())
        editor = ActionOptionsDialog("run_cmd")
        editor.target.setText("echo hello")
        editor._accept()
        self.assertEqual(editor.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(editor.data["target"], "echo hello")
        editor.close()
        picker.close()

    def test_action_tiles_keep_title_description_in_separate_rows(self):
        from PySide6.QtWidgets import QLabel
        from PySide6.QtCore import Qt
        picker = ActionPicker()
        self.assertTrue(bool(picker.windowFlags() & Qt.WindowType.FramelessWindowHint))
        picker.show()
        QApplication.processEvents()
        picker.category_list.setCurrentRow(1)
        QApplication.processEvents()
        tile = picker._buttons["run_cmd"]
        title = tile.findChild(QLabel, "TileTitle")
        description = tile.findChild(QLabel, "TileDescription")
        self.assertIsNotNone(title)
        self.assertIsNotNone(description)
        self.assertGreaterEqual(description.geometry().top(), title.geometry().bottom())
        self.assertGreaterEqual(tile.height(), 70)
        picker.close()

    def test_parameter_dialog_validates_website(self):
        config = ActionOptionsDialog("open_website")
        config.target.setText("https://www.wikipedia.org/")
        config._accept()
        self.assertEqual(config.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(config.data["target"], "https://www.wikipedia.org/")

    def test_action_configuration_dialogs_cover_recently_enabled_options(self):
        for action in (
            "run_cmd", "run_powershell", "wait_minutes", "mouse_hold",
            "mouse_right_hold", "app_volume", "voice_female", "voice_male",
            "play_mp3", "play_wav", "run_file", "open_first_result",
            "monitor_on", "monitor_off", "sleep_pc", "tray_minimize",
        ):
            with self.subTest(action=action):
                dialog = ActionOptionsDialog(action)
                self.assertEqual(dialog.windowTitle(), "Настроить действие")
                self.assertTrue(dialog.isEnabled())
                dialog.close()

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
