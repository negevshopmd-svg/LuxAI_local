"""Is this phrase already a complete command? (0.4.4c, «early answer»)

The listener waits for a pause after speech (2.3 s by default) so a long sentence is never cut in the middle.
For a short, complete command that wait is pure delay: the listener now recognises the phrase at the first
short pause and asks ``complete(text)``. Yes → Jarvis acts at once; no → it waits the whole pause as before.

Only text checks that are instant and touch nothing are used here (this runs on the microphone thread): a
saved command of the library, and the deterministic local intents (volume, a named game, a website, an app,
a timer / alarm / reminder, Discord microphone). A question for the AI, a dictated message or anything with
«and then» always waits for the whole pause — the user may still be speaking.
"""
from __future__ import annotations

import re

# Words that mean the sentence goes on (a chain, a message, a question for the AI): never cut early.
_CONTINUES = re.compile(r"(?:\b(?:и затем|потом|после этого|а также|and then|then|apoi|după aceea|напиши|"
                        r"напечатай|отправь|сообщение|write|send|message|scrie|trimite|mesaj|почему|объясни|"
                        r"расскажи|why|explain|tell me|de ce|explică)\b|[,;:]\s*$)", re.I)
MAX_WORDS = 9  # longer phrases are sentences, not quick commands


def _strip_name(text: str, prefix: str) -> str:
    value = " ".join(str(text or "").split()).strip(" .!?")
    names = {name for name in (prefix, "Jarvis", "Джарвис", "Жарвис") if name}
    pattern = r"^(?:%s)[,\s]+" % "|".join(re.escape(name) for name in names)
    return re.sub(pattern, "", value, flags=re.I)


def detectors():
    from luxai.quick_actions import parse as quick_action
    from luxai.steam_games import local_game_request
    from luxai.task_intents import direct_app_request, system_volume_request
    from luxai.timers import parse_request
    from luxai.voice_desktop import wants_discord_mic_mute
    from luxai.websites import website_plan
    from luxai.task_intents import screenshot_request
    from luxai.weather_service import is_weather_question
    return (quick_action, system_volume_request, local_game_request, website_plan, direct_app_request, parse_request,
            wants_discord_mic_mute, screenshot_request, is_weather_question)


def complete(text: str, registry=None, prefix: str = "Jarvis", match_options: dict | None = None,
             prefix_required: bool = False) -> bool:
    """True when ``text`` is a whole, known command that can run without waiting for more speech."""
    value = " ".join(str(text or "").split())
    if not value:
        return False
    if prefix_required and not re.match(r"^(?:%s)\b" % re.escape(prefix or "Jarvis"), value, re.I) \
            and not re.match(r"^(?:jarvis|джарвис|жарвис)\b", value, re.I):
        return False  # prefix mode: phrases without the name are ignored anyway — no need to hurry
    command = _strip_name(value, prefix)
    if not command or len(command.split()) > MAX_WORDS or _CONTINUES.search(command):
        return False
    if registry is not None:
        try:
            if registry.match(value, prefix, **(match_options or {})) is not None:
                return True
        except Exception:
            pass
    for detect in detectors():
        try:
            if detect(command):
                return True
        except Exception:
            continue
    return False
