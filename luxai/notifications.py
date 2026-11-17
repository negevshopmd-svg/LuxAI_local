"""Notification reader (0.4.1e): new Windows toasts, cleaned for speech.

Windows keeps the current user's notifications in
``%LOCALAPPDATA%\\Microsoft\\Windows\\Notifications\\wpndatabase.db``. The
watcher opens it READ-ONLY, remembers the newest row at start (old
notifications are never read) and returns only toasts that arrive later.
Nothing is written, logged or sent anywhere; text only goes to local TTS.
"""
from __future__ import annotations

import os
import re
import sqlite3
from contextlib import closing
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

DB_PATH = Path(os.path.expandvars(r"%LOCALAPPDATA%")) / "Microsoft" / "Windows" / "Notifications" / "wpndatabase.db"

KNOWN_APPS = {
    "telegram": "Telegram", "discord": "Discord", "whatsapp": "WhatsApp", "viber": "Viber", "signal": "Signal",
    "skype": "Skype", "teams": "Teams", "slack": "Slack", "zoom": "Zoom", "outlook": "Outlook", "thunderbird": "Thunderbird",
    "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox", "opera": "Opera", "yandex": "Яндекс", "steam": "Steam",
    "spotify": "Spotify", "vk": "VK", "instagram": "Instagram", "messenger": "Messenger", "mail": "Почта",
}
# Our own tray notices and system noise are never read aloud.
IGNORED_APP_PARTS = ("python", "jarvis", "luxai", "windows.defender", "securityandmaintenance", "windows.systemtoast",
                     "microsoft.explorer.notification", "screensketch", "windows.immersivecontrolpanel",
                     "windows.securitycenter", "windows.shell", "microsoft.windows.")


def app_name(primary_id: str) -> str:
    """Friendly app name from an AppUserModelID or an executable path."""
    raw = str(primary_id or "")
    lowered = raw.casefold()
    for key, name in KNOWN_APPS.items():
        if key in lowered:
            return name
    package, _, entry = raw.partition("!")
    if entry and (entry.casefold() in ("app", "application", "main") or "." in package):
        # Store-app ids: «OpenAI.Codex_2p2nqsd0c76g0!App» → «Codex».
        raw = re.sub(r"_[a-z0-9]{10,16}$", "", package)
    if re.fullmatch(r"\{[0-9A-Fa-f-]{36}\}", raw.strip()):
        return ""  # an unnamed GUID cannot be spoken meaningfully
    tail = re.split(r"[\\/!]", raw)[-1] or raw
    tail = re.sub(r"\.exe$", "", tail, flags=re.I)
    parts = [part for part in re.split(r"[._]", tail) if part and not re.fullmatch(r"[0-9a-f]{8,}|\d+|com|org|net|app|desktop", part, re.I)]
    name = parts[-1] if parts else tail
    return name[:1].upper() + name[1:40] if name else ""


def is_ignored_app(primary_id: str) -> bool:
    lowered = str(primary_id or "").casefold()
    return any(part in lowered for part in IGNORED_APP_PARTS)


def toast_texts(payload) -> list[str]:
    """Visible <text> lines of a toast XML payload."""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    payload = str(payload or "").strip().lstrip("﻿")
    if not payload.startswith("<"):
        return []
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return []
    texts = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == "text":
            if (element.attrib.get("placement") or "") == "attribution":
                continue
            value = " ".join("".join(element.itertext()).split())
            if value:
                texts.append(value)
    return texts[:4]


_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
# An optional "код:" in front is replaced together with the code itself.
_CODE = re.compile(r"(?:(?<![\w-])(?:ваш\s+)?(?:код\w*|code|cod\w*)(?:\s+(?:подтверждения|входа|verification|de\s+verificare))?"
                   r"[\s:—-]*)?(?<![\w-])(?:\d[\d\s-]{3,10}\d|[A-Z0-9]{6,12})(?![\w-])", re.I)


WORDS = {
    "link": {"ru": "ссылка", "en": "link", "ro": "link"},
    "code": {"ru": "пришёл код", "en": "a code arrived", "ro": "a venit un cod"},
}


def clean_for_speech(text: str, *, skip_codes: bool = True, skip_links: bool = True, limit: int = 200,
                     language: str = "ru") -> str:
    value = " ".join(str(text or "").split())
    if skip_links:
        value = _URL.sub(WORDS["link"].get(language, "ссылка"), value)
        value = _EMAIL.sub("", value)
    if skip_codes:
        code_word = WORDS["code"].get(language, "пришёл код")
        found = {"labelled": False, "bare": False}

        def code(match):
            matched = match.group(0)
            labelled = re.match(r"(?:ваш\s+)?(?:код|code|cod)", matched, re.I) is not None
            if sum(ch.isdigit() for ch in matched) < (1 if labelled else 4):
                return matched
            if labelled and not found["labelled"]:
                found["labelled"] = True
                return code_word  # «Ваш код 4829» → «пришёл код»
            found["bare"] = True
            return ""  # a bare number is dropped; the sentence gets «пришёл код» at the end

        value = _CODE.sub(code, value)
        if found["bare"] and not found["labelled"]:
            value = value.rstrip(" ,.;:") + ", " + code_word
    value = re.sub(r"\s+([,.!?:;])", r"\1", value)
    value = re.sub(r"(?:[,:;—-]\s*){2,}", ", ", value)
    value = " ".join(value.split()).strip(" ,:;—-")
    if len(value) > limit:
        value = value[:limit].rsplit(" ", 1)[0] + "…"
    return value


def compose(app: str, texts: list[str], *, say_app=True, mode="text", skip_codes=True, skip_links=True,
            limit=200, language="ru") -> str:
    """«Telegram: Мама — купи хлеба». mode: sender | text (first body line) | full."""
    texts = [clean_for_speech(item, skip_codes=skip_codes, skip_links=skip_links, limit=limit, language=language)
             for item in texts]
    texts = [item for item in texts if item]
    if not texts:
        return ""
    title = texts[0]
    if mode == "sender":
        body = ""
    elif mode == "full":
        body = " ".join(texts[1:])
    else:
        body = texts[1] if len(texts) > 1 else ""
    if app and title.casefold() == app.casefold() and body:
        title, body = body, ""
    message = f"{title} — {body}" if body else title
    message = clean_for_speech(message, skip_codes=False, limit=limit)
    return f"{app}: {message}" if say_app and app else message


DEFAULT_ON = {"Telegram", "Discord", "WhatsApp", "Viber", "Signal", "Skype", "Teams", "Slack", "Zoom", "Outlook",
              "Thunderbird", "Почта", "Messenger", "VK", "Instagram"}


def parse_rules(value: str) -> dict[str, bool]:
    """«Telegram=1\nChrome=0» → {"Telegram": True, "Chrome": False}."""
    rules = {}
    for line in str(value or "").splitlines():
        name, _, flag = line.partition("=")
        name = name.strip()
        if name:
            rules[name[:40]] = flag.strip() != "0"
    return rules


def format_rules(rules: dict[str, bool]) -> str:
    return "\n".join(f"{name}={1 if on else 0}" for name, on in sorted(rules.items(), key=lambda item: item[0].casefold()))


def app_allowed(app: str, rules: dict[str, bool]) -> bool:
    """Explicit choice wins; otherwise every (non-system) app is read."""
    if app in rules:
        return rules[app]
    return True


def group_message(app: str, senders: list[str], count: int, language: str = "ru", say_app=True) -> str:
    """«Telegram: 3 новых сообщения — Мама, Папа»."""
    names = ", ".join(dict.fromkeys(name for name in senders if name))[:120]
    if language == "en":
        head = f"{count} new messages"
    elif language == "ro":
        head = f"{count} mesaje noi"
    else:
        word = "новое сообщение" if count % 10 == 1 and count % 100 != 11 else (
            "новых сообщения" if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14 else "новых сообщений")
        head = f"{count} {word}"
    body = f"{head} — {names}" if names else head
    return f"{app}: {body}" if say_app and app else body


def computer_locked() -> bool:
    if sys.platform != "win32":
        return False
    import ctypes
    user32 = ctypes.windll.user32
    desktop = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
    if not desktop:
        return True
    try:
        return not user32.SwitchDesktop(desktop)
    finally:
        user32.CloseDesktop(desktop)


_REQUESTS = (
    ("missed", r"(?:что\s+пришло|что\s+нового\s+пришло|пропущенн\w+\s+уведомлен\w*|какие\s+уведомлен\w*|"
               r"ce\s+a\s+venit|ce\s+notific[aă]ri|what\s+came\s+in|missed\s+notifications|any\s+notifications)"),
    ("last", r"(?:прочитай|повтори|прочти)\s+последн\w+\s+(?:сообщени\w*|уведомлени\w*)|"
             r"cite[șs]te\s+ultim\w*\s+(?:mesaj|notificare)|read\s+the\s+last\s+(?:message|notification)"),
    ("off", r"(?:не\s+читай|перестань\s+читать|выключи\s+(?:озвучку\s+)?уведомлени\w*)\s*(?:уведомлени\w*)?|"
            r"nu\s+citi\s+notific[aă]rile|don'?t\s+read\s+notifications|stop\s+reading\s+notifications"),
    ("on", r"(?:читай|включи\s+(?:озвучку\s+)?)\s*уведомлени\w*|cite[șs]te\s+notific[aă]rile|read\s+notifications"),
    ("dnd", r"(?:не\s+беспокой\w*|nu\s+deranja|do\s+not\s+disturb)"),
)


def parse_voice_request(text: str) -> str | None:
    value = " ".join(str(text or "").casefold().split())
    value = re.sub(r"^(?:jarvis|джарвис)[\s,]*", "", value)
    if len(value) > 80:
        return None
    for name, pattern in _REQUESTS:
        if re.fullmatch(r"(?:пожалуйста\s+)?(?:" + pattern + r")[\s.!?,]*(?:пожалуйста)?[\s.!?]*", value):
            return name
    return None


def in_quiet_hours(hour: int, start: int, end: int) -> bool:
    if start == end:
        return False
    return start <= hour < end if start < end else (hour >= start or hour < end)


def microphone_in_use_by_other_app() -> bool:
    """True while another desktop app records or films (a call). Jarvis itself is ignored."""
    if sys.platform != "win32":
        return False
    return _device_in_use("microphone") or _device_in_use("webcam")


def _device_in_use(device: str) -> bool:
    import winreg
    base = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore" + "\\" + device
    for sub in ("NonPackaged", ""):
        try:
            root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, base + ("\\" + sub if sub else ""))
        except OSError:
            continue
        with root:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                lowered = name.casefold()
                # Always-listening assistants (Jarvis itself, Luxify) are not calls.
                if name == "NonPackaged" or any(part in lowered for part in ("python", "luxai", "luxify")):
                    continue
                try:
                    with winreg.OpenKey(root, name) as key:
                        stop, _ = winreg.QueryValueEx(key, "LastUsedTimeStop")
                        start, _ = winreg.QueryValueEx(key, "LastUsedTimeStart")
                except OSError:
                    continue
                if stop == 0 and start:
                    return True
    return False


class NotificationWatcher:
    """Return toasts that arrived after the watcher started (read-only)."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path or DB_PATH)
        self.last_order = None
        self.error = ""

    def available(self) -> bool:
        return self.path.is_file()

    def _connect(self):
        uri = "file:" + str(self.path).replace("\\", "/") + "?mode=ro"
        return sqlite3.connect(uri, uri=True, timeout=0.5)

    def prime(self):
        """Skip everything that already exists."""
        try:
            with closing(self._connect()) as connection:
                value = connection.execute("SELECT COALESCE(MAX([Order]), 0) FROM Notification").fetchone()[0]
            self.last_order = int(value or 0)
            self.error = ""
        except sqlite3.Error as error:
            self.error = str(error)
            self.last_order = None
        return self.last_order is not None

    def poll(self) -> list[dict]:
        if self.last_order is None and not self.prime():
            return []
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT n.[Order], n.Payload, h.PrimaryId FROM Notification n "
                    "LEFT JOIN NotificationHandler h ON h.RecordId = n.HandlerId "
                    "WHERE n.[Order] > ? AND n.Type = 'toast' ORDER BY n.[Order] LIMIT 20",
                    (self.last_order,)).fetchall()
            self.error = ""
        except sqlite3.Error as error:
            self.error = str(error)
            return []
        result = []
        for order, payload, primary in rows:
            self.last_order = max(self.last_order, int(order))
            if is_ignored_app(primary):
                continue
            result.append({"app": app_name(primary), "texts": toast_texts(payload), "source": str(primary or "")})
        return result


def windows_do_not_disturb() -> bool:
    """True when Windows says notifications should wait (presentation,
    full-screen D3D app, quiet time / focus). Uses SHQueryUserNotificationState."""
    if sys.platform != "win32":
        return False
    import ctypes
    state = ctypes.c_int(0)
    try:
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return False
    except (OSError, AttributeError):
        return False
    # 2 busy, 3 D3D full screen, 4 presentation, 6 quiet time; 5 = accepts notifications.
    return state.value in (2, 3, 4, 6)
