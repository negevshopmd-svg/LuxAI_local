"""Closed-loop desktop reasoning regressions; never access a live desktop.

These tests check action observation, refusal of unverified success,
limited retries and reuse of the user's preceding goal after a miss.
"""
from __future__ import annotations

import sys
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from luxai.visual_reasoner import (
    _is_safe_click, is_visual_feedback, is_visual_goal, run_visual_reasoner,
)

GOAL = "Жарвис, зайди в Discord и нажми на микрофон."


class ReasoningUnitTests(unittest.TestCase):
    def test_goal_detection_is_generic_not_one_phrase(self):
        self.assertTrue(is_visual_goal(GOAL))
        self.assertTrue(is_visual_goal(
            "Выбери вкладку со списком задач в приложении"
        ))
        self.assertTrue(is_visual_goal(
            "Please open the application and click the settings menu"
        ))
        self.assertFalse(is_visual_goal("Привет как дела"))
        self.assertTrue(is_visual_feedback("Ты не попал. Давай заново."))
        self.assertTrue(is_visual_feedback("That click missed, try again"))
        self.assertFalse(is_visual_feedback("Спасибо, всё работает!"))

    def test_safety_gate_rejects_message_send_payment_and_password_controls(self):
        for control in ("Send message", "Pay now", "Удалить аккаунт",
                        "Password field", "Оплатить"):
            with self.subTest(control=control):
                with self.assertRaises((ValueError, PermissionError)):
                    _is_safe_click(control, GOAL)
        self.assertEqual(_is_safe_click("Discord microphone", GOAL),
                         "Discord microphone")

    def test_click_is_not_success_until_new_screenshot_and_verifier(self):
        first = mock.Mock(hwnd=42)
        second = mock.Mock(hwnd=42)
        planner = mock.Mock()
        planner.enabled.return_value = True
        with (
            mock.patch("luxai.visual_reasoner.sys.platform", "win32"),
            mock.patch("luxai.visual_reasoner._select_window", return_value=42),
            mock.patch("luxai.visual_reasoner.capture_window",
                       side_effect=[first, second]) as captures,
            mock.patch("luxai.visual_reasoner._choose", side_effect=[
                {"action": "click", "target": "Microphone icon", "reason": "found mic"},
                {"action": "done", "reason": "muted icon visible"},
            ]) as decide,
            mock.patch("luxai.visual_reasoner.find_visual_target",
                       return_value=(320, 600)),
            mock.patch("luxai.visual_reasoner.click_visual_target") as click,
            mock.patch("luxai.visual_reasoner._verify_goal",
                       return_value=True) as verify,
            mock.patch("luxai.visual_reasoner.time.sleep"),
        ):
            result = run_visual_reasoner(planner, GOAL)
        self.assertEqual(captures.call_count, 2)
        self.assertIs(decide.call_args_list[1].kwargs["previous"], first)
        click.assert_called_once_with(first, (320, 600), 1)
        verify.assert_called_once_with(planner, GOAL, second)
        self.assertIn("подтвердил", result)

    def test_false_completion_never_claims_success_or_clicks(self):
        planner = mock.Mock()
        with (
            mock.patch("luxai.visual_reasoner.sys.platform", "win32"),
            mock.patch("luxai.visual_reasoner._select_window", return_value=42),
            mock.patch("luxai.visual_reasoner.capture_window"),
            mock.patch("luxai.visual_reasoner._choose", side_effect=[
                {"action": "done", "reason": "possibly complete"},
                {"action": "stop", "reason": "cannot confirm"},
            ]),
            mock.patch("luxai.visual_reasoner._verify_goal",
                       return_value=False) as verify,
            mock.patch("luxai.visual_reasoner.click_visual_target") as click,
        ):
            result = run_visual_reasoner(planner, GOAL, feedback="ты не попал")
        verify.assert_called_once()
        click.assert_not_called()
        self.assertIn("не удалось", result)

    def test_missed_click_does_not_repeat_the_same_control(self):
        planner = mock.Mock()
        with (
            mock.patch("luxai.visual_reasoner.sys.platform", "win32"),
            mock.patch("luxai.visual_reasoner._select_window", return_value=42),
            mock.patch("luxai.visual_reasoner.capture_window"),
            mock.patch("luxai.visual_reasoner._choose", side_effect=[
                {"action": "click", "target": "Microphone icon"},
                {"action": "click", "target": "Microphone icon"},
            ]),
            mock.patch("luxai.visual_reasoner.find_visual_target",
                       return_value=(200, 300)),
            mock.patch("luxai.visual_reasoner.click_visual_target") as click,
            mock.patch("luxai.visual_reasoner.time.sleep"),
        ):
            result = run_visual_reasoner(planner, GOAL)
        click.assert_called_once()
        self.assertIn("Повторный клик", result)

    def test_unknown_or_dangerous_model_action_never_executes(self):
        with (
            mock.patch("luxai.visual_reasoner.sys.platform", "win32"),
            mock.patch("luxai.visual_reasoner._select_window", return_value=42),
            mock.patch("luxai.visual_reasoner.capture_window"),
            mock.patch("luxai.visual_reasoner._choose",
                       return_value={"action": "open_shell", "target": "cmd"}),
            mock.patch("luxai.visual_reasoner.click_visual_target") as click,
        ):
            with self.assertRaises(ValueError):
                run_visual_reasoner(mock.Mock(), GOAL)
        click.assert_not_called()

    def test_missing_target_app_stops_instead_of_guessing_window(self):
        with (
            mock.patch("luxai.visual_reasoner.sys.platform", "win32"),
            mock.patch("luxai.visual_reasoner._select_window",
                       side_effect=ValueError("No safe app")) as select,
            mock.patch("luxai.visual_reasoner._choose") as decide,
        ):
            with self.assertRaisesRegex(ValueError, "No safe app"):
                run_visual_reasoner(mock.Mock(), GOAL)
        decide.assert_not_called()


class FeedbackRoutingUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("Qt not installed")
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self):
        import main
        import tempfile
        from pathlib import Path
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "config.json"
        path.write_text('{"microphone_enabled":false,"tts_enabled":false,'
                        '"online_agent_enabled":false}', encoding="utf-8")
        with (
            mock.patch.object(main, "CONFIG", path),
            mock.patch("sounddevice.query_devices", return_value=[]),
        ):
            window = main.MainWindow()
        self.addCleanup(window.close)
        return window

    def test_user_correction_reuses_last_visual_goal_not_smalltalk(self):
        window = self.make_window()
        window._last_visual_goal = GOAL
        window._last_visual_goal_at = time.monotonic()
        with (
            mock.patch.object(window, "_start_visual_reasoner") as run,
            mock.patch.object(window, "_start_local_chat") as chat,
        ):
            window.run_command("Ты не попал. Давай заново.")
        run.assert_called_once_with(GOAL, feedback="Ты не попал. Давай заново.")
        chat.assert_not_called()

    def test_unknown_visual_goal_routes_to_repeated_observation(self):
        window = self.make_window()
        phrase = "Жарвис, открой Discord и нажми на иконку настроек канала."
        with (
            mock.patch.object(window, "_start_visual_reasoner") as run,
            mock.patch.object(window, "_direct_macro_worker") as macro,
        ):
            window.run_command(phrase)
        run.assert_called_once_with(phrase)
        macro.assert_not_called()

    def test_discord_sending_is_not_delegated_to_unrestricted_mouse_agent(self):
        import main
        window = self.make_window()
        phrase = "Нажми в Discord на пользователя Hanzo и отправь привет."
        with (
            mock.patch.object(window, "_start_visual_reasoner") as general,
            mock.patch("main.threading.Thread") as thread,
        ):
            window.run_command(phrase)
        general.assert_not_called()
        self.assertTrue(thread.called)


if __name__ == "__main__":
    unittest.main()
