"""Single-request isolated llama.cpp process; never imported by the GUI.

Reads one JSON request from stdin, writes exactly one structured result marker.
"""
from __future__ import annotations

import json
import os
import sys


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read(100_000))
        model_path = payload["model"]
        if not isinstance(model_path, str) or not model_path.lower().endswith(".gguf"):
            raise ValueError("Invalid GGUF model path")
        from llama_cpp import Llama
        llm = Llama(
            model_path=model_path,
            n_ctx=1536, n_batch=64,
            n_threads=max(2, min(4, os.cpu_count() or 4)),
            n_gpu_layers=0,
            use_mmap=True,
            verbose=False,
        )
        max_tokens = min(400, max(1, int(payload.get("max_tokens", 96))))
        temperature = min(1.0, max(0.0, float(payload.get("temperature", 0.2))))
        if isinstance(payload.get("messages"), list):
            result = llm.create_chat_completion(
                messages=payload["messages"], max_tokens=max_tokens,
                temperature=temperature,
            )
        else:
            result = llm(str(payload.get("prompt") or "")[:10_000],
                         max_tokens=max_tokens, temperature=temperature)
        print("LUXAI_RESPONSE_JSON:" + json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        # Only the exception type is printed, not private prompts or model paths.
        print(f"GGUF worker error: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
