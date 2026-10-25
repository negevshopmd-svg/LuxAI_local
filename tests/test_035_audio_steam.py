"""0.3.5 regression tests: Discord headphones confirmation and natural Steam."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from luxai.discord_headphones_visual import (
    discord_headphones_mode, inspect_discord_headphones, set_discord_headphones,
)
from luxai.task_intents import steam_self_nickname_request, opening_app


class NaturalCommandTests(unittest.TestCase):
    def test_reported_steam_exact_request_is_single_goal(self):
        phrases = (
            "Открой Steam и скажи какой у меня там никнейм.",
            "Открой Steam и скажи какой у меня там ник.",
            "Можешь зайти в Steam и сказать какой у меня ник?",
        )
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertTrue(steam_self_nickname_request(phrase))
                self.assertEqual(opening_app(phrase), "steam")

    def test_headphones_distinguish_from_microphone_and_generic_chat(self):
        for voice in (
            "Выключи наушники в дискорде.",
            "Отключи наушники Discord",
            "Deafen headphones in Discord",
        ):
            self.assertEqual(discord_headphones_mode(voice), "off")
        self.assertEqual(discord_headphones_mode("Включи наушники в Discord"), "on")
        self.assertIsNone(discord_headphones_mode("Выключи микрофон в Discord"))
        self.assertIsNone(discord_headphones_mode("Просто выключи наушники компьютера"))
        self.assertIsNone(discord_headphones_mode("Как работают наушники Discord?"))


class HeadphonesScreenshotTests(unittest.TestCase):
    def test_localizes_actual_slash_state_and_account_bar(self):
        import io
        from PIL import Image
        from luxai.visual_click import VisualCapture
        img = Image.new("RGB", (1368, 683), "#15213b")
        stream = io.BytesIO()
        img.save(stream, format="JPEG")
        capture = VisualCapture(
            hwnd=40, pid=41, title="Discord", left=0, top=0,
            width=1368, height=683, image_width=1368, image_height=683,
            jpeg=stream.getvalue(),
        )
        planner = mock.Mock()
        planner._provider.return_value = "openai"
        planner.enabled.return_value = True
        planner.config = {"online_model": "gpt-4.1-mini"}
        planner._extract_text.return_value = json.dumps({
            "found": True, "x": 920, "y": 880, "state": "off",
        })
        planner._read_json_content.side_effect = json.loads
        with mock.patch("luxai.secure_keys.get_api_key", return_value="test-key"):
            state, point = inspect_discord_headphones(planner, capture)
        self.assertEqual(state, "off")
        self.assertGreater(point[0], 1100)
        self.assertGreater(point[1], 600)
        prompt = planner._request.call_args.args[3][1]["content"][0]["text"]
        self.assertIn("RED DIAGONAL SLASH", prompt)
        self.assertIn("HEADPHONES", prompt)

    def test_already_deafened_is_proven_without_extra_click(self):
        with (
            mock.patch("luxai.discord_screen_review._ensure_discord_visible", return_value=90),
            mock.patch("luxai.discord_screen_review.focus_discord"),
            mock.patch("luxai.visual_click.capture_window"),
            mock.patch("luxai.discord_headphones_visual.inspect_discord_headphones",
                       return_value=("off", (1507, 885))),
            mock.patch("luxai.visual_click.click_visual_target") as click,
        ):
            result = set_discord_headphones(mock.Mock(), mode="off")
        self.assertIn("уже выключены", result)
        click.assert_not_called()

    def test_click_once_and_confirm_fresh_slash(self):
        from luxai.visual_click import VisualCapture
        shot = VisualCapture(90, 15, "Discord", 0, 0, 1592, 922,
                             1592, 922, b"fake")
        with (
            mock.patch("luxai.discord_screen_review._ensure_discord_visible", return_value=90),
            mock.patch("luxai.discord_screen_review.focus_discord"),
            mock.patch("luxai.visual_click.capture_window",
                       side_effect=[shot, shot]) as shots,
            mock.patch("luxai.visual_click.capture_window_region",
                       return_value=shot) as crop,
            mock.patch("luxai.discord_headphones_visual.inspect_discord_headphones",
                       side_effect=[("on", (1507, 885)), ("on", (1508, 885)),
                                    ("off", (1508, 885))]) as inspect,
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.discord_headphones_visual.time.sleep"),
        ):
            output = set_discord_headphones(mock.Mock(), mode="off")
        self.assertEqual(output, "Наушники Discord выключены.")
        click.assert_called_once_with(shot, (1508, 885), 1)
        self.assertEqual(shots.call_count, 2)
        crop.assert_called_once()
        self.assertEqual(inspect.call_count, 3)

    def test_if_broad_screenshot_does_not_see_slash_zoom_rechecks_after_click(self):
        from luxai.visual_click import VisualCapture
        shot = VisualCapture(90, 15, "Discord", 0, 0, 1592, 922,
                             1592, 922, b"fake")
        with (
            mock.patch("luxai.discord_screen_review._ensure_discord_visible", return_value=90),
            mock.patch("luxai.discord_screen_review.focus_discord"),
            mock.patch("luxai.visual_click.capture_window", side_effect=[shot, shot]),
            mock.patch("luxai.visual_click.capture_window_region", return_value=shot) as crop,
            mock.patch("luxai.discord_headphones_visual.inspect_discord_headphones",
                       side_effect=[("on", (1507, 885)), ("on", (1507, 885)),
                                    ("unknown", (1507, 885)), ("off", (1507, 885))]),
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.discord_headphones_visual.time.sleep"),
        ):
            answer = set_discord_headphones(mock.Mock(), mode="off")
        self.assertEqual(answer, "Наушники Discord выключены.")
        self.assertEqual(crop.call_count, 2)
        click.assert_called_once()

    def test_no_false_success_if_state_is_still_on(self):
        with (
            mock.patch("luxai.discord_screen_review._ensure_discord_visible", return_value=90),
            mock.patch("luxai.discord_screen_review.focus_discord"),
            mock.patch("luxai.visual_click.capture_window"),
            mock.patch("luxai.visual_click.capture_window_region"),
            mock.patch("luxai.discord_headphones_visual.inspect_discord_headphones",
                       side_effect=[("on", (1507, 885)), ("on", (1507, 885)),
                                    ("on", (1507, 885))]),
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.discord_headphones_visual.time.sleep"),
        ):
            answer = set_discord_headphones(mock.Mock(), mode="off")
        click.assert_called_once()
        self.assertIn("не изменилось", answer)
        self.assertNotIn("Discord выключены.", answer)


class VisualRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("Qt not installed")
        cls.app = QApplication.instance() or QApplication([])

    def window(self):
        import main
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = Path(tmp.name) / "config.json"
        config.write_text('{"microphone_enabled":false,"tts_enabled":false,'
                          '"online_agent_enabled":false}', encoding="utf-8")
        p = mock.patch.object(main, "CONFIG", config)
        p.start()
        self.addCleanup(p.stop)
        with mock.patch("sounddevice.query_devices", return_value=[]):
            win = main.MainWindow()
        self.addCleanup(win.close)
        return win

    def test_exact_steam_request_skips_generic_adaptive_planner(self):
        phrase = "Открой Steam и скажи какой у меня там никнейм."
        window = self.window()
        with (
            mock.patch.object(window, "_start_steam_profile_lookup") as steam,
            mock.patch.object(window, "_start_adaptive_task") as cloud,
            mock.patch.object(window, "_start_visual_reasoner") as visual,
        ):
            window.run_command(phrase)
        steam.assert_called_once_with(phrase)
        cloud.assert_not_called()
        visual.assert_not_called()

    def test_headphones_command_uses_dedicated_state_verifier(self):
        phrase = "Выключи наушники в дискорде."
        window = self.window()
        with (
            mock.patch.object(window, "_start_discord_headphones_visual") as headphone,
            mock.patch.object(window, "_start_adaptive_task") as cloud,
            mock.patch.object(window, "_start_visual_reasoner") as generic,
        ):
            window.run_command(phrase)
        headphone.assert_called_once_with(phrase)
        cloud.assert_not_called()
        generic.assert_not_called()

    def test_cloud_screenshot_consent_remains_required(self):
        window = self.window()
        window.online_planner.enabled = mock.Mock(return_value=True)
        with (
            mock.patch.object(window, "_allow_cloud_screenshots", return_value=False),
            mock.patch.object(window, "_resolved_command") as done,
            mock.patch("main.threading.Thread") as thread,
        ):
            window._start_discord_headphones_visual("Выключи наушники в Discord")
        thread.assert_not_called()
        self.assertIn("отменён", done.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
