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
        config_patch = mock.patch.object(main, "CONFIG", config)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        with mock.patch("sounddevice.query_devices", return_value=[]):
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

    def test_missed_mic_feedback_resumes_dedicated_discord_visual_target(self):
        import main
        import time
        window = self.make_window()
        original = "Жарвис, выключи микрофон в Discord"
        window._last_visual_goal = original
        window._last_visual_goal_at = time.monotonic()
        with (
            mock.patch.object(window, "_start_discord_mic_visual") as mic,
            mock.patch.object(window, "_start_visual_reasoner") as generic,
            mock.patch.object(window, "_start_adaptive_task") as adaptive,
        ):
            window.run_command(
                "Кликни по микрофону, ты опять не попал, надо правее."
            )
        mic.assert_called_once_with(original)
        generic.assert_not_called()
        adaptive.assert_not_called()

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



class DiscordMicPixelTargetTests(unittest.TestCase):
    """Regression: custom bottom-right account panel on a 1368x683 desktop."""

    @staticmethod
    def screenshot(*, left=0, top=0, width=1368, height=683):
        import io
        from PIL import Image, ImageDraw
        from luxai.visual_click import VisualCapture

        image = Image.new("RGB", (width, height), "#172033")
        draw = ImageDraw.Draw(image)
        # Fake bottom user bar and a small microphone icon near the RIGHT.
        draw.rectangle((max(0, width - 375), height - 72,
                        width - 5, height - 4), fill="#112443")
        icon_x, icon_y = width - 153, height - 42
        draw.ellipse((icon_x - 6, icon_y - 10, icon_x + 6, icon_y + 5),
                     fill="#ffffff")
        draw.line((icon_x, icon_y + 5, icon_x, icon_y + 12),
                  fill="#ffffff", width=2)
        data = io.BytesIO()
        image.save(data, format="JPEG", quality=85)
        return VisualCapture(
            hwnd=25, pid=50, title="Discord", left=left, top=top,
            width=width, height=height,
            image_width=width, image_height=height, jpeg=data.getvalue(),
        )

    def test_crop_preserves_actual_screen_coordinates_at_right_edge(self):
        from luxai.discord_mic_visual import microphone_panel_capture
        from luxai.visual_click import validate_visual_point
        original = self.screenshot(left=160, top=75)
        crop = microphone_panel_capture(original)
        self.assertEqual(crop.left, original.left)
        self.assertEqual(crop.width, original.width)
        self.assertGreater(crop.top, original.top)
        self.assertGreater(crop.image_width, original.image_width)
        target_x = original.left + 1215
        target_y = original.top + 641
        normalized_x = (target_x - crop.left) / crop.width * 1000
        normalized_y = (target_y - crop.top) / crop.height * 1000
        actual = validate_visual_point(
            {"found": True, "x": normalized_x, "y": normalized_y}, crop,
        )
        self.assertLessEqual(abs(actual[0] - target_x), 1)
        self.assertLessEqual(abs(actual[1] - target_y), 1)
        self.assertGreater(normalized_x, 850)

    def test_cropped_image_uses_bottom_bar_without_changing_window_identity(self):
        from PIL import Image
        import io
        from luxai.discord_mic_visual import microphone_panel_capture
        source = self.screenshot(left=-1368, top=60)
        crop = microphone_panel_capture(source)
        with Image.open(io.BytesIO(crop.jpeg)) as output:
            self.assertEqual(output.size, (crop.image_width, crop.image_height))
        self.assertEqual((crop.hwnd, crop.pid, crop.title),
                         (source.hwnd, source.pid, source.title))
        self.assertEqual((crop.left, crop.top + crop.height),
                         (source.left, source.top + source.height))

    def test_locator_asks_for_cropped_mic_near_user_name_and_gear(self):
        import json
        from luxai.discord_mic_visual import (
            microphone_panel_capture, inspect_discord_microphone,
        )
        screenshot = self.screenshot()
        crop = microphone_panel_capture(screenshot)
        x = 1215 / crop.width * 1000
        y = (641 - crop.top) / crop.height * 1000
        planner = mock.Mock()
        planner._provider.return_value = "openai"
        planner.enabled.return_value = True
        planner.config = {"online_model": "gpt-4.1-mini", "online_timeout": 60}
        planner._extract_text.return_value = json.dumps({
            "found": True, "x": x, "y": y, "state": "unmuted",
        })
        planner._read_json_content.side_effect = json.loads
        with mock.patch("luxai.secure_keys.get_api_key",
                        return_value="test-only-key"):
            state, point = inspect_discord_microphone(planner, screenshot)
        self.assertEqual(state, "unmuted")
        self.assertLessEqual(abs(point[0] - 1215), 1)
        self.assertLessEqual(abs(point[1] - 641), 1)
        prompt = planner._request.call_args.args[3]
        self.assertIn("MAGNIFIED BOTTOM STRIP", prompt[1]["content"][0]["text"])
        self.assertIn("RIGHT", prompt[1]["content"][0]["text"])
        self.assertIn("account-bar MIC", prompt[0]["content"])

    def test_toggle_does_not_claim_success_if_mic_stays_unmuted(self):
        with (
            mock.patch("luxai.discord_screen_review._ensure_discord_visible",
                       return_value=45),
            mock.patch("luxai.discord_screen_review.focus_discord"),
            mock.patch("luxai.discord_screen_review._save_capture"),
            mock.patch("luxai.visual_click.capture_window"),
            mock.patch("luxai.discord_mic_visual.inspect_discord_microphone",
                       side_effect=[("unmuted", (1215, 641)),
                                    ("unmuted", (1215, 641))]),
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.discord_mic_visual.time.sleep"),
        ):
            outcome = click_discord_microphone_by_screenshot(
                mock.Mock(), mode="toggle",
            )
        click.assert_called_once()
        self.assertIn("не изменилось", outcome)

    def test_after_click_other_mic_icon_is_not_verification(self):
        with (
            mock.patch("luxai.discord_screen_review._ensure_discord_visible",
                       return_value=45),
            mock.patch("luxai.discord_screen_review.focus_discord"),
            mock.patch("luxai.discord_screen_review._save_capture"),
            mock.patch("luxai.visual_click.capture_window"),
            mock.patch("luxai.discord_mic_visual.inspect_discord_microphone",
                       side_effect=[("unmuted", (1215, 641)),
                                    ("muted", (1170, 641))]),
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.discord_mic_visual.time.sleep"),
        ):
            outcome = click_discord_microphone_by_screenshot(
                mock.Mock(), mode="mute",
            )
        click.assert_called_once()
        self.assertIn("подтвердить не удалось", outcome)


if __name__ == "__main__":
    unittest.main()
