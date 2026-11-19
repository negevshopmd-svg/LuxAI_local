"""Discord microphone and headphones without the cloud (0.4.2o).

1. Read the real account-bar buttons through Windows UI Automation (Discord is
   Chromium: its «Mute» / «Deafen» buttons are switches with a name and a
   pressed state). Jarvis runs as administrator, so it can read an elevated
   Discord too.
2. Already in the wanted state → just say so. Otherwise toggle the button
   itself (no keyboard, no window switch); if that is not possible, press
   Discord's own shortcut (Ctrl+Shift+M / Ctrl+Shift+D).
3. Read the state again and report what is true now.

When the state cannot be read at all, ``set_discord_audio`` returns None so the
caller may use the screenshot workflow; ``force_toggle`` presses the shortcut.
"""
from __future__ import annotations

import re
import time

KEYS = {"mic": ("ctrl", "shift", "m"), "deaf": ("ctrl", "shift", "d")}
# Button names in Discord's English / Russian / Romanian clients.
_MIC = re.compile(r"(?:\bmute\b|\bunmute\b|микрофон|microfon)", re.I)
_DEAF = re.compile(r"(?:deafen|звук|наушник|asurz|c[ăa][șs]ti|sunet)", re.I)
# A label that offers to turn something ON means it is currently OFF.
_OFFERS_ON = re.compile(r"^(?:un|вкл|включ|activ|reactiv|porn)", re.I)

TARGETS = {
    "mic_off": ("mic", "off"), "mic_on": ("mic", "on"), "mic_toggle": ("mic", "toggle"),
    "sound_off": ("deaf", "off"), "sound_on": ("deaf", "on"), "sound_toggle": ("deaf", "toggle"),
}
# "off" always means «not heard / hears nothing» (muted / deafened), as in the voice phrases.


def _automation():
    import comtypes
    import comtypes.client
    try:
        comtypes.CoInitialize()
    except OSError:
        pass  # already initialised in this thread (never uninitialise: it crashed UIA before)
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient as uia
    automation = comtypes.client.CreateObject("{ff48dba4-60ef-4201-aa87-54103eef594e}", interface=uia.IUIAutomation)
    return automation, uia


def _classify(name: str) -> str | None:
    if _DEAF.search(name) and not re.search(r"микрофон|microfon|\bmic", name, re.I):
        return "deaf"
    if _MIC.search(name):
        return "mic"
    return None


def read_buttons(hwnd: int, attempts: int = 3) -> dict:
    """{"mic": (element, state), "deaf": (element, state)}; state True = muted/deafened, None = unknown."""
    automation, uia = _automation()
    root = automation.ElementFromHandle(hwnd)
    condition = automation.CreatePropertyCondition(uia.UIA_ControlTypePropertyId, uia.UIA_ButtonControlTypeId)
    window = root.CurrentBoundingRectangle
    found = None
    for attempt in range(attempts):
        found = root.FindAll(uia.TreeScope_Descendants, condition)
        if found.Length > 3:
            break
        time.sleep(0.6)  # Chromium builds its accessibility tree after the first question
    best: dict = {}
    for index in range(found.Length if found is not None else 0):
        element = found.GetElement(index)
        name = (element.CurrentName or "").strip()
        kind = _classify(name)
        if kind is None:
            continue
        rect = element.CurrentBoundingRectangle
        # The account bar is the LOWEST mic/deafen pair (call panels and member menus have «Mute» too).
        if rect.bottom <= rect.top or rect.bottom < window.top + (window.bottom - window.top) * 0.6:
            continue
        state = None
        try:
            pattern = element.GetCurrentPattern(uia.UIA_TogglePatternId)
            if pattern:
                state = pattern.QueryInterface(uia.IUIAutomationTogglePattern).CurrentToggleState == 1
        except Exception:
            state = None
        if state is None and name:
            state = bool(_OFFERS_ON.search(name))
        if kind not in best or rect.bottom > best[kind][2]:
            best[kind] = (element, state, rect.bottom, name)
    return {kind: (value[0], value[1]) for kind, value in best.items()}


def _toggle(element) -> bool:
    _automation_obj, uia = _automation()
    for pattern_id, interface, method in ((uia.UIA_TogglePatternId, uia.IUIAutomationTogglePattern, "Toggle"),
                                          (uia.UIA_InvokePatternId, uia.IUIAutomationInvokePattern, "Invoke")):
        try:
            pattern = element.GetCurrentPattern(pattern_id)
            if pattern:
                getattr(pattern.QueryInterface(interface), method)()
                return True
        except Exception:
            continue
    return False


_WORDS = {
    "mic": {"off": ("Микрофон Discord выключен.", "The Discord microphone is off.", "Microfonul Discord e oprit."),
            "on": ("Микрофон Discord включён.", "The Discord microphone is on.", "Microfonul Discord e pornit.")},
    "deaf": {"off": ("Звук в Discord выключен (наушники).", "Discord sound is off (deafened).",
                     "Sunetul din Discord e oprit (căști)."),
             "on": ("Звук в Discord включён (наушники).", "Discord sound is on.", "Sunetul din Discord e pornit (căști).")},
}
_ALREADY = ("Уже было так: ", "It already was: ", "Era deja așa: ")


def _say(kind: str, muted: bool, language: str, already: bool = False) -> str:
    index = {"ru": 0, "en": 1, "ro": 2}.get(language, 0)
    text = _WORDS[kind]["off" if muted else "on"][index]
    return (_ALREADY[index] + text[0].lower() + text[1:]) if already else text


def set_discord_audio(kind: str, mode: str, language: str = "ru") -> str | None:
    """Set the Discord mic ("mic") or headphones ("deaf") to mode off/on/toggle.

    Returns the reply, or None when the state could not be read (the caller
    may then use the screenshot workflow or ``force_toggle``).
    """
    from luxai.discord_window_state import find_discord_window
    from luxai.windows_control import running_pids
    index = {"ru": 0, "en": 1, "ro": 2}.get(language, 0)
    if not running_pids("discord"):
        return ("Discord не запущен.", "Discord is not running.", "Discord nu rulează.")[index]
    hwnd = find_discord_window()
    try:
        buttons = read_buttons(hwnd)
    except Exception:
        return None
    if kind not in buttons or buttons[kind][1] is None:
        return None
    element, muted = buttons[kind]
    want_muted = (not muted) if mode == "toggle" else (mode == "off")
    if muted == want_muted:
        return _say(kind, muted, language, already=True)
    if not _toggle(element):
        from luxai.discord_shortcuts import press_in_discord
        press_in_discord(hwnd, *KEYS[kind])
    for _ in range(8):
        time.sleep(0.25)
        try:
            now = read_buttons(hwnd, attempts=1).get(kind, (None, None))[1]
        except Exception:
            now = None
        if now == want_muted:
            return _say(kind, now, language)
    # The button did not change: try the official shortcut once.
    from luxai.discord_shortcuts import press_in_discord
    press_in_discord(hwnd, *KEYS[kind])
    time.sleep(0.5)
    try:
        now = read_buttons(hwnd, attempts=1).get(kind, (None, None))[1]
    except Exception:
        now = None
    if now == want_muted:
        return _say(kind, now, language)
    return ("Discord не изменил кнопку — проверьте её сами.", "Discord did not change the button — please check it.",
            "Discord nu a schimbat butonul — verifică-l.")[index]


def force_toggle(kind: str, language: str = "ru") -> str:
    """No readable state and no cloud: press Discord's own shortcut and say it is a switch."""
    from luxai.discord_shortcuts import press_in_discord
    from luxai.discord_window_state import find_discord_window
    from luxai.windows_control import running_pids
    index = {"ru": 0, "en": 1, "ro": 2}.get(language, 0)
    if not running_pids("discord"):
        return ("Discord не запущен.", "Discord is not running.", "Discord nu rulează.")[index]
    press_in_discord(find_discord_window(), *KEYS[kind])
    label = "Ctrl+Shift+M" if kind == "mic" else "Ctrl+Shift+D"
    what = (("микрофон", "the microphone", "microfonul") if kind == "mic" else ("звук", "the sound", "sunetul"))[index]
    return (f"Переключил {what} Discord ({label}) — состояние прочитать не удалось.",
            f"Toggled {what} in Discord ({label}) — its state could not be read.",
            f"Am comutat {what} din Discord ({label}) — starea nu s-a putut citi.")[index]


def run_target(target: str, language: str = "ru") -> str:
    """A Discord command from the command library: «mic_off», «deaf_on», or a shortcut id."""
    if target in TARGETS:
        kind, mode = TARGETS[target]
        answer = set_discord_audio(kind, mode, language)
        return answer if answer is not None else force_toggle(kind, language)
    from luxai.discord_shortcuts import BY_ID, run_discord_shortcut
    if target in BY_ID:
        return run_discord_shortcut(target, language)
    raise ValueError("Unknown Discord command")
