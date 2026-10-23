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
    """Find and install the newest compatible official CPU wheel.

    Existing working backends survive a temporary failure to query the package
    index. Never attempt a native C++ build or mark broken DLLs as working.
    """
    executable = str(python)
    previously_working = check_backend(executable)
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
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _append_log(f"Version check/install failed: {type(exc).__name__}.")
        if previously_working and check_backend(executable):
            print("LuxAI local AI: current backend works, but its latest version could not be checked.")
            return True
        print("LuxAI local AI: installation could not complete. Check logs/local_ai_install.log.")
        return False

    verified = check_backend(executable)
    if result.returncode == 0 and verified:
        _append_log("SUCCESS: newest compatible backend installed and import verified.")
        print("LuxAI local AI: newest compatible CPU wheel checked and import verified.", flush=True)
        return True
    if previously_working and verified:
        _append_log(f"WARNING: update failed (code={result.returncode}), existing backend works.")
        print("LuxAI local AI: update unavailable; existing verified backend remains usable.")
        return True
    _append_log(f"FAILED: pip code={result.returncode}, native import did not pass.")
    print("LuxAI local AI: no working compatible prebuilt wheel. See logs/local_ai_install.log.")
    return False


def main() -> int:
    return 0 if install_backend() else 1


if __name__ == "__main__":
    raise SystemExit(main())
