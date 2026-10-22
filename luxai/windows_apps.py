"""Resolve installed Windows apps by name rather than by AI-supplied commands.

Lookup uses App Paths, Start Menu shortcuts, common install locations and PATH.
No name is ever interpolated into CMD/PowerShell. App search is local and only
launches an executable/shortcut discovered on the current user's machine.
"""
from __future__ import annotations

import glob
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

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
    "калькулятор": "calculator",
    "проводник": "explorer",
    "стим": "steam",
    "спотифай": "spotify",
    "эдж": "edge",
}
EXEC_NAMES = {
    "firefox": ("firefox.exe",),
    "chrome": ("chrome.exe",),
    "edge": ("msedge.exe",),
    "telegram": ("Telegram.exe",),
    "discord": ("Discord.exe",),
    "spotify": ("Spotify.exe",),
    "steam": ("Steam.exe",),
    "notepad": ("notepad.exe",),
    "calculator": ("calc.exe",),
    "explorer": ("explorer.exe",),
}
# Resolve common apps even if they haven't registered App Paths.
COMMON_DIRS = {
    "firefox": ("Mozilla Firefox/firefox.exe",),
    "chrome": ("Google/Chrome/Application/chrome.exe",),
    "edge": ("Microsoft/Edge/Application/msedge.exe",),
    "telegram": ("Telegram Desktop/Telegram.exe",),
    "steam": ("Steam/steam.exe",),
    "spotify": ("Spotify/Spotify.exe",),
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
    return ALIASES.get(value, value)


def _match_name(query: str, candidate: str) -> bool:
    candidate = candidate.casefold()
    # Exact or app-name with normal vendor suffix; no fuzzy substring "cmd".
    stem = Path(candidate).stem if candidate.endswith(".exe") or candidate.endswith(".lnk") else candidate
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


def launch_installed_app(name: str, confirmed=None) -> tuple[bool, str]:
    """Return (dispatched_to_Windows, human description).

    A dispatched launch cannot prove that app became visible. The assistant
    must never say "opened" until the OS process/window is observed.
    """
    query = normalized_name(name)
    path = resolve_installed_app(query)
    if path is None:
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
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, shell=False, close_fds=True,
            )
        return True, f"Передал Windows запрос на запуск «{name}»."
    except (OSError, ValueError) as error:
        return False, f"Windows не удалось запустить «{name}»: {error}"
