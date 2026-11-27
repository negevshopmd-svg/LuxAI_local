"""What the updater itself downloads (0.4.3z), told to the setup window.

The setup window used to add up every byte the network card received, so a
Steam download running at the same time showed up as a 2 GB update. Now each
step that downloads reports its own bytes: helper processes started by the
updater print ``LUXAI_GOT <bytes>`` lines (only when the updater asked for them
through ``LUXAI_UPDATE_METER=1``), and pip's «Downloading x (6.9 MB)» lines are
counted too. Nothing here touches the network.
"""
from __future__ import annotations

import os
import re
import sys

MARKER = "LUXAI_GOT"
ENV = "LUXAI_UPDATE_METER"
_PIP = re.compile(r"^\s*Downloading \S+ \(([\d.,]+)\s*(B|kB|KB|MB|GB)\)", re.M)
_UNITS = {"B": 1, "kB": 1000, "KB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3}
_LINE = re.compile(r"^%s (\d{1,13})$" % MARKER)


def enabled() -> bool:
    return os.environ.get(ENV) == "1"


def report(count: int | float) -> None:
    """One more piece downloaded (only when the updater listens; otherwise nothing is printed)."""
    count = int(count)
    if count > 0 and enabled():
        try:
            print(f"{MARKER} {count}", flush=True)
        except (OSError, ValueError):
            pass


def pip_bytes(text: str) -> int:
    """The sizes pip announces for what it really downloads («Using cached» is not a download)."""
    total = 0.0
    for number, unit in _PIP.findall(str(text or "")):
        try:
            total += float(number.replace(",", ".")) * _UNITS[unit]
        except (ValueError, KeyError):
            continue
    return int(total)


def parse_line(line: str) -> int | None:
    """Bytes of a ``LUXAI_GOT`` line, or None for any other line."""
    match = _LINE.match(str(line or "").strip())
    return int(match.group(1)) if match else None


def folder_size(path) -> int:
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += os.stat(os.path.join(root, name)).st_size
                except OSError:
                    continue
    except OSError:
        return 0
    return total


if __name__ == "__main__":  # pragma: no cover - manual check
    print(pip_bytes(sys.stdin.read()))
