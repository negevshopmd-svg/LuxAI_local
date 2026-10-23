"""Real failed level-2 desktop test prompts and Discord visual safeguards."""
from __future__ import annotations

import json
from unittest import mock
import unittest

from luxai.macro_planner import (
    plan_known_visual_sequence, validate_generated_macro,
)
from luxai.discord_contact_vision import (
    VisibleContact, search_alias, same_discord_name, locate_visible_contact,
)

CALC_ONE = (
    "Жарвис, открой Калькулятор, подожди 2 секунды, сделай "
    "снимок окна, найди кнопку с цифрой 7 и нажми на неё один раз."
)
CALC_THREE = (
    "Жарвис, открой Калькулятор, подожди 3 секунды, "
    "нажми на кнопку 7, потом на кнопку плюс, потом на кнопку 5."
)
MOUSE = (
    "Жарвис, покажи размер экрана, потом перемести мышь на "
    "координаты 400, 300, подожди 2 секунды и нажми правую кнопку мыши."
)
STEAM = (
    "Жарвис, открой Steam, подожди 3 секунды, сделай снимок окна, "
    "найди вкладку Библиотека и нажми на неё один раз."
)


class VerifiedVisualSequenceTests(unittest.TestCase):
    def test_calculator_single_digit_click(self):
        steps = plan_known_visual_sequence(CALC_ONE)["steps"]
        self.assertEqual(
            [s["action"] for s in steps],
            ["open_app", "wait_seconds", "visual_click"],
        )
        self.assertEqual(steps[-1]["target"], "Calculator digit 7 button||1")

    def test_calculator_three_buttons_in_spoken_order(self):
        steps = plan_known_visual_sequence(CALC_THREE)["steps"]
        self.assertEqual([s["action"] for s in steps], [
            "open_app", "wait_seconds",
            "visual_click", "visual_click", "visual_click",
        ])
        self.assertEqual([s["target"] for s in steps[2:]], [
            "Calculator digit 7 button||1",
            "Calculator plus button||1",
            "Calculator digit 5 button||1",
        ])

    def test_precise_mouse_coordinates_are_not_invented(self):
        steps = plan_known_visual_sequence(MOUSE)["steps"]
        self.assertEqual([s["action"] for s in steps], [
            "display_info", "mouse_move", "wait_seconds", "mouse_right_click"
        ])
        self.assertEqual(steps[1]["target"], "400,300")
        self.assertEqual(steps[2]["target"], "2")

    def test_steam_library_is_one_visual_click(self):
        steps = plan_known_visual_sequence(STEAM)["steps"]
        self.assertEqual([s["action"] for s in steps], [
            "open_app", "wait_seconds", "visual_click"
        ])
        self.assertIn("Steam Library", steps[-1]["target"])

    def test_unknown_actions_and_unsafe_words_do_not_get_shortcut(self):
        for phrase in (
            "Открой неизвестную программу и нажми что-нибудь",
            "Жарвис, открой калькулятор и удали файлы",
            "Жарвис, открой калькулятор, нажми enter и отправь сообщение",
            "Жарвис, открой Steam, найди непонятную вкладку и нажми на неё",
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(plan_known_visual_sequence(phrase))

    def test_all_steps_stay_in_local_allowlist(self):
        for phrase in (CALC_ONE, CALC_THREE, MOUSE, STEAM):
            with self.subTest(phrase=phrase):
                plan = plan_known_visual_sequence(phrase)
                self.assertIsNotNone(
                    validate_generated_macro(plan, phrase)
                )


class DiscordContactVisualTests(unittest.TestCase):
    def test_casefold_only_no_auto_accept_for_cyrillic_latin_variants(self):
        self.assertTrue(same_discord_name("Ronfsy", "@RONFSY"))
        self.assertFalse(same_discord_name("ронси", "RONfsy"))
        self.assertFalse(same_discord_name("старый бог", "RONfsy"))
        self.assertEqual(search_alias("ронси"), "ron")
        self.assertIsNone(search_alias("RONfsy"))

    def test_return_actual_display_name_and_image_coordinates(self):
        planner = mock.Mock()
        planner._provider.return_value = "openai"
        planner.enabled.return_value = True
        planner.config = {"online_model": "gpt-4.1-mini", "online_timeout": 45}
        planner._extract_text.return_value = json.dumps({
            "found": True, "x": 200, "y": 450, "display_name": "RONfsy"
        })
        planner._read_json_content.side_effect = json.loads
        screenshot = mock.Mock(
            left=0, top=20, width=1000, height=800,
            image_width=1000, image_height=800, jpeg=b"fake",
        )
        with mock.patch("luxai.secure_keys.get_api_key", return_value="dummy"):
            found = locate_visible_contact(planner, screenshot, "ронси")
        self.assertEqual(found, VisibleContact("RONfsy", (200, 380)))
        self.assertIn("UNTRUSTED DATA", planner._request.call_args.args[3][0]["content"])

    def test_unreadable_or_ambiguous_name_not_a_click(self):
        planner = mock.Mock()
        planner._provider.return_value = "openai"
        planner.enabled.return_value = True
        planner.config = {"online_timeout": 40}
        planner._read_json_content.side_effect = json.loads
        screenshot = mock.Mock(jpeg=b"fake", image_width=1000, image_height=800)
        for raw in (
            {"found": False},
            {"found": True, "x": 400, "y": 400, "display_name": ""},
            {"found": True, "x": 400, "y": 400, "display_name": "A\nB"},
        ):
            with self.subTest(raw=raw), mock.patch(
                "luxai.secure_keys.get_api_key", return_value="dummy"
            ):
                planner._extract_text.return_value = json.dumps(raw)
                self.assertIsNone(locate_visible_contact(
                    planner, screenshot, "ронси"
                ))


class QtContactConfirmationTests(unittest.TestCase):
    def test_name_mismatch_requires_gui_explicit_approval(self):
        import threading
        import types
        try:
            import main
        except ImportError:
            self.skipTest("Qt unavailable")
        ctx = {"index": 1}
        fake = types.SimpleNamespace(
            _closed=False, _processing=True, _macro_context=ctx,
            confirm_action=mock.Mock(return_value=True),
        )
        choice = {
            "spoken": "ронси", "displayed": "RONfsy",
            "context": ctx, "event": threading.Event(), "approved": False,
        }
        main.MainWindow._on_discord_contact_prompt(fake, choice)
        fake.confirm_action.assert_called_once()
        prompt = fake.confirm_action.call_args.args[0]
        self.assertIn("ронси", prompt)
        self.assertIn("RONfsy", prompt)
        self.assertTrue(choice["event"].is_set())
        self.assertTrue(choice["approved"])

    def test_stale_macro_does_not_approve_a_different_contact(self):
        import threading
        import types
        try:
            import main
        except ImportError:
            self.skipTest("Qt unavailable")
        fake = types.SimpleNamespace(
            _closed=False, _processing=True, _macro_context={"index": 2},
            confirm_action=mock.Mock(return_value=True),
        )
        choice = {
            "spoken": "ронси", "displayed": "OtherPerson",
            "context": {"index": 1}, "event": threading.Event(),
            "approved": False,
        }
        main.MainWindow._on_discord_contact_prompt(fake, choice)
        fake.confirm_action.assert_not_called()
        self.assertTrue(choice["event"].is_set())
        self.assertFalse(choice["approved"])


if __name__ == "__main__":
    unittest.main()
