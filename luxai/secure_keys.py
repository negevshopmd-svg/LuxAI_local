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

from luxai.api_providers import ENV_VARS, provider_config

BASE = Path(__file__).resolve().parents[1]
# Keep encrypted credentials in the signed-in Windows account's stable app data,
# independent of Desktop, project ZIP extraction and source updates.
LEGACY_SECRET_DIR = BASE / ".luxai_secrets"
SECRET_DIR = (
    Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    / "LuxAI_Local" / "secrets"
    if sys.platform == "win32" else LEGACY_SECRET_DIR
)
LEGACY_OPENAI_FILE = LEGACY_SECRET_DIR / "openai_key.dpapi"


def _secret_file(provider: str) -> Path:
    provider_config(provider)
    return SECRET_DIR / f"{provider}_key.dpapi"


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


def _legacy_secret_file(provider: str) -> Path:
    provider_config(provider)
    return LEGACY_SECRET_DIR / f"{provider}_key.dpapi"


def _saved_key(provider: str) -> str:
    """Read new per-user location, then older portable-app location."""
    for file in (_secret_file(provider), _legacy_secret_file(provider)):
        try:
            if file.is_file():
                key = _win_crypt(file.read_bytes(), encrypt=False).decode("utf-8").strip()
                if key:
                    return key
        except (OSError, ValueError, UnicodeError, RuntimeError, AttributeError):
            continue
    return ""


def key_storage_status(provider: str = "openai") -> str:
    """Present/missing/unreadable without ever exposing secret values."""
    provider_config(provider)
    if os.environ.get(ENV_VARS[provider], "").strip():
        return "environment"
    if _saved_key(provider):
        return "saved"
    if _secret_file(provider).exists() or _legacy_secret_file(provider).exists():
        return "unreadable"
    return "missing"


def get_api_key(provider: str = "openai") -> str:
    """Prefer encrypted key chosen in UI; fall back to an environment key."""
    provider_config(provider)
    stored = _saved_key(provider)
    if stored:
        return stored
    return os.environ.get(ENV_VARS[provider], "").strip()


def has_api_key(provider: str = "openai") -> bool:
    return bool(get_api_key(provider))


def store_api_key(key: str, provider: str = "openai") -> None:
    """DPAPI round-trip verified before replacing the previous saved key."""
    provider_config(provider)
    key = str(key).strip()
    if not key or len(key) > 2048 or any(ord(ch) < 33 or ord(ch) == 127 for ch in key):
        raise ValueError("Invalid API key")
    encrypted = _win_crypt(key.encode("utf-8"), encrypt=True)
    SECRET_DIR.mkdir(parents=True, exist_ok=True)
    target = _secret_file(provider)
    staging = target.with_name(target.name + ".tmp")
    try:
        staging.write_bytes(encrypted)
        actual = _win_crypt(staging.read_bytes(), encrypt=False).decode("utf-8")
        if actual != key:
            raise OSError("Encrypted API key could not be recovered after saving")
        staging.replace(target)
        if _saved_key(provider) != key:
            raise OSError("Saved API key verification failed")
    finally:
        staging.unlink(missing_ok=True)


def clear_api_key(provider: str = "openai") -> None:
    """Delete both app-data and previous-location secrets for this provider."""
    _secret_file(provider).unlink(missing_ok=True)
    previous = _legacy_secret_file(provider)
    if previous != _secret_file(provider):
        previous.unlink(missing_ok=True)
