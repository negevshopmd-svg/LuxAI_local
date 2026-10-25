"""Unit tests for verified multi-step visual automation without screen/network use."""
from __future__ import annotations

import base64
import json
import unittest
from unittest import mock

from luxai.action_catalog import validate_step
from luxai.macro_planner import validate_generated_macro, needs_live_macro_planning
from luxai.visual_click import (
    VisualCapture, desktop_geometry, parse_click_target, multimodal_messages,
    validate_visual_point, find_visual_target,
)


def sample_capture():
    return VisualCapture(
        hwnd=123, pid=456, title="Explorer",
        left=-1920, top=20, width=1920, height=1080,
        image_width=1300, image_height=731, jpeg=b"fake-jpeg",
    )


class VisualTargetRules(unittest.TestCase):
    def test_click_count_and_user_named_control(self):
        self.assertEqual(parse_click_target("Корзина||2"), ("Корзина", 2))
        self.assertEqual(validate_step({
            "action": "visual_click", "target": "Download button||5",
        })["target"], "Download button||5")
        for unsafe in (
            "button", "button||0", "button||11", "button||999",
            "password box||1", "Windows Security||1", "passcode||1",
            "some\nbutton||1",
        ):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                validate_step({"action": "visual_click", "target": unsafe})

    def test_window_coordinates_use_negative_monitor_origin_and_original_size(self):
        capture = sample_capture()
        self.assertEqual(validate_visual_point(
            {"found": True, "x": 500, "y": 500}, capture
        ), (-960, 560))
        with self.assertRaisesRegex(ValueError, "outside|near edge"):
            validate_visual_point({"found": True, "x": 999, "y": 3}, capture)
        for response in ({"found": False, "x": 500, "y": 500},
                         {"found": True, "x": "500", "y": 500},
                         {"found": True, "x": 2000, "y": 400},
                         {"x": 300, "y": 400}):
            with self.subTest(response=response), self.assertRaises(ValueError):
                validate_visual_point(response, capture)

    def test_provider_request_uses_selected_provider_no_fallback(self):
        planner = mock.Mock()
        planner._provider.return_value = "openai"
        planner.enabled.return_value = True
        planner.config = {"online_model": "gpt-4.1-mini", "online_timeout": 45}
        planner._request.return_value = {"choices": [{"message": {
            "content": '{"found":true,"x":500,"y":500}',
        }}]}
        from luxai.online_agent import OnlinePlanner
        planner._read_json_content = OnlinePlanner._read_json_content
        planner._extract_text = OnlinePlanner._extract_text
        with mock.patch("luxai.secure_keys.get_api_key", return_value="fake-key"):
            point = find_visual_target(planner, "Recycle Bin", sample_capture())
        self.assertEqual(point, (-960, 560))
        kwargs = planner._request.call_args
        self.assertEqual(kwargs.args[0], "openai")
        self.assertIn("VISUAL LOCATOR", kwargs.args[3][0]["content"])
        image = kwargs.args[3][1]["content"][1]["image_url"]["url"]
        self.assertTrue(image.startswith("data:image/jpeg;base64,"))
        self.assertEqual(base64.b64decode(image.split(",", 1)[1]), b"fake-jpeg")

    def test_anthropic_uses_native_base64_image_format(self):
        msg = multimodal_messages("Ok button", sample_capture(), "anthropic")
        self.assertEqual(msg[1]["content"][1]["source"]["media_type"], "image/jpeg")
        self.assertNotIn("image_url", msg[1]["content"][1])

    def test_real_desktop_dimensions_from_virtual_monitor_not_assumptions(self):
        fake = mock.MagicMock()
        fake.__enter__.return_value.monitors = [
            {"left": -1080, "top": 0, "width": 3000, "height": 1080}
        ]
        with mock.patch("mss.mss", return_value=fake):
            self.assertEqual(desktop_geometry(), {
                "left": -1080, "top": 0, "width": 3000, "height": 1080,
            })



class PhysicalPixelClickTests(unittest.TestCase):
    """No real desktop access: simulate mixed-DPI, crops, and mouse events."""

    def test_full_image_preserves_1920_width_with_sharp_compression(self):
        import io
        from PIL import Image
        from luxai.visual_click import _encode_visual_image
        image = Image.new("RGB", (1920, 1080), "white")
        iw, ih, data = _encode_visual_image(image)
        self.assertEqual((iw, ih), (1920, 1080))
        self.assertLess(len(data), 1_200_000)
        with Image.open(io.BytesIO(data)) as decoded:
            self.assertEqual(decoded.size, (iw, ih))

    def test_precise_locator_uses_independent_second_pass_and_real_offsets(self):
        from dataclasses import replace
        from luxai.visual_click import find_visual_target
        screen = sample_capture()
        # First-pass estimated desktop pixel = -1920 + 1536, 20 + 756
        candidate = (-384, 776)
        detail = replace(screen, left=-515, top=650, width=300, height=260,
                         image_width=600, image_height=520, jpeg=b"detail")
        planner = mock.Mock()
        planner._provider.return_value = "openai"
        planner.enabled.return_value = True
        planner.config = {"online_model": "gpt-4.1-mini", "online_timeout": 50}
        planner._request.side_effect = [object(), object()]
        planner._extract_text.side_effect = [
            '{"found":true,"x":800,"y":700}',
            '{"found":true,"x":480,"y":490}',
        ]
        planner._read_json_content.side_effect = json.loads
        with (
            mock.patch("luxai.secure_keys.get_api_key", return_value="test-key"),
            mock.patch("luxai.visual_click.capture_window_region",
                       return_value=detail) as crop,
        ):
            result = find_visual_target(planner, "Mic", screen, precise=True)
        crop.assert_called_once_with(screen, candidate)
        self.assertEqual(result, (-371, 777))
        self.assertEqual(planner._request.call_count, 2)
        request = planner._request.call_args.args[3]
        self.assertIn("FRESH MAGNIFIED PHYSICAL-PIXEL CROP",
                      request[1]["content"][0]["text"])
        self.assertIn("left=-515", request[1]["content"][0]["text"])

    def test_precise_locator_rejects_conflicting_control_after_zoom(self):
        from dataclasses import replace
        from luxai.visual_click import find_visual_target
        capture = sample_capture()
        detail = replace(capture, left=-1100, top=300, width=440,
                         height=330, image_width=880, image_height=660)
        planner = mock.Mock()
        planner._provider.return_value = "openai"
        planner.enabled.return_value = True
        planner.config = {}
        planner._request.side_effect = [object(), object()]
        planner._extract_text.side_effect = [
            '{"found":true,"x":500,"y":500}',
            '{"found":true,"x":850,"y":850}',
        ]
        planner._read_json_content.side_effect = json.loads
        with (
            mock.patch("luxai.secure_keys.get_api_key", return_value="test"),
            mock.patch("luxai.visual_click.capture_window_region",
                       return_value=detail),
        ):
            with self.assertRaisesRegex(ValueError, "differs"):
                find_visual_target(planner, "Settings", capture, precise=True)

    def test_region_uses_native_negative_monitor_coords_not_resized_jpeg(self):
        from PIL import Image
        from luxai.visual_click import capture_window_region
        source = sample_capture()
        raw = mock.Mock()
        raw.size = (200, 140)
        raw.rgb = Image.new("RGB", raw.size, "#2a5ac1").tobytes()
        screen = mock.MagicMock()
        screen.__enter__.return_value = screen
        screen.monitors = [{
            "left": -1920, "top": 0, "width": 3840, "height": 1080
        }]
        screen.grab.return_value = raw
        with (
            mock.patch("luxai.visual_click.sys.platform", "win32"),
            mock.patch("luxai.visual_click._require_same_capture_window") as same,
            mock.patch("mss.mss", return_value=screen),
        ):
            roi = capture_window_region(
                source, (-1750, 930), width=200, height=140,
            )
        self.assertEqual((roi.left, roi.top, roi.width, roi.height),
                         (-1850, 860, 200, 140))
        self.assertEqual((roi.image_width, roi.image_height), (400, 280))
        same.assert_called_once()
        screen.grab.assert_called_once_with({
            "left": -1850, "top": 860, "width": 200, "height": 140,
        })

    def test_move_between_capture_and_click_is_rejected(self):
        from luxai.visual_click import _require_same_capture_window
        shot = sample_capture()
        with (
            mock.patch("luxai.screen_interact._valid_external_window",
                       return_value=(shot.pid, shot.title)),
            mock.patch("luxai.screen_interact._foreground_hwnd",
                       return_value=shot.hwnd),
            mock.patch("luxai.visual_click._visible_window_bounds",
                       return_value=(-1913, 20, 1920, 1080)),
        ):
            with self.assertRaisesRegex(RuntimeError, "moved or resized"):
                _require_same_capture_window(shot, desktop_geometry())

    def test_native_click_keeps_negative_physical_pixels_and_checks_owner(self):
        from luxai.visual_click import click_visual_target
        import sys
        shot = sample_capture()
        user32 = mock.Mock()
        user32.GetForegroundWindow.return_value = shot.hwnd
        user32.WindowFromPoint.return_value = 777
        user32.SetCursorPos.return_value = True
        screen = mock.MagicMock()
        screen.__enter__.return_value.monitors = [{
            "left": -1920, "top": 0, "width": 3840, "height": 1080
        }]
        with (
            mock.patch("luxai.visual_click.sys.platform", "win32"),
            mock.patch("luxai.visual_click._require_same_capture_window"),
            mock.patch("luxai.win32.get_user32", return_value=user32),
            mock.patch("luxai.screen_interact._window_pid", return_value=shot.pid),
            mock.patch.dict(sys.modules, {"pyautogui": mock.Mock()}),
            mock.patch("mss.mss", return_value=screen),
            mock.patch("luxai.visual_click.time.sleep"),
        ):
            click_visual_target(shot, (-500, 720), 1)
        user32.SetCursorPos.assert_called_once_with(-500, 720)
        self.assertEqual(user32.mouse_event.call_count, 2)
        self.assertEqual(user32.mouse_event.call_args_list[0].args[0], 0x0002)
        self.assertEqual(user32.mouse_event.call_args_list[1].args[0], 0x0004)

    def test_click_refuses_control_hidden_by_other_process(self):
        from luxai.visual_click import click_visual_target
        import sys
        shot = sample_capture()
        user32 = mock.Mock()
        user32.GetForegroundWindow.return_value = shot.hwnd
        user32.WindowFromPoint.return_value = 771
        screen = mock.MagicMock()
        screen.__enter__.return_value.monitors = [{
            "left": -1920, "top": 0, "width": 3840, "height": 1080
        }]
        with (
            mock.patch("luxai.visual_click.sys.platform", "win32"),
            mock.patch("luxai.visual_click._require_same_capture_window"),
            mock.patch("luxai.win32.get_user32", return_value=user32),
            mock.patch("luxai.screen_interact._window_pid", return_value=999),
            mock.patch.dict(sys.modules, {"pyautogui": mock.Mock()}),
            mock.patch("mss.mss", return_value=screen),
        ):
            with self.assertRaisesRegex(RuntimeError, "covered"):
                click_visual_target(shot, (-500, 720), 1)
        user32.SetCursorPos.assert_not_called()
        user32.mouse_event.assert_not_called()

    def test_dwm_physical_frame_overrides_dpi_virtualized_getwindowrect(self):
        import ctypes
        from luxai.visual_click import _visible_window_bounds
        desktop = {"left": -1920, "top": 0, "width": 3840, "height": 2160}
        def dwm_attribute(hwnd, key, out, n):
            self.assertEqual(key, 9)
            rect = out._obj
            rect.left, rect.top, rect.right, rect.bottom = -1700, 110, -300, 1010
            return 0
        dwm = mock.Mock()
        dwm.DwmGetWindowAttribute.side_effect = dwm_attribute
        win = mock.Mock()
        with (
            mock.patch.object(ctypes, "windll", create=True,
                              new=mock.Mock(dwmapi=dwm)),
            mock.patch("luxai.win32.get_user32", return_value=win),
        ):
            self.assertEqual(_visible_window_bounds(123, desktop),
                             (-1700, 110, 1400, 900))
        win.GetWindowRect.assert_not_called()


class MacroPlanningTests(unittest.TestCase):
    def test_complex_russian_request_routes_through_full_macro(self):
        self.assertTrue(needs_live_macro_planning(
            "открой корзину, потом удали все из корзины, потом выйди"
        ))
        self.assertTrue(needs_live_macro_planning("нажми на кнопку Сохранить два раза"))
        self.assertFalse(needs_live_macro_planning("Сколько времени?"))

    def test_visual_control_cloud_steps_accept_labeled_clicks(self):
        proposal = validate_generated_macro({
            "steps": [
                {"action": "display_info"},
                {"action": "visual_click", "target": "Recycle Bin||2"},
                {"action": "wait_seconds", "target": "2"},
                {"action": "visual_click", "target": "Refresh||3"},
            ]
        }, "Нажми на корзину, потом 3 клика Обновить")
        self.assertEqual(len(proposal["steps"]), 4)
        self.assertEqual(proposal["steps"][1]["target"], "Recycle Bin||2")

    def test_empty_bin_requires_explicit_spoken_intent_and_followup_confirm(self):
        proposal = {"steps": [{"action": "empty_recycle_bin"}]}
        self.assertIsNone(validate_generated_macro(proposal, "Open Explorer"))
        self.assertIsNotNone(
            validate_generated_macro(proposal, "Удали всё из корзины Windows")
        )
        self.assertIsNotNone(
            validate_generated_macro(proposal, "empty the recycle bin")
        )

    def test_shell_action_cannot_be_smuggled_through_vision(self):
        for step in (
            {"action": "run_cmd", "target": "del /q *"},
            {"action": "visual_click", "target": "Password||1"},
            {"action": "visual_click", "target": "button||200"},
        ):
            self.assertIsNone(validate_generated_macro({"steps": [step]}, "click"))

class VisualConsentUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            cls.app = QApplication.instance() or QApplication([])
        except ImportError:
            raise unittest.SkipTest("PySide6 not installed")

    def test_declined_window_screenshot_does_not_start_ai_or_click(self):
        import tempfile
        from pathlib import Path
        import main
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text('{"microphone_enabled": false, "tts_enabled": false}',
                              encoding="utf-8")
            config_patch = mock.patch.object(main, "CONFIG", config)
            config_patch.start()
            self.addCleanup(config_patch.stop)
            with mock.patch("sounddevice.query_devices", return_value=[]):
                window = main.MainWindow()
            try:
                window._processing = True
                window._active_text = "click save"
                window._macro_context = {
                    "index": 0, "text": "click save", "messages": [],
                    "steps": [validate_step({
                        "action": "visual_click", "target": "Save button||2",
                    })],
                }
                window.online_planner.enabled = mock.Mock(return_value=True)
                with mock.patch.object(main, "_foreground_hwnd", return_value=222), \
                     mock.patch.object(main, "_valid_external_window",
                                       return_value=(123, "Editor")), \
                     mock.patch.object(window, "confirm_action", return_value=False), \
                     mock.patch.object(window, "_visual_worker") as worker, \
                     mock.patch.object(window, "_resolved_command") as resolved:
                    window._next_macro_step()
                    worker.assert_not_called()
                    resolved.assert_called_once()
                    self.assertIn("отменена", resolved.call_args.args[1])
            finally:
                window._processing = False
                window._macro_context = None
                window.close()


if __name__ == "__main__":
    unittest.main()
