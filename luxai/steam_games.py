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
    "warthunder": ("war thunder", "warthunder", "вар тандер", "вартандер", "вар тандр", "war-tunder"),
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
    text = text.casefold()
    if not any(re.search(r"(?<!\w)" + re.escape(verb) + r"(?!\w)", text) for verb in LAUNCH_VERBS):
        return None
    for game, aliases in ALIASES.items():
        for alias in aliases:
            if re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text):
                return game
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
