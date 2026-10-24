"""Offline tests for real Discord window state and verified focus.

Mocks simulate Windows APIs. No actual Discord or message sending occurs.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import sys
import types
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from luxai.discord_window_state import (
    focus_discord, find_discord_window, launch_or_activate_discord,
    is_background_window_correction,
)
from luxai.macro_planner import needs_live_macro_planning, validate_generated_macro

SEND_REQUEST = (
    "Зайти в дискорд и напиши пользователю старый бог привет "
    "и нажми enter чтобы отправить."
)


class FakeWindows:
    def __init__(self, *, hidden=False, offscreen=False, minimized=False,
                 cannot_focus=False):
        self.visible = not hidden
        self.offscreen = offscreen
        self.minimized = minimized
        self.foreground = 0
        self.cannot_focus = cannot_focus
        self.show_calls = []
        self.moves = []
        self.rect = [9000, 8500, 9900, 9000] if offscreen else [50, 50, 950, 700]

    def IsWindow(self, hwnd): return bool(hwnd == 42)
    def IsWindowVisible(self, hwnd): return self.visible
    def IsIconic(self, hwnd): return self.minimized
    def ShowWindow(self, hwnd, how):
        self.show_calls.append(int(how))
        self.visible = True
        self.minimized = False
        return 1
    def ShowWindowAsync(self, hwnd, how): return self.ShowWindow(hwnd, how)
    def GetSystemMetrics(self, index):
        return {76: 0, 77: 0, 78: 1920, 79: 1080}[index]
    def GetWindowRect(self, hwnd, rect_ptr):
        rect = ctypes.cast(rect_ptr, ctypes.POINTER(wintypes.RECT)).contents
        rect.left, rect.top, rect.right, rect.bottom = self.rect
        return 1
    def SetWindowPos(self, hwnd, insert_after, x, y, w, h, flags):
        self.moves.append((x, y))
        dx = self.rect[2] - self.rect[0]
        dy = self.rect[3] - self.rect[1]
        self.rect = [x, y, x+dx, y+dy]
        return 1
    def SetForegroundWindow(self, hwnd):
        if not self.cannot_focus:
            self.foreground = hwnd
        return not self.cannot_focus
    def BringWindowToTop(self, hwnd): return True


class WindowRestorationTests(unittest.TestCase):
    def _focus(self, native):
        with (
            mock.patch("luxai.discord_window_state.sys.platform", "win32"),
            mock.patch("luxai.discord_window_state._user32", return_value=native),
            mock.patch("luxai.screen_interact._window_pid", return_value=900),
            mock.patch("luxai.screen_interact._window_title", return_value="Discord"),
            mock.patch("luxai.screen_interact._foreground_hwnd",
                       side_effect=lambda: native.foreground),
            mock.patch.dict(sys.modules, {
                "psutil": types.SimpleNamespace(
                    Process=mock.Mock(
                        return_value=types.SimpleNamespace(name=lambda: "Discord.exe")
                    ),
                    Error=OSError,
                )
            }),
            mock.patch("luxai.discord_window_state.time.sleep"),
        ):
            return focus_discord(42)

    def test_hidden_and_minimized_discord_is_revealed_and_focused(self):
        fake = FakeWindows(hidden=True, minimized=True)
        self.assertEqual(self._focus(fake), 42)
        self.assertTrue(fake.visible)
        self.assertIn(5, fake.show_calls)
        self.assertIn(9, fake.show_calls)
        self.assertEqual(fake.foreground, 42)

    def test_second_open_does_not_unmaximize_or_move_visible_discord(self):
        fake = FakeWindows()
        self.assertEqual(self._focus(fake), 42)
        self.assertNotIn(9, fake.show_calls)
        self.assertFalse(fake.moves)

    def test_offscreen_window_is_moved_to_visible_virtual_desktop(self):
        fake = FakeWindows(offscreen=True)
        self.assertEqual(self._focus(fake), 42)
        self.assertTrue(fake.moves)
        self.assertLess(fake.rect[0], 1920)
        self.assertLess(fake.rect[1], 1080)

    def test_process_exists_but_window_cannot_be_focused_is_not_success(self):
        fake = FakeWindows(hidden=True, cannot_focus=True)
        with self.assertRaisesRegex(RuntimeError, "передний план"):
            self._focus(fake)

    def test_wrong_process_is_never_restored(self):
        fake = FakeWindows(hidden=True)
        with (
            mock.patch("luxai.discord_window_state.sys.platform", "win32"),
            mock.patch("luxai.discord_window_state._user32", return_value=fake),
            mock.patch("luxai.screen_interact._window_pid", return_value=900),
            mock.patch("luxai.screen_interact._window_title", return_value="Discord"),
            mock.patch.dict(sys.modules, {
                "psutil": types.SimpleNamespace(
                    Process=mock.Mock(
                        return_value=types.SimpleNamespace(name=lambda: "Unknown.exe")
                    ),
                    Error=OSError,
                )
            }),
        ):
            with self.assertRaisesRegex(ValueError, "не принадлежит"):
                focus_discord(42)
        self.assertEqual(fake.show_calls, [])


class LaunchVerificationTests(unittest.TestCase):
    def test_existing_discord_window_is_restored_not_launched_again(self):
        with (
            mock.patch("luxai.discord_window_state.sys.platform", "win32"),
            mock.patch("luxai.discord_window_state.find_discord_window",
                       return_value=42),
            mock.patch("luxai.discord_window_state.focus_discord") as focus,
            mock.patch("luxai.discord_window_state.os.startfile",
                       create=True) as launch,
        ):
            okay, answer = launch_or_activate_discord()
        self.assertTrue(okay)
        focus.assert_called_once_with(42)
        launch.assert_not_called()
        self.assertIn("окно Discord видно", answer)

    def test_discord_in_tray_requires_real_window_after_uri(self):
        with (
            mock.patch("luxai.discord_window_state.sys.platform", "win32"),
            mock.patch("luxai.discord_window_state.find_discord_window",
                       side_effect=[ValueError("hidden tray"), 42]),
            mock.patch("luxai.discord_window_state.focus_discord") as focus,
            mock.patch("luxai.discord_window_state.os.startfile",
                       create=True) as launch,
            mock.patch("luxai.discord_window_state.time.sleep"),
        ):
            okay, answer = launch_or_activate_discord()
        self.assertTrue(okay)
        focus.assert_called_once_with(42)
        launch.assert_called_once_with("discord://")
        self.assertIn("открыто", answer)

    def test_tray_process_alone_never_reports_success(self):
        with (
            mock.patch("luxai.discord_window_state.sys.platform", "win32"),
            mock.patch("luxai.discord_window_state.find_discord_window",
                       side_effect=ValueError("hidden tray")),
            mock.patch("luxai.discord_window_state.os.startfile",
                       create=True),
            mock.patch("luxai.discord_window_state.time.sleep"),
        ):
            okay, answer = launch_or_activate_discord()
        self.assertFalse(okay)
        self.assertIn("не удалось сделать видимым", answer)

    def test_windows_app_dispatch_uses_verified_discord_path(self):
        from luxai.windows_apps import launch_installed_app
        with (
            mock.patch("luxai.windows_apps.sys.platform", "win32"),
            mock.patch("luxai.discord_window_state.launch_or_activate_discord",
                       return_value=(True, "visible and active")) as focused,
            mock.patch("luxai.windows_apps.resolve_installed_app") as resolve,
        ):
            self.assertEqual(
                launch_installed_app("дискорд"),
                (True, "visible and active"),
            )
        focused.assert_called_once()
        resolve.assert_not_called()

    def test_capture_precondition_restores_before_returning_hwnd(self):
        from luxai.discord_screen_review import _ensure_discord_visible
        with (
            mock.patch("luxai.discord_screen_review.find_discord_window",
                       return_value=42),
            mock.patch("luxai.discord_window_state.focus_discord") as focus,
            mock.patch("luxai.windows_apps.launch_installed_app") as launch,
        ):
            self.assertEqual(_ensure_discord_visible(), 42)
        focus.assert_called_once_with(42)
        launch.assert_not_called()


class SpokenIntentTests(unittest.TestCase):
    def test_compound_send_never_degrades_to_just_open_discord(self):
        self.assertTrue(needs_live_macro_planning(SEND_REQUEST))
        self.assertIsNone(validate_generated_macro({
            "steps": [{"action": "open_app", "target": "discord"}],
        }, SEND_REQUEST))
        proposed = validate_generated_macro({
            "steps": [{"action": "discord_send_text",
                       "target": "старый бог||привет"}],
        }, SEND_REQUEST)
        self.assertEqual(proposed["steps"][0]["action"], "discord_send_text")

    def test_corresponding_process_window_correction_is_recognized(self):
        self.assertTrue(is_background_window_correction(
            "он запущен но окно же не открыто"
        ))
        self.assertFalse(is_background_window_correction(
            "Discord открыт, нажми на микрофон"
        ))

    def test_followup_restores_window_without_repeating_send_request(self):
        try:
            from PySide6.QtWidgets import QApplication
            import main
        except ImportError:
            self.skipTest("Qt unavailable")
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                '{"microphone_enabled":false,"tts_enabled":false,'
                '"online_agent_enabled":false}', encoding="utf-8"
            )
            with (
                mock.patch.object(main, "CONFIG", path),
                mock.patch("sounddevice.query_devices", return_value=[]),
            ):
                window = main.MainWindow()
            try:
                window._last_visual_goal = SEND_REQUEST
                window._last_visual_goal_at = time.monotonic()
                with (
                    mock.patch("luxai.windows_apps.launch_installed_app",
                               return_value=(True, "visible")) as restore,
                    mock.patch.object(window, "_run_saved_steps") as send,
                    mock.patch.object(window, "_resolved_command") as report,
                ):
                    window.run_command("он запущен но окно же не открыто")
                restore.assert_called_once_with("discord")
                send.assert_not_called()
                self.assertEqual(report.call_args.args[1], "visible")
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
