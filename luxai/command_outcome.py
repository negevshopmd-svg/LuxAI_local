"""How a finished command ended: completed, failed or cancelled (audit 7 #4, #5).

The command queue used to look for words anywhere in the reply: «This order was cancelled last
week» cleared the rest of a command chain, and «No errors found» counted as a failure. Only the
fixed replies Jarvis itself gives for a cancellation, and replies that START with its own error
wording, count now.
"""
from __future__ import annotations

import re

# The exact replies Jarvis gives when the user declines or stops something (ru / en / ro).
CANCELLED_REPLIES = frozenset(text.casefold() for text in (
    "Действие отменено.", "Action cancelled.", "Acțiune anulată.",
    "Задача отменена.", "Task cancelled.", "Sarcina a fost anulată.",
    "Команда отменена.", "Command cancelled.", "Comanda a fost anulată.",
    "Создание команды отменено.", "Command creation cancelled.", "Crearea comenzii a fost anulată.",
    "Нажатие отменено.", "Операция отменена.", "Операция отменена", "Команда отменена",
    "Отменено.", "Cancelled.", "Anulat.",
))

_ERROR_PREFIX = re.compile(r"^(?:ошибка|error|eroare)\s*[:.]", re.IGNORECASE)
_FAILURE_START = re.compile(
    r"^(?:не\s+удалось|не\s+получилось|could\s+not|couldn't|failed|nu\s+am\s+putut|nu\s+s-a\s+putut)\b",
    re.IGNORECASE)


def _plain(answer) -> str:
    return " ".join(str(answer or "").split())


def is_cancelled(answer) -> bool:
    """True only for Jarvis' own cancellation reply, alone or after its «Error:» prefix."""
    text = _plain(answer)
    text = _ERROR_PREFIX.sub("", text).strip()
    return text.casefold() in CANCELLED_REPLIES


def is_failed(answer) -> bool:
    """True when the reply starts with Jarvis' error wording or is a cancellation."""
    text = _plain(answer)
    if not text:
        return False
    return bool(_ERROR_PREFIX.match(text) or _FAILURE_START.match(text)) or is_cancelled(text)
