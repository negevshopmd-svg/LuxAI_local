"""Cloud-first command routing, app discovery and real file action tests."""
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

from luxai.online_agent import OnlinePlanner
from luxai.windows_apps import normalized_name, resolve_installed_app, launch_installed_app
from luxai.intent_routing import is_operational_request, routine_reply, suspicious_completion_reply
from luxai.file_actions import rename_user_item, create_user_item
from luxai.steam_games import lookup_steam_game, local_game_intent
from luxai.agent import LocalAgent


class CloudExecutionTests(unittest.TestCase):
    def test_arbitrary_installed_app_names_are_valid_plans(self):
        for target in ("Blender", "Mozilla Firefox", "фаерфокс", "Discord"):
            actual = OnlinePlanner._validate({"action": "open_app", "target": target, "reply": ""})
            self.assertEqual(actual["action"], "open_app")
        self.assertEqual(
            OnlinePlanner._validate({"action": "open_app", "target": "фаерфокс", "reply": ""})["target"],
            "firefox",
        )
        for target in ("cmd", "powershell", "bash", r"C:\Users\Joe\evil.exe", "rm -rf /"):
            self.assertIsNone(OnlinePlanner._validate({
                "action": "open_app", "target": target, "reply": "",
            }))

    def test_firefox_resolution_uses_real_registered_path(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "firefox.exe"
            path.touch()
            with mock.patch(
                "luxai.windows_apps.app_path_candidates",
                return_value=iter([path]),
            ):
                self.assertEqual(resolve_installed_app("фаерфокс"), path)
        self.assertEqual(normalized_name("файерфокс"), "firefox")

    def test_app_execution_requires_approval_and_finds_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            program = Path(tmp) / "firefox.exe"
            program.touch()
            with mock.patch("luxai.windows_apps.resolve_installed_app", return_value=program):
                with mock.patch("luxai.windows_apps.sys.platform", "win32"):
                    with mock.patch("luxai.windows_apps.subprocess.Popen") as popen:
                        denied, result = launch_installed_app("firefox", lambda _: False)
                        self.assertFalse(denied)
                        popen.assert_not_called()
                        allowed, result = launch_installed_app("firefox", lambda _: True)
                        self.assertTrue(allowed)
                        self.assertIn("Передал Windows", result)
                        popen.assert_called_once()
                        self.assertEqual(popen.call_args.args[0], [str(program)])
                        self.assertFalse(popen.call_args.kwargs["shell"])

    def test_undertale_official_appid_works_without_network(self):
        self.assertEqual(local_game_intent("Запусти андертейл"), "undertale")
        with mock.patch("luxai.steam_games.urllib.request.urlopen") as url:
            result = lookup_steam_game("Undertale", timeout=2)
        self.assertEqual(result, (391540, "Undertale"))
        url.assert_not_called()

    def test_cloud_planner_can_verify_undertale_title(self):
        fake = {"choices": [{"message": {"content": json.dumps({
            "action": "steam_game", "target": "Undertale", "reply": "",
        })}}]}
        planner = OnlinePlanner({
            "online_provider": "gemini",
            "online_model": "gemini-3.5-flash-lite",
            "online_agent_enabled": True,
        })
        with mock.patch.object(planner, "enabled", return_value=True), mock.patch(
            "luxai.online_agent.get_api_key", return_value="fake-test-key",
        ), mock.patch.object(planner, "_request", return_value=fake):
            result = planner.plan("Открой Undertale в Steam")
        self.assertEqual(result["action"], "steam_verified")
        self.assertEqual(result["appid"], 391540)

    def test_only_verified_file_rename_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            src = create_user_item("create_file", "Новый файл.txt", home=home)
            self.assertTrue(src.exists())
            dst = rename_user_item("Новый файл.txt", "заметки.txt", home=home)
            self.assertFalse(src.exists())
            self.assertTrue(dst.exists())
            self.assertEqual(dst.name, "заметки.txt")
            with self.assertRaises(FileNotFoundError):
                rename_user_item("Новый файл.txt", "missing.txt", home=home)

    def test_pronoun_rename_needs_real_prior_file(self):
        agent = LocalAgent({"language": "ru"})
        plan = {
            "action": "rename_file", "source": "@last",
            "target": "заметки.txt", "location": "desktop",
        }
        with mock.patch("luxai.agent.rename_user_item") as rename:
            result = agent.execute_plan("Переименуй его", plan, lambda _: True)
        self.assertIn("Не знаю", result)
        rename.assert_not_called()
        self.assertFalse(agent.last_execution_success)

    def test_file_rename_confirmation_and_new_name_tracking(self):
        agent = LocalAgent({"language": "ru"})
        agent.last_file = {"name": "Новый файл.txt", "location": "desktop"}
        plan = {
            "action": "rename_file", "source": "@last",
            "target": "новое.txt", "location": "desktop",
        }
        with mock.patch("luxai.agent.rename_user_item", return_value=Path("desktop") / "новое.txt") as fn:
            out = agent.execute_plan("Переименуй его", plan, lambda _: False)
            self.assertIn("отменено", out)
            fn.assert_not_called()
            out = agent.execute_plan("Переименуй его", plan, lambda _: True)
            self.assertIn("Проверено", out)
            self.assertTrue(agent.last_execution_success)
            self.assertEqual(agent.last_file["name"], "новое.txt")

    def test_cloud_search_uses_native_google_grounding_and_not_unverified_inference(self):
        planner = OnlinePlanner({"online_provider": "gemini"})
        response = {
            "candidates": [{
                "content": {"parts": [{"text": "Завтра ожидается дождь."}]},
                "groundingMetadata": {
                    "groundingChunks": [{"web": {"uri": "https://weather.example.org/report"}}]
                },
            }]
        }
        with mock.patch("luxai.online_agent.urllib.request.build_opener") as opener:
            handle = opener.return_value.open.return_value.__enter__.return_value
            handle.read.return_value = json.dumps(response).encode()
            answer = planner._grounded_answer(
                "Какая погода завтра в Кишинёве?",
                "gemini-3.5-flash-lite", "test-key", 5,
            )
            self.assertIn("дождь", answer)
            request = opener.return_value.open.call_args.args[0]
            self.assertIn("generativelanguage.googleapis.com", request.full_url)
            self.assertNotIn("test-key", request.full_url)
            payload = json.loads(request.data)
            self.assertEqual(payload["tools"], [{"google_search": {}}])
            self.assertEqual(request.get_header("X-goog-api-key"), "test-key")

    def test_actions_not_conversation_text_for_offline_llm(self):
        self.assertTrue(is_operational_request("Жарвис, переименуй его"))
        self.assertTrue(is_operational_request("Запусти Undertale"))
        self.assertTrue(is_operational_request("Какая погода завтра?"))
        self.assertFalse(is_operational_request("Привет"))
        self.assertIsNone(routine_reply("Открой Firefox", "ru"))
        self.assertTrue(suspicious_completion_reply("Я открыл Firefox"))
        self.assertFalse(suspicious_completion_reply("Не могу открыть Firefox"))

    def test_local_agent_plan_does_not_execute_arbitrary_cmd(self):
        agent = LocalAgent({"language": "ru"})
        with mock.patch("luxai.agent.execute_desktop_step") as execute:
            reply = agent.execute_plan(
                "Открой CMD",
                {"action": "open_app", "target": "cmd"},
                lambda _: True,
            )
        execute.assert_not_called()
        self.assertFalse(agent.last_execution_success)
        self.assertIn("Некорректное", reply)


if __name__ == "__main__":
    unittest.main()
