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
