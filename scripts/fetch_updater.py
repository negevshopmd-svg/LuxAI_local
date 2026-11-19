"""Download the updater safely (0.4.2r) — run by Update.bat from the INSTALLED copy.

Audit 2026-11-19 #8 and #28:
- Update.py is taken from the GitHub API for ONE exact commit of main (not a
  possibly cached raw URL) and its git blob hash is checked against the hash
  GitHub reports for that commit, then it is compiled before it may run.
  (This proves the file is exactly the one in the repository at that commit;
  it cannot protect against a compromised repository — that would need signed
  releases.)
- A bootstrap lock (.luxai_bootstrap.lock, with the owner's PID) stops a second
  Update.bat before it can touch the first one's files; the downloaded file gets
  a unique name, printed on stdout for Update.bat.

Exit codes: 0 ok, 2 network / check failed, 3 another update is running.
Standard library only.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import urllib.request
import uuid
from pathlib import Path

OWNER, REPO, BRANCH = "negevshopmd-svg", "LuxAI_local", "main"
API = f"https://api.github.com/repos/{OWNER}/{REPO}"
ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / ".luxai_bootstrap.lock"


def _get(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": "LuxAI-Updater",
                                                   "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read(8_000_000).decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("unexpected GitHub answer")
    return data


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.windll.kernel32.GetLastError() == 5  # exists, but not ours to open
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def take_lock(owner_pid: int) -> bool:
    for _ in range(2):
        try:
            handle = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                holder = int(LOCK.read_text(encoding="ascii").strip() or 0)
            except (OSError, ValueError):
                holder = 0
            if _pid_alive(holder):
                return False
            LOCK.unlink(missing_ok=True)  # a crashed Update.bat left it
            continue
        os.write(handle, str(owner_pid).encode("ascii"))
        os.close(handle)
        return True
    return False


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def fetch() -> Path:
    commit = _get(f"{API}/commits/{BRANCH}").get("sha", "")
    if not (isinstance(commit, str) and len(commit) == 40 and all(c in "0123456789abcdef" for c in commit)):
        raise ValueError("GitHub did not return a valid commit")
    meta = _get(f"{API}/contents/Update.py?ref={commit}")
    if meta.get("encoding") != "base64" or not isinstance(meta.get("content"), str):
        raise ValueError("unexpected file answer")
    data = base64.b64decode(meta["content"])
    if git_blob_sha(data) != meta.get("sha"):
        raise ValueError("Update.py does not match the hash GitHub reports for this commit")
    compile(data, "Update.py", "exec")
    target = ROOT / f"Update.{uuid.uuid4().hex[:10]}.new.py"
    target.write_bytes(data)
    return target


def parent_of(pid: int) -> int:
    """The parent PID (Windows Toolhelp); 0 when unknown."""
    if sys.platform != "win32":
        return 0
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

    kernel = ctypes.windll.kernel32
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snapshot = kernel.CreateToolhelp32Snapshot(0x2, 0)
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return 0
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(Entry)
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            if entry.th32ProcessID == pid:
                return int(entry.th32ParentProcessID)
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return 0


def main() -> int:
    # «for /f» runs us through a short-lived cmd.exe: the lock belongs to ITS parent, the Update.bat window.
    owner = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else (parent_of(os.getppid()) or os.getppid())
    if not take_lock(owner):
        print("BUSY")
        return 3
    try:
        target = fetch()
    except Exception as error:  # the bat shows the reason
        LOCK.unlink(missing_ok=True)
        print(f"ERROR {type(error).__name__}: {str(error)[:200]}")
        return 2
    print(target.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
