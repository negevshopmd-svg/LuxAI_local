"""Graceful game close verifies real Win32 marshalling, ownership and exit."""
import ctypes
from ctypes import wintypes
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

from luxai import windows_control
from luxai.win32 import WNDENUMPROC, bind_user32

NATIVE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
GAME_HWND = 0x1234567887654321
STEAM_HWND = GAME_HWND + 1


class NativeGameWindows:
    def __init__(self, behavior="exit", title="War Thunder"):
        self.behavior = behavior
        self.processes = {711: "aces.exe", 712: "Steam.exe", 713: "aces-helper.exe"}
        self.windows = {GAME_HWND: [711, title, True], STEAM_HWND: [712, "Steam", True]}
        self.posts = []
        self.callbacks = []
        self.IsWindow = self.native(wintypes.BOOL, (wintypes.HWND,), lambda h: h in self.windows)
        self.IsWindowVisible = self.native(wintypes.BOOL, (wintypes.HWND,), lambda h: self.windows.get(h, [0, "", False])[2])
        self.GetWindowTextLengthW = self.native(ctypes.c_int, (wintypes.HWND,), lambda h: len(self.windows.get(h, [0, "", False])[1]))
        self.GetWindowTextW = self.native(ctypes.c_int, (wintypes.HWND, ctypes.POINTER(ctypes.c_wchar), ctypes.c_int), self.title)
        self.GetWindowThreadProcessId = self.native(wintypes.DWORD, (wintypes.HWND, ctypes.POINTER(wintypes.DWORD)), self.pid)
        self.EnumWindows = self.native(wintypes.BOOL, (WNDENUMPROC, wintypes.LPARAM), self.enumerate)
        self.PostMessageW = self.native(wintypes.BOOL, (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM), self.post)

    def native(self, result, arguments, function):
        callback = NATIVE(result, *arguments)(function)
        self.callbacks.append(callback)
        return callback

    def title(self, hwnd, output, length):
        text = self.windows.get(hwnd, [0, "", False])[1][:length - 1]
        for i, value in enumerate(text + "\0"):
            output[i] = value
        return len(text)

    def pid(self, hwnd, output):
        output.contents.value = self.windows.get(hwnd, [0])[0]
        return 1

    def enumerate(self, callback, param):
        for hwnd in list(self.windows):
            if not callback(hwnd, param):
                break
        return True

    def post(self, hwnd, message, wparam, lparam):
        self.posts.append((hwnd, message))
        if self.behavior == "exit":
            self.windows.pop(hwnd, None)
            self.processes.pop(711, None)
        elif self.behavior == "hide":
            self.windows[hwnd][2] = False
        elif self.behavior == "respawn":
            self.windows.pop(hwnd, None)
            self.windows[GAME_HWND + 2] = [711, "War Thunder", True]
        return True


class GameCloseNativeTests(unittest.TestCase):
    def scope(self, native):
        process_library = SimpleNamespace(
            Error=OSError,
            process_iter=mock.Mock(side_effect=lambda _attrs: [
                SimpleNamespace(pid=pid, info={"pid": pid, "name": name})
                for pid, name in native.processes.items()
            ]),
        )
        for patch in (
            mock.patch.dict(sys.modules, {"psutil": process_library}),
            mock.patch.object(windows_control.sys, "platform", "win32"),
            mock.patch.object(windows_control, "get_user32", return_value=bind_user32(native)),
            mock.patch.object(windows_control.time, "sleep"),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        return process_library

    def test_wm_close_targets_only_exact_game_binary_and_window_then_verifies_game_exit(self):
        native = NativeGameWindows()
        self.scope(native)
        self.assertEqual(windows_control.running_pids("War Thunder"), {711})
        okay, message = windows_control.close_installed_app("war tander", confirmed=lambda _: True, language="ro")
        self.assertTrue(okay, message)
        self.assertIn("Verificat", message)
        self.assertEqual(native.posts, [(GAME_HWND, 0x0010)])
        self.assertIn(STEAM_HWND, native.windows)
        self.assertEqual(native.processes, {712: "Steam.exe", 713: "aces-helper.exe"})

    def test_repeated_close_of_absent_game_is_idempotent_and_does_not_close_steam(self):
        native = NativeGameWindows()
        native.processes.pop(711)
        native.windows.pop(GAME_HWND)
        self.scope(native)
        for language, word in (("ru", "не запущено"), ("ro", "nu rulează"), ("en", "not running")):
            okay, message = windows_control.close_installed_app("War Thunder", language=language)
            self.assertTrue(okay, message)
            self.assertIn(word, message)
        self.assertEqual(native.posts, [])
        self.assertIn(STEAM_HWND, native.windows)

    def test_wrong_window_title_or_background_client_does_not_grant_force_termination(self):
        for native in (NativeGameWindows(title="Other ACES editor"), NativeGameWindows()):
            if native.windows[GAME_HWND][1] == "War Thunder":
                native.windows[GAME_HWND][2] = False
            self.scope(native)
            okay, message = windows_control.close_installed_app("War Thunder", confirmed=lambda _: True)
            self.assertFalse(okay)
            self.assertEqual(native.posts, [])
            self.assertIn("не подтверждено", message)

    def test_confirmation_decline_or_reused_handle_never_posts_to_other_application(self):
        native = NativeGameWindows()
        self.scope(native)
        self.assertFalse(windows_control.close_installed_app("War Thunder", confirmed=lambda _: False)[0])
        def change_owner(_question):
            native.windows[GAME_HWND][0] = 712
            return True
        self.assertFalse(windows_control.close_installed_app("War Thunder", confirmed=change_owner)[0])
        self.assertEqual(native.posts, [])

    def test_hidden_window_or_respawned_window_does_not_falsely_confirm_game_exit(self):
        for behavior in ("hide", "respawn", "unchanged"):
            with self.subTest(behavior=behavior):
                native = NativeGameWindows(behavior)
                self.scope(native)
                okay, message = windows_control.close_installed_app("War Thunder", confirmed=lambda _: True, language="en")
                self.assertFalse(okay)
                self.assertIn("not yet confirmed", message)
                self.assertEqual(native.posts, [(GAME_HWND, 0x0010)])

    def test_process_inspection_unavailable_cannot_claim_game_already_closed(self):
        native = NativeGameWindows()
        self.scope(native)
        with mock.patch.dict(sys.modules, {"psutil": None}):
            okay, message = windows_control.close_installed_app("War Thunder", language="ro")
        self.assertFalse(okay)
        self.assertEqual(native.posts, [])
        self.assertIn("verifica", message)

    def test_incomplete_process_snapshot_cannot_claim_game_already_closed(self):
        class UnreadableProcess:
            pid = 901

            @property
            def info(self):
                raise OSError("access denied")

        for inspection in (OSError("access denied"), [SimpleNamespace(pid=901, info={"name": None})],
                           [UnreadableProcess()]):
            with self.subTest(inspection=inspection):
                native = NativeGameWindows()
                library = self.scope(native)
                if isinstance(inspection, Exception):
                    library.process_iter.side_effect = inspection
                else:
                    library.process_iter.side_effect = lambda _attrs: inspection
                okay, message = windows_control.close_installed_app("War Thunder", language="en")
                self.assertFalse(okay)
                self.assertIn("not confirmed", message)
                self.assertEqual(native.posts, [])

    def test_unreadable_windows_kernel_and_idle_names_do_not_block_absent_game_check(self):
        native = NativeGameWindows()
        native.processes.pop(711)
        native.windows.pop(GAME_HWND)
        library = self.scope(native)
        library.process_iter.side_effect = lambda _attrs: [
            SimpleNamespace(pid=0, info={"name": None}),
            SimpleNamespace(pid=4, info={"name": None}),
            SimpleNamespace(pid=712, info={"name": "Steam.exe"}),
        ]
        okay, message = windows_control.close_installed_app("War Thunder", language="en")
        self.assertTrue(okay, message)
        self.assertIn("not running", message)
        self.assertEqual(native.posts, [])

    def test_process_that_exits_during_snapshot_is_not_an_access_failure(self):
        class ExitedProcess(OSError):
            pass

        class Disappeared:
            pid = 900

            @property
            def info(self):
                raise ExitedProcess("process exited")

        native = NativeGameWindows()
        native.processes.pop(711)
        native.windows.pop(GAME_HWND)
        library = self.scope(native)
        library.NoSuchProcess = ExitedProcess
        library.process_iter.side_effect = lambda _attrs: [Disappeared()]
        okay, message = windows_control.close_installed_app("War Thunder", language="en")
        self.assertTrue(okay, message)
        self.assertIn("not running", message)

    def test_failed_snapshot_after_wm_close_cannot_confirm_exit(self):
        native = NativeGameWindows()
        library = self.scope(native)
        snapshot = [SimpleNamespace(pid=pid, info={"name": name})
                    for pid, name in native.processes.items()]
        library.process_iter.side_effect = [snapshot, snapshot, OSError("access denied")]
        okay, message = windows_control.close_installed_app("War Thunder", confirmed=lambda _: True, language="en")
        self.assertFalse(okay)
        self.assertIn("not confirmed", message)
        self.assertEqual(native.posts, [(GAME_HWND, 0x0010)])

    def test_unreadable_unrelated_service_does_not_block_verified_game_window_close(self):
        native = NativeGameWindows()
        library = self.scope(native)
        library.process_iter.side_effect = lambda _attrs: [
            *[SimpleNamespace(pid=pid, info={"name": name})
              for pid, name in native.processes.items()],
            SimpleNamespace(pid=901, info={"name": None}),
        ]
        okay, message = windows_control.close_installed_app(
            "War Thunder", confirmed=lambda _: True, language="en")
        self.assertEqual(native.posts, [(GAME_HWND, 0x0010)])
        self.assertNotIn(GAME_HWND, native.windows)
        self.assertIn(STEAM_HWND, native.windows)
        # The observed target can close, but incomplete global inspection
        # cannot establish that no game client has remained/respawned.
        self.assertFalse(okay)
        self.assertIn("not confirmed", message)


if __name__ == "__main__":
    unittest.main()
