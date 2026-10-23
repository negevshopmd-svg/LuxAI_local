"""Regression checks for spoken file targets, real renames and reply language."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from luxai.agent import LocalAgent
from luxai.file_actions import create_user_item, parse_file_intent, rename_user_item
from luxai.online_agent import OnlinePlanner
from luxai.voice_files import parse_open_user_file


class SpokenFileTargetTests(unittest.TestCase):
    def test_cloud_file_location_survives_validation_and_execution(self):
        for location in ("desktop", "documents", "downloads"):
            with self.subTest(location=location):
                plan = OnlinePlanner._validate({
                    "action": "open_user_file", "target": "report.pdf",
                    "location": location, "reply": "",
                })
                self.assertEqual(plan["location"], location)
                confirm = mock.Mock()
                agent = LocalAgent({"language": "en"})
                with mock.patch("luxai.agent.open_user_file", return_value=(True, "Opened")) as opened:
                    agent.execute_plan("open my report", plan, confirm)
                opened.assert_called_once_with("report.pdf", location, confirm=confirm)
                self.assertTrue(agent.last_execution_success)

    def test_open_placement_is_removed_in_all_supported_languages(self):
        cases = {
            "open file report.pdf in documents": ("report.pdf", "documents"),
            "open file report.pdf from the Downloads folder": ("report.pdf", "downloads"),
            "open file report.pdf on the desktop": ("report.pdf", "desktop"),
            "deschide fișierul raport.pdf din documente": ("raport.pdf", "documents"),
            "deschide fisierul raport.pdf din descarcari": ("raport.pdf", "downloads"),
            "deschide fișierul raport.pdf în descărcări": ("raport.pdf", "downloads"),
            "deschide fișierul raport.pdf de pe desktop": ("raport.pdf", "desktop"),
            "Открой файл Отчёт.pdf в папке Документы": ("Отчёт.pdf", "documents"),
            "Открой файл Отчёт.pdf из загрузок": ("Отчёт.pdf", "downloads"),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                result = parse_open_user_file(text)
                self.assertIsNotNone(result)
                self.assertEqual((result["target"], result["location"]), expected)

    def test_filename_words_do_not_select_another_directory(self):
        for name in ("Documents.pdf", "My downloads.txt", '"Notes in documents"'):
            with self.subTest(name=name):
                plan = parse_open_user_file("open file " + name)
                self.assertEqual(plan["location"], "desktop")
                self.assertEqual(plan["target"], name.strip('"'))

    def test_location_support_keeps_path_and_folder_allowlists(self):
        for target in ("../secret.txt", r"C:\Windows\system.ini", "subfolder/file.txt"):
            with self.subTest(target=target):
                self.assertIsNone(parse_open_user_file(f"open file {target} in documents"))
                self.assertIsNone(OnlinePlanner._validate({
                    "action": "open_user_file", "target": target,
                    "location": "documents", "reply": "",
                }))
        self.assertIsNone(OnlinePlanner._validate({
            "action": "open_user_file", "target": "report.pdf",
            "location": "system32", "reply": "",
        }))


class SpokenRenameTests(unittest.TestCase):
    def test_explicit_source_is_never_replaced_by_last_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            requested = create_user_item("create_file", "старый.txt", content="requested", home=home)
            previous = create_user_item("create_file", "last.txt", content="keep me", home=home)
            plan = parse_file_intent("Переименуй файл старый.txt в новый.txt")
            agent = LocalAgent({"language": "ru"})
            agent.last_file = {"name": previous.name, "location": "desktop"}

            def rename(source, destination, location):
                return rename_user_item(source, destination, location, home=home)

            confirm = mock.Mock(return_value=True)
            with mock.patch("luxai.agent.rename_user_item", side_effect=rename):
                agent.execute_plan("Переименуй файл старый.txt в новый.txt", plan, confirm)
            self.assertFalse(requested.exists())
            self.assertEqual((requested.parent / "новый.txt").read_text(), "requested")
            self.assertEqual(previous.read_text(), "keep me")
            self.assertIn("старый.txt", confirm.call_args.args[0])
            self.assertTrue(agent.last_execution_success)

    def test_named_rename_remains_subject_to_confirmation(self):
        agent = LocalAgent({"language": "en"})
        plan = parse_file_intent("rename file report.txt to notes.txt")
        self.assertEqual(plan["source"], "report.txt")
        with mock.patch("luxai.agent.rename_user_item") as rename:
            agent.execute_plan("rename file report.txt to notes.txt", plan, lambda _: False)
        rename.assert_not_called()
        self.assertFalse(agent.last_execution_success)

    def test_pronouns_still_require_real_last_item_context(self):
        for text in ("Переименуй его в заметки.txt", "rename it to notes.txt"):
            with self.subTest(text=text):
                plan = parse_file_intent(text)
                self.assertEqual(plan["source"], "@last")
                agent = LocalAgent({"language": "ru"})
                with mock.patch("luxai.agent.rename_user_item") as rename:
                    agent.execute_plan(text, plan, lambda _: True)
                rename.assert_not_called()
                self.assertFalse(agent.last_execution_success)

    def test_romanian_and_named_placement_preserve_source(self):
        cases = {
            "redenumește fișierul vechi.txt în nou.txt din documente": ("vechi.txt", "nou.txt", "documents"),
            'rename file "old report.txt" to "new report.txt" in downloads': ("old report.txt", "new report.txt", "downloads"),
            'rename file "how to read.txt" to "notes to keep.txt"': ("how to read.txt", "notes to keep.txt", "desktop"),
            "Переименуй файл старый.txt в новый.txt в документах": ("старый.txt", "новый.txt", "documents"),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                plan = parse_file_intent(text)
                self.assertIsNotNone(plan)
                self.assertEqual((plan["source"], plan["target"], plan["location"]), expected)

    def test_rename_rejects_paths_instead_of_falling_back_to_last(self):
        for text in (
            "rename file ../old.txt to new.txt",
            "rename file old.txt to subfolder/new.txt",
            r"rename file C:\old.txt to new.txt",
            "rename to new.txt",
        ):
            self.assertIsNone(parse_file_intent(text), text)


class SelectionSummaryLanguageTests(unittest.TestCase):
    def test_local_summary_obeys_configured_response_language(self):
        for language, expected in (("ro", "Romanian"), ("en", "English"), ("ru", "Russian")):
            with self.subTest(language=language):
                model = mock.Mock()
                model.create_chat_completion.return_value = {
                    "choices": [{"message": {"content": "Summary"}}],
                }
                agent = LocalAgent({"language": "ru", "response_language": language})
                with mock.patch.object(agent, "_load_llm", return_value=model):
                    self.assertEqual(agent.summarize_selection("Выделенный русский текст"), "Summary")
                messages = model.create_chat_completion.call_args.kwargs["messages"]
                self.assertIn(f"Always reply in {expected}.", messages[0]["content"])
                self.assertIn("Выделенный русский текст", messages[1]["content"])


if __name__ == "__main__":
    unittest.main()
