"""Discord voice calls for the status island (0.4.3y): in a call or not, where / with whom, mic, sound, volume.

- In a call: Windows itself says Discord holds the microphone (the privacy «in use» registry, read-only).
- Where / with whom: the «Voice Connected» panel of the Discord window, read through UI Automation
  (the same way Jarvis already reads Discord's mic / deafen buttons; no screenshots, no clicks). For a
  direct call it is the person («@Ana»), for a server it is «Channel / Server».
- Mic and deafen: Discord's own buttons (``discord_audio``), in the background, never typing.
- Volume: the Windows mixer volume of Discord (what you hear from the call).
Everything here runs on the island probe thread or a short worker thread, never on the Qt UI thread.
"""
from __future__ import annotations

import re
import sys
import time

_CONNECTED = re.compile(r"voice connected|голосов\w* (?:связь|подключ)|подключено к голос|conectat la voce|"
                        r"conexiune vocal|rtc connected", re.I)
_DISCONNECT = re.compile(r"^(?:disconnect|отключиться|deconecteaz[ăa]-te|deconectare)$", re.I)
_NOISE = re.compile(r"voice connected|подключ|conectat|ping|\bms\b|disconnect|отключ|deconect|noise|шумоподав|"
                    r"suprim|camera|камер|video|видео|screen|экран|ecran|activit|актив|soundboard|звуков", re.I)


def discord_holds_microphone() -> bool:
    """Windows' «a program uses the microphone» list says Discord (a call or a voice channel)."""
    if sys.platform != "win32":
        return False
    try:
        from luxai.notifications import devices_in_use
        return any("discord" in name.casefold() for name in devices_in_use("microphone"))
    except Exception:
        return False


def read_call_panel(hwnd: int) -> dict:
    """{"connected": bool, "where": str, "mic_muted": bool|None, "deafened": bool|None} from the Discord window."""
    from luxai.discord_audio import _automation, read_buttons
    result = {"connected": False, "where": "", "mic_muted": None, "deafened": None}
    automation, uia = _automation()
    root = automation.ElementFromHandle(hwnd)
    everything = root.FindAll(uia.TreeScope_Descendants, automation.CreateTrueCondition())
    window = root.CurrentBoundingRectangle
    lower = window.top + (window.bottom - window.top) * 0.5
    panel = None
    texts = []
    for index in range(min(everything.Length, 6000)):
        element = everything.GetElement(index)
        name = (element.CurrentName or "").strip()
        if not name:
            continue
        rect = element.CurrentBoundingRectangle
        if rect.bottom < lower:
            continue  # the call panel is in the lower half, above the account bar
        if _CONNECTED.search(name) or _DISCONNECT.match(name):
            result["connected"] = True
            if _CONNECTED.search(name) and panel is None:
                panel = rect
        texts.append((name, rect))
    if panel is not None:
        # The line under «Voice Connected»: «General / My server» or «@Ana».
        below = [(rect.top, name) for name, rect in texts
                 if panel.bottom - 4 <= rect.top <= panel.bottom + 40 and rect.left < panel.left + 120
                 and not _NOISE.search(name) and len(name) <= 120]
        if below:
            result["where"] = sorted(below)[0][1]
    buttons = read_buttons(hwnd, attempts=1)
    result["mic_muted"] = buttons.get("mic", (None, None))[1]
    result["deafened"] = buttons.get("deaf", (None, None))[1]
    return result


class DiscordCall:
    """Polled once a second by the island probe; ``state()`` is what the island shows."""

    def __init__(self, holds_microphone=discord_holds_microphone, panel_reader=None, window_finder=None):
        self.holds_microphone = holds_microphone
        self.panel_reader = panel_reader or read_call_panel
        self.window_finder = window_finder
        self.since = 0.0
        self.panel: dict = {}
        self._panel_at = 0.0
        self._panel_failures = 0

    def _hwnd(self) -> int:
        if self.window_finder is not None:
            return self.window_finder()
        from luxai.discord_window_state import find_discord_window
        return find_discord_window()

    def poll(self, now: float | None = None) -> dict | None:
        now = time.time() if now is None else now
        in_call = self.holds_microphone()
        if in_call and now - self._panel_at >= (3 if self._panel_failures < 3 else 30):
            self._panel_at = now
            try:
                hwnd = self._hwnd()
                self.panel = self.panel_reader(hwnd) if hwnd else {}
                self._panel_failures = 0 if self.panel else self._panel_failures + 1
            except Exception:
                self.panel = {}
                self._panel_failures += 1  # e.g. Discord runs elevated and Jarvis does not: details stay unknown
        if not in_call:
            self.since = 0.0
            self.panel = {}
            self._panel_at = 0.0
            return None
        if not self.since:
            self.since = now
        return {"since": self.since, "where": self.panel.get("where", ""), "mic_muted": self.panel.get("mic_muted"),
                "deafened": self.panel.get("deafened"), "volume": discord_volume()}


# --- the Discord volume in the Windows mixer ------------------------------------------------------

def _discord_sessions():
    from pycaw.pycaw import AudioUtilities
    return [session for session in AudioUtilities.GetAllSessions()
            if session.Process is not None and session.Process.name().casefold() == "discord.exe"]


def discord_volume() -> float | None:
    try:
        sessions = _discord_sessions()
        if not sessions:
            return None
        return round(max(session.SimpleAudioVolume.GetMasterVolume() for session in sessions), 2)
    except Exception:
        return None


def change_discord_volume(step: float) -> float | None:
    """+0.1 / -0.1 on every Discord audio session; returns the new level."""
    try:
        sessions = _discord_sessions()
        if not sessions:
            return None
        level = max(session.SimpleAudioVolume.GetMasterVolume() for session in sessions)
        level = max(0.0, min(1.0, round(level + step, 2)))
        for session in sessions:
            session.SimpleAudioVolume.SetMasterVolume(level, None)
        return level
    except Exception:
        return None


def toggle_discord(kind: str, language: str) -> str:
    """Mic («mic») or headphones («deaf») on/off with Discord's own button; the reply sentence."""
    # Never Discord's keyboard shortcut from here: it brings Discord to the front, out of a game.
    from luxai.discord_audio import set_discord_audio
    reply = set_discord_audio(kind, "toggle", language)
    if reply is not None:
        return reply
    return {"ru": "Не вижу кнопок Discord — переключите в самом Discord.",
            "en": "I cannot see Discord's buttons — switch it in Discord itself.",
            "ro": "Nu văd butoanele Discord — comută din Discord."}.get(language, "")
