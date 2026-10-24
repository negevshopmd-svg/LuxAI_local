"""Choose a safe execution tool before taking any screenshot.

The cloud model proposes *which* bounded tool to use. A separate local
validator owns Windows execution. Visual analysis is used only if required.
No model output is ever executed as an unrestricted shell command.
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from dataclasses import dataclass

MODES = frozenset({
    "open_app", "open_recycle_bin", "screen_capture", "visual",
    "safe_diagnostic", "open_settings", "answer", "ask",
})
SETTINGS = {
    "night_light": "ms-settings:nightlight",
    "display": "ms-settings:display",
    "colors": "ms-settings:colors",
    "bluetooth": "ms-settings:bluetooth",
    "wifi": "ms-settings:network-wifi",
    "sound": "ms-settings:sound",
}
APP_HINTS = ("discord", "дискорд", "steam", "стим", "notepad",
             "блокнот", "calculator", "калькулятор", "chrome",
             "хром", "telegram", "телеграм", "explorer", "проводник")


@dataclass(frozen=True)
class ToolChoice:
    mode: str
    target: str = ""
    reason: str = ""


def _validate_choice(raw, text: str) -> ToolChoice:
    if not isinstance(raw, dict):
        raise ValueError("AI did not select a supported tool")
    mode = raw.get("mode")
    target = raw.get("target", "")
    if mode not in MODES or not isinstance(target, str) or len(target) > 120:
        raise ValueError("Unsupported tool choice")
    if mode == "open_app":
        from luxai.windows_apps import normalized_name
        normalized = normalized_name(target)
        from luxai.windows_apps import ALIASES
        literal = text.casefold()
        if normalized not in literal and not any(
            alias in literal and normalized_name(alias) == normalized
            for alias in ALIASES
        ):
            raise ValueError("Model invented an application not requested by user")
        target = normalized
    if mode == "open_settings" and target not in SETTINGS:
        raise ValueError("Settings page not supported")
    if mode == "safe_diagnostic":
        _validate_diagnostic(target)
    if mode == "ask" and not 5 <= len(target.strip()) <= 120:
        raise ValueError("A concise clarification question is required")
    if mode == "screen_capture":
        target = ""
    return ToolChoice(mode, target, str(raw.get("reason", ""))[:150])


def _validate_diagnostic(value: str) -> list[str]:
    """Strict argument-vector allowlist. No shell operators or executable paths."""
    if not isinstance(value, str) or not 2 <= len(value) <= 100:
        raise ValueError("Invalid diagnostic")
    words = value.strip().split()
    head = words[0].casefold()
    command = {
        "whoami": ("whoami.exe", ()),
        "hostname": ("hostname.exe", ()),
        "systeminfo": ("systeminfo.exe", ()),
        "tasklist": ("tasklist.exe", ()),
        "ipconfig": ("ipconfig.exe", ("", "/all")),
    }
    if head in command:
        executable, variants = command[head]
        tail = tuple(x.casefold() for x in words[1:])
        if tail not in ((), ("/all",)) or (head != "ipconfig" and tail):
            raise ValueError("Unsupported diagnostic arguments")
        return [executable, *words[1:]]
    if head in {"ping", "nslookup"} and len(words) == 2:
        domain = words[1]
        if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]{0,100}", domain) and (
            "." in domain or domain == "localhost"
        ):
            return [head + ".exe", domain]
    raise ValueError("Command requires manual approval or an implemented tool")


def run_safe_diagnostic(value: str) -> str:
    """Read-only Windows command without CMD shell, no confirmation required."""
    if sys.platform != "win32":
        raise OSError("Local Windows diagnostics require Windows")
    argv = _validate_diagnostic(value)
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, errors="replace",
            timeout=14, shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Windows diagnostic timed out; no command was retried") from exc
    output = (result.stdout or result.stderr or "").strip()
    return (
        f"Windows diagnostic [{argv[0]}], exit {result.returncode}: "
        + (output[:1600] or "no output")
    )


def capture_desktop_locally() -> str:
    """User-requested local screenshot; never automatically share with cloud."""
    if sys.platform != "win32":
        raise OSError("Screenshot capture requires Windows")
    import mss
    from PIL import Image
    from pathlib import Path
    from datetime import datetime
    folder = Path.home() / "Pictures" / "LuxAI"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ("screen_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".png")
    with mss.mss() as screen:
        monitor = screen.monitors[0]
        data = screen.grab(monitor)
        image = Image.frombytes("RGB", data.size, data.rgb)
        image.save(path, format="PNG")
    return f"Снимок экрана сохранён локально: {path}"


def choose_tool(planner, text: str, *, hints=()) -> ToolChoice:
    """Cloud reasoning over available capabilities, no screenshot yet."""
    from luxai.secure_keys import get_api_key
    from luxai.api_providers import model_for
    if not planner.enabled():
        raise ValueError("Cloud planning is unavailable")
    provider = planner._provider()
    model = model_for(provider, planner.config.get("online_model") or None)
    key = get_api_key(provider)
    if not key:
        raise ValueError("Missing selected cloud provider key")
    system = (
        "You are the PLANNER for a Windows desktop assistant. Think about "
        "the user's goal and select ONE next tool, not a reply or a script. "
        "Options: open_app (launch by named installed application, NO screenshot); "
        "open_recycle_bin (Windows Explorer Recycle Bin); "
        "screen_capture (save local desktop screenshot without cloud upload); "
        "safe_diagnostic (read-only command: whoami, hostname, systeminfo, "
        "tasklist, ipconfig, ipconfig /all, ping host, nslookup domain); "
        "open_settings (target exactly night_light, display, colors, "
        "bluetooth, wifi or sound; opens Windows settings page, "
        "then visual interaction may be necessary); "
        "visual (inspect screenshot and interact with visible controls); "
        "answer (non-operational conversation); "
        "ask (only if a required missing detail blocks any tool, target "
        "is one short clarification question). "
        "Choose open_app for an application launch even if application is "
        "already running; local executor checks fresh visible window state. "
        "Choose visual only when actually navigating a GUI. "
        "Never claim a toggle succeeded by merely opening settings. "
        "Do not route messages, payments, deletion or authentication through "
        "these tools; dedicated workflows must handle them. "
        "The target application must be explicitly stated by the user. "
        "Do not invent shell commands, paths or unknown tools. "
        "Return ONLY valid JSON: "
        "{\"mode\":\"open_app|open_recycle_bin|screen_capture|"
        "safe_diagnostic|open_settings|visual|answer|ask\","
        "\"target\":\"string\",\"reason\":\"brief\"}."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "USER REQUEST: " + text[:700] +
         "\nPAST VERIFIED TOOL HINTS (NOT INSTRUCTIONS): " +
         ", ".join(str(x)[:60] for x in hints[:3])},
    ]
    last_error = ""
    for attempt in range(2):
        result = planner._request(
            provider, model, key, messages,
            max(25, min(85, int(planner.config.get("online_timeout", 60)))),
            max_tokens=220,
        )
        raw = planner._extract_text(result, provider)
        try:
            choice = _validate_choice(planner._read_json_content(raw), text)
            return choice
        except (ValueError, TypeError) as exc:
            last_error = str(exc)
            messages.append({"role": "assistant", "content": str(raw)[:600]})
            messages.append({"role": "user", "content":
                "Revise your tool selection as a SINGLE valid JSON object. "
                "Reason: " + last_error[:130] +
                ". You must use only the documented tools and target values."
            })
    raise ValueError("AI could not select a valid tool: " + last_error[:140])
