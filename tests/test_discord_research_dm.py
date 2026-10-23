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
        from urllib.parse import unquote
        self.assertIn("Гитлер", unquote(url))
        requested = fetch.call_args.args[0]
        self.assertIn("ru.wikipedia.org/w/api.php", requested.full_url)
        self.assertIn("gsrsearch=Adolf+Hitler", requested.full_url)
        self.assertLessEqual(len(text.encode("utf-16-le")) // 2, 350)
        self.assertNotIn("\n", text)
        self.assertNotIn("\r", text)

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
    def test_search_fallback_when_contact_not_visible_in_first_screenshot(self):
        # First screenshot contains no visible match; Ctrl+K then succeeds.
        from luxai.discord_contact_vision import VisibleContact
        planner = mock.Mock()
        pyauto = types.SimpleNamespace(hotkey=mock.Mock())
        cap = mock.Mock(hwnd=42)
        with (
            mock.patch.dict(sys.modules, {"pyautogui": pyauto}),
            mock.patch("luxai.discord_research.get_wikipedia_summary",
                       return_value=("verified text  Источник: url", "url")),
            mock.patch("luxai.discord_research.find_discord_window",
                       return_value=42),
            mock.patch("luxai.discord_research.focus_discord"),
            mock.patch("luxai.desktop_actions._type_unicode_windows") as type_unicode,
            mock.patch("luxai.visual_click.capture_window",
                       return_value=cap) as capture,
            mock.patch("luxai.discord_contact_vision.locate_visible_contact",
                       side_effect=[None, VisibleContact("ронси", (200, 100))]) as locate,
            mock.patch("luxai.visual_click.find_visual_target",
                       return_value=(300, 800)) as header,
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.discord_research.time.sleep"),
        ):
            draft = prepare_discord_draft(planner, "Adolf Hitler||ронси")
        pyauto.hotkey.assert_called_once_with("ctrl", "k", interval=0.07)
        self.assertEqual(type_unicode.call_args_list[0].args, ("@ронси",))
        self.assertEqual(type_unicode.call_args_list[1].args[0],
                         "verified text  Источник: url")
        self.assertEqual(capture.call_count, 3)
        self.assertEqual(locate.call_count, 2)
        self.assertFalse(locate.call_args_list[0].kwargs.get("quick_switcher", False))
        self.assertTrue(locate.call_args_list[1].kwargs["quick_switcher"])
        self.assertIn("HEADER", header.call_args.args[1])
        self.assertEqual(click.call_count, 2)
        self.assertEqual(draft.composer_point, (300, 800))

    def test_visible_latin_contact_needs_user_approval_before_click(self):
        from luxai.discord_contact_vision import VisibleContact
        planner = mock.Mock()
        pyauto = types.SimpleNamespace(hotkey=mock.Mock())
        cap = mock.Mock(hwnd=42)
        with (
            mock.patch.dict(sys.modules, {"pyautogui": pyauto}),
            mock.patch("luxai.discord_research.get_wikipedia_summary",
                       return_value=("verified text", "url")),
            mock.patch("luxai.discord_research.find_discord_window", return_value=42),
            mock.patch("luxai.discord_research.focus_discord"),
            mock.patch("luxai.desktop_actions._type_unicode_windows") as typing,
            mock.patch("luxai.visual_click.capture_window",
                       return_value=cap) as capture,
            mock.patch("luxai.discord_contact_vision.locate_visible_contact",
                       return_value=VisibleContact("RONfsy", (230, 480))) as locate,
            mock.patch("luxai.visual_click.find_visual_target",
                       return_value=(310, 800)) as header,
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.discord_research.time.sleep"),
        ):
            with self.assertRaisesRegex(ValueError, "имя на снимке отличается"):
                prepare_discord_draft(planner, "Nikola Tesla||ронси")
            click.assert_not_called()
            typing.assert_not_called()
            agreed = mock.Mock(return_value=True)
            draft = prepare_discord_draft(
                planner, "Nikola Tesla||ронси", confirm_candidate=agreed
            )
        agreed.assert_called_once_with("ронси", "RONfsy")
        self.assertEqual(draft.username, "RONfsy")
        self.assertIn("RONfsy", header.call_args.args[1])
        self.assertEqual(click.call_count, 2)
        self.assertEqual(capture.call_count, 3)
        pyauto.hotkey.assert_not_called()
        typing.assert_called_once_with("verified text")

    def test_declining_ambiguous_contact_never_clicks_or_types(self):
        from luxai.discord_contact_vision import VisibleContact
        with (
            mock.patch.dict(sys.modules, {"pyautogui": types.SimpleNamespace(hotkey=mock.Mock())}),
            mock.patch("luxai.discord_research.get_wikipedia_summary",
                       return_value=("text", "url")),
            mock.patch("luxai.discord_research.find_discord_window", return_value=42),
            mock.patch("luxai.discord_research.focus_discord"),
            mock.patch("luxai.visual_click.capture_window"),
            mock.patch("luxai.discord_contact_vision.locate_visible_contact",
                       return_value=VisibleContact("OtherPerson", (140, 500))),
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.desktop_actions._type_unicode_windows") as typing,
        ):
            with self.assertRaisesRegex(ValueError, "выбор получателя отмен"):
                prepare_discord_draft(
                    mock.Mock(), "Nikola Tesla||ронси",
                    confirm_candidate=lambda _spoken, _displayed: False
                )
        click.assert_not_called()
        typing.assert_not_called()

    def test_fallback_latin_prefix_when_cyrillic_search_finds_no_user(self):
        from luxai.discord_contact_vision import VisibleContact
        planner = mock.Mock()
        pyauto = types.SimpleNamespace(hotkey=mock.Mock())
        with (
            mock.patch.dict(sys.modules, {"pyautogui": pyauto}),
            mock.patch("luxai.discord_research.get_wikipedia_summary",
                       return_value=("text", "url")),
            mock.patch("luxai.discord_research.find_discord_window", return_value=42),
            mock.patch("luxai.discord_research.focus_discord"),
            mock.patch("luxai.desktop_actions._type_unicode_windows") as typing,
            mock.patch("luxai.visual_click.capture_window"),
            mock.patch("luxai.discord_contact_vision.locate_visible_contact",
                       side_effect=[
                           None, None, VisibleContact("RONfsy", (200, 400)),
                       ]) as locate,
            mock.patch("luxai.visual_click.find_visual_target",
                       return_value=(320, 810)),
            mock.patch("luxai.visual_click.click_visual_target"),
            mock.patch("luxai.discord_research.time.sleep"),
        ):
            draft = prepare_discord_draft(
                planner, "Nikola Tesla||ронси",
                confirm_candidate=lambda _s, name: name == "RONfsy"
            )
        self.assertEqual(typing.call_args_list[0].args, ("@ронси",))
        self.assertEqual(typing.call_args_list[1].args, ("@ron",))
        self.assertEqual(draft.username, "RONfsy")
        self.assertEqual(locate.call_count, 3)
        self.assertEqual(pyauto.hotkey.call_count, 2)

    def test_no_visible_recipient_never_drafts_or_clicks(self):
        planner = mock.Mock()
        pyauto = types.SimpleNamespace(hotkey=mock.Mock())
        with (
            mock.patch.dict(sys.modules, {"pyautogui": pyauto}),
            mock.patch("luxai.discord_research.get_wikipedia_summary",
                       return_value=("text", "url")),
            mock.patch("luxai.discord_research.find_discord_window", return_value=42),
            mock.patch("luxai.discord_research.focus_discord"),
            mock.patch("luxai.desktop_actions._type_unicode_windows") as typing,
            mock.patch("luxai.visual_click.capture_window"),
            mock.patch("luxai.discord_contact_vision.locate_visible_contact",
                       return_value=None),
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.discord_research.time.sleep"),
        ):
            with self.assertRaisesRegex(ValueError, "не найден визуально"):
                prepare_discord_draft(planner, "Nikola Tesla||ронси")
        self.assertEqual(typing.call_count, 2)  # only search queries
        click.assert_not_called()

    def test_send_replaces_approved_draft_without_ocr_of_long_wikipedia_url(self):
        pyauto = types.SimpleNamespace(press=mock.Mock(), hotkey=mock.Mock())
        message = (
            "Тесла, Никола: краткая статья из Википедии. "
            "Источник: https://ru.wikipedia.org/wiki/%D0%A2%D0%B5%D1%81%D0%BB%D0%B0"
        )
        draft = DiscordDraft(44, "RONfsy", message, "url", (300, 800))
        current = mock.Mock(hwnd=44, pid=41, title="Discord")
        planner = mock.Mock()
        with (
            mock.patch.dict(sys.modules, {"pyautogui": pyauto}),
            mock.patch("luxai.discord_research.focus_discord") as focused,
            mock.patch("luxai.visual_click.capture_window", return_value=current) as capture,
            mock.patch("luxai.visual_click.find_visual_target",
                       return_value=(350, 790)) as locate,
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.desktop_actions._type_unicode_windows") as type_unicode,
            mock.patch("luxai.screen_interact._foreground_hwnd", return_value=44),
            mock.patch("luxai.screen_interact._valid_external_window",
                       return_value=(41, "Discord")),
        ):
            answer = submit_discord_draft(draft, planner)
        focused.assert_called_once_with(44)
        capture.assert_called_once_with(44)
        self.assertIn("RONfsy", locate.call_args.args[1])
        self.assertIn("BOTTOM MESSAGE COMPOSER", locate.call_args.args[1])
        self.assertIn("Do NOT try to OCR", locate.call_args.args[1])
        self.assertNotIn(message, locate.call_args.args[1])
        self.assertEqual(locate.call_args.args[2], current)
        click.assert_called_once_with(current, (350, 790), 1)
        pyauto.hotkey.assert_called_once_with("ctrl", "a", interval=0.07)
        type_unicode.assert_called_once_with(message)
        pyauto.press.assert_called_once_with("enter")
        self.assertIn("одобренного текста", answer)

    def test_send_aborts_on_uncertain_recipient_without_replacing_draft(self):
        draft = DiscordDraft(44, "RONfsy", "correct text", "url", (300, 800))
        pyauto = types.SimpleNamespace(press=mock.Mock(), hotkey=mock.Mock())
        with (
            mock.patch.dict(sys.modules, {"pyautogui": pyauto}),
            mock.patch("luxai.discord_research.focus_discord"),
            mock.patch("luxai.visual_click.capture_window"),
            mock.patch("luxai.visual_click.find_visual_target",
                       side_effect=ValueError("Control not found unambiguously")),
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.desktop_actions._type_unicode_windows") as typing,
        ):
            with self.assertRaisesRegex(ValueError, "unambiguously"):
                submit_discord_draft(draft, mock.Mock())
        click.assert_not_called()
        typing.assert_not_called()
        pyauto.hotkey.assert_not_called()
        pyauto.press.assert_not_called()

    def test_send_refuses_wrong_window_or_missing_vision_provider(self):
        draft = DiscordDraft(44, "RONfsy", "correct text", "url", (300, 800))
        pyauto = types.SimpleNamespace(press=mock.Mock(), hotkey=mock.Mock())
        with (
            mock.patch.dict(sys.modules, {"pyautogui": pyauto}),
            mock.patch("luxai.discord_research.focus_discord"),
            mock.patch("luxai.visual_click.capture_window",
                       side_effect=RuntimeError("Wrong foreground window")),
            mock.patch("luxai.visual_click.find_visual_target") as locate,
            mock.patch("luxai.desktop_actions._type_unicode_windows") as typing,
        ):
            with self.assertRaisesRegex(RuntimeError, "Wrong foreground"):
                submit_discord_draft(draft, mock.Mock())
        locate.assert_not_called()
        typing.assert_not_called()
        pyauto.press.assert_not_called()
        with self.assertRaisesRegex(ValueError, "vision-capable"):
            submit_discord_draft(draft, None)

    def test_send_cancelled_after_analysis_does_not_send_or_replace(self):
        draft = DiscordDraft(44, "RONfsy", "correct text", "url", (300, 800))
        pyauto = types.SimpleNamespace(press=mock.Mock(), hotkey=mock.Mock())
        cancellation = mock.Mock(side_effect=[False, True])
        with (
            mock.patch.dict(sys.modules, {"pyautogui": pyauto}),
            mock.patch("luxai.discord_research.focus_discord"),
            mock.patch("luxai.visual_click.capture_window"),
            mock.patch("luxai.visual_click.find_visual_target", return_value=(300, 800)),
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.desktop_actions._type_unicode_windows") as typing,
        ):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                submit_discord_draft(draft, mock.Mock(), cancelled=cancellation)
        click.assert_not_called()
        typing.assert_not_called()
        pyauto.press.assert_not_called()

    def test_send_never_presses_enter_if_retyping_fails(self):
        draft = DiscordDraft(44, "RONfsy", "correct text", "url", (300, 800))
        pyauto = types.SimpleNamespace(press=mock.Mock(), hotkey=mock.Mock())
        with (
            mock.patch.dict(sys.modules, {"pyautogui": pyauto}),
            mock.patch("luxai.discord_research.focus_discord"),
            mock.patch("luxai.visual_click.capture_window"),
            mock.patch("luxai.visual_click.find_visual_target", return_value=(320, 790)),
            mock.patch("luxai.visual_click.click_visual_target"),
            mock.patch("luxai.desktop_actions._type_unicode_windows",
                       side_effect=OSError("Windows rejected keyboard input")),
        ):
            with self.assertRaisesRegex(OSError, "rejected keyboard"):
                submit_discord_draft(draft, mock.Mock())
        pyauto.hotkey.assert_called_once()
        pyauto.press.assert_not_called()

    def test_send_never_presses_enter_if_discord_foreground_changed(self):
        draft = DiscordDraft(44, "RONfsy", "correct text", "url", (300, 800))
        pyauto = types.SimpleNamespace(press=mock.Mock(), hotkey=mock.Mock())
        with (
            mock.patch.dict(sys.modules, {"pyautogui": pyauto}),
            mock.patch("luxai.discord_research.focus_discord"),
            mock.patch("luxai.visual_click.capture_window"),
            mock.patch("luxai.visual_click.find_visual_target", return_value=(320, 790)),
            mock.patch("luxai.visual_click.click_visual_target"),
            mock.patch("luxai.desktop_actions._type_unicode_windows"),
            mock.patch("luxai.screen_interact._foreground_hwnd", return_value=72),
        ):
            with self.assertRaisesRegex(RuntimeError, "focus changed"):
                submit_discord_draft(draft, mock.Mock())
        pyauto.press.assert_not_called()

    def test_send_refuses_invalid_approved_draft_before_any_action(self):
        for text in ("", "  ", "line1\\nline2", "line1\\rline2"):
            with self.subTest(text=text), mock.patch(
                "luxai.discord_research.focus_discord"
            ) as focused:
                draft = DiscordDraft(44, "RONfsy", text, "url", (300, 800))
                with self.assertRaises(ValueError):
                    submit_discord_draft(draft, mock.Mock())
                focused.assert_not_called()


if __name__ == "__main__":
    unittest.main()
