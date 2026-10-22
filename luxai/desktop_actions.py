"""Trusted actions selected in Jarvis's graphical command editor.

No shell command execution, no arbitrary model-supplied scripts. All Windows
keyboard/mouse operations are explicit user-created, prevalidated macro steps.
"""
from __future__ import annotations

import ctypes
import sys
import urllib.parse
import webbrowser

from luxai.action_catalog import HOTKEYS, validate_step


def _type_unicode_windows(text: str):
    """Type Cyrillic/Unicode using Windows SendInput (without clipboard edits)."""
    if sys.platform != "win32":
        raise OSError("Ввод текста доступен только на Windows")
    from ctypes import wintypes

    ULONG_PTR = ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = (
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        )

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = (
            ("dx", wintypes.LONG), ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR),
        )

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = (("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                    ("wParamH", wintypes.WORD))

    class INPUT_UNION(ctypes.Union):
        _fields_ = (("ki", KEYBDINPUT), ("mi", MOUSEINPUT),
                    ("hi", HARDWAREINPUT))

    class INPUT(ctypes.Structure):
        _fields_ = (("type", wintypes.DWORD), ("u", INPUT_UNION))

    user32 = ctypes.windll.user32
    send = user32.SendInput
    send.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    send.restype = wintypes.UINT
    # UTF-16 code units (including both halves of surrogate pairs).
    encoded = text.encode("utf-16-le")
    if len(encoded) // 2 > 350:
        raise ValueError("Слишком длинный текст")
    events = []
    for position in range(0, len(encoded), 2):
        code_unit = int.from_bytes(encoded[position:position + 2], "little")
        for flags in (0x0004, 0x0004 | 0x0002):  # UNICODE, KEYUP
            event = INPUT()
            event.type = 1
            event.u.ki = KEYBDINPUT(0, code_unit, flags, 0, 0)
            events.append(event)
    if events:
        array = (INPUT * len(events))(*events)
        count = send(len(array), array, ctypes.sizeof(INPUT))
        if count != len(array):
            raise OSError("Windows rejected keyboard input")


def execute_desktop_step(raw: dict) -> str:
    """Return a result message if action succeeds; raise for failed actions.

    Caller must obtain user approval for potentially impactful steps.
    Pauses are handled asynchronously by QTimer in main.py, not here.
    """
    step = validate_step(raw)
    action = step["action"]
    target = step["target"]

    if action == "noop":
        return ""
    if action == "open_website":
        if not webbrowser.open(target, new=2):
            raise OSError("Не удалось открыть сайт")
        return "Открыл сайт."
    if action == "search_web":
        url = "https://www.google.com/search?" + urllib.parse.urlencode({"q": target})
        if not webbrowser.open(url, new=2):
            raise OSError("Не удалось открыть результаты поиска")
        return "Открыл результаты поиска."
    if action in {"speak_text", "speak_ready", "speak_done"}:
        return {
            "speak_text": target,
            "speak_ready": "Вас понял, сэр.",
            "speak_done": "Всё готово, сэр.",
        }[action]
    if action == "lock_screen":
        if sys.platform != "win32":
            raise OSError("Блокировка экрана доступна только на Windows")
        if not ctypes.windll.user32.LockWorkStation():
            raise OSError("Не удалось заблокировать экран")
        return "Экран заблокирован."

    if sys.platform != "win32":
        raise OSError("Это действие поддерживается только на Windows")

    if action == "type_text":
        _type_unicode_windows(target)
        return "Текст введён."

    # Import lazily: pyautogui needs a real Windows graphical session.
    import pyautogui as gui
    gui.FAILSAFE = True
    gui.PAUSE = 0.06
    if action == "hotkey":
        gui.hotkey(*HOTKEYS[target], interval=0.07)
        return f"Нажато: {target.upper()}."
    if action == "press_enter":
        gui.press("enter")
        return "Нажат Enter."
    if action == "save_document":
        gui.hotkey("ctrl", "s", interval=0.08)
        return "Нажато Ctrl+S."
    if action == "mouse_click":
        gui.click()
        return "Клик выполнен."
    if action == "mouse_double_click":
        gui.doubleClick(interval=0.14)
        return "Двойной клик выполнен."
    if action == "mouse_scroll":
        gui.scroll(int(target))
        return "Прокрутка выполнена."
    if action == "mouse_move":
        x, y = (int(part) for part in target.split(","))
        if not gui.onScreen(x, y):
            raise ValueError("Координаты за пределами экрана")
        gui.moveTo(x, y, duration=0.15)
        return "Курсор перемещён."
    if action == "volume_up":
        gui.press("volumeup", presses=2, interval=0.05)
        return "Громкость увеличена."
    if action == "volume_down":
        gui.press("volumedown", presses=2, interval=0.05)
        return "Громкость уменьшена."
    raise ValueError("Действие не поддерживается исполнителем")
