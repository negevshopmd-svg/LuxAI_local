"""Exercise real ctypes hook callbacks without sending keyboard input."""
import ctypes
from ctypes import wintypes
from types import SimpleNamespace
import unittest
from unittest import mock

from luxai import command_recording


class NativeCall:
    """A native-function double accepting ctypes argtypes/restype declarations."""
    def __init__(self, function):
        self.function = function

    def __call__(self, *args):
        return self.function(*args)


class CtypesWithNativeDoubles:
    def __init__(self, kernel32):
        self.windll = SimpleNamespace(kernel32=kernel32)

    def __getattr__(self, name):
        return getattr(ctypes, name)


class KeyboardData(ctypes.Structure):
    _fields_ = [("key", wintypes.DWORD), ("scan", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("extra", ctypes.c_size_t)]


class NativeRecording039Tests(unittest.TestCase):
    def test_left_right_and_both_windows_keys_record_the_same_shortcut(self):
        for held_keys in ({0x5B}, {0x5C}, {0x5B, 0x5C}):
            with self.subTest(held_keys=held_keys):
                hooks, removed = {}, []

                def install(kind, callback, module, thread):
                    hooks[kind] = callback
                    return kind

                def foreground_pid(window, pointer):
                    ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD)).contents.value = 99
                    return 1

                def next_message(*args):
                    # Deliver D while Windows is held in a supported game.
                    # Missing the modifier would wrongly save a plain D action.
                    data = KeyboardData(key=0x44)
                    hooks[13](0, 0x0100, ctypes.addressof(data))
                    return 0

                user32 = SimpleNamespace()
                functions = {
                    "SetWindowsHookExW": install,
                    "UnhookWindowsHookEx": lambda hook: removed.append(hook) or 1,
                    "CallNextHookEx": lambda *args: 0,
                    "GetMessageW": next_message,
                    "GetAsyncKeyState": lambda key: 0x8000 if key in held_keys else 0,
                    "GetForegroundWindow": lambda: 42,
                    "GetWindowThreadProcessId": foreground_pid,
                    "PeekMessageW": lambda *args: 0,
                    "PostQuitMessage": lambda *args: None,
                }
                for name, function in functions.items():
                    setattr(user32, name, NativeCall(function))
                kernel32 = SimpleNamespace(
                    GetModuleHandleW=NativeCall(lambda module: 1),
                    GetCurrentThreadId=NativeCall(lambda: 1),
                )
                recorder = command_recording.ActionRecorder(record_game_keys=True)
                recorder._buffer.begin()
                with (mock.patch("luxai.win32.get_user32", return_value=user32),
                      mock.patch.object(command_recording, "ctypes", CtypesWithNativeDoubles(kernel32)),
                      mock.patch("psutil.Process", return_value=SimpleNamespace(name=lambda: "dota2.exe"))):
                    recorder._run()
                self.assertEqual(recorder._buffer.steps, [
                    {"action": "hotkey", "target": "win+d", "location": "desktop"},
                ])
                self.assertEqual(set(removed), {13, 14})
                self.assertFalse(recorder.active)
                self.assertEqual(recorder.error, "")
