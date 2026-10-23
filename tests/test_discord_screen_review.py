"""Regression tests for multi-stage Discord visual requests; no real account/screen."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

from luxai.action_catalog import validate_step
from luxai.discord_screen_review import (
    detect_discord_screen_review, looks_like_discord_screen_review,
    validate_discord_review_user,
    run_discord_screen_review, summarize_discord_capture,
)
from luxai.macro_planner import needs_live_macro_planning, validate_generated_macro

VOICE = (
    "жарис открой дискорд потом сделай снимок экрана дискорда "
    "после этого найди пользователя октавиан после этого сделай "
    "снимок экрана после сделай краткий пересказ этого снимок экрана"
)
VOICE_MISHEARD = (
    "Откроете Скопт, потом сделайте снимок экрана, найдите "
    "пользователя Старый Бог, после этого в переписке сделайте "
    "снимок экрана и сделайте краткое содержимое."
)
VOICE_UNCERTAIN_APP = VOICE_MISHEARD.replace("Скопт", "Сквар")
VOICE_FROM_NEW_SCREENSHOT = (
    "жарис открой дискорд сделай снимок экрана найди там пользователя "
    "старый бог нажми на него потом сделай еще один снимок экрана "
    "потом сделай ей краткое расскажи краткое содержание чата"
)


class ReviewRoutingTests(unittest.TestCase):
    def test_actual_whisper_transcript_is_one_ordered_macro(self):
        from luxai.fast_intents import strip_wake_name
        self.assertTrue(strip_wake_name(VOICE).startswith("открой дискорд"))
        self.assertEqual(detect_discord_screen_review(VOICE), "октавиан")
        self.assertTrue(needs_live_macro_planning(VOICE))
        self.assertEqual(
            validate_generated_macro({
                "steps": [{"action": "discord_screen_review", "target": "октавиан"}],
            }, VOICE)["steps"][0]["action"], "discord_screen_review",
        )
        self.assertEqual(validate_step({
            "action": "discord_screen_review", "target": "октавиан"
        })["target"], "октавиан")

    def test_latest_whisper_transcript_preserves_display_name_and_all_steps(self):
        self.assertEqual(detect_discord_screen_review(VOICE_MISHEARD), "Старый Бог")
        self.assertTrue(looks_like_discord_screen_review(VOICE_MISHEARD))
        self.assertTrue(needs_live_macro_planning(VOICE_MISHEARD))
        self.assertEqual(validate_discord_review_user("Старый Бог"), "Старый Бог")
        planned = validate_generated_macro({
            "steps": [{"action": "discord_screen_review", "target": "Старый Бог"}],
        }, VOICE_MISHEARD)
        self.assertEqual(planned["steps"][0]["target"], "Старый Бог")
        self.assertIsNone(validate_generated_macro({
            "steps": [{"action": "open_app", "target": "discord"}],
        }, VOICE_MISHEARD))
        self.assertIsNone(validate_generated_macro({
            "steps": [{"action": "discord_screen_review", "target": "Старый"}],
        }, VOICE_MISHEARD))

    def test_latest_spoken_command_with_tam_and_click_is_one_verified_workflow(self):
        # Exact failed Whisper transcript: previously hit the generic cloud
        # macro planner and "AI did not provide a complete supported sequence."
        self.assertEqual(
            detect_discord_screen_review(VOICE_FROM_NEW_SCREENSHOT),
            "старый бог",
        )
        self.assertTrue(looks_like_discord_screen_review(VOICE_FROM_NEW_SCREENSHOT))
        self.assertTrue(needs_live_macro_planning(VOICE_FROM_NEW_SCREENSHOT))
        valid = validate_generated_macro({
            "steps": [{"action": "discord_screen_review", "target": "старый бог"}],
        }, VOICE_FROM_NEW_SCREENSHOT)
        self.assertEqual(valid["steps"][0]["target"], "старый бог")
        # No incomplete launcher-only or unsafely guessed GUI click proposals.
        self.assertIsNone(validate_generated_macro({
            "steps": [{"action": "open_app", "target": "discord"}]
        }, VOICE_FROM_NEW_SCREENSHOT))
        self.assertIsNone(validate_generated_macro({
            "steps": [{"action": "visual_click", "target": "старый бог||1"}],
        }, VOICE_FROM_NEW_SCREENSHOT))

    def test_spoken_mouse_action_is_not_part_of_contact_name(self):
        variants = [
            "найди там пользователя старый бог нажми на него потом",
            "найди пользователя Старый Бог и нажми на него",
            "найди здесь пользователя старый бог кликни по нему",
            "найди пользователя старый бог, нажми на него",
        ]
        from luxai.discord_screen_review import _USER_RE
        for phrase in variants:
            with self.subTest(phrase=phrase):
                match = _USER_RE.search(phrase)
                self.assertIsNotNone(match)
                self.assertEqual(match.group("name").casefold(), "старый бог")

    def test_unknown_app_keeps_request_together_and_requires_clarification(self):
        self.assertTrue(looks_like_discord_screen_review(VOICE_UNCERTAIN_APP))
        self.assertTrue(needs_live_macro_planning(VOICE_UNCERTAIN_APP))
        self.assertIsNone(detect_discord_screen_review(VOICE_UNCERTAIN_APP))
        self.assertIsNone(validate_generated_macro({
            "steps": [{"action": "open_app", "target": "discord"}],
        }, VOICE_UNCERTAIN_APP))
        self.assertIsNone(detect_discord_screen_review(
            VOICE_MISHEARD + " и отправь сообщение"
        ))

    def test_no_standalone_inspection_and_no_partial_cloud_plan(self):
        from luxai.screen_interact import is_screen_inspection_request
        self.assertTrue(is_screen_inspection_request(VOICE))
        for steps in (
            [{"action": "open_app", "target": "discord"}],
            [{"action": "visual_click", "target": "октавиан||1"}],
            [{"action": "discord_screen_review", "target": "другой"}],
        ):
            self.assertIsNone(validate_generated_macro({"steps": steps}, VOICE))
        self.assertIsNone(validate_generated_macro({
            "steps": [{"action": "discord_screen_review", "target": "октавиан"}]
        }, "Открой Discord"))

    def test_user_requires_clear_target_and_no_send_intent(self):
        for phrase in (
            "открой Discord потом сделай снимок экрана",
            "найди пользователя октавиан",
            VOICE + " и отправь сообщение",
        ):
            self.assertIsNone(detect_discord_screen_review(phrase))
        for username in ("x", "../bad", "more than four words user label", "a\nb", ""):
            with self.subTest(username=username), self.assertRaises(ValueError):
                validate_discord_review_user(username)


class ReviewWorkflowTests(unittest.TestCase):
    def test_opens_correct_window_and_summarizes_only_second_capture(self):
        planner = mock.Mock()
        first = mock.Mock(hwnd=55, jpeg=b"first")
        search = mock.Mock(hwnd=55, jpeg=b"search")
        last = mock.Mock(hwnd=55, jpeg=b"last")
        gui = types.SimpleNamespace(hotkey=mock.Mock(), press=mock.Mock())
        with (
            mock.patch.dict(sys.modules, {"pyautogui": gui}),
            mock.patch("luxai.discord_screen_review._ensure_discord_visible",
                       return_value=55) as ensure,
            mock.patch("luxai.discord_screen_review.focus_discord") as focus,
            mock.patch("luxai.visual_click.capture_window",
                       side_effect=[first, search, last]) as capture,
            mock.patch("luxai.discord_screen_review._save_capture",
                       side_effect=[Path("first.jpg"), Path("second.jpg")]) as save,
            mock.patch("luxai.discord_screen_review._type_not_real", create=True),
            mock.patch("luxai.desktop_actions._type_unicode_windows") as write,
            mock.patch("luxai.visual_click.find_visual_target",
                       side_effect=[(210, 100), (340, 75)]) as locate,
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.discord_screen_review.summarize_discord_capture",
                       return_value="В окне видна переписка.") as summary,
            mock.patch("luxai.discord_screen_review.time.sleep"),
        ):
            answer = run_discord_screen_review(planner, "октавиан")
        ensure.assert_called_once()
        focus.assert_called_once_with(55)
        self.assertEqual(capture.call_count, 3)
        self.assertEqual(save.call_args_list[0].args, (first, "before"))
        self.assertEqual(save.call_args_list[1].args, (last, "after"))
        gui.hotkey.assert_called_once_with("ctrl", "k", interval=0.07)
        write.assert_called_once_with("@октавиан")
        self.assertEqual(locate.call_count, 2)
        self.assertIn("exact Discord username OR display name 'октавиан'", locate.call_args_list[0].args[1])
        self.assertIn("searched user 'октавиан'", locate.call_args_list[1].args[1])
        click.assert_called_once_with(search, (210, 100), 1)
        summary.assert_called_once_with(planner, last)
        gui.press.assert_not_called()
        self.assertIn("first.jpg", answer)
        self.assertIn("second.jpg", answer)

    def test_multiword_display_name_sent_only_to_discord_search_not_to_chat(self):
        planner = mock.Mock()
        capture = mock.Mock(hwnd=55)
        gui = types.SimpleNamespace(hotkey=mock.Mock(), press=mock.Mock())
        with (
            mock.patch.dict(sys.modules, {"pyautogui": gui}),
            mock.patch("luxai.discord_screen_review._ensure_discord_visible", return_value=55),
            mock.patch("luxai.discord_screen_review.focus_discord"),
            mock.patch("luxai.visual_click.capture_window", return_value=capture),
            mock.patch("luxai.discord_screen_review._save_capture", return_value=Path("file.jpg")),
            mock.patch("luxai.desktop_actions._type_unicode_windows") as write,
            mock.patch("luxai.visual_click.find_visual_target", return_value=(300, 120)) as find,
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.discord_screen_review.summarize_discord_capture",
                       return_value="Виден чат.") as summarize,
            mock.patch("luxai.discord_screen_review.time.sleep"),
        ):
            result = run_discord_screen_review(planner, "Старый Бог")
        write.assert_called_once_with("@Старый Бог")
        self.assertIn("Старый Бог", find.call_args_list[0].args[1])
        self.assertIn("Старый Бог", find.call_args_list[1].args[1])
        click.assert_called_once()
        gui.press.assert_not_called()
        summarize.assert_called_once()
        self.assertIn("Старый Бог", result)

    def test_ambiguous_user_never_generates_fake_summary_or_types_message(self):
        planner = mock.Mock()
        gui = types.SimpleNamespace(hotkey=mock.Mock(), press=mock.Mock())
        with (
            mock.patch.dict(sys.modules, {"pyautogui": gui}),
            mock.patch("luxai.discord_screen_review._ensure_discord_visible",
                       return_value=55),
            mock.patch("luxai.discord_screen_review.focus_discord"),
            mock.patch("luxai.visual_click.capture_window") as capture,
            mock.patch("luxai.discord_screen_review._save_capture",
                       return_value=Path("first.jpg")) as save,
            mock.patch("luxai.desktop_actions._type_unicode_windows") as type_unicode,
            mock.patch("luxai.visual_click.find_visual_target",
                       side_effect=ValueError("Control not found unambiguously")),
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.discord_screen_review.summarize_discord_capture") as summarize,
            mock.patch("luxai.discord_screen_review.time.sleep"),
        ):
            with self.assertRaisesRegex(ValueError, "unambiguously"):
                run_discord_screen_review(planner, "октавиан")
        self.assertEqual(capture.call_count, 2)
        save.assert_called_once()
        type_unicode.assert_called_once_with("@октавиан")
        click.assert_not_called()
        summarize.assert_not_called()
        gui.press.assert_not_called()

    def test_cancellation_before_search_prevents_cloud_and_click(self):
        planner = mock.Mock()
        with (
            mock.patch.dict(sys.modules, {"pyautogui": types.SimpleNamespace(
                hotkey=mock.Mock())}),
            mock.patch("luxai.discord_screen_review._ensure_discord_visible",
                       return_value=55),
            mock.patch("luxai.discord_screen_review.focus_discord"),
            mock.patch("luxai.visual_click.capture_window") as capture,
            mock.patch("luxai.discord_screen_review._save_capture",
                       return_value=Path("first.jpg")),
            mock.patch("luxai.visual_click.find_visual_target") as locate,
            mock.patch("luxai.visual_click.click_visual_target") as click,
        ):
            cancelled = mock.Mock(side_effect=[False, False, True])
            with self.assertRaisesRegex(RuntimeError, "отменена"):
                run_discord_screen_review(planner, "октавиан",
                                          cancelled=cancelled)
        capture.assert_called_once()
        locate.assert_not_called()
        click.assert_not_called()

    def test_image_summary_is_json_and_cannot_invent_a_success_message(self):
        planner = mock.Mock()
        planner.enabled.return_value = True
        planner._provider.return_value = "openai"
        planner.config = {"online_model": "gpt-4.1-mini", "online_timeout": 40}
        planner._extract_text.return_value = '{"summary":"Виден чат Discord."}'
        planner._read_json_content.side_effect = json.loads
        capture = mock.Mock(jpeg=b"fake", image_width=100, image_height=60)
        with mock.patch("luxai.secure_keys.get_api_key", return_value="dummy"):
            response = summarize_discord_capture(planner, capture)
        self.assertEqual(response, "Виден чат Discord.")
        args = planner._request.call_args.args
        self.assertEqual(args[0], "openai")
        self.assertIn("untrusted DATA", args[3][0]["content"])
        self.assertIn("image_url", args[3][1]["content"][1])
        planner._extract_text.return_value = '{"summary":""}'
        with mock.patch("luxai.secure_keys.get_api_key", return_value="dummy"):
            with self.assertRaisesRegex(ValueError, "не смог"):
                summarize_discord_capture(planner, capture)


class ScreenRoutingUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("PySide6 not installed")
        cls.app = QApplication.instance() or QApplication([])

    def build_window(self):
        import main
        import tempfile
        from pathlib import Path
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        config = Path(temporary.name) / "config.json"
        config.write_text(
            '{"microphone_enabled":false,"tts_enabled":false,'
            '"online_agent_enabled":false}', encoding="utf-8",
        )
        with (
            mock.patch.object(main, "CONFIG", config),
            mock.patch("sounddevice.query_devices", return_value=[]),
        ):
            window = main.MainWindow()
        self.addCleanup(window.close)
        return window

    def test_full_command_starts_macro_instead_of_inspecting_buttons(self):
        import main
        window = self.build_window()
        window.online_planner.enabled = mock.Mock(return_value=True)
        with (
            mock.patch.object(window, "_start_screen_inspection") as screen,
            mock.patch.object(window, "_direct_task_worker") as ocr,
            mock.patch.object(main.threading, "Thread") as thread,
        ):
            window.run_command(VOICE)
        screen.assert_not_called()
        ocr.assert_not_called()
        thread.assert_called_once()
        self.assertEqual(
            thread.call_args.kwargs["target"], window._direct_macro_worker,
        )
        self.assertEqual(thread.call_args.kwargs["args"], (VOICE,))

    def test_misheard_app_still_routes_to_macro_not_chatbot(self):
        import main
        window = self.build_window()
        window.online_planner.enabled = mock.Mock(return_value=True)
        with (
            mock.patch.object(window, "_start_screen_inspection") as screen,
            mock.patch.object(main.threading, "Thread") as thread,
            mock.patch.object(window, "_online_thread") as chatbot,
        ):
            window.run_command(VOICE_MISHEARD)
        screen.assert_not_called()
        chatbot.assert_not_called()
        thread.assert_called_once()
        self.assertEqual(
            thread.call_args.kwargs["target"], window._direct_macro_worker,
        )
        self.assertEqual(thread.call_args.kwargs["args"], (VOICE_MISHEARD,))

    def test_current_voice_phrase_runs_dedicated_macro_not_cloud_generation(self):
        import main
        window = self.build_window()
        window.online_planner.enabled = mock.Mock(return_value=True)
        with (
            mock.patch.object(main.threading, "Thread") as thread,
            mock.patch.object(window, "_start_screen_inspection") as screen,
            mock.patch.object(window.online_planner, "plan_macro") as cloud,
        ):
            window.run_command(VOICE_FROM_NEW_SCREENSHOT)
        screen.assert_not_called()
        cloud.assert_not_called()
        thread.assert_called_once()
        self.assertEqual(thread.call_args.kwargs["args"], (VOICE_FROM_NEW_SCREENSHOT,))

        # Verify actual worker processing bypasses open-ended cloud proposal
        # and produces the dedicated, locally validated action.
        with (
            mock.patch.object(window.online_planner, "plan_macro") as cloud,
            mock.patch.object(window.direct_macro_ready, "emit") as emitted,
        ):
            window._direct_macro_worker(VOICE_FROM_NEW_SCREENSHOT)
        cloud.assert_not_called()
        self.assertEqual(
            emitted.call_args.args[1]["steps"][0]["action"],
            "discord_screen_review",
        )

    def test_no_cloud_does_not_start_wrong_screen_inspection(self):
        window = self.build_window()
        window.online_planner.enabled = mock.Mock(return_value=False)
        with (
            mock.patch.object(window, "_start_screen_inspection") as screen,
            mock.patch.object(window, "_resolved_command") as result,
        ):
            window.run_command(VOICE)
        screen.assert_not_called()
        result.assert_called_once()
        self.assertIn("нескольких шагов не выполнена", result.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
