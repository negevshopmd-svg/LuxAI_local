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
    def test_completion_verifier_receives_goal_clauses_after_500_characters(self):
        from luxai.visual_reasoner import _verify_goal
        goal = "Inspect these controls: " + "visible label " * 45 + " and enable Night Light"
        planner = mock.Mock(config={})
        planner._provider.return_value = "openai"
        planner._read_json_content.return_value = {"verified": True}
        with (
            mock.patch("luxai.visual_reasoner.multimodal_messages", return_value=[{}, {}]) as pack,
            mock.patch("luxai.secure_keys.get_api_key", return_value="test-key"),
        ):
            self.assertTrue(_verify_goal(planner, goal, mock.Mock()))
        self.assertIn(goal, pack.call_args.args[0])
        self.assertIn("An open app proves success only when the whole user goal is opening that app", pack.call_args.args[0])
        self.assertIn("otherwise verify every requested subsequent control/state", pack.call_args.args[0])

    def test_click_goal_binds_explicit_app_instead_of_stale_preferred_handle(self):
        from luxai.visual_reasoner import _select_window
        with (
            mock.patch("luxai.windows_apps.activate_app_window", return_value=84) as activate,
            mock.patch("luxai.screen_interact._valid_external_window", return_value=(100, "Steam")),
            mock.patch("luxai.screen_interact._foreground_hwnd", return_value=84),
        ):
            self.assertEqual(_select_window("нажми на магазин в Стиме", preferred_hwnd=42), 84)
        activate.assert_called_once_with("steam")

    def test_windows_settings_goal_binds_native_systemsettings_identity(self):
        from luxai.visual_reasoner import _select_window
        with (
            mock.patch("luxai.windows_apps.activate_app_window", return_value=84) as activate,
            mock.patch("luxai.screen_interact._valid_external_window", return_value=(100, "Settings")),
            mock.patch("luxai.screen_interact._foreground_hwnd", return_value=84),
        ):
            self.assertEqual(_select_window("Click Night Light in Windows Settings", preferred_hwnd=42), 84)
        activate.assert_called_once_with("settings")

    def test_missing_explicit_app_does_not_capture_unrelated_foreground(self):
        from luxai.visual_reasoner import _select_window
        with (
            mock.patch("luxai.windows_apps.activate_app_window", return_value=0),
            mock.patch("luxai.screen_interact._valid_external_window") as valid,
        ):
            with self.assertRaises(ValueError):
                _select_window("Click Steam Store", preferred_hwnd=42)
        valid.assert_not_called()

    def test_observed_native_failure_falls_back_to_verified_desktop_for_known_or_unknown_app(self):
        from luxai.visual_reasoner import _select_window
        for goal, app in (("Open Steam", "steam"), ("Open Aurora", "aurora"), ("Open Discord", "discord")):
            with (
                self.subTest(goal=goal),
                mock.patch("luxai.windows_apps.activate_app_window", return_value=0) as activate,
                mock.patch("luxai.visual_reasoner._desktop_window", return_value=81) as desktop,
                mock.patch("luxai.screen_interact._foreground_hwnd", return_value=81),
                mock.patch("luxai.screen_interact._valid_external_window", return_value=(100, "Windows desktop")) as valid,
                mock.patch("luxai.discord_screen_review._ensure_discord_visible") as relaunch,
            ):
                self.assertEqual(_select_window(goal, preferred_hwnd=42, native_open_failed=True), 81)
            activate.assert_called_once_with(app)
            desktop.assert_called_once()
            valid.assert_called_once_with(81)
            relaunch.assert_not_called()

    def test_late_native_window_can_be_verified_before_using_desktop_fallback(self):
        from luxai.visual_reasoner import _select_window
        with (
            mock.patch("luxai.windows_apps.activate_app_window", return_value=84),
            mock.patch("luxai.visual_reasoner._desktop_window") as desktop,
            mock.patch("luxai.screen_interact._foreground_hwnd", return_value=84),
            mock.patch("luxai.screen_interact._valid_external_window", return_value=(200, "Steam")),
        ):
            self.assertEqual(_select_window("Open Steam", preferred_hwnd=42, native_open_failed=True), 84)
        desktop.assert_not_called()

    def test_desktop_fallback_keeps_original_compound_goal_for_post_action_verification(self):
        goal = "Open Steam and click Store"
        desktop = SimpleNamespace(hwnd=81, pid=100)
        steam = SimpleNamespace(hwnd=84, pid=200)
        with (
            mock.patch("luxai.visual_reasoner.sys.platform", "win32"),
            mock.patch("luxai.windows_apps.activate_app_window", return_value=0),
            mock.patch("luxai.visual_reasoner._desktop_window", return_value=81),
            mock.patch("luxai.screen_interact._foreground_hwnd", side_effect=[81, 84]),
            mock.patch("luxai.screen_interact._valid_external_window", side_effect=lambda hwnd: (100, "Windows desktop") if hwnd == 81 else (200, "Steam")),
            mock.patch("luxai.windows_apps.find_app_window", return_value=84),
            mock.patch("luxai.visual_reasoner.capture_window", side_effect=[desktop, RuntimeError("New window focused"), steam]),
            mock.patch("luxai.visual_reasoner._choose", side_effect=[{"action": "click", "target": "Steam icon"}, {"action": "done"}]),
            mock.patch("luxai.visual_reasoner.find_visual_target", return_value=(100, 200)),
            mock.patch("luxai.visual_reasoner.click_visual_target") as click,
            mock.patch("luxai.visual_reasoner._verify_goal", return_value=False) as verify,
            mock.patch("luxai.visual_reasoner.time.sleep"),
        ):
            planner, outcome = mock.Mock(), {}
            run_visual_reasoner(planner, goal, preferred_hwnd=42, validated_goal=True,
                                native_open_failed=True, result_sink=outcome)
        click.assert_called_once()
        verify.assert_called_once_with(planner, goal, steam)
        self.assertTrue(outcome["ok"])
        self.assertFalse(outcome["verified"])

    def test_native_open_failure_flag_does_not_bypass_visual_danger_gate(self):
        with mock.patch("luxai.visual_reasoner.sys.platform", "win32"), mock.patch("luxai.visual_reasoner._select_window") as select:
            with self.assertRaises(PermissionError):
                run_visual_reasoner(mock.Mock(), "Delete all files", validated_goal=True, native_open_failed=True)
        select.assert_not_called()

    def test_desktop_and_recycle_bin_are_visual_goals_in_supported_languages(self):
        for phrase in ("нажми пожалуйста на корзину", "click Recycle Bin on desktop",
                       "apasă pe Coșul de reciclare"):
            with self.subTest(phrase=phrase):
                self.assertTrue(is_visual_goal(phrase))

    def test_trusted_adaptive_goal_skips_only_phrase_heuristic(self):
        goal = "Open Aurora"
        self.assertFalse(is_visual_goal(goal))
        with (
            mock.patch("luxai.visual_reasoner.sys.platform", "win32"),
            mock.patch("luxai.visual_reasoner._select_window", return_value=42) as select,
            mock.patch("luxai.visual_reasoner.capture_window"),
            mock.patch("luxai.visual_reasoner._choose", return_value={"action": "stop"}),
        ):
            with self.assertRaises(ValueError):
                run_visual_reasoner(mock.Mock(), goal)
            select.assert_not_called()
            result = run_visual_reasoner(mock.Mock(), goal, validated_goal=True)
            self.assertIn("Не удалось", result)
        select.assert_called_once()

    def test_trusted_goal_still_refuses_consequential_workflows(self):
        with (
            mock.patch("luxai.visual_reasoner.sys.platform", "win32"),
            mock.patch("luxai.visual_reasoner._select_window") as select,
        ):
            for goal in ("Empty Recycle Bin", "Delete the old files", "Send a message"):
                with self.subTest(goal=goal), self.assertRaises(PermissionError):
                    run_visual_reasoner(mock.Mock(), goal, validated_goal=True)
            select.assert_not_called()

    def test_preferred_window_does_not_capture_unrelated_foreground(self):
        from luxai.visual_reasoner import _select_window
        user32 = mock.Mock()
        with (
            mock.patch("luxai.screen_interact._foreground_hwnd", side_effect=[77, 42]),
            mock.patch("luxai.screen_interact._valid_external_window", return_value=(100, "Aurora")),
            mock.patch("luxai.win32.get_user32", return_value=user32),
            mock.patch("luxai.visual_reasoner.time.sleep"),
        ):
            self.assertEqual(_select_window("Open Aurora", preferred_hwnd=42), 42)
        user32.SetForegroundWindow.assert_called_once_with(42)

    def test_failed_preferred_focus_never_falls_back_to_another_app(self):
        from luxai.visual_reasoner import _select_window
        user32 = mock.Mock()
        with (
            mock.patch("luxai.screen_interact._foreground_hwnd", return_value=77),
            mock.patch("luxai.screen_interact._valid_external_window", return_value=(100, "Aurora")),
            mock.patch("luxai.win32.get_user32", return_value=user32),
            mock.patch("luxai.visual_reasoner.time.sleep"),
        ):
            with self.assertRaises(ValueError):
                _select_window("Open Aurora", preferred_hwnd=42)
        user32.SetForegroundWindow.assert_called_once_with(42)

    def test_desktop_request_uses_shell_instead_of_remembered_application(self):
        from luxai.visual_reasoner import _select_window
        user32 = mock.Mock()
        user32.FindWindowW.return_value = 81
        with (
            mock.patch("luxai.screen_interact._foreground_hwnd", side_effect=[77, 81]),
            mock.patch("luxai.screen_interact._valid_external_window", return_value=(100, "Program Manager")) as valid,
            mock.patch("luxai.screen_interact._is_shell_desktop_window", return_value=True),
            mock.patch("luxai.win32.get_user32", return_value=user32),
            mock.patch("luxai.visual_reasoner.time.sleep"),
        ):
            self.assertEqual(_select_window("нажми пожалуйста на корзину", preferred_hwnd=42), 81)
        user32.FindWindowW.assert_called_once_with("Progman", None)
        user32.SetForegroundWindow.assert_called_once_with(81)
        self.assertTrue(all(call.args == (81,) for call in valid.call_args_list))

    def test_workerw_icon_host_is_selected_when_progman_has_no_icons(self):
        from luxai.visual_reasoner import _desktop_window
        user32 = mock.Mock()
        user32.FindWindowW.return_value = 81
        user32.EnumWindows.side_effect = lambda callback, argument: callback(84, argument)
        with (
            mock.patch("luxai.screen_interact._is_shell_desktop_window", side_effect=lambda hwnd: hwnd == 84),
            mock.patch("luxai.screen_interact._valid_external_window", return_value=(100, "Windows desktop")) as valid,
            mock.patch("luxai.win32.get_user32", return_value=user32),
        ):
            self.assertEqual(_desktop_window(), 84)
        valid.assert_called_once_with(84)

    def test_action_can_follow_verified_resulting_window_before_goal_check(self):
        first = SimpleNamespace(hwnd=42, pid=100)
        second = SimpleNamespace(hwnd=84, pid=100)
        planner = mock.Mock()
        with (
            mock.patch("luxai.visual_reasoner.sys.platform", "win32"),
            mock.patch("luxai.visual_reasoner._select_window", return_value=42),
            mock.patch("luxai.visual_reasoner.capture_window", side_effect=[
                first, RuntimeError("Old window lost foreground"), second,
            ]) as capture,
            mock.patch("luxai.screen_interact._foreground_hwnd", return_value=84),
            mock.patch("luxai.screen_interact._valid_external_window", return_value=(100, "Application settings")),
            mock.patch("luxai.visual_reasoner._choose", side_effect=[
                {"action": "click", "target": "Settings"}, {"action": "done"},
            ]),
            mock.patch("luxai.visual_reasoner.find_visual_target", return_value=(100, 200)),
            mock.patch("luxai.visual_reasoner.click_visual_target") as click,
            mock.patch("luxai.visual_reasoner._verify_goal", return_value=True) as verify,
            mock.patch("luxai.visual_reasoner.time.sleep"),
        ):
            outcome = {}
            run_visual_reasoner(planner, GOAL, result_sink=outcome)
        self.assertEqual(capture.call_args_list, [mock.call(42), mock.call(42), mock.call(84)])
        click.assert_called_once()
        verify.assert_called_once_with(planner, GOAL, second)
        self.assertTrue(outcome["verified"])

    def test_new_foreground_requires_same_process_or_requested_app_ownership(self):
        from luxai.visual_reasoner import _follow_action_window
        previous = SimpleNamespace(hwnd=42, pid=100)
        with (
            mock.patch("luxai.screen_interact._foreground_hwnd", return_value=84),
            mock.patch("luxai.screen_interact._valid_external_window", return_value=(200, "Aurora")),
            mock.patch("luxai.windows_apps.find_app_window", return_value=84) as find,
        ):
            self.assertEqual(_follow_action_window("Open Aurora", previous), 84)
        find.assert_called_once_with("aurora")

    def test_unrelated_or_protected_new_window_cannot_be_followed(self):
        from luxai.visual_reasoner import _follow_action_window
        previous = SimpleNamespace(hwnd=42, pid=100)
        with (
            mock.patch("luxai.screen_interact._foreground_hwnd", return_value=84),
            mock.patch("luxai.screen_interact._valid_external_window", return_value=(200, "Unrelated app")),
            mock.patch("luxai.windows_apps.find_app_window", return_value=0),
        ):
            with self.assertRaises(RuntimeError):
                _follow_action_window("Open Aurora", previous)
        with (
            mock.patch("luxai.screen_interact._foreground_hwnd", return_value=84),
            mock.patch("luxai.screen_interact._valid_external_window", return_value=(100, "Password required")),
        ):
            with self.assertRaises(PermissionError):
                _follow_action_window("Open Aurora", previous)

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
        self.assertIn("не удалось", result.casefold())

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

    def test_new_contact_spelling_uses_verified_discord_search_tool(self):
        goal = "Открой Discord и найди пользователя Octavian"
        planner = mock.Mock()
        with (
            mock.patch("luxai.visual_reasoner.sys.platform", "win32"),
            mock.patch("luxai.visual_reasoner._select_window", return_value=42),
            mock.patch("luxai.visual_reasoner.capture_window"),
            mock.patch("luxai.visual_reasoner._choose", side_effect=[
                {"action": "search_discord", "target": "Octavian"},
                {"action": "stop", "reason": "result list has no unique match"},
            ]),
            mock.patch("luxai.discord_search_guard.verified_discord_search") as search,
            mock.patch("luxai.visual_reasoner.click_visual_target") as click,
            mock.patch("luxai.visual_reasoner.time.sleep"),
        ):
            result = run_visual_reasoner(planner, goal)
        search.assert_called_once()
        self.assertEqual(search.call_args.args[:3],
                         (planner, 42, "@Octavian"))
        click.assert_not_called()
        self.assertIn("не удалось", result.casefold())

    def test_ai_cannot_invent_contact_name_during_search(self):
        goal = "Открой Discord и найди пользователя Octavian"
        with (
            mock.patch("luxai.visual_reasoner.sys.platform", "win32"),
            mock.patch("luxai.visual_reasoner._select_window", return_value=42),
            mock.patch("luxai.visual_reasoner.capture_window"),
            mock.patch("luxai.visual_reasoner._choose", return_value={
                "action": "search_discord", "target": "AnotherPerson",
            }),
            mock.patch("luxai.discord_search_guard.verified_discord_search") as search,
        ):
            with self.assertRaisesRegex(PermissionError, "invented"):
                run_visual_reasoner(mock.Mock(), goal)
        search.assert_not_called()

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
        # run_command persists settings after construction, so keep the
        # temporary configuration active until the window has been closed.
        config_patch = mock.patch.object(main, "CONFIG", path)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        with mock.patch("sounddevice.query_devices", return_value=[]):
            window = main.MainWindow()
        self.addCleanup(window.close)
        return window

    def test_user_correction_reuses_last_visual_goal_not_smalltalk(self):
        window = self.make_window()
        window._last_visual_goal = GOAL
        window._last_visual_goal_at = time.monotonic()
        with (
            mock.patch.object(window, "_start_discord_mic_visual") as mic,
            mock.patch.object(window, "_start_visual_reasoner") as generic,
            mock.patch.object(window, "_start_local_chat") as chat,
        ):
            window.run_command("Ты не попал. Давай заново.")
        # Microphone state changes have a dedicated verified click workflow.
        # Feedback must re-observe it, never fall into generic desktop chat.
        mic.assert_called_once_with(GOAL)
        generic.assert_not_called()
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

    def test_stale_learned_open_app_cannot_override_full_gui_request(self):
        window = self.make_window()
        phrase = "Жарвис, открой Discord и нажми на значок настроек канала"
        window.command_registry.match = mock.Mock(return_value={
            "action": "open_app", "target": "discord",
            "learned": True, "steps": [],
        })
        with (
            mock.patch.object(window, "_start_visual_reasoner") as visual,
            mock.patch.object(window, "_execute_registered") as stale,
        ):
            window.run_command(phrase)
        visual.assert_called_once_with(phrase)
        stale.assert_not_called()

    def test_discord_sending_is_not_delegated_to_unrestricted_mouse_agent(self):
        import main
        window = self.make_window()
        phrase = "Нажми в Discord на пользователя Hanzo и отправь привет."
        window.online_planner.enabled = mock.Mock(return_value=True)
        with (
            mock.patch.object(window, "_start_visual_reasoner") as general,
            mock.patch("main.threading.Thread") as thread,
        ):
            window.run_command(phrase)
        general.assert_not_called()
        self.assertTrue(thread.called)


if __name__ == "__main__":
    unittest.main()
