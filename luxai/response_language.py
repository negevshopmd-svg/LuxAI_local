"""Resolve Jarvis reply language independently of interface translations."""
from __future__ import annotations

import re

from luxai.fast_intents import strip_wake_name


LANGUAGE_NAMES = {"ru": "Russian", "en": "English", "ro": "Romanian"}

def detect_language(text: str, fallback: str = "ro") -> str:
    text = str(text or "")
    if re.search(r"[а-яё]", text, re.IGNORECASE):
        return "ru"
    clean = strip_wake_name(text).casefold()
    # Treat the user's explicit spoken vocabulary as stronger than the Latin
    # alphabet (which is shared by English and Romanian).
    if re.search(r"\b(?:hello|hi|hey|how|what|why|please|thank|thanks|good|are|you|the|open|tell|can)\b", clean):
        return "en"
    if re.search(r"\b(?:salut|bună|buna|ce|cum|sunt|vreau|te|rog|mulțumesc|multumesc|deschide|porneste|pornește)\b", clean):
        return "ro"
    if re.search(r"[ăâîșț]", clean):
        return "ro"
    return fallback if fallback in LANGUAGE_NAMES else "ro"


def reply_language(config: dict, text: str = "") -> str:
    output = str(config.get("response_language", "auto") or "auto").lower()
    if output in LANGUAGE_NAMES:
        return output
    configured = str(config.get("language", "auto") or "auto").lower()
    if configured in LANGUAGE_NAMES:
        return configured
    ui = str(config.get("ui_language", "ro") or "ro").lower()
    return detect_language(text, ui if ui in LANGUAGE_NAMES else "ro")


def language_instruction(language: str) -> str:
    return {
        "ru": "Always reply in Russian. Never switch to another language unless specifically requested.",
        "en": "Always reply in English. Do not use Russian or Romanian in the reply unless quoting the user.",
        "ro": "Always reply in Romanian. Do not use Russian or English in the reply unless quoting the user.",
    }.get(language, "Always reply in English.")
