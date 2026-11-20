"""Read the Windows clipboard OFF the Qt thread (audit 2 #14).

Qt's QClipboard can only be used on the GUI thread: when the program that owns the clipboard
renders its data slowly (delayed rendering), the whole Jarvis window waited. This module opens
the clipboard with the plain Win32 API on a worker thread and copies only what the history needs:
the privacy marker formats, Unicode text, «HTML Format» and, when there is no text, the picture
(CF_DIB). Sizes are checked before anything is copied.

Coalescing (audit 2 #35): Windows numbers every clipboard change (GetClipboardSequenceNumber).
Changes that arrive while a read is waiting are read once, as the CURRENT content; ``skipped``
in the result tells how many changes were not seen individually. A program that copies two
things within ~60 ms therefore leaves only the second one in the history — a deliberate limit
that keeps Jarvis from reading the clipboard in the middle of another program's update.
"""
from __future__ import annotations

import ctypes
import re
import struct
import sys
import time

CF_DIB = 8
CF_UNICODETEXT = 13
MAX_TEXT_BYTES = 8 * 1024 * 1024
MAX_DIB_BYTES = 256 * 1024 * 1024
_MARKERS = ("excludeclipboardcontentfrommonitorprocessing", "clipboard viewer ignore", "canincludeinclipboardhistory")


def _api():
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
    user32.EnumClipboardFormats.restype = wintypes.UINT
    user32.GetClipboardFormatNameW.argtypes = [wintypes.UINT, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClipboardFormatNameW.restype = ctypes.c_int
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    user32.GetClipboardSequenceNumber.argtypes = []
    user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalSize.restype = ctypes.c_size_t
    return user32, kernel32


def _global_bytes(kernel32, handle, limit: int) -> bytes | None:
    if not handle:
        return None
    size = int(kernel32.GlobalSize(handle) or 0)
    if size <= 0 or size > limit:
        return None
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        return None
    try:
        return ctypes.string_at(pointer, size)
    finally:
        kernel32.GlobalUnlock(handle)


def html_fragment(raw: bytes) -> str:
    """The HTML part of a Windows «HTML Format» block (header with byte offsets)."""
    head = raw[:400].decode("ascii", "ignore")
    start = re.search(r"StartHTML:(-?\d+)", head)
    end = re.search(r"EndHTML:(-?\d+)", head)
    if start and end and 0 <= int(start.group(1)) < int(end.group(1)) <= len(raw):
        raw = raw[int(start.group(1)):int(end.group(1))]
    return raw.split(b"\x00", 1)[0].decode("utf-8", "replace")


def read_clipboard() -> dict | None:
    """{"seq", "formats", "text", "html", "dib"} or None when the clipboard is empty."""
    if sys.platform != "win32":
        raise OSError("Windows only")
    user32, kernel32 = _api()
    sequence = int(user32.GetClipboardSequenceNumber())
    for _attempt in range(15):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.02)  # another program has it open for a moment
    else:
        raise OSError("The clipboard is busy")
    try:
        available = []
        formats = {}
        fmt = 0
        while True:
            fmt = int(user32.EnumClipboardFormats(fmt))
            if not fmt:
                break
            available.append(fmt)
            if fmt >= 0xC000 and len(available) < 200:
                buffer = ctypes.create_unicode_buffer(256)
                name = buffer.value if user32.GetClipboardFormatNameW(fmt, buffer, 256) else ""
                if any(marker in name.casefold() for marker in _MARKERS):
                    formats[name] = _global_bytes(kernel32, user32.GetClipboardData(fmt), 4096) or b""
        if not available:
            return None
        text = html = ""
        dib = None
        if CF_UNICODETEXT in available:
            raw = _global_bytes(kernel32, user32.GetClipboardData(CF_UNICODETEXT), MAX_TEXT_BYTES)
            if raw:
                text = raw.decode("utf-16-le", "replace").split("\x00", 1)[0]
        html_format = int(user32.RegisterClipboardFormatW("HTML Format"))
        if text and html_format in available:
            raw = _global_bytes(kernel32, user32.GetClipboardData(html_format), MAX_TEXT_BYTES * 3)
            if raw:
                html = html_fragment(raw)
        if not text and CF_DIB in available:
            dib = _global_bytes(kernel32, user32.GetClipboardData(CF_DIB), MAX_DIB_BYTES)
        return {"seq": sequence, "formats": formats, "text": text, "html": html, "dib": dib,
                "image": CF_DIB in available}
    finally:
        user32.CloseClipboard()


def dib_to_bmp(dib: bytes) -> bytes:
    """A complete BMP file from CF_DIB bytes (Qt's BMP reader then decodes it on any thread)."""
    if len(dib) < 40:
        raise ValueError("Short DIB")
    header_size = struct.unpack_from("<I", dib, 0)[0]
    bit_count = struct.unpack_from("<H", dib, 14)[0]
    compression = struct.unpack_from("<I", dib, 16)[0]
    colors_used = struct.unpack_from("<I", dib, 32)[0]
    masks = 12 if header_size == 40 and compression in (3, 6) else 0
    palette = (colors_used or (1 << bit_count)) * 4 if bit_count <= 8 else colors_used * 4
    offset = 14 + header_size + masks + palette
    return b"BM" + struct.pack("<IHHI", 14 + len(dib), 0, 0, offset) + dib
