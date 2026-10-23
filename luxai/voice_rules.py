"""Language-specific ASR settings independent of audio drivers."""
ROMANIAN_PROMPT = (
    "Conversație în limba română cu asistentul vocal Jarvis. "
    "Deschide YouTube, Telegram, Discord, Steam, Dota, Google Chrome. "
    "Apasă Enter, Escape, Control, Shift, tasta Q; creează un fișier sau un dosar. "
    "Salut, Jarvis. Pornește programul. Mulțumesc."
)


def recognition_options(language: str | None, beam_size: int) -> dict:
    return {
        "language": language,
        "beam_size": max(3, beam_size) if language == "ro" else beam_size,
        "best_of": 1,
        "vad_filter": False,
        "condition_on_previous_text": False,
        "initial_prompt": ROMANIAN_PROMPT if language == "ro" else None,
        "temperature": 0.0,
        "no_speech_threshold": 0.65,
    }


# Whisper can hallucinate video outro phrases on noise or silence, especially
# when a segment is too short. Do not forward these boilerplate transcripts.
import re
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
    return re.sub(r"[^\w\s-]+", " ", str(text or "").casefold(), flags=re.UNICODE).strip().replace("  ", " ")


def is_hallucinated_outro(text: str) -> bool:
    return normalized_speech(text) in OUTRO_HALLUCINATIONS


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
