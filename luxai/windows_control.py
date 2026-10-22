"""Windows process/window operations for user-approved Jarvis commands.

Close an application using WM_CLOSE on visible top-level windows owned by
precisely matched executable names. We never use taskkill /F, close arbitrary
shell interpreters, or hide a failure behind a chat-style "done" answer.
"""
from __future__ import annotations

import ctypes
import os
import re
import sys
import time

from luxai.windows_apps import normalized_name, EXEC_NAMES

# Windows Code.exe has no meaningful relation to the OS "code" directory.
# Only these exact process executable names can be acted on.
KNOWN_PROCESSES = {
    **{key: tuple(x.casefold() for x in values) for key, values in EXEC_NAMES.items()},
    "vscode": ("code.exe",),
    "visual studio": ("devenv.exe",),
    "pycharm": ("pycharm64.exe", "pycharm.exe"),
    "notepad++": ("notepad++.exe",),
    "obs": ("obs64.exe", "obs32.exe"),
    "blender": ("blender.exe",),
    "vlc": ("vlc.exe",),
}
NEVER_CLOSE = {
    "explorer.exe", "winlogon.exe", "csrss.exe", "services.exe",
    "svchost.exe", "lsass.exe", "system", "smss.exe", "dwm.exe",
    "cmd.exe", "powershell.exe", "pwsh.exe", "conhost.exe",
    "python.exe", "pythonw.exe", "jarvis.exe", "taskmgr.exe",
}
# Closing an arbitrary unknown application is not safe without a validated
# process identity. We can learn its exact binary from a path found locally.


def process_names_for_app(name: str) -> set[str]:
    query = normalized_name(name)
    names = KNOWN_PROCESSES.get(query, ())
    if not names:
        from luxai.windows_apps import resolve_installed_app
        discovered = resolve_installed_app(query)
        if discovered is not None and discovered.suffix.casefold() == ".exe":
            names = (discovered.name.casefold(),)
    return set(names) - NEVER_CLOSE


def running_pids(name: str) -> set[int]:
    names = process_names_for_app(name)
    if not names:
        return set()
    try:
        import psutil
    except ImportError:
        return set()
    found: set[int] = set()
    for process in psutil.process_iter(["pid", "name"]):
        try:
            if str(process.info.get("name", "")).casefold() in names and process.pid != os.getpid():
                found.add(int(process.pid))
        except (psutil.Error, ValueError, TypeError):
            continue
    return found


def _visible_app_windows(pids: set[int]) -> list[int]:
    if sys.platform != "win32" or not pids:
        return []
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    windows: list[int] = []

    @callback_type
    def collect(hwnd, _):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in pids:
                windows.append(int(hwnd))
        return True

    user32.EnumWindows(collect, 0)
    return windows


def close_installed_app(name: str, confirmed=None) -> tuple[bool, str]:
    """Ask user, WM_CLOSE visible windows, verify they disappeared.

    bool is True ONLY when no relevant visible windows remain; if the app
    opens an unsaved-document confirmation the result is reported as pending.
    """
    query = normalized_name(name)
    if sys.platform != "win32":
        return False, "Закрытие программ поддерживается только на Windows."
    names = process_names_for_app(query)
    if not names:
        return False, f"Не могу безопасно определить процесс приложения «{name}»."
    pids = running_pids(query)
    if not pids:
        return False, f"Приложение «{name}» сейчас не запущено."
    windows = _visible_app_windows(pids)
    if not windows:
        return False, (
            f"Процесс «{name}» найден, но его окно не обнаружено. "
            "Принудительное завершение отключено."
        )
    question = (
        f"Закрыть «{name}»? Открытых окон: {len(windows)}.\n"
        "Несохранённые документы могут вызвать запрос на сохранение."
    )
    if confirmed is not None and not confirmed(question):
        return False, "Действие отменено."

    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.PostMessageW.argtypes = (
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )
    user32.PostMessageW.restype = wintypes.BOOL
    sent = 0
    for hwnd in windows:
        if user32.PostMessageW(hwnd, 0x0010, 0, 0):  # WM_CLOSE
            sent += 1
    if not sent:
        return False, f"Windows отказался закрыть «{name}»."
    # Wait briefly for a normal close; never force-terminate applications.
    for _ in range(6):
        time.sleep(0.20)
        remaining = set(_visible_app_windows(running_pids(query)))
        if not any(hwnd in remaining for hwnd in windows):
            return True, f"Проверено: окно «{name}» закрыто."
    return False, (
        f"Запрос закрытия отправлен «{name}», но окно ещё открыто. "
        "Проверьте запрос сохранения файлов."
    )
