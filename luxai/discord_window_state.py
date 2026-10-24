"""Identify, restore and VERIFY the actual Discord window.

Process existence is not a usable GUI state: Discord may be in the tray,
minimized, hidden or even outside the virtual desktop. No click/capture
is allowed until the real window is restored and in the foreground.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import sys
import time

import re


def is_background_window_correction(text: str) -> bool:
    """A follow-up saying a process exists but the GUI was never opened."""
    phrase = " ".join(str(text or "").casefold().split())
    return bool(
        len(phrase) <= 220
        and re.search(
            r"(?:запущ\w*|работа\w*|процесс|фон\w*|already running|"
            r"background|ruleaz|fundal)",
            phrase,
        )
        and re.search(r"(?:окн\w*|window|fereastr\w*)", phrase)
        and re.search(
            r"(?:не\s+откр\w*|не\s+видн\w*|не\s+появ\w*|"
            r"не\s+актив\w*|not\s+open|not\s+visible|"
            r"nu\s+(?:e|este)\s+deschis|не\s+на\s+экране)",
            phrase,
        )
    )


DISCORD_NAMES = frozenset({"discord.exe", "discordptb.exe", "discordcanary.exe"})


def _user32():
    return ctypes.windll.user32


def _discord_candidates() -> list[int]:
    if sys.platform != "win32":
        raise OSError("Discord window discovery requires Windows")
    import psutil
    user32 = _user32()
    user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowTextW.argtypes = [
        wintypes.HWND, wintypes.LPWSTR, ctypes.c_int,
    ]
    found = []
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL

    @callback
    def collect(hwnd, _):
        if user32.GetWindow(hwnd, 4):  # GW_OWNER; exclude floating owned popups
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            exe = psutil.Process(pid.value).name().casefold()
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return True
        if exe not in DISCORD_NAMES:
            return True
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, len(title))
        if "discord" not in title.value.casefold():
            return True
        found.append(int(hwnd))
        return True

    user32.EnumWindows(callback, 0)
    return found


def find_discord_window() -> int:
    """Return an unambiguous REAL Discord top-level HWND, even when hidden."""
    windows = list(dict.fromkeys(_discord_candidates()))
    if len(windows) == 1:
        return windows[0]
    if len(windows) > 1:
        from luxai.screen_interact import _foreground_hwnd
        active = _foreground_hwnd()
        if active in windows:
            return active
        raise ValueError(
            "Найдено несколько окон Discord. Выберите нужное окно."
        )
    raise ValueError(
        "Окно Discord не найдено. Процесс может работать в трее."
    )


def _virtual_desktop(user32):
    return (
        int(user32.GetSystemMetrics(76)),  # SM_XVIRTUALSCREEN
        int(user32.GetSystemMetrics(77)),  # SM_YVIRTUALSCREEN
        max(1, int(user32.GetSystemMetrics(78))),
        max(1, int(user32.GetSystemMetrics(79))),
    )


def _window_on_screen(user32, hwnd):
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    x, y, width, height = _virtual_desktop(user32)
    return (
        min(int(rect.right), x + width) - max(int(rect.left), x) >= 80
        and min(int(rect.bottom), y + height) - max(int(rect.top), y) >= 70
    )


def focus_discord(hwnd: int) -> int:
    """Restore hidden/minimized/offscreen Discord; verify REAL foreground."""
    if sys.platform != "win32":
        raise OSError("Discord windows require Windows")
    import psutil
    from luxai.screen_interact import _foreground_hwnd, _window_pid, _window_title

    user32 = _user32()
    for func in ('IsWindow', 'IsWindowVisible', 'IsIconic', 'SetForegroundWindow', 'BringWindowToTop'):
        native = getattr(user32, func, None)
        if native is not None:
            try:
                native.argtypes = [wintypes.HWND]
            except (AttributeError, TypeError):
                pass
    for name in ("ShowWindow", "ShowWindowAsync"):
        fn = getattr(user32, name, None)
        if fn is not None:
            try:
                fn.argtypes = [wintypes.HWND, ctypes.c_int]
            except (AttributeError, TypeError):
                pass
    if not hwnd or not user32.IsWindow(hwnd):
        raise ValueError("Окно Discord было закрыто.")
    pid = _window_pid(hwnd)
    try:
        name = psutil.Process(pid).name().casefold()
    except (psutil.Error, OSError) as exc:
        raise ValueError("Не удалось проверить процесс Discord") from exc
    if name not in DISCORD_NAMES or "discord" not in _window_title(hwnd).casefold():
        raise ValueError("Окно не принадлежит Discord")

    # SW_SHOW first covers hidden-to-tray windows; SW_RESTORE covers minimized
    # Electron windows. Process existence alone never reaches success.
    was_hidden = not user32.IsWindowVisible(hwnd)
    was_minimized = bool(user32.IsIconic(hwnd))
    if was_hidden:
        user32.ShowWindow(hwnd, 5)
    # SW_RESTORE on an already maximized window can UNMAXIMIZE it.
    # Capture minimized state BEFORE SW_SHOW, which itself can change it.
    if was_minimized:
        user32.ShowWindow(hwnd, 9)
        if hasattr(user32, "ShowWindowAsync"):
            user32.ShowWindowAsync(hwnd, 9)
    time.sleep(0.13)

    if not _window_on_screen(user32, hwnd):
        x, y, width, height = _virtual_desktop(user32)
        # Only move a VERIFIED Discord window which is entirely offscreen.
        # Do not change a visible window's chosen monitor or size.
        user32.SetWindowPos(
            hwnd, 0, x + min(60, width // 10),
            y + min(60, height // 10), 0, 0,
            0x0001 | 0x0004 | 0x0010,  # NOSIZE|NOZORDER|NOACTIVATE
        )
    if not user32.IsWindowVisible(hwnd) or not _window_on_screen(user32, hwnd):
        raise RuntimeError(
            "Discord работает как процесс, но окно пока не видно на экране."
        )
    user32.SetForegroundWindow(hwnd)
    if hasattr(user32, "BringWindowToTop"):
        user32.BringWindowToTop(hwnd)
    for _ in range(7):
        if _foreground_hwnd() == hwnd and _window_on_screen(user32, hwnd):
            return hwnd
        time.sleep(0.12)
    raise RuntimeError(
        "Discord найден, но Windows не позволила вывести его на передний план."
    )


def activate_running_discord() -> int:
    """Attempt a real GUI activation; never report process-only success."""
    hwnd = find_discord_window()
    return focus_discord(hwnd)


def launch_or_activate_discord(confirmed=None) -> tuple[bool, str]:
    """Reveal running Discord, or wake its tray icon via its URI/executable."""
    if sys.platform != "win32":
        return False, "Discord GUI поддерживается только на Windows."
    try:
        focus_discord(find_discord_window())
        return True, "Проверено: окно Discord видно на экране и активно."
    except (OSError, ValueError, RuntimeError):
        pass
    from luxai.windows_apps import resolve_installed_app
    # A tray-only process can have NO visible main HWND. Registered URI is
    # preferable to launching a second process and is also useful for
    # Electron installations that were updated in place.
    try:
        os.startfile("discord://")
    except (OSError, AttributeError):
        path = resolve_installed_app("discord")
        if path is None:
            return False, (
                "Discord запущен в фоне либо не найден. "
                "Не удалось открыть его главное окно."
            )
        if confirmed is not None and not confirmed(
            "Запустить Discord, чтобы открыть видимое окно?"
        ):
            return False, "Действие отменено."
        import subprocess
        try:
            if path.suffix.casefold() == ".lnk":
                os.startfile(str(path))
            else:
                subprocess.Popen(
                    [str(path)], shell=False,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except OSError as exc:
            return False, f"Не удалось открыть Discord: {exc}"
    last_error = ""
    for _ in range(24):
        time.sleep(0.23)
        try:
            focus_discord(find_discord_window())
            return True, "Проверено: окно Discord открыто, видно и активно."
        except (OSError, ValueError, RuntimeError) as exc:
            last_error = str(exc)
    return False, (
        "Discord может работать в фоне, но его главное окно не "
        "удалось сделать видимым. " + last_error[:160]
    )
