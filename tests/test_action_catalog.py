"""Safe action catalog and multi-step persistent command tests (no GUI needed)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_unsafe_actions_are_unavailable(self):
        for action in ("run_cmd", "run_powershell", "sleep_pc", "mouse_hold"):
            self.assertFalse(CATALOG[action]["available"])
            with self.assertRaises(ValueError):
                validate_step({"action": action, "target": "echo hello"})

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
            with self.assertRaises(ValueError):
                registry.save_custom({
                    "title": "Bad", "phrases": ["do bad"],
                    "action": "run_cmd", "target": "x",
                    "steps": [{"action": "run_cmd", "target": "rm -rf"}],
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
