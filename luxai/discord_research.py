"""Source-backed research to a specifically confirmed Discord DM.

This is a dedicated workflow, not a generic screenshot click. The bot finds
a cited article, searches Discord Quick Switcher for @recipient, visually
validates a match and the DM composer, drafts a message, and waits for an
explicit user decision before pressing Enter. It never claims delivery.
"""
from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

TOPIC_LIMIT = 110
USER_LIMIT = 48


def validate_research_dm_target(value: object) -> tuple[str, str]:
    if not isinstance(value, str) or "||" not in value:
        raise ValueError("Укажите тему и пользователя Discord: Тема||Имя")
    topic, username = value.rsplit("||", 1)
    topic, username = topic.strip(), username.strip().lstrip("@")
    if (not 2 <= len(topic) <= TOPIC_LIMIT or
            not 2 <= len(username) <= USER_LIMIT or
            any(ord(c) < 32 or c in "<>|" for c in topic + username) or
            not re.fullmatch(r"[\w.\- ]{2,48}", username, re.UNICODE)):
        raise ValueError("Неверная тема или имя пользователя Discord")
    return topic, username


def detect_research_dm_request(text: str) -> tuple[str, str] | None:
    """Detect the user's full multi-stage instruction, not arbitrary clicks."""
    phrase = str(text or "").strip()
    lower = phrase.casefold()
    if not (
        re.search(r"(?i)(?:информац|сведени|information|informați|informati|найди|find)", lower)
        and re.search(r"(?i)(?:discord|дискорд|дисси|dessie|в десси|в дисе)", lower)
        and re.search(r"(?i)(?:отправ|напиши|send|trimite|сообщени|message|поставь)", lower)
    ):
        return None
    # Voice recognition may spell Discord/username differently. Extract a
    # candidate, but the recipient must be confirmed again before sending.
    topic_match = re.search(
        r"(?is)(?:информаци[юя]\s+(?:про|об|о)|"
        r"information about|informați[ei]\s+despre|informatii\s+despre)"
        r"\s+(.+?)(?=\s+(?:потом|затем|then|apoi|и\s+(?:нажми|отправ|открой))\b|$)",
        phrase,
    )
    user_match = re.search(
        r"(?i)(?:пользовател[ья]\s+|user(?:name)?\s+|utilizator(?:ul)?\s+|@)"
        r"([\w.\-]{2,48})",
        phrase,
    )
    if not topic_match or not user_match:
        return None
    try:
        return validate_research_dm_target(
            topic_match.group(1).strip(" ,.!?") + "||" + user_match.group(1)
        )
    except ValueError:
        return None


def get_wikipedia_summary(topic: str) -> tuple[str, str]:
    """Real ru.wikipedia.org TextExtracts query; never invent article text."""
    topic, _ = validate_research_dm_target(topic + "||testuser")
    args = urllib.parse.urlencode({
        "action": "query", "generator": "search", "gsrsearch": topic,
        "gsrlimit": "1", "prop": "extracts", "exintro": "1",
        "explaintext": "1", "exchars": "650", "format": "json", "formatversion": "2",
    })
    url = "https://ru.wikipedia.org/w/api.php?" + args
    req = urllib.request.Request(url, headers={
        "User-Agent": "LuxAI-DesktopAssistant/0.2 (Wikipedia summary; non-bot desktop client)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=14) as response:
        if response.status != 200:
            raise OSError("Wikipedia API returned an error")
        payload = json.loads(response.read(160_000).decode("utf-8"))
    pages = payload.get("query", {}).get("pages", [])
    if not isinstance(pages, list) or len(pages) != 1:
        raise ValueError("Wikipedia did not find a unique relevant article")
    page = pages[0]
    title = str(page.get("title", "")).strip()
    extract = re.sub(r"\s+", " ", str(page.get("extract", ""))).strip()
    if not title or len(extract) < 45:
        raise ValueError("Wikipedia has no usable article text for this topic")
    # Cite the actual source; no hallucinated article or source.
    link = "https://ru.wikipedia.org/wiki/" + urllib.parse.quote(
        title.replace(" ", "_"), safe="()_"
    )
    limit = max(105, 336 - len(title) - len(link))
    snippet = extract[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    # One visual line: inserting a newline into Discord may send before
    # the explicit final user confirmation on some client versions.
    body = f"{title}: {snippet}…  Источник: {link}"
    if len(body.encode("utf-16-le")) // 2 > 350:
        raise ValueError("Article preview exceeds message size limit")
    return body, link


def find_discord_window() -> int:
    """Identify Discord by the real process image, not window title alone."""
    if sys.platform != "win32":
        raise OSError("This workflow requires Windows Discord desktop")
    import psutil
    user32 = ctypes.windll.user32
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowTextW.argtypes = [
        wintypes.HWND, wintypes.LPWSTR, ctypes.c_int,
    ]
    handles = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd, extra):
        if not user32.IsWindowVisible(wintypes.HWND(hwnd)) or user32.GetWindow(wintypes.HWND(hwnd), 4):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        try:
            process_name = psutil.Process(pid.value).name().casefold()
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return True
        if process_name in {"discord.exe", "discordptb.exe", "discordcanary.exe"}:
            title_buffer = ctypes.create_unicode_buffer(260)
            user32.GetWindowTextW(wintypes.HWND(hwnd), title_buffer, len(title_buffer))
            if "discord" in title_buffer.value.casefold():
                handles.append(int(hwnd))
        return True
    user32.EnumWindows(collect, 0)
    if len(handles) != 1:
        raise ValueError(
            "Discord должен быть открыт в одном окне. Запустите Discord и повторите команду."
        )
    return handles[0]


def focus_discord(hwnd: int) -> None:
    if sys.platform != "win32":
        raise OSError("Windows required")
    from luxai.screen_interact import _valid_external_window, _foreground_hwnd
    pid, title = _valid_external_window(hwnd)
    import psutil
    if psutil.Process(pid).name().casefold() not in {
        "discord.exe", "discordptb.exe", "discordcanary.exe",
    }:
        raise ValueError("Selected window is not the Discord application")
    user32 = ctypes.windll.user32
    user32.ShowWindow(wintypes.HWND(hwnd), 9)  # restore; does not minimize user windows
    user32.SetForegroundWindow(wintypes.HWND(hwnd))
    time.sleep(0.22)
    if _foreground_hwnd() != hwnd:
        raise RuntimeError("Could not focus Discord window")


@dataclass(frozen=True)
class DiscordDraft:
    hwnd: int
    username: str
    message: str
    source_url: str
    composer_point: tuple[int, int]
    # The screenshot is not retained in this object.


def prepare_discord_draft(planner, target: str) -> DiscordDraft:
    """Run only AFTER user consents to sharing up to two Discord screenshots."""
    from luxai.visual_click import capture_window, find_visual_target, click_visual_target
    from luxai.desktop_actions import _type_unicode_windows
    import pyautogui

    topic, username = validate_research_dm_target(target)
    message, source_url = get_wikipedia_summary(topic)
    hwnd = find_discord_window()
    focus_discord(hwnd)

    # Discord's documented Ctrl+K Quick Switcher, @ prefix for DM users.
    pyautogui.hotkey("ctrl", "k", interval=0.07)
    time.sleep(0.18)
    _type_unicode_windows("@" + username)
    time.sleep(0.95)
    selected = capture_window(hwnd)
    point = find_visual_target(
        planner,
        f"Discord Quick Switcher USER result EXACTLY matching @{username}. "
        "Search result must be visible in the switcher; reject ambiguous names.",
        selected,
    )
    click_visual_target(selected, point, 1)
    time.sleep(0.8)
    conversation = capture_window(hwnd)
    composer = find_visual_target(
        planner,
        f"Discord DM conversation HEADER displays recipient {username} "
        "and message composer at bottom; ONLY locate composer if header "
        f"unambiguously matches {username}. Otherwise return found:false.",
        conversation,
    )
    click_visual_target(conversation, composer, 1)
    # The message is PREPARED; no Enter or other send action here.
    if "\n" in message or "\r" in message:
        raise ValueError("Message contains an unsafe newline")
    _type_unicode_windows(message)
    return DiscordDraft(hwnd, username, message, source_url, composer)


def submit_discord_draft(draft: DiscordDraft, planner, *, cancelled=None) -> str:
    """Reinspect the CURRENT recipient and unsent text after final approval.

    A saved composer coordinate is not enough: the Discord chat or draft may
    have changed while the user was reading the confirmation dialog. The
    original screenshot consent covers this third and final visual check.
    If anything cannot be verified, do not click or send.
    """
    if not isinstance(draft, DiscordDraft):
        raise ValueError("No prepared Discord draft")
    if planner is None:
        raise ValueError("A vision-capable AI is required to verify the draft")
    if cancelled is not None and cancelled():
        raise RuntimeError("Discord send cancelled")
    from luxai.visual_click import capture_window, find_visual_target, click_visual_target
    import pyautogui

    focus_discord(draft.hwnd)
    current = capture_window(draft.hwnd)
    point = find_visual_target(
        planner,
        "Discord DIRECT MESSAGE: verify the visible chat HEADER is exactly "
        f"the intended recipient @{draft.username}, AND the message composer "
        "contains the COMPLETE UNSENT draft, not a different message. "
        f"Expected exact draft: {draft.message!r}. "
        "Only if BOTH checks are unambiguous, return the center of that "
        "composer. If the chat, message or text is different, unreadable, "
        "partially hidden or absent, return found:false.",
        current,
    )
    if cancelled is not None and cancelled():
        raise RuntimeError("Discord send cancelled")
    # Clicking through the capture validator rejects a switched window,
    # overlay or out-of-bounds location; never reuse the old coordinates.
    click_visual_target(current, point, 1)
    if cancelled is not None and cancelled():
        raise RuntimeError("Discord send cancelled")
    pyautogui.press("enter")
    return ("Enter отправлен в проверенный диалог Discord. Доставку сообщения "
            "подтвердить не могу — проверьте историю переписки.")
