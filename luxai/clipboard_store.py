"""Clipboard history: items, pins, limits, privacy rules and encrypted storage.

Pure logic without Qt so it can be tested on its own. The runtime feeds it
what the clipboard holds; it decides what to keep.

Privacy:
* programs mark passwords "not for history" with the standard Windows formats
  (ExcludeClipboardContentFromMonitorProcessing, CanIncludeInClipboardHistory=0,
  Clipboard Viewer Ignore) — such copies are never stored;
* copies made by a listed program (password managers) are never stored;
* Jarvis's own temporary clipboard use is muted with ``suppress()``;
* on disk the history is encrypted with Windows DPAPI for the current user.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
import threading
import time
from pathlib import Path

MAX_TEXT = 100_000
MAX_IMAGE_BYTES = 8 * 1024 * 1024
FILE_MAGIC = b"LUXCLIP1"

_suppress_until = 0.0
_lock = threading.Lock()


def suppress(seconds: float = 2.0) -> None:
    """Jarvis is about to use the clipboard temporarily: do not remember it."""
    global _suppress_until
    with _lock:
        _suppress_until = max(_suppress_until, time.monotonic() + seconds)


def suppressed() -> bool:
    return time.monotonic() < _suppress_until


_PRIVATE_FORMATS = ("excludeclipboardcontentfrommonitorprocessing", "clipboard viewer ignore")


def marked_private(formats: dict) -> bool:
    """``formats`` maps clipboard format names to their bytes."""
    for name, data in formats.items():
        lowered = str(name).casefold()
        if any(marker in lowered for marker in _PRIVATE_FORMATS):
            return True
        if "canincludeinclipboardhistory" in lowered or "canuploadtocloudclipboard" in lowered:
            if "canincludeinclipboardhistory" in lowered and bytes(data or b"")[:4] in (b"", b"\0\0\0\0"):
                return True
    return False


def _norm(name: str) -> str:
    name = str(name or "").casefold()
    name = re.sub(r"\.exe$", "", name)
    return re.sub(r"[^0-9a-zа-яё]", "", name)


def excluded_app(app: str, names) -> bool:
    """True when the program ``app`` (exe name) is in the exclusion list."""
    app = _norm(app)
    if not app:
        return False
    for name in names:
        name = _norm(name)
        if name and (app == name or (len(name) >= 5 and app.startswith(name))):
            return True
    return False


def parse_names(value) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    return [line.strip() for line in str(value or "").replace(",", "\n").splitlines() if line.strip()]


class ClipboardHistory:
    def __init__(self):
        self.items: list[dict] = []
        self._next = 1

    # -- adding --
    def _new_id(self) -> int:
        value = self._next
        self._next += 1
        return value

    def _push(self, item: dict, key: str) -> dict:
        item["key"] = key
        existing = next((entry for entry in self.items if entry.get("key") == key), None)
        if existing is not None:
            self.items.remove(existing)
            item["pinned"] = existing.get("pinned", False)
            item["id"] = existing["id"]
        self.items.insert(0, item)
        return item

    def add_text(self, value: str, *, html: str = "", app: str = "", now: float | None = None) -> dict | None:
        value = str(value or "")
        if not value.strip():
            return None
        # The identity is the WHOLE text, computed before the cut (audit 2 #31): two long texts with
        # the same beginning stay two items, and a pinned one is never replaced by the other.
        key = "t:" + hashlib.sha1(value.encode("utf-8", "replace")).hexdigest()
        truncated = len(value) > MAX_TEXT
        value = value[:MAX_TEXT]
        html = str(html or "")[: MAX_TEXT * 3]
        item = {"id": self._new_id(), "kind": "text", "text": value, "html": html, "app": app,
                "time": time.time() if now is None else now, "pinned": False}
        if truncated:
            item["truncated"] = True  # shown in the list: only the first MAX_TEXT characters were kept
        return self._push(item, key)

    def add_image(self, png: bytes, *, thumb: bytes = b"", size=(0, 0), app: str = "",
                  now: float | None = None) -> dict | None:
        if not png or len(png) > MAX_IMAGE_BYTES:
            return None
        digest = hashlib.sha1(png).hexdigest()
        item = {"id": self._new_id(), "kind": "image", "text": "", "png": png, "thumb": thumb,
                "size": list(size), "app": app, "time": time.time() if now is None else now, "pinned": False}
        return self._push(item, "i:" + digest)

    # -- limits --
    def trim(self, keep: int, budget: int = 160 * 1024 * 1024) -> None:
        ordinary = [item for item in self.items if not item.get("pinned")]
        for item in ordinary[max(1, int(keep)):]:
            self.items.remove(item)
        # A total size limit: the oldest unpinned pictures go first, so memory and the saved file stay bounded.
        total = sum(len(item.get("png") or b"") + len(item.get("thumb") or b"") for item in self.items)
        for item in reversed([entry for entry in self.items if entry["kind"] == "image" and not entry.get("pinned")]):
            if total <= budget:
                break
            total -= len(item.get("png") or b"") + len(item.get("thumb") or b"")
            self.items.remove(item)

    def prune(self, max_age_days: int, now: float | None = None) -> None:
        if not max_age_days:
            return
        limit = (time.time() if now is None else now) - max_age_days * 86400
        self.items = [item for item in self.items if item.get("pinned") or item.get("time", 0) >= limit]

    # -- editing --
    def find(self, item_id: int) -> dict | None:
        return next((item for item in self.items if item["id"] == item_id), None)

    PINNED_IMAGE_BUDGET = 64 * 1024 * 1024

    def toggle_pin(self, item_id: int) -> bool:
        item = self.find(item_id)
        if item is None:
            return False
        if not item.get("pinned") and item["kind"] == "image":
            pinned = sum(len(entry.get("png") or b"") for entry in self.items
                         if entry.get("pinned") and entry["kind"] == "image")
            if pinned + len(item.get("png") or b"") > self.PINNED_IMAGE_BUDGET:
                return False  # pinned pictures are exempt from trimming, so they have their own limit
        item["pinned"] = not item.get("pinned")
        return item["pinned"]

    def remove(self, item_id: int) -> None:
        self.items = [item for item in self.items if item["id"] != item_id]

    def clear(self) -> None:
        """«Очистить историю»: pinned items stay."""
        self.items = [item for item in self.items if item.get("pinned")]

    def clear_all(self) -> None:
        self.items = []

    def ordered(self) -> list[dict]:
        return [item for item in self.items if item.get("pinned")] + \
               [item for item in self.items if not item.get("pinned")]

    def previous_text(self) -> str | None:
        """The text copied before the current one («вставь предыдущее»)."""
        texts = [item for item in self.items if item["kind"] == "text"]
        if len(texts) >= 2:
            return texts[1]["text"]
        return None

    # -- storage --
    def to_bytes(self) -> bytes:
        rows = []
        for item in self.items:
            row = {key: value for key, value in item.items() if key not in ("png", "thumb")}
            if item.get("png"):
                row["png"] = base64.b64encode(item["png"]).decode("ascii")
            if item.get("thumb"):
                row["thumb"] = base64.b64encode(item["thumb"]).decode("ascii")
            rows.append(row)
        return json.dumps({"version": 1, "items": rows}, ensure_ascii=False).encode("utf-8")

    def load_bytes(self, data: bytes) -> None:
        payload = json.loads(data.decode("utf-8"))
        items = []
        for row in payload.get("items", []):
            if not isinstance(row, dict) or row.get("kind") not in ("text", "image"):
                continue
            item = dict(row)
            for key in ("png", "thumb"):
                if isinstance(item.get(key), str):
                    item[key] = base64.b64decode(item[key])
            item["id"] = self._new_id()
            items.append(item)
        self.items = items

    def save(self, path: Path) -> bool:
        if sys.platform != "win32":
            return False
        from luxai.secure_keys import _win_crypt
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        import os as _os
        import uuid as _uuid
        temp = path.with_name(f"{path.name}.{_os.getpid()}.{_uuid.uuid4().hex[:6]}.tmp")  # unique (audit #12)
        try:
            temp.write_bytes(FILE_MAGIC + _win_crypt(self.to_bytes(), True))
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
        return True

    MAX_FILE_BYTES = 400 * 1024 * 1024  # the trim budgets (160 + 64 MB) plus Base64 and encryption

    def load(self, path: Path) -> bool:
        path = Path(path)
        if sys.platform != "win32" or not path.is_file():
            return False
        if path.stat().st_size > self.MAX_FILE_BYTES:
            return False  # checked BEFORE reading (audit 2 #17)
        from luxai.secure_keys import _win_crypt
        raw = path.read_bytes()
        if not raw.startswith(FILE_MAGIC):
            return False
        try:
            self.load_bytes(_win_crypt(raw[len(FILE_MAGIC):], False))
        except Exception:
            return False
        return True


def history_file() -> Path:
    """Inside the app's .luxai_data folder, which updates keep."""
    return Path(__file__).resolve().parents[1] / ".luxai_data" / "clipboard_history.bin"


def clipboard_owner_app() -> str:
    """Exe name of the program that put data on the clipboard (or the active one)."""
    if sys.platform != "win32":
        return ""
    import ctypes
    from ctypes import wintypes
    try:
        import psutil
        user32 = ctypes.windll.user32
        user32.GetClipboardOwner.restype = wintypes.HWND
        user32.GetForegroundWindow.restype = wintypes.HWND
        for hwnd in (user32.GetClipboardOwner(), user32.GetForegroundWindow()):
            if not hwnd:
                continue
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value:
                return psutil.Process(pid.value).name()
    except Exception:
        return ""
    return ""
