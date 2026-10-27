"""Run a potentially unstable native llama.cpp model in an isolated process.

Each inference uses a short-lived worker, keeping crashes or large allocations
away from Jarvis's Qt UI/microphone process. A model will take longer to load.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SENTINEL = "LUXAI_RESPONSE_JSON:"
TIMEOUT_SECONDS = 150


class GGUFWorkerError(RuntimeError):
    pass


class IsolatedGGUF:
    def __init__(self, model_path: str):
        self.model_path = str(Path(model_path).resolve())

    def _request(self, messages=None, prompt=None, max_tokens=160, temperature=0.2):
        request = {"model": self.model_path, "messages": messages,
                   "prompt": prompt, "max_tokens": min(400, max(1, int(max_tokens))),
                   "temperature": min(1.0, max(0.0, float(temperature)))}
        try:
            # Explicit UTF-8 on BOTH pipe ends. Windows cp1251/cp1252 default
            # codecs cannot encode Romanian ș/ț or arbitrary GGUF prompts.
            environment = os.environ.copy()
            environment["PYTHONIOENCODING"] = "utf-8"
            completed = subprocess.run(
                [sys.executable, "-m", "luxai.gguf_worker"],
                input=json.dumps(request, ensure_ascii=False),
                text=True, encoding="utf-8", errors="replace",
                env=environment, cwd=ROOT, capture_output=True,
                timeout=TIMEOUT_SECONDS, check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise GGUFWorkerError("Local GGUF model timed out; try a smaller model or more RAM.") from error
        except (OSError, UnicodeError) as error:
            raise GGUFWorkerError("Could not start the isolated GGUF process.") from error
        if completed.returncode != 0:
            raise GGUFWorkerError(
                "Local GGUF process failed or was stopped. Check model compatibility, "
                "available RAM and logs/local_ai_install.log. The engine is prepared "
                "automatically at startup/update. Jarvis remains running."
            )
        for line in reversed(completed.stdout.splitlines()):
            if line.startswith(SENTINEL):
                try:
                    result = json.loads(line[len(SENTINEL):])
                except (ValueError, TypeError) as error:
                    raise GGUFWorkerError("Invalid reply from local GGUF worker") from error
                if not isinstance(result, dict):
                    raise GGUFWorkerError("Invalid GGUF worker response")
                return result
        raise GGUFWorkerError("No response from local GGUF worker")

    def create_chat_completion(self, *, messages, max_tokens=96, temperature=0.2, **kwargs):
        return self._request(messages=messages, max_tokens=max_tokens, temperature=temperature)

    def __call__(self, prompt, max_tokens=96, temperature=0.2, **kwargs):
        return self._request(prompt=prompt, max_tokens=max_tokens, temperature=temperature)
