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
        self.assertFalse(wants_discord_mic_visual_click(MUTE))

    def test_existing_mute_shortcut_is_still_recognized(self):
        self.assertTrue(wants_discord_mic_mute(MUTE))
        self.assertTrue(wants_discord_mic_mute(
            "Отключи микрофон в дискорде"
        ))

    def test_click_targets_only_verified_discord_window_and_mic(self):
        capture = mock.Mock(hwnd=45)
        planner = mock.Mock()
        with (
            mock.patch("luxai.discord_screen_review._ensure_discord_visible",
                       return_value=45) as window,
            mock.patch("luxai.discord_screen_review.focus_discord") as focus,
            mock.patch("luxai.discord_screen_review._save_capture",
                       return_value=Path("discord_microphone.jpg")) as save,
            mock.patch("luxai.visual_click.capture_window",
                       return_value=capture) as shot,
            mock.patch("luxai.visual_click.find_visual_target",
                       return_value=(420, 650)) as locate,
            mock.patch("luxai.visual_click.click_visual_target") as click,
        ):
            result = click_discord_microphone_by_screenshot(planner)
        window.assert_called_once()
        focus.assert_called_once_with(45)
        shot.assert_called_once_with(45)
        save.assert_called_once_with(capture, "microphone")
        self.assertIn("Discord desktop microphone", locate.call_args.args[1])
        self.assertEqual(locate.call_args.args[2], capture)
        click.assert_called_once_with(capture, (420, 650), 1)
        self.assertIn("состояние микрофона не подтверждено", result)

    def test_ambiguous_button_never_clicks(self):
        with (
            mock.patch("luxai.discord_screen_review._ensure_discord_visible",
                       return_value=45),
            mock.patch("luxai.discord_screen_review.focus_discord"),
            mock.patch("luxai.discord_screen_review._save_capture",
                       return_value=Path("local.jpg")),
            mock.patch("luxai.visual_click.capture_window"),
            mock.patch("luxai.visual_click.find_visual_target",
                       side_effect=ValueError("Control not found unambiguously")),
            mock.patch("luxai.visual_click.click_visual_target") as click,
        ):
            with self.assertRaisesRegex(ValueError, "unambiguously"):
                click_discord_microphone_by_screenshot(mock.Mock())
        click.assert_not_called()

    def test_cancellation_prevents_cloud_call_and_click(self):
        with (
            mock.patch("luxai.discord_screen_review._ensure_discord_visible",
                       return_value=45),
            mock.patch("luxai.discord_screen_review.focus_discord"),
            mock.patch("luxai.discord_screen_review._save_capture",
                       return_value=Path("local.jpg")),
            mock.patch("luxai.visual_click.capture_window") as shot,
            mock.patch("luxai.visual_click.find_visual_target") as locate,
            mock.patch("luxai.visual_click.click_visual_target") as click,
        ):
            with self.assertRaisesRegex(RuntimeError, "отменена"):
                click_discord_microphone_by_screenshot(
                    mock.Mock(), cancelled=lambda: True,
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

    def test_visual_consent_refusal_never_uploads_or_clicks(self):
        window = self.make_window()
        with (
            mock.patch.object(window, "confirm_action",
                              return_value=False) as confirm,
            mock.patch.object(window, "_resolved_command") as resolved,
            mock.patch("main.threading.Thread") as thread,
        ):
            window._start_discord_mic_visual(VOICE)
        self.assertIn("ОДИН снимок", confirm.call_args.args[0])
        self.assertIn("отменено", resolved.call_args.args[1])
        thread.assert_not_called()

    def test_existing_mute_stays_local_even_when_generic_planner_would_match(self):
        import main
        window = self.make_window()
        with (
            mock.patch.object(main, "needs_live_macro_planning",
                              return_value=True) as macro_intent,
            mock.patch.object(main, "toggle_discord_microphone",
                              return_value="Отправил Ctrl+Shift+M.") as mute,
            mock.patch.object(window, "_resolved_command") as result,
            mock.patch("main.threading.Thread") as thread,
        ):
            window.run_command(MUTE)
        mute.assert_called_once()
        result.assert_called_once()
        # run_command queries macro planning only to decide whether to split
        # the utterance. Its dispatcher must still use local mute immediately.
        macro_intent.assert_called_once_with(MUTE)
        thread.assert_not_called()


if __name__ == "__main__":
    unittest.main()
