"""Small deterministic Russian voice intents for screen reading and dictation.

Dictation is an explicit local mode: speech chunks are typed only into the
focused *other* application, never into Jarvis or a random app while the UI
is foreground. No transcribed text is sent to Gemini during dictation.
"""
from __future__ import annotations

import re

from luxai.fast_intents import strip_wake_name

DICTATION_START = re.compile(
    r"(?:\b(?:начни|включи|запусти)\s+(?:голосов\w+\s+)?диктовк\w*"
    r"|\b(?:могу|буду)\s+(?:тебе\s+)?диктовать"
    r"|\b(?:будешь|начни)\s+писать\b"
    r"|\b(?:записывай|запиши)\s+(?:всё\s+)?(?:что\s+)?(?:я\s+)?(?:говорю|диктую))",
    re.I,
)
DICTATION_STOP = {
    "стоп", "остановись", "останови диктовку", "закончи диктовку",
    "выключи диктовку", "хватит", "stop", "stop dictation",
    "oprește dictarea", "opreste dictarea",
}
SCREEN_READ = re.compile(
    r"(?:"
    r"\b(?:прочитай|прочесть|прочти|посмотри|покажи|увидь)\b.{0,55}"
    r"\b(?:экран\w*|экране|монитор\w*|написано|текст)\b"
    r"|\b(?:что|какой\s+текст)\b.{0,35}\b(?:на\s+экране|видно\s+на\s+экране)"
    r"|\b(?:видишь|смотришь)\s+(?:мой\s+)?экран"
    r"|\b(?:read|analyze|see)\s+(?:my\s+)?screen\b"
    r")",
    re.I,
)
DISCORD_MIC = re.compile(
    r"(?:(?:дискорд|discord).{0,65}(?:микрофон|микроф|звук\s+микрофона)"
    r"|(?:микрофон|микроф).{0,65}(?:дискорд|discord))",
    re.I,
)
DISCORD_MUTE = re.compile(
    # Whisper frequently produces "выключу" instead of "выключи".
    r"\b(?:выключ\w*|отключ\w*|заглуш\w*|замьют\w*|замут\w*|mute|"
    r"приглуш\w*)\b",
    re.I,
)


def is_dictation_start(text: str) -> bool:
    return bool(DICTATION_START.search(strip_wake_name(text)))


def is_dictation_stop(text: str) -> bool:
    clean = strip_wake_name(text).casefold()
    clean = re.sub(r"[.!?,;:]+", " ", clean)
    clean = " ".join(clean.split())
    return clean in DICTATION_STOP


def dictation_text(text: str) -> str:
    text = strip_wake_name(text).strip()
    if not text:
        return ""
    transforms = {
        "новая строка": "\n",
        "новый абзац": "\n\n",
        "точка": ".",
        "запятая": ",",
        "вопросительный знак": "?",
        "восклицательный знак": "!",
        "пробел": " ",
    }
    replacement = transforms.get(text.casefold().rstrip(".,!? "), text)
    if replacement != text:
        return replacement
    return text + " "


def wants_screen_read(text: str) -> bool:
    return bool(SCREEN_READ.search(strip_wake_name(text)))


def discord_mic_visual_mode(text: str) -> str | None:
    """A spoken GUI-button action is NEVER a Discord global shortcut.

    An explicit button press does not require the user to also say "take a
    screenshot": inspection is how LuxAI locates real on-screen controls.
    Return the desired post-action state, not an arbitrary key sequence.
    """
    phrase = strip_wake_name(text).casefold().strip()
    if not 14 <= len(phrase) <= 320 or not DISCORD_MIC.search(phrase):
        return None
    if re.search(
        r"\b(?:отправ\w*|напиши|send|trimite|удали|delete|сообщени\w*)\b",
        phrase,
    ):
        return None
    button = re.search(
        r"(?:\bкнопк\w*|\bзначок\w*|\bиконк\w*|"
        r"\bbutton\b|\bicon\b)",
        phrase,
    )
    pressing = re.search(
        r"(?:нажм\w*|нажать|нажми|клик\w*|щёлк\w*|"
        r"щелк\w*|click|apasă|apasa)",
        phrase,
    )
    if not button or not pressing:
        return None
    if re.search(
        r"\b(?:чтобы|для\s+того\s+чтобы)\s+"
        r"(?:его\s+)?(?:включ\w*|размут\w*|активир\w*)",
        phrase,
    ):
        return "unmute"
    if re.search(
        r"\b(?:чтобы|для\s+того\s+чтобы)\s+"
        r"(?:его\s+)?(?:выключ\w*|отключ\w*|заглуш\w*|замут\w*)",
        phrase,
    ) or DISCORD_MUTE.search(phrase):
        return "mute"
    return "toggle"


def wants_discord_mic_visual_click(text: str) -> bool:
    return discord_mic_visual_mode(text) is not None


def wants_discord_mic_mute(text: str) -> bool:
    """Legacy keyboard shortcut ONLY for requests with no GUI button press."""
    if wants_discord_mic_visual_click(text):
        return False
    phrase = strip_wake_name(text)
    return bool(DISCORD_MIC.search(phrase) and DISCORD_MUTE.search(phrase))


def read_screen_locally(tesseract_path="") -> str:
    """Take a real screenshot, run local Tesseract OCR, never upload it."""
    from luxai.screen import capture_screen, read_screen_text
    picture = capture_screen()
    try:
        actual = read_screen_text(picture, tesseract_path=tesseract_path)
    except Exception as exc:
        reason = str(exc)
        if (
            "tesseract" in reason.casefold()
            or "ocr" in reason.casefold()
            or isinstance(exc, FileNotFoundError)
        ):
            return (
                "Не удалось прочитать экран: встроенный Tesseract OCR "
                "не готов. " + reason[:180] + " "
                "Проверьте интернет и статус автоустановки в "
                "Настройки → Система → Встроенный Tesseract OCR "
                "или повторите Update.bat."
            )
        return f"Не удалось прочитать экран: {type(exc).__name__}: {reason[:150]}"
    text = " ".join(str(actual).split())
    if not text:
        return (
            "Снимок экрана сделан, но локальное распознавание не нашло "
            "читаемого текста. Анализ картинок без текста пока недоступен."
        )
    return "Прочитал на экране: " + text[:1000]


def toggle_discord_microphone(confirm=None) -> str:
    """Send official Discord toggle mute shortcut; cannot determine mic state.

    A toggle is not an idempotent mute. Ask for approval with clear wording
    and avoid claiming microphone is disabled when we cannot read its state.
    """
    import sys
    if sys.platform != "win32":
        return "Управление микрофоном Discord доступно только на Windows."
    from luxai.windows_control import running_pids
    if not running_pids("discord"):
        return "Discord сейчас не запущен. Ничего не переключал."
    note = (
        "Discord: Ctrl+Shift+M переключит микрофон. "
        "Если он уже выключен, сочетание включит его. "
        "Продолжить?"
    )
    if confirm is None or not confirm("⚠ " + note):
        return "Переключение микрофона Discord отменено."
    try:
        import pyautogui
        pyautogui.hotkey("ctrl", "shift", "m", interval=0.1)
    except Exception as exc:
        return f"Не удалось отправить сочетание Discord: {exc}"
    return (
        "Отправил Discord Ctrl+Shift+M. Это переключатель микрофона, "
        "а не гарантированная команда «выключить». "
        "Проверьте значок микрофона в Discord."
    )
