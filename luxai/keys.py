"""Layout-independent keyboard shortcuts (Ctrl+C / Ctrl+V / Ctrl+A).

pyautogui maps letters through the *current keyboard layout* of the calling
thread; with a Russian/Romanian layout "c" may not resolve and Ctrl+C is
never sent. Virtual-key codes are layout independent.
"""
from __future__ import annotations

import ctypes
import sys
import time

_VK = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B, "enter": 0x0D, "esc": 0x1B, "tab": 0x09,
       "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23, "left": 0x25, "up": 0x26, "right": 0x27,
       "down": 0x28, "backspace": 0x08, "space": 0x20, "pageup": 0x21, "pagedown": 0x22,
       "oem_comma": 0xBC}
KEYUP = 0x0002


def vk_code(name: str) -> int:
    name = name.casefold()
    if name in _VK:
        return _VK[name]
    if len(name) == 1 and name.isascii() and name.isalnum():
        return ord(name.upper())
    if name.startswith("f") and name[1:].isdigit():
        return 0x6F + int(name[1:])
    raise ValueError(f"unknown key {name}")


def release_modifiers() -> None:
    """Lift modifiers the user may still hold after a global shortcut."""
    if sys.platform != "win32":
        return
    user32 = ctypes.windll.user32
    for code in (0x12, 0xA4, 0xA5, 0x10, 0xA0, 0xA1, 0x5B, 0x5C):
        if user32.GetAsyncKeyState(code) & 0x8000:
            user32.keybd_event(code, 0, KEYUP, 0)


def press(*names: str, interval: float = 0.03, **_ignored) -> None:
    """press("ctrl", "c") — same call shape as pyautogui.hotkey."""
    if sys.platform != "win32":
        return
    user32 = ctypes.windll.user32
    codes = [vk_code(name) for name in names]
    for code in codes:
        user32.keybd_event(code, 0, 0, 0)
        time.sleep(interval)
    for code in reversed(codes):
        user32.keybd_event(code, 0, KEYUP, 0)
        time.sleep(interval / 2)


_PATCHED = False


def patch_pyautogui() -> None:
    """Make pyautogui.hotkey/press layout independent on Windows.

    Letters, digits and F-keys go through virtual-key codes; anything else
    (arrows, media keys, symbols) keeps pyautogui's own handling.
    """
    global _PATCHED
    if _PATCHED or sys.platform != "win32":
        return
    try:
        import pyautogui
    except Exception:
        return
    original_hotkey, original_press = pyautogui.hotkey, pyautogui.press

    def resolvable(names):
        try:
            for name in names:
                vk_code(str(name))
            return True
        except ValueError:
            return False

    def hotkey(*names, **kwargs):
        if names and resolvable(names):
            return press(*names, interval=float(kwargs.get("interval", 0.03) or 0.03))
        return original_hotkey(*names, **kwargs)

    def key_press(keys_, presses=1, interval=0.0, **kwargs):
        names = [keys_] if isinstance(keys_, str) else list(keys_)
        if names and resolvable(names):
            for _ in range(max(1, int(presses))):
                for name in names:
                    press(name, interval=0.01)
                if interval:
                    time.sleep(interval)
            return None
        return original_press(keys_, presses=presses, interval=interval, **kwargs)

    pyautogui.hotkey = hotkey
    pyautogui.press = key_press
    _PATCHED = True
