"""Offline-safe routing tests. Run: python -m unittest discover -s tests -v"""
import re
import sys
import types
import unittest
from unittest import mock

# Unit tests of text routing do not require screen-capture libraries.
sys.modules.setdefault(
    "luxai.screen",
    types.SimpleNamespace(
        capture_screen=lambda: None,
        read_screen_text=lambda *args, **kwargs: "",
    ),
)

from luxai.agent import LocalAgent
from luxai.online_agent import OnlinePlanner
from luxai.steam_games import local_game_intent, lookup_steam_game


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.agent = LocalAgent({"language": "ru", "online_agent_enabled": False})

    def test_russian_time_whisper_variation(self):
        for phrase in ("Сколько время?", "Сколько времени?", "Который час?"):
            answer = self.agent.handle_fast(phrase, confirm_callback=lambda _: False)
            self.assertRegex(answer, r"Сейчас \d{2}:\d{2}")

    def test_dota_offline_intent(self):
        for command in ("Открой Доту", "Запусти Dota 2", "Жарвис, открой Дота 2"):
            self.assertEqual(local_game_intent(command), "dota2")
        with mock.patch("luxai.agent.launch_steam_game", return_value=True) as launch:
            response = self.agent.handle_fast("Открой Доту", confirm_callback=lambda _: True)
        self.assertIn("Dota 2", response)
        launch.assert_called_once_with(570)

    def test_dota_confirmation_required(self):
        with mock.patch("luxai.agent.launch_steam_game") as launch:
            response = self.agent.handle_fast("Открой Доту", confirm_callback=lambda _: False)
        self.assertIn("отменено", response.lower())
        launch.assert_not_called()

    def test_unknown_cloud_targets_cannot_run_cmd(self):
        invalid = [
            {"action": "open_app", "target": "cmd", "reply": ""},
            {"action": "launch_game", "target": "steam://rungameid/570", "reply": ""},
            {"action": "open_app", "target": "powershell", "reply": ""},
            {"action": "launch_game", "target": "rm -rf", "reply": ""},
        ]
        for proposal in invalid:
            self.assertIsNone(OnlinePlanner._validate(proposal))
            result = self.agent.execute_plan("Открой программу", proposal, lambda _: True)
            self.assertFalse(self.agent.last_execution_success)
            self.assertTrue(
                result is None or "Некорректное" in result,
                f"Rejected proposal incorrectly marked executable: {proposal}",
            )

    def test_cloud_reply_safe(self):
        plan = {"action": "reply", "target": "", "reply": "Слушаю."}
        self.assertEqual(self.agent.execute_plan("Привет", plan), "Слушаю.")

    def test_steam_api_invalid_name_no_request(self):
        with mock.patch("luxai.steam_games.urllib.request.urlopen") as req:
            self.assertIsNone(lookup_steam_game("<script>"))
            req.assert_not_called()

    def test_no_api_key_means_no_cloud_request(self):
        planner = OnlinePlanner({"online_agent_enabled": True})
        with mock.patch("luxai.online_agent.get_api_key", return_value=""):
            self.assertFalse(planner.enabled())
            self.assertIsNone(planner.plan("Открой Доту"))


if __name__ == "__main__":
    unittest.main()
