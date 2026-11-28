"""Language-specific ASR settings independent of audio drivers."""
ROMANIAN_PROMPT = (
    "Conversație în limba română cu asistentul vocal Jarvis. "
    "Deschide YouTube, Telegram, Discord, Steam, Dota, Google Chrome, War Thunder. "
    "Apasă Enter, Escape, Control, Shift, tasta Q; creează un fișier sau un dosar. "
    "Salut, Jarvis. Pornește programul. Închide War Thunder. "
    "Setează volumul la 50 de procente. Citește ecranul. Mulțumesc."
)
# Auto still detects the language acoustically. Context helps short commands
# containing English app/key names without forcing the result into one language.
# 0.4.4c: Russian had no prompt. Measured on spoken commands (tests/command_bench, medium, beam 1): word errors
# 37.8 % → 23.3 %; small 55 % → 37 %. Without it the first syllable was often lost («Открой» → «Рывай», «Сделай» →
# «Делай»). General command vocabulary only, never a fixed list of the user's commands.
RUSSIAN_PROMPT = (
    "Разговор с голосовым помощником Джарвис. Открой YouTube, Discord, Steam, Telegram, калькулятор. "
    "Сделай громче, сделай тише. Поставь таймер. Сделай скриншот. Закрой окно."
)


# 0.4.4d: Whisper sometimes drops or garbles the first sound of a short Russian command (measured with
# tests/command_bench/accuracy_bench.py). Only the FIRST word is repaired, only into the verb it can only mean,
# and only when the rest of the phrase is kept as heard.
import re as _re
_FIRST_WORD_FIXES = (
    (_re.compile(r"^(?:окрой|ткрой|откой|крой|открой-?ка)(?=[\s,.!?]|$)", _re.I), "Открой"),
    (_re.compile(r"^делай(?=\s+(?:по)?(?:громче|тише|скриншот|снимок)\b)", _re.I), "Сделай"),
    (_re.compile(r"^запустит(?:е|ь|ься)?(?=[\s,.!?]|$)", _re.I), "Запусти"),
    (_re.compile(r"^копируй(?=\s|$)", _re.I), "Скопируй"),
    (_re.compile(r"^убей(?=\s+(?:звук|громкость)\b)", _re.I), "Убавь"),
    (_re.compile(r"^напомню(?=[\s,]+(?:через|в|завтра|мне)\b)", _re.I), "Напомни"),
    (_re.compile(r"^найти(?=\s+(?:в|на|мне)\b)", _re.I), "Найди"),
)


def fix_command_words(text: str) -> str:
    """«Окрой калькулятор» → «Открой калькулятор», «Делай тише» → «Сделай тише», «Напомню, через…» → «Напомни…»."""
    value = str(text or "")
    stripped = value.lstrip()
    for pattern, verb in _FIRST_WORD_FIXES:
        match = pattern.match(stripped)
        if match:
            fixed = verb + stripped[match.end():]
            if verb == "Напомни":
                fixed = _re.sub(r"^Напомни,\s*", "Напомни ", fixed)
            return fixed
    return value


AUTO_PROMPT = ROMANIAN_PROMPT + (
    " Русский: открой Discord, нажми клавишу Q, запусти War Thunder."
    " English: open Discord, press the Q key, open War Thunder. Jarvis."
)


def recognition_options(language: str | None, beam_size: int) -> dict:
    return {
        "language": language,
        "beam_size": max(3, beam_size) if language in ("ro", None) else beam_size,
        "best_of": 1,
        "vad_filter": False,
        "condition_on_previous_text": False,
        "initial_prompt": ROMANIAN_PROMPT if language == "ro" else RUSSIAN_PROMPT if language == "ru"
        else AUTO_PROMPT if language is None else None,
        "temperature": 0.0,
        "no_speech_threshold": 0.65,
    }


# Whisper can hallucinate video outro phrases on noise or silence, especially
# when a segment is too short. Do not forward these boilerplate transcripts.
import re
import unicodedata
OUTRO_HALLUCINATIONS = frozenset({
    "спасибо за внимание", "спасибо за просмотр",
    "подписывайтесь на канал", "субтитры сделал", "продолжение следует",
    "thanks for watching", "thank you for watching",
    "mulțumesc pentru vizionare", "multumesc pentru vizionare",
    # Subtitle credits Whisper invents from silence (seen on a real PC).
    "с вами был игорь негода", "редактор субтитров а синецкая корректор а егорова",
    "субтитры создавал dimatorzok", "субтитры подогнал", "корректор а кулакова",
    "subtitles by the amara org community", "amara org",
})
STOP_SPEECH_PHRASES = frozenset({
    "стоп", "замолчи", "замолкни", "хватит", "тихо", "остановись",
    "stop", "stop speaking", "be quiet", "quiet",
    "taci", "oprește-te", "opreste-te", "oprește", "opreste",
})


def normalized_speech(text: str) -> str:
    value = unicodedata.normalize("NFC", str(text or "")).translate(
        str.maketrans({"ş": "ș", "Ş": "Ș", "ţ": "ț", "Ţ": "Ț"})
    ).casefold()
    return " ".join(re.sub(r"[^\w\s-]+", " ", value, flags=re.UNICODE).split())


def is_hallucinated_outro(text: str) -> bool:
    return normalized_speech(text) in OUTRO_HALLUCINATIONS


def is_repetitive_transcript(text: str) -> bool:
    """Reject a near-whole utterance looping the same short unit 12+ times.

    Whisper can turn steady noise into long character/token loops despite a
    high no-speech probability. Do not search inside normal sentences: a
    dictation request or an explicit keyboard sequence may contain repeats.
    Quoted literal text also remains literal.
    """
    raw = str(text or "").strip()
    if len(raw) >= 2 and (raw[0], raw[-1]) in {
        ('"', '"'), ("'", "'"), ("«", "»"), ("“", "”"),
    }:
        return False
    value = normalized_speech(raw)
    words = value.split()
    for width in (1, 2, 3):
        if len(words) >= 12 * width and all(
                word == words[index % width] for index, word in enumerate(words)):
            return True
    return bool(re.fullmatch(r".{0,3}?(?P<unit>.{1,12})(?P=unit){11,}.{0,3}", value))


def is_stop_speech_command(text: str) -> bool:
    return normalized_speech(text) in STOP_SPEECH_PHRASES


def speech_pause_seconds(configured: float | str | None) -> float:
    """2.3s default: tolerate brief thinking pauses before closing a phrase."""
    try:
        value = float(configured)
    except (TypeError, ValueError):
        return 2.3
    if not 1.2 <= value <= 4.0:
        return 2.3
    return value
