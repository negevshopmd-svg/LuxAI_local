"""Start LuxAI with a visible Windows error if initialization fails.

pythonw.exe does not have a console, so unhandled startup tracebacks would
otherwise be invisible when the program is shared with another computer.
This bootstrapper uses only Python standard-library modules.
"""
from __future__ import annotations

import ctypes
import datetime
import os
from pathlib import Path
import sys
import traceback
import faulthandler

ROOT = Path(__file__).resolve().parent
STARTUP_LOG = ROOT / "logs" / "startup_error.log"
NATIVE_LOG = ROOT / "logs" / "fatal_error.log"
_native_log_handle = None


def enable_native_crash_log():
    """Record native stack traces for access violations when Python survives long enough."""
    global _native_log_handle
    try:
        NATIVE_LOG.parent.mkdir(parents=True, exist_ok=True)
        _native_log_handle = NATIVE_LOG.open("a", encoding="utf-8")
        faulthandler.enable(file=_native_log_handle, all_threads=True)
    except (OSError, RuntimeError, ValueError):
        pass



def _log_startup_error(exc: BaseException) -> None:
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        STARTUP_LOG.parent.mkdir(parents=True, exist_ok=True)
        with STARTUP_LOG.open("a", encoding="utf-8") as output:
            output.write(f"\n=== LuxAI startup error {datetime.datetime.now().isoformat(timespec='seconds')} ===\n")
            output.write(f"Python: {sys.version}\n")
            output.write(f"Executable: {sys.executable}\n")
            output.write(f"Directory: {ROOT}\n")
            output.write(detail + "\n")
    except OSError:
        pass

    _show_failure_dialog(detail)


def _show_failure_dialog(detail: str) -> None:
    message = (
        "LuxAI nu a putut porni.\n\n"
        "Deschide fisierul:\n"
        f"{STARTUP_LOG}\n\n"
        "Trimite mesajul de eroare pentru diagnostic."
    )
    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(None, message, "LuxAI - Eroare la pornire", 0x10)
            return
        except (AttributeError, OSError):
            pass
    if sys.stderr is not None:
        print(message, file=sys.stderr)
        print(detail, file=sys.stderr)

_instance_mutex = None
_MESSAGES = {
    "running": ("Jarvis уже запущен (значок в трее).", "Jarvis rulează deja (pictograma din bara de sistem).",
                "Jarvis is already running (tray icon)."),
    "pending": ("Последнее обновление было прервано, часть файлов может быть от разных версий.\n"
                "Лучше запустить Update.bat — он установит всё заново.\n\nВсё равно запустить Jarvis?",
                "Ultima actualizare a fost întreruptă; unele fișiere pot fi din versiuni diferite.\n"
                "Cel mai bine rulează Update.bat — reinstalează totul.\n\nPornești totuși Jarvis?",
                "The last update was interrupted; some files may come from different versions.\n"
                "Best run Update.bat — it installs everything again.\n\nStart Jarvis anyway?"),
    "updating": ("Сейчас идёт обновление Jarvis. Дождитесь его окончания и запустите снова.",
                 "Jarvis se actualizează chiar acum. Așteaptă să termine, apoi pornește-l din nou.",
                 "Jarvis is being updated right now. Wait until it finishes, then start it again."),
    "unfinished": ("Не удалось завершить прерванное обновление, Jarvis не запущен.\n"
                   "Запустите Update.bat — он установит всё заново.",
                   "Actualizarea întreruptă nu a putut fi terminată; Jarvis nu a pornit.\n"
                   "Rulează Update.bat — reinstalează totul.",
                   "The interrupted update could not be finished; Jarvis was not started.\n"
                   "Run Update.bat — it installs everything again."),
}


def _language_index() -> int:
    try:
        import json
        language = json.loads((ROOT / "config.json").read_text(encoding="utf-8")).get("ui_language", "ru")
    except Exception:
        language = "ru"
    if not isinstance(language, str):
        language = "ru"  # a damaged config (e.g. a list) never stops the message (audit 2 #21)
    return {"ru": 0, "ro": 1, "en": 2}.get(language, 0)


def _message(key: str, icon: int = 0x40) -> int:
    """Show a message box; returns the button pressed (6 = Yes) or 0 without a window."""
    text = _MESSAGES[key][_language_index()]
    if os.name == "nt":
        try:
            return int(ctypes.windll.user32.MessageBoxW(None, text, "Jarvis", icon))
        except (AttributeError, OSError):
            pass
    if sys.stderr is not None:
        print(text, file=sys.stderr)
    return 0


def update_running() -> bool:
    """Is Update.py holding its lock right now? (the same OS lock, released even after a crash)"""
    lock_path = ROOT / ".luxai_data" / "updater.lock"
    if not lock_path.is_file():
        return False
    try:
        with lock_path.open("r+b") as handle:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    return True
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    return True
                fcntl.flock(handle, fcntl.LOCK_UN)
    except OSError:
        return False
    return False


def finish_interrupted_update() -> str:
    """«ok», «updating» or «unfinished». The moves run in Update.py --resume under the updater lock
    (audit 2 #1), so they never race a running update; a failure blocks the start."""
    if not (ROOT / ".luxai_update_journal.json").exists():
        return "ok"
    import subprocess
    python = Path(sys.executable)
    console = python.with_name("python.exe")
    try:
        result = subprocess.run([str(console if console.is_file() else python), str(ROOT / "Update.py"), "--resume"],
                                cwd=str(ROOT), timeout=180, check=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return "unfinished"
    if result.returncode == 2:
        return "updating"
    if result.returncode != 0 or (ROOT / ".luxai_update_journal.json").exists():
        return "unfinished"
    return "ok"


def single_instance(wait: float = 10.0) -> bool:
    """One Jarvis per installation folder: two copies overwrote each other's settings and
    commands (audit #12). The running copy OWNS a named mutex; Windows releases it even after a
    crash. A new copy waits a little: when Jarvis restarts itself (e.g. as administrator) the old
    copy is still closing for a moment."""
    global _instance_mutex
    if os.name != "nt":
        return True
    import hashlib
    import time
    name = "Local\\LuxAI-Jarvis-" + hashlib.sha1(str(ROOT).casefold().encode("utf-8")).hexdigest()[:16]
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    deadline = time.monotonic() + wait
    while True:
        handle = kernel.CreateMutexW(None, True, name)
        error = kernel.GetLastError()
        if handle and error != 183:
            _instance_mutex = handle  # created and owned
            return True
        if handle:
            # Exists: wait until its owner exits (0 = released, 0x80 = owner ended without releasing).
            left = max(0, int((deadline - time.monotonic()) * 1000))
            if kernel.WaitForSingleObject(handle, left) in (0, 0x80):
                _instance_mutex = handle
                return True
            kernel.CloseHandle(handle)
            return False
        # Access denied: an elevated copy holds it; ask again until it is gone or the time is up.
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.3)


def main() -> int:
    try:
        os.chdir(ROOT)
        if not single_instance():
            _message("running")
            return 0
        if update_running():
            _message("updating", 0x30)  # files are being replaced right now (audit 2 #1)
            return 0
        state = finish_interrupted_update()
        if state != "ok":
            _message(state, 0x30 if state == "updating" else 0x10)
            return 0 if state == "updating" else 1
        if (ROOT / ".luxai_update_pending.json").exists():
            # Interrupted update (audit #29): ask; «No» (the default) keeps Jarvis closed.
            if _message("pending", 0x30 | 0x4 | 0x100) != 6:
                return 1
        enable_native_crash_log()
        # The wheel is installed by setup/update. Recover interrupted/offline
        # installations silently; never hold Qt startup on a native import or pip.
        from luxai.local_ai_setup import start_background_setup
        start_background_setup()
        import main as application
        return int(application.main() or 0)
    except Exception as exc:
        _log_startup_error(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
