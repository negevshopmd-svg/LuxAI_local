"""Deterministic Russian, Romanian and English desktop voice intents.

Dictation is an explicit local mode: speech chunks are typed only into the
focused *other* application, never into Jarvis or a random app while the UI
is foreground. No transcribed text is sent to Gemini during dictation.
"""
from __future__ import annotations

import re

from luxai.fast_intents import command_text, strip_wake_name

DICTATION_START = re.compile(
    r"(?:\b(?:начни|включи|запусти)\s+(?:голосов\w+\s+)?диктовк\w*"
    r"|\b(?:могу|буду)\s+(?:тебе\s+)?диктовать"
    r"|\b(?:будешь|начни)\s+писать\b"
    r"|\b(?:записывай|запиши)\s+(?:всё\s+)?(?:что\s+)?(?:я\s+)?(?:говорю|диктую)"
    r"|\b(?:start|begin|enable|turn\s+on)\s+(?:the\s+)?(?:voice\s+)?(?:dictation|voice\s+typing)(?:\s+mode)?"
    r"|\b(?:start|begin)\s+(?:taking\s+)?dictation"
    r"|\b(?:începe|incepe|pornește|porneste|activează|activeaza)\s+(?:modul\s+(?:de\s+)?)?(?:dictarea|dictare|scrierea\s+vocală|scrierea\s+vocala)"
    r"|\b(?:scrie|notează|noteaza)\s+(?:tot\s+)?ce\s+(?:îți\s+|iti\s+)?(?:spun|dictez))",
    re.I,
)
DICTATION_STOP = {
    "стоп", "остановись", "останови диктовку", "закончи диктовку",
    "выключи диктовку", "хватит", "stop", "stop dictation",
    "oprește dictarea", "opreste dictarea",
    "stop dictating", "end dictation", "finish dictation", "disable dictation",
    "turn off dictation", "stop voice typing", "end voice typing",
    "încheie dictarea", "incheie dictarea", "termină dictarea", "termina dictarea",
    "oprește modul de dictare", "opreste modul de dictare", "dezactivează dictarea",
    "dezactiveaza dictarea", "oprește scrierea vocală", "opreste scrierea vocala",
}
SCREEN_READ = re.compile(
    r"(?:"
    r"\b(?:прочитай|прочитать|прочитаешь|прочесть|прочти|посмотри|покажи|увидь)\b.{0,55}"
    r"\b(?:экран\w*|экране|монитор\w*|написано|текст)\b"
    r"|\b(?:что|какой\s+текст)\b.{0,35}\b(?:на\s+экране|видно\s+на\s+экране)"
    r"|\b(?:видишь|смотришь)\s+(?:мой\s+)?экран"
    r"|\b(?:read|analyze|see|look\s+at|inspect)\s+(?:(?:the|my)\s+)?(?:text\s+(?:on|from)\s+(?:(?:the|my)\s+)?)?screen\b"
    r"|\b(?:what(?:'s|\s+is)?|tell\s+me\s+what(?:'s|\s+is)?)\s+(?:shown\s+|written\s+)?on\s+(?:(?:the|my)\s+)?screen\b"
    r"|\b(?:citește|citeste|citești|citesti|analizează|analizeaza|arată-mi|arata-mi|privește|priveste|uită-te|uita-te)\b.{0,55}\b(?:ecran\w*|monitor\w*)\b"
    r"|\b(?:ce\s+(?:scrie|apare|vezi|este)|spune-mi\s+ce\s+(?:scrie|apare|vezi))\b.{0,35}\b(?:pe\s+ecran|pe\s+monitor)\b"
    r")",
    re.I,
)
DISCORD_MIC = re.compile(
    r"(?:(?<!\w)(?:дискорд\w*|discord)(?!\w).{0,85}(?<!\w)(?:микрофон\w*|микроф|microphone|mic|microfon\w*)(?!\w)"
    r"|(?<!\w)(?:микрофон\w*|микроф|microphone|mic|microfon\w*)(?!\w).{0,85}(?<!\w)(?:дискорд\w*|discord)(?!\w))",
    re.I,
)
DISCORD_MUTE = re.compile(
    # Whisper frequently produces "выключу" instead of "выключи".
    r"\b(?:выключ\w*|отключ\w*|заглуш\w*|замьют\w*|замут\w*|mute|"
    r"приглуш\w*|закр\w*\s+(?:(?:мой|его)\s+)?микрофон\w*|"
    r"turn\s+off|disable|opre(?:ște|ste|ști|sti)|dezactiv(?:eaz[ăa]|ezi|a)|închide|inchide|închizi|inchizi)\b",
    re.I,
)
DISCORD_UNMUTE = re.compile(
    r"\b(?:включ\w*|размут\w*|размьют\w*|unmute|enable|turn\s+on|porne(?:ște|ste|ști|sti)|activ(?:eaz[ăa]|ezi|a)|deschide|deschizi)\b",
    re.I,
)
DISCORD_MESSAGE_OPERATION = re.compile(
    r"\b(?:отправ\w*|напиш\w*|напис\w*|send|write|message|text|scrie(?:-i)?|scriei|trimite(?:-i)?|удали|delete|сообщени\w*)\b",
    re.I,
)


def _mic_non_action_context(phrase):
    if re.match(r"(?:как|how|cum|объясни|поясни|explică|explica|explain)\b", phrase):
        return True
    if re.search(r"\b(?:как\s+(?:(?:мне|можно)\s+)?(?:выключ\w*|включ\w*|отключ\w*|закр\w*|нач\w*|прочит\w*)|how\s+(?:can\s+i|do\s+i|to|should\s+i)|cum\s+(?:pot|se|s[ăa]))\b", phrase):
        return True
    return bool(re.search(
        r"\b(?:не\s+(?:(?:надо|нужно)\s+)?(?:закр\w*|выключ\w*|отключ\w*|включ\w*|размут\w*|размьют\w*|замут\w*|заглуш\w*|наж\w*|клик\w*|нач\w*|запис\w*|прочит\w*|посмотр\w*)|"
        r"(?:do\s+not|don['’]?t|never)\s+(?:mute|unmute|disable|enable|turn|click|press|read|start|begin|look|inspect)|"
        r"nu(?:-mi|-l)?\s+(?:(?:vreau|trebuie)\s+(?:s[ăa]\s+)?)?(?:opri\w*|opre\w*|porni\w*|porne\w*|activ\w*|dezactiv\w*|închid\w*|inchid\w*|deschid\w*|scoat\w*|sco[țt]\w*|ap[ăa]s\w*|încep\w*|incep\w*|citi\w*|cite\w*))\b",
        phrase,
    ))


def is_dictation_start(text: str) -> bool:
    phrase = command_text(text).casefold()
    if _mic_non_action_context(phrase):
        return False
    if DISCORD_MESSAGE_OPERATION.search(phrase) and not re.fullmatch(
        r"(?:scrie|notează|noteaza)\s+(?:tot\s+)?ce\s+(?:îți\s+|iti\s+)?(?:spun|dictez)[.!?]*", phrase,
    ):
        return False
    return bool(DICTATION_START.search(phrase))


def is_dictation_stop(text: str) -> bool:
    clean = command_text(text).casefold()
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
        "new line": "\n", "newline": "\n", "line break": "\n",
        "new paragraph": "\n\n", "period": ".", "full stop": ".",
        "comma": ",", "question mark": "?", "exclamation mark": "!", "space": " ",
        "linie nouă": "\n", "linie noua": "\n", "rând nou": "\n", "rand nou": "\n",
        "paragraf nou": "\n\n", "punct": ".", "virgulă": ",", "virgula": ",",
        "semnul întrebării": "?", "semnul intrebarii": "?",
        "semnul exclamării": "!", "semnul exclamarii": "!", "spațiu": " ", "spatiu": " ",
    }
    replacement = transforms.get(text.casefold().rstrip(".,!? "), text)
    if replacement != text:
        return replacement
    return text + " "


def wants_screen_read(text: str) -> bool:
    phrase = command_text(text).casefold()
    if _mic_non_action_context(phrase) or re.match(
        r"(?:scrie(?:-i)?|trimite(?:-i)?|send|write|message|напиш\w*|отправ\w*)\b", phrase,
    ):
        return False
    return bool(SCREEN_READ.search(phrase))


def discord_mic_visual_mode(text: str) -> str | None:
    """A spoken GUI-button action is NEVER a Discord global shortcut.

    An explicit button press does not require the user to also say "take a
    screenshot": inspection is how LuxAI locates real on-screen controls.
    Return the desired post-action state, not an arbitrary key sequence.
    """
    phrase = command_text(text).casefold().strip()
    if not 14 <= len(phrase) <= 320 or not DISCORD_MIC.search(phrase):
        return None
    if DISCORD_MESSAGE_OPERATION.search(phrase):
        return None
    if _mic_non_action_context(phrase):
        return None
    button = re.search(
        r"(?:\bкнопк\w*|\bзнач(?:ок|к)\w*|\bиконк\w*|"
        r"\bbutton\b|\bicon\b|\bbuton\w*|\bpictogram\w*|\biconi[țt]\w*)",
        phrase,
    )
    pressing = re.search(
        r"\b(?:нажм\w*|нажим\w*|нажать|нажми|клик\w*|щёлк\w*|"
        r"щелк\w*|click|press|tap|apasă|apasa|apeși|apesi|d[ăa]\s+(?:un\s+)?(?:clic|click))\b",
        phrase,
    )
    direct_mic = re.search(
        r"(?:на\s+микрофон\w*|по\s+микрофон\w*|"
        r"на\s+микроф\w*|pe\s+microfon\w*|on\s+(?:(?:the|my)\s+)?(?:mic|microphone)\b|"
        r"\b(?:click|tap|press|apasă|apasa|apeși|apesi)\s+(?:on\s+|pe\s+)?"
        r"(?:(?:the|my|discord(?:'s)?)\s+)*(?:microphone|mic|microfon\w*)\b)", phrase,
    )
    explicit_shortcut = re.search(
        r"(?:ctrl\s*\+\s*shift\s*\+\s*m|"
        r"контр[о]?л\w*\s+шифт\w*\s+м)", phrase,
    )
    if explicit_shortcut:
        return None
    remove_mute = re.search(r"\b(?:scoate|scoți|scoti)\b.{0,45}\b(?:de\s+pe|din)\s+mute\b", phrase)
    if remove_mute and not pressing:
        return "unmute"
    if (button or direct_mic) and pressing:
        pass
    elif not pressing and DISCORD_MUTE.search(phrase):
        # "Выключи микрофон" describes a desired STATE; a shortcut
        # alone is a toggle and can accidentally enable it.
        return "mute"
    elif not pressing and DISCORD_UNMUTE.search(phrase):
        return "unmute"
    else:
        return None
    if re.search(
        r"\b(?:(?:чтобы|для\s+того\s+чтобы)\s+(?:его\s+)?(?:включ\w*|размут\w*|активир\w*)|"
        r"(?:ca\s+s[ăa](?:-l)?|pentru\s+a(?:-l)?)\s+(?:îl\s+|il\s+)?(?:porni\w*|porne\w*|activ\w*|deschid\w*)|"
        r"to\s+(?:unmute|enable|turn\s+on))\b",
        phrase,
    ) or remove_mute:
        return "unmute"
    if re.search(
        r"\b(?:(?:чтобы|для\s+того\s+чтобы)\s+(?:его\s+)?(?:выключ\w*|отключ\w*|заглуш\w*|замут\w*)|"
        r"(?:ca\s+s[ăa](?:-l)?|pentru\s+a(?:-l)?)\s+(?:îl\s+|il\s+)?(?:opri\w*|opre\w*|dezactiv\w*|închid\w*|inchid\w*)|"
        r"to\s+(?:mute|disable|turn\s+off))\b",
        phrase,
    ) or DISCORD_MUTE.search(phrase):
        return "mute"
    return "unmute" if DISCORD_UNMUTE.search(phrase) else "toggle"


def wants_discord_mic_visual_click(text: str) -> bool:
    return discord_mic_visual_mode(text) is not None


def wants_discord_mic_mute(text: str) -> bool:
    """Legacy keyboard shortcut ONLY for requests with no GUI button press."""
    if wants_discord_mic_visual_click(text):
        return False
    phrase = command_text(text).casefold().strip()
    if DISCORD_MESSAGE_OPERATION.search(phrase) or _mic_non_action_context(phrase):
        return False
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
