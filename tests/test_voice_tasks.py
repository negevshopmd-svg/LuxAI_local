"""Voice websites, actual Windows Desktop files, low-friction confirmations,
and newly available shortcut actions in the conversational command wizard.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from luxai.websites import website_plan, open_website
from luxai.voice_files import parse_open_user_file, resolve_named_file, open_user_file
from luxai.voice_shortcuts import keyboard_action_plan, command_capabilities_reply
from luxai.action_catalog import validate_step
from luxai.command_registry import CommandRegistry
from luxai.command_wizard import CommandWizard
from luxai.online_agent import OnlinePlanner


class AdultNavigationTests(unittest.TestCase):
    def test_adult_site_including_russian_whisper_variants_is_https_navigation(self):
        for phrase in (
            "Открой порно-хам.", "Откроет порно-хам.", "Открой Порнхаб", "Открой порно хаб",
            "Жарвис, открой порнхаб в браузере", "Open Pornhub",
            "Открой сайт Pornhub.com",
        ):
            with self.subTest(phrase=phrase):
                p = website_plan(phrase)
                self.assertIsNotNone(p)
                self.assertEqual(p["action"], "open_site")
                self.assertEqual(p["target"], "https://www.pornhub.com/")
        cloud = OnlinePlanner._validate({
            "action": "open_site", "target": "порнхаб", "reply": "",
        })
        self.assertIsNotNone(cloud)
        self.assertEqual(cloud["target"], "https://www.pornhub.com/")

    def test_real_browser_handoff_is_not_a_false_prohibition(self):
        with mock.patch("luxai.websites.webbrowser.open", return_value=True) as open_browser:
            ok, message = open_website("порно-хам")
        self.assertTrue(ok)
        self.assertIn("Отправил браузеру", message)
        open_browser.assert_called_once_with("https://www.pornhub.com/", new=2)


class DesktopFileTests(unittest.TestCase):
    def test_russian_file_requests_and_location(self):
        phrases = {
            "Открой файл Отчёт.docx на рабочем столе": ("Отчёт.docx", "desktop"),
            "Откроет файл Отчёт.docx на десктопе": ("Отчёт.docx", "desktop"),
            "Открой файл «Мой отчёт.pdf» с рабочего стола.": ("Мой отчёт.pdf", "desktop"),
            "Открой документ Резюме в документах": ("Резюме", "documents"),
            "Открой файл Лекции.mp4 в загрузках": ("Лекции.mp4", "downloads"),
            "Жарвис, открой документ Notes в Ворде": ("Notes", "desktop"),
            "Открой папку Работа на рабочем столе": ("Работа", "desktop"),
        }
        for phrase, expected in phrases.items():
            with self.subTest(phrase=phrase):
                value = parse_open_user_file(phrase)
                self.assertIsNotNone(value)
                self.assertEqual((value["target"], value["location"]), expected)

    def test_not_an_open_file_request(self):
        for phrase in (
            "Открой проводник", "Открой Word", "Открой YouTube",
            "Какие файлы на рабочем столе?", "Создай файл Мой отчёт.txt",
            "Открой файл ../secret", "Открой файл C:\\Windows\\system.ini",
        ):
            self.assertIsNone(parse_open_user_file(phrase), phrase)

    def test_unique_stem_and_exact_filename(self):
        with tempfile.TemporaryDirectory() as temp:
            desktop = Path(temp) / "Desktop"
            desktop.mkdir()
            (desktop / "Мой отчёт.docx").write_bytes(b"WORD")
            (desktop / "Обзор.pdf").write_bytes(b"PDF")
            (desktop / "Изображение.png").write_bytes(b"PNG")
            self.assertEqual(
                resolve_named_file("Мой отчёт", home=Path(temp)).name,
                "Мой отчёт.docx",
            )
            self.assertEqual(
                resolve_named_file("ОБЗОР.PDF", home=Path(temp)).name,
                "Обзор.pdf",
            )
            (desktop / "Мой отчёт.pdf").write_bytes(b"PDF")
            with self.assertRaisesRegex(ValueError, "несколько файлов"):
                resolve_named_file("Мой отчёт", home=Path(temp))
            with self.assertRaises(FileNotFoundError):
                resolve_named_file("Не существует", home=Path(temp))

    def test_routine_document_open_uses_windows_not_explorer_or_gemini(self):
        with tempfile.TemporaryDirectory() as temp:
            desktop = Path(temp) / "Desktop"
            desktop.mkdir()
            document = desktop / "Отчёт.docx"
            document.write_bytes(b"DOCUMENT")
            deny_callback = mock.Mock(side_effect=AssertionError("No prompts for documents"))
            with mock.patch("luxai.voice_files.sys.platform", "win32"), mock.patch(
                "luxai.voice_files.os.startfile", create=True,
            ) as open_windows:
                success, answer = open_user_file(
                    "Отчёт.docx", confirm=deny_callback, home=Path(temp),
                )
            self.assertTrue(success)
            self.assertIn("Отчёт.docx", answer)
            open_windows.assert_called_once_with(str(document))
            deny_callback.assert_not_called()

    def test_executables_and_scripts_require_approval_even_if_prompts_off(self):
        with tempfile.TemporaryDirectory() as temp:
            desktop = Path(temp) / "Desktop"
            desktop.mkdir()
            (desktop / "Install.cmd").write_bytes(b"echo arbitrary")
            prompts = []
            with mock.patch("luxai.voice_files.sys.platform", "win32"), mock.patch(
                "luxai.voice_files.os.startfile", create=True,
            ) as open_windows:
                success, answer = open_user_file(
                    "Install.cmd", confirm=lambda prompt: prompts.append(prompt) or False,
                    home=Path(temp),
                )
            self.assertFalse(success)
            self.assertIn("отменён", answer)
            self.assertIn("⚠", prompts[0])
            open_windows.assert_not_called()

    def test_action_editor_accepts_safe_named_file_without_path(self):
        item = validate_step({
            "action": "open_user_file", "target": "Отчёт.docx",
            "location": "desktop",
        })
        self.assertEqual(item["target"], "Отчёт.docx")
        for invalid in ("../../log.txt", "C:\\system.ini", "path/file.txt", ""):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    validate_step({
                        "action": "open_user_file", "target": invalid,
                        "location": "desktop",
                    })
        with self.assertRaises(ValueError):
            validate_step({
                "action": "open_user_file", "target": "File.txt",
                "location": "system32",
            })


class KeyboardAndWizardTests(unittest.TestCase):
    def test_enter_and_saved_hotkeys_are_recognized(self):
        choices = {
            "Нажми Enter": ("press_enter", ""),
            "Жарвис, нажми клавишу энтер.": ("press_enter", ""),
            "Нажми Ctrl+S": ("hotkey", "ctrl+s"),
            "Нажми контрол эс": ("hotkey", "ctrl+s"),
            "Сохрани": ("save_document", ""),
        }
        for phrase, (action, target) in choices.items():
            with self.subTest(phrase=phrase):
                plan = keyboard_action_plan(phrase)
                self.assertIsNotNone(plan)
                self.assertEqual((plan["action"], plan["target"]), (action, target))
                validate_step(plan)
        self.assertIsNone(keyboard_action_plan("Поздравь меня"))
        self.assertIsNone(keyboard_action_plan("Нажми ctrl+alt+delete"))

    def test_capabilities_reflect_real_command_catalog(self):
        for message in ("Что ты умеешь делать?", "Жарвис, какие у тебя команды?"):
            answer = command_capabilities_reply(message)
            self.assertIsNotNone(answer)
            self.assertIn("Enter", answer)
            self.assertIn("рабочего стола", answer)
            self.assertIn("Новая команда", answer)
        self.assertIsNone(command_capabilities_reply("привет"))
        answer = command_capabilities_reply(
            "У тебя есть команда чтобы нажать Enter?"
        )
        self.assertIsNotNone(answer)
        self.assertIn("Нажать Enter", answer)

    def test_voice_wizard_can_save_new_enter_shortcut_and_open_file(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = CommandRegistry(path=Path(temp) / "commands.json")
            wizard = CommandWizard(registry)
            self.assertIn("фразу", wizard.start())
            wizard.feed("теперь подтвердить")
            prompt, online, _ = wizard.feed("Нажми Enter")
            self.assertIsNone(online)
            self.assertIn("Enter", prompt)
            result, _, saved = wizard.feed("да")
            self.assertIsNotNone(saved)
            self.assertEqual(saved["steps"][0]["action"], "press_enter")
            self.assertIsNotNone(registry.match("теперь подтвердить"))
            self.assertIn("Готово", result)

            wizard.start()
            wizard.feed("открой мой отчёт")
            answer, online, _ = wizard.feed("Открой файл Отчёт.docx на рабочем столе")
            self.assertIsNone(online)
            self.assertIn("Отчёт.docx", answer)
            wizard.feed("да")
            saved_file = registry.match("открой мой отчёт")
            self.assertEqual(saved_file["steps"][0]["action"], "open_user_file")
            self.assertEqual(saved_file["steps"][0]["target"], "Отчёт.docx")

    def test_voice_wizard_can_save_website_shortcut_without_cloud(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = CommandRegistry(path=Path(temp) / "commands.json")
            wizard = CommandWizard(registry)
            wizard.start()
            wizard.feed("мой канал")
            message, request, saved = wizard.feed("Открой YouTube в браузере")
            self.assertIsNone(request)
            self.assertIsNone(saved)
            self.assertIn("youtube.com", message)
            wizard.feed("да")
            record = registry.match("мой канал")
            self.assertEqual(record["steps"][0]["action"], "open_website")
            self.assertEqual(record["steps"][0]["target"], "https://www.youtube.com/")


if __name__ == "__main__":
    unittest.main()
