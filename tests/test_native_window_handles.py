"""Exercise ctypes conversion itself using native callbacks, without a desktop."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

from luxai import discord_window_state, screen_interact, windows_apps, windows_control
from luxai.win32 import WNDENUMPROC, bind_user32, hwnd_value


NATIVE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
LARGE_HWND = 0x1234567887654321


class NativeWindows:
    """Real ctypes function pointers reveal ABI bugs that Python mocks conceal."""

    def __init__(self, *, visible=True, minimized=False, cannot_focus=False):
        self.foreground = 0
        self.visible = visible
        self.minimized = minimized
        self.cannot_focus = cannot_focus
        self.seen = []
        self.title = "Discord — Discuție"
        self.unicode_queries = []
        self._callbacks = []
        self.IsWindow = self.native(wintypes.BOOL, (wintypes.HWND,), self.is_window)
        self.IsWindowVisible = self.native(wintypes.BOOL, (wintypes.HWND,), self.is_visible)
        self.IsIconic = self.native(wintypes.BOOL, (wintypes.HWND,), lambda hwnd: self.minimized)
        self.GetForegroundWindow = self.native(wintypes.HWND, (), lambda: self.foreground)
        # Simulate a DLL lookup whose default ctypes return type is C int.
        self.GetForegroundWindow.restype = ctypes.c_int
        self.GetWindow = self.native(wintypes.HWND, (wintypes.HWND, wintypes.UINT), lambda *_: 0)
        self.GetWindowThreadProcessId = self.native(
            wintypes.DWORD, (wintypes.HWND, ctypes.POINTER(wintypes.DWORD)), self.process_id,
        )
        self.GetWindowTextLengthW = self.native(ctypes.c_int, (wintypes.HWND,), lambda _: len(self.title))
        self.GetWindowTextW = self.native(
            ctypes.c_int, (wintypes.HWND, ctypes.POINTER(ctypes.c_wchar), ctypes.c_int), self.window_text,
        )
        self.GetWindowRect = self.native(
            wintypes.BOOL, (wintypes.HWND, ctypes.POINTER(wintypes.RECT)), self.window_rect,
        )
        self.GetSystemMetrics = self.native(
            ctypes.c_int, (ctypes.c_int,), lambda i: {76: 0, 77: 0, 78: 1920, 79: 1080}[i],
        )
        self.ShowWindow = self.native(wintypes.BOOL, (wintypes.HWND, ctypes.c_int), self.show_window)
        self.ShowWindowAsync = self.native(wintypes.BOOL, (wintypes.HWND, ctypes.c_int), self.show_window)
        self.SetForegroundWindow = self.native(wintypes.BOOL, (wintypes.HWND,), self.focus)
        self.BringWindowToTop = self.native(wintypes.BOOL, (wintypes.HWND,), lambda _: 1)
        self.EnumWindows = self.native(wintypes.BOOL, (WNDENUMPROC, wintypes.LPARAM), self.enumerate)
        self.FindWindowW = self.native(
            wintypes.HWND, (wintypes.LPCWSTR, wintypes.LPCWSTR), self.find_window,
        )
        self.FindWindowW.argtypes = None
        self.FindWindowW.restype = ctypes.c_int

    def native(self, result, arguments, function):
        pointer = NATIVE(result, *arguments)(function)
        self._callbacks.append(pointer)
        return pointer

    def is_window(self, hwnd):
        self.seen.append(hwnd)
        return hwnd == LARGE_HWND

    def is_visible(self, hwnd):
        self.seen.append(hwnd)
        return self.visible

    def process_id(self, hwnd, pid):
        self.seen.append(hwnd)
        pid.contents.value = 987654
        return 7

    def window_text(self, hwnd, buffer, length):
        self.seen.append(hwnd)
        text = self.title[:length - 1]
        for index, char in enumerate(text + "\0"):
            buffer[index] = char
        return len(text)

    def window_rect(self, hwnd, rect):
        self.seen.append(hwnd)
        rect.contents.left, rect.contents.top = 50, 60
        rect.contents.right, rect.contents.bottom = 1000, 800
        return 1

    def show_window(self, hwnd, how):
        self.seen.append(hwnd)
        self.visible = True
        self.minimized = False
        return 1

    def focus(self, hwnd):
        self.seen.append(hwnd)
        if not self.cannot_focus:
            self.foreground = hwnd
        return not self.cannot_focus

    def enumerate(self, callback, lparam):
        callback(LARGE_HWND, lparam)
        return 1

    def find_window(self, class_name, title):
        self.unicode_queries.append((class_name, title))
        return LARGE_HWND


@unittest.skipUnless(ctypes.sizeof(ctypes.c_void_p) == 8, "Win64 pointer-width regression")
class NativeHandleTests(unittest.TestCase):
    def native_scope(self, native):
        patcher = mock.patch.object(
            ctypes, "windll", types.SimpleNamespace(user32=native), create=True,
        )
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_foreground_window_keeps_all_64_bits(self):
        native = NativeWindows()
        native.foreground = LARGE_HWND
        self.native_scope(native)
        with mock.patch("luxai.screen_interact.sys.platform", "win32"):
            self.assertEqual(screen_interact._foreground_hwnd(), LARGE_HWND)
            self.assertEqual(screen_interact._window_pid(LARGE_HWND), 987654)
            self.assertEqual(screen_interact._window_title(LARGE_HWND), native.title)
            self.assertEqual(screen_interact._valid_external_window(LARGE_HWND), (987654, native.title))
        self.assertTrue(native.seen)
        self.assertTrue(all(hwnd == LARGE_HWND for hwnd in native.seen))

    def test_null_foreground_is_zero_not_a_conversion_error(self):
        native = NativeWindows()
        self.native_scope(native)
        with mock.patch("luxai.screen_interact.sys.platform", "win32"):
            self.assertEqual(screen_interact._foreground_hwnd(), 0)
        self.assertEqual(hwnd_value(wintypes.HWND(LARGE_HWND)), LARGE_HWND)

    def test_wide_string_parameters_are_marshaled_explicitly(self):
        native = NativeWindows()
        bind_user32(native)
        title = "Discuție — Старый Бог"
        self.assertEqual(native.FindWindowW(None, title), LARGE_HWND)
        self.assertEqual(native.unicode_queries, [(None, title)])

    def test_discord_and_process_window_enumeration_share_callback_abi(self):
        native = NativeWindows()
        self.native_scope(native)
        process = types.SimpleNamespace(name=lambda: "Discord.exe")
        psutil = types.SimpleNamespace(
            Process=lambda _: process, Error=OSError,
            NoSuchProcess=OSError, AccessDenied=OSError,
        )
        with (
            mock.patch("luxai.discord_window_state.sys.platform", "win32"),
            mock.patch.dict(sys.modules, {"psutil": psutil}),
        ):
            # Exercise both orders against the same function pointers. An
            # incompatible EnumWindows callback type used to depend on order.
            self.assertEqual(windows_control._visible_app_windows({987654}), [LARGE_HWND])
            self.assertEqual(discord_window_state.find_discord_window(), LARGE_HWND)
            self.assertEqual(windows_control._visible_app_windows({987654}), [LARGE_HWND])
        self.assertTrue(all(hwnd == LARGE_HWND for hwnd in native.seen))

    def test_real_ctypes_discord_restore_and_foreground_validation(self):
        native = NativeWindows(visible=False, minimized=True)
        self.native_scope(native)
        psutil = types.SimpleNamespace(
            Process=lambda _: types.SimpleNamespace(name=lambda: "Discord.exe"),
            Error=OSError,
        )
        with (
            mock.patch("luxai.discord_window_state.sys.platform", "win32"),
            mock.patch.dict(sys.modules, {"psutil": psutil}),
            mock.patch("luxai.discord_window_state.time.sleep"),
        ):
            self.assertEqual(discord_window_state.focus_discord(LARGE_HWND), LARGE_HWND)
        self.assertTrue(native.visible)
        self.assertFalse(native.minimized)
        self.assertEqual(native.foreground, LARGE_HWND)

    def test_app_hwnd_requires_process_identity_and_real_foreground(self):
        native = NativeWindows()
        self.native_scope(native)
        with (
            mock.patch("luxai.windows_apps.sys.platform", "win32"),
            mock.patch("luxai.windows_apps._app_windows", return_value=[LARGE_HWND]),
        ):
            self.assertEqual(windows_apps.find_app_window("firefox"), 0)
            self.assertEqual(windows_apps.activate_app_window("firefox"), LARGE_HWND)
            self.assertEqual(windows_apps.find_app_window("firefox"), LARGE_HWND)
        with (
            mock.patch("luxai.windows_apps.sys.platform", "win32"),
            mock.patch("luxai.windows_apps._app_windows", return_value=[]),
        ):
            # Even a matching foreground HWND is unusable if app identity
            # cannot be associated with its process-owned windows.
            self.assertEqual(windows_apps.find_app_window("firefox"), 0)


class ApplicationLaunchVerificationTests(unittest.TestCase):
    def test_a_running_pid_without_a_window_is_not_launch_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "firefox.exe"
            exe.touch()
            with (
                mock.patch("luxai.windows_apps.sys.platform", "win32"),
                mock.patch("luxai.windows_apps.resolve_installed_app", return_value=exe),
                mock.patch("luxai.windows_apps.subprocess.Popen") as launch,
                mock.patch("luxai.windows_control.running_pids", return_value={987654}),
                mock.patch("luxai.windows_control._visible_app_windows", return_value=[]),
                mock.patch("time.sleep"),
            ):
                okay, message = windows_apps.launch_installed_app("firefox")
        self.assertFalse(okay)
        self.assertIn("видимое активное окно не найдено", message)
        launch.assert_called_once()

    def test_accepted_protocol_without_a_window_is_not_launch_success(self):
        with (
            mock.patch("luxai.windows_apps.sys.platform", "win32"),
            mock.patch("luxai.windows_apps.resolve_installed_app", return_value=None),
            mock.patch("luxai.windows_apps.os.startfile", create=True) as launch,
            mock.patch("luxai.windows_control.running_pids", return_value={987654}),
            mock.patch("luxai.windows_control._visible_app_windows", return_value=[]),
            mock.patch("time.sleep"),
        ):
            okay, message = windows_apps.launch_installed_app("spotify")
        self.assertFalse(okay)
        self.assertIn("видимое активное окно не найдено", message)
        launch.assert_called_once_with("spotify:")

    def test_discord_open_is_a_direct_local_operation(self):
        with (
            mock.patch("luxai.windows_apps.sys.platform", "win32"),
            mock.patch("luxai.discord_window_state.launch_or_activate_discord",
                       return_value=(True, "visible and active")) as native,
            mock.patch("luxai.windows_apps.resolve_installed_app") as discover,
            mock.patch("luxai.screen_interact.inspect_screen_buttons") as inspect,
            mock.patch("luxai.online_agent.OnlinePlanner.plan") as cloud,
        ):
            self.assertEqual(windows_apps.launch_installed_app("discord"), (True, "visible and active"))
        native.assert_called_once_with(confirmed=None)
        discover.assert_not_called()
        inspect.assert_not_called()
        cloud.assert_not_called()


class NativeProcessDiscoveryTests(unittest.TestCase):
    def process_scope(self, names):
        processes = [types.SimpleNamespace(pid=987650 + index, info={"pid": 987650 + index, "name": name})
                     for index, name in enumerate(names)]
        psutil = types.SimpleNamespace(process_iter=mock.Mock(return_value=processes), Error=OSError)
        patcher = mock.patch.dict(sys.modules, {"psutil": psutil})
        patcher.start()
        self.addCleanup(patcher.stop)
        return psutil

    def test_explorer_is_discoverable_but_still_protected_from_close(self):
        psutil = self.process_scope(["explorer.exe", "Explorer.EXE", "explorer-helper.exe"])
        self.assertEqual(windows_control.running_pids("explorer", for_discovery=True), {987650, 987651})
        self.assertEqual(windows_control.running_pids("explorer"), set())
        self.assertEqual(windows_control.process_names_for_app("explorer"), set())
        with (
            mock.patch("luxai.windows_control.sys.platform", "win32"),
            mock.patch("luxai.windows_control.get_user32") as user32,
        ):
            okay, _ = windows_control.close_installed_app("explorer")
        self.assertFalse(okay)
        user32.assert_not_called()
        psutil.process_iter.assert_called_once_with(["pid", "name"])

    def test_calculator_actual_process_names_are_matched_exactly(self):
        self.process_scope(["Calculator.exe", "CalculatorApp.exe", "calc.exe", "calculator-helper.exe"])
        self.assertEqual(windows_control.running_pids("calculator", for_discovery=True), {987650, 987651, 987652})
        self.assertEqual(windows_control.running_pids("calculator"), {987650, 987651, 987652})

    def test_app_window_discovery_does_not_use_close_permission_filter(self):
        with (
            mock.patch("luxai.windows_control.running_pids", return_value={987650}) as pids,
            mock.patch("luxai.windows_control._visible_app_windows", return_value=[LARGE_HWND]) as windows,
        ):
            self.assertEqual(windows_apps._app_windows("explorer"), [LARGE_HWND])
        pids.assert_called_once_with("explorer", for_discovery=True)
        windows.assert_called_once_with({987650})


if __name__ == "__main__":
    unittest.main()
