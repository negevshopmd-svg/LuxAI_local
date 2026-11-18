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
import threading

from luxai.fast_intents import strip_wake_name

MAX_CLIPBOARD_BYTES = 12 * 1024 * 1024
MAX_SELECTED_CHARS = 6500

SELECTION_WORDS = re.compile(
    r"(?:выделенн\w*|выделил\w*|выделю|выделяю|выделен\w*|выбранн\w*|"
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
# Short explicit requests such as "Сделай краткий пересказ" commonly follow
# highlighting a webpage. Interpret them as a selection request only when
# there's no dictated text or other object to summarize. The GUI handler
# still requires a verified external foreground application window.
SHORT_SELECTION_SUMMARY = re.compile(
    r"^\s*(?:(?:сделай|дай|подготовь|пожалуйста\s+сделай)\s+)?"
    r"(?:краткий\s+)?(?:пересказ|резюме|суммаризацию)"
    r"(?:\s+(?:этого\s+)?текста)?\s*[.!?]*$",
    re.I,
)



def selected_text_intent(text: str) -> str | None:
    """Return summarize/read only for explicit selections; not whole screen."""
    phrase = strip_wake_name(text).strip()
    if SHORT_SELECTION_SUMMARY.fullmatch(phrase):
        return "summarize"
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
    from luxai.clipboard_store import suppress

    suppress(1.5)
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
    from luxai.clipboard_store import suppress
    suppress(3.0)
    if keyboard is None:
        # Layout independent: with a Russian layout pyautogui never sends "c".
        from luxai.keys import press as keyboard, release_modifiers
        release_modifiers()
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


def selected_text_by_automation(hwnd: int, timeout: float = 2.0) -> str:
    """The selected text of the focused control via Windows UI Automation.

    Used when an app ignores the synthetic Ctrl+C. Chromium/Electron apps
    (Discord, browsers) expose their selection through the TextPattern once
    an accessibility client asks. Returns "" when nothing can be read.
    """
    if sys.platform != "win32":
        return ""
    result = {"text": ""}

    def work():
        try:
            import comtypes
            import comtypes.client
            # COM stays initialised for this short-lived thread: releasing it while
            # UIA objects are still alive crashes the process.
            try:
                comtypes.CoInitialize()
            except OSError:
                pass  # COM is already set up for this thread
            if True:
                comtypes.client.GetModule("UIAutomationCore.dll")
                from comtypes.gen import UIAutomationClient as uia
                automation = comtypes.client.CreateObject(
                    "{ff48dba4-60ef-4201-aa87-54103eef594e}", interface=uia.IUIAutomation)
                candidates = []
                try:
                    candidates.append(automation.GetFocusedElement())
                except Exception:
                    pass
                try:
                    import ctypes as _ct
                    candidates.append(automation.ElementFromHandle(_ct.c_void_p(int(hwnd))))
                except Exception:
                    pass
                for element in candidates:
                    for item in _text_pattern_elements(automation, uia, element):
                        found = _selection_of(uia, item)
                        if found:
                            result["text"] = found
                            return
        except Exception:
            result["text"] = ""

    thread = threading.Thread(target=work, daemon=True, name="JarvisSelectionUIA")
    thread.start()
    thread.join(timeout)
    return result["text"].strip()


def _text_pattern_elements(automation, uia, element, limit: int = 40):
    """The element itself, then descendants that support the TextPattern."""
    if element is None:
        return []
    found = [element]
    try:
        condition = automation.CreatePropertyCondition(uia.UIA_IsTextPatternAvailablePropertyId, True)
        items = element.FindAll(uia.TreeScope_Descendants, condition)
        for index in range(min(items.Length, limit)):
            found.append(items.GetElement(index))
    except Exception:
        pass
    return found


def _selection_of(uia, element) -> str:
    try:
        pattern = element.GetCurrentPattern(uia.UIA_TextPatternId)
        if not pattern:
            return ""
        pattern = pattern.QueryInterface(uia.IUIAutomationTextPattern)
        ranges = pattern.GetSelection()
        parts = []
        for index in range(ranges.Length):
            parts.append(ranges.GetElement(index).GetText(MAX_SELECTED_CHARS))
        return " ".join(part for part in parts if part and part.strip())
    except Exception:
        return ""


def window_runs_as_admin(hwnd: int) -> bool:
    """True when the window's program runs with higher rights than Jarvis.

    Windows then blocks keys and UI Automation from ordinary programs (UIPI):
    Ctrl+C sent by Jarvis never arrives. Checked only when a copy failed.
    """
    if sys.platform != "win32" or not hwnd:
        return False
    import os
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32")
    kernel32 = ctypes.WinDLL("kernel32")
    advapi32 = ctypes.WinDLL("advapi32")
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                             ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    def elevated(pid: int):
        process = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not process:
            return None
        try:
            token = wintypes.HANDLE()
            if not advapi32.OpenProcessToken(process, 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
                return True  # a higher-rights process refuses even this
            try:
                value, size = wintypes.DWORD(), wintypes.DWORD()
                if not advapi32.GetTokenInformation(token, 20, ctypes.byref(value), 4, ctypes.byref(size)):
                    return None
                return bool(value.value)  # TokenElevation
            finally:
                kernel32.CloseHandle(token)
        finally:
            kernel32.CloseHandle(process)

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(ctypes.c_void_p(int(hwnd)), ctypes.byref(pid))
    if not pid.value:
        return False
    target, own = elevated(pid.value), elevated(os.getpid())
    return bool(target) and not own


def admin_window_message(hwnd: int) -> str:
    """Plain words for the user: what blocks the copy and how to fix it."""
    from luxai.screen_interact import _window_title
    title = (_window_title(hwnd) or "").strip()
    name = "Discord" if "discord" in title.casefold() else (title.rsplit(" - ", 1)[-1] or "это окно")
    return (f"{name} запущен от имени администратора, поэтому Windows не даёт Jarvis копировать из него "
            f"текст и нажимать в нём клавиши. Закройте {name} полностью (в трее «Выйти») и откройте "
            f"его обычным способом — без «Запуск от имени администратора».")
