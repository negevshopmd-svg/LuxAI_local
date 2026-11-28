"""Everyday one-step commands answered on this PC at once (0.4.4c): volume, media keys, the window in front.

Before 0.4.4c no local rule knew «сделай громче», «следующий трек», «пауза» or «закрой окно»: they went to the
AI planner (seconds, internet) although each is one key or one Windows call. ``parse`` recognises only a WHOLE
phrase in ru / ro / en (so «выключи звук в дискорде» stays Discord's), ``run`` does it and says what is true now.
"""
from __future__ import annotations

import re
import sys

STEP = 10  # percent for «louder» / «quieter» without a number
# The patterns accept the usual recognition slips measured in tests/command_bench: a lost first sound
# («Делай тише») and a garbled last word («Следующий тригг»).

_NUM = r"(?:на\s+|by\s+|cu\s+)?(\d{1,3})\s*(?:%|процент\w*|percent|procente?|la\s+sută)?"
_UP = (r"(?:с?делай\s+)?(?:по)?громче|прибавь\s+(?:звук|громкость)|увеличь\s+(?:звук|громкость)|"
       r"(?:turn|make)\s+(?:the\s+)?(?:volume|sound|it)\s+up|(?:volume|sound)\s+up|louder|turn\s+it\s+up|"
       r"(?:dă|da|fă|fa)\s+(?:mai\s+)?tare|mai\s+tare|crește\s+volumul|creste\s+volumul|"
       r"(?:dă|da)\s+volumul\s+mai\s+tare")
_DOWN = (r"(?:с?делай\s+)?(?:по)?тише|убавь\s+(?:звук|громкость)|уменьши\s+(?:звук|громкость)|"
         r"(?:turn|make)\s+(?:the\s+)?(?:volume|sound|it)\s+down|(?:volume|sound)\s+down|quieter|turn\s+it\s+down|"
         r"(?:dă|da|fă|fa)\s+(?:mai\s+)?(?:încet|incet)|mai\s+(?:încet|incet)|scade\s+volumul|"
         r"(?:dă|da)\s+volumul\s+mai\s+(?:încet|incet)")
PHRASES = (
    ("volume_up", re.compile(r"(?:%s)(?:\s+%s)?" % (_UP, _NUM))),
    ("volume_down", re.compile(r"(?:%s)(?:\s+%s)?" % (_DOWN, _NUM))),
    ("mute", re.compile(r"(?:выключи|отключи)\s+(?:весь\s+)?звук|без\s+звука|(?:mute|unmute)(?:\s+(?:the\s+)?(?:sound|pc|computer))?|"
                        r"включи\s+звук|(?:oprește|opreste)\s+sunetul|fără\s+sunet|fara\s+sunet|(?:pornește|porneste)\s+sunetul")),
    ("media_play_pause", re.compile(r"пауза|поставь\s+на\s+паузу|продолжи(?:\s+(?:музыку|воспроизведение|видео))?|"
                                    r"(?:play|pause|resume)(?:\s+(?:the\s+)?(?:music|video|song))?|"
                                    r"pauză|pauza|(?:pune|dă|da)\s+pauză|redă|reda|continuă|continua")),
    ("media_next", re.compile(r"(?:следующ\w+|дальше)\s+(?:тр\w*|песн\w+|видео)|следующий|"
                              r"next(?:\s+(?:track|song|video))?|skip(?:\s+(?:this|the)\s+(?:track|song))?|"
                              r"(?:piesa|melodia)\s+următoare|(?:piesa|melodia)\s+urmatoare|următoarea|urmatoarea")),
    ("media_previous", re.compile(r"(?:предыдущ\w+|прошл\w+)\s+(?:тр\w*|песн\w+|видео)|"
                                  r"previous(?:\s+(?:track|song|video))?|"
                                  r"(?:piesa|melodia)\s+(?:anterioară|anterioara|precedentă|precedenta)")),
    ("win_close", re.compile(r"закрой\s+(?:это\s+|текущее\s+|активное\s+)?окно|close\s+(?:this|the|the\s+current)\s+window|"
                             r"(?:închide|inchide)\s+fereastra(?:\s+(?:asta|activă|activa))?")),
    ("win_minimize", re.compile(r"сверни\s+(?:это\s+|текущее\s+|активное\s+)?окно|minimi[sz]e\s+(?:this|the)\s+window|"
                                r"minimizează\s+fereastra|minimizeaza\s+fereastra")),
    ("win_maximize", re.compile(r"разверни\s+(?:это\s+|текущее\s+|активное\s+)?окно(?:\s+на\s+весь\s+экран)?|"
                                r"maximi[sz]e\s+(?:this|the)\s+window|maximizează\s+fereastra|maximizeaza\s+fereastra")),
    ("show_desktop", re.compile(r"сверни\s+все\s+окна|покажи\s+рабочий\s+стол|show\s+(?:the\s+)?desktop|"
                                r"minimi[sz]e\s+(?:all|everything)|minimizează\s+tot|minimizeaza\s+tot|"
                                r"arată\s+desktopul|arata\s+desktopul")),
)
_NAME = re.compile(r"^(?:jarvis|джарвис|жарвис)[,\s]+", re.I)
_POLITE = re.compile(r"\s*(?:,?\s*(?:пожалуйста|please|te\s+rog|плиз))$|^(?:пожалуйста|please|te\s+rog)\s+", re.I)


def parse(text: str) -> dict | None:
    """{"action": ..., "step": percent} when the WHOLE phrase is one of these commands, else None."""
    value = " ".join(str(text or "").casefold().replace("ё", "е").split()).strip(" .!?")
    value = _POLITE.sub("", _NAME.sub("", value)).strip(" .!?,")
    if not value or len(value) > 60:
        return None
    for action, pattern in PHRASES:
        match = pattern.fullmatch(value)
        if match:
            result = {"action": action}
            if action in ("volume_up", "volume_down"):
                number = next((group for group in match.groups() if group), None)
                result["step"] = max(1, min(100, int(number))) if number else STEP
            return result
    return None


WORDS = {
    "volume": ("Громкость {n}%.", "Volume {n}%.", "Volum {n}%."),
    "muted": ("Звук выключен.", "Sound muted.", "Sunet oprit."),
    "unmuted": ("Звук включён.", "Sound on.", "Sunet pornit."),
    "media_play_pause": ("Пауза / воспроизведение.", "Play / pause.", "Pauză / redare."),
    "media_next": ("Следующий трек.", "Next track.", "Piesa următoare."),
    "media_previous": ("Предыдущий трек.", "Previous track.", "Piesa anterioară."),
    "win_close": ("Закрываю окно.", "Closing the window.", "Închid fereastra."),
    "win_minimize": ("Окно свёрнуто.", "Window minimised.", "Fereastra minimizată."),
    "win_maximize": ("Окно развёрнуто.", "Window maximised.", "Fereastra maximizată."),
    "show_desktop": ("Рабочий стол.", "Desktop.", "Desktop."),
    "no_window": ("Не вижу окна, к которому это относится.", "I do not see the window this is for.",
                  "Nu văd fereastra la care se referă."),
    "own_window": ("Это окно самого Jarvis — его закрывают крестиком.", "This is Jarvis' own window — close it with its ✕.",
                   "Aceasta e fereastra lui Jarvis — închide-o din ✕."),
    "failed": ("Не получилось: {error}", "That did not work: {error}", "N-a mers: {error}"),
}
MEDIA_KEYS = {"media_play_pause": 0xB3, "media_next": 0xB0, "media_previous": 0xB1}


def word(key: str, language: str, **values) -> str:
    return WORDS[key][{"ru": 0, "en": 1, "ro": 2}.get(language, 0)].format(**values)


def run(command: dict, language: str, hwnd: int = 0) -> str:
    """Do it now and say what is true (the real volume read back, not the intended one)."""
    action = command["action"]
    try:
        if action in ("volume_up", "volume_down"):
            from luxai.windows_volume import windows_volume
            delta = command.get("step", STEP) * (1 if action == "volume_up" else -1)
            return word("volume", language, n=windows_volume(max(0, min(100, windows_volume() + delta))))
        if action == "mute":
            return word("muted" if toggle_mute() else "unmuted", language)
        if action in MEDIA_KEYS:
            from luxai.extensions_runtime import press_virtual_key
            press_virtual_key(MEDIA_KEYS[action])
            return word(action, language)
        if action == "show_desktop":
            from luxai.keys import press
            press("win", "d")
            return word(action, language)
        from luxai import action_circle as ac
        message = ac.window_action(action, int(hwnd or 0)) if hwnd else "no_window"
        return word(message or action, language) if (message or action) in WORDS else word(action, language)
    except Exception as error:  # a missing audio device, a closed window…
        return word("failed", language, error=type(error).__name__)


def toggle_mute() -> bool:
    """Mute / unmute the default output; True when it is muted now."""
    if sys.platform != "win32":
        raise OSError("Windows only")
    from luxai.windows_volume import _endpoint_volume
    endpoint = _endpoint_volume()
    endpoint.SetMute(0 if endpoint.GetMute() else 1, None)
    return bool(endpoint.GetMute())
