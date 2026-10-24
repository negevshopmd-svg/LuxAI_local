"""Explicit Win32 ABI for window operations shared by Jarvis's desktop tools.

ctypes otherwise assumes C ``int`` arguments/returns. That truncates HWNDs on
64-bit Windows and cannot marshal Python strings to wide-character parameters.
One callback type also prevents EnumWindows signatures changing with call order.
Importing this module is safe on non-Windows test/development machines.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes


WNDENUMPROC = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
    wintypes.BOOL, wintypes.HWND, wintypes.LPARAM,
)
LRESULT = ctypes.c_ssize_t

_SIGNATURES = {
    "EnumWindows": ((WNDENUMPROC, wintypes.LPARAM), wintypes.BOOL),
    "GetForegroundWindow": ((), wintypes.HWND),
    "GetWindow": ((wintypes.HWND, wintypes.UINT), wintypes.HWND),
    "GetAncestor": ((wintypes.HWND, wintypes.UINT), wintypes.HWND),
    "FindWindowW": ((wintypes.LPCWSTR, wintypes.LPCWSTR), wintypes.HWND),
    "FindWindowExW": ((wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR), wintypes.HWND),
    "IsWindow": ((wintypes.HWND,), wintypes.BOOL),
    "IsWindowVisible": ((wintypes.HWND,), wintypes.BOOL),
    "IsIconic": ((wintypes.HWND,), wintypes.BOOL),
    "GetWindowThreadProcessId": ((wintypes.HWND, ctypes.POINTER(wintypes.DWORD)), wintypes.DWORD),
    "GetWindowTextLengthW": ((wintypes.HWND,), ctypes.c_int),
    "GetWindowTextW": ((wintypes.HWND, wintypes.LPWSTR, ctypes.c_int), ctypes.c_int),
    "GetClassNameW": ((wintypes.HWND, wintypes.LPWSTR, ctypes.c_int), ctypes.c_int),
    "GetWindowRect": ((wintypes.HWND, ctypes.POINTER(wintypes.RECT)), wintypes.BOOL),
    "ShowWindow": ((wintypes.HWND, ctypes.c_int), wintypes.BOOL),
    "ShowWindowAsync": ((wintypes.HWND, ctypes.c_int), wintypes.BOOL),
    "SetForegroundWindow": ((wintypes.HWND,), wintypes.BOOL),
    "BringWindowToTop": ((wintypes.HWND,), wintypes.BOOL),
    "SetWindowPos": ((wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                      ctypes.c_int, ctypes.c_int, wintypes.UINT), wintypes.BOOL),
    "GetSystemMetrics": ((ctypes.c_int,), ctypes.c_int),
    "WindowFromPoint": ((wintypes.POINT,), wintypes.HWND),
    "PostMessageW": ((wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM), wintypes.BOOL),
    "SendMessageW": ((wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM), LRESULT),
    "SendMessageTimeoutW": ((wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                             wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)), LRESULT),
    "GetClipboardSequenceNumber": ((), wintypes.DWORD),
    "LockWorkStation": ((), wintypes.BOOL),
}


def bind_user32(library):
    """Apply the same declarations before every use, independent of call order."""
    for name, (arguments, result) in _SIGNATURES.items():
        function = getattr(library, name, None)
        # Native _CFuncPtr objects need the ABI. Plain Python test doubles do
        # not perform ctypes conversion and may not support these attributes.
        if isinstance(function, ctypes._CFuncPtr):
            function.argtypes = arguments
            function.restype = result
    return library


def get_user32():
    """Return user32 with pointer-width HWNDs and correctly typed callbacks."""
    try:
        library = ctypes.windll.user32
    except AttributeError as exc:
        raise OSError("Windows window APIs are unavailable on this platform") from exc
    return bind_user32(library)


def hwnd_value(value) -> int:
    """Normalize either ctypes HWNDs or native int/NULL returns without loss."""
    if isinstance(value, ctypes.c_void_p):
        value = value.value
    return int(value or 0)


def window_on_screen(library, hwnd: int, *, minimum_width=20, minimum_height=20) -> bool:
    """Check actual window/virtual-desktop intersection without screen capture."""
    rect = wintypes.RECT()
    if not library.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    left = int(library.GetSystemMetrics(76))
    top = int(library.GetSystemMetrics(77))
    width = max(1, int(library.GetSystemMetrics(78)))
    height = max(1, int(library.GetSystemMetrics(79)))
    return (
        min(int(rect.right), left + width) - max(int(rect.left), left) >= minimum_width
        and min(int(rect.bottom), top + height) - max(int(rect.top), top) >= minimum_height
    )
