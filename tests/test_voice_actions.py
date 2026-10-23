"""Offline regression tests for voice-created keyboard and mouse macros."""
import tempfile
import unittest
from pathlib import Path
from luxai.voice_actions import parse_action, parse_action_sequence
from luxai.command_registry import CommandRegistry
from luxai.command_wizard import CommandWizard
from luxai.action_catalog import validate_step


class VoiceActionsTests(unittest.TestCase):
    def test_single_key_variants(self):
        for phrase in ("нажать на Q", "Нажми английскую Q", "нажми кью", "press q", "Жарвис, нажми й"):
            with self.subTest(phrase=phrase):
                self.assertEqual(parse_action(phrase)["action"], "press_key")
                self.assertEqual(parse_action(phrase)["target"], "q")

    def test_mouse_and_keyboard(self):
        cases = {
            "кликни": ("mouse_click", ""),
            "правый клик": ("mouse_right_click", ""),
            "двойной клик": ("mouse_double_click", ""),
            "прокрути вниз 3": ("mouse_scroll", "-3"),
            "перемести курсор на 600,350": ("mouse_move", "600,350"),
            "нажми Ctrl+S": ("hotkey", "ctrl+s"),
            "подожди 2 секунды": ("wait_seconds", "2"),
            "напечатай Hello World": ("type_text", "Hello World"),
        }
        for phrase, expected in cases.items():
            with self.subTest(phrase=phrase):
                action = parse_action(phrase)
                self.assertEqual((action["action"], action["target"]), expected)
                validate_step(action)

    def test_chain_and_refuse_unsafe_or_partial(self):
        plan = parse_action_sequence("нажми Q, потом кликни, затем подожди 2 секунды")
        self.assertEqual([p["action"] for p in plan], ["press_key", "mouse_click", "wait_seconds"])
        self.assertIsNone(parse_action_sequence("нажми Q потом взломай пароль"))
        self.assertIsNone(parse_action("нажми ctrl+alt+delete"))
        self.assertIsNone(parse_action("нажми win+r"))
        self.assertIsNone(parse_action("перемести курсор на 99999,2"))

    def test_wizard_saves_multistep_action(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = CommandRegistry(Path(temp) / "commands.json")
            wizard = CommandWizard(registry)
            wizard.start()
            wizard.feed("разгон")
            response, online, _ = wizard.feed("нажми Q потом кликни")
            self.assertIsNone(online)
            self.assertIn("клик", response.casefold())
            _, _, saved = wizard.feed("да")
            self.assertEqual([s["action"] for s in saved["steps"]], ["press_key", "mouse_click"])
            registry.reload()
            self.assertEqual(len(registry.match("разгон")["steps"]), 2)


if __name__ == "__main__":
    unittest.main()
