"""Cloud-generated macro workflows: validation, persistence and keyboard execution."""
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

from luxai.action_catalog import validate_step
from luxai.command_registry import CommandRegistry
from luxai.command_wizard import CommandWizard, is_create_command_request
from luxai.macro_planner import validate_generated_macro
from luxai.online_agent import OnlinePlanner
from luxai.voice_actions import parse_action, parse_action_sequence


class KeySequenceTests(unittest.TestCase):
    def test_russian_english_and_romanian_letter_sequences(self):
        for phrase in ("нажимай qwerd", "нажми клавиши q w e r d",
                       "press Q W E R D", "apasă tastele qwerd"):
            with self.subTest(phrase=phrase):
                step = parse_action(phrase)
                self.assertIsNotNone(step)
                self.assertEqual(step["action"], "key_sequence")
                self.assertEqual(step["target"], "q,w,e,r,d")

    def test_modifiers_and_existing_hotkeys_are_not_replaced(self):
        self.assertEqual(parse_action("нажми Ctrl+S")["action"], "hotkey")
        self.assertEqual(parse_action("нажми Enter")["action"], "press_enter")
        self.assertIsNone(parse_action("нажми ctrl"))

    def test_sequence_validation_enforces_safe_bounds_and_normalizes(self):
        self.assertEqual(validate_step({"action": "key_sequence", "target": "QWERD"})["target"], "q,w,e,r,d")
        self.assertEqual(validate_step({"action": "key_sequence", "target": "q, w, e, r, d"})["target"], "q,w,e,r,d")
        for value in ("q", "q" * 25, "q;del", "q+alt", "q\nw", "q,й", "q,win", "../x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_step({"action": "key_sequence", "target": value})

    def test_key_sequence_is_real_keyboard_presses_not_text_insertion(self):
        from luxai import desktop_actions
        gui = types.SimpleNamespace(FAILSAFE=False, PAUSE=0, press=mock.Mock())
        with mock.patch.object(desktop_actions.sys, "platform", "win32"), mock.patch.dict(
            sys.modules, {"pyautogui": gui}
        ):
            output = desktop_actions.execute_desktop_step({
                "action": "key_sequence", "target": "q,w,e,r,d",
            })
        gui.press.assert_called_once_with(["q", "w", "e", "r", "d"], interval=0.08)
        self.assertIn("Клавиши", output)


class CloudMacroProposalTests(unittest.TestCase):
    def test_full_multi_step_plan_is_validated_in_order(self):
        result = validate_generated_macro({"steps": [
            {"action": "open_app", "target": "notepad"},
            {"action": "wait_seconds", "target": "2"},
            {"action": "key_sequence", "target": "qwerd"},
            {"action": "hotkey", "target": "ctrl+s"},
            {"action": "mouse_move", "target": "600,350"},
            {"action": "mouse_click"},
        ]})
        self.assertEqual(len(result["steps"]), 6)
        self.assertEqual(result["steps"][2]["target"], "q,w,e,r,d")
        self.assertEqual(result["steps"][3]["target"], "ctrl+s")

    def test_never_accepts_destructive_or_unapproved_cloud_code(self):
        unsafe = [
            {"action": "run_cmd", "target": "del /q *"},
            {"action": "run_powershell", "target": "Remove-Item"},
            {"action": "run_file", "target": "C:/danger.exe"},
            {"action": "type_text", "target": "powershell -Command Remove-Item X"},
            {"action": "type_text", "target": "del /q all"},
            {"action": "type_text", "target": "hello\\nworld"},
            {"action": "trash_file", "target": "test.txt"},
            {"action": "empty_recycle_bin"},
            {"action": "hotkey", "target": "win+r; powershell"},
            {"action": "open_website", "target": "http://localhost"},
        ]
        for step in unsafe:
            with self.subTest(step=step):
                self.assertIsNone(validate_generated_macro({"steps": [step]}))
        self.assertIsNone(validate_generated_macro({"steps": []}))
        self.assertIsNone(validate_generated_macro({"steps": [{"action": "noop"}] * 9}))
        self.assertIsNone(validate_generated_macro({"steps": "press q"}))

    def test_cloud_uses_dedicated_long_json_request_not_single_action_planner(self):
        planner = OnlinePlanner({
            "online_agent_enabled": True, "online_provider": "openai",
            "online_model": "gpt-4.1-mini", "online_timeout": 45,
        })
        result_json = {"steps": [
            {"action": "open_app", "target": "notepad"},
            {"action": "key_sequence", "target": "qwerd"},
        ]}
        response = {"choices": [{"message": {"content": json.dumps(result_json)}}]}
        with mock.patch.object(planner, "enabled", return_value=True), mock.patch(
            "luxai.online_agent.get_api_key", return_value="fake-test-key"
        ), mock.patch.object(planner, "_request", return_value=response) as requester:
            result = planner.plan_macro("открой блокнот потом нажми qwerd")
        self.assertEqual(len(result["steps"]), 2)
        args, kwargs = requester.call_args
        self.assertIn("MULTI-STEP MACRO DESIGNER", args[3][0]["content"])
        self.assertEqual(args[3][1]["content"], "открой блокнот потом нажми qwerd")
        self.assertGreaterEqual(kwargs["max_tokens"], 1000)


class CommandWizardMacroTests(unittest.TestCase):
    def test_saved_cloud_sequence_survives_restart_and_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "commands.json"
            wizard = CommandWizard(CommandRegistry(path))
            wizard.start()
            wizard.feed("Клавиатурный набор")
            response, description, _ = wizard.feed("открой блокнот потом нажми qwerd")
            self.assertEqual(description, "открой блокнот потом нажми qwerd")
            proposal = {"steps": [
                {"action": "open_app", "target": "notepad"},
                {"action": "key_sequence", "target": "qwerd"},
            ]}
            confirmation, _ = wizard.accept_online_plan(proposal)
            self.assertIn("Q → W → E → R → D", confirmation)
            # The command cannot be persisted before the user's explicit yes.
            self.assertFalse(CommandRegistry(path).custom)
            message, _, saved = wizard.feed("да")
            self.assertIsNotNone(saved)
            restored = CommandRegistry(path).match("Клавиатурный набор")
            self.assertEqual(restored["steps"][1]["target"], "q,w,e,r,d")
            self.assertIn("Готово", message)

    def test_cloud_rejection_does_not_save_partial_macro(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = CommandRegistry(Path(folder) / "commands.json")
            wizard = CommandWizard(registry)
            wizard.start()
            wizard.feed("Удалить все")
            wizard.feed("очистить корзину потом закрыть")
            message, plan = wizard.accept_online_plan({"steps": [
                {"action": "mouse_click"},
                {"action": "run_cmd", "target": "danger"},
            ]})
            self.assertIsNone(plan)
            self.assertIn("не создаются автоматически", message)
            self.assertFalse(registry.custom)

    def test_romanian_create_command_trigger(self):
        self.assertTrue(is_create_command_request("Creează o nouă comandă"))
        self.assertTrue(is_create_command_request("creeaza comanda"))
        self.assertTrue(is_create_command_request("Создай команду"))


if __name__ == "__main__":
    unittest.main()
