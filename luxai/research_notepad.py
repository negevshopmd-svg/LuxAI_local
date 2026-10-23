"""Grounded Wikipedia facts to a verified Notepad window.

This is a specialized multi-app workflow. Generic browser search only opens a
tab and MUST NOT be mistaken for researched facts the assistant can type.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import re
import sys
import time
import urllib.parse
import urllib.request

from luxai.fast_intents import strip_wake_name


def detect_research_notepad(text: str) -> str | None:
    phrase = strip_wake_name(str(text or "")).strip()
    lower = phrase.casefold()
    if not (
        re.search(r"(?:найди\w*\s+в\s+интернет\w*|найди\w*\s+факт|find.*facts)", lower)
        and re.search(r"(?:три\s+факт\w*|3\s+факт\w*|three\s+facts)", lower)
        and re.search(r"(?:блокнот\w*|notepad)", lower)
        and re.search(r"(?:напиши|запиши|write|введи)", lower)
        and re.search(r"(?:выдели\s+весь\s+текст|ctrl\s*\+\s*a|select\s+all)", lower)
        and re.search(r"(?:скопируй|копируй|ctrl\s*\+\s*c|copy)", lower)
    ):
        return None
    match = re.search(
        r"(?:три|3|three)\s+(?:факт\w*|facts)\s+(?:про|о|об|about)\s+"
        r"([\w\- ]{2,70}?)(?=\s*[,;.!?]|\s+(?:открой|потом|затем)|$)",
        phrase, re.IGNORECASE | re.UNICODE,
    )
    if not match:
        return None
    topic = " ".join(match.group(1).split())
    if any(c in topic for c in "\\/:*?\"<>|") or len(topic) > 60:
        return None
    return topic


def _research_three_facts(topic: str) -> tuple[str, str]:
    """Fetch source-backed extract; do not fabricate facts from search results."""
    args = urllib.parse.urlencode({
        "action": "query", "generator": "search", "gsrsearch": topic,
        "gsrlimit": "1", "prop": "extracts", "exintro": "1",
        "explaintext": "1", "exchars": "2400", "format": "json",
        "formatversion": "2",
    })
    req = urllib.request.Request(
        "https://ru.wikipedia.org/w/api.php?" + args,
        headers={"User-Agent": "LuxAI-DesktopAssistant/0.2 (facts research; desktop)"},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        if response.status != 200:
            raise OSError("Wikipedia did not respond successfully")
        payload = json.loads(response.read(120000).decode("utf-8"))
    pages = payload.get("query", {}).get("pages", [])
    if not isinstance(pages, list) or len(pages) != 1:
        raise ValueError("Не найден единственный источник для трёх фактов")
    page = pages[0]
    source_title = str(page.get("title", "")).strip()
    extract = re.sub(r"\s+", " ", str(page.get("extract", ""))).strip()
    if not source_title or len(extract) < 90:
        raise ValueError("Не удалось извлечь достоверные факты")
    source = "https://ru.wikipedia.org/wiki/" + urllib.parse.quote(
        source_title.replace(" ", "_"), safe="()_",
    )
    # Preserve entire sentences, not arbitrary character slices that alter
    # the meaning of facts. With short quotes only, never hallucinate facts.
    candidates = re.split(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z0-9])", extract)
    facts = []
    for sentence in candidates:
        value = sentence.strip()
        if 24 <= len(value) <= 115 and value.endswith((".", "!", "?")):
            facts.append(value)
        if len(facts) >= 3:
            break
    if len(facts) < 3:
        raise ValueError(
            "В проверенной статье недостаточно трёх коротких фактов. "
            "Ничего не выдумываю и не печатаю."
        )
    notes = "\n".join(f"{i}. {v}" for i, v in enumerate(facts, 1))
    # URL stays in the app reply; three factual sentences go to Notepad.
    if len(notes.encode("utf-16-le")) // 2 > 350:
        raise ValueError("Источник содержит слишком длинные факты для ввода")
    return notes, source


def _focus_notepad_window() -> int:
    if sys.platform != "win32":
        raise OSError("Notepad workflow is Windows-only")
    import psutil
    from luxai.screen_interact import _foreground_hwnd, _valid_external_window
    user32 = ctypes.windll.user32
    windows = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd, _extra):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            name = psutil.Process(pid.value).name().casefold()
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return True
        if name == "notepad.exe":
            windows.append(int(hwnd))
        return True

    user32.EnumWindows(collect, 0)
    if len(windows) != 1:
        raise ValueError("Откройте ровно одно окно Блокнота и повторите команду")
    hwnd = windows[0]
    _valid_external_window(hwnd)
    user32.ShowWindow(wintypes.HWND(hwnd), 9)
    user32.SetForegroundWindow(wintypes.HWND(hwnd))
    time.sleep(0.3)
    if _foreground_hwnd() != hwnd:
        raise RuntimeError("Не удалось безопасно активировать Блокнот")
    return hwnd


def write_researched_facts_to_notepad(topic: str, *, cancelled=None) -> str:
    """Open Notepad, type three sourced sentences and copy them via hotkeys."""
    if not 2 <= len(topic) <= 60:
        raise ValueError("Неправильная тема исследования")
    from luxai.windows_apps import launch_installed_app
    from luxai.desktop_actions import _type_unicode_windows
    from luxai.screen_interact import _foreground_hwnd
    import pyautogui

    def check():
        if cancelled is not None and cancelled():
            raise RuntimeError("Команда отменена")

    check()
    facts, source = _research_three_facts(topic)
    check()
    success, message = launch_installed_app("notepad")
    if not success:
        raise RuntimeError("Не получилось открыть Блокнот: " + message)
    hwnd = _focus_notepad_window()
    check()
    # Avoid accidentally replacing an existing user's document. Always
    # create a blank Notepad buffer, verifying Notepad still has focus.
    pyautogui.hotkey("ctrl", "n", interval=0.08)
    time.sleep(0.25)
    hwnd = _focus_notepad_window()
    check()
    _type_unicode_windows(facts)
    check()
    if _foreground_hwnd() != hwnd:
        raise RuntimeError("Блокнот потерял фокус после ввода; копирование отменено")
    pyautogui.hotkey("ctrl", "a", interval=0.08)
    check()
    pyautogui.hotkey("ctrl", "c", interval=0.08)
    return (
        "Три предложения из Википедии записаны и скопированы в Блокноте. "
        f"Источник: {source}. Текст: {facts}"
    )
