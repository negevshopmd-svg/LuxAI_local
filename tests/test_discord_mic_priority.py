"""Regression tests for native Discord mic handling after live macro routing.

All tests use mocked desktop state and AI, never access a real Discord account.
"""
from __future__ import annotations

from pathlib import Path
import sys
import types
import unittest
from unittest import mock

from luxai.discord_mic_visual import click_discord_microphone_by_screenshot
from luxai.macro_planner import needs_live_macro_planning
from luxai.voice_desktop import wants_discord_mic_mute, wants_discord_mic_visual_click

VOICE = "Сделай снимок экрана и нажми на кнопку микрофона в дискорде."
MUTE = "Жарвис, выключи микрофон в Discord"


class DiscordMicIntentTests(unittest.TestCase):
    def test_actual_spoken_screenshot_and_mic_button_request(self):
        self.assertTrue(wants_discord_mic_visual_click(VOICE))
        # The generic planner used to seize this phrase before local handlers.
        self.assertTrue(needs_live_macro_planning(VOICE))
        self.assertTrue(wants_discord_mic_visual_click(
            "Жарвис сделай скриншот потом кликни на значок микрофона в Discord"
        ))
        self.assertFalse(wants_discord_mic_visual_click(
            "Найди пользователя в Discord и расскажи содержание чата"
        ))
        self.assertFalse(wants_discord_mic_visual_click(
            "Сделай снимок экрана потом отправь сообщение в Discord"
        ))
        self.assertTrue(wants_discord_mic_visual_click(MUTE))

    def test_plain_mute_uses_verified_visual_state(self):
        from luxai.voice_desktop import discord_mic_visual_mode
        self.assertFalse(wants_discord_mic_mute(MUTE))
        self.assertEqual(discord_mic_visual_mode(MUTE), "mute")
        self.assertEqual(discord_mic_visual_mode(
            "Отключи микрофон в дискорде"
        ), "mute")

    def test_spoken_button_mute_without_explicit_screenshot(self):
        from luxai.voice_desktop import discord_mic_visual_mode
        examples = [
            "Зайди в Discord и нажми на кнопку микрофона чтобы его выключить.",
            "Жарвис зайди в Дискорд нажми на кнопку микрофона чтобы выключить.",
            "Нажми в Discord на значок микрофона чтобы его отключить.",
        ]
        for phrase in examples:
            with self.subTest(phrase=phrase):
                self.assertEqual(discord_mic_visual_mode(phrase), "mute")
                self.assertTrue(wants_discord_mic_visual_click(phrase))
                self.assertFalse(wants_discord_mic_mute(phrase))
        self.assertEqual(discord_mic_visual_mode(VOICE), "toggle")
        self.assertEqual(discord_mic_visual_mode(
            "Открой Discord нажми на кнопку микрофона чтобы включить"
        ), "unmute")
        self.assertTrue(wants_discord_mic_visual_click(MUTE))

    def test_already_muted_never_clicks_or_unmutes(self):
        captured = mock.Mock(hwnd=45)
        with (
            mock.patch("luxai.discord_screen_review._ensure_discord_visible",
                       return_value=45),
            mock.patch("luxai.discord_screen_review.focus_discord"),
            mock.patch("luxai.discord_screen_review._save_capture"),
            mock.patch("luxai.visual_click.capture_window",
                       return_value=captured) as shot,
            mock.patch("luxai.discord_mic_visual.inspect_discord_microphone",
                       return_value=("muted", (420, 650))) as inspect,
            mock.patch("luxai.visual_click.click_visual_target") as click,
        ):
            result = click_discord_microphone_by_screenshot(
                mock.Mock(), mode="mute"
            )
        shot.assert_called_once_with(45)
        inspect.assert_called_once_with(mock.ANY, captured)
        click.assert_not_called()
        self.assertIn("уже выключен", result)

    def test_running_mic_is_clicked_once_and_final_state_verified(self):
        capture_before = mock.Mock(hwnd=45)
        capture_after = mock.Mock(hwnd=45)
        with (
            mock.patch("luxai.discord_screen_review._ensure_discord_visible",
                       return_value=45) as window,
            mock.patch("luxai.discord_screen_review.focus_discord") as focus,
            mock.patch("luxai.discord_screen_review._save_capture") as save,
            mock.patch("luxai.visual_click.capture_window",
                       side_effect=[capture_before, capture_after]) as shot,
            mock.patch("luxai.discord_mic_visual.inspect_discord_microphone",
                       side_effect=[
                           ("unmuted", (420, 650)),
                           ("muted", (420, 650)),
                       ]) as inspect,
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.discord_mic_visual.time.sleep"),
        ):
            result = click_discord_microphone_by_screenshot(
                mock.Mock(), mode="mute"
            )
        window.assert_called_once()
        self.assertEqual(focus.call_count, 2)
        self.assertEqual(shot.call_count, 2)
        self.assertEqual(save.call_args_list[0].args, (capture_before, "microphone_before"))
        self.assertEqual(save.call_args_list[1].args, (capture_after, "microphone_after"))
        self.assertEqual(inspect.call_count, 2)
        click.assert_called_once_with(capture_before, (420, 650), 1)
        self.assertIn("микрофон выключен", result)

    def test_unknown_state_does_not_toggle_when_user_asked_mute(self):
        with (
            mock.patch("luxai.discord_screen_review._ensure_discord_visible",
                       return_value=45),
            mock.patch("luxai.discord_screen_review.focus_discord"),
            mock.patch("luxai.discord_screen_review._save_capture"),
            mock.patch("luxai.visual_click.capture_window"),
            mock.patch("luxai.discord_mic_visual.inspect_discord_microphone",
                       return_value=("unknown", (420, 650))),
            mock.patch("luxai.visual_click.click_visual_target") as click,
        ):
            answer = click_discord_microphone_by_screenshot(
                mock.Mock(), mode="mute"
            )
        click.assert_not_called()
        self.assertIn("Не нажимал кнопку", answer)

    def test_unmute_already_enabled_does_not_click(self):
        with (
            mock.patch("luxai.discord_screen_review._ensure_discord_visible",
                       return_value=45),
            mock.patch("luxai.discord_screen_review.focus_discord"),
            mock.patch("luxai.discord_screen_review._save_capture"),
            mock.patch("luxai.visual_click.capture_window"),
            mock.patch("luxai.discord_mic_visual.inspect_discord_microphone",
                       return_value=("unmuted", (420, 650))),
            mock.patch("luxai.visual_click.click_visual_target") as click,
        ):
            answer = click_discord_microphone_by_screenshot(
                mock.Mock(), mode="unmute"
            )
        click.assert_not_called()
        self.assertIn("уже включён", answer)

    def test_ambiguous_button_never_clicks(self):
        with (
            mock.patch("luxai.discord_screen_review._ensure_discord_visible",
                       return_value=45),
            mock.patch("luxai.discord_screen_review.focus_discord"),
            mock.patch("luxai.discord_screen_review._save_capture"),
            mock.patch("luxai.visual_click.capture_window"),
            mock.patch("luxai.discord_mic_visual.inspect_discord_microphone",
                       side_effect=ValueError("Control not found unambiguously")),
            mock.patch("luxai.visual_click.click_visual_target") as click,
        ):
            with self.assertRaisesRegex(ValueError, "unambiguously"):
                click_discord_microphone_by_screenshot(mock.Mock(), mode="mute")
        click.assert_not_called()

    def test_after_click_uncertain_does_not_claim_muted(self):
        with (
            mock.patch("luxai.discord_screen_review._ensure_discord_visible",
                       return_value=45),
            mock.patch("luxai.discord_screen_review.focus_discord"),
            mock.patch("luxai.discord_screen_review._save_capture"),
            mock.patch("luxai.visual_click.capture_window"),
            mock.patch("luxai.discord_mic_visual.inspect_discord_microphone",
                       side_effect=[
                           ("unmuted", (420, 650)),
                           ValueError("Control not found unambiguously"),
                       ]),
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.discord_mic_visual.time.sleep"),
        ):
            answer = click_discord_microphone_by_screenshot(
                mock.Mock(), mode="mute"
            )
        click.assert_called_once()
        self.assertIn("подтвердить не удалось", answer)

    def test_cancellation_prevents_cloud_call_and_click(self):
        with (
            mock.patch("luxai.discord_screen_review._ensure_discord_visible",
                       return_value=45),
            mock.patch("luxai.discord_screen_review.focus_discord"),
            mock.patch("luxai.discord_screen_review._save_capture"),
            mock.patch("luxai.visual_click.capture_window") as shot,
            mock.patch("luxai.discord_mic_visual.inspect_discord_microphone") as locate,
            mock.patch("luxai.visual_click.click_visual_target") as click,
        ):
            with self.assertRaisesRegex(RuntimeError, "отменена"):
                click_discord_microphone_by_screenshot(
                    mock.Mock(), mode="mute", cancelled=lambda: True,
                )
        shot.assert_not_called()
        locate.assert_not_called()
        click.assert_not_called()


class DiscordMicPriorityUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("Qt is unavailable")
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self):
        import main
        import tempfile
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        config = Path(root.name) / "config.json"
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
        window.online_planner.enabled = mock.Mock(return_value=True)
        return window

    def test_visual_mic_request_never_enters_generic_cloud_macro(self):
        import main
        window = self.make_window()
        with (
            mock.patch.object(window, "_start_discord_mic_visual") as visual,
            mock.patch.object(window, "_direct_macro_worker") as macro,
            mock.patch.object(main.threading, "Thread") as thread,
            mock.patch.object(window.online_planner, "plan_macro") as cloud,
        ):
            window.run_command(VOICE)
        visual.assert_called_once_with(VOICE)
        macro.assert_not_called()
        cloud.assert_not_called()
        thread.assert_not_called()

    def test_explicit_button_to_mute_routes_to_visual_not_ctrl_shift_m(self):
        import main
        phrase = "Зайди в Discord и нажми на кнопку микрофона чтобы его выключить."
        window = self.make_window()
        window.command_registry.match = mock.Mock(return_value={
            "action": "open_app", "target": "discord", "steps": []
        })
        with (
            mock.patch.object(window, "_start_discord_mic_visual") as visual,
            mock.patch.object(window, "_execute_registered") as learned,
            mock.patch.object(main, "toggle_discord_microphone") as keyboard,
            mock.patch.object(main.threading, "Thread") as thread,
        ):
            window.run_command(phrase)
        visual.assert_called_once_with(phrase)
        keyboard.assert_not_called()
        learned.assert_not_called()
        thread.assert_not_called()

    def test_visual_consent_refusal_never_uploads_or_clicks(self):
        window = self.make_window()
        with (
            mock.patch.object(window, "confirm_action",
                              return_value=False) as confirm,
            mock.patch.object(window, "_resolved_command") as resolved,
            mock.patch("main.threading.Thread") as thread,
        ):
            window._start_discord_mic_visual(VOICE)
        self.assertIn("до закрытия Jarvis", confirm.call_args.args[0])
        self.assertIn("отменено", resolved.call_args.args[1])
        thread.assert_not_called()

    def test_plain_mute_never_hits_toggle_or_old_macro(self):
        import main
        window = self.make_window()
        with (
            mock.patch.object(window, "_start_discord_mic_visual") as visual,
            mock.patch.object(main, "toggle_discord_microphone") as keyboard,
            mock.patch.object(window, "_execute_registered") as learned,
            mock.patch("main.threading.Thread") as thread,
        ):
            window.run_command(MUTE)
        visual.assert_called_once_with(MUTE)
        keyboard.assert_not_called()
        learned.assert_not_called()
        thread.assert_not_called()


if __name__ == "__main__":
    unittest.main()
