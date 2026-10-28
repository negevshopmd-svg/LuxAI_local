"""Validated command triggers active only while Jarvis is running.

No trigger executes desktop actions itself. Callbacks deliver saved command
entries through the application's existing execution/confirmation pipeline.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import date, datetime, timedelta
import hashlib
import json
import re
import sys
import threading
import time
from pathlib import Path


STATE_PATH = Path(__file__).resolve().parents[1] / ".luxai_data" / "command_trigger_state.json"
APP_PROCESSES = {
    "telegram": {"telegram.exe"}, "discord": {"discord.exe"}, "steam": {"steam.exe"},
    "chrome": {"chrome.exe"}, "firefox": {"firefox.exe"}, "edge": {"msedge.exe"},
    "spotify": {"spotify.exe"}, "notepad": {"notepad.exe"},
    "calculator": {"calculatorapp.exe", "calculator.exe", "calc.exe"},
    "explorer": {"explorer.exe"}, "word": {"winword.exe"},
}


def normalize_hotkey(value):
    if not isinstance(value, str) or len(value) > 60:
        raise ValueError("Некорректное сочетание клавиш.")
    value = value.strip().casefold().replace("control", "ctrl").replace("meta", "win")
    if not value:
        return ""
    parts = [part.strip() for part in value.split("+")]
    if not all(parts) or len(parts) != len(set(parts)):
        raise ValueError("Некорректное сочетание клавиш.")
    modifiers = {"ctrl", "alt", "shift", "win"}
    keys = [part for part in parts if part not in modifiers]
    if len(keys) != 1 or not re.fullmatch(r"[a-z0-9]|f(?:[1-9]|1[0-2])", keys[0]):
        raise ValueError("Укажите букву, цифру или F1–F12 с модификаторами.")
    if len(parts) == 1 and re.fullmatch(r"f(?:[1-9]|1[0-2])", keys[0]) is None:
        raise ValueError("Для буквы или цифры добавьте Ctrl, Alt, Shift или Win.")
    # Avoid intercepting emergency/system combinations.
    result = "+".join([key for key in ("ctrl", "alt", "shift", "win") if key in parts] + keys)
    if result in {"alt+f4", "ctrl+shift+esc", "win+l"}:
        raise ValueError("Это системное сочетание нельзя назначить команде.")
    return result


def validate_schedule(value):
    if value in (None, {}):
        return {}
    if not isinstance(value, dict) or value.get("mode") not in {"once", "daily", "weekly"}:
        raise ValueError("Некорректное расписание.")
    clock = value.get("time")
    if not isinstance(clock, str) or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", clock) is None:
        raise ValueError("Время запуска должно быть в формате ЧЧ:ММ.")
    result = {"mode": value["mode"], "time": clock}
    if result["mode"] == "once":
        day = value.get("date")
        if not isinstance(day, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day) is None:
            raise ValueError("Выберите дату запуска.")
        try:
            date.fromisoformat(day)
        except ValueError:
            raise ValueError("Выберите корректную дату запуска.") from None
        result["date"] = day
    elif result["mode"] == "weekly":
        days = value.get("weekdays")
        if (not isinstance(days, list) or not 1 <= len(days) <= 7
                or any(type(day) is not int or not 0 <= day <= 6 for day in days)):
            raise ValueError("Выберите хотя бы один день недели.")
        result["weekdays"] = sorted(set(days))
    return result


def validate_event(value):
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise ValueError("Некорректное событие.")
    kind = value.get("type")
    if kind == "headphones_connected":
        return {"type": kind}
    if kind == "app_started" and value.get("app") in APP_PROCESSES:
        return {"type": kind, "app": value["app"]}
    raise ValueError("Выберите поддерживаемое приложение или подключение наушников.")


def running_applications():
    """Read process names, not window text or application/document contents."""
    import psutil
    names = set()
    for process in psutil.process_iter(["name"]):
        try:
            names.add(str(process.info.get("name", "")).casefold())
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return {app for app, processes in APP_PROCESSES.items() if names & processes}


def headphones_connected():
    words = ("headphone", "headset", "наушник", "гарнитур", "головной",
             "căști", "căşti", "casti", "hands-free")
    if sys.platform == "win32":
        try:
            import comtypes
            from pycaw.pycaw import AudioUtilities
        except ImportError:
            pass
        else:
            # PortAudio may retain a startup device snapshot after hot-plug.
            # Windows endpoint state is live and does not interrupt capture.
            comtypes.CoInitialize()
            try:
                for device in AudioUtilities.GetAllDevices():
                    state = getattr(device, "state", 0)
                    state = getattr(state, "value", state)
                    if int(state) & 1 and any(word in str(device.FriendlyName).casefold() for word in words):
                        return True
                return False
            finally:
                comtypes.CoUninitialize()
    import sounddevice
    return any(device.get("max_output_channels", 0) > 0
               and any(word in str(device.get("name", "")).casefold() for word in words)
               for device in sounddevice.query_devices())


class CommandTriggerEngine:
    """Poll schedules/event transitions and dispatch each occurrence once.

    Call poll on a Qt timer and marshal global-hotkey IDs onto that same UI
    thread before calling handle_hotkey. No catch-up work runs after downtime.
    """
    def __init__(self, registry, callback, *, state_path=STATE_PATH):
        self.registry, self.callback = registry, callback
        self.state_path = Path(state_path) if state_path else None
        self._last_poll = None
        self._apps = None
        self._headphones = None
        self._hotkey_times = {}
        self._fired = {}
        self.last_error = ""
        self._probe_lock = threading.Lock()
        self._probe_pending = False
        self._probe_cache = {"apps": None, "headphones": None}
        self._probe_thread = None
        if self.state_path:
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._fired = {key: value for key, value in list(data.items())[-3000:]
                                   if isinstance(key, str) and len(key) <= 250
                                   and isinstance(value, str) and len(value) <= 50}
            except (OSError, ValueError, TypeError):
                pass

    def _entries(self):
        # The registry has validated JSON; check again at the dispatch boundary
        # so mutable editor drafts cannot be executed as saved triggers.
        from luxai.command_registry import checked_command
        entries = []
        for entry in self.registry.entries():
            try:
                checked = checked_command(entry, builtin=entry.get("builtin", False))
                if checked["enabled"]:
                    entries.append(checked)
            except (TypeError, ValueError):
                continue
        return entries

    def _dispatch(self, entry):
        try:
            self.callback(dict(entry))
        except Exception as exc:
            self.last_error = f"Command trigger: {type(exc).__name__}"

    def _remember(self, key, now):
        self._fired[key] = now.isoformat()
        if len(self._fired) > 3000:
            self._fired = dict(list(self._fired.items())[-3000:])
        if self.state_path:
            try:
                self.state_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.state_path.with_suffix(".tmp")
                temporary.write_text(json.dumps(self._fired, indent=2), encoding="utf-8")
                temporary.replace(self.state_path)
            except OSError as exc:
                self.last_error = f"Schedule state: {type(exc).__name__}"

    def _probe_inputs(self, need_apps, need_headphones):
        """One driver/process scan at a time; never block the Qt timer."""
        with self._probe_lock:
            if not self._probe_pending:
                self._probe_pending = True

                def read():
                    values = {}
                    try:
                        if need_apps:
                            values["apps"] = running_applications()
                        if need_headphones:
                            values["headphones"] = headphones_connected()
                    except Exception as exc:
                        self.last_error = f"Command event devices: {type(exc).__name__}"
                    finally:
                        with self._probe_lock:
                            self._probe_cache.update(values)
                            self._probe_pending = False

                self._probe_thread = threading.Thread(target=read, daemon=True, name="JarvisCommandEventProbe")
                self._probe_thread.start()
            return dict(self._probe_cache)

    def poll(self, now=None, *, apps=None, headphones=None):
        now = now or datetime.now().astimezone()
        entries = self._entries()
        needs_apps = any(entry.get("event", {}).get("type") == "app_started" for entry in entries)
        needs_headphones = any(entry.get("event", {}).get("type") == "headphones_connected" for entry in entries)
        if needs_apps and apps is None or needs_headphones and headphones is None:
            cached = self._probe_inputs(needs_apps and apps is None, needs_headphones and headphones is None)
            if needs_apps and apps is None:
                apps = cached["apps"]
            if needs_headphones and headphones is None:
                headphones = cached["headphones"]
        apps = set(apps) if apps is not None else None
        previous = self._last_poll
        # First observation establishes state. A sleep/resume or clock jump
        # never replays minutes/hours of missed schedules.
        continuous = previous is not None and 0 <= (now - previous).total_seconds() <= 120
        dispatched = set()

        def dispatch_once(entry):
            if entry["id"] not in dispatched:
                dispatched.add(entry["id"])
                self._dispatch(entry)

        for entry in entries:
            schedule = entry.get("schedule", {})
            if schedule and continuous:
                hours, minutes = map(int, schedule["time"].split(":"))
                due = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
                eligible = (schedule["mode"] == "daily"
                            or schedule["mode"] == "once" and schedule["date"] == now.date().isoformat()
                            or schedule["mode"] == "weekly" and now.weekday() in schedule["weekdays"])
                if eligible and previous < due <= now:
                    signature = hashlib.sha256(json.dumps(schedule, sort_keys=True).encode()).hexdigest()[:16]
                    key = entry["id"] + ":" + signature + ":" + due.strftime("%Y-%m-%dT%H:%M")
                    if key not in self._fired:
                        self._remember(key, now)
                        dispatch_once(entry)
            event = entry.get("event", {})
            if event.get("type") == "app_started" and self._apps is not None and apps is not None:
                if event["app"] in apps - self._apps:
                    dispatch_once(entry)
            elif event.get("type") == "headphones_connected" and self._headphones is False and headphones is True:
                dispatch_once(entry)
        self._last_poll = now
        self._apps = apps
        self._headphones = bool(headphones) if headphones is not None else None

    def handle_hotkey(self, identifier):
        now = time.monotonic()
        if now - self._hotkey_times.get(identifier, -100.0) < 0.75:
            return
        for entry in self._entries():
            if entry["id"] == identifier and entry.get("hotkey"):
                self._hotkey_times[identifier] = now
                self._dispatch(entry)
                break


class WindowsHotkeyListener:
    """Register global shortcuts without installing keyboard hooks.

    on_id is invoked on the message-pump thread; it must only emit a Qt signal.
    An unavailable or already-reserved shortcut is reported via errors.
    """
    def __init__(self, on_id):
        self.on_id = on_id
        self.errors = {}
        self._requested = []
        self._lock = threading.Lock()
        self._thread = None
        self._thread_id = None
        self._stopping = False

    @property
    def last_error(self):
        return "; ".join(dict.fromkeys(self.errors.values()))

    def sync(self, entries):
        requested = [(entry["id"], normalize_hotkey(entry.get("hotkey", "")))
                     for entry in entries if entry.get("enabled") and entry.get("hotkey")]
        with self._lock:
            if requested == self._requested and self._thread and self._thread.is_alive():
                return
            self._requested = requested
        if sys.platform != "win32":
            self.errors = {identifier: "Глобальные сочетания клавиш доступны в Windows." for identifier, _ in requested}
            return
        if not requested and not (self._thread and self._thread.is_alive()):
            self.errors = {}
            return
        if not self._thread or not self._thread.is_alive():
            self._stopping = False
            self._thread = threading.Thread(target=self._run, daemon=True, name="JarvisCommandHotkeys")
            self._thread.start()
        self._post(0x8001)

    def _post(self, message):
        if self._thread_id:
            user32 = ctypes.windll.user32
            user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.PostThreadMessageW(self._thread_id, message, 0, 0)

    def stop(self):
        self._stopping = True
        if sys.platform == "win32":
            self._post(0x0012)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)

    def _run(self):
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = wintypes.BOOL
        message = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
        self._thread_id = kernel32.GetCurrentThreadId()
        registered = {}

        def refresh():
            for number in list(registered):
                user32.UnregisterHotKey(None, number)
            registered.clear()
            errors = {}
            with self._lock:
                requested = list(self._requested)
            seen = set()
            for number, (identifier, shortcut) in enumerate(requested, 1):
                if shortcut in seen:
                    errors[identifier] = "Это сочетание уже назначено другой команде."
                    continue
                seen.add(shortcut)
                parts = shortcut.split("+")
                modifiers = 0x4000  # MOD_NOREPEAT
                for name, flag in (("alt", 1), ("ctrl", 2), ("shift", 4), ("win", 8)):
                    if name in parts:
                        modifiers |= flag
                key = parts[-1]
                virtual_key = 0x70 + int(key[1:]) - 1 if len(key) > 1 else ord(key.upper())
                if user32.RegisterHotKey(None, number, modifiers, virtual_key):
                    registered[number] = identifier
                else:
                    errors[identifier] = "Windows не удалось зарегистрировать сочетание. Возможно, оно уже используется."
            self.errors = errors

        try:
            refresh()
            while not self._stopping:
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0:
                    break
                if message.message == 0x8001:
                    refresh()
                elif message.message == 0x0312 and int(message.wParam) in registered:
                    try:
                        self.on_id(registered[int(message.wParam)])
                    except Exception:
                        pass
        finally:
            for number in registered:
                user32.UnregisterHotKey(None, number)
            self._thread_id = None


# Kept as a convenient import for editor integrations; no hooks start on import.
from luxai.command_recording import ActionRecorder
