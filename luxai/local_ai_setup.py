"""Install and verify the optional llama.cpp GGUF backend in LuxAI's own venv.

Safe for an automatic Windows installer/update: only official precompiled
CPU wheels are accepted, never an unexpected C++ source build.
"""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LOG_FILE = ROOT / "logs" / "local_ai_install.log"
OFFICIAL_CPU_WHEELS = "https://abetlen.github.io/llama-cpp-python/whl/cpu"
BACKEND_IMPORT = "from llama_cpp import Llama; print('LuxAI local GGUF backend OK')"
INSTALL_TIMEOUT = 420


def check_backend(python: str | Path = sys.executable) -> bool:
    """Test import in a child process; incompatible native DLLs must not crash Qt."""
    try:
        probe = subprocess.run(
            [str(python), "-c", BACKEND_IMPORT],
            cwd=str(ROOT), capture_output=True, text=True,
            errors="replace", timeout=35, check=False,
        )
        return probe.returncode == 0 and "LuxAI local GGUF backend OK" in probe.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


def _append_log(message: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as output:
        output.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")


def install_backend(python: str | Path = sys.executable) -> bool:
    """Install only wheel files; verify the real import, not just pip exit status."""
    executable = str(python)
    if check_backend(executable):
        _append_log(f"Already installed in {executable}.")
        print("LuxAI local AI: llama-cpp-python already available.", flush=True)
        return True

    _append_log(f"Installing official CPU wheel for {executable}.")
    print("LuxAI local AI: installing official Windows CPU wheel...", flush=True)
    command = [
        executable, "-m", "pip", "install",
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
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _append_log(f"Installation stopped: {type(exc).__name__}.")
        print("LuxAI local AI: installation could not complete. Check logs/local_ai_install.log.")
        return False

    if result.returncode == 0 and check_backend(executable):
        _append_log("SUCCESS: llama-cpp-python import verified.")
        print("LuxAI local AI: installed and verified successfully.", flush=True)
        return True
    _append_log(f"FAILED: pip code={result.returncode}, import check unsuccessful.")
    print(
        "LuxAI local AI: no working compatible prebuilt wheel. "
        "See logs/local_ai_install.log. Normal Jarvis commands still work.",
        flush=True,
    )
    return False


def main() -> int:
    return 0 if install_backend() else 1


if __name__ == "__main__":
    raise SystemExit(main())
