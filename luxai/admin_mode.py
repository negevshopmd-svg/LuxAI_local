"""Run Jarvis with administrator rights, without a Windows prompt at every start.

Windows (UIPI) blocks ordinary programs from sending keys to, or reading text
from, programs started as administrator. When the user turns this on, Jarvis
creates ONE scheduled task with the highest privileges (one UAC prompt). Then
run_windows.bat and the Windows autostart start Jarvis through that task.

Turning it off deletes the task (one UAC prompt) and Jarvis starts normally.
"""
from __future__ import annotations

import ctypes
import getpass
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
TASK_NAME = "LuxAI Jarvis (admin)"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def launcher(root: Path = ROOT) -> tuple[Path, Path]:
    """(executable, script) that start Jarvis: Jarvis.exe when ready, else pythonw."""
    scripts = root / ".venv" / "Scripts"
    jarvis = scripts / "Jarvis.exe"
    exe = jarvis if jarvis.is_file() and (scripts / "Jarvis.exe.stamp").is_file() else scripts / "pythonw.exe"
    return exe, root / "launch_windows.py"


def task_xml(root: Path = ROOT, user: str | None = None) -> str:
    exe, script = launcher(root)
    user = user or f"{os.environ.get('USERDOMAIN', '')}\\{getpass.getuser()}".lstrip("\\")
    return f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Starts Jarvis (LuxAI Local) with administrator rights without a prompt.</Description></RegistrationInfo>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>4</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(str(exe))}</Command>
      <Arguments>"{escape(str(script))}"</Arguments>
      <WorkingDirectory>{escape(str(root))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
'''


def task_exists() -> bool:
    if sys.platform != "win32":
        return False
    result = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME], capture_output=True,
                            creationflags=_NO_WINDOW)
    return result.returncode == 0


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _elevated_schtasks(arguments: str, timeout: float = 60) -> bool:
    """Run schtasks.exe with the Windows elevation prompt; True on success."""
    from ctypes import wintypes

    class SHELLEXECUTEINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    info = SHELLEXECUTEINFO()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = "schtasks.exe"
    info.lpParameters = arguments
    info.nShow = 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        return False  # the user said «No» or Windows refused
    kernel32 = ctypes.windll.kernel32
    kernel32.WaitForSingleObject(info.hProcess, int(timeout * 1000))
    code = wintypes.DWORD()
    kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    kernel32.CloseHandle(info.hProcess)
    return code.value == 0


def enable(root: Path = ROOT) -> bool:
    """Create/refresh the task (one UAC prompt)."""
    path = Path(tempfile.mkdtemp()) / "luxai_jarvis_admin.xml"
    path.write_text(task_xml(root), encoding="utf-16")
    try:
        ok = _elevated_schtasks(f'/Create /TN "{TASK_NAME}" /XML "{path}" /F')
    finally:
        try:
            path.unlink()
            path.parent.rmdir()
        except OSError:
            pass
    return ok and task_exists()


def disable() -> bool:
    """Delete the task (one UAC prompt). True when it is gone."""
    if not task_exists():
        return True
    _elevated_schtasks(f'/Delete /TN "{TASK_NAME}" /F')
    return not task_exists()


def run_task() -> bool:
    """Start Jarvis through the task (no prompt)."""
    if not task_exists():
        return False
    result = subprocess.run(["schtasks", "/Run", "/TN", TASK_NAME], capture_output=True, creationflags=_NO_WINDOW)
    return result.returncode == 0


def autostart_command(root: Path = ROOT) -> str:
    """What the Windows autostart (Run key) should execute now."""
    if task_exists():
        return f'schtasks.exe /Run /TN "{TASK_NAME}"'
    exe, script = launcher(root)
    return f'"{exe}" "{script}"'


def wait_until_running_elevated(timeout: float = 15.0) -> bool:
    """After run_task(): wait until an elevated Jarvis process appears."""
    import psutil
    end = time.monotonic() + timeout
    own = os.getpid()
    while time.monotonic() < end:
        for process in psutil.process_iter(["name", "pid", "cmdline"]):
            try:
                if process.info["pid"] == own:
                    continue
                cmdline = " ".join(process.info["cmdline"] or [])
                if "launch_windows.py" in cmdline and str(ROOT).casefold() in cmdline.casefold():
                    return True
            except (psutil.Error, OSError):
                continue
        time.sleep(0.3)
    return False
