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
        "initial_prompt": ROMANIAN_PROMPT if language == "ro" else AUTO_PROMPT if language is None else None,
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
