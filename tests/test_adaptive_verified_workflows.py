"""Offline regressions for adaptive cloud tools and screenshot-gated Discord text.

No network, real Discord account, or keyboard input occurs in these tests.
"""
from __future__ import annotations
import json
import types
import unittest
from unittest import mock

from luxai.discord_search_guard import verified_discord_search
from luxai.discord_research import (
    validate_discord_text_target, validate_discord_plain_message,
    prepare_discord_draft,
)
from luxai.macro_planner import validate_generated_macro

SPEECH = (
    "Жарвис нажми в дискорде на пользователя Ханзу потом "
    "напиши ему привет и нажми enter"
)


class CloudToolSafetyTests(unittest.TestCase):
    def test_cloud_can_choose_new_send_tool_from_unseen_phrasing(self):
        plan = validate_generated_macro({
            "steps": [{"action": "discord_send_text", "target": "Ханзу||привет"}],
        }, SPEECH)
        self.assertEqual(plan["steps"][0]["action"], "discord_send_text")
        for wrong in (
            [{"action": "open_app", "target": "discord"}],
            [{"action": "type_text", "target": "привет"},
             {"action": "press_enter", "target": ""}],
            [{"action": "discord_send_text", "target": "Ронси||привет"}],
            [{"action": "discord_send_text", "target": "Ханзу||другой текст"}],
        ):
            with self.subTest(wrong=wrong):
                self.assertIsNone(validate_generated_macro({"steps": wrong}, SPEECH))

    def test_user_message_text_is_literal_and_bounded(self):
        self.assertEqual(
            validate_discord_text_target("  Hanzo || привет "),
            ("Hanzo", "привет"),
        )
        for invalid in ("", "a\nb", "a||b", "a"*351):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    validate_discord_plain_message(invalid)

    def test_cloud_revises_invalid_plan_without_executing_partial_steps(self):
        from luxai.online_agent import OnlinePlanner
        import luxai.online_agent as mod
        planner = mock.Mock()
        planner.enabled.return_value = True
        planner._provider.return_value = "openai"
        planner._blocked_until = 0
        planner.config = {"online_timeout": 60}
        planner._request.side_effect = [
            {"test": "rejected"}, {"test": "accepted"},
        ]
        planner._extract_text.side_effect = [
            json.dumps({"steps": [{"action": "open_app", "target": "discord"}]}),
            json.dumps({"steps": [
                {"action": "discord_send_text", "target": "Ханзу||привет"}
            ]}),
        ]
        planner._read_json_content.side_effect = json.loads
        with mock.patch.object(mod, "get_api_key", return_value="dummy"):
            plan = OnlinePlanner.plan_macro(planner, SPEECH)
        self.assertEqual(plan["steps"][0]["action"], "discord_send_text")
        self.assertEqual(planner._request.call_count, 2)
        repaired_messages = planner._request.call_args.args[3]
        self.assertIn("validator rejected", repaired_messages[-1]["content"])
        self.assertEqual(planner.last_error, "")

    def test_generated_nonuser_message_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_discord_text_target("Hanzo||first\nsecond")


class ScreenshotGateTests(unittest.TestCase):
    def _common(self, point):
        import sys
        screenshot = mock.Mock(hwnd=77, left=0, top=0, height=900, width=1300)
        pyauto = types.SimpleNamespace(hotkey=mock.Mock())
        stack = (
            mock.patch.dict(sys.modules, {"pyautogui": pyauto}),
            mock.patch("luxai.discord_research.focus_discord"),
            mock.patch("luxai.visual_click.capture_window", return_value=screenshot),
            mock.patch("luxai.visual_click.find_visual_target", return_value=point),
            mock.patch("luxai.visual_click.click_visual_target"),
            mock.patch("luxai.desktop_actions._type_unicode_windows"),
            mock.patch("luxai.discord_search_guard.time.sleep"),
        )
        return stack, screenshot, pyauto

    def test_missing_modal_never_types_into_chat(self):
        stack, shot, pyauto = self._common((600, 490))
        from contextlib import ExitStack
        with ExitStack() as x:
            for p in stack: x.enter_context(p)
            locate = x.enter_context(mock.patch(
                "luxai.visual_click.find_visual_target",
                side_effect=ValueError("Control not found unambiguously"),
            ))
            typer = x.enter_context(mock.patch(
                "luxai.desktop_actions._type_unicode_windows",
            ))
            with self.assertRaises(ValueError):
                verified_discord_search(mock.Mock(), 77, "@Octavian")
        typer.assert_not_called()

    def test_bottom_message_composer_is_not_a_search_overlay(self):
        stack, shot, pyauto = self._common((650, 860))
        from contextlib import ExitStack
        with ExitStack() as x:
            mocks = [x.enter_context(p) for p in stack]
            with self.assertRaisesRegex(ValueError, "overlay not verified"):
                verified_discord_search(mock.Mock(), 77, "@Octavian")
            mocks[4].assert_not_called()  # no click
            mocks[5].assert_not_called()  # no typing

    def test_overlay_disappearing_after_click_never_types_recipient(self):
        stack, shot, pyauto = self._common((650, 270))
        from contextlib import ExitStack
        with ExitStack() as x:
            mocks = [x.enter_context(p) for p in stack]
            with mock.patch(
                "luxai.visual_click.find_visual_target",
                side_effect=[(650, 270),
                             ValueError("Control not found unambiguously")],
            ):
                with self.assertRaises(ValueError):
                    verified_discord_search(mock.Mock(), 77, "@Octavian")
            mocks[4].assert_called_once()
            mocks[5].assert_not_called()

    def test_only_verified_modal_input_receives_the_search_text(self):
        stack, shot, pyauto = self._common((650, 270))
        from contextlib import ExitStack
        with ExitStack() as x:
            mocks = [x.enter_context(p) for p in stack]
            result = verified_discord_search(mock.Mock(), 77, "@Octavian")
            self.assertIs(result, shot)
            self.assertEqual(mocks[2].call_count, 3)
            self.assertEqual(mocks[3].call_count, 2)
            mocks[4].assert_called_once_with(shot, (650, 270), 1)
            mocks[5].assert_called_once_with("@Octavian")
            pyauto.hotkey.assert_called_once_with("ctrl", "k", interval=0.07)


class ActiveChatVerificationTests(unittest.TestCase):
    def test_sidebar_and_popup_name_is_not_an_open_chat_header(self):
        from luxai.discord_navigation import _chat_header_ok
        screenshot = mock.Mock(
            left=0, top=0, width=1200, height=850,
        )
        for point in ((90, 35), (600, 300), (600, 720)):
            with (
                self.subTest(point=point),
                mock.patch("luxai.visual_click.capture_window",
                           return_value=screenshot),
                mock.patch("luxai.visual_click.find_visual_target",
                           return_value=point),
            ):
                with self.assertRaisesRegex(ValueError, "header"):
                    _chat_header_ok(mock.Mock(), 77, "Octavian")

    def test_real_top_main_chat_header_is_accepted(self):
        from luxai.discord_navigation import _chat_header_ok
        shot = mock.Mock(left=0, top=0, width=1200, height=850)
        with (
            mock.patch("luxai.visual_click.capture_window", return_value=shot),
            mock.patch("luxai.visual_click.find_visual_target",
                       return_value=(450, 48)),
        ):
            self.assertIs(_chat_header_ok(mock.Mock(), 77, "Octavian"), shot)


class DirectMessageDraftTests(unittest.TestCase):
    def test_literal_message_does_not_fetch_wikipedia(self):
        from luxai.discord_contact_vision import VisibleContact
        shot = mock.Mock(hwnd=77)
        with (
            mock.patch("luxai.discord_research.get_wikipedia_summary") as wiki,
            mock.patch("luxai.discord_research.find_discord_window", return_value=77),
            mock.patch("luxai.discord_research.focus_discord"),
            mock.patch("luxai.visual_click.capture_window", return_value=shot),
            mock.patch("luxai.discord_contact_vision.locate_visible_contact",
                       return_value=VisibleContact("Ханзу", (200, 400))),
            mock.patch("luxai.discord_navigation._chat_header_ok", return_value=shot),
            mock.patch("luxai.visual_click.find_visual_target", return_value=(500, 800)),
            mock.patch("luxai.visual_click.click_visual_target"),
            mock.patch("luxai.desktop_actions._type_unicode_windows") as typer,
            mock.patch("luxai.discord_research.time.sleep"),
        ):
            draft = prepare_discord_draft(
                mock.Mock(), "Direct user message||Ханзу",
                message_override="привет",
            )
        wiki.assert_not_called()
        typer.assert_called_once_with("привет")
        self.assertEqual(draft.message, "привет")
        self.assertEqual(draft.username, "Ханзу")


if __name__ == "__main__":
    unittest.main()
