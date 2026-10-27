"""Decide whether a request describes an operation that requires verified tools.

An offline text-only GGUF model must never be allowed to pretend that it
created/deleted a file, opened an app, executed CMD or looked up live weather.
"""
from __future__ import annotations

import re

from luxai.fast_intents import command_text, strip_wake_name, quick_reply

OPERATION_TERMS = (
    r"открой|открыть|запусти|запустить|включи|включить|"
    r"создай|создать|сделай|переименуй|переименовать|"
    r"нажми|нажать|кликни|щёлкни|щелкни|переключи|поставь|покажи|"
    r"сними|сфотографируй|выбери|"
    r"удали|удалить|сотри|закрой|выключи|"
    r"найди\s+в\s+интернете|погода|погоду|"
    r"перемести|переместить|скопируй|сохрани|"
    r"громкость|сверни|выполни|команду|"
    r"open|launch|start|run|create|rename|delete|"
    r"close|click|press|type|write|move|copy|save|scroll|wait|"
    r"minimize|maximize|shutdown|restart|reboot|mute|unmute|"
    r"weather|deschide|deschizi|pornește|porneste|pornești|pornesti|"
    r"lansează|lanseaza|închide|inchide|închizi|inchizi|oprește|opreste|"
    r"apasă|apasa|apeși|apesi|scrie|scrii|tastează|tasteaza|mută|muta|"
    r"copiază|copiaza|salvează|salveaza|setează|seteaza|reglează|regleaza|"
    r"derulează|deruleaza|așteaptă|asteapta|creează|creeaza|"
    r"redenumește|redenumeste|șterge|sterge|caută|cauta|"
    r"citește|citeste|verifică|verifica|volumul|microfonul|vremea|"
    r"repornește|reporneste|blochează|blocheaza|minimizează|minimizeaza"
)
PATTERN = re.compile(r"(?<!\w)(?:" + OPERATION_TERMS + r")(?!\w)", re.IGNORECASE)


def is_operational_request(text: str) -> bool:
    return bool(PATTERN.search(command_text(text)))


def routine_reply(text: str, language: str = "ru") -> str | None:
    name_removed = strip_wake_name(text)
    if not name_removed:
        return {
            "ru": "Слушаю.",
            "ro": "Te ascult.",
            "en": "I'm listening.",
        }.get(language, "Слушаю.")
    return quick_reply(name_removed, language)


def suspicious_completion_reply(text: str) -> bool:
    """Detect when a model tries to claim Windows success as plain prose."""
    if not isinstance(text, str):
        return False
    return bool(re.search(
        r"\b(?:открыл(?:а|и)?|создал(?:а|и)?|переименовал(?:а|и)?|"
        r"удалил(?:а|и)?|запустил(?:а|и)?|выполнил(?:а|и)?|"
        r"закрыл(?:а|и)?|нажал(?:а|и)?|сохранил(?:а|и)?|скопировал(?:а|и)?|"
        r"opened|created|renamed|deleted|launched|executed|closed|saved|copied|moved|pressed|"
        r"am\s+(?:deschis|pornit|creat|redenumit|șters|sters|închis|inchis|"
        r"executat|apăsat|apasat|salvat|copiat|mutat|setat|restartat))\b",
        text.casefold(),
    ))
