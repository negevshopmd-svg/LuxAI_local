"""Store the user's API key with Windows Data Protection API (DPAPI).

The key is never added to config.json or to the GitHub repository.
Windows encrypts the data for the current logged-in user. On non-Windows
systems, environment variables are supported, but keys are not stored here.
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SECRET_DIR = BASE / ".luxai_secrets"
SECRET_FILE = SECRET_DIR / "openai_key.dpapi"
ENV_NAME = "OPENAI_API_KEY"


class _Blob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _win_crypt(data: bytes, encrypt: bool) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("Encrypted API-key storage is available on Windows only")
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    src_buf = ctypes.create_string_buffer(data)
    src = _Blob(len(data), ctypes.cast(src_buf, ctypes.POINTER(ctypes.c_byte)))
    dest = _Blob()
    fn = crypt.CryptProtectData if encrypt else crypt.CryptUnprotectData
    fn.restype = wintypes.BOOL
    if encrypt:
        fn.argtypes = [
            ctypes.POINTER(_Blob), ctypes.c_wchar_p, ctypes.POINTER(_Blob),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob),
        ]
        ok = fn(ctypes.byref(src), "Jarvis API key", None, None, None, 0x01, ctypes.byref(dest))
    else:
        fn.argtypes = [
            ctypes.POINTER(_Blob), ctypes.POINTER(ctypes.c_wchar_p), ctypes.POINTER(_Blob),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob),
        ]
        ok = fn(ctypes.byref(src), None, None, None, None, 0x01, ctypes.byref(dest))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(dest.pbData, dest.cbData)
    finally:
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        kernel.LocalFree(ctypes.cast(dest.pbData, ctypes.c_void_p))


def get_api_key() -> str:
    """Environment variable takes precedence; otherwise decrypt the local secret."""
    key = os.environ.get(ENV_NAME, "").strip()
    if key:
        return key
    try:
        if SECRET_FILE.is_file():
            return _win_crypt(SECRET_FILE.read_bytes(), encrypt=False).decode("utf-8").strip()
    except (OSError, ValueError, UnicodeError, RuntimeError, AttributeError):
        return ""
    return ""


def has_api_key() -> bool:
    return bool(get_api_key())


def store_api_key(key: str) -> None:
    key = key.strip()
    if not key or len(key) > 512 or any(c in key for c in "\r\n"):
        raise ValueError("Invalid API key")
    encrypted = _win_crypt(key.encode("utf-8"), encrypt=True)
    SECRET_DIR.mkdir(parents=True, exist_ok=True)
    target = SECRET_FILE.with_suffix(".tmp")
    target.write_bytes(encrypted)
    target.replace(SECRET_FILE)


def clear_api_key() -> None:
    SECRET_FILE.unlink(missing_ok=True)
