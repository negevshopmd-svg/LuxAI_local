"""Install and verify the optional llama.cpp GGUF backend in LuxAI's own venv.

Safe for an automatic Windows installer/update: only official precompiled
CPU wheels are accepted, never an unexpected C++ source build.
"""
from __future__ import annotations

from datetime import datetime
from contextlib import contextmanager
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
LOG_FILE = ROOT / "logs" / "local_ai_install.log"
OFFICIAL_CPU_WHEELS = "https://abetlen.github.io/llama-cpp-python/whl/cpu"
BACKEND_IMPORT = "from llama_cpp import Llama; print('LuxAI local GGUF backend OK')"
INSTALL_TIMEOUT = 420
PROBE_TIMEOUT = 35
LOCK_MAX_AGE = INSTALL_TIMEOUT + PROBE_TIMEOUT * 2 + 120
STATUS_MAX_AGE = 24 * 60 * 60
_SETUP_GUARD = threading.Lock()
_BACKGROUND_GUARD = threading.Lock()
_BACKGROUND_REQUESTED = False


def runtime_python(python: str | Path = sys.executable) -> str:
    """Use console Python with hidden windows, including under pythonw.exe.

    Native-import probes need usable redirected stdout. A pythonw launcher
    can have no standard streams; its sibling belongs to the same environment.
    """
    executable = Path(python)
    if executable.name.casefold() == "pythonw.exe":
        console = executable.with_name("python.exe")
        if console.is_file():
            executable = console
    return str(executable)


def _quiet_process_options() -> dict:
    return ({"creationflags": subprocess.CREATE_NO_WINDOW}
            if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW") else {})


def _write_status(state: str) -> None:
    """Record progress for diagnostics without risking the main application."""
    filename = LOG_FILE.with_suffix(".status.json")
    temporary = filename.with_name(filename.name + f".{os.getpid()}.tmp")
    try:
        filename.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps({
            "state": state, "updated_at": time.time(),
            "environment": str(Path(sys.prefix).resolve()),
        }), encoding="utf-8")
        temporary.replace(filename)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def setup_status() -> str:
    """Return recent automatic setup progress, never an installation guarantee."""
    try:
        data = json.loads(LOG_FILE.with_suffix(".status.json").read_text(encoding="utf-8"))
        if data.get("environment") != str(Path(sys.prefix).resolve()):
            return ""
        state = data.get("state")
        age = time.time() - float(data["updated_at"])
        maximum = LOCK_MAX_AGE if state == "installing" else STATUS_MAX_AGE
        if 0 <= age <= maximum and state in {"installing", "ready", "unavailable"}:
            return state
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    return ""


@contextmanager
def _setup_lock():
    """Serialize threads locally and installers across OS processes."""
    if not _SETUP_GUARD.acquire(blocking=False):
        yield False
        return
    try:
        with _file_setup_lock() as acquired:
            yield acquired
    finally:
        _SETUP_GUARD.release()


@contextmanager
def _file_setup_lock():
    """Keep one installer across processes; the OS releases crashed helpers.

    The one-byte lockfile is deliberately retained. Deleting lockfiles on
    release or based on age can race a different process using the same path.
    """
    filename = LOG_FILE.with_suffix(".lock")
    handle = None
    acquired = False
    try:
        filename.parent.mkdir(parents=True, exist_ok=True)
        if filename.is_symlink():
            raise OSError("Setup lock cannot be a symbolic link")
        descriptor = os.open(filename, os.O_CREAT | os.O_RDWR, 0o600)
        handle = os.fdopen(descriptor, "r+b", buffering=0)
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"\0")
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
    except (ImportError, OSError):
        pass
    try:
        yield acquired
    finally:
        if handle is not None:
            try:
                if acquired:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            handle.close()


def check_backend(python: str | Path = sys.executable) -> bool:
    """Test import in a child process; incompatible native DLLs must not crash Qt."""
    try:
        probe = subprocess.run(
            [runtime_python(python), "-c", BACKEND_IMPORT],
            cwd=str(ROOT), capture_output=True, text=True,
            errors="replace", timeout=PROBE_TIMEOUT, check=False,
            **_quiet_process_options(),
        )
        return probe.returncode == 0 and "LuxAI local GGUF backend OK" in probe.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


def _append_log(message: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as output:
        output.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")


def install_backend(python: str | Path = sys.executable) -> bool:
    """Find and install the newest compatible official CPU wheel.

    Existing working backends survive a temporary failure to query the package
    index. Never attempt a native C++ build or mark broken DLLs as working.
    """
    with _setup_lock() as acquired:
        if not acquired:
            # Another bounded helper owns pip. Never launch a competing install.
            return False
        return _install_backend(runtime_python(python))


def _install_backend(executable: str, *, previously_working: bool | None = None) -> bool:
    if previously_working is None:
        previously_working = check_backend(executable)
    _write_status("installing")
    _append_log(f"Checking newest compatible llama-cpp-python for {executable}.")
    print("LuxAI local AI: checking latest compatible official CPU wheel...", flush=True)
    command = [
        executable, "-m", "pip", "install", "--upgrade",
        "--disable-pip-version-check", "--prefer-binary",
        "--only-binary=:all:", "--retries", "2", "--timeout", "35",
        "--extra-index-url", OFFICIAL_CPU_WHEELS,
        "llama-cpp-python>=0.3.20",
    ]
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as output:
            result = subprocess.run(
                command, cwd=str(ROOT), stdout=output, stderr=subprocess.STDOUT,
                timeout=INSTALL_TIMEOUT, check=False,
                **_quiet_process_options(),
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _append_log(f"Version check/install failed: {type(exc).__name__}.")
        if previously_working and check_backend(executable):
            _write_status("ready")
            print("LuxAI local AI: current backend works, but its latest version could not be checked.")
            return True
        _write_status("unavailable")
        print("LuxAI local AI: installation could not complete. Check logs/local_ai_install.log.")
        return False

    verified = check_backend(executable)
    if result.returncode == 0 and verified:
        _write_status("ready")
        _append_log("SUCCESS: newest compatible backend installed and import verified.")
        print("LuxAI local AI: newest compatible CPU wheel checked and import verified.", flush=True)
        return True
    if previously_working and verified:
        _write_status("ready")
        _append_log(f"WARNING: update failed (code={result.returncode}), existing backend works.")
        print("LuxAI local AI: update unavailable; existing verified backend remains usable.")
        return True
    _append_log(f"FAILED: pip code={result.returncode}, native import did not pass.")
    _write_status("unavailable")
    print("LuxAI local AI: no working compatible prebuilt wheel. See logs/local_ai_install.log.")
    return False


def ensure_backend(python: str | Path = sys.executable) -> bool:
    """Repair missing/broken engines on launch; working engines need no network."""
    with _setup_lock() as acquired:
        if not acquired:
            return False
        executable = runtime_python(python)
        if check_backend(executable):
            _write_status("ready")
            return True
        return _install_backend(executable, previously_working=False)


def start_background_setup() -> bool:
    """Start automatic maintenance without waiting or opening a terminal."""
    global _BACKGROUND_REQUESTED
    if sys.platform != "win32":
        return False
    # Both the diagnostic launcher and main.py can reach this entry point.
    # Schedule at most once per running process, allowing a failed spawn to
    # retry when the next entry point is reached.
    with _BACKGROUND_GUARD:
        if _BACKGROUND_REQUESTED:
            return True
        try:
            subprocess.Popen(
                [runtime_python(), "-m", "luxai.local_ai_setup", "--ensure"],
                cwd=str(ROOT), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                **_quiet_process_options(),
            )
        except OSError:
            return False
        _BACKGROUND_REQUESTED = True
        return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ensure", action="store_true",
                        help="repair only a missing/broken engine, without upgrading a working one")
    options = parser.parse_args(argv)
    return 0 if (ensure_backend() if options.ensure else install_backend()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
