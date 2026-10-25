"""Discord's hidden Electron helpers must not appear as extra app windows."""
from __future__ import annotations

from contextlib import ExitStack
import ctypes
from ctypes import wintypes
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

from luxai.discord_window_state import _discord_candidates, find_discord_window


class WindowApi:
    def __init__(self, windows, foreground=0):
        self.windows = windows
        self.foreground = foreground

    def EnumWindows(self, callback, data):
        for hwnd in self.windows:
            callback(hwnd, data)
        return 1

    def GetWindow(self, hwnd, kind):
        return self.windows[hwnd].get("owner", 0)

    def GetWindowThreadProcessId(self, hwnd, pointer):
        ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD)).contents.value = self.windows[hwnd].get("pid", 101)
        return 1

    def GetWindowTextW(self, hwnd, output, length):
        output.value = self.windows[hwnd].get("title", "Discord")[:length - 1]
        return len(output.value)

    def GetClassNameW(self, hwnd, output, length):
        output.value = self.windows[hwnd].get("class", "Chrome_WidgetWin_1")[:length - 1]
        return len(output.value)

    def GetWindowLongPtrW(self, hwnd, index):
        return self.windows[hwnd].get("style", 0)

    def GetWindowRect(self, hwnd, pointer):
        value = ctypes.cast(pointer, ctypes.POINTER(wintypes.RECT)).contents
        value.left, value.top, value.right, value.bottom = self.windows[hwnd].get("rect", (50, 50, 1000, 800))
        return 1

    def GetSystemMetrics(self, index):
        return {76: 0, 77: 0, 78: 1920, 79: 1080}[index]

    def GetForegroundWindow(self):
        return self.foreground

    def IsWindowVisible(self, hwnd):
        return self.windows[hwnd].get("visible", True)

    def IsIconic(self, hwnd):
        return self.windows[hwnd].get("minimized", False)


class DiscordWindowSelectionTests(unittest.TestCase):
    def scope(self, windows, *, foreground=0, process_names=None):
        stack = ExitStack()
        self.addCleanup(stack.close)
        api = WindowApi(windows, foreground)
        processes = process_names or {101: "Discord.exe"}
        psutil = SimpleNamespace(
            Process=lambda pid: SimpleNamespace(name=lambda: processes[pid]),
            Error=OSError, NoSuchProcess=OSError, AccessDenied=OSError,
        )
        stack.enter_context(mock.patch("luxai.discord_window_state.sys.platform", "win32"))
        stack.enter_context(mock.patch("luxai.discord_window_state._user32", return_value=api))
        stack.enter_context(mock.patch("luxai.discord_window_state._window_cloaked",
                                       side_effect=lambda hwnd: windows[hwnd].get("cloaked", False)))
        stack.enter_context(mock.patch.dict(sys.modules, {"psutil": psutil}))
        return api

    def test_unique_visible_main_wins_over_hidden_titled_discord_frames(self):
        self.scope({
            41: {"visible": False, "class": "Chrome_WidgetWin_0"},
            42: {"title": "Friends - Discord"},
            43: {"visible": False, "title": "Discord"},
        }, foreground=999)
        self.assertEqual(find_discord_window(), 42)

    def test_owned_tool_nonactivating_and_tiny_helpers_are_not_candidates(self):
        self.scope({
            40: {"owner": 42},
            41: {"style": 0x80},
            42: {"title": "Friends - Discord"},
            43: {"style": 0x08000000},
            44: {"rect": (0, 0, 1, 1)},
            45: {"class": "Chrome_MessageWindow"},
        })
        self.assertEqual(_discord_candidates(), [42])
        self.assertEqual(find_discord_window(), 42)

    def test_cloaked_and_offscreen_frames_do_not_duplicate_visible_window(self):
        self.scope({
            41: {"cloaked": True},
            42: {"title": "Friends - Discord"},
            43: {"rect": (5000, 5000, 6000, 5800)},
        })
        self.assertEqual(find_discord_window(), 42)

    def test_multiple_visible_accounts_are_still_ambiguous(self):
        self.scope({41: {}, 42: {"pid": 102, "title": "Discord Canary"}},
                   foreground=999, process_names={101: "Discord.exe", 102: "DiscordCanary.exe"})
        with self.assertRaisesRegex(ValueError, "несколько окон"):
            find_discord_window()

    def test_user_foreground_selects_between_real_visible_accounts(self):
        self.scope({41: {}, 42: {"pid": 102, "title": "Discord PTB"}},
                   foreground=42, process_names={101: "Discord.exe", 102: "DiscordPTB.exe"})
        self.assertEqual(find_discord_window(), 42)

    def test_one_minimized_main_remains_restorable_despite_tiny_icon_rect(self):
        self.scope({42: {"minimized": True, "rect": (-32000, -32000, -31840, -31972)}})
        self.assertEqual(find_discord_window(), 42)

    def test_hidden_main_can_be_recovered_from_tray_without_launching(self):
        self.scope({41: {"visible": False, "class": "Chrome_WidgetWin_0"},
                    42: {"visible": False, "class": "Chrome_WidgetWin_1"}})
        self.assertEqual(find_discord_window(), 42)

    def test_two_hidden_main_frames_remain_ambiguous(self):
        self.scope({41: {"visible": False}, 42: {"visible": False}})
        with self.assertRaisesRegex(ValueError, "несколько окон"):
            find_discord_window()

    def test_only_cloaked_main_is_not_reported_as_current_desktop(self):
        self.scope({42: {"cloaked": True}})
        with self.assertRaisesRegex(ValueError, "другом рабочем столе"):
            find_discord_window()

    def test_an_unrelated_process_with_discord_title_is_not_a_candidate(self):
        self.scope({41: {"pid": 103}, 42: {}}, process_names={101: "Discord.exe", 103: "chrome.exe"})
        self.assertEqual(_discord_candidates(), [42])


if __name__ == "__main__":
    unittest.main()
