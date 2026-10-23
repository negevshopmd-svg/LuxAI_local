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

def main() -> int:
    try:
        os.chdir(ROOT)
        enable_native_crash_log()
        import main as application
        return int(application.main() or 0)
    except Exception as exc:
        _log_startup_error(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
