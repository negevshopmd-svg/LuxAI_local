"""Source-backed Discord research: full routing, recipient verification and send safety."""
from __future__ import annotations

import json
import sys
import types
import unittest
from unittest import mock

from luxai.discord_research import (
    DiscordDraft, detect_research_dm_request, validate_research_dm_target,
    get_wikipedia_summary, prepare_discord_draft, submit_discord_draft,
)
from luxai.macro_planner import validate_generated_macro, needs_live_macro_planning
from luxai.command_wizard import _action_from_description
from luxai.action_catalog import validate_step


VOICE_PHRASE = (
    "Найди информацию про Adolf Hitler потом нажми в Dessie "
    "на пользователя ронси и ставим информацию про адольфа гитлера "
    "и отправь нажми enter"
)


class ResearchIntentTests(unittest.TestCase):
    def test_actual_transcript_preserves_topic_and_recipient(self):
        self.assertEqual(
            detect_research_dm_request(VOICE_PHRASE),
            ("Adolf Hitler", "ронси"),
        )
        self.assertTrue(needs_live_macro_planning(VOICE_PHRASE))
        self.assertEqual(_action_from_description(VOICE_PHRASE)["action"],
                         "discord_research_dm")

    def test_safe_data_model_and_unambiguous_username(self):
        self.assertEqual(
            validate_step({
                "action": "discord_research_dm",
                "target": "Adolf Hitler||ронси",
            })["target"], "Adolf Hitler||ронси"
        )
        for value in ("Adolf Hitler", "thing||x", "thing||password:secret",
                      "topic||user/../../passwd", "topic||a\nb"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_research_dm_target(value)

    def test_reject_browser_search_followed_by_blind_discord_visual_click(self):
        wrong = {"steps": [
            {"action": "search_web", "target": "Adolf Hitler"},
            {"action": "visual_click", "target": "ронси||1"},
            {"action": "press_enter"},
        ]}
        self.assertIsNone(validate_generated_macro(wrong, VOICE_PHRASE))
        right = {"steps": [{"action": "discord_research_dm",
                            "target": "Adolf Hitler||ронси"}]}
        self.assertIsNotNone(validate_generated_macro(right, VOICE_PHRASE))

    def test_model_must_not_change_recipient_or_subject(self):
        for item in ("Adolf Hitler||someoneelse", "other topic||ронси"):
            with self.subTest(item=item):
                self.assertIsNone(validate_generated_macro({
                    "steps": [{"action": "discord_research_dm", "target": item}]
                }, VOICE_PHRASE))
        self.assertIsNone(validate_generated_macro({
            "steps": [{"action": "discord_research_dm",
                       "target": "Adolf Hitler||ронси"}]
        }, "Open Discord"))


class ResearchContentTests(unittest.TestCase):
    def test_uses_cited_real_wikipedia_extract_not_ai_fiction(self):
        sample = {
            "query": {"pages": [{
                "title": "Адольф Гитлер",
                "extract": "Адольф Гитлер был немецким политическим деятелем. "
                           "Он был диктатором Германии в период национал-социализма.",
            }]},
        }
        response = mock.MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.read.return_value = (
            json.dumps(sample).encode("utf-8")
        )
        with mock.patch("luxai.discord_research.urllib.request.urlopen",
                        return_value=response) as fetch:
            text, url = get_wikipedia_summary("Adolf Hitler")
        self.assertIn("немецким политическим", text)
        self.assertIn("Источник: https://ru.wikipedia.org/wiki/", text)
        self.assertIn("Гитлер", url)
        requested = fetch.call_args.args[0]
        self.assertIn("ru.wikipedia.org/w/api.php", requested.full_url)
        self.assertIn("gsrsearch=Adolf+Hitler", requested.full_url)
        self.assertLessEqual(len(text.encode("utf-16-le")) // 2, 350)

    def test_empty_article_is_not_fabricated(self):
        response = mock.MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.read.return_value = (
            b'{"query":{"pages":[{"title":"Unknown","extract":""}]}}'
        )
        with mock.patch("luxai.discord_research.urllib.request.urlopen",
                        return_value=response):
            with self.assertRaises(ValueError):
                get_wikipedia_summary("Unknown subject")


class DiscordDraftTests(unittest.TestCase):
    def test_visual_selection_uses_exact_user_and_checks_chat_header(self):
        # This tests orchestration without a real Discord account or API key.
        planner = mock.Mock()
        pyauto = types.SimpleNamespace(hotkey=mock.Mock())
        cap = mock.Mock(hwnd=42)
        with (
            mock.patch.dict(sys.modules, {"pyautogui": pyauto}),
            mock.patch("luxai.discord_research.get_wikipedia_summary",
                       return_value=("verified text\nИсточник: url", "url")),
            mock.patch("luxai.discord_research.find_discord_window",
                       return_value=42),
            mock.patch("luxai.discord_research.focus_discord"),
            mock.patch("luxai.desktop_actions._type_unicode_windows") as type_unicode,
            mock.patch("luxai.visual_click.capture_window",
                       return_value=cap) as capture,
            mock.patch("luxai.visual_click.find_visual_target",
                       side_effect=[(200, 100), (300, 800)]) as locate,
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.discord_research.time.sleep"),
        ):
            draft = prepare_discord_draft(planner, "Adolf Hitler||ронси")
        pyauto.hotkey.assert_called_once_with("ctrl", "k", interval=0.07)
        self.assertEqual(type_unicode.call_args_list[0].args, ("@ронси",))
        self.assertEqual(type_unicode.call_args_list[1].args[0],
                         "verified text\nИсточник: url")
        self.assertEqual(capture.call_count, 2)
        self.assertEqual(locate.call_count, 2)
        self.assertIn("@ронси", locate.call_args_list[0].args[1])
        self.assertIn("HEADER", locate.call_args_list[1].args[1])
        self.assertEqual(click.call_count, 2)
        self.assertEqual(draft.composer_point, (300, 800))

    def test_reject_ambiguous_recipient_before_type_or_send(self):
        planner = mock.Mock()
        pyauto = types.SimpleNamespace(hotkey=mock.Mock())
        with (
            mock.patch.dict(sys.modules, {"pyautogui": pyauto}),
            mock.patch("luxai.discord_research.get_wikipedia_summary",
                       return_value=("text", "url")),
            mock.patch("luxai.discord_research.find_discord_window",
                       return_value=42),
            mock.patch("luxai.discord_research.focus_discord"),
            mock.patch("luxai.desktop_actions._type_unicode_windows") as typing,
            mock.patch("luxai.visual_click.capture_window"),
            mock.patch("luxai.visual_click.find_visual_target",
                       side_effect=ValueError("Control not found unambiguously")),
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.discord_research.time.sleep"),
        ):
            with self.assertRaises(ValueError):
                prepare_discord_draft(planner, "Adolf Hitler||ронси")
        self.assertEqual(typing.call_count, 1)  # only search string
        click.assert_not_called()

    def test_send_is_a_distinct_function_after_draft(self):
        pyauto = types.SimpleNamespace(onScreen=mock.Mock(return_value=True),
                                       click=mock.Mock(), press=mock.Mock())
        draft = DiscordDraft(44, "ронси", "text", "url", (300, 800))
        with mock.patch.dict(sys.modules, {"pyautogui": pyauto}), \
             mock.patch("luxai.discord_research.focus_discord") as focused:
            answer = submit_discord_draft(draft)
        focused.assert_called_once_with(44)
        pyauto.click.assert_called_once_with(300, 800)
        pyauto.press.assert_called_once_with("enter")
        self.assertIn("проверьте историю", answer)


if __name__ == "__main__":
    unittest.main()
