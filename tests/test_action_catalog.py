"""Safe action catalog and multi-step persistent command tests (no GUI needed)."""
import tempfile
import unittest
import sys
import types
from pathlib import Path
from unittest import mock

sys.modules.setdefault(
    "luxai.screen",
    types.SimpleNamespace(
        capture_screen=lambda: None,
        read_screen_text=lambda *args, **kwargs: "",
    ),
)

from luxai.action_catalog import CATALOG, CATEGORIES, describe_step, validate_step
from luxai.command_registry import CommandRegistry
from luxai.desktop_actions import execute_desktop_step
from luxai.agent import LocalAgent


class ActionCatalogTests(unittest.TestCase):
    def test_categories_match_reference(self):
        headings = [name for name, _ in CATEGORIES]
        for category in ("Запуск", "Клавиши", "Мышь", "Программа", "Озвучка", "Звук", "Система", "Браузер"):
            self.assertIn(category, headings)
            self.assertTrue(any(a["category"] == category for a in CATALOG.values()))

    def test_all_reference_actions_have_real_implementations(self):
        for action, definition in CATALOG.items():
            self.assertTrue(definition["available"], action)
        self.assertEqual(validate_step({"action": "run_cmd", "target": "echo hello"})["target"], "echo hello")
        self.assertEqual(validate_step({"action": "run_powershell", "target": "Get-Date"})["action"], "run_powershell")
        self.assertEqual(validate_step({"action": "mouse_hold", "target": "3"})["target"], "3")
        self.assertEqual(validate_step({"action": "wait_minutes", "target": "2"})["target"], "2")
        with self.assertRaises(ValueError):
            validate_step({"action": "run_cmd", "target": "echo hello\nother"})
        with self.assertRaises(ValueError):
            validate_step({"action": "mouse_hold", "target": "10"})

    def test_safe_browser_url_validation(self):
        for url in ("http://example.org", "https://localhost/path", "file:///tmp/test", "https://127.0.0.1"):
            with self.assertRaises(ValueError):
                validate_step({"action": "open_website", "target": url})
        valid = validate_step({"action": "open_website", "target": "https://www.wikipedia.org"})
        self.assertEqual(valid["target"], "https://www.wikipedia.org")

    def test_unicode_and_hotkeys(self):
        self.assertEqual(validate_step({"action": "type_text", "target": "Привет, мир!"})["target"], "Привет, мир!")
        self.assertEqual(validate_step({"action": "hotkey", "target": "ctrl+s"})["action"], "hotkey")
        with self.assertRaises(ValueError):
            validate_step({"action": "hotkey", "target": "win+r; powershell"})

    def test_macro_reopens_after_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            location = Path(folder) / "commands.json"
            registry = CommandRegistry(location)
            raw = {
                "title": "Мой утренний набор",
                "phrases": ["открой рабочий набор"],
                "action": "open_app",
                "target": "telegram",
                "steps": [
                    {"action": "open_app", "target": "telegram"},
                    {"action": "wait_seconds", "target": "2"},
                    {"action": "open_website", "target": "https://www.wikipedia.org"},
                    {"action": "speak_done"},
                ],
            }
            registry.save_custom(raw)
            fresh = CommandRegistry(location)
            match = fresh.match("открой рабочий набор")
            self.assertEqual(len(match["steps"]), 4)
            self.assertEqual(match["steps"][2]["target"], "https://www.wikipedia.org")

    def test_invalid_macro_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = CommandRegistry(Path(folder) / "commands.json")
            # GUI-created terminal steps are permitted only with explicit
            # user confirmation; invalid shell contents cannot contain newlines.
            with self.assertRaises(ValueError):
                registry.save_custom({
                    "title": "Bad", "phrases": ["do bad"],
                    "action": "run_cmd", "target": "x",
                    "steps": [{"action": "run_cmd", "target": "echo hello\nother"}],
                })
            with self.assertRaises(ValueError):
                registry.save_custom({
                    "title": "Too many", "phrases": ["more"],
                    "action": "time", "target": "",
                    "steps": [{"action": "noop"}] * 9,
                })

    def test_user_selected_keyboard_action_executes_only_after_confirmation(self):
        agent = LocalAgent({"language": "ru"})
        step = validate_step({"action": "hotkey", "target": "ctrl+s"})
        with mock.patch("luxai.agent.execute_desktop_step") as runner:
            no = agent.execute_plan("сохранить документ", step, lambda _: False)
            self.assertIn("отменено", no)
            runner.assert_not_called()
            runner.return_value = "Сохранено."
            yes = agent.execute_plan("сохранить документ", step, lambda _: True)
            self.assertIn("Сохранено", yes)
            runner.assert_called_once()

    def test_user_defined_terminal_actions_wait_for_real_exit_code(self):
        from luxai.desktop_actions import _launch_user_script
        fake_done = type("Result", (), {"returncode": 0})()
        with mock.patch("luxai.desktop_actions.sys.platform", "win32"), mock.patch(
            "luxai.desktop_actions.subprocess.run", return_value=fake_done
        ) as executor:
            result = _launch_user_script("run_cmd", "echo test")
            self.assertIn("выполнена", result)
            args = executor.call_args.args[0]
            self.assertEqual(args[:3], ["cmd.exe", "/D", "/C"])
            self.assertEqual(args[3], "echo test")
            self.assertFalse(executor.call_args.kwargs["shell"])
            self.assertEqual(executor.call_args.kwargs["timeout"], 25)

        failed = type("Result", (), {"returncode": 7})()
        with mock.patch("luxai.desktop_actions.sys.platform", "win32"), mock.patch(
            "luxai.desktop_actions.subprocess.run", return_value=failed
        ):
            with self.assertRaisesRegex(OSError, "код 7"):
                _launch_user_script("run_powershell", "Get-Date")

    def test_manual_shell_action_always_requires_confirmation(self):
        agent = LocalAgent({"language": "ru"})
        plan = validate_step({"action": "run_cmd", "target": "echo hello"})
        prompts = []
        with mock.patch("luxai.agent.execute_desktop_step") as runner:
            answer = agent.execute_plan(
                "start command", plan,
                lambda message: prompts.append(message) or False,
            )
            self.assertIn("отменено", answer)
            runner.assert_not_called()
        self.assertIn("echo hello", prompts[0])
        self.assertIn("CMD", prompts[0])

    def test_new_action_arguments_are_validated(self):
        cases = [
            ({"action": "app_volume", "target": "telegram:75"}, "telegram:75"),
            ({"action": "voice_female", "target": "Привет"}, "Привет"),
            ({"action": "mouse_right_hold", "target": "2"}, "2"),
            ({"action": "open_first_result", "target": "python docs"}, "python docs"),
        ]
        for plan, value in cases:
            self.assertEqual(validate_step(plan)["target"], value)
        for plan in (
            {"action": "app_volume", "target": "invalid:80"},
            {"action": "wait_minutes", "target": "100"},
            {"action": "run_powershell", "target": ""},
        ):
            with self.assertRaises(ValueError):
                validate_step(plan)

    def test_website_is_opened_via_browser_not_cmd(self):
        with mock.patch("luxai.desktop_actions.webbrowser.open", return_value=True) as browser:
            result = execute_desktop_step({
                "action": "open_website",
                "target": "https://example.org/test",
            })
            self.assertEqual(result, "Открыл сайт.")
            browser.assert_called_once_with("https://example.org/test", new=2)


if __name__ == "__main__":
    unittest.main()
