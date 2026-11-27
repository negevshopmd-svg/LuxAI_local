"""Action circle (0.4.3v): a radial menu at the cursor — your commands in one click, actions for the window
that was active, media keys and a web search for the selected text.

Pure logic (no Qt): which slots the circle shows, their labels in three languages, and the Win32 window
operations. ``extensions_runtime`` shows ``ui_convert_circle.RadialMenu`` and runs the picked slot.
"""
from __future__ import annotations

import ctypes
import sys
import urllib.parse

WINDOW_ACTIONS = ("win_minimize", "win_maximize", "win_topmost", "win_close")
MEDIA_ACTIONS = ("media_play_pause", "media_next", "media_mute")
SEARCH_ACTIONS = ("search_selection",)

LABELS = {
    "search_selection": ("Найти выделенное", "Search selection", "Caută selecția"),
    "win_minimize": ("Свернуть", "Minimize", "Minimizează"),
    "win_maximize": ("Развернуть", "Maximize", "Maximizează"),
    "win_topmost": ("Поверх всех", "Always on top", "Deasupra tuturor"),
    "win_close": ("Закрыть окно", "Close window", "Închide fereastra"),
    "media_play_pause": ("Пауза / играть", "Play / pause", "Pauză / redă"),
    "media_next": ("Следующий трек", "Next track", "Piesa următoare"),
    "media_mute": ("Без звука", "Mute", "Fără sunet"),
    "title": ("Круг действий", "Action circle", "Cerc de acțiuni"),
    "no_window": ("Окно, для которого открыт круг, уже закрыто.", "The window the circle was opened for is gone.",
                  "Fereastra pentru care s-a deschis cercul nu mai există."),
    "own_window": ("Это окно самого Jarvis — его закрывают крестиком или из трея.",
                   "This is Jarvis' own window — close it with its ✕ or from the tray.",
                   "Aceasta e fereastra lui Jarvis — închide-o din ✕ sau din tray."),
    "empty": ("В круге нет ни одного пункта: включите группы или добавьте команды в настройках плагина.",
              "The circle has no items: turn groups on or add commands in the plugin's settings.",
              "Cercul nu are niciun element: pornește grupuri sau adaugă comenzi în setările pluginului."),
    "no_command": ("Команда «{name}» не найдена или выключена в библиотеке команд.",
                   "The command «{name}» is not in the command library or is off.",
                   "Comanda „{name}” nu e în biblioteca de comenzi sau e oprită."),
    "no_selection": ("Выделите текст, чтобы найти его.", "Select some text to search for it.",
                     "Selectează un text ca să-l cauți."),
    "topmost_on": ("Окно теперь поверх всех.", "The window now stays on top.", "Fereastra stă acum deasupra tuturor."),
    "topmost_off": ("Окно больше не поверх всех.", "The window no longer stays on top.",
                    "Fereastra nu mai stă deasupra tuturor."),
}
ICONS = {"search_selection": "search", "win_minimize": "minus", "win_maximize": "maximize-2", "win_topmost": "pin",
         "win_close": "x", "media_play_pause": "play", "media_next": "chevron-right", "media_mute": "volume-x"}
MEDIA_CODES = {"media_play_pause": 0xB3, "media_next": 0xB0, "media_mute": 0xAD}
SEARCH_URLS = {"google": "https://www.google.com/search?q=", "duckduckgo": "https://duckduckgo.com/?q=",
               "bing": "https://www.bing.com/search?q="}


def word(key: str, language: str) -> str:
    return LABELS[key][{"ru": 0, "en": 1, "ro": 2}.get(language, 0)]


def _names(value) -> list[str]:
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def chosen_commands(entries, names: str, *, fallback: int = 4) -> list[dict]:
    """The library commands for the circle: the ones named in the settings (title or phrase, any case), in that
    order; with no names, the first ``fallback`` enabled personal commands. Agent commands are never shown."""
    usable = [entry for entry in entries if entry.get("enabled", True) and not entry.get("agent")]
    wanted = _names(names)
    if not wanted:
        return [entry for entry in usable if not entry.get("builtin")][:fallback]
    result = []
    for name in wanted:
        key = name.casefold()
        match = next((entry for entry in usable
                      if str(entry.get("title", "")).casefold() == key
                      or any(str(phrase).casefold() == key for phrase in entry.get("phrases", []))), None)
        if match is not None and match not in result:
            result.append(match)
    return result


def slots(settings: dict, entries, language: str) -> list[tuple[str, str, str]]:
    """[(id, label, icon)] in circle order, at most ``items``: commands first, then search, window, media.

    A command slot id is ``cmd:<command id>``. The groups fill the room the commands leave; the last ones
    (media first) are the ones left out when everything does not fit."""
    try:
        room = max(4, min(12, int(settings.get("items", 10))))
    except (TypeError, ValueError):
        room = 10
    fixed = []
    if settings.get("show_search", True):
        fixed += SEARCH_ACTIONS
    if settings.get("show_window", True):
        fixed += WINDOW_ACTIONS
    if settings.get("show_media", True):
        fixed += MEDIA_ACTIONS
    commands = chosen_commands(entries, settings.get("commands", ""))
    items = [(f"cmd:{entry['id']}", str(entry.get("title") or "")[:24], command_icon(entry)) for entry in commands]
    items += [(action, word(action, language), ICONS[action]) for action in fixed]
    return items[:room]


# 0.4.4a: every group has its own colour in the circle (commands use the theme colour).
GROUP_COLORS = {"search_selection": "#2dd4bf", "win_minimize": "#a78bfa", "win_maximize": "#a78bfa",
                "win_topmost": "#a78bfa", "win_close": "#f87171", "media_play_pause": "#f472b6",
                "media_next": "#f472b6", "media_mute": "#f472b6"}


def tint(identifier: str) -> str | None:
    """The colour of a circle item; None = the theme colour (your commands)."""
    return GROUP_COLORS.get(str(identifier or ""))


def command_icon(entry: dict) -> str:
    """The icon of what a command does (opens an app, a site, a game…), as in the command library."""
    try:
        from luxai.action_catalog import ACTION_ICONS
        from luxai.icons import ASSET_DIR
    except Exception:
        return "zap"
    name = ACTION_ICONS.get(str(entry.get("action") or ""), "")
    if name and ((ASSET_DIR / "lucide" / f"{name}.svg").is_file() or (ASSET_DIR / "project" / f"{name}.svg").is_file()):
        return name
    return "zap"


def search_url(text: str, engine: str = "google") -> str:
    query = " ".join(str(text or "").split())[:300]
    return SEARCH_URLS.get(engine, SEARCH_URLS["google"]) + urllib.parse.quote_plus(query)


# -- window operations (Win32) ---------------------------------------------------------------------------
SW_MINIMIZE, SW_MAXIMIZE, SW_RESTORE = 6, 3, 9
WM_CLOSE = 0x0010
GWL_EXSTYLE, WS_EX_TOPMOST = -20, 0x00000008
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010


_USER32 = None


def _user32():
    """A private user32 with declared types: without them ctypes passes a window handle as a 32-bit int, so a
    handle above 2^31 failed (OverflowError) and «Always on top» was not applied. A private instance keeps
    these declarations away from the other modules' calls."""
    global _USER32
    if sys.platform != "win32":
        return None
    if _USER32 is None:
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        HWND = wintypes.HWND
        user32.IsWindow.argtypes = [HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.IsZoomed.argtypes = [HWND]
        user32.IsZoomed.restype = wintypes.BOOL
        user32.IsIconic.argtypes = [HWND]
        user32.IsIconic.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.PostMessageW.argtypes = [HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostMessageW.restype = wintypes.BOOL
        user32.GetWindowLongW.argtypes = [HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowPos.argtypes = [HWND, HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                        wintypes.UINT]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        _USER32 = user32
    return _USER32


def window_alive(hwnd: int) -> bool:
    user32 = _user32()
    return bool(user32 and hwnd and user32.IsWindow(hwnd))


def is_own_window(hwnd: int) -> bool:
    user32 = _user32()
    if not user32 or not hwnd:
        return False
    import os
    from ctypes import wintypes
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == os.getpid()


def is_topmost(hwnd: int) -> bool:
    user32 = _user32()
    return bool(user32 and user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)


def window_action(action: str, hwnd: int) -> str:
    """Do ``action`` on the window; returns a message key for the user, or ""."""
    user32 = _user32()
    if user32 is None or not window_alive(hwnd):
        return "no_window"
    if action == "win_minimize":
        user32.ShowWindow(hwnd, SW_MINIMIZE)
    elif action == "win_maximize":
        user32.ShowWindow(hwnd, SW_RESTORE if user32.IsZoomed(hwnd) else SW_MAXIMIZE)
    elif action == "win_topmost":
        on = not is_topmost(hwnd)
        user32.SetWindowPos(hwnd, HWND_TOPMOST if on else HWND_NOTOPMOST, 0, 0, 0, 0,
                            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
        return "topmost_on" if on else "topmost_off"
    elif action == "win_close":
        if is_own_window(hwnd):
            return "own_window"  # never close Jarvis by accident from its own circle
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)  # like the ✕: the program may still ask to save
    return ""
