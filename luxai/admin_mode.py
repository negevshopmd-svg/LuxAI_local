"""Run Jarvis with administrator rights, without a Windows prompt at every start.

Windows (UIPI) blocks ordinary programs from sending keys to, or reading text
from, programs started as administrator. When the user turns this on, Jarvis
creates ONE scheduled task with the highest privileges (one UAC prompt). Then
run_windows.bat and the Windows autostart start Jarvis through that task.

Turning it off deletes the task (one UAC prompt) and Jarvis starts normally.

Audit 2 #5: every installation folder has its OWN task («LuxAI Jarvis (admin) <id>»), and a task is
used, ended or deleted only after its XML shows it starts THIS folder. The old shared name
«LuxAI Jarvis (admin)» is still recognised when it belongs to this folder and is migrated away.
"""
from __future__ import annotations

import ctypes
import getpass
import hashlib
import html
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
LEGACY_TASK_NAME = "LuxAI Jarvis (admin)"
LEGACY_RUN_VALUE = "LuxAI_Jarvis"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def installation_id(root: Path = ROOT) -> str:
    """Short, stable id of this installation folder."""
    return hashlib.sha1(os.path.normcase(os.path.abspath(str(root))).encode("utf-8")).hexdigest()[:8]


def task_name(root: Path = ROOT) -> str:
    return f"{LEGACY_TASK_NAME} {installation_id(root)}"


TASK_NAME = task_name()


def run_value_name(root: Path = ROOT) -> str:
    """The Windows autostart (Run key) value of THIS installation."""
    return f"{LEGACY_RUN_VALUE}_{installation_id(root)}"


def name_file(root: Path = ROOT) -> Path:
    """run_windows.bat, Update.py and the installer read the task name from here."""
    return root / ".luxai_data" / "admin_task.txt"


def _same_folder(a: str, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a.strip().rstrip("\\/"))) == os.path.normcase(os.path.abspath(str(b)))


def task_belongs_here(name: str, root: Path = ROOT) -> bool:
    """The task exists AND its action starts Jarvis from this folder."""
    if sys.platform != "win32":
        return False
    try:
        result = subprocess.run(["schtasks", "/Query", "/TN", name, "/XML"], capture_output=True, timeout=20,
                                creationflags=_NO_WINDOW, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    raw = result.stdout
    text = raw.decode("utf-16", "ignore") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "ignore")
    folder = re.search(r"<WorkingDirectory>(.*?)</WorkingDirectory>", text, re.I | re.S)
    command = re.search(r"<Command>(.*?)</Command>", text, re.I | re.S)
    if not folder or not command or not _same_folder(html.unescape(folder.group(1)), root):
        return False
    exe = os.path.normcase(os.path.abspath(html.unescape(command.group(1)).strip().strip('"')))
    return exe.startswith(os.path.normcase(os.path.abspath(str(root))) + os.sep)


def our_tasks(root: Path = ROOT) -> list[str]:
    """Names of the admin tasks that start THIS folder (own name first, then the old shared one)."""
    return [name for name in (task_name(root), LEGACY_TASK_NAME) if task_belongs_here(name, root)]


def our_task(root: Path = ROOT) -> str | None:
    names = our_tasks(root)
    return names[0] if names else None


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


def task_exists(root: Path = ROOT) -> bool:
    """This installation has a working admin task (another folder's task does not count)."""
    return our_task(root) is not None


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _elevated_schtasks(arguments: str, timeout: float = 120, program: str = "schtasks.exe") -> bool:
    """Run schtasks.exe with the Windows elevation prompt; True on success.

    Blocks while the UAC prompt is open: callers in the UI run it on a worker thread (audit 2 #20).
    """
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
    info.lpFile = program
    info.lpParameters = arguments
    info.nShow = 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        return False  # the user said «No» or Windows refused
    kernel32 = ctypes.windll.kernel32
    finished = kernel32.WaitForSingleObject(info.hProcess, int(timeout * 1000)) == 0
    code = wintypes.DWORD()
    kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    kernel32.CloseHandle(info.hProcess)
    return finished and code.value == 0


def _write_name_file(root: Path, name: str | None) -> None:
    path = name_file(root)
    try:
        if name is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name, encoding="ascii")  # no newline: read by «set /p» in run_windows.bat
    except OSError:
        pass


def enable(root: Path = ROOT) -> bool:
    """Create/refresh THIS folder's task (one UAC prompt); an old shared task of this folder is removed with it."""
    name = task_name(root)
    path = Path(tempfile.mkdtemp()) / "luxai_jarvis_admin.xml"
    path.write_text(task_xml(root), encoding="utf-16")
    try:
        if task_belongs_here(LEGACY_TASK_NAME, root):
            # Same single prompt: create the own task, then delete the shared one that pointed here.
            ok = _elevated_schtasks(f'/d /s /c "schtasks /Create /TN "{name}" /XML "{path}" /F && '
                                    f'schtasks /Delete /TN "{LEGACY_TASK_NAME}" /F"', program="cmd.exe")
        else:
            ok = _elevated_schtasks(f'/Create /TN "{name}" /XML "{path}" /F')
    finally:
        try:
            path.unlink()
            path.parent.rmdir()
        except OSError:
            pass
    ok = ok and task_belongs_here(name, root)
    if ok:
        _write_name_file(root, name)
    return ok


def disable(root: Path = ROOT) -> bool:
    """Delete THIS folder's task(s) (one UAC prompt each). True when none is left; others are never touched."""
    for name in our_tasks(root):
        _elevated_schtasks(f'/Delete /TN "{name}" /F')
    left = task_exists(root)
    if not left:
        _write_name_file(root, None)
    return not left


def run_task(root: Path = ROOT) -> bool:
    """Start Jarvis through this folder's task (no prompt)."""
    name = our_task(root)
    if name is None:
        return False
    result = subprocess.run(["schtasks", "/Run", "/TN", name], capture_output=True, creationflags=_NO_WINDOW,
                            check=False)
    return result.returncode == 0


def autostart_command(root: Path = ROOT) -> str:
    """What the Windows autostart (Run key) should execute now."""
    name = our_task(root)
    if name is not None:
        return f'schtasks.exe /Run /TN "{name}"'
    exe, script = launcher(root)
    return f'"{exe}" "{script}"'


def autostart_value_is_ours(command: str, root: Path = ROOT) -> bool:
    """Does an autostart command start THIS folder (directly or through this folder's task)?"""
    text = os.path.normcase(str(command))
    if os.path.normcase(str(root / "launch_windows.py")) in text or os.path.normcase(str(root / "main.py")) in text:
        return True
    return any(f'"{os.path.normcase(name)}"' in text for name in our_tasks(root))


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
