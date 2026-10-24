"""Verified local tool hints for repeat commands without storing voice text."""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path

SAFE_MODES = frozenset({"screen_capture", "open_recycle_bin", "safe_diagnostic"})
MAX_ENTRIES = 96


def _store() -> Path:
    return Path.home() / ".luxai_data" / "tool_history.json"


def _fingerprint(text: str) -> str:
    from luxai.fast_intents import strip_wake_name
    cleaned = re.sub(r"\s+", " ", strip_wake_name(str(text)).casefold()).strip(" ,.?!")
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()


def recall(text: str):
    try:
        data = json.loads(_store().read_text(encoding="utf-8"))
        stored = data.get(_fingerprint(text), {})
        if stored.get("mode") not in SAFE_MODES:
            return None
        from luxai.adaptive_tasks import _validate_choice
        return _validate_choice(stored, text)
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def remember(text: str, choice) -> None:
    if choice.mode not in SAFE_MODES:
        return
    path = _store()
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(data, dict):
            data = {}
        data[_fingerprint(text)] = {"mode": choice.mode, "target": choice.target}
        while len(data) > MAX_ENTRIES:
            data.pop(next(iter(data)))
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data), encoding="utf-8")
        temp.replace(path)
    except (OSError, ValueError, TypeError):
        pass
