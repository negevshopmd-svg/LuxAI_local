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
                "Закройте Jarvis и запустите Update.bat — он установит всё заново.",
                "Ultima actualizare a fost întreruptă; unele fișiere pot fi din versiuni diferite.\n"
                "Închide Jarvis și rulează Update.bat — reinstalează totul.",
                "The last update was interrupted; some files may come from different versions.\n"
                "Close Jarvis and run Update.bat — it installs everything again."),
}


def _language_index() -> int:
    try:
        import json
        language = json.loads((ROOT / "config.json").read_text(encoding="utf-8")).get("ui_language", "ru")
    except Exception:
        language = "ru"
    return {"ru": 0, "ro": 1, "en": 2}.get(language, 0)


def _message(key: str, icon: int = 0x40) -> None:
    text = _MESSAGES[key][_language_index()]
    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(None, text, "Jarvis", icon)
            return
        except (AttributeError, OSError):
            pass
    if sys.stderr is not None:
        print(text, file=sys.stderr)


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
        if (ROOT / ".luxai_update_journal.json").exists():
            # An update stopped between two files (audit #29): finish its moves before any code loads.
            try:
                import subprocess
                subprocess.run([sys.executable.replace("pythonw.exe", "python.exe").replace("Jarvis.exe", "python.exe"),
                                str(ROOT / "Update.py"), "--resume"], cwd=str(ROOT), timeout=120,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
            except Exception:
                pass
        if (ROOT / ".luxai_update_pending.json").exists():
            _message("pending", 0x30)  # interrupted update (audit #29): say it, then start anyway
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
