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
    "vscode": ("Code.exe",),
    "visual studio": ("devenv.exe",),
    "pycharm": ("pycharm64.exe", "pycharm.exe"),
    "blender": ("blender.exe",),
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


def launch_installed_app(name: str, confirmed=None) -> tuple[bool, str]:
    """Locate, request Windows launch, then verify process presence.

    A successful subprocess.Popen is NOT proof that an application opened.
    Return verified success only after a known executable's process appears.
    """
    import time
    query = normalized_name(name)
    path = resolve_installed_app(query)
    if path is None:
        known_protocols = {
            "telegram": "tg://resolve",
            "discord": "discord://",
            "spotify": "spotify:",
            "steam": "steam://open/main",
        }
        if sys.platform == "win32" and query in known_protocols:
            if confirmed is not None and not confirmed(
                f"Запустить «{name}» через зарегистрированный протокол Windows?"
            ):
                return False, "Действие отменено."
            try:
                os.startfile(known_protocols[query])
            except (OSError, AttributeError) as exc:
                return False, f"Не удалось запустить «{name}»: {exc}"
            return True, f"Отправил запрос запуска «{name}» через Windows. Проверьте окно приложения."
        return False, f"Не нашёл установленную программу «{name}»."

    if confirmed is not None and not confirmed(f"Запустить «{name}»?\n{path}"):
        return False, "Действие отменено."
    if sys.platform != "win32":
        return False, "Запуск программ поддерживается только на Windows."
    try:
        from luxai.windows_control import running_pids
        was_running = bool(running_pids(query))
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
        for _ in range(9):
            if running_pids(query):
                return True, (
                    f"Проверено: процесс «{name}» запущен."
                    if not was_running else
                    f"«{name}» уже запущен. Запрос на открытие передан Windows."
                )
            time.sleep(0.14)
        # Do not suggest it opened when process observation has not succeeded.
        return False, (
            f"Запрос на запуск «{name}» отправлен, "
            "но появление процесса пока не подтверждено."
        )
    except (OSError, ValueError) as error:
        return False, f"Windows не удалось запустить «{name}»: {error}"
