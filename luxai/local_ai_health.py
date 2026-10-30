"""Small, thread-safe observations of actual local inference; no UI or prompts.

Availability is deliberately separate: only a completed, nonempty model reply
can produce a successful observation. Records are scoped to exact file identity.
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import threading


_guard = threading.Lock()
_records = OrderedDict()
_sequence = 0
_LIMIT = 32


def model_identity(path):
    path = Path(path)
    try:
        stat = path.stat()
        return (str(path), stat.st_size, stat.st_mtime_ns,
                getattr(stat, "st_dev", 0), getattr(stat, "st_ino", 0))
    except OSError:
        return (str(path), None, None, None, None)


def begin_inference(path):
    """Called only after the inference lock is acquired, never for a busy retry."""
    global _sequence
    identity = model_identity(path)
    with _guard:
        _sequence += 1
        token = (identity, _sequence)
        _records[identity] = {"request": _sequence, "state": "working", "code": ""}
        _records.move_to_end(identity)
        while len(_records) > _LIMIT:
            _records.popitem(last=False)
        return token


def finish_inference(token, success, code="failed"):
    identity, sequence = token
    with _guard:
        record = _records.get(identity)
        if record is None or record["request"] != sequence:
            return False
        _records[identity] = {"request": sequence, "state": "success" if success else "error",
                              "code": "" if success else code if code in {
                                  "timeout", "failed", "empty_reply", "worker_failed", "invalid_reply",
                              } else "failed"}
        return True


def inference_status(identity):
    with _guard:
        record = _records.get(identity)
        return dict(record) if record else None


def has_generated_text(result):
    if not isinstance(result, dict) or not isinstance(result.get("choices"), list):
        return False
    for choice in result["choices"]:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        values = [choice.get("text")]
        if isinstance(message, dict):
            values.append(message.get("content"))
        if any(isinstance(value, str) and value.strip() for value in values):
            return True
    return False
