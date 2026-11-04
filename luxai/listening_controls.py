"""Exact voice controls and a non-intercepting Windows push-to-talk gate."""
from __future__ import annotations

import ctypes
import re
import sys
import unicodedata


DEFAULT_CONTROL_PHRASES = {
    "prefix_mode_phrases": "перейди в режим префикса",
    "quiet_mode_phrases": "перейди в тихий режим",
    "microphone_off_phrases": "выключи микрофон",
    "command_stop_phrases": "стоп, stop, oprește",
}

_CONTROL_KEYS = (
    ("command_stop_phrases", "stop"),
    ("prefix_mode_phrases", "prefix"),
    ("quiet_mode_phrases", "quiet"),
    ("microphone_off_phrases", "microphone_off"),
)
_WAKE_NAMES = ("jarvis", "джарвис", "жарвис", "джервис", "жервис", "жарис", "джарис")


def normalize_control_phrase(value):
    """Ignore case and punctuation, while retaining complete word boundaries."""
    text = unicodedata.normalize("NFC", str(value or "")).translate(
        str.maketrans({"ş": "ș", "Ş": "Ș", "ţ": "ț", "Ţ": "Ț"})
    ).casefold()
    return " ".join(re.sub(r"[\W_]+", " ", text, flags=re.UNICODE).split())


def _phrases(value):
    if not isinstance(value, str):
        return ()
    return tuple(phrase for raw in value[:2000].split(",")[:24]
                 if (phrase := normalize_control_phrase(raw[:120])))


def mode_control(text, config):
    """Return a configured control only when the entire utterance matches.

    An optional wake name is accepted at the beginning. A command mentioning a
    control phrase as a substring never changes mode or cancels queued work.
    Explicitly empty phrase settings disable the corresponding control.
    """
    if not isinstance(text, str) or len(text) > 2000:
        return None
    normalized = normalize_control_phrase(text)
    if not normalized:
        return None
    candidates = {normalized}
    names = set(_phrases(config.get("wake_prefix", ""))) | set(_WAKE_NAMES)
    for name in names:
        if normalized.startswith(name + " "):
            candidates.add(normalized[len(name) + 1:])
    for key, control in _CONTROL_KEYS:
        if candidates.intersection(_phrases(config.get(key, DEFAULT_CONTROL_PHRASES[key]))):
            return control
    return None


def normalize_listen_hotkey(value):
    """Validate a held key without registering or suppressing its normal use."""
    if not isinstance(value, str) or not value or len(value) > 60:
        raise ValueError("Invalid listening hotkey")
    parts = [part.strip().casefold() for part in value.split("+")]
    aliases = {"control": "ctrl", "meta": "win"}
    parts = [aliases.get(part, part) for part in parts]
    modifiers = ("ctrl", "alt", "shift", "win")
    if not all(parts) or len(parts) != len(set(parts)):
        raise ValueError("Invalid listening hotkey")
    keys = [part for part in parts if part not in modifiers]
    if len(keys) != 1 or re.fullmatch(r"[a-z0-9]|space|f(?:[1-9]|1[0-2])", keys[0]) is None:
        raise ValueError("Invalid listening hotkey")
    return "+".join([part for part in modifiers if part in parts] + keys)


def _windows_key_pressed(code):
    return bool(ctypes.windll.user32.GetAsyncKeyState(code) & 0x8000)


def capture_allowed(config, *, key_reader=None):
    """Read current key state; unavailable or malformed held-key gates close.

    ``key_reader`` is an optional virtual-key-to-bool function for tests. The
    native path reads Windows key state without installing keyboard hooks.
    """
    if config.get("listen_mode", "always") != "hold":
        return True
    if key_reader is None:
        if sys.platform != "win32":
            return False
        key_reader = _windows_key_pressed
    try:
        parts = normalize_listen_hotkey(config.get("listen_hotkey", "ctrl+space")).split("+")
        for modifier, code in (("ctrl", 0x11), ("alt", 0x12), ("shift", 0x10)):
            if modifier in parts and not key_reader(code):
                return False
        if "win" in parts and not (key_reader(0x5B) or key_reader(0x5C)):
            return False
        key = parts[-1]
        code = 0x20 if key == "space" else 0x6F + int(key[1:]) if key.startswith("f") and len(key) > 1 else ord(key.upper())
        return bool(key_reader(code))
    except (ValueError, TypeError, AttributeError, OSError, RuntimeError):
        return False
