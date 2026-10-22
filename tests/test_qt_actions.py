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


def _load_main_class_for_mock_tests():
    """Load UI routing without heavy microphone/screenshot libraries in CI."""
    import sys
    import types
    from unittest import mock

    voice = types.ModuleType("luxai.voice")
    voice.VoiceListener = object
    voice.speak = lambda *args, **kwargs: True
    screen = types.ModuleType("luxai.screen")
    screen.capture_screen = lambda: None
    screen.read_screen_text = lambda *args, **kwargs: ""
    voices = types.ModuleType("luxai.voices")
    voices.available_voices = lambda *args, **kwargs: []
    with mock.patch.dict(sys.modules, {
        "luxai.voice": voice,
        "luxai.screen": screen,
        "luxai.voices": voices,
    }):
        from main import MainWindow
    return MainWindow


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class QtActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_main_dispatch_routes_unknown_voice_action_to_gemini_before_local(self):
        import types
        from unittest import mock
        MainWindow = _load_main_class_for_mock_tests()

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
            confirm_action=lambda _message: False,
            _online_thread=lambda *_: None,
            _resolved_command=mock.Mock(),
        )
        with mock.patch.object(__import__("threading"), "Thread") as thread:
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
        MainWindow = _load_main_class_for_mock_tests()

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
            confirm_action=lambda _message: False,
            _resolved_command=mock.Mock(),
            _start_local_chat=mock.Mock(),
        )
        import types as pytypes
        fake._safe_local_fallback = pytypes.MethodType(MainWindow._safe_local_fallback, fake)
        MainWindow._dispatch_command(fake)
        fake._start_local_chat.assert_not_called()
        fake._resolved_command.assert_called_once()
        self.assertIn("Системное действие НЕ выполнено", fake._resolved_command.call_args.args[1])

    def test_weather_is_routed_to_direct_forecast_before_gemini(self):
        import types
        from unittest import mock
        MainWindow = _load_main_class_for_mock_tests()
        fake = types.SimpleNamespace(
            _processing=False, _closed=False,
            _command_queue=[{"parts": ["Какая погода завтра в Кишневе?"]}],
            cfg={"language": "ru", "wake_prefix": "Jarvis"},
            command_registry=types.SimpleNamespace(
                disabled_match=lambda *_: False,
                match=lambda *_: None,
            ),
            online_planner=types.SimpleNamespace(enabled=mock.Mock(side_effect=RuntimeError("Gemini must not be called"))),
            mic_status=types.SimpleNamespace(setText=mock.Mock()),
            _direct_task_worker=mock.Mock(),
            _resolved_command=mock.Mock(),
        )
        with mock.patch.object(__import__("threading"), "Thread") as thread:
            MainWindow._dispatch_command(fake)
        thread.assert_called_once()
        self.assertIn("JarvisWeather", str(thread.call_args))
        self.assertEqual(fake._active_text, "Какая погода завтра в Кишневе?")
        fake.online_planner.enabled.assert_not_called()
        fake._resolved_command.assert_not_called()

    def test_screen_read_routed_to_real_local_ocr_not_chat(self):
        import types
        from unittest import mock
        MainWindow = _load_main_class_for_mock_tests()
        fake = types.SimpleNamespace(
            _processing=False, _closed=False,
            _command_queue=[{"parts": ["Прочитай что написано на экране."]}],
            cfg={"language": "ru", "wake_prefix": "Jarvis"},
            command_registry=types.SimpleNamespace(
                disabled_match=lambda *_: False,
                match=lambda *_: None,
            ),
            online_planner=types.SimpleNamespace(enabled=mock.Mock(side_effect=RuntimeError("No Gemini"))),
            mic_status=types.SimpleNamespace(setText=mock.Mock()),
            _direct_task_worker=mock.Mock(),
            _resolved_command=mock.Mock(),
        )
        with mock.patch.object(__import__("threading"), "Thread") as thread:
            MainWindow._dispatch_command(fake)
        self.assertIn("JarvisScreenOCR", str(thread.call_args))
        fake.online_planner.enabled.assert_not_called()

    def test_dictation_switches_on_and_types_without_llm(self):
        import types
        from unittest import mock
        MainWindow = _load_main_class_for_mock_tests()
        fake = types.SimpleNamespace(
            dictation_active=False,
            command_wizard=types.SimpleNamespace(active=False),
            append_message=mock.Mock(),
            mic_status=types.SimpleNamespace(setText=mock.Mock()),
            isActiveWindow=lambda: False,
        )
        MainWindow.run_command(fake, "Теперь я тебе могу диктовать и ты будешь писать.")
        self.assertTrue(fake.dictation_active)
        send = mock.Mock()
        with mock.patch.dict(MainWindow._type_voice_chunk.__globals__, {"_type_unicode_windows": send}):
            MainWindow._type_voice_chunk(fake, "Привет друзья")
            send.assert_called_once_with("Привет друзья ")
            MainWindow._type_voice_chunk(fake, "Стоп.")
            self.assertFalse(fake.dictation_active)
            send.assert_called_once()

    def test_home_has_functional_screen_assist_entrypoint(self):
        from luxai.ui_home import HomePage
        home = HomePage({"voice_volume": 80})
        self.assertIsNotNone(home.screen_assist_button)
        self.assertTrue(home.screen_assist_button.isEnabled())
        self.assertIn("кнопки", home.screen_assist_button.text())
        home.close()

    def test_screen_preview_displays_buttons_and_emits_selection(self):
        import time
        from luxai.screen_interact import ScreenInspection, VisibleButton
        from luxai.ui_screen_assist import ScreenAssistDialog

        snapshot = ScreenInspection(
            hwnd=100, pid=4000, title="Test Dialog",
            buttons=(
                VisibleButton("Да", (15, 20, 85, 50)),
                VisibleButton("Нет", (100, 20, 180, 50)),
            ),
            captured=time.monotonic(),
        )
        dialog = ScreenAssistDialog(snapshot)
        self.assertIn("Test Dialog", dialog.details.text())
        self.assertTrue(dialog.yes_button.isEnabled())
        self.assertTrue(dialog.no_button.isEnabled())
        self.assertEqual(dialog.button_list.count(), 2)
        selected = []
        dialog.click_requested.connect(selected.append)
        dialog.yes_button.click()
        self.assertEqual(selected, ["yes"])
        dialog.close()

    def test_builtin_word_command_bypasses_cloud_even_when_gemini_connected(self):
        import types
        from unittest import mock
        MainWindow = _load_main_class_for_mock_tests()
        builtin = {
            "builtin": True,
            "action": "open_app",
            "target": "word",
            "location": "desktop",
            "enabled": True,
        }
        fake = types.SimpleNamespace(
            _processing=False, _closed=False,
            _command_queue=[{"parts": ["Открой Word"]}],
            cfg={"language": "ru", "wake_prefix": "Jarvis"},
            command_registry=types.SimpleNamespace(
                disabled_match=lambda *_: False,
                match=lambda *_: builtin,
            ),
            agent=types.SimpleNamespace(history=[]),
            online_planner=types.SimpleNamespace(
                enabled=mock.Mock(side_effect=AssertionError("Presets need no Gemini")),
            ),
            _execute_registered=mock.Mock(),
        )
        MainWindow._dispatch_command(fake)
        fake.online_planner.enabled.assert_not_called()
        fake._execute_registered.assert_called_once_with("Открой Word", builtin)

    def test_desktop_filename_dispatches_to_local_file_opener_not_explorer(self):
        import types
        from unittest import mock
        MainWindow = _load_main_class_for_mock_tests()
        fake = types.SimpleNamespace(
            _processing=False, _closed=False,
            _command_queue=[{"parts": ["Открой файл Отчёт.docx на рабочем столе"]}],
            cfg={"language": "ru", "wake_prefix": "Jarvis"},
            command_registry=types.SimpleNamespace(
                disabled_match=lambda *_: False,
                match=lambda *_: None,
            ),
            agent=types.SimpleNamespace(
                execute_plan=mock.Mock(
                    return_value="Передал Windows запрос открыть «Отчёт.docx»."
                ),
                history=[],
            ),
            online_planner=types.SimpleNamespace(
                enabled=mock.Mock(side_effect=RuntimeError("Gemini not needed")),
            ),
            confirm_action=lambda _: True,
            _resolved_command=mock.Mock(),
        )
        MainWindow._dispatch_command(fake)
        fake.online_planner.enabled.assert_not_called()
        fake.agent.execute_plan.assert_called_once()
        plan = fake.agent.execute_plan.call_args.args[1]
        self.assertEqual(plan["action"], "open_user_file")
        self.assertEqual(plan["target"], "Отчёт.docx")
        fake._resolved_command.assert_called_once()

    def test_old_config_true_does_not_trigger_prompts_for_normal_actions(self):
        import types
        from unittest import mock
        MainWindow = _load_main_class_for_mock_tests()
        fake = types.SimpleNamespace(
            cfg={"confirm_desktop_actions": True},
        )
        # ConfirmAction should return before constructing any modal Qt dialog
        # for ordinary requests. A legacy True must not enable prompt spam.
        with mock.patch.dict(
            MainWindow.confirm_action.__globals__,
            {"QMessageBox": mock.Mock(side_effect=AssertionError("Dialog spam"))},
        ):
            self.assertTrue(MainWindow.confirm_action(fake, "Запустить Word?"))
            self.assertTrue(MainWindow.confirm_action(fake, "Открыть YouTube?"))
            self.assertTrue(MainWindow.confirm_action(fake, "Создать файл Отчёт.txt"))

    def test_spoken_website_is_opened_without_gemini(self):
        import types
        from unittest import mock
        MainWindow = _load_main_class_for_mock_tests()
        fake = types.SimpleNamespace(
            _processing=False, _closed=False,
            _command_queue=[{"parts": ["Открой ютуб в браузере"]}],
            cfg={"language": "ru", "wake_prefix": "Jarvis"},
            command_registry=types.SimpleNamespace(
                disabled_match=lambda *_: False,
                match=lambda *_: None,
            ),
            agent=types.SimpleNamespace(
                execute_plan=mock.Mock(return_value="Отправил браузеру адрес HTTPS."),
                history=[],
            ),
            online_planner=types.SimpleNamespace(
                enabled=mock.Mock(side_effect=RuntimeError("Gemini not needed")),
            ),
            confirm_action=lambda *_: False,
            _resolved_command=mock.Mock(),
        )
        MainWindow._dispatch_command(fake)
        fake.online_planner.enabled.assert_not_called()
        fake.agent.execute_plan.assert_called_once()
        plan = fake.agent.execute_plan.call_args.args[1]
        self.assertEqual(plan["action"], "open_site")
        self.assertEqual(plan["target"], "https://www.youtube.com/")
        fake._resolved_command.assert_called_once()

    def test_direct_spoken_yes_starts_screen_inspection_without_gemini(self):
        import types
        from unittest import mock
        MainWindow = _load_main_class_for_mock_tests()
        fake = types.SimpleNamespace(
            _processing=False, _closed=False,
            _command_queue=[{"parts": ["Нажми да"]}],
            cfg={"language": "ru", "wake_prefix": "Jarvis"},
            command_registry=types.SimpleNamespace(
                disabled_match=lambda *_: False,
                match=lambda *_: None,
            ),
            agent=types.SimpleNamespace(history=[]),
            online_planner=types.SimpleNamespace(
                enabled=mock.Mock(side_effect=RuntimeError("Gemini not needed")),
            ),
            _screen_snapshot=None,
            _start_screen_inspection=mock.Mock(),
        )
        MainWindow._dispatch_command(fake)
        self.assertEqual(fake._pending_screen_click, "yes")
        fake._start_screen_inspection.assert_called_once_with("Нажми да")
        fake.online_planner.enabled.assert_not_called()

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
