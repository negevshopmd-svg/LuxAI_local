"""Resolve installed Windows apps by name rather than by AI-supplied commands.

Lookup uses App Paths, Start Menu shortcuts, common install locations and PATH.
No name is ever interpolated into CMD/PowerShell. App search is local and only
launches an executable/shortcut discovered on the current user's machine.
"""
from __future__ import annotations

import glob
import ctypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from luxai.win32 import get_user32, hwnd_value, window_on_screen
from luxai.steam_games import ALIASES as GAME_ALIASES

ALIASES = {
    "файерфокс": "firefox",
    "фаерфокс": "firefox",
    "файрфокс": "firefox",
    "фоерфокс": "firefox",
    "фаирфокс": "firefox",
    "mozilla firefox": "firefox",
    "мозила": "firefox",
    "телеграм": "telegram",
    "телеграмм": "telegram",
    "дискорд": "discord",
    "хром": "chrome",
    "гугл хром": "chrome",
    "блокнот": "notepad",
    "ворд": "word",
    "ворде": "word",
    "microsoft word": "word",
    "калькулятор": "calculator",
    "проводник": "explorer",
    "стим": "steam",
    "спотифай": "spotify",
    "эдж": "edge",
    "visual studio code": "vscode",
    "visual studio код": "vscode",
    "vs code": "vscode",
    "v s code": "vscode",
    "vscode": "vscode",
    "вс код": "vscode",
    "ви эс код": "vscode",
    "визуал студио код": "vscode",
    "визуал студия код": "vscode",
    "код студио": "vscode",
    "визуал студио": "visual studio",
    "windows settings": "settings",
    "настройки windows": "settings",
    "setări windows": "settings",
    "setari windows": "settings",
    **{alias: game for game, aliases in GAME_ALIASES.items() for alias in aliases},
}
EXEC_NAMES = {
    "firefox": ("firefox.exe",),
    "chrome": ("chrome.exe",),
    "edge": ("msedge.exe",),
    "telegram": ("Telegram.exe",),
    "discord": ("Discord.exe",),
    "spotify": ("Spotify.exe",),
    "steam": ("Steam.exe", "steamwebhelper.exe"),
    "settings": ("SystemSettings.exe",),
    "notepad": ("notepad.exe",),
    "word": ("WINWORD.EXE",),
    "calculator": ("calc.exe", "Calculator.exe", "CalculatorApp.exe"),
    "explorer": ("explorer.exe",),
    "vscode": ("Code.exe",),
    "visual studio": ("devenv.exe",),
    "pycharm": ("pycharm64.exe", "pycharm.exe"),
    "blender": ("blender.exe",),
    "warthunder": ("aces.exe",),
    "dota2": ("dota2.exe",),
    "cs2": ("cs2.exe",),
    "undertale": ("undertale.exe",),
}
# Resolve common apps even if they haven't registered App Paths.
COMMON_DIRS = {
    "firefox": ("Mozilla Firefox/firefox.exe",),
    "chrome": ("Google/Chrome/Application/chrome.exe",),
    "edge": ("Microsoft/Edge/Application/msedge.exe",),
    "telegram": ("Telegram Desktop/Telegram.exe",),
    "steam": ("Steam/steam.exe",),
    "spotify": ("Spotify/Spotify.exe",),
    "vscode": (
        "Programs/Microsoft VS Code/Code.exe",
        "Microsoft VS Code/Code.exe",
    ),
    "visual studio": ("Microsoft Visual Studio/2022/Community/Common7/IDE/devenv.exe",),
}


def normalized_name(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError("Название приложения должно быть текстом")
    value = " ".join(name.casefold().strip().split())
    if not (1 <= len(value) <= 90):
        raise ValueError("Название приложения должно быть от 1 до 90 символов")
    if not re.fullmatch(r"[\w\u0400-\u04ff .()+-]+", value, flags=re.UNICODE):
        raise ValueError("Недопустимые символы в названии приложения")
    if "/" in value or "\\" in value or value in {".", ".."} or value.endswith((".exe", ".bat", ".cmd", ".ps1")):
        raise ValueError("Нужно название приложения, не путь к файлу и не команда")
    value = ALIASES.get(value, value)
    # AI must not be able to relabel a terminal or script host as an app.
    if value in {
        "cmd", "powershell", "pwsh", "terminal", "wt", "bash", "sh",
        "wscript", "cscript", "mshta", "regedit", "rundll32",
        "taskkill", "schtasks", "msiexec", "python", "pythonw",
    }:
        raise ValueError("Командные интерпретаторы не запускаются по онлайн-плану")
    return value


def _match_name(query: str, candidate: str) -> bool:
    candidate = candidate.casefold()
    # Exact or app-name with normal vendor suffix; no fuzzy substring "cmd".
    stem = Path(candidate).stem if candidate.endswith(".exe") or candidate.endswith(".lnk") else candidate
    if query == "vscode" and ("visual studio code" in stem or stem == "code"):
        return True
    return query == stem or query == candidate or (
        query in stem.split() and len(query) >= 4
    )


def app_path_candidates(name: str):
    """Yield path candidates in reliability order, without traversing disks."""
    query = normalized_name(name)
    exes = EXEC_NAMES.get(query, (query.replace(" ", "") + ".exe",))
    for exe in exes:
        path = shutil.which(exe)
        if path:
            yield Path(path)

    if sys.platform != "win32":
        return

    try:
        import winreg

        root_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for exe in exes:
                try:
                    with winreg.OpenKey(hive, root_path + "\\" + exe) as key:
                        value, _ = winreg.QueryValueEx(key, "")
                        if value:
                            yield Path(os.path.expandvars(str(value).strip().strip('"')))
                except OSError:
                    continue
    except ImportError:
        pass

    locations = [
        os.environ.get("PROGRAMFILES", ""),
        os.environ.get("PROGRAMFILES(X86)", ""),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    for base in filter(None, locations):
        for rel in COMMON_DIRS.get(query, ()):
            yield Path(base) / Path(rel)

    menu_roots = [
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    ]
    for directory in menu_roots:
        if not directory.is_dir():
            continue
        # This is not an unbounded full disk scan, only the Start menu.
        for shortcut in directory.rglob("*.lnk"):
            if _match_name(query, shortcut.stem):
                yield shortcut


def resolve_installed_app(name: str) -> Path | None:
    for candidate in app_path_candidates(name):
        try:
            if candidate.is_file() and candidate.suffix.casefold() in {".exe", ".lnk"}:
                return candidate
        except OSError:
            continue
    return None


def _app_windows(name: str) -> list[int]:
    from luxai.windows_control import running_pids, _visible_app_windows
    # Discovery may observe Explorer/system-owned windows without granting the
    # close operation permission to terminate those protected processes.
    return _visible_app_windows(running_pids(name, for_discovery=True))


def _usable_window(user32, hwnd: int, *, foreground_only: bool) -> bool:
    return bool(
        hwnd and user32.IsWindow(hwnd) and user32.IsWindowVisible(hwnd)
        and not user32.IsIconic(hwnd) and window_on_screen(user32, hwnd)
        and (not foreground_only or hwnd_value(user32.GetForegroundWindow()) == hwnd)
    )


def find_app_window(name: str, *, foreground_only=True) -> int:
    """Find a verified app-owned visible HWND, with no screenshots or cloud.

    By default require foreground ownership too, so a follow-up visual task
    cannot accidentally capture whichever unrelated app happens to be active.
    A process in the tray or an offscreen/minimized window returns zero.
    """
    query = normalized_name(name)
    if sys.platform != "win32":
        return 0
    windows = _app_windows(query)
    if not windows:
        return 0
    user32 = get_user32()
    active = hwnd_value(user32.GetForegroundWindow())
    ordered = sorted(windows, key=lambda hwnd: hwnd != active)
    for hwnd in ordered:
        if _usable_window(user32, hwnd, foreground_only=foreground_only):
            return hwnd
    return 0


def activate_app_window(name: str) -> int:
    """Restore/focus an app-owned HWND and return it only after verification."""
    query = normalized_name(name)
    if sys.platform != "win32":
        return 0
    if query == "discord":
        from luxai.discord_window_state import activate_running_discord
        try:
            return activate_running_discord()
        except (OSError, ValueError, RuntimeError):
            return 0
    windows = _app_windows(query)
    if not windows:
        return 0
    user32 = get_user32()
    active = hwnd_value(user32.GetForegroundWindow())
    for hwnd in sorted(windows, key=lambda value: value != active):
        if not user32.IsWindow(hwnd):
            continue
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE; preserve maximized windows
        user32.SetForegroundWindow(hwnd)
        if _usable_window(user32, hwnd, foreground_only=True):
            return hwnd
    return 0


def _wait_for_app_window(name: str) -> int:
    import time
    for _ in range(9):
        hwnd = activate_app_window(name)
        if hwnd:
            return hwnd
        time.sleep(0.14)
    return 0


def launch_installed_app(name: str, confirmed=None) -> tuple[bool, str]:
    """Locate, request Windows launch, then verify an actual usable window.

    A successful subprocess.Popen is NOT proof that an application opened.
    Return success only for a visible foreground window owned by that app.
    """
    query = normalized_name(name)
    if query == "discord" and sys.platform == "win32":
        # Discord may run only in the tray. Never report "opened" merely
        # because its process exists or Windows accepted the URI request.
        from luxai.discord_window_state import launch_or_activate_discord
        return launch_or_activate_discord(confirmed=confirmed)
    path = resolve_installed_app(query)
    if path is None:
        known_protocols = {
            "telegram": "tg://resolve",
            "discord": "discord://",
            "spotify": "spotify:",
            "steam": "steam://open/main",
            "settings": "ms-settings:",
        }
        if sys.platform == "win32" and query in known_protocols:
            if confirmed is not None and not confirmed(
                f"Запустить «{name}» через зарегистрированный протокол Windows?"
            ):
                return False, "Действие отменено."
            try:
                os.startfile(known_protocols[query])
                hwnd = _wait_for_app_window(query)
            except (OSError, AttributeError, ValueError, ctypes.ArgumentError) as exc:
                return False, f"Не удалось запустить «{name}»: {exc}"
            if hwnd:
                return True, f"Проверено: окно «{name}» открыто, видно и активно."
            return False, (
                f"Запрос запуска «{name}» передан Windows, но видимое "
                "активное окно не найдено. Приложение может работать в фоне."
            )
        return False, f"Не нашёл установленную программу «{name}»."

    if confirmed is not None and not confirmed(f"Запустить «{name}»?\n{path}"):
        return False, "Действие отменено."
    if sys.platform != "win32":
        return False, "Запуск программ поддерживается только на Windows."
    try:
        if path.suffix.lower() == ".lnk":
            os.startfile(str(path))
        else:
            subprocess.Popen(
                [str(path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                close_fds=True,
            )
        if _wait_for_app_window(query):
            return True, f"Проверено: окно «{name}» открыто, видно и активно."
        # A background process/accepted launch request cannot prove a usable GUI.
        return False, (
            f"Запрос на запуск «{name}» отправлен, "
            "но видимое активное окно не найдено. Приложение может работать в фоне."
        )
    except (OSError, ValueError, ctypes.ArgumentError) as error:
        return False, f"Windows не удалось запустить «{name}»: {error}"
