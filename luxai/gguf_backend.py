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
import threading

from luxai.local_ai_health import begin_inference, finish_inference, has_generated_text

ROOT = Path(__file__).resolve().parents[1]
SENTINEL = "LUXAI_RESPONSE_JSON:"
TIMEOUT_SECONDS = 150
EXTENDED_TIMEOUT_SECONDS = 300
INFERENCE_LOCK_TIMEOUT_SECONDS = 2
_INFERENCE_LOCK = threading.Lock()
DEFAULT_CONTEXT_TOKENS = 1536
DEFAULT_OUTPUT_LIMIT = 400
MAX_CONTEXT_TOKENS = 8192
MAX_OUTPUT_TOKENS = 4096


def inference_budget(n_ctx=None, max_tokens=160):
    """Keep normal replies small; larger budgets require an explicit request."""
    if n_ctx is None:
        return DEFAULT_CONTEXT_TOKENS, min(DEFAULT_OUTPUT_LIMIT, max(1, int(max_tokens)))
    context = min(MAX_CONTEXT_TOKENS, max(DEFAULT_CONTEXT_TOKENS, int(n_ctx)))
    # Even an explicit small context must retain room for the input prompt.
    limit = DEFAULT_OUTPUT_LIMIT if context == DEFAULT_CONTEXT_TOKENS else min(MAX_OUTPUT_TOKENS, context // 2)
    return context, min(limit, max(1, int(max_tokens)))


class GGUFWorkerError(RuntimeError):
    def __init__(self, message, *, code=""):
        super().__init__(message)
        self.code = code


class IsolatedGGUF:
    def __init__(self, model_path: str):
        self.model_path = str(Path(model_path).resolve())

    def _request(self, messages=None, prompt=None, max_tokens=160, temperature=0.2, n_ctx=None):
        context, output = inference_budget(n_ctx, max_tokens)
        request = {"model": self.model_path, "messages": messages,
                   "prompt": prompt, "max_tokens": output,
                   "temperature": min(1.0, max(0.0, float(temperature)))}
        if n_ctx is not None:
            request["n_ctx"] = context
        if not _INFERENCE_LOCK.acquire(timeout=INFERENCE_LOCK_TIMEOUT_SECONDS):
            raise GGUFWorkerError("The local model is busy. Wait for the current request and try again.", code="busy")
        token = None
        succeeded = False
        failure_code = "failed"
        try:
            token = begin_inference(self.model_path)
            # Explicit UTF-8 on BOTH pipe ends. Windows cp1251/cp1252 default
            # codecs cannot encode Romanian ș/ț or arbitrary GGUF prompts.
            environment = os.environ.copy()
            environment["PYTHONIOENCODING"] = "utf-8"
            completed = subprocess.run(
                [sys.executable, "-m", "luxai.gguf_worker"],
                input=json.dumps(request, ensure_ascii=False),
                text=True, encoding="utf-8", errors="replace",
                env=environment, cwd=ROOT, capture_output=True,
                timeout=EXTENDED_TIMEOUT_SECONDS if n_ctx is not None else TIMEOUT_SECONDS, check=False,
            )
            if completed.returncode != 0:
                failure_code = "worker_failed"
                raise GGUFWorkerError(
                    "Local GGUF process failed or was stopped. Check model compatibility, "
                    "available RAM and logs/local_ai_install.log. The engine is prepared "
                    "automatically at startup/update. Jarvis remains running."
                )
            failure_code = "invalid_reply"
            for line in reversed(completed.stdout.splitlines()):
                if line.startswith(SENTINEL):
                    try:
                        result = json.loads(line[len(SENTINEL):])
                    except (ValueError, TypeError) as error:
                        raise GGUFWorkerError("Invalid reply from local GGUF worker") from error
                    if not isinstance(result, dict):
                        raise GGUFWorkerError("Invalid GGUF worker response")
                    succeeded = has_generated_text(result)
                    if not succeeded:
                        failure_code = "empty_reply"
                    return result
            raise GGUFWorkerError("No response from local GGUF worker")
        except subprocess.TimeoutExpired as error:
            failure_code = "timeout"
            raise GGUFWorkerError("Local GGUF model timed out; try a smaller model or more RAM.") from error
        except (OSError, UnicodeError) as error:
            raise GGUFWorkerError("Could not start the isolated GGUF process.") from error
        finally:
            if token is not None:
                finish_inference(token, succeeded, failure_code)
            _INFERENCE_LOCK.release()

    def create_chat_completion(self, *, messages, max_tokens=96, temperature=0.2, n_ctx=None, **kwargs):
        return self._request(messages=messages, max_tokens=max_tokens, temperature=temperature, n_ctx=n_ctx)

    def __call__(self, prompt, max_tokens=96, temperature=0.2, n_ctx=None, **kwargs):
        return self._request(prompt=prompt, max_tokens=max_tokens, temperature=temperature, n_ctx=n_ctx)
