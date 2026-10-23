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
            "action": "visual_click", "target": "Download button||3",
        })["target"], "Download button||3")
        for unsafe in (
            "button", "button||0", "button||4", "button||999",
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

if __name__ == "__main__":
    unittest.main()
