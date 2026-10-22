"""Read explicit user-selected text from the focused Windows application.

Jarvis cannot observe highlighting just by taking an OCR screenshot. For
browser/editor selection, send Ctrl+C to the verified EXTERNAL window,
read clipboard Unicode text, and restore the prior clipboard formats.

Qt clipboard calls MUST run on the Qt GUI thread. This module deliberately
does not transmit clipboard content to any network/API.
"""
from __future__ import annotations

import ctypes
import re
import sys

from luxai.fast_intents import strip_wake_name

MAX_CLIPBOARD_BYTES = 12 * 1024 * 1024
MAX_SELECTED_CHARS = 6500

SELECTION_WORDS = re.compile(
    r"(?:выделенн\w*|выделил\w*|выделен\w*|выбранн\w*|"
    r"selected|highlighted|selectat\w*|evidențiat\w*)", re.I,
)
SUMMARY_WORDS = re.compile(
    r"(?:пересказ\w*|перескаж\w*|пересказать|резюм\w*|"
    r"суммар\w*|кратк\w*|суть|основн\w*|объясни|объяснить|"
    r"summar\w*|rezum\w*|pe\s+scurt)", re.I,
)
READ_WORDS = re.compile(
    r"(?:прочитай|прочти|прочесть|прочитать|зачитай|озвучь|"
    r"покажи|скажи|что\s+я\s+выделил|read|citește|citeste)", re.I,
)


def selected_text_intent(text: str) -> str | None:
    """Return summarize/read only for explicit selections; not whole screen."""
    phrase = strip_wake_name(text).strip()
    if not SELECTION_WORDS.search(phrase):
        return None
    if SUMMARY_WORDS.search(phrase):
        return "summarize"
    if READ_WORDS.search(phrase):
        return "read"
    if re.search(r"\bя\s+выделил\w*\b.{0,45}\b(?:текст|фрагмент\w*)", phrase, re.I):
        return "summarize"
    return None


def clipboard_sequence() -> int:
    if sys.platform != "win32":
        return 0
    return int(ctypes.windll.user32.GetClipboardSequenceNumber())


def capture_clipboard(clipboard) -> dict[str, bytes] | None:
    """Clone all exposed MIME formats, or refuse copy if can't preserve them."""
    data = clipboard.mimeData()
    if data is None:
        return {}
    formats = list(data.formats())
    if len(formats) > 30:
        return None
    saved = {}
    total = 0
    for fmt in formats:
        content = bytes(data.data(fmt))
        total += len(content)
        if total > MAX_CLIPBOARD_BYTES:
            return None
        saved[str(fmt)] = content
    return saved


def restore_clipboard(clipboard, saved: dict[str, bytes]) -> None:
    """Restore text, HTML and other clipboard formats, not only plain text."""
    from PySide6.QtCore import QMimeData

    if not saved:
        clipboard.clear()
        return
    replacement = QMimeData()
    for fmt, contents in saved.items():
        replacement.setData(fmt, contents)
    clipboard.setMimeData(replacement)


def copy_selected_text(clipboard, hwnd: int, *, keyboard=None,
                       foreground=None, sleep=None) -> tuple[str, int, dict]:
    """Trigger Ctrl+C with a verified foreground, return capture context.

    Caller must check clipboard_sequence() again *after* a Qt timer has let
    the target application populate the clipboard.
    """
    from luxai.screen_interact import _valid_external_window, _foreground_hwnd
    _valid_external_window(hwnd)
    current = foreground() if foreground is not None else _foreground_hwnd()
    if current != hwnd:
        raise RuntimeError(
            "Активное окно изменилось. Выберите текст в браузере и повторите."
        )
    preserved = capture_clipboard(clipboard)
    if preserved is None:
        raise RuntimeError(
            "Буфер обмена содержит сложные или слишком большие данные. "
            "Не хочу потерять их при копировании. Скопируйте выделение вручную."
        )
    before = clipboard_sequence()
    if keyboard is None:
        import pyautogui
        keyboard = pyautogui.hotkey
    keyboard("ctrl", "c", interval=0.06)
    return "pending", before, preserved


def finish_selected_copy(clipboard, hwnd: int, before: int,
                         preserved: dict, *, foreground=None) -> str:
    """Read new selection and restore original clipboard if unchanged.

    Never mistake preexisting clipboard text for an actual selection, and
    never overwrite clipboard data supplied by another app in the meantime.
    """
    from luxai.screen_interact import _foreground_hwnd
    current = foreground() if foreground is not None else _foreground_hwnd()
    after = clipboard_sequence()
    if after == before or (not after and not clipboard.text()):
        raise RuntimeError(
            "Не удалось скопировать выделенный текст из активного окна. "
            "Выделите текст в браузере и повторите команду."
        )
    selected = str(clipboard.text()).strip()
    if after and clipboard_sequence() == after:
        restore_clipboard(clipboard, preserved)
    if current != hwnd:
        raise RuntimeError(
            "Фокус окна изменился во время копирования. "
            "Повторите команду с нужным окном."
        )
    if not selected:
        raise RuntimeError(
            "Выделение не содержит обычного текста. "
            "Попробуйте выделить именно текст, а не изображение."
        )
    if len(selected) > MAX_SELECTED_CHARS:
        selected = selected[:MAX_SELECTED_CHARS].rsplit(" ", 1)[0]
        selected += "\n[Выделение сокращено до 6500 символов.]"
    return selected


def extractive_fallback(text: str) -> str:
    """Honest, modestly useful extractive fallback, no fabricated AI summary."""
    clean = " ".join(str(text).split())
    if len(clean) <= 420:
        return "Выделенный текст: " + clean
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    result = ""
    for sentence in sentences:
        if len(result) + len(sentence) + 1 > 550:
            break
        result += (" " if result else "") + sentence
        if len(result) > 220:
            break
    if not result:
        result = clean[:400].rsplit(" ", 1)[0] + "…"
    return (
        "Удалось прочитать выделение, но AI сейчас недоступен. "
        "Начало текста без автоматического пересказа: " + result
    )
