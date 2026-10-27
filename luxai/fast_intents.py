"""Tiny deterministic, offline intents for Russian/English/Romanian voice chat.

These run before any neural network or network request. Recognizing routine
phrases must never depend on the availability of an API key or a GGUF model.
"""
from __future__ import annotations

import re
import unicodedata


WAKE_ALIASES = ("jarvis", "джарвис", "жарвис", "джервис", "жервис", "жарис", "джарис")

_REQUEST_PREFIX = re.compile(
    r"^(?:пожалуйста|ну|(?:ты\s+)?можешь(?:\s+ли)?(?:\s+ты)?|"
    r"(?:не\s+)?мог(?:ла)?\s+бы\s+ты|хочу\s+чтобы\s+ты|"
    r"please|(?:can|could|would|will)\s+you(?:\s+please)?|"
    r"te\s+rog(?:\s+frumos)?|(?:poți|poti)(?:\s+(?:tu|te\s+rog(?:\s+frumos)?))?(?:\s+(?:să|sa))?|"
    r"(?:îmi|imi)\s+(?:poți|poti)(?:\s+(?:să|sa))?|"
    r"ai\s+putea(?:\s+(?:te\s+rog))?(?:\s+(?:să|sa))?|"
    r"(?:aș|as)\s+(?:vrea|dori)\s+(?:să|sa)|vreau\s+(?:să|sa)|"
    r"(?:să|sa)(?=\s+(?:deschizi|pornești|pornesti|apeși|apesi|închizi|inchizi|"
    r"setezi|faci|salvezi|scrii)))\b[\s,:;—–-]*", re.I,
)


def command_text(text: str, *, trim_trailing_politeness: bool = True,
                 normalize_unicode: bool = True) -> str:
    """Normalize request framing, never rewrite names, negation or payloads.

    Romanian keyboard layouts can emit cedilla characters or decomposed
    accents. They represent the same spoken command, rather than another
    nickname. Literal typing callers retain the trailing words verbatim.
    """
    value = str(text or "").strip()
    if normalize_unicode:
        value = unicodedata.normalize("NFC", value).translate(
            str.maketrans({"ş": "ș", "Ş": "Ș", "ţ": "ț", "Ţ": "Ț"})
        )
    for _ in range(6):
        previous = value
        value = strip_wake_name(value, strip_trailing=trim_trailing_politeness).strip()
        value = _REQUEST_PREFIX.sub("", value, count=1)
        if value == previous:
            break
    if trim_trailing_politeness:
        value = re.sub(
            r"(?:[,\s]+(?:пожалуйста|please|te\s+rog(?:\s+frumos)?))[.!?]*$",
            "", value, flags=re.I,
        )
    return value.strip()


def strip_wake_name(text: str, configured: str = "Jarvis", *, strip_trailing: bool = True) -> str:
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
    if match:
        return value[match.end():].lstrip(" \t,.!?:;—–-")
    # Many speakers say "Hello, Jarvis" rather than "Jarvis, hello".
    # Strip only a known standalone name at the *end* of a phrase.
    tail = re.search(
        r"[,\s]+(?:" + alternatives + r")[.!?]*$", value, flags=re.IGNORECASE
    ) if strip_trailing else None
    if tail and value[:tail.start()].strip():
        return value[:tail.start()].strip()
    return value


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
        "pornește", "porneste", "pornești", "pornesti", "deschizi", "deschidea",
        "lansează", "lanseaza", "lansezi", "abrir",
    )
    value = command_text(text).casefold()
    return any(re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", value) for word in words)
