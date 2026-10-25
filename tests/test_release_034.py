"""0.3.4 keyboard, mouse and Discord microphone regressions (offline)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from luxai.voice_actions import parse_action_sequence
from luxai.discord_navigation import detect_discord_open_dm
from luxai.discord_mic_visual import click_discord_microphone_by_screenshot
from luxai.visual_click import VisualCapture


def image_capture():
    return VisualCapture(
        hwnd=45, pid=50, title="Discord", left=0, top=0,
        width=1368, height=683, image_width=1368, image_height=683,
        jpeg=b"synthetic-blob",
    )


class LocalInputPriorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("Qt not available")
        cls.app = QApplication.instance() or QApplication([])

    def window(self):
        import main
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config = Path(directory.name) / "config.json"
        config.write_text('{"microphone_enabled":false,"tts_enabled":false,'
                          '"online_agent_enabled":false}', encoding="utf-8")
        patch = mock.patch.object(main, "CONFIG", config)
        patch.start()
        self.addCleanup(patch.stop)
        with mock.patch("sounddevice.query_devices", return_value=[]):
            window = main.MainWindow()
        self.addCleanup(window.close)
        return window

    def test_natural_q_and_w_voices_are_direct_not_cloud(self):
        for phrase, expected in [
            ("Нажми на клавишу W.", "w"),
            ("Нажми на Q.", "q"),
        ]:
            with self.subTest(phrase=phrase):
                actions = parse_action_sequence(phrase)
                self.assertEqual(actions[0]["action"], "press_key")
                self.assertEqual(actions[0]["target"], expected)
                window = self.window()
                with (
                    mock.patch.object(window, "_run_direct_input") as native,
                    mock.patch.object(window, "_start_adaptive_task") as cloud,
                    mock.patch.object(window, "_start_visual_reasoner") as vision,
                ):
                    window.run_command(phrase)
                native.assert_called_once_with(phrase, actions)
                cloud.assert_not_called()
                vision.assert_not_called()

    def test_no_confirmation_for_explicit_foreground_key_or_mouse(self):
        for phrase in ("Нажми на Q.", "кликни"):
            with self.subTest(phrase=phrase):
                window = self.window()
                step = parse_action_sequence(phrase)
                with (
                    mock.patch("luxai.screen_interact._foreground_hwnd", return_value=45),
                    mock.patch("luxai.screen_interact._valid_external_window",
                               return_value=(123, "Discord")),
                    mock.patch.object(window, "isActiveWindow", return_value=False),
                    mock.patch.object(window.agent, "execute_plan",
                                      return_value="Нажато.") as executor,
                    mock.patch.object(window, "confirm_action") as confirm,
                    mock.patch.object(window, "_resolved_command") as result,
                ):
                    window._run_direct_input(phrase, step)
                self.assertEqual(executor.call_args.args[:2], (phrase, step[0]))
                self.assertFalse(executor.call_args.kwargs["confirm_callback"]("unrelated destructive action"))
                confirm.assert_not_called()
                result.assert_called_once()

    def test_no_input_when_no_external_window_active(self):
        window = self.window()
        with (
            mock.patch("luxai.screen_interact._foreground_hwnd", return_value=0),
            mock.patch("luxai.screen_interact._valid_external_window",
                       side_effect=ValueError("Jarvis window")),
            mock.patch.object(window.agent, "execute_plan") as native,
            mock.patch.object(window, "_resolved_command") as result,
        ):
            window._run_direct_input("Нажми Q", parse_action_sequence("Нажми Q"))
        native.assert_not_called()
        self.assertIn("Jarvis window", result.call_args.args[1])

    def test_named_discord_contact_uses_verified_navigation(self):
        import main
        phrase = "Жми на пользователя R0nfsy в дискорде."
        self.assertEqual(detect_discord_open_dm(phrase), "R0nfsy")
        window = self.window()
        window.online_planner.enabled = mock.Mock(return_value=True)
        with (
            mock.patch.object(window, "_direct_macro_worker") as worker,
            mock.patch.object(window, "_start_adaptive_task") as adaptive,
            mock.patch.object(window, "_start_visual_reasoner") as generic,
            mock.patch.object(main.threading, "Thread") as thread,
        ):
            window.run_command(phrase)
        self.assertEqual(thread.call_args.kwargs["target"], worker)
        adaptive.assert_not_called()
        generic.assert_not_called()


class NativeInputPlannerTests(unittest.TestCase):
    def test_explicit_key_is_executable_once_no_extra_confirmation(self):
        from luxai.desktop_agent import DesktopRuntime
        runtime = DesktopRuntime(
            "Press W", mock.Mock(), {"response_language": "en"},
        )
        with (
            mock.patch("luxai.screen_interact._foreground_hwnd", return_value=42),
            mock.patch("luxai.screen_interact._valid_external_window",
                       return_value=(55, "Steam")),
            mock.patch("luxai.desktop_actions.execute_desktop_step",
                       return_value="W pressed.") as execute,
        ):
            result = runtime("desktop_input", {"action": "press_key", "target": "w"}, {})
            self.assertTrue(result.ok)
            self.assertFalse(result.verified)
            execute.assert_called_once()
            with self.assertRaises(PermissionError):
                runtime("desktop_input", {"action": "press_key", "target": "w"}, {})

    def test_unrequested_keys_and_free_text_are_denied(self):
        from luxai.desktop_agent import DesktopRuntime
        runtime = DesktopRuntime("Press W", mock.Mock(), {})
        with mock.patch("luxai.desktop_actions.execute_desktop_step") as execute:
            for action, target in [
                ("press_key", "q"), ("type_text", "send message"),
                ("mouse_click", ""), ("run_cmd", "echo hello"),
            ]:
                with self.subTest(action=action), self.assertRaises(PermissionError):
                    runtime("desktop_input", {"action": action, "target": target}, {})
        execute.assert_not_called()


class MicrophonePrecisionTests(unittest.TestCase):
    def test_final_click_uses_fresh_zoom_below_glyph(self):
        capture = image_capture()
        with (
            mock.patch("luxai.discord_screen_review._ensure_discord_visible", return_value=45),
            mock.patch("luxai.discord_screen_review.focus_discord"),
            mock.patch("luxai.discord_screen_review._save_capture"),
            mock.patch("luxai.visual_click.capture_window", side_effect=[capture, capture]),
            mock.patch("luxai.visual_click.capture_window_region",
                       return_value=capture) as zoom,
            mock.patch("luxai.discord_mic_visual.inspect_discord_microphone",
                       side_effect=[("unmuted", (1215, 633)),
                                    ("unmuted", (1215, 640)),
                                    ("muted", (1215, 640))]) as inspect,
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.discord_mic_visual.time.sleep"),
        ):
            answer = click_discord_microphone_by_screenshot(mock.Mock(), mode="mute")
        zoom.assert_called_once_with(capture, (1215, 633), width=280, height=150)
        self.assertTrue(inspect.call_args_list[1].kwargs["closeup"])
        click.assert_called_once_with(capture, (1215, 645), 1)
        self.assertIn("микрофон выключен", answer)

    def test_bad_closeup_never_clicks_anything(self):
        capture = image_capture()
        with (
            mock.patch("luxai.discord_screen_review._ensure_discord_visible", return_value=45),
            mock.patch("luxai.discord_screen_review.focus_discord"),
            mock.patch("luxai.discord_screen_review._save_capture"),
            mock.patch("luxai.visual_click.capture_window", return_value=capture),
            mock.patch("luxai.visual_click.capture_window_region",
                       return_value=capture),
            mock.patch("luxai.discord_mic_visual.inspect_discord_microphone",
                       side_effect=[("unmuted", (1215, 633)),
                                    ("unmuted", (1215, 581))]),
            mock.patch("luxai.visual_click.click_visual_target") as click,
        ):
            with self.assertRaisesRegex(ValueError, "differs"):
                click_discord_microphone_by_screenshot(mock.Mock(), mode="mute")
        click.assert_not_called()

    def test_unknown_overview_state_uses_closeup_to_toggle_once(self):
        capture = image_capture()
        with (
            mock.patch("luxai.discord_screen_review._ensure_discord_visible", return_value=45),
            mock.patch("luxai.discord_screen_review.focus_discord"),
            mock.patch("luxai.discord_screen_review._save_capture"),
            mock.patch("luxai.visual_click.capture_window", return_value=capture),
            mock.patch("luxai.visual_click.capture_window_region", return_value=capture),
            mock.patch("luxai.discord_mic_visual.inspect_discord_microphone",
                       side_effect=[("unknown", (1215, 633)),
                                    ("muted", (1215, 640)),
                                    ("unmuted", (1215, 640))]),
            mock.patch("luxai.visual_click.click_visual_target") as click,
        ):
            outcome = click_discord_microphone_by_screenshot(mock.Mock(), mode="toggle")
        # This is a real toggle request: one click is permitted if the state
        # is known, unlike a specific 'mute' request already fulfilled.
        click.assert_called_once()


if __name__ == "__main__":
    unittest.main()
