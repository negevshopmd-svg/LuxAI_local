"""UI roles and application-owned copy follow RU/RO/EN without editing data."""
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication, QLabel

from luxai.ui_i18n import chat_author, get_ui_language, is_user_author, set_ui_language, tr


class InterfaceLocalization038aTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import main
        self.addCleanup(set_ui_language, get_ui_language())
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        config = Path(folder.name) / "config.json"
        config.write_text(json.dumps({
            "microphone_enabled": False, "tts_enabled": False,
            "online_agent_enabled": False, "ui_language": "ru",
            "language": "ro", "response_language": "en",
            "ui_theme": "dark", "ui_animations": False,
            "llm_model_path": "",
        }), encoding="utf-8")
        patcher = mock.patch.object(main, "CONFIG", config)
        patcher.start()
        self.addCleanup(patcher.stop)
        with (mock.patch("sounddevice.query_devices", return_value=[]),
              mock.patch.object(main.MainWindow, "_ocr_setup_worker")):
            self.window = main.MainWindow()
        self.addCleanup(self.window.close)

    def choose_language(self, language):
        panel = self.window.settings_panel
        panel.ui_language.setCurrentIndex(panel.ui_language.findData(language))
        panel.flush_auto_save()

    def test_real_voice_handler_uses_russian_role_with_romanian_recognition(self):
        window = self.window
        phrase = "Salut <b>Hanzo</b>, не меняй текст & numele."
        with mock.patch.object(window, "run_command") as run:
            window.handle_voice(phrase)
        run.assert_called_once_with(phrase)
        self.assertEqual(window.history[-1], ("Tu (voce)", phrase))
        for log in (window.log, window.home_history):
            self.assertIn("Вы (голос)", log.toPlainText())
            self.assertNotIn("Tu (voce)", log.toPlainText())
            self.assertIn(phrase, log.toPlainText())
            self.assertIn("&lt;b&gt;Hanzo&lt;/b&gt;", log.toHtml())

    def test_existing_history_roles_switch_live_while_data_and_input_stay_unchanged(self):
        window = self.window
        voice = "Salvează <documentul> & păstrează Русский."
        window.append_message("Tu (voce)", voice, "#79a6ff")
        window.append_message("Tu", "My exact typed message", "#79a6ff")
        window.append_message("Jarvis", "Ответ остаётся на выбранном языке ответа.", "#a5b9dc")
        original = list(window.history)
        window.command.setText("Ciornă не переводить")
        window.command.setCursorPosition(8)
        for language, voice_author, text_author in (
            ("en", "You (voice)", "You:"),
            ("ro", "Tu (voce)", "Tu:"),
            ("ru", "Вы (голос)", "Вы:"),
        ):
            with self.subTest(language=language):
                self.choose_language(language)
                self.assertEqual(window.history, original)
                self.assertIn(voice_author, window.log.toPlainText())
                self.assertIn(text_author, window.log.toPlainText())
                self.assertIn(voice_author, window.home_history.toPlainText())
                self.assertIn(voice, window.log.toPlainText())
                self.assertEqual(window.command.text(), "Ciornă не переводить")
                self.assertEqual(window.command.cursorPosition(), 8)
                self.assertEqual(window.cfg["language"], "ro")
                self.assertEqual(window.cfg["response_language"], "en")
        self.assertNotIn("Tu (voce)", window.log.toPlainText())

    def test_static_home_and_settings_labels_do_not_leak_russian_into_english_or_romanian(self):
        window = self.window
        for language in ("en", "ro"):
            self.choose_language(language)
            leaked = []
            for root in (window.home_page, window.settings_panel):
                for label in root.findChildren(QLabel):
                    if re.search(r"[А-Яа-яЁё]", label.text()):
                        leaked.append(label.text())
            self.assertEqual(leaked, [], (language, leaked))

    def test_legacy_model_health_source_has_localized_copy_in_all_ui_languages(self):
        source = "No model selected or model file missing. Place a .gguf in models/."
        self.assertIn("Модель не выбрана", tr(source, "ru"))
        self.assertEqual(tr(source, "en"), source)
        self.assertIn("Nu este selectat", tr(source, "ro"))
        self.assertEqual(tr("my arbitrary model-file.gguf", "ru"), "my arbitrary model-file.gguf")
        for language in ("en", "ro", "ru"):
            self.choose_language(language)
            health = self.window.settings_panel.model_health.text()
            self.assertEqual(health, tr(source, language))

    def test_author_roles_translate_only_exact_application_labels(self):
        for language, expected in (("ru", "Вы (голос)"), ("en", "You (voice)"), ("ro", "Tu (voce)")):
            self.assertEqual(chat_author("Tu (voce)", language), expected)
        for author in ("Jarvis", "TuMann", "<b>Tu</b>", "My saved name"):
            self.assertFalse(is_user_author(author))
            self.assertEqual(chat_author(author, "ru"), author)

    def test_command_library_translates_builtin_titles_but_preserves_named_user_commands(self):
        from luxai.ui_commands import CommandsPage
        records = [
            {"id": "builtin", "title": "Блокнот", "category": "Приложения", "builtin": True,
             "action": "open_app", "enabled": True, "phrases": ["открой блокнот"]},
            {"id": "personal", "title": "Блокнот", "category": "Мои команды", "builtin": False,
             "action": "open_app", "enabled": True, "phrases": ["my exact phrase"]},
        ]
        registry = mock.Mock(custom=[records[1]])
        registry.entries.return_value = records
        page = CommandsPage(registry)
        self.addCleanup(page.close)
        for language, builtin in (("en", "Notepad"), ("ro", "Notepad"), ("ru", "Блокнот")):
            page.interface_language = language
            page.refresh()
            first = page.tree.topLevelItem(0).child(0)
            personal = page.tree.topLevelItem(1).child(0)
            self.assertEqual(first.text(0), builtin)
            self.assertEqual(personal.text(0), "Блокнот")
            self.assertEqual(first.toolTip(0), "открой блокнот")
            self.assertEqual(personal.toolTip(0), "my exact phrase")

    def test_action_dialog_units_follow_language_without_changing_the_saved_action(self):
        from luxai.ui_action_picker import ActionOptionsDialog
        for language, minutes, steps in (("en", " min", " steps"),
                                         ("ro", " min", " pași"),
                                         ("ru", " мин", " шага")):
            set_ui_language(language)
            for action, suffix in (("wait_minutes", minutes), ("mouse_scroll", steps)):
                with self.subTest(language=language, action=action):
                    dialog = ActionOptionsDialog(action, {"target": "3"})
                    self.addCleanup(dialog.close)
                    self.assertEqual(dialog.target.suffix(), suffix)
                    dialog._accept()
                    self.assertEqual(dialog.data["action"], action)
                    self.assertEqual(dialog.data["target"], "3")

    def test_confirmation_and_screen_dialogs_follow_ui_instead_of_recognition_language(self):
        import main
        window = self.window
        window.cfg["confirm_all_actions"] = True
        buttons = main.QMessageBox.StandardButton
        screenshot_path = Path("/tmp/example.png")
        description = 'echo "<b>keep exact</b>" & numele'
        observed = "Nu traduce <b>этот текст</b> & test."
        for language, confirmation, yes, screenshot, screen_text in (
            ("ru", "Подтвердите действие", "Да", "Снимок экрана", "Текст на экране"),
            ("en", "Confirm action", "Yes", "Screenshot", "On-screen text"),
            ("ro", "Confirmă acțiunea", "Da", "Captură de ecran", "Textul de pe ecran"),
        ):
            with self.subTest(language=language):
                self.choose_language(language)
                dialog = mock.Mock()
                dialog.exec.return_value = buttons.No
                factory = mock.Mock(return_value=dialog)
                factory.StandardButton = buttons
                with (mock.patch.object(main, "QMessageBox", factory),
                      mock.patch.object(main.QTimer, "singleShot")):
                    self.assertFalse(window.confirm_action("⚠ " + description))
                dialog.setWindowTitle.assert_called_once_with(confirmation)
                self.assertIn(description, dialog.setText.call_args.args[0])
                dialog.button(buttons.Yes).setText.assert_any_call(yes)
                self.assertIsNone(window.pending_confirmation_dialog)
                with (mock.patch.object(main, "capture_screen", return_value=screenshot_path),
                      mock.patch.object(main.QMessageBox, "information") as notify):
                    window.screen_action()
                self.assertEqual(notify.call_args.args[1], screenshot)
                self.assertIn(str(screenshot_path), notify.call_args.args[2])
                ocr_dialog = mock.Mock()
                factory = mock.Mock(return_value=ocr_dialog)
                factory.StandardButton = buttons
                with (mock.patch.object(main, "capture_screen", return_value=screenshot_path),
                      mock.patch.object(main, "read_screen_text", return_value=observed),
                      mock.patch.object(main, "QMessageBox", factory)):
                    window.ocr_action()
                ocr_dialog.setWindowTitle.assert_called_once_with(screen_text)
                ocr_dialog.setText.assert_called_once_with(observed)
                self.assertEqual(window.history[-1], ("OCR", observed))


if __name__ == "__main__":
    unittest.main()
