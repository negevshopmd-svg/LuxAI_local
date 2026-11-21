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
import math
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
            if re.search(r"[-−–]\s*$", value[:match.start()]):
                return None  # «-5 minutes» is not five minutes (audit #16)
            total += int(round(_number(match.group(1)) * _FACTOR[unit]))
    if total == 0:
        # A bare unit means one: «на минуту», «на час», «на секунду».
        bare = re.search(r"(?<!\w)(минуту|час|секунду)(?!\w)", value)
        if bare:
            total = {"минуту": 60, "час": 3600, "секунду": 1}[bare.group(1)]
    if total <= 0:
        return None
    return min(total, MAX_SECONDS)


_CLOCK_FULL = re.compile(r"(?<!\d)(\d{1,2})[:.\-h ](\d{2})(?!\d)", re.I)
_CLOCK_HOUR = re.compile(r"(?:\bв\b|\bна\b|\bla\b|\bat\b|\bfor\b|ora)\s+(\d{1,2})"
                         r"(?!\s*(?:минут|мин|час|min|ore|or[aă]|hour|sec|сек|\d))", re.I)
_CLOCK_SUFFIX = re.compile(r"\s*(?:am|pm|a\.m\.|p\.m\.|утра|вечера|дня|ночи)\b", re.I)


def _clock_match(value: str):
    """The clock-time match in ``value`` (the SAME one for the time and for the label, audit 2 #10)."""
    return _CLOCK_FULL.search(value) or _CLOCK_HOUR.search(value)


_PM = r"(?:вечера|дня|pm|p\.m\.|seara|seară|după-amiaza)"
_AM = r"(?:ночи|утра|am|a\.m\.|dimineața|dimineata)"
_DAY = r"(?:завтра|mâine|maine|tomorrow)"


def parse_clock(text: str, now: dt.datetime, *, near_only: bool = False) -> dt.datetime | None:
    """Next occurrence of a clock time: "7:30", "в 7 утра", "la 6", "at 6 pm".

    ``near_only`` (reminders): AM/PM and «tomorrow» count only next to the time itself, never inside the
    message — «remind me at 08:00 to check PM report» is 08:00, not 20:00 (audit 3 #5).
    """
    value = str(text or "").casefold()
    match = _CLOCK_FULL.search(value)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
    else:
        match = _CLOCK_HOUR.search(value)
        if not match:
            return None
        hour, minute = int(match.group(1)), 0
    if near_only:
        after = value[match.end():]
        marker = re.match(r"\s*(" + _PM + "|" + _AM + r")\b", after)
        marks = marker.group(1) if marker else ""
        rest = after[marker.end():] if marker else after
        day = bool(re.search(_DAY, value[:match.start()]) or re.match(r"\s*,?\s*" + _DAY, rest))
    else:
        marks, day = value, bool(re.search(_DAY, value))
    if re.search(_PM, marks) and hour < 12:
        hour += 12
    if re.search(r"(?:ночи|am|a\.m\.)", marks) and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if day or target <= now:
        target += dt.timedelta(days=1)
    return target


_DURATION_PART = re.compile(
    r"(?<![\w:])" + _NUMBER + r"\s*(?:" + "|".join(_UNITS.values()) + r")(?!\w)|полчаса|пол\s*часа|полтора\s+часа|"
    r"half\s+an\s+hour|quarter\s+of\s+an\s+hour|четверть\s+часа|o\s+jum[aă]tate\s+de\s+or[aă]", re.I)
_JOIN = re.compile(r"^\s*(?:,|и|and|și|si)?\s*$", re.I)


def _duration_start(text: str) -> int:
    """Where the first duration phrase starts (-1 when there is none)."""
    match = _DURATION_PART.search(str(text or ""))
    return match.start() if match else -1


def _first_duration(text: str) -> tuple[str, str]:
    """(the first duration phrase with its compound parts, the words after it).

    «remind me in 5 minutes to check the oven for 2 minutes» → ("5 minutes", "to check the oven for 2 minutes"):
    only the first clause sets the time; the rest is the message (audit #15).
    A minus in front stays with the phrase («-5 minutes», «−5 minutes»), so the same validation as for
    timers refuses it (audit 2 #9).
    """
    value = str(text or "")
    matches = list(_DURATION_PART.finditer(value))
    if not matches:
        return "", ""
    end = matches[0].end()
    sign = "-" if re.search(r"[-−–]\s*$", value[:matches[0].start()]) else ""
    parts = [sign + matches[0].group(0)]
    for match in matches[1:]:
        if _JOIN.match(value[end:match.start()]):
            parts.append(match.group(0))
            end = match.end()
        else:
            break
    return " ".join(parts), value[end:]


def _clean_label(tail: str) -> str:
    tail = re.sub(r"^[\s,.:;—-]*(?:что(?:бы)?|о\s+том,?\s+что(?:бы)?|să|sa|to|about|that)?\s*", "", tail,
                  flags=re.I).strip(" .,!?")
    return tail[:80]


_TIME_PREPOSITION = re.compile(r"\s*(?:через|в|во|на|к|în|in|la|at|on|at\s+about|ora|peste)\s*$", re.I)


def _body_before(text: str, start: int) -> str:
    """The message written BEFORE the time: «remind me to call Ana in 5 minutes» → «call Ana» (audit 2 #10)."""
    value = str(text or "")
    remind = _REMIND_WORDS.search(value)
    if not remind or start <= remind.end():
        return ""
    body = _TIME_PREPOSITION.sub("", value[remind.end():start])
    return _clean_label(body)


def _label(text: str) -> str:
    """Words after the time in a reminder: «… через 20 минут выключить плиту», «in five minutes to call Ana»."""
    after = _clean_label(_first_duration(text)[1])
    return after or _body_before(text, _duration_start(text))


def _clock_label(text: str) -> str:
    """Words after the clock time in «remind me at 09:30 to call Ana» (or before it, «… to call Ana at 7:30»)."""
    value = str(text or "")
    match = _clock_match(value)
    if not match:
        return ""
    end = match.end()
    suffix = _CLOCK_SUFFIX.match(value, end)
    if suffix:
        end = suffix.end()
    return _clean_label(value[end:]) or _body_before(value, match.start())


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
    remind_match = _REMIND_WORDS.search(lowered)
    remind = bool(remind_match)
    if remind_match and not any(m.start() < remind_match.start() for pattern in (_TIMER_WORDS, _ALARM_WORDS, _CANCEL_WORDS)
                                for m in [pattern.search(lowered)] if m):
        # «remind me …» first: the words after it are the MESSAGE («… to check the alarm» stays a
        # reminder with that label, audit 2 #10), never a second command.
        return _parse_reminder(value, lowered, now)
    if _LIST_WORDS.search(lowered) and (timerish or alarmish or len(lowered.split()) <= 4):
        return Request("list")  # a long general question («… left in this video») goes to the chat (audit #16)
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
    if remind:
        return _parse_reminder(value, lowered, now)
    if timerish:
        seconds = parse_duration(lowered)
        if seconds:
            return Request("timer", seconds=seconds)
    return None


def _parse_reminder(value: str, lowered: str, now: dt.datetime) -> Request | None:
    """Intent, time and message parsed separately; the label comes from the same match as the time."""
    # Whatever comes FIRST sets the trigger — a duration («in 5 minutes») or a clock time («at 08:00»);
    # the other one belongs to the message (audit 3 #5: «at 08:00 to water plants for 5 minutes»).
    duration_at = _duration_start(value)
    clock = _clock_match(value)
    clock_first = clock is not None and (duration_at < 0 or clock.start() < duration_at)
    if not clock_first:
        first, _tail = _first_duration(value)
        if first:
            seconds = parse_duration(first)  # «-5 minutes» → None: never five minutes (audit 2 #9)
            return Request("timer", seconds=seconds, label=_label(value)) if seconds else None
    at = parse_clock(lowered, now, near_only=True)
    if at is not None:
        return Request("alarm", at=at, label=_clock_label(value))
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


_LATEST = dt.datetime(2200, 1, 1).timestamp()


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
                due, created = float(entry["due"]), float(entry.get("created", 0))
                # NaN / infinity / year 3000 would break the countdown or never ring (audit #17).
                if not (math.isfinite(due) and math.isfinite(created) and 0 < due < _LATEST):
                    continue
                duration = int(entry.get("duration", 0))
                if not 0 <= duration <= MAX_SECONDS:
                    continue
                items.append(Timer(str(entry["id"])[:20], entry["kind"], due,
                                   str(entry.get("label", ""))[:80], duration, created))
            except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
                continue
        self.items = sorted(items, key=lambda item: item.due)[:MAX_TIMERS]

    def save(self, items: list[Timer] | None = None):
        items = self.items if items is None else items
        self.path.parent.mkdir(parents=True, exist_ok=True)
        staging = self.path.with_name(f"{self.path.name}.{os.getpid()}.{uuid.uuid4().hex[:6]}.tmp")
        try:
            staging.write_text(json.dumps([asdict(item) for item in items], ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(staging, self.path)
        finally:
            staging.unlink(missing_ok=True)

    def _commit(self, items: list[Timer]) -> None:
        """Write first, change the list after: a failed save leaves memory and disk the same (audit #18)."""
        items = sorted(items, key=lambda item: item.due)
        self.save(items)
        self.items = items

    def add(self, timer: Timer) -> Timer:
        if len(self.items) >= MAX_TIMERS:
            raise ValueError("too many timers")
        self._commit(self.items + [timer])
        return timer

    def remove(self, identifier: str) -> bool:
        remaining = [item for item in self.items if item.id != identifier]
        if len(remaining) == len(self.items):
            return False
        self._commit(remaining)
        return True

    def remove_many(self, identifiers) -> int:
        """Remove several timers with ONE write (audit 2 #37): all or nothing."""
        wanted = set(identifiers)
        remaining = [item for item in self.items if item.id not in wanted]
        removed = len(self.items) - len(remaining)
        if removed:
            self._commit(remaining)
        return removed

    def clear(self, kind: str = "") -> int:
        remaining = [item for item in self.items if kind and item.kind != kind]
        removed = len(self.items) - len(remaining)
        if removed:
            self._commit(remaining)
        return removed

    def due(self, now: float | None = None) -> list[Timer]:
        now = dt.datetime.now().timestamp() if now is None else now
        return [item for item in self.items if item.due <= now]
