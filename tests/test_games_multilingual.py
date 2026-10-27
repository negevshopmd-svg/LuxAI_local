"""Known-game commands have equivalent local meaning in RU, RO and EN."""
import unittest
from unittest import mock

from luxai.agent import LocalAgent
from luxai.steam_games import GAMES, local_game_intent, local_game_request, lookup_steam_game
from luxai.windows_apps import normalized_name
from luxai.windows_control import process_names_for_app


LAUNCH_VARIANTS = {
    "ro": [
        "Deschide War Thunder", "Jarvis, Deschidea, War Thunder.", "Pornește War Thunder",
        "Porneste War Thunder.", "Te rog deschide War Thunder", "Poți să deschizi War Thunder?",
        "Poti te rog sa pornesti War Thunder?", "Ai putea să lansezi War Thunder?",
        "Aș vrea să deschizi jocul War Thunder", "Vreau să pornești War Thunder",
        "Lansează jocul War Thunder", "Deschide-mi War Thunder", "Pornește War Thunder prin Steam",
        "Te rog frumos, deschide War Thunder", "Poți deschide War Thunder, te rog?",
    ],
    "ru": [
        "Открой War Thunder", "Запусти War Thunder", "Открыть War Thunder",
        "Пожалуйста запусти War Thunder", "Можешь открыть War Thunder?",
        "Можешь ты открыть игру War Thunder?", "Мог бы ты запустить War Thunder?",
        "Жарвис, включи War Thunder", "Не мог бы ты открыть War Thunder?",
        "Запускай War Thunder", "Открывай War Thunder", "Откроешь War Thunder?",
        "Можешь ли ты открыть War Thunder?", "Открой War Thunder через Steam",
        "Ты можешь запустить War Thunder, пожалуйста?",
    ],
    "en": [
        "Open War Thunder", "Start War Thunder", "Launch War Thunder", "Run War Thunder",
        "Play War Thunder", "Jarvis, open War Thunder.", "Please launch War Thunder",
        "Can you start War Thunder?", "Could you open War Thunder, please?",
        "Would you please launch the game War Thunder?", "Will you run War Thunder?",
        "Open the War Thunder", "Start War Thunder through Steam", "Launch 'War Thunder'",
        "Please open War Thunder now",
    ],
}

CLOSE_VARIANTS = {
    "ro": [
        "Închide War Thunder", "Inchide War Thunder", "Oprește War Thunder", "Opreste War Thunder",
        "Jarvis, închide War Thunder.", "Te rog închide War Thunder", "Poți să închizi War Thunder?",
        "Poti te rog sa opresti War Thunder?", "Ai putea să închizi War Thunder?",
        "Aș dori să închizi War Thunder", "Vreau să închizi jocul War Thunder",
        "Închide-mi War Thunder", "Oprește jocul War Thunder", "Închide War Thunder acum",
        "Te rog frumos, închide fereastra jocului War Thunder",
    ],
    "ru": [
        "Закрой War Thunder", "Закрыть War Thunder", "Закрывай War Thunder", "Выключи War Thunder",
        "Выключить War Thunder", "Останови War Thunder", "Заверши игру War Thunder",
        "Жарвис, закрой War Thunder.", "Пожалуйста закрой War Thunder", "Можешь закрыть War Thunder?",
        "Не мог бы ты закрыть War Thunder?", "Можешь ты закрыть окно War Thunder?",
        "Закроешь War Thunder?", "Закрой War Thunder сейчас", "Ты можешь закрыть War Thunder, пожалуйста?",
    ],
    "en": [
        "Close War Thunder", "Exit War Thunder", "Quit War Thunder", "Stop War Thunder",
        "Shut down War Thunder", "Jarvis, close War Thunder.", "Please close War Thunder",
        "Can you close War Thunder?", "Could you exit War Thunder, please?",
        "Would you please close the game War Thunder?", "Will you quit War Thunder?",
        "Close the window of War Thunder", "Close War Thunder window", "Close 'War Thunder'",
        "Please close War Thunder now",
    ],
}


class GameCommandCorpusTests(unittest.TestCase):
    def test_courtesy_after_game_action_keeps_exact_target_in_each_language(self):
        for action, phrases in (
            ("launch_game", ("Deschide, te rog, War Thunder", "Запусти пожалуйста War Thunder",
                             "Open, please, War Thunder")),
            ("close_app", ("Închide te rog War Thunder", "Закрой пожалуйста War Thunder",
                           "Close please War Thunder")),
        ):
            for phrase in phrases:
                with self.subTest(phrase=phrase):
                    self.assertEqual(local_game_request(phrase), {"action": action, "target": "warthunder"})
        for phrase in (
            "Nu închide te rog War Thunder", "Не закрывай пожалуйста War Thunder",
            "Do not close please War Thunder", 'Scrie "Închide te rog War Thunder"',
            'Type "Close please War Thunder"', 'Напиши "Закрой пожалуйста War Thunder"',
            "Închide te rog War Thunder și deschide Steam",
            "Закрой пожалуйста War Thunder и открой Steam",
            "Close please War Thunder and open Steam",
        ):
            with self.subTest(rejected=phrase):
                self.assertIsNone(local_game_request(phrase))

    def test_fifteen_launch_and_close_variants_in_each_language_have_same_plan(self):
        for variants, action in ((LAUNCH_VARIANTS, "launch_game"), (CLOSE_VARIANTS, "close_app")):
            for language, phrases in variants.items():
                self.assertEqual(len(phrases), 15)
                for phrase in phrases:
                    with self.subTest(language=language, phrase=phrase):
                        self.assertEqual(local_game_request(phrase), {"action": action, "target": "warthunder"})
                        self.assertEqual(local_game_intent(phrase), "warthunder" if action == "launch_game" else None)

    def test_variants_execute_same_local_steam_id_or_exact_native_close(self):
        for language in LAUNCH_VARIANTS:
            agent = LocalAgent({"response_language": language})
            with mock.patch("luxai.agent.launch_steam_game", return_value=True) as launch, mock.patch(
                "luxai.agent.close_installed_app", return_value=(True, "Native verified close"),
            ) as close, mock.patch("luxai.agent.launch_installed_app") as app:
                for phrase in LAUNCH_VARIANTS[language]:
                    reply = agent.handle_fast(phrase, confirm_callback=lambda _: True)
                    self.assertIn("Steam", reply)
                    self.assertTrue(agent.last_execution_success)
                    self.assertEqual(agent.last_app, "warthunder")
                self.assertEqual(launch.call_args_list, [mock.call(236390)] * 15)
                launch.reset_mock()
                for phrase in CLOSE_VARIANTS[language]:
                    self.assertEqual(agent.handle_fast(phrase, confirm_callback=lambda _: True), "Native verified close")
                    self.assertTrue(agent.last_execution_success)
                self.assertEqual(close.call_count, 15)
                for call in close.call_args_list:
                    self.assertEqual(call.args, ("warthunder",))
                    self.assertEqual(call.kwargs["language"], language)
                launch.assert_not_called()
                app.assert_not_called()

    def test_negative_howto_messages_unknown_games_and_compounds_are_not_partial_game_commands(self):
        phrases = [
            "Nu deschide War Thunder", "Nu închide War Thunder", "Nu vreau să pornești War Thunder",
            "Cum să deschid War Thunder?", "Cum pot închide War Thunder?", "Nu poți închide War Thunder?",
            "Scrie-i lui Hanzo în Discord deschide War Thunder", "Spune-mi cum să închid War Thunder",
            "Deschide War Thunder și închide Steam", "Închide War Thunder apoi deschide Discord",
            "Не открывай War Thunder", "Не закрывай War Thunder", "Как открыть War Thunder?",
            "Скажи как закрыть War Thunder", "Напиши Hanzo: закрой War Thunder",
            "Открой War Thunder и скажи мой ник", "Закрой War Thunder и открой Discord",
            "Don't open War Thunder", "Do not close War Thunder", "How to start War Thunder?",
            "Tell me how to close War Thunder", "Send Hanzo the message: close War Thunder",
            '"Open War Thunder"', "Start War Thunder and click Settings", "Close War Thunder then open Steam",
            "Open War Thunder Helper", "Close War Thunder Wiki", "Open an unknown game",
        ]
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertIsNone(local_game_request(phrase))

    def test_asr_aliases_keep_same_game_binary_and_official_steam_id(self):
        for alias in ("War Thunder", "war tander", "war tunder", "war-thunder", "warthunder", "вар тандер", "вартандер"):
            with self.subTest(alias=alias):
                self.assertEqual(normalized_name(alias), "warthunder")
                self.assertEqual(process_names_for_app(alias), {"aces.exe"})
                self.assertEqual(lookup_steam_game(alias), GAMES["warthunder"])

    def test_native_launch_decline_does_not_execute_or_remember_success(self):
        agent = LocalAgent({"response_language": "ro"})
        with mock.patch("luxai.agent.launch_steam_game") as launch:
            answer = agent.handle_fast("Pornește War Thunder", confirm_callback=lambda _: False)
        launch.assert_not_called()
        self.assertFalse(agent.last_execution_success)
        self.assertIn("anulată", answer)

    def test_rejected_game_requests_cannot_degrade_into_partial_steam_actions(self):
        agent = LocalAgent({"response_language": "ro"})
        phrases = [
            "Deschide War Thunder și închide Steam", "Închide War Thunder apoi deschide Steam",
            "Cum să deschid War Thunder prin Steam?", "Nu deschide War Thunder prin Steam",
            "Не открывай War Thunder через Steam", "Как открыть War Thunder через Steam?",
            "Закрой War Thunder и запусти Steam", "Открой War Thunder и закрой Steam",
            "How to open War Thunder through Steam?", "Don't open War Thunder through Steam",
            "Close War Thunder then open Steam", "Start War Thunder and close Steam",
            "Send Hanzo the message: open War Thunder through Steam",
        ]
        with mock.patch("luxai.agent.launch_steam_game") as game, mock.patch.object(
            agent, "_open_application",
        ) as app, mock.patch("luxai.agent.close_installed_app") as close, mock.patch(
            "luxai.agent.launch_installed_app",
        ) as native:
            for phrase in phrases:
                with self.subTest(phrase=phrase):
                    self.assertIsNone(agent.handle_fast(phrase, confirm_callback=lambda _: True))
            game.assert_not_called()
            app.assert_not_called()
            close.assert_not_called()
            native.assert_not_called()


if __name__ == "__main__":
    unittest.main()
