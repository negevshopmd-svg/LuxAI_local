"""Safe file replacement shared by every settings / data writer (0.4.2u, audit #12).

A fixed «file.tmp» name let two writers (two Jarvis copies, a save racing a
backup) overwrite each other's half-written file. Here every write gets its
own temporary name in the SAME folder (so the final rename is atomic), is
flushed to disk, then replaces the target; a briefly locked target (antivirus,
a reader) is retried for a few seconds.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path


def atomic_write_bytes(path, data: bytes, attempts: int = 10) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temporary = Path(name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(attempts):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt == attempts - 1:
                    raise
                time.sleep(0.3)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_text(path, text: str, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding))
