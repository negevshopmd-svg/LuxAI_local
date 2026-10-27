"""A newly accepted verb form must still delimit a compound app request."""
import unittest
from unittest import mock

from luxai.agent import LocalAgent
from luxai.task_intents import direct_app_request, opening_app


class RomanianCompoundInflectionTests(unittest.TestCase):
    def test_action_inflections_cannot_become_part_of_an_application_name(self):
        for continuation in (
            "închizi Firefox", "inchizi Firefox", "lansezi War Thunder",
            "salvezi fișierul", "salvează documentul", "scrii Salut",
            "tastează Salut", "oprești jocul", "citești ecranul",
            "aștepți 2 secunde", "muți cursorul la 10,20",
            "reglezi volumul la 50", "derulezi în jos",
        ):
            for conjunction in ("și", "si"):
                phrase = f"Deschide Discord {conjunction} {continuation}"
                with self.subTest(phrase=phrase):
                    self.assertIsNone(direct_app_request(phrase))
                    self.assertEqual(opening_app(phrase), "discord")

    def test_action_words_inside_single_application_names_keep_their_name(self):
        for phrase, target in (
            ("Open Mount and Blade", "mount and blade"),
            ("Deschide aplicația Muți", "muți"),
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(direct_app_request(phrase), target)


class FastAppRequestBoundaryTests(unittest.TestCase):
    def test_negative_howto_quoted_and_compound_requests_never_launch_a_partial_app(self):
        phrases = (
            "Nu deschide Discord", "Do not open Discord", "Не открывай Discord",
            "Cum să deschid Discord?", "Explain how to open Discord", "Объясни как открыть Discord",
            'Spune-i lui Hanzo: deschide Discord', 'Tell Hanzo: open Discord',
            'Напиши Hanzo: открой Discord', '"Open Discord"',
            "Deschide Discord și salvezi fișierul", "Open Discord and click Settings",
            "Открой Discord и нажми настройки", "Nu deschide Notepad",
            "Do not open calculator", "Не открой проводник", "How to open browser?",
        )
        agent = LocalAgent({"response_language": "ro"})
        with mock.patch.object(agent, "_open_application") as application, mock.patch(
            "luxai.agent.subprocess.Popen",
        ) as process, mock.patch("luxai.agent.webbrowser.open") as browser:
            for phrase in phrases:
                with self.subTest(phrase=phrase):
                    self.assertIsNone(agent.handle_fast(phrase, confirm_callback=lambda _: True))
            application.assert_not_called()
            process.assert_not_called()
            browser.assert_not_called()

    def test_legacy_app_aliases_and_exact_system_apps_still_open_locally(self):
        agent = LocalAgent({"response_language": "ro"})
        with mock.patch.object(agent, "_open_application", return_value=True) as application:
            for phrase, target in (
                ("Открой телегу", "telegram"), ("Poți să deschizi Discord?", "discord"),
                ("Please open Microsoft Word", "word"), ("Запусти Firefox", "firefox"),
            ):
                with self.subTest(phrase=phrase):
                    self.assertIsNotNone(agent.handle_fast(phrase, confirm_callback=lambda _: True))
                    application.assert_called_with(target)
        with mock.patch("luxai.agent.subprocess.Popen") as process:
            for phrase, executable in (
                ("Poți să deschizi Notepad?", "notepad.exe"),
                ("Could you open Calculator?", "calc.exe"),
                ("Пожалуйста открой Проводник", "explorer.exe"),
            ):
                with self.subTest(phrase=phrase):
                    self.assertIsNotNone(agent.handle_fast(phrase, confirm_callback=lambda _: True))
                    process.assert_called_with([executable])


if __name__ == "__main__":
    unittest.main()
