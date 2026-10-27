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
from luxai.win32 import WNDENUMPROC, get_user32, hwnd_value

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


def process_names_for_app(name: str, *, for_discovery=False) -> set[str]:
    query = normalized_name(name)
    names = KNOWN_PROCESSES.get(query, ())
    if not names:
        from luxai.windows_apps import resolve_installed_app
        discovered = resolve_installed_app(query)
        if discovered is not None and discovered.suffix.casefold() == ".exe":
            names = (discovered.name.casefold(),)
    return set(names) if for_discovery else set(names) - NEVER_CLOSE


def running_pids(name: str, *, for_discovery=False, require_complete=False) -> set[int]:
    names = process_names_for_app(name, for_discovery=for_discovery)
    if not names:
        return set()
    try:
        import psutil
    except ImportError as exc:
        if require_complete:
            raise OSError("Process inspection is unavailable") from exc
        return set()
    found: set[int] = set()
    complete = True
    try:
        for process in psutil.process_iter(["pid", "name"]):
            try:
                pid = int(process.pid)
                # These identities cannot be a user game. Some Windows
                # versions deny names for the kernel and idle processes.
                if pid in {0, 4, os.getpid()}:
                    continue
                executable = process.info.get("name")
                if not isinstance(executable, str) or not executable:
                    complete = False
                    continue
                if executable.casefold() in names:
                    found.add(pid)
            except getattr(psutil, "NoSuchProcess", ()):
                # A process that exited during the snapshot is not running.
                continue
            except (psutil.Error, ValueError, TypeError):
                complete = False
    except (psutil.Error, ValueError, TypeError):
        complete = False
    if require_complete and not complete:
        raise OSError("The running-process snapshot is incomplete")
    return found


def _visible_app_windows(pids: set[int]) -> list[int]:
    if sys.platform != "win32" or not pids:
        return []
    from ctypes import wintypes

    user32 = get_user32()
    windows: list[int] = []

    @WNDENUMPROC
    def collect(hwnd, _):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in pids:
                windows.append(hwnd_value(hwnd))
        return True

    user32.EnumWindows(collect, 0)
    return windows


def _close_windows(query: str, pids: set[int]) -> list[int]:
    windows = _visible_app_windows(pids)
    if query != "warthunder" or not windows:
        return windows
    # aces.exe is War Thunder's game client, not Steam or its launcher. The
    # actual game window title must corroborate that executable identity.
    user32 = get_user32()
    verified = []
    for hwnd in windows:
        length = user32.GetWindowTextLengthW(hwnd)
        if not 0 < length < 4096:
            continue
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        if re.search(r"(?<!\w)(?:war\s*-?\s*thunder|вар\s*тандер)(?!\w)", title.value, re.I):
            verified.append(hwnd)
    return verified


def _window_still_owned(user32, hwnd: int, pids: set[int]) -> bool:
    from ctypes import wintypes
    if not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd):
        return False
    owner = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
    return owner.value in pids


def close_installed_app(name: str, confirmed=None, *, language="ru") -> tuple[bool, str]:
    """Ask user, WM_CLOSE visible windows, verify they disappeared.

    bool is True ONLY when no relevant visible windows remain; if the app
    opens an unsaved-document confirmation the result is reported as pending.
    """
    def say(ru, ro, en):
        return ro if language == "ro" else en if language == "en" else ru

    query = normalized_name(name)
    from luxai.steam_games import GAMES
    display = GAMES[query][1] if query in GAMES else name
    if sys.platform != "win32":
        return False, say("Закрытие программ поддерживается только на Windows.",
                          "Închiderea aplicațiilor este disponibilă doar pe Windows.",
                          "Closing applications is supported only on Windows.")
    names = process_names_for_app(query)
    if not names:
        return False, say(f"Не могу безопасно определить процесс приложения «{display}».",
                          f"Nu pot identifica sigur procesul aplicației «{display}».",
                          f"Could not safely identify the process for «{display}».")
    try:
        import psutil  # noqa: F401
    except ImportError:
        return False, say("Не удалось проверить запущенные процессы.",
                          "Nu am putut verifica procesele active.",
                          "Could not inspect running processes.")
    inspection_failure = (False, say(
        "Не удалось полностью проверить запущенные процессы; закрытие не подтверждено.",
        "Nu am putut verifica toate procesele active; închiderea nu este confirmată.",
        "Could not fully inspect running processes; closure is not confirmed."))

    def inspect_pids(*, require_complete=True):
        # Discovery can use a partial list. A game-close verification must
        # distinguish an empty list from a failed/inaccessible inspection.
        return (running_pids(query, require_complete=require_complete)
                if query in GAMES else running_pids(query))

    try:
        pids = inspect_pids(require_complete=False)
        if not pids and query in GAMES:
            # An inaccessible unrelated Windows service must not stop a
            # positively identified game window from receiving WM_CLOSE.
            # Absence, however, requires a complete snapshot.
            pids = inspect_pids()
    except OSError:
        return inspection_failure
    if not pids:
        return query in GAMES, say(f"Приложение «{display}» сейчас не запущено; закрывать нечего.",
                                    f"«{display}» nu rulează; nu este nimic de închis.",
                                    f"«{display}» is not running; there is nothing to close.")
    windows = _close_windows(query, pids)
    if not windows:
        return False, say(
            f"Процесс «{display}» найден, но его окно не подтверждено. Принудительное завершение отключено.",
            f"Procesul «{display}» există, dar fereastra nu a fost confirmată. Nu forțez închiderea.",
            f"The «{display}» process exists, but its window was not verified. Force termination is disabled.")
    question = say(
        f"Закрыть «{display}»? Открытых окон: {len(windows)}.\nНесохранённые документы могут вызвать запрос на сохранение.",
        f"Închid «{display}»? Ferestre deschise: {len(windows)}.\nAplicația poate cere salvarea modificărilor.",
        f"Close «{display}»? Open windows: {len(windows)}.\nThe application may ask to save unsaved changes.")
    if confirmed is not None and not confirmed(question):
        return False, say("Действие отменено.", "Acțiune anulată.", "Action cancelled.")

    user32 = get_user32()
    sent = 0
    # A confirmation dialog can leave a long interval before execution. Never
    # trust a stale/reused HWND or close a window that now belongs to Steam.
    try:
        current_pids = inspect_pids(require_complete=False)
    except OSError:
        return inspection_failure
    current_windows = set(_close_windows(query, current_pids))
    for hwnd in windows:
        if (hwnd in current_windows and _window_still_owned(user32, hwnd, current_pids)
                and user32.PostMessageW(hwnd, 0x0010, 0, 0)):  # WM_CLOSE
            sent += 1
    if not sent:
        return False, say(f"Окно «{display}» изменилось или Windows отказался его закрыть.",
                          f"Fereastra «{display}» s-a schimbat sau Windows a refuzat închiderea.",
                          f"The «{display}» window changed or Windows refused to close it.")
    # Wait briefly for a normal close; never force-terminate applications.
    for _ in range(15 if query in GAMES else 6):
        time.sleep(0.20)
        try:
            remaining_pids = inspect_pids()
        except OSError:
            return inspection_failure
        remaining = _close_windows(query, remaining_pids)
        if not remaining and (query not in GAMES or not remaining_pids):
            return True, say(f"Проверено: «{display}» закрыто.",
                             f"Verificat: «{display}» a fost închis.",
                             f"Verified: «{display}» is closed.")
    return False, say(
        f"Запрос закрытия отправлен «{display}», но завершение ещё не подтверждено. Проверьте окно приложения.",
        f"Am trimis cererea de închidere pentru «{display}», dar închiderea nu este încă confirmată. Verifică aplicația.",
        f"Sent «{display}» a close request, but shutdown is not yet confirmed. Check the application.")
