"""Opt-in Windows action recording without typed text or clipboard contents.

Recorded actions are ordinary allowlisted macro steps. Recording never replays
them or reads text/clipboard contents. Printable keys are excluded by default;
an explicit game-key option permits key actions in supported game processes
only. Clicks/keys in Jarvis itself, including Stop, are always excluded.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import sys
import threading

from luxai.action_catalog import HOTKEYS, SINGLE_KEYS, validate_step


class RecordingBuffer:
    """Pure bounded recorder used by native hooks and deterministic tests."""
    def __init__(self, max_actions=8, *, own_pid=None, record_game_keys=False):
        if max_actions is not None and (type(max_actions) is not int or max_actions < 1):
            raise ValueError("Recording action count must be positive or unlimited.")
        self.max_actions = max_actions
        self.own_pid = os.getpid() if own_pid is None else own_pid
        self.record_game_keys = bool(record_game_keys)
        self.steps = []
        self.active = False
        self.error = ""
        self._lock = threading.Lock()

    @property
    def count(self):
        with self._lock:
            return len(self.steps)

    def preview(self):
        """Return a bounded read-only snapshot; never include typed text."""
        with self._lock:
            return [dict(step) for step in self.steps[-4:]]

    def begin(self):
        with self._lock:
            self.steps, self.error, self.active = [], "", True

    def stop(self):
        with self._lock:
            self.active = False
            return [dict(step) for step in self.steps]

    def _append(self, steps, foreground_pid):
        if foreground_pid == self.own_pid:
            return
        try:
            verified = [validate_step(step) for step in steps]
        except (ValueError, TypeError):
            return
        with self._lock:
            if not self.active:
                return
            if self.max_actions is not None and len(self.steps) + len(verified) > self.max_actions:
                self.active = False
                self.error = "Достигнут предел действий записи."
                return
            self.steps.extend(verified)
            if self.max_actions is not None and len(self.steps) == self.max_actions:
                self.active = False

    def record_key(self, key, modifiers=(), *, foreground_pid=None, foreground_is_game=False):
        key = str(key).casefold()
        if key == "esc":
            self.stop()
            return
        if foreground_pid == self.own_pid:
            return
        modifiers = {str(value).casefold() for value in modifiers}
        if modifiers:
            shortcut = "+".join([part for part in ("ctrl", "alt", "shift", "win") if part in modifiers] + [key])
            # The action catalog, not a raw key logger, defines combinations.
            if shortcut in HOTKEYS:
                self._append([{"action": "hotkey", "target": shortcut}], foreground_pid)
            return
        if self.record_game_keys and foreground_is_game and key in set("abcdefghijklmnopqrstuvwxyz0123456789"):
            self._append([{"action": "press_key", "target": key}], foreground_pid)
            return
        # Letters/digits/space/backspace are text input; never collect them.
        safe_navigation = {"tab", "enter", "up", "down", "left", "right", "home", "end", "pageup", "pagedown"}
        if key in safe_navigation or key in {f"f{number}" for number in range(1, 13)}:
            self._append([{"action": "press_key", "target": key}], foreground_pid)

    def record_click(self, x, y, button="left", *, foreground_pid=None):
        action = {"left": "mouse_click", "right": "mouse_right_click", "middle": "mouse_middle_click"}.get(button)
        if action is None or type(x) is not int or type(y) is not int:
            return
        self._append([{"action": "mouse_move", "target": f"{x},{y}"},
                      {"action": action}], foreground_pid)

    def record_scroll(self, x, y, clicks, *, foreground_pid=None):
        if type(x) is not int or type(y) is not int or type(clicks) is not int or not clicks:
            return
        self._append([{"action": "mouse_move", "target": f"{x},{y}"},
                      {"action": "mouse_scroll", "target": str(max(-10, min(10, clicks)))}], foreground_pid)


class ActionRecorder:
    def __init__(self, max_actions=8, *, record_game_keys=False):
        self._buffer = RecordingBuffer(max_actions, record_game_keys=record_game_keys)
        self._thread = None
        self._thread_id = None
        self._ready = threading.Event()
        self._cancelled = threading.Event()
        self._startup_error = ""

    @property
    def active(self):
        return self._buffer.active

    @property
    def error(self):
        return self._startup_error or self._buffer.error

    @property
    def count(self):
        return self._buffer.count

    @property
    def preview(self):
        return self._buffer.preview()

    def start(self):
        if self.active:
            return True
        if sys.platform != "win32":
            self._startup_error = "Запись действий доступна в Windows."
            return False
        self.stop()
        self._startup_error = ""
        self._ready.clear()
        self._cancelled.clear()
        self._buffer.begin()
        self._thread = threading.Thread(target=self._run, daemon=True, name="JarvisActionRecorder")
        self._thread.start()
        if not self._ready.wait(timeout=1.0):
            self._startup_error = "Не удалось запустить запись действий."
            self.stop()
            return False
        if self._startup_error:
            self.stop()
            return False
        return True

    def stop(self):
        self._cancelled.set()
        steps = self._buffer.stop()
        if self._thread_id and sys.platform == "win32":
            user32 = ctypes.windll.user32
            user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        return steps

    def _run(self):
        hooks = []
        try:
            from luxai.win32 import get_user32
            user32, kernel32 = get_user32(), ctypes.windll.kernel32
            callback_type = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
                ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM,
            )

            class MouseData(ctypes.Structure):
                _fields_ = [("point", wintypes.POINT), ("mouseData", wintypes.DWORD),
                            ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                            ("extra", ctypes.c_size_t)]

            class KeyboardData(ctypes.Structure):
                _fields_ = [("key", wintypes.DWORD), ("scan", wintypes.DWORD),
                            ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                            ("extra", ctypes.c_size_t)]

            user32.SetWindowsHookExW.argtypes = [ctypes.c_int, callback_type, wintypes.HINSTANCE, wintypes.DWORD]
            user32.SetWindowsHookExW.restype = ctypes.c_void_p
            user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
            user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
            user32.CallNextHookEx.restype = ctypes.c_ssize_t
            user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
            user32.GetMessageW.restype = ctypes.c_int
            user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
            user32.GetAsyncKeyState.restype = ctypes.c_short
            kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            kernel32.GetModuleHandleW.restype = wintypes.HMODULE
            pressed = set()

            def foreground_pid():
                pid = wintypes.DWORD()
                window = user32.GetForegroundWindow()
                if window:
                    user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
                return int(pid.value)

            def is_game_process(pid):
                if not self._buffer.record_game_keys or not pid or pid == self._buffer.own_pid:
                    return False
                try:
                    import psutil
                    from luxai.steam_games import GAMES
                    from luxai.windows_apps import EXEC_NAMES
                    allowed = {name.casefold() for game in GAMES for name in EXEC_NAMES.get(game, ())}
                    return psutil.Process(pid).name().casefold() in allowed
                except Exception:
                    return False

            def finish_if_needed():
                if not self.active:
                    user32.PostQuitMessage(0)

            def mouse_callback(code, message, data_pointer):
                try:
                    if code >= 0 and self.active:
                        data = ctypes.cast(data_pointer, ctypes.POINTER(MouseData)).contents
                        if not data.flags & 1:  # Ignore injected input, including replay.
                            pid = foreground_pid()
                            buttons = {0x0202: "left", 0x0205: "right", 0x0208: "middle"}
                            if message in buttons:
                                self._buffer.record_click(int(data.point.x), int(data.point.y), buttons[message], foreground_pid=pid)
                            elif message == 0x020A:
                                delta = ctypes.c_short((data.mouseData >> 16) & 0xFFFF).value
                                self._buffer.record_scroll(int(data.point.x), int(data.point.y), int(delta / 120), foreground_pid=pid)
                            finish_if_needed()
                except Exception:
                    pass
                return user32.CallNextHookEx(None, code, message, data_pointer)

            def keyboard_callback(code, message, data_pointer):
                try:
                    if code >= 0 and self.active:
                        data = ctypes.cast(data_pointer, ctypes.POINTER(KeyboardData)).contents
                        keycode = int(data.key)
                        if not data.flags & 0x10:
                            if message in (0x0101, 0x0105):
                                pressed.discard(keycode)
                            elif message in (0x0100, 0x0104) and keycode not in pressed:
                                pressed.add(keycode)
                                aliases = {0x1B: "esc", 0x09: "tab", 0x0D: "enter", 0x25: "left", 0x26: "up",
                                           0x27: "right", 0x28: "down", 0x24: "home", 0x23: "end",
                                           0x21: "pageup", 0x22: "pagedown"}
                                key = aliases.get(keycode)
                                if 0x70 <= keycode <= 0x7B:
                                    key = f"f{keycode - 0x70 + 1}"
                                elif 0x30 <= keycode <= 0x5A:
                                    key = chr(keycode).casefold()
                                modifiers = [name for name, code in (("ctrl", 0x11), ("alt", 0x12), ("shift", 0x10))
                                             if user32.GetAsyncKeyState(code) & 0x8000]
                                if any(user32.GetAsyncKeyState(code) & 0x8000 for code in (0x5B, 0x5C)):
                                    modifiers.append("win")
                                if key:
                                    pid = foreground_pid()
                                    game = (not modifiers and self._buffer.record_game_keys
                                            and is_game_process(pid))
                                    self._buffer.record_key(key, modifiers, foreground_pid=pid, foreground_is_game=game)
                                finish_if_needed()
                except Exception:
                    pass
                return user32.CallNextHookEx(None, code, message, data_pointer)

            # Keep callbacks alive until both native hooks have been removed.
            mouse_proc, keyboard_proc = callback_type(mouse_callback), callback_type(keyboard_callback)
            message = wintypes.MSG()
            user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
            self._thread_id = kernel32.GetCurrentThreadId()
            module = kernel32.GetModuleHandleW(None)
            for kind, callback in ((14, mouse_proc), (13, keyboard_proc)):
                hook = user32.SetWindowsHookExW(kind, callback, module, 0)
                if not hook:
                    raise OSError("Windows input hook unavailable")
                hooks.append(hook)
            self._ready.set()
            while not self._cancelled.is_set() and self.active:
                if user32.GetMessageW(ctypes.byref(message), None, 0, 0) <= 0:
                    break
        except Exception:
            self._startup_error = "Не удалось запустить запись действий."
        finally:
            if hooks:
                for hook in hooks:
                    user32.UnhookWindowsHookEx(hook)
            self._thread_id = None
            self._buffer.stop()
            self._ready.set()
