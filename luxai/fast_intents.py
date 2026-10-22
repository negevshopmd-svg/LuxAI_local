"""Tiny deterministic, offline intents for Russian/English/Romanian voice chat.

These run before any neural network or network request. Recognizing routine
phrases must never depend on the availability of an API key or a GGUF model.
"""
from __future__ import annotations

import re


WAKE_ALIASES = ("jarvis", "джарвис", "жарвис", "джервис", "жервис")


def strip_wake_name(text: str, configured: str = "Jarvis") -> str:
    """Remove exactly one assistant-name prefix (including Whisper variants)."""
    value = str(text or "").strip()
    names = {word.strip() for word in str(configured).split(",") if word.strip()}
    names.update(WAKE_ALIASES)
    ordered = sorted(names, key=len, reverse=True)
    alternatives = "|".join(re.escape(word) for word in ordered)
    match = re.match(
        r"^\s*(?:" + alternatives + r")(?=$|[\s,.:;!?—–-])",
        value,
        flags=re.IGNORECASE,
    )
    return value[match.end():].lstrip(" \t,.!?:;—–-") if match else value


def quick_reply(text: str, language: str = "ru") -> str | None:
    """Return a concise response for simple talk, with zero model load."""
    text = re.sub(r"[\s.!?,;:—–-]+", " ", str(text or "").casefold()).strip()
    text = re.sub(
        r"^(?:ну|эй|слушай|пожалуйста|hey|please)\s+", "", text,
    )
    speech = {
        "greeting": {
            "ru": "Привет. Слушаю.",
            "ro": "Salut. Te ascult.",
            "en": "Hello. I'm listening.",
        },
        "gratitude": {
            "ru": "Пожалуйста.",
            "ro": "Cu plăcere.",
            "en": "You're welcome.",
        },
        "acknowledgment": {
            "ru": "Хорошо.",
            "ro": "Bine.",
            "en": "Okay.",
        },
        "presence": {
            "ru": "Да, я здесь. Слушаю.",
            "ro": "Da, sunt aici. Te ascult.",
            "en": "Yes, I'm here. I'm listening.",
        },
        "wellbeing": {
            "ru": "Всё отлично. Готов помочь.",
            "ro": "Totul bine. Sunt gata să ajut.",
            "en": "All good. Ready to help.",
        },
        "farewell": {
            "ru": "До встречи.",
            "ro": "Pe curând.",
            "en": "See you.",
        },
    }
    groups = {
        "greeting": {
            "привет", "приветствую", "здравствуй", "здравствуйте",
            "доброе утро", "добрый день", "добрый вечер",
            "хай", "hello", "hi", "hey", "salut", "buna",
            "bună", "bună ziua", "buna ziua", "bună dimineața",
            "buna dimineata", "bună seara", "buna seara",
        },
        "gratitude": {
            "спасибо", "спасибо большое", "большое спасибо",
            "огромное спасибо", "спасибочки", "благодарю",
            "благодарю тебя", "спс", "thank you", "thanks",
            "thanks a lot", "thx", "merci", "mulțumesc",
            "multumesc", "mersi", "mulțumesc mult", "multumesc mult",
        },
        "acknowledgment": {
            "ок", "окей", "ладно", "понял", "понятно",
            "хорошо", "ясно", "okay", "ok", "got it", "bine",
            "am înțeles", "am inteles",
        },
        "presence": {
            "ты тут", "ты здесь", "ты меня слышишь", "слышишь меня",
            "джарвис ты тут", "жарвис ты тут", "are you there",
            "can you hear me", "esti aici", "ești aici",
        },
        "wellbeing": {
            "как дела", "как ты", "как поживаешь", "how are you",
            "ce faci", "cum ești", "cum esti",
        },
        "farewell": {
            "пока", "до свидания", "увидимся", "до встречи",
            "bye", "goodbye", "la revedere",
        },
    }
    for category, phrases in groups.items():
        if text in phrases:
            return speech[category].get(language, speech[category]["ru"])
    return None


def has_launch_verb(text: str) -> bool:
    words = (
        "открой", "открыть", "открывай", "откроешь",
        "запусти", "запустить", "запускай", "запустишь",
        "включи", "включить", "можешь открыть", "можно открыть",
        "open", "launch", "start", "run", "deschide",
        "pornește", "porneste", "abrir",
    )
    value = str(text or "").casefold()
    return any(re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", value) for word in words)
