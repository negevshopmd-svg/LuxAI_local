"""Steam downloads for the status island (0.4.3y): which game, how far, how fast, how long still.

Steam has no local API for this, and the app manifest is written only when an
update starts or stops, so the island follows Steam's own ``logs/content_log.txt``
(read-only, from where it is now): «update started : download A/B» gives the
start and the size, «Current download rate: X Mbps» comes once a minute, the
state lines tell downloading / verifying / installing / paused / finished.
Between the rate lines the progress is estimated from the last rate (shown with
«≈»). Nothing is written anywhere.
"""
from __future__ import annotations

import datetime as _dt
import re
import time
from pathlib import Path

LINE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] (.*)$")
STARTED = re.compile(r"AppID (\d+) update started : download (\d+)/(\d+), store \d+/\d+, reuse \d+/\d+, delta \d+/\d+, "
                     r"stage (\d+)/(\d+)")
CHANGED = re.compile(r"AppID (\d+) App update changed : (.*)$")
RATE = re.compile(r"Current download rate: ([\d.]+) Mbps")
FINISHED = re.compile(r"AppID (\d+) finished update")
CANCELED = re.compile(r"AppID (\d+) update canceled")
SUSPENDED = re.compile(r"AppID (\d+) state changed : .*\(Suspended\)")
TAIL_ON_START = 300_000  # bytes of the log read at start: enough to find a download that is already running


def _when(text: str) -> float:
    try:
        return _dt.datetime.strptime(text, "%Y-%m-%d %H:%M:%S").timestamp()
    except ValueError:
        return time.time()


def phase_of(flags: str) -> str:
    flags = flags.casefold()
    if "verifying" in flags or "validating" in flags:
        return "verifying"
    if "downloading" in flags:
        return "downloading"
    if "committing" in flags or "staging" in flags or "preallocating" in flags or "reconfiguring" in flags:
        return "installing"
    if flags.strip(" ,") == "none":
        return "stopped"
    return "preparing"


class SteamDownloads:
    """Feed it the log lines (``feed``) or let it read the log (``poll``); ``state()`` is what the island shows."""

    def __init__(self, log_path: Path | None = None):
        self.path = Path(log_path) if log_path else None
        self.offset = None
        self.app = None   # the download now: dict
        self.done: list[dict] = []  # finished since the last state() call
        self._partial = ""

    # -- reading -----------------------------------------------------------------------------------
    def _locate(self) -> Path | None:
        if self.path is None:
            from luxai.game_detect import SteamIndex
            root = SteamIndex().root()
            self.path = root / "logs" / "content_log.txt" if root else None
        return self.path

    def poll(self):
        path = self._locate()
        if path is None:
            return
        try:
            size = path.stat().st_size
        except OSError:
            return
        if self.offset is None or size < self.offset:
            self.offset = max(0, size - TAIL_ON_START) if self.offset is None else 0  # first look / log rotated
            self._partial = ""
            skip_first = self.offset > 0
        else:
            skip_first = False
        if size == self.offset:
            return
        try:
            with open(path, "rb") as handle:
                handle.seek(self.offset)
                data = handle.read(min(size - self.offset, 2_000_000))
        except OSError:
            return
        self.offset += len(data)
        text = self._partial + data.decode("utf-8", errors="replace")
        lines = text.split("\n")
        self._partial = lines.pop()  # an unfinished last line waits for the rest
        if skip_first and lines:
            lines.pop(0)  # we started in the middle of a line
        for line in lines:
            self.feed(line.rstrip("\r"))

    def feed(self, line: str):
        match = LINE.match(line)
        if not match:
            return
        when, body = _when(match.group(1)), match.group(2)
        started = STARTED.search(body)
        if started:
            appid, got, total, staged, stage_total = started.groups()
            total_bytes = int(total) or int(stage_total)
            done_bytes = int(got) if int(total) else int(staged)
            self.app = {"appid": appid, "downloaded": float(done_bytes), "total": float(total_bytes), "rate": 0.0,
                        "at": when, "phase": "preparing", "started": when}
            return
        app = self.app
        rate = RATE.search(body)
        if rate and app is not None:
            self._advance(when)
            app["rate"] = float(rate.group(1)) * 1_000_000 / 8
            return
        for pattern, kind in ((FINISHED, "finished"), (CANCELED, "paused"), (SUSPENDED, "paused")):
            found = pattern.search(body)
            if found and app is not None and found.group(1) == app["appid"]:
                self._advance(when)
                if kind == "finished":
                    self.done.append({"appid": app["appid"], "total": app["total"], "seconds": when - app["started"]})
                    self.app = None
                else:
                    app["phase"], app["rate"] = "paused", 0.0
                return
        changed = CHANGED.search(body)
        if changed and app is not None and changed.group(1) == app["appid"]:
            self._advance(when)
            phase = phase_of(changed.group(2))
            if phase == "stopped":
                app["phase"], app["rate"] = ("paused" if app["phase"] != "finished" else "finished"), 0.0
            else:
                app["phase"] = phase

    def _advance(self, when: float):
        """Bytes downloaded since the last line, at the last known rate."""
        app = self.app
        if app is None:
            return
        if app["phase"] == "downloading" and app["rate"] > 0:
            app["downloaded"] = min(app["total"], app["downloaded"] + app["rate"] * max(0.0, when - app["at"]))
        app["at"] = when

    # -- what the island shows ------------------------------------------------------------------
    def state(self, now: float | None = None) -> dict | None:
        app = self.app
        if app is None:
            return None
        now = time.time() if now is None else now
        downloaded = app["downloaded"]
        if app["phase"] == "downloading" and app["rate"] > 0:
            downloaded = min(app["total"], downloaded + app["rate"] * max(0.0, min(now - app["at"], 180)))
        left = max(0.0, app["total"] - downloaded)
        eta = left / app["rate"] if app["rate"] > 0 and app["phase"] == "downloading" else None
        stale = app["phase"] == "downloading" and now - app["at"] > 600  # Steam closed or the log stopped
        return {"appid": app["appid"], "phase": "paused" if stale else app["phase"], "downloaded": downloaded,
                "total": app["total"], "rate": 0.0 if stale else app["rate"], "eta": None if stale else eta}

    def take_done(self) -> list[dict]:
        done, self.done = self.done, []
        return done


def human_bytes(value: float, language: str) -> str:
    units = {"ru": ("МБ", "ГБ"), "en": ("MB", "GB"), "ro": ("MB", "GB")}.get(language, ("MB", "GB"))
    if value >= 1e9:
        return f"{value / 1e9:.1f} {units[1]}".replace(".", "," if language != "en" else ".")
    return f"{value / 1e6:.0f} {units[0]}"


def human_rate(value: float, language: str) -> str:
    unit = {"ru": "МБ/с", "en": "MB/s", "ro": "MB/s"}.get(language, "MB/s")
    number = value / 1e6
    text = f"{number:.1f}" if number < 10 else f"{number:.0f}"
    return f"{text.replace('.', ',') if language != 'en' else text} {unit}"


def human_eta(seconds: float | None, language: str) -> str:
    if seconds is None:
        return ""
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes = max(1, rest // 60) if not hours else rest // 60
    h, m = {"ru": ("ч", "мин"), "en": ("h", "min"), "ro": ("h", "min")}.get(language, ("h", "min"))
    return f"{hours} {h} {minutes:02d} {m}" if hours else f"{minutes} {m}"
