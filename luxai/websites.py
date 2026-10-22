"""Open a user-requested public website in the default browser.

All URLs are constructed locally and restricted to HTTPS public domain names.
The web planner may name a site, but never choose file/javascript/localhost
URLs or inject command-line flags. Returning "dispatched" does not establish
that the browser finished loading a page.
"""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit
import webbrowser

from luxai.fast_intents import strip_wake_name, has_launch_verb

SITES = {
    # Age-restricted websites are ordinary HTTPS destinations, not an
    # automatic reason to refuse a navigation request. The user remains
    # responsible for satisfying site age requirements.
    "pornhub": "https://www.pornhub.com/",
    "pornhub.com": "https://www.pornhub.com/",
    "порнхаб": "https://www.pornhub.com/",
    "порнохаб": "https://www.pornhub.com/",
    "порно-хаб": "https://www.pornhub.com/",
    "порно-хам": "https://www.pornhub.com/",
    "порно хам": "https://www.pornhub.com/",
    "порно хаб": "https://www.pornhub.com/",
    "порн хам": "https://www.pornhub.com/",
    "порнхаб": "https://www.pornhub.com/",
    "youtube": "https://www.youtube.com/",
    "ютуб": "https://www.youtube.com/",
    "ютубе": "https://www.youtube.com/",
    "ютюб": "https://www.youtube.com/",
    "ю туб": "https://www.youtube.com/",
    "youtube.com": "https://www.youtube.com/",
    "google": "https://www.google.com/",
    "гугл": "https://www.google.com/",
    "google.com": "https://www.google.com/",
    "github": "https://github.com/",
    "гитхаб": "https://github.com/",
    "википедия": "https://ru.wikipedia.org/",
    "wikipedia": "https://www.wikipedia.org/",
    "twitch": "https://www.twitch.tv/",
    "твич": "https://www.twitch.tv/",
    "discord": "https://discord.com/app",
    "дискорд": "https://discord.com/app",
    "telegram": "https://web.telegram.org/",
    "телеграм": "https://web.telegram.org/",
    "instagram": "https://www.instagram.com/",
    "инстаграм": "https://www.instagram.com/",
    "tiktok": "https://www.tiktok.com/",
    "тикток": "https://www.tiktok.com/",
    "reddit": "https://www.reddit.com/",
    "реддит": "https://www.reddit.com/",
    "chatgpt": "https://chatgpt.com/",
    "чат гпт": "https://chatgpt.com/",
    "spotify": "https://open.spotify.com/",
    "спотифай": "https://open.spotify.com/",
    "netflix": "https://www.netflix.com/",
    "нетфликс": "https://www.netflix.com/",
    "vk": "https://vk.com/",
    "вконтакте": "https://vk.com/",
    "yandex": "https://ya.ru/",
    "яндекс": "https://ya.ru/",
    "фейсбук": "https://www.facebook.com/",
    "facebook": "https://www.facebook.com/",
    "linkedin": "https://www.linkedin.com/",
    "линкедин": "https://www.linkedin.com/",
    "x": "https://x.com/",
    "twitter": "https://x.com/",
    "твиттер": "https://x.com/",
}

SITE_MARKER = re.compile(
    r"\b(?:сайт|сайте|сайтик|браузер|браузере|браузера|"
    r"site|website|browser|browserul|бразуере|браузере)\b",
    re.I,
)
LAUNCH_START = re.compile(
    r"^\s*(?:открой|откроет|откроешь|открывай|открыть|откройте|открой-ка|"
    r"запусти|запустить|open|launch|deschide|porneste|pornește)\b",
    re.I,
)
SEPARATORS = re.compile(
    r"\b(?:пожалуйста|мне|сайт|сайте|сайтик|в|во|через|"
    r"браузере|браузер|браузера|браузером|браузере|"
    r"web|website|site|browser|the|in|în|on|my|"
    r"вкладке|новую|новой|новую\s+вкладку)\b",
    re.I,
)


def website_name_from_speech(text: str) -> str | None:
    spoken = strip_wake_name(text).strip().casefold()
    if not LAUNCH_START.match(spoken):
        return None
    spoken = LAUNCH_START.sub("", spoken, count=1).strip(" \t.,!?")
    if not spoken or spoken in {"браузер", "browser", "браузер по умолчанию"}:
        return None
    tagged = bool(SITE_MARKER.search(spoken))
    site = SEPARATORS.sub(" ", spoken)
    # Colons are significant in a spoken HTTPS URL. Only strip punctuation
    # from regular site names, not from an explicit https:// domain.
    if "https://" not in site:
        site = re.sub(r"[,!?:]+", " ", site)
    site = " ".join(site.strip(" \t.,!?").split())
    if site in {"discord", "дискорд", "telegram", "телеграм", "spotify", "спотифай"} and not tagged:
        return None  # desktop app by default; website only with browser/site
    if site in SITES:
        return site
    # Any public FQDN can be opened when specifically dictated. Bare names
    # not in SITES require explicit website context to avoid hijacking an
    # "open [installed desktop app]" command.
    if site.startswith("https://") and len(site) <= 225:
        return site
    if "." in site and re.fullmatch(r"[\w.-]{4,140}", site):
        return site
    if tagged and re.fullmatch(r"[\w \-]{2,55}", site):
        return site
    return None


def normalize_public_website(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError("Нужно название сайта или HTTPS-адрес.")
    cleaned = " ".join(name.strip().casefold().split())
    if len(cleaned) > 250 or not cleaned:
        raise ValueError("Слишком длинное или пустое название сайта.")
    if cleaned in SITES:
        return SITES[cleaned]
    if cleaned.startswith("http://"):
        raise ValueError("Открывать можно только HTTPS-сайты.")
    raw = cleaned if "://" in cleaned else "https://" + cleaned
    split = urlsplit(raw)
    hostname = split.hostname
    if split.scheme != "https" or not hostname or split.username or split.password:
        raise ValueError("Разрешены только обычные публичные HTTPS-сайты.")
    if split.port not in (None, 443) or split.fragment:
        raise ValueError("Необычный порт или фрагмент в адресе сайта.")
    if not re.fullmatch(r"[a-z0-9.-]{3,200}", hostname):
        raise ValueError("Неверное имя сайта.")
    if hostname.endswith((".local", ".internal", ".localhost", ".test")) or hostname == "localhost":
        raise ValueError("Локальные адреса не открываются по команде AI.")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError("Укажите публичный адрес сайта, а не IP.")
    if "." not in hostname or any(not x for x in hostname.split(".")):
        raise ValueError("Неизвестное название сайта.")
    if not re.fullmatch(r"/[a-z0-9_./~%+-]*|", split.path) or split.query:
        # Only simple web paths, never special schemes or JS payloads.
        raise ValueError("В адресе недопустимые параметры.")
    components = [chunk for chunk in split.path.casefold().split("/") if chunk]
    if any(chunk in (".", "..", "%2e", "%2e%2e", "%2e.", ".%2e") for chunk in components):
        # URL parameters are intentionally not generated by the AI planner.
        raise ValueError("В адресе недопустимые параметры.")
    return urlunsplit(("https", hostname, split.path or "/", "", ""))


def website_plan(text: str) -> dict | None:
    name = website_name_from_speech(text)
    if name is None:
        return None
    try:
        url = normalize_public_website(name)
    except ValueError:
        # Unknown names are handled by Gemini, not guessed as domains.
        return None
    return {"action": "open_site", "target": url, "reply": ""}


def open_website(target: str) -> tuple[bool, str]:
    try:
        url = normalize_public_website(target)
    except ValueError as exc:
        return False, f"Не удалось распознать сайт: {exc}"
    try:
        requested = webbrowser.open(url, new=2)
    except Exception as exc:
        return False, f"Браузер не смог открыть {url}: {exc}"
    if not requested:
        return False, f"Windows не подтвердил передачу ссылки браузеру: {url}"
    return True, f"Отправил браузеру адрес {url}. Проверьте, загрузилась ли страница."
