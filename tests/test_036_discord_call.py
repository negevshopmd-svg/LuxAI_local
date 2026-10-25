"""Offline regression tests for one-command Discord voice calls (0.3.6).

No test places a real Discord call, accesses an account, or uploads a screenshot.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from luxai.discord_call_visual import (
    detect_discord_call_request, call_discord_user, _locate_voice_call_button,
    _observe_call_state,
)
from luxai.visual_click import VisualCapture


def shot():
    return VisualCapture(
        hwnd=33, pid=44, title="Discord", left=0, top=0,
        width=1522, height=990, image_width=1522, image_height=990,
        jpeg=b"mock-image",
    )


class DiscordCallIntentTests(unittest.TestCase):
    def test_implicit_call_from_single_natural_command_in_three_languages(self):
        expected = {
            "Позвони пользователю RomC в дискорде.": "RomC",
            "Позвони Hanzo в Discord": "Hanzo",
            "Можешь позвонить Hanzo в Discord?": "Hanzo",
            "Позвони в Discord пользователю Hanzo": "Hanzo",
            "Жарвис, позвони пользователю Hanzo в дискорде": "Hanzo",
            "Sună-l pe Hanzo în Discord": "Hanzo",
            "Suna pe Hanzo in Discord!": "Hanzo",
            "Apelează-l pe Hanzo în Discord": "Hanzo",
            "Call Hanzo on Discord": "Hanzo",
            "Call user RomC in Discord": "RomC",
        }
        for command, name in expected.items():
            with self.subTest(command=command):
                self.assertEqual(detect_discord_call_request(command), name)

    def test_no_phone_call_for_questions_negations_other_apps_or_extra_tasks(self):
        for command in (
            "Как позвонить Hanzo в Discord?",
            "Не звони Hanzo в Discord.",
            "Не надо звонить пользователю Hanzo в Discord",
            "Don't call Hanzo on Discord",
            "Nu suna pe Hanzo în Discord",
            "Позвони в Telegram пользователю Hanzo",
            "Открой Discord", "Нажми на телефон в Discord",
            "Набери номер телефона в Discord",
            "Позвони Hanzo в Discord, потом отправь сообщение",
            "Позвони Hanzo в Discord и напиши привет",
            "Включи видеозвонок Hanzo в Discord",
            "Позвони пользователю GhostOX, Hanzo в Discord",
            "Позвони в группу друзей в Discord",
        ):
            with self.subTest(command=command):
                self.assertIsNone(detect_discord_call_request(command))


class DiscordCallVisualTests(unittest.TestCase):
    def test_correct_phone_is_found_in_upper_individual_dm_header(self):
        point = (1134, 56)
        with mock.patch("luxai.visual_click.find_visual_target",
                        return_value=point) as find:
            self.assertEqual(_locate_voice_call_button(mock.Mock(), shot()), point)
        self.assertTrue(find.call_args.kwargs["precise"])
        prompt = find.call_args.args[1]
        self.assertIn("VOICE CALL HANDSET", prompt)
        self.assertIn("VIDEO CAMERA", prompt)
        self.assertIn("group or channel", prompt)

    def test_phone_icon_in_chat_history_or_sidebar_is_rejected(self):
        for point in ((300, 55), (1134, 650), (1515, 55)):
            with self.subTest(point=point):
                with mock.patch("luxai.visual_click.find_visual_target",
                                return_value=point):
                    with self.assertRaisesRegex(ValueError, "top header"):
                        _locate_voice_call_button(mock.Mock(), shot())

    def test_one_command_opens_verified_dm_and_calls_once_then_checks_ringing(self):
        capture = shot()
        with (
            mock.patch("luxai.discord_navigation.open_discord_contact",
                       return_value="Discord: открыт чат Hanzo") as opened,
            mock.patch("luxai.discord_screen_review._ensure_discord_visible",
                       return_value=33),
            mock.patch("luxai.discord_research.focus_discord") as focus,
            mock.patch("luxai.discord_navigation._chat_header_ok",
                       return_value=capture) as header,
            mock.patch("luxai.discord_call_visual._observe_call_state",
                       side_effect=["idle", "idle", "ringing"]) as state,
            mock.patch("luxai.discord_call_visual._locate_voice_call_button",
                       side_effect=[(1134, 56), (1135, 56)]) as phone,
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.visual_click.capture_window",
                       return_value=capture) as after,
            mock.patch("luxai.discord_call_visual.time.sleep"),
        ):
            result = call_discord_user(mock.Mock(), "Hanzo")
        self.assertIn("ожидаю ответа", result)
        opened.assert_called_once()
        self.assertEqual(opened.call_args.args[1], "Hanzo")
        self.assertEqual(header.call_count, 2)
        self.assertEqual(state.call_count, 3)
        self.assertEqual(phone.call_count, 2)
        click.assert_called_once_with(capture, (1135, 56), 1)
        after.assert_called_once_with(33)
        self.assertGreaterEqual(focus.call_count, 2)

    def test_already_ringing_never_places_second_call(self):
        with (
            mock.patch("luxai.discord_navigation.open_discord_contact"),
            mock.patch("luxai.discord_screen_review._ensure_discord_visible", return_value=33),
            mock.patch("luxai.discord_research.focus_discord"),
            mock.patch("luxai.discord_navigation._chat_header_ok", return_value=shot()),
            mock.patch("luxai.discord_call_visual._observe_call_state", return_value="ringing"),
            mock.patch("luxai.discord_call_visual._locate_voice_call_button") as phone,
            mock.patch("luxai.visual_click.click_visual_target") as click,
        ):
            result = call_discord_user(mock.Mock(), "Hanzo")
        self.assertIn("уже идёт", result)
        click.assert_not_called()
        phone.assert_not_called()

    def test_unknown_pre_click_state_does_not_place_call(self):
        with (
            mock.patch("luxai.discord_navigation.open_discord_contact"),
            mock.patch("luxai.discord_screen_review._ensure_discord_visible", return_value=33),
            mock.patch("luxai.discord_research.focus_discord"),
            mock.patch("luxai.discord_navigation._chat_header_ok", return_value=shot()),
            mock.patch("luxai.discord_call_visual._observe_call_state", return_value="unknown"),
            mock.patch("luxai.visual_click.click_visual_target") as click,
        ):
            result = call_discord_user(mock.Mock(), "Hanzo")
        self.assertIn("неясно", result)
        click.assert_not_called()

    def test_relocation_of_phone_button_cancels_before_click(self):
        with (
            mock.patch("luxai.discord_navigation.open_discord_contact"),
            mock.patch("luxai.discord_screen_review._ensure_discord_visible", return_value=33),
            mock.patch("luxai.discord_research.focus_discord"),
            mock.patch("luxai.discord_navigation._chat_header_ok", return_value=shot()),
            mock.patch("luxai.discord_call_visual._observe_call_state",
                       side_effect=["idle", "idle"]),
            mock.patch("luxai.discord_call_visual._locate_voice_call_button",
                       side_effect=[(1134, 56), (1190, 56)]),
            mock.patch("luxai.visual_click.click_visual_target") as click,
        ):
            with self.assertRaisesRegex(ValueError, "moved"):
                call_discord_user(mock.Mock(), "Hanzo")
        click.assert_not_called()

    def test_fresh_state_changed_pre_click_aborts_without_click(self):
        with (
            mock.patch("luxai.discord_navigation.open_discord_contact"),
            mock.patch("luxai.discord_screen_review._ensure_discord_visible", return_value=33),
            mock.patch("luxai.discord_research.focus_discord"),
            mock.patch("luxai.discord_navigation._chat_header_ok", return_value=shot()),
            mock.patch("luxai.discord_call_visual._observe_call_state",
                       side_effect=["idle", "ringing"]),
            mock.patch("luxai.discord_call_visual._locate_voice_call_button",
                       return_value=(1134, 56)),
            mock.patch("luxai.visual_click.click_visual_target") as click,
        ):
            result = call_discord_user(mock.Mock(), "Hanzo")
        self.assertIn("изменилось", result)
        click.assert_not_called()

    def test_after_click_idle_not_reported_as_success_and_never_redials(self):
        with (
            mock.patch("luxai.discord_navigation.open_discord_contact"),
            mock.patch("luxai.discord_screen_review._ensure_discord_visible", return_value=33),
            mock.patch("luxai.discord_research.focus_discord"),
            mock.patch("luxai.discord_navigation._chat_header_ok", return_value=shot()),
            mock.patch("luxai.discord_call_visual._observe_call_state",
                       side_effect=["idle", "idle", "idle"]),
            mock.patch("luxai.discord_call_visual._locate_voice_call_button",
                       return_value=(1134, 56)),
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.visual_click.capture_window", return_value=shot()),
            mock.patch("luxai.discord_call_visual.time.sleep"),
        ):
            result = call_discord_user(mock.Mock(), "Hanzo")
        self.assertIn("не подтверждено", result)
        click.assert_called_once()

    def test_contact_header_must_verify_before_phone_is_ever_clicked(self):
        with (
            mock.patch("luxai.discord_navigation.open_discord_contact",
                       side_effect=ValueError("Wrong DM header")),
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.discord_call_visual._locate_voice_call_button") as locate,
        ):
            with self.assertRaisesRegex(ValueError, "Wrong DM"):
                call_discord_user(mock.Mock(), "Hanzo")
        click.assert_not_called()
        locate.assert_not_called()

    def test_status_uses_live_call_controls_not_call_history(self):
        planner = mock.Mock()
        planner._provider.return_value = "openai"
        planner.enabled.return_value = True
        planner.config = {"online_model": "gpt-4.1-mini"}
        planner._extract_text.return_value = '{"state":"ringing"}'
        planner._read_json_content.return_value = {"state": "ringing"}
        with mock.patch("luxai.secure_keys.get_api_key", return_value="test-key"):
            result = _observe_call_state(planner, shot(), "Hanzo")
        self.assertEqual(result, "ringing")
        prompt = planner._request.call_args.args[3][1]["content"][0]["text"]
        self.assertIn("call-history messages", prompt)
        self.assertIn("hang-up", prompt)


class DiscordCallMainRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("PySide6 not installed")
        cls.app = QApplication.instance() or QApplication([])

    def window(self):
        import main
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        cfg = Path(temp.name) / "config.json"
        cfg.write_text(
            '{"microphone_enabled":false,"tts_enabled":false,'
            '"online_agent_enabled":false}', encoding="utf-8",
        )
        patch = mock.patch.object(main, "CONFIG", cfg)
        patch.start()
        self.addCleanup(patch.stop)
        with mock.patch("sounddevice.query_devices", return_value=[]):
            window = main.MainWindow()
        self.addCleanup(window.close)
        return window

    def test_natural_voice_call_is_not_downgraded_to_generic_planner(self):
        for text in (
            "Позвони пользователю RomC в дискорде.",
            "Позвони Hanzo в Discord",
            "Sună-l pe Hanzo în Discord",
        ):
            with self.subTest(text=text):
                window = self.window()
                with (
                    mock.patch.object(window, "_start_discord_call_visual") as call,
                    mock.patch.object(window, "_start_adaptive_task") as planner,
                    mock.patch.object(window, "_execute_registered") as saved,
                    mock.patch.object(window, "_run_direct_input") as local,
                ):
                    window.run_command(text)
                call.assert_called_once_with(text, detect_discord_call_request(text))
                planner.assert_not_called()
                saved.assert_not_called()
                local.assert_not_called()

    def test_cloud_screenshot_permission_denial_does_not_call_contact(self):
        window = self.window()
        window.online_planner.enabled = mock.Mock(return_value=True)
        with (
            mock.patch.object(window, "_allow_cloud_screenshots", return_value=False),
            mock.patch.object(window, "_resolved_command") as result,
            mock.patch("main.threading.Thread") as thread,
            mock.patch("luxai.discord_navigation.open_discord_contact") as open_dm,
        ):
            window._start_discord_call_visual("Позвони Hanzo в Discord", "Hanzo")
        thread.assert_not_called()
        open_dm.assert_not_called()
        self.assertIn("отменён", result.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
