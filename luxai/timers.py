"""Timers and alarms (0.4.1c): phrase parsing, persistence and formatting.

Pure module (no Qt). ``parse_request`` understands RU/RO/EN requests such as
«поставь таймер на 10 минут», «напомни через 20 минут выключить плиту»,
«разбуди в 7:30», «отмени таймер», «сколько осталось». ``TimerStore`` keeps
timers in ``.luxai_data/timers.json`` (atomic writes) so alarms survive a
restart; a timer that expired while Jarvis was closed rings once on start.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

MAX_TIMERS = 20
MAX_SECONDS = 7 * 24 * 3600

_UNITS = {
    "seconds": r"(?:секунд\w*|сек\.?|secund\w*|sec\.?|seconds?|secs?)",
    "minutes": r"(?:минут\w*|мин\.?|minut\w*|min\.?|minutes?|mins?)",
    "hours": r"(?:час\w*|ч\.?|or[ăa]\w*|ore|hours?|hrs?|h)",
}
_FACTOR = {"seconds": 1, "minutes": 60, "hours": 3600}

_WORD_NUMBERS = {
    # ru
    "один": 1, "одну": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6,
    "семь": 7, "восемь": 8, "девять": 9, "десять": 10, "одиннадцать": 11, "двенадцать": 12,
    "пятнадцать": 15, "двадцать": 20, "двадцать пять": 25, "тридцать": 30, "сорок": 40,
    "сорок пять": 45, "пятьдесят": 50, "полтора": 1.5, "полторы": 1.5, "пол": 0.5,
    # ro
    "unu": 1, "o": 1, "un": 1, "doi": 2, "două": 2, "doua": 2, "trei": 3, "patru": 4, "cinci": 5,
    "șase": 6, "sase": 6, "șapte": 7, "sapte": 7, "opt": 8, "nouă": 9, "noua": 9, "zece": 10,
    "cincisprezece": 15, "douăzeci": 20, "douazeci": 20, "treizeci": 30, "patruzeci": 40,
    # en
    "one": 1, "a": 1, "an": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
    "forty five": 45, "fifty": 50, "half": 0.5,
}
_NUMBER = r"(\d+(?:[.,]\d+)?|" + "|".join(sorted((re.escape(word) for word in _WORD_NUMBERS), key=len, reverse=True)) + r")"

_TIMER_WORDS = re.compile(
    r"(?:таймер\w*|засеки|засечь|отсчёт|отсчет|cronometr\w*|temporizator\w*|timer\w*|countdown)", re.I)
_REMIND_WORDS = re.compile(r"(?:напомни\w*|напомнить|aminte[șs]te-mi|aminteste-mi|reaminte[șs]te|remind\s+me)", re.I)
_ALARM_WORDS = re.compile(
    r"(?:будильник\w*|разбуди\w*|подними\s+меня|alarm[aă]\w*|alarma|trezeș?te-m[aă]|trezeste-ma|deștept\w*|"
    r"alarm\b|wake\s+me(?:\s+up)?)", re.I)
_CANCEL_WORDS = re.compile(
    r"(?:отмени\w*|удали\w*|выключи\w*|останови\w*|сбрось|убери|anuleaz[aă]|[șs]terge|opre[șs]te|"
    r"cancel|delete|remove|stop|turn\s+off)", re.I)
_ALL_WORDS = re.compile(r"(?:все|всё|toate|toat|all)", re.I)
_LIST_WORDS = re.compile(
    r"(?:сколько\s+(?:осталось|времени\s+осталось)|какие\s+(?:таймеры|будильники)|список\s+(?:таймеров|будильников)|"
    r"c[âa]t\s+a\s+mai\s+r[aă]mas|ce\s+(?:cronometre|alarme)|how\s+(?:much|long)\s+(?:time\s+)?(?:is\s+)?left|"
    r"what\s+(?:timers|alarms)|list\s+(?:timers|alarms))", re.I)


def _number(value: str) -> float:
    value = value.strip().casefold()
    if value in _WORD_NUMBERS:
        return float(_WORD_NUMBERS[value])
    return float(value.replace(",", "."))


def parse_duration(text: str) -> int | None:
    """Total seconds from phrases like "1 час 20 минут", "полчаса", "90 sec"."""
    value = " " + str(text or "").casefold().replace("ё", "е") + " "
    special = {r"полчаса|пол\s*часа|o\s+jum[aă]tate\s+de\s+or[aă]|half\s+an\s+hour": 1800,
               r"полтора\s+часа": 5400, r"полторы\s+минуты": 90, r"четверть\s+часа|un\s+sfert\s+de\s+or[aă]|quarter\s+of\s+an\s+hour": 900}
    total = 0
    for pattern, seconds in special.items():
        if re.search(pattern, value):
            total += seconds
            value = re.sub(pattern, " ", value)
    for unit, unit_pattern in _UNITS.items():
        for match in re.finditer(r"(?<![\w:])" + _NUMBER + r"\s*" + unit_pattern + r"(?!\w)", value, re.I):
            total += int(round(_number(match.group(1)) * _FACTOR[unit]))
    if total == 0:
        # A bare unit means one: «на минуту», «на час», «на секунду».
        bare = re.search(r"(?<!\w)(минуту|час|секунду)(?!\w)", value)
        if bare:
            total = {"минуту": 60, "час": 3600, "секунду": 1}[bare.group(1)]
    if total <= 0:
        return None
    return min(total, MAX_SECONDS)


def parse_clock(text: str, now: dt.datetime) -> dt.datetime | None:
    """Next occurrence of a clock time: "7:30", "в 7 утра", "la 6", "at 6 pm"."""
    value = str(text or "").casefold()
    match = re.search(r"(?<!\d)(\d{1,2})[:.\-h ](\d{2})(?!\d)", value)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
    else:
        match = re.search(r"(?:\bв\b|\bна\b|\bla\b|\bat\b|\bfor\b|ora)\s+(\d{1,2})(?!\s*(?:минут|мин|час|min|ore|or[aă]|hour|sec|сек|\d))", value)
        if not match:
            return None
        hour, minute = int(match.group(1)), 0
    if re.search(r"(?:вечера|дня|pm|p\.m\.|seara|seară|după-amiaza)", value) and hour < 12:
        hour += 12
    if re.search(r"(?:ночи|am|a\.m\.)", value) and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if re.search(r"(?:завтра|mâine|maine|tomorrow)", value) or target <= now:
        target += dt.timedelta(days=1)
    return target


def _label(text: str) -> str:
    """Words after the time in a reminder: «… через 20 минут выключить плиту»."""
    value = str(text or "")
    pieces = re.split(r"(?:\d+\s*(?:" + "|".join(_UNITS.values()) + r")|полчаса|полтора\s+часа|half\s+an\s+hour)",
                      value, flags=re.I)
    tail = pieces[-1] if len(pieces) > 1 else ""
    tail = re.sub(r"^[\s,.:;—-]*(?:что(?:бы)?|о\s+том,?\s+что(?:бы)?|să|sa|to|about)?\s*", "", tail, flags=re.I).strip(" .,!?")
    return tail[:80]


@dataclass
class Request:
    kind: str  # timer | alarm | cancel | list
    seconds: int = 0
    at: dt.datetime | None = None
    label: str = ""
    all: bool = False


def parse_request(text: str, now: dt.datetime | None = None) -> Request | None:
    """Recognize a timer/alarm request; None when the text is something else."""
    now = now or dt.datetime.now()
    value = " ".join(str(text or "").split())
    if not value or len(value) > 300:
        return None
    lowered = value.casefold()
    timerish = bool(_TIMER_WORDS.search(lowered))
    alarmish = bool(_ALARM_WORDS.search(lowered))
    remind = bool(_REMIND_WORDS.search(lowered))
    if _LIST_WORDS.search(lowered):
        return Request("list")
    if (timerish or alarmish) and _CANCEL_WORDS.search(lowered) and not re.search(r"\bна\s+\d|\bfor\s+\d|\bde\s+\d", lowered):
        return Request("cancel", all=bool(_ALL_WORDS.search(lowered)),
                       label="alarm" if alarmish and not timerish else ("timer" if timerish and not alarmish else ""))
    if alarmish:
        at = parse_clock(lowered, now)
        if at is not None:
            return Request("alarm", at=at)
        seconds = parse_duration(lowered)
        if seconds and re.search(r"(?:через|în|in)\s", lowered):
            return Request("alarm", at=now + dt.timedelta(seconds=seconds))
        return None
    if timerish or remind:
        seconds = parse_duration(lowered)
        if seconds:
            return Request("timer", seconds=seconds, label=_label(value) if remind else "")
        if remind:
            at = parse_clock(lowered, now)
            if at is not None:
                return Request("alarm", at=at, label=_label(re.sub(r"\d{1,2}[:.]\d{2}", "", value)))
    return None


# --- formatting -------------------------------------------------------------------

def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def format_duration(seconds: int, language: str = "ru") -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    for amount, ru, en, ro in ((hours, ("час", "часа", "часов"), ("hour", "hours"), ("oră", "ore")),
                               (minutes, ("минуту", "минуты", "минут"), ("minute", "minutes"), ("minut", "minute")),
                               (secs, ("секунду", "секунды", "секунд"), ("second", "seconds"), ("secundă", "secunde"))):
        if not amount:
            continue
        if language == "en":
            parts.append(f"{amount} {en[0] if amount == 1 else en[1]}")
        elif language == "ro":
            parts.append(f"{amount} {ro[0] if amount == 1 else ro[1]}")
        else:
            parts.append(f"{amount} {_plural_ru(amount, *ru)}")
    if not parts:
        return {"ru": "0 секунд", "en": "0 seconds", "ro": "0 secunde"}.get(language, "0 секунд")
    return " ".join(parts)


def format_countdown(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


# --- persistence --------------------------------------------------------------------

@dataclass
class Timer:
    id: str
    kind: str  # timer | alarm
    due: float  # epoch seconds
    label: str = ""
    duration: int = 0  # timers only, for the "10 minutes" wording
    created: float = field(default_factory=lambda: dt.datetime.now().timestamp())

    def remaining(self, now: float | None = None) -> int:
        now = dt.datetime.now().timestamp() if now is None else now
        return max(0, int(round(self.due - now)))


def new_timer(kind: str, due: float, label: str = "", duration: int = 0) -> Timer:
    return Timer(uuid.uuid4().hex[:12], kind, float(due), str(label or "")[:80], int(duration))


class TimerStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.items: list[Timer] = []
        self.load()

    def load(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = []
        items = []
        for entry in raw if isinstance(raw, list) else []:
            try:
                if entry.get("kind") not in ("timer", "alarm"):
                    continue
                items.append(Timer(str(entry["id"])[:20], entry["kind"], float(entry["due"]),
                                   str(entry.get("label", ""))[:80], int(entry.get("duration", 0)),
                                   float(entry.get("created", 0))))
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
        self.items = sorted(items, key=lambda item: item.due)[:MAX_TIMERS]

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        staging = self.path.with_name(self.path.name + ".tmp")
        staging.write_text(json.dumps([asdict(item) for item in self.items], ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(staging, self.path)

    def add(self, timer: Timer) -> Timer:
        if len(self.items) >= MAX_TIMERS:
            raise ValueError("too many timers")
        self.items.append(timer)
        self.items.sort(key=lambda item: item.due)
        self.save()
        return timer

    def remove(self, identifier: str) -> bool:
        before = len(self.items)
        self.items = [item for item in self.items if item.id != identifier]
        if len(self.items) != before:
            self.save()
            return True
        return False

    def clear(self, kind: str = "") -> int:
        before = len(self.items)
        self.items = [item for item in self.items if kind and item.kind != kind]
        if len(self.items) != before:
            self.save()
        return before - len(self.items)

    def due(self, now: float | None = None) -> list[Timer]:
        now = dt.datetime.now().timestamp() if now is None else now
        return [item for item in self.items if item.due <= now]
