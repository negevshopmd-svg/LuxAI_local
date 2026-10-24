"""Bounded Windows tools with host-owned user authorization and real evidence.

Cloud JSON describes a proposed operation; it cannot grant itself permission.
Ordinary, parsed local read-only commands run without another dialog. Other
scripts need an exact (shell, command) authorization supplied by the host for
the current user goal. This is deliberately not a regex sandbox for arbitrary
PowerShell. Process output is data, never a new source of instructions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from contextlib import contextmanager
import ctypes
import locale
import os
from pathlib import Path, PureWindowsPath
import re
import shlex
import subprocess
import sys
import threading
import time
from typing import Iterable


MAX_COMMAND_CHARS = 6000
MAX_OUTPUT_BYTES = 16384  # Per stream; readers drain excess without retaining it.
MAX_TIMEOUT_SECONDS = 60
PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
THEME_VALUES = ("AppsUseLightTheme", "SystemUsesLightTheme")
_power_lock = threading.Lock()
_READBACK_PROPERTIES = {
    name.casefold() for name in (
        "Name", "Id", "ProcessName", "ProcessId", "Responding", "CPU", "WorkingSet", "WorkingSet64",
        "PrivateMemorySize64", "StartTime", "MainWindowTitle", "MainWindowHandle", "Path", "Company",
        "Description", "FileVersion", "ProductVersion", "Status", "DisplayName", "ServiceName",
        "StartType", "CanStop", "AppID", "CommandType", "Source", "Caption", "Version",
        "OSArchitecture", "BuildNumber", "LastBootUpTime", "FreePhysicalMemory", "TotalVisibleMemorySize",
        "NumberOfLogicalProcessors", "Manufacturer", "Model", "DeviceID", "PNPDeviceID",
        "InterfaceAlias", "InterfaceIndex", "IPAddress", "AddressFamily", "PrefixLength",
        "PrefixOrigin", "SuffixOrigin", "Dhcp", "MacAddress", "LinkSpeed", "DnsSuffix", "ServerAddresses",
        "FullName", "DirectoryName", "BaseName", "Extension", "Length", "LastWriteTime", "CreationTime",
        "Attributes", "Mode", "Count", "Year", "Month", "Day", "DayOfWeek", "Hour", "Minute", "Second",
        "WindowsProductName", "WindowsVersion", "CsManufacturer", "CsModel", "CsNumberOfLogicalProcessors",
        "OsName", "OsVersion", "OsArchitecture", "OsBuildNumber", "OsLastBootUpTime", "OsFreePhysicalMemory",
    )
}


@dataclass(frozen=True)
class GoalAuthorization:
    goal: str
    source: str = "user"
    allow_power_actions: bool = False
    approved_commands: frozenset[tuple[str, str]] = frozenset()


def make_authorization(
    goal: str, *, source: str = "user", allow_power_actions: bool = False,
    approved_commands: Iterable[tuple[str, str]] = (),
) -> GoalAuthorization:
    """Call only with host-owned user intent, never deserialized planner flags."""
    if not isinstance(goal, str) or not 1 <= len(goal.strip()) <= 4000:
        raise ValueError("A current user goal is required")
    if source not in {"user", "web", "screen", "tool", "model"}:
        raise ValueError("Unknown instruction source")
    approved = set()
    for entry in approved_commands:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            raise ValueError("Approved commands must be exact (shell, command) pairs")
        shell, command = entry
        if shell not in {"cmd", "powershell"} or not isinstance(command, str) or not command.strip():
            raise ValueError("Invalid approved command")
        approved.add((shell, command.strip()))
    return GoalAuthorization(goal.strip(), source, bool(allow_power_actions), frozenset(approved))


@dataclass
class ShellResult:
    status: str
    summary: str
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    verified: bool = False
    question: str = ""
    timed_out: bool = False
    cancelled: bool = False
    truncated: bool = False
    verification_stdout: str = ""
    verification_stderr: str = ""
    verification_exit_code: int | None = None
    details: dict = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status == "success"

    def to_dict(self) -> dict:
        result = asdict(self)
        result["success"] = self.success
        result["output_source"] = "local_process_output"
        result["output_is_instruction"] = False
        return result


class ShellValidationError(ValueError):
    def __init__(self, message: str, *, needs_authorization: bool = False, question: str = ""):
        super().__init__(message)
        self.needs_authorization = needs_authorization
        self.question = question


@dataclass(frozen=True)
class ShellPlan:
    shell: str
    command: str
    purpose: str
    verification_shell: str = ""
    verification_command: str = ""
    expect: str = ""
    read_only: bool = False


def _require_user(authorization: GoalAuthorization) -> None:
    if not isinstance(authorization, GoalAuthorization) or authorization.source != "user":
        raise ShellValidationError("Only the current user's instruction can authorize local commands")


def _command_text(value, label="command") -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= MAX_COMMAND_CHARS:
        raise ShellValidationError(f"Invalid {label}")
    text = value.strip()
    if any(char in text for char in ("\0", "\r", "\n")):
        raise ShellValidationError("Use one explicit command, without hidden lines")
    return text


def _ps_tokens(command: str) -> list[list[tuple[str, bool]]]:
    """Parse a small argument/pipeline grammar, not general PowerShell syntax."""
    stages: list[list[tuple[str, bool]]] = [[]]
    index = 0
    while index < len(command):
        char = command[index]
        if char.isspace():
            index += 1
            continue
        if char == "|":
            if not stages[-1]:
                raise ValueError("Empty pipeline stage")
            stages.append([])
            index += 1
            continue
        if char in "'\"":
            quote = char
            index += 1
            value = []
            while index < len(command):
                char = command[index]
                if char == quote:
                    if quote == "'" and index + 1 < len(command) and command[index + 1] == "'":
                        value.append("'")
                        index += 2
                        continue
                    index += 1
                    break
                if quote == '"' and char in "$`":
                    raise ValueError("Interpolation is not a literal argument")
                value.append(char)
                index += 1
            else:
                raise ValueError("Unclosed quote")
            if index < len(command) and not command[index].isspace() and command[index] != "|":
                raise ValueError("Concatenated expressions are not literal arguments")
            stages[-1].append(("".join(value), True))
            continue
        start = index
        while index < len(command) and not command[index].isspace() and command[index] != "|":
            if command[index] in ";&<>`$(){}[]'\"":
                raise ValueError("Expressions, invocation and redirection are not allowed")
            index += 1
        stages[-1].append((command[start:index], False))
    if not stages[-1] or len(stages) > 4:
        raise ValueError("Invalid pipeline")
    return stages


def _local_path(value: str) -> bool:
    # UNC paths can perform network authentication even during a read operation.
    if not value or value.startswith(("\\\\", "//")):
        return False
    path = PureWindowsPath(value)
    if ":" in value and not re.match(r"^[A-Za-z]:[\\/]", value):
        return False
    sensitive = {".ssh", ".aws", ".azure", ".gnupg", ".kube", "credentials", "secrets", ".luxai_secrets"}
    return not any(part.casefold() in sensitive for part in path.parts)


def _identifier_list(value: str) -> bool:
    return all(
        re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item)
        and item.casefold() in _READBACK_PROPERTIES
        for item in value.split(",")
    )


def _parameters(tokens: list[tuple[str, bool]], allowed: dict[str, str], positional: str = "") -> bool:
    position = 1
    positional_used = False
    while position < len(tokens):
        token, quoted = tokens[position]
        name = token.casefold()
        if not quoted and name.startswith("-"):
            kind = allowed.get(name)
            if kind is None:
                return False
            position += 1
            if kind == "flag":
                continue
            if position >= len(tokens):
                return False
            value = tokens[position][0]
        else:
            if not positional or positional_used:
                return False
            positional_used = True
            kind, value = positional, token
        if kind == "path" and not _local_path(value):
            return False
        if kind == "identifier" and not _identifier_list(value):
            return False
        if kind == "number" and (not value.isdecimal() or not 1 <= int(value) <= 1000):
            return False
        if kind == "name" and not re.fullmatch(r"[A-Za-z0-9_.*? -]{1,200}", value):
            return False
        if kind == "class" and value.casefold() not in {
            "win32_operatingsystem", "win32_computersystem", "win32_videocontroller", "win32_sounddevice",
        }:
            return False
        if kind == "commandtype" and value.casefold() not in {"application", "cmdlet"}:
            return False
        if kind == "pathtype" and value.casefold() not in {"leaf", "container", "any"}:
            return False
        position += 1
    return True


def _readonly_powershell(command: str, *, verification: bool = False) -> bool:
    try:
        stages = _ps_tokens(command)
    except ValueError:
        return False
    first, quoted = stages[0][0]
    if quoted:
        return False
    base = first.casefold()
    options = {
        "get-date": ({"-format": "name", "-asutc": "flag"}, ""),
        "get-process": ({"-name": "name", "-id": "number"}, "name"),
        "get-service": ({"-name": "name", "-displayname": "name"}, "name"),
        "get-startapps": ({"-name": "name"}, "name"),
        "get-command": ({"-name": "name", "-commandtype": "commandtype"}, "name"),
        "get-computerinfo": ({"-property": "identifier"}, ""),
        "get-ciminstance": ({"-classname": "class"}, "class"),
        "get-childitem": ({"-literalpath": "path", "-path": "path", "-filter": "name", "-recurse": "flag", "-file": "flag", "-directory": "flag", "-name": "flag"}, "path"),
        "test-path": ({"-literalpath": "path", "-path": "path", "-pathtype": "pathtype"}, "path"),
        "get-netadapter": ({"-name": "name"}, "name"),
        "get-netipaddress": ({"-interfacealias": "name"}, ""),
        "get-dnsclientserveraddress": ({"-interfacealias": "name"}, ""),
    }
    if base not in options or not _parameters(stages[0], *options[base]):
        return False
    if base in {"get-ciminstance", "test-path"} and len(stages[0]) == 1:
        return False
    projected = False
    for stage in stages[1:]:
        name, quoted = stage[0]
        name = name.casefold()
        if quoted:
            return False
        if name in {"select-object", "sort-object", "format-table", "format-list"}:
            if not _parameters(stage, {"-property": "identifier", "-first": "number", "-descending": "flag", "-autosize": "flag"}, "identifier"):
                return False
            # JSON serialization may otherwise expose deep object properties.
            if name == "select-object":
                projected = projected or any(not value.startswith("-") and _identifier_list(value) for value, _ in stage[1:])
        elif name == "convertto-json":
            if not projected or not _parameters(stage, {"-compress": "flag"}):
                return False
        elif name == "out-string":
            if not _parameters(stage, {"-width": "number"}):
                return False
        elif name == "measure-object":
            if len(stage) != 1:
                return False
        else:
            return False
    return True


def _readonly_cmd(command: str, *, verification: bool = False) -> bool:
    if any(char in command for char in "&|<>^%!`\r\n"):
        return False
    try:
        tokens = shlex.split(command, posix=False)
    except ValueError:
        return False
    if not tokens:
        return False
    executable = tokens[0].casefold().removesuffix(".exe")
    args = [item.strip('"') for item in tokens[1:]]
    if executable in {"ver", "hostname", "systeminfo"}:
        return not args
    if executable == "whoami":
        return all(arg.casefold() in {"/all", "/user", "/groups", "/priv", "/fo", "list", "csv", "table", "/nh"} for arg in args)
    if executable == "ipconfig":
        return all(arg.casefold() in {"/all", "/displaydns"} for arg in args)
    if executable == "tasklist":
        index = 0
        while index < len(args):
            flag = args[index].casefold()
            if flag in {"/nh", "/v", "/svc", "/apps"}:
                index += 1
                continue
            if flag not in {"/fi", "/fo"} or index + 1 >= len(args):
                return False
            value = args[index + 1]
            if flag == "/fo" and value.casefold() not in {"list", "csv", "table"}:
                return False
            if flag == "/fi" and not re.fullmatch(r"[A-Za-z0-9_ .,*=:/-]{1,200}", value):
                return False
            index += 2
        return True
    if executable == "where":
        return bool(args) and all(re.fullmatch(r"[A-Za-z0-9_.*? /:\\-]{1,300}", arg) and _local_path(arg) for arg in args)
    if executable == "dir":
        flags = {"/a", "/a:d", "/a:-d", "/b", "/s", "/o:n", "/t:w", "/-c"}
        return all(arg.casefold() in flags if arg.startswith("/") else _local_path(arg) for arg in args)
    if executable == "powercfg":
        if not args:
            return False
        operation = args[0].casefold()
        if operation in {"/getactivescheme", "/list"}:
            return len(args) == 1
        if operation == "/query":
            # Query operands are scheme/subgroup GUIDs or documented aliases,
            # never another operation switch such as /setactive or /change.
            return len(args) <= 3 and all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}", arg) for arg in args[1:])
        return False
    return False


def command_is_read_only(shell: str, command: str, *, verification: bool = False) -> bool:
    return _readonly_powershell(command, verification=verification) if shell == "powershell" else shell == "cmd" and _readonly_cmd(command, verification=verification)


def validate_shell_plan(raw: dict, authorization: GoalAuthorization) -> ShellPlan:
    _require_user(authorization)
    if not isinstance(raw, dict) or set(raw) - {"shell", "command", "purpose", "verification", "goal"}:
        raise ShellValidationError("Invalid shell plan fields")
    if raw.get("goal", authorization.goal) != authorization.goal:
        raise ShellValidationError("This plan belongs to a different user goal")
    shell = raw.get("shell")
    if shell not in {"cmd", "powershell"}:
        raise ShellValidationError("Choose cmd or powershell")
    command = _command_text(raw.get("command"))
    purpose = raw.get("purpose")
    if not isinstance(purpose, str) or not 1 <= len(purpose.strip()) <= 1000:
        raise ShellValidationError("The plan must explain its purpose")
    read_only = command_is_read_only(shell, command)
    if not read_only and (shell, command) not in authorization.approved_commands:
        question = f"Allow this exact {shell} command for '{authorization.goal}'?\n{command}"
        raise ShellValidationError("This command needs scoped user authorization", needs_authorization=True, question=question)
    # Do not add elevation flags, execution-policy bypasses or RunAs wrappers.
    if re.search(r"(?i)(?:\b(?:bypass|encodedcommand|runas|psexec)\b|\b-verb\s+['\"]?runas|\buac\b)", command):
        raise ShellValidationError("This tool does not bypass permissions or elevate execution")
    check = raw.get("verification")
    check_shell = check_command = expect = ""
    if check is not None:
        if not isinstance(check, dict) or set(check) - {"shell", "command", "expect"}:
            raise ShellValidationError("Invalid readback verification")
        check_shell = check.get("shell", shell)
        check_command = _command_text(check.get("command"), "verification command")
        if check_shell not in {"cmd", "powershell"} or not command_is_read_only(check_shell, check_command, verification=True):
            raise ShellValidationError("Verification must be a parsed local read-only observation")
        expect = check.get("expect", "")
        if not isinstance(expect, str) or len(expect) > 500:
            raise ShellValidationError("Invalid expected readback")
    if not read_only and not check_command:
        raise ShellValidationError("A changing command needs an independent read-only verification")
    if not read_only and not expect.strip():
        raise ShellValidationError("A changing command needs an expected readback value")
    return ShellPlan(shell, command, purpose.strip(), check_shell, check_command, expect, read_only)


class _Capture:
    def __init__(self, limit: int):
        self.limit = limit
        self.data = bytearray()
        self.truncated = False
        self.error = False

    def drain(self, stream) -> None:
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    return
                remaining = self.limit - len(self.data)
                self.data.extend(chunk[:max(0, remaining)])
                self.truncated = self.truncated or len(chunk) > remaining
        except (OSError, ValueError):
            self.error = True


def _decode(data: bytearray, encoding: str = "") -> str:
    if encoding:
        return bytes(data).decode(encoding, errors="replace").lstrip("\ufeff")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return bytes(data).decode("utf-16", errors="replace")
    try:
        return bytes(data).decode("utf-8")
    except UnicodeDecodeError:
        try:
            encoding = "cp" + str(ctypes.windll.kernel32.GetOEMCP()) if sys.platform == "win32" else ""
        except (AttributeError, OSError):
            encoding = ""
        return bytes(data).decode(encoding or locale.getpreferredencoding(False) or "cp1252", errors="replace")


def _stop_process(process) -> None:
    if process.poll() is not None:
        return
    try:
        subprocess.run(
            [_windows_executable("taskkill.exe"), "/PID", str(process.pid), "/T", "/F"],
            shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=3, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _run(args: list[str], *, timeout: float, cancel_event=None, output_limit=MAX_OUTPUT_BYTES) -> ShellResult:
    if cancel_event is not None and cancel_event.is_set():
        return ShellResult("cancelled", "Cancelled before starting", cancelled=True)
    try:
        process = subprocess.Popen(
            args, shell=False, cwd=str(Path.home()), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    except OSError as exc:
        return ShellResult("failed", "Windows could not start the command", stderr=str(exc))
    stdout, stderr = _Capture(output_limit), _Capture(output_limit)
    readers = [
        threading.Thread(target=capture.drain, args=(stream,), daemon=True, name="LuxAIShellOutput")
        for capture, stream in ((stdout, process.stdout), (stderr, process.stderr))
    ]
    for reader in readers:
        reader.start()
    deadline = time.monotonic() + timeout
    timed_out = cancelled = False
    while process.poll() is None:
        cancelled = cancel_event is not None and cancel_event.is_set()
        timed_out = time.monotonic() >= deadline
        if cancelled or timed_out:
            _stop_process(process)
            break
        time.sleep(0.025)
    for reader in readers:
        reader.join(timeout=0.25)
    open_output = any(reader.is_alive() for reader in readers)
    for reader, stream in zip(readers, (process.stdout, process.stderr)):
        if not reader.is_alive():
            stream.close()
    code = process.poll()
    status = "cancelled" if cancelled else "timeout" if timed_out else "success" if code == 0 else "failed"
    executable = PureWindowsPath(args[0]).name.casefold()
    encoding = "utf-8" if executable == "powershell.exe" else "utf-16-le" if executable == "cmd.exe" and "/u" in args else ""
    return ShellResult(
        status, "Command cancelled" if cancelled else "Command timed out" if timed_out else f"Command exited with code {code}",
        exit_code=code, stdout=_decode(stdout.data, encoding), stderr=_decode(stderr.data, encoding),
        timed_out=timed_out, cancelled=cancelled, truncated=stdout.truncated or stderr.truncated,
        details={"output_complete": not open_output and not stdout.error and not stderr.error},
    )


def _windows_executable(name: str) -> str:
    root = PureWindowsPath(os.environ.get("SystemRoot", r"C:\Windows"))
    if not root.is_absolute():
        root = PureWindowsPath(r"C:\Windows")
    if name == "explorer.exe":
        return str(root / name)
    if name == "powershell.exe":
        return str(root / "System32" / "WindowsPowerShell" / "v1.0" / name)
    return str(root / "System32" / name)


def _shell_args(shell: str, command: str) -> list[str]:
    if shell == "powershell":
        # A non-terminating error followed by a successful formatting stage
        # must not look like a successful observation merely because exit=0.
        utf8 = "$ErrorActionPreference = 'Stop'; $OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
        return [_windows_executable("powershell.exe"), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", utf8 + command]
    if command_is_read_only("cmd", command):
        tokens = shlex.split(command, posix=False)
        executable = tokens[0].casefold().removesuffix(".exe")
        if executable not in {"dir", "ver"}:
            # Known native queries do not need CMD parsing or PATH lookup.
            return [_windows_executable(executable + ".exe"), *(arg.strip('"') for arg in tokens[1:])]
    return [_windows_executable("cmd.exe"), "/u", "/d", "/s", "/c", command]


def execute_shell_plan(
    raw: dict, authorization: GoalAuthorization, *, cancel_event=None,
    timeout: float = 20, output_limit: int = MAX_OUTPUT_BYTES,
) -> ShellResult:
    try:
        plan = validate_shell_plan(raw, authorization)
    except ShellValidationError as exc:
        return ShellResult("needs_authorization" if exc.needs_authorization else "failed", str(exc), question=exc.question)
    if sys.platform != "win32":
        return ShellResult("unsupported", "Local CMD and PowerShell execution is available only on Windows")
    if not isinstance(timeout, (int, float)) or not 0 < timeout <= MAX_TIMEOUT_SECONDS:
        return ShellResult("failed", "Invalid command timeout")
    if not isinstance(output_limit, int) or not 256 <= output_limit <= MAX_OUTPUT_BYTES:
        return ShellResult("failed", "Invalid output limit")
    result = _run(_shell_args(plan.shell, plan.command), timeout=timeout, cancel_event=cancel_event, output_limit=output_limit)
    if not result.success:
        return result
    result.details.update({"purpose": plan.purpose, "goal": authorization.goal, "read_only": plan.read_only})
    if plan.verification_command:
        check = _run(_shell_args(plan.verification_shell, plan.verification_command), timeout=timeout, cancel_event=cancel_event, output_limit=output_limit)
        result.verification_stdout, result.verification_stderr = check.stdout, check.stderr
        result.verification_exit_code = check.exit_code
        result.truncated = result.truncated or check.truncated
        result.verified = bool(check.success and check.details.get("output_complete") and not check.truncated and (not plan.expect or plan.expect.casefold() in check.stdout.casefold()))
        if check.cancelled or check.timed_out:
            result.status, result.cancelled, result.timed_out = check.status, check.cancelled, check.timed_out
        elif not result.verified:
            result.status = "failed"
    else:
        result.verified = bool(plan.read_only and result.details.get("output_complete") and not result.truncated)
    result.summary = "Local readback verified" if result.verified else "Command completed; the requested result has not been verified"
    return result


def capabilities() -> dict:
    return {
        "platform": "Windows", "shells": ["cmd", "powershell"],
        "automatic": "Parsed local read-only commands and explicit typed user operations",
        "other_commands": "Exact scoped (shell, command) authorization and read-only readback required",
        "elevation": False,
        "night_light": {"read": False, "set": False, "open_settings": True, "reason": "No stable supported Night Light state API is used; undocumented registry blobs are not modified"},
        "theme": {"read": True, "set_current_user_dark_theme": True},
        "power": ["shutdown", "restart", "sleep", "lock", "cancel_shutdown"],
    }


def _power_intent(goal: str, action: str) -> bool:
    text = goal.casefold()
    if re.search(r"\b(?:don['’]t|do\s+not|never|no\s+(?:shutdown|restart|reboot|sleep|lock)|nu|what|explain|how|cum|ce înseamnă|ce inseamna|не|как|что)\b", text):
        return False
    patterns = {
        "shutdown": r"(?:^(?:please\s+)?(?:shutdown|shut\s+down)[.!]?\s*$|\b(?:shutdown|shut\s+down|turn\s+off)\s+(?:(?:the|my|this)\s+)?(?:pc|computer|laptop)\b|\b(?:oprește|opreste|închide|inchide)\b.{0,35}\b(?:calculator|computer|pc|laptop)|выключ\w*.{0,35}(?:компьютер|пк|ноутбук))",
        "restart": r"(?:^(?:please\s+)?(?:restart|reboot)[.!]?\s*$|\b(?:restart|reboot)\s+(?:(?:the|my|this)\s+)?(?:pc|computer|laptop)\b|\breporne(?:ște|ste)\b.{0,35}(?:calculator|computer|pc|laptop)|перезагруз\w*.{0,35}(?:компьютер|пк|ноутбук))",
        "sleep": r"(?:^(?:please\s+)?(?:sleep|suspend)[.!]?\s*$|\b(?:pc|computer|laptop)\b.{0,25}\b(?:sleep|suspend)\b|\b(?:calculator|computer|pc|laptop)\w*.{0,25}\b(?:repaus|somn)\b|(?:компьютер|пк|ноутбук).{0,25}(?:спящ|сон)|усып\w*.{0,25}(?:компьютер|пк|ноутбук))",
        "lock": r"(?:\block\b.{0,25}\b(?:screen|computer|pc)|\bblocheaz[ăa]\b.{0,25}\b(?:ecran|calculator|pc)|заблокир\w*.{0,25}(?:экран|компьютер|пк))",
        "cancel_shutdown": r"(?:\bcancel\b.{0,25}\b(?:shutdown|restart)|\banuleaz[ăa]\b.{0,25}\b(?:oprirea|repornirea)|отмен\w*.{0,25}(?:выключ|перезагруз))",
    }
    if action in {"shutdown", "restart"} and re.search(patterns["cancel_shutdown"], text):
        return False
    return bool(re.search(patterns[action], text))


def _theme_intent(goal: str, dark: bool) -> bool:
    text = goal.casefold()
    if re.search(r"\b(?:don['’]t|do\s+not|never|no\s+(?:dark|light|theme)|nu(?!\s+mai\b)|не|what|explain|how|cum|ce înseamnă|ce inseamna|как|что)\b", text):
        return False
    if not re.search(r"(?:theme|tem[ăa]|тема|режим|\bmode\b|\bmod\b)", text):
        return False
    requested_dark = bool(re.search(r"(?:\bdark\b|întunec|intunec|темн)", text))
    requested_light = bool(re.search(r"(?:\blight\b|luminos|deschis|светл)", text))
    if requested_dark == requested_light:
        return False
    disabling = bool(re.search(r"(?:\bdisable\b|\bturn\s+off\b|dezactiveaz|\bnu mai\b|выключ|отключ)", text))
    return dark == (not requested_dark if disabling else requested_dark)


def _theme_preferences() -> dict:
    import winreg
    values = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE_KEY, 0, winreg.KEY_READ) as key:
            for name in THEME_VALUES:
                try:
                    value, _ = winreg.QueryValueEx(key, name)
                    values[name] = int(value) if value in (0, 1) else None
                except FileNotFoundError:
                    values[name] = None
    except FileNotFoundError:
        values = dict.fromkeys(THEME_VALUES)
    return values


def _set_theme(dark: bool) -> dict:
    import winreg
    previous = {}
    changed = []
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, PERSONALIZE_KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
        for name in THEME_VALUES:
            try:
                previous[name] = winreg.QueryValueEx(key, name)
            except FileNotFoundError:
                previous[name] = None
        try:
            for name in THEME_VALUES:
                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, 0 if dark else 1)
                changed.append(name)
        except OSError:
            for name in reversed(changed):
                if previous[name] is None:
                    winreg.DeleteValue(key, name)
                else:
                    value, value_type = previous[name]
                    winreg.SetValueEx(key, name, 0, value_type, value)
            raise
    # Broadcast the documented settings-change message; persistence is checked
    # separately, and applications may still require reopening to repaint.
    try:
        from ctypes import wintypes
        sender = ctypes.windll.user32.SendMessageTimeoutW
        sender.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM, wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t))
        sender.restype = wintypes.LPARAM
        value = ctypes.create_unicode_buffer("ImmersiveColorSet")
        result = ctypes.c_size_t()
        sender(0xFFFF, 0x001A, 0, ctypes.cast(value, ctypes.c_void_p).value, 0x0002, 1000, ctypes.byref(result))
    except (AttributeError, OSError):
        pass
    return _theme_preferences()


@contextmanager
def _shutdown_privilege():
    """Temporarily enable an already-granted right; never request elevation."""
    from ctypes import wintypes

    class LUID(ctypes.Structure):
        _fields_ = (("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG))

    class LUID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = (("Luid", LUID), ("Attributes", wintypes.DWORD))

    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = (("PrivilegeCount", wintypes.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1))

    api = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    token = wintypes.HANDLE()
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    api.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
    api.LookupPrivilegeValueW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(LUID))
    api.AdjustTokenPrivileges.argtypes = (wintypes.HANDLE, wintypes.BOOL, ctypes.POINTER(TOKEN_PRIVILEGES), wintypes.DWORD, ctypes.POINTER(TOKEN_PRIVILEGES), ctypes.POINTER(wintypes.DWORD))
    if not api.OpenProcessToken(kernel.GetCurrentProcess(), 0x0020 | 0x0008, ctypes.byref(token)):
        raise OSError(ctypes.get_last_error(), "Windows denied access to the current process token")
    previous = TOKEN_PRIVILEGES()
    changed = False
    try:
        requested = TOKEN_PRIVILEGES()
        requested.PrivilegeCount = 1
        requested.Privileges[0].Attributes = 0x00000002  # SE_PRIVILEGE_ENABLED
        if not api.LookupPrivilegeValueW(None, "SeShutdownPrivilege", ctypes.byref(requested.Privileges[0].Luid)):
            raise OSError(ctypes.get_last_error(), "Windows could not look up the shutdown right")
        length = wintypes.DWORD()
        ctypes.set_last_error(0)
        if not api.AdjustTokenPrivileges(token, False, ctypes.byref(requested), ctypes.sizeof(previous), ctypes.byref(previous), ctypes.byref(length)):
            raise OSError(ctypes.get_last_error(), "Windows denied the shutdown right")
        error = ctypes.get_last_error()
        if error:
            raise OSError(error, "The current user has not been granted the shutdown right")
        changed = True
        yield
    finally:
        if changed:
            api.AdjustTokenPrivileges(token, False, ctypes.byref(previous), 0, None, None)
        kernel.CloseHandle(token)


def _request_shutdown(action: str, delay_seconds: int) -> tuple[bool, int]:
    """Use the documented graceful API; shutdown.exe /t > 0 implies /f."""
    from ctypes import wintypes
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    initiate = api.InitiateSystemShutdownExW
    initiate.argtypes = (wintypes.LPWSTR, wintypes.LPWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.BOOL, wintypes.DWORD)
    initiate.restype = wintypes.BOOL
    with _power_lock, _shutdown_privilege():
        accepted = bool(initiate(None, "Jarvis: user-requested power action", delay_seconds, False, action == "restart", 0x80040000))
        error = 0 if accepted else ctypes.get_last_error()
    return accepted, error


def _cancel_shutdown() -> tuple[bool, int]:
    from ctypes import wintypes
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    cancel = api.AbortSystemShutdownW
    cancel.argtypes = (wintypes.LPWSTR,)
    cancel.restype = wintypes.BOOL
    with _power_lock, _shutdown_privilege():
        accepted = bool(cancel(None))
        error = 0 if accepted else ctypes.get_last_error()
    return accepted, error


def execute_builtin(
    action: str, authorization: GoalAuthorization, *, enabled: bool | None = None,
    delay_seconds: int = 30, cancel_event=None,
) -> ShellResult:
    try:
        _require_user(authorization)
    except ShellValidationError as exc:
        return ShellResult("failed", str(exc))
    if sys.platform != "win32":
        return ShellResult("unsupported", "This local Windows tool is unavailable on this platform")
    if cancel_event is not None and cancel_event.is_set():
        return ShellResult("cancelled", "Cancelled before starting", cancelled=True)
    if action in {"shutdown", "restart", "sleep", "lock", "cancel_shutdown"}:
        if not authorization.allow_power_actions or not _power_intent(authorization.goal, action):
            return ShellResult("needs_authorization", "The current user must explicitly request this power action", question=f"Do you want Windows to {action.replace('_', ' ')}?")
        if action in {"shutdown", "restart"}:
            if not isinstance(delay_seconds, int) or not 30 <= delay_seconds <= 300:
                return ShellResult("failed", "Choose a cancellation delay from 30 to 300 seconds")
            try:
                accepted, error = _request_shutdown(action, delay_seconds)
            except (AttributeError, OSError) as exc:
                return ShellResult("failed", "Windows could not schedule the power request", stderr=str(exc))
            return ShellResult(
                "success" if accepted else "failed",
                f"Windows accepted a graceful {action} request with a {delay_seconds}-second cancellation window; the computer is not confirmed off" if accepted else "Windows denied the power request; administrator permissions were not bypassed",
                exit_code=error, verified=accepted,
                details={"pending_action": action if accepted else None, "delay_seconds": delay_seconds, "verification_kind": "windows_request_acknowledged", "force_close_apps": False, "cancel_action": "cancel_shutdown"},
            )
        if action == "cancel_shutdown":
            try:
                accepted, error = _cancel_shutdown()
            except (AttributeError, OSError) as exc:
                return ShellResult("failed", "Windows could not cancel the power request", stderr=str(exc))
            return ShellResult("success" if accepted else "failed", "Windows confirmed cancellation of the pending shutdown/restart" if accepted else "Windows did not confirm cancellation of a pending shutdown/restart", exit_code=error, verified=accepted)
        try:
            if action == "lock":
                lock = ctypes.windll.user32.LockWorkStation
                from ctypes import wintypes
                lock.argtypes = ()
                lock.restype = wintypes.BOOL
                accepted = bool(lock())
            else:
                with _power_lock, _shutdown_privilege():
                    suspend = ctypes.windll.powrprof.SetSuspendState
                    suspend.argtypes = (ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_ubyte)
                    suspend.restype = ctypes.c_ubyte
                    accepted = bool(suspend(False, False, False))
        except (AttributeError, OSError) as exc:
            return ShellResult("failed", "Windows rejected the power request", stderr=str(exc))
        return ShellResult("success" if accepted else "failed", f"Windows {'accepted' if accepted else 'rejected'} the {action} request; resulting screen/power state is not independently verified", details={"request_accepted": accepted})
    if action == "get_theme":
        try:
            values = _theme_preferences()
        except OSError as exc:
            return ShellResult("failed", "Could not read the current user's theme preferences", stderr=str(exc))
        return ShellResult("success", "Read the current user's Windows theme preferences", verified=True, stdout=str(values), details=values)
    if action == "set_dark_theme":
        if not isinstance(enabled, bool) or not _theme_intent(authorization.goal, enabled):
            return ShellResult("needs_authorization", "Specify the requested Windows dark/light theme", question="Do you want the current user's dark or light Windows theme?")
        try:
            values = _set_theme(enabled)
        except OSError as exc:
            return ShellResult("failed", "Could not change the current user's theme preferences", stderr=str(exc))
        verified = all(values.get(name) == (0 if enabled else 1) for name in THEME_VALUES)
        return ShellResult("success" if verified else "failed", "Windows theme preferences were read back; some applications may need reopening" if verified else "Windows theme readback did not match the request", verified=verified, details=values)
    if action in {"get_night_light", "set_night_light"}:
        return ShellResult("unsupported", "Night Light state is not exposed by a stable supported API in this tool; use its Windows settings page", details=capabilities()["night_light"])
    if action == "open_night_light_settings":
        result = _run([_windows_executable("explorer.exe"), "ms-settings:nightlight"], timeout=10, cancel_event=cancel_event)
        result.verified = False
        result.summary = "Requested the Windows Night Light settings page; Night Light was not changed or verified" if result.success else "Windows could not open the Night Light settings page; Night Light was not changed"
        return result
    return ShellResult("failed", "Unknown local Windows capability")
