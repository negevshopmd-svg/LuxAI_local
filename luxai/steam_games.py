"""Steam game launcher with safe, exact-name Store lookups.

Never accept a terminal command from an AI. Only a verified integer Steam
app id reaches the operating system's registered steam:// protocol handler.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request


GAMES = {
    "dota2": (570, "Dota 2"),
    "cs2": (730, "Counter-Strike 2"),
    "warthunder": (236390, "War Thunder"),
    "undertale": (391540, "Undertale"),
}

ALIASES = {
    "dota2": ("dota", "dota 2", "дота", "доту", "доты", "дота 2", "доту 2"),
    "cs2": ("cs2", "cs 2", "csgo", "cs:go", "кс2", "кс 2", "контр страйк", "counter strike"),
    "warthunder": (
        "war thunder", "warthunder", "war-thunder", "war tander", "war tunder",
        "war thunder game", "вар тандер", "вартандер", "вар тандр", "вар тандэр", "war-tunder",
    ),
    "undertale": ("undertale", "андертейл", "андертэйл", "андертеил", "андертел", "андертале", "андертейла", "андертэла"),
}

LAUNCH_VERBS = (
    "открой", "открыть", "открывай", "запусти", "запустить", "включи",
    "open", "launch", "start", "run", "play", "deschide", "porneste", "pornește",
)


def _normalized(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKC", text).casefold()
        if ch.isalnum()
    )


def local_game_intent(text: str) -> str | None:
    request = local_game_request(text)
    return request["target"] if request and request["action"] == "launch_game" else None


def mentions_known_game(text: str) -> bool:
    """A routing hint only: a mentioned name never grants launch authority."""
    value = str(text or "").casefold()
    return any(
        re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", value)
        for aliases in ALIASES.values() for alias in aliases
    )


def local_game_request(text: str) -> dict | None:
    """Recognize one complete named-game request, without an API or app scan.

    Do not extract a launch verb from quoted speech, a message body, a how-to
    question, a negative instruction or only the first half of a compound task.
    The known game ID still comes from GAMES, never from the user's words.
    """
    from luxai.fast_intents import command_text
    value = command_text(text).casefold().translate(str.maketrans({
        "ă": "a", "â": "a", "î": "i", "ș": "s", "ț": "t",
    }))
    value = re.sub(r"\s+", " ", value).strip().rstrip(" .!?")
    launch = (
        r"открой|открыть|открывай|откроешь|запусти|запустить|запускай|"
        r"включи|включить|open|launch|start|run|play|deschide(?:-mi)?|deschidea|"
        r"deschizi|porneste|pornesti|lanseaza|lansezi|intra in"
    )
    close = (
        r"закрой|закрыть|закрывай|закроешь|выключи|выключить|останови|"
        r"заверши|close|exit|quit|stop|shut down|inchide(?:-mi)?|inchizi|"
        r"opreste|opresti|iesi din|inchideti"
    )
    prefix = r"(?:(?:пожалуйста|please)\s+)?"
    # Courtesy directly after the action belongs to the request framing.
    # Keep it bounded here: stripping arbitrary middle words could turn a
    # quoted message or a compound goal into a different game command.
    courtesy = r"(?:(?:пожалуйста|please|te rog(?: frumos)?)[,;]?\s+)?"
    article = r"(?:the\s+)?(?:(?:игру|игры|окно(?:\s+игры)?|приложение|(?:game|app|application|window)(?:\s+(?:of|for))?|jocul|joc|fereastra(?:\s+jocului)?)\s+)?"
    platform = r"(?:\s+(?:в стим(?:е)?|в steam|через steam|in steam|on steam|through steam|prin steam|din steam|in steam))?"
    for action, verbs in (("launch_game", launch), ("close_app", close)):
        match = re.fullmatch(prefix + r"(?:" + verbs + r")[\s,:]+" + courtesy + article + r"(.+?)" + platform + r"(?:\s+(?:acum|now|сейчас))?", value)
        if not match:
            continue
        target = match.group(1).strip()
        target = re.sub(r"\s+(?:window|окно)$", "", target)
        # Quotes around the explicitly named game are data, not a second
        # command; the complete action phrase must still have matched above.
        if len(target) >= 2 and (target[0], target[-1]) in {
            ('"', '"'), ("'", "'"), ("«", "»"), ("“", "”"),
        }:
            target = target[1:-1].strip()
        for game, aliases in ALIASES.items():
            if target in {*aliases, GAMES[game][1].casefold()}:
                return {"action": action, "target": game}
    return None


def lookup_steam_game(title: str, timeout: int = 4) -> tuple[int, str] | None:
    """Resolve official Steam app id from the public StoreSearch API.

    Only an exact normalized title match is accepted: the online AI does
    not choose an arbitrary URL, executable or app id.
    """
    query = str(title or "").strip()
    if not query or len(query) > 90 or re.search(r"[\x00-\x1f<>]", query):
        return None
    # Official Steam IDs for a few frequent games remain available offline
    # when StoreSearch is unreachable (including Russian transcriptions).
    normalized_query = _normalized(query)
    for game_key, aliases in ALIASES.items():
        if any(_normalized(alias) == normalized_query for alias in aliases) or _normalized(GAMES[game_key][1]) == normalized_query:
            app_id, name = GAMES[game_key]
            return app_id, name
    qs = urllib.parse.urlencode({"term": query, "l": "english", "cc": "US"})
    request = urllib.request.Request(
        "https://store.steampowered.com/api/storesearch/?" + qs,
        headers={"User-Agent": "JarvisLocalAssistant/2.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=max(2, min(int(timeout), 6))) as response:
            result = json.loads(response.read(256 * 1024))
        for item in result.get("items", [])[:20]:
            app_id = item.get("id")
            name = str(item.get("name", ""))
            if (
                type(app_id) is int and 0 < app_id < 100_000_000
                and _normalized(name) == _normalized(query)
            ):
                return app_id, name
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return None


def launch_steam_game(app_id: int) -> bool:
    if type(app_id) is not int or app_id < 1 or app_id > 100_000_000:
        return False
    uri = f"steam://rungameid/{app_id}"
    try:
        if os.name == "nt":
            os.startfile(uri)
        else:
            return False
        return True
    except (OSError, AttributeError):
        return False
