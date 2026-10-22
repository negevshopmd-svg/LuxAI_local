"""No-network tests for voice-defined commands and safe filesystem functions."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from luxai.command_registry import CommandRegistry
from luxai.command_wizard import CommandWizard, is_create_command_request
from luxai.file_actions import (
    create_user_item, list_user_items, parse_file_intent, safe_name,
)
from luxai.online_agent import OnlinePlanner
from luxai.steam_games import local_game_intent


class FileAndCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self.home.mkdir()
        self.path = Path(self.temp.name) / "commands.json"
        self.registry = CommandRegistry(path=self.path)

    def test_default_voice_commands_exist(self):
        actions = {item["title"]: item for item in self.registry.entries()}
        for name in ("Telegram", "Discord", "Dota 2", "Counter-Strike 2", "War Thunder"):
            self.assertIn(name, actions)
        self.assertIsNotNone(self.registry.match("открой телеграм"))
        self.assertEqual(self.registry.match("запусти вар тандер")["target"], "warthunder")

    def test_war_thunder_intents(self):
        self.assertEqual(local_game_intent("Жарвис, открой вар тандер"), "warthunder")
        self.assertEqual(local_game_intent("Запусти War Thunder"), "warthunder")

    def test_file_on_desktop_default_name(self):
        plan = parse_file_intent("Создай файл на рабочем столе.")
        self.assertEqual(plan["action"], "create_file")
        self.assertEqual(plan["target"], "Новый файл.txt")
        self.assertEqual(plan["location"], "desktop")

    def test_file_named_and_location(self):
        plan = parse_file_intent("Создай файл Отчёт.txt на рабочем столе.")
        self.assertEqual(plan["target"], "Отчёт.txt")
        self.assertEqual(plan["location"], "desktop")

    def test_safe_file_creation_does_not_overwrite(self):
        first = create_user_item("create_file", "тест.txt", home=self.home)
        second = create_user_item("create_file", "тест.txt", home=self.home)
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())
        self.assertNotEqual(first, second)
        self.assertIn("тест.txt", list_user_items(home=self.home))

    def test_create_folder_and_file_in_documents(self):
        doc = create_user_item("create_folder", "Мои документы", location="documents", home=self.home)
        self.assertTrue(doc.is_dir())
        note = create_user_item("create_file", "отчёт.md", location="documents", home=self.home)
        self.assertEqual(note.read_text(encoding="utf-8"), "")

    def test_forbidden_names_and_absolute_paths(self):
        for bad in ("../secret.txt", "C:\\Temp\\foo.txt", "CON.txt", "auto.exe", "../../evil", "evil|name.txt"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    safe_name(bad)
        with self.assertRaises(ValueError):
            create_user_item("create_file", "good.txt", location="../../", home=self.home)

    def test_wizard_creates_command_through_dialogue(self):
        self.assertTrue(is_create_command_request("Жарвис, создай пожалуйста новую команду"))
        wizard = CommandWizard(self.registry, wake_prefix="Jarvis")
        self.assertIn("фразу", wizard.start())
        message, online, saved = wizard.feed("Открой мою телегу")
        self.assertIn("Что нужно делать", message)
        self.assertIsNone(online)
        self.assertIsNone(saved)
        message, online, _ = wizard.feed("Открой Telegram")
        self.assertIn("открыть telegram", message)
        message, _, saved = wizard.feed("Да")
        self.assertIsNotNone(saved)
        self.assertIn("добавлена", message)
        self.assertFalse(wizard.active)
        self.assertEqual(self.registry.match("Открой мою телегу")["target"], "telegram")
        # Survive application restart.
        again = CommandRegistry(self.path)
        self.assertEqual(again.match("Открой мою телегу")["target"], "telegram")

    def test_wizard_online_safe_action_and_refuses_shell(self):
        wizard = CommandWizard(self.registry)
        wizard.start()
        wizard.feed("запусти мой любимый проект")
        msg, pending, _ = wizard.feed("включи необычную программу")
        self.assertTrue(pending)
        self.assertEqual(wizard.stage, "online")
        reject, plan = wizard.accept_online_plan({
            "action": "open_app", "target": "cmd", "reply": "",
        })
        self.assertIsNone(plan)
        self.assertIn("безопасно", reject)
        self.assertEqual(wizard.stage, "action")

    def test_wizard_can_accept_safe_online_game_plan(self):
        wizard = CommandWizard(self.registry)
        wizard.start()
        wizard.feed("открой мой проект")
        _, pending, _ = wizard.feed("запусти мою красивую игру")
        self.assertIsNotNone(pending)
        message, plan = wizard.accept_online_plan({
            "action": "launch_game", "target": "warthunder", "reply": "",
        })
        self.assertEqual(plan["target"], "warthunder")
        self.assertIn("War Thunder", message)
        _, _, saved = wizard.feed("да")
        self.assertEqual(saved["target"], "warthunder")

    def test_disable_default_prevents_trigger(self):
        cmd = self.registry.match("открой телеграм")
        self.registry.set_enabled(cmd["id"], False)
        self.assertIsNone(self.registry.match("открой телеграм"))
        self.assertTrue(self.registry.disabled_match("открой телеграм"))
        self.registry.set_enabled(cmd["id"], True)
        self.assertFalse(self.registry.disabled_match("открой телеграм"))

    def test_cloud_file_plan_validation_rejects_terminal_paths(self):
        valid = {
            "action": "create_file", "target": "новый.txt",
            "location": "desktop", "reply": "",
        }
        self.assertEqual(OnlinePlanner._validate(valid)["action"], "create_file")
        invalid = dict(valid, target="C:\\Windows\\System32\\evil.exe")
        self.assertIsNone(OnlinePlanner._validate(invalid))

    def test_no_execution_before_wizard_save(self):
        wizard = CommandWizard(self.registry)
        with mock.patch("luxai.file_actions.create_user_item") as create:
            wizard.start()
            wizard.feed("мой файл")
            msg, _, _ = wizard.feed("создай файл на рабочем столе")
            self.assertIn("файл", msg)
            wizard.feed("да")
            create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
