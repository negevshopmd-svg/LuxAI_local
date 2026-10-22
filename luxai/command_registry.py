"""Persistent, allowlisted voice-command library with editable personal shortcuts.

Built-in commands run instantly without AI. User commands are stored in
.luxai_data/commands.json, which the updater preserves. New online-resolved
commands can be learned only AFTER safe local execution succeeds.
No shortcut can contain shell code, arbitrary executable names or URLs.
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from luxai.fast_intents import strip_wake_name
from luxai.file_actions import safe_name, ALLOWED_LOCATIONS
from luxai.steam_games import GAMES
from luxai.action_catalog import CATALOG, validate_step

BASE = Path(__file__).resolve().parents[1]
DATA_DIR = BASE / ".luxai_data"
REGISTRY_FILE = DATA_DIR / "commands.json"
MAX_USER_COMMANDS = 300
APP_TARGETS = (
    "telegram", "discord", "steam", "chrome", "firefox", "edge",
    "spotify", "notepad", "calculator", "explorer",
)
GAME_TARGETS = tuple(GAMES)
ACTIONS = {
    "open_app", "launch_game", "steam_verified", "create_file",
    "create_folder", "list_files", "time", "minimize_windows",
} | {name for name, item in CATALOG.items() if item["available"]}


def _built_in(category, title, action, target="", phrases=(), location="desktop"):
    return {
        "id": "built_" + re.sub(r"[^a-z0-9]+", "_", action + "_" + target + "_" + category.lower()).strip("_"),
        "category": category, "title": title, "action": action,
        "target": target, "location": location, "phrases": list(phrases),
        "enabled": True, "builtin": True, "learned": False,
    }


BUILTINS = [
    _built_in("Приложения", "Telegram", "open_app", "telegram", (
        "открой телеграм", "открой телеграмм", "открыть телеграм",
        "запусти телеграм", "открой telegram", "open telegram",
    )),
    _built_in("Приложения", "Discord", "open_app", "discord", (
        "открой дискорд", "запусти дискорд", "открой discord", "open discord",
    )),
    _built_in("Приложения", "Steam", "open_app", "steam", (
        "открой стим", "открой steam", "запусти стим", "open steam",
    )),
    _built_in("Приложения", "Google Chrome", "open_app", "chrome", (
        "открой хром", "открой google chrome", "open chrome", "запусти хром",
    )),
    _built_in("Приложения", "Mozilla Firefox", "open_app", "firefox", (
        "открой firefox", "открой файрфокс", "open firefox",
    )),
    _built_in("Приложения", "Microsoft Edge", "open_app", "edge", (
        "открой edge", "открой эдж", "open edge",
    )),
    _built_in("Приложения", "Spotify", "open_app", "spotify", (
        "открой spotify", "открой спотифай", "open spotify",
    )),
    _built_in("Windows", "Блокнот", "open_app", "notepad", (
        "открой блокнот", "запусти блокнот", "open notepad",
    )),
    _built_in("Windows", "Калькулятор", "open_app", "calculator", (
        "открой калькулятор", "запусти калькулятор", "open calculator",
    )),
    _built_in("Windows", "Проводник", "open_app", "explorer", (
        "открой проводник", "запусти проводник", "open file explorer",
    )),
    _built_in("Windows", "Свернуть окна", "minimize_windows", phrases=(
        "сверни все окна", "свернуть все окна", "minimize all windows",
    )),
    _built_in("Windows", "Время", "time", phrases=(
        "сколько время", "сколько времени", "который час",
        "what time is it", "cât e ceasul",
    )),
    _built_in("Игры Steam", "Dota 2", "launch_game", "dota2", (
        "открой доту", "запусти доту", "открой дота 2", "запусти dota 2",
        "открой dota", "launch dota 2",
    )),
    _built_in("Игры Steam", "Counter-Strike 2", "launch_game", "cs2", (
        "открой кс", "открой кс 2", "запусти кс", "открой cs",
        "запусти counter strike", "launch cs2",
    )),
    _built_in("Игры Steam", "War Thunder", "launch_game", "warthunder", (
        "открой вар тандер", "открой вар тандер", "запусти вар тандер",
        "открой war thunder", "запусти war thunder", "открой вартандер",
        "запусти вартандер", "launch war thunder",
    )),
    _built_in("Файлы", "Создать файл на рабочем столе", "create_file", "Новый файл.txt", (
        "создай файл на рабочем столе", "создай файл",
        "создать файл на рабочем столе", "create a file on desktop",
    )),
    _built_in("Файлы", "Создать папку на рабочем столе", "create_folder", "Новая папка", (
        "создай папку на рабочем столе", "создай папку",
        "создать папку на рабочем столе", "create folder on desktop",
    )),
    _built_in("Файлы", "Показать файлы на рабочем столе", "list_files", phrases=(
        "покажи файлы на рабочем столе", "какие файлы на рабочем столе",
        "list desktop files",
    )),
]


def normalize_phrase(text):
    s = re.sub(r"[\s.!?,;:—–\-]+", " ", str(text or "").casefold()).strip()
    return s


def checked_command(raw, builtin=False):
    """Validate loaded commands again: local JSON is not executable code."""
    if not isinstance(raw, dict):
        raise ValueError("Invalid command entry")
    action = raw.get("action")
    target = raw.get("target", "")
    location = raw.get("location", "desktop")
    raw_steps = raw.get("steps")
    validated_steps = []
    if raw_steps is not None:
        if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= 8:
            raise ValueError("A command must contain 1 to 8 actions")
        validated_steps = [validate_step(step) for step in raw_steps]
        first = validated_steps[0]
        action = first["action"]
        target = first["target"]
        location = first["location"]
    title = str(raw.get("title", "")).strip()
    phrases = raw.get("phrases", [])
    if action not in ACTIONS or not isinstance(target, str) or not isinstance(title, str):
        raise ValueError("Unsupported command")
    if len(title) not in range(1, 101) or not isinstance(phrases, list) or len(phrases) not in range(1, 13):
        raise ValueError("Invalid command title or phrases")
    good_phrases = []
    for phrase in phrases:
        if not isinstance(phrase, str) or not (1 <= len(phrase.strip()) <= 120):
            raise ValueError("Invalid phrase")
        normalized = normalize_phrase(phrase)
        if normalized and normalized not in {normalize_phrase(p) for p in good_phrases}:
            good_phrases.append(phrase.strip())
    if not good_phrases:
        raise ValueError("At least one phrase is required")
    if action == "open_app" and target not in APP_TARGETS:
        raise ValueError("Unknown application")
    if action == "launch_game" and target not in GAMES:
        raise ValueError("Unknown preset game")
    if action == "steam_verified":
        appid = raw.get("appid")
        if not isinstance(appid, int) or isinstance(appid, bool) or not (1 <= appid <= 100_000_000):
            raise ValueError("Invalid Steam app ID")
        if not target or len(target) > 100:
            raise ValueError("Invalid Steam game title")
    if action in ("create_file", "create_folder"):
        target = safe_name(target, is_folder=action == "create_folder")
    if action not in ("create_file", "create_folder", "open_app", "launch_game", "steam_verified"):
        target = ""
    if location not in ALLOWED_LOCATIONS:
        raise ValueError("Invalid destination")
    identifier = raw.get("id")
    if not isinstance(identifier, str) or len(identifier) > 100 or not re.fullmatch(r"[a-zA-Z0-9_-]+", identifier):
        raise ValueError("Invalid command ID")
    return {
        "id": identifier,
        "title": title,
        "category": str(raw.get("category", "Мои команды"))[:60],
        "action": action,
        "target": target,
        "appid": raw.get("appid") if action == "steam_verified" else None,
        "location": location,
        "phrases": good_phrases,
        "enabled": bool(raw.get("enabled", True)),
        "builtin": bool(builtin),
        "learned": bool(raw.get("learned", False)) if not builtin else False,
        "steps": validated_steps,
    }


class CommandRegistry:
    def __init__(self, path=None):
        self.path = Path(path) if path else REGISTRY_FILE
        self.custom = []
        self.disabled_builtins = set()
        self.reload()

    def reload(self):
        self.custom = []
        self.disabled_builtins = set()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            self.disabled_builtins = set(
                x for x in data.get("disabled_builtins", [])
                if isinstance(x, str) and x.startswith("built_")
            )
            for item in data.get("commands", [])[:MAX_USER_COMMANDS]:
                try:
                    self.custom.append(checked_command(item))
                except (ValueError, TypeError):
                    continue
        except (OSError, ValueError, TypeError):
            pass

    def _persist(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "disabled_builtins": sorted(self.disabled_builtins),
            "commands": self.custom,
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def entries(self):
        result = []
        for original in BUILTINS:
            item = checked_command(original, builtin=True)
            item["enabled"] = item["id"] not in self.disabled_builtins
            result.append(item)
        return result + [dict(item) for item in self.custom]

    def match(self, spoken, prefix="Jarvis"):
        command = normalize_phrase(strip_wake_name(spoken, prefix))
        if not command:
            return None
        # User-created commands override defaults only when exact phrases match.
        for item in list(self.custom) + self.entries()[:len(BUILTINS)]:
            if item["enabled"] and any(normalize_phrase(p) == command for p in item["phrases"]):
                return dict(item)
        return None

    def disabled_match(self, spoken, prefix="Jarvis"):
        """Avoid executing explicitly disabled built-in triggers via looser AI rules."""
        phrase = normalize_phrase(strip_wake_name(spoken, prefix))
        for item in BUILTINS:
            if item["id"] not in self.disabled_builtins:
                continue
            if any(normalize_phrase(candidate) == phrase for candidate in item["phrases"]):
                return True
        return False

    def save_custom(self, raw):
        data = dict(raw)
        if not data.get("id"):
            data["id"] = "user_" + uuid.uuid4().hex[:16]
        data["builtin"] = False
        validated = checked_command(data)
        existing = next((i for i, x in enumerate(self.custom) if x["id"] == validated["id"]), None)
        if existing is None:
            if len(self.custom) >= MAX_USER_COMMANDS:
                raise ValueError("Too many custom commands")
            self.custom.append(validated)
        else:
            self.custom[existing] = validated
        self._persist()
        return validated

    def set_enabled(self, identifier, enabled):
        if identifier.startswith("built_"):
            valid_ids = {item["id"] for item in BUILTINS}
            if identifier not in valid_ids:
                raise ValueError("Unknown built-in command")
            if enabled:
                self.disabled_builtins.discard(identifier)
            else:
                self.disabled_builtins.add(identifier)
        else:
            record = next((item for item in self.custom if item["id"] == identifier), None)
            if record is None:
                raise ValueError("Unknown custom command")
            record["enabled"] = bool(enabled)
        self._persist()

    def remove_custom(self, identifier):
        original = len(self.custom)
        self.custom = [item for item in self.custom if item["id"] != identifier]
        if len(self.custom) == original:
            raise ValueError("Command not found or is built-in")
        self._persist()

    def learn(self, phrase, plan, *, success: bool):
        """Record successful, verified commands; never store arbitrary AI scripts."""
        if not success or not isinstance(plan, dict):
            return None
        action = plan.get("action")
        if action not in {"open_app", "launch_game", "steam_verified"}:
            return None
        phrase = str(phrase or "").strip()
        if not phrase or len(phrase) > 120 or self.match(phrase):
            return None
        target = str(plan.get("target", ""))
        title = target if action != "launch_game" else GAMES.get(target, ("", target))[1]
        raw = {
            "id": "learned_" + uuid.uuid4().hex[:16],
            "category": "Выученные команды",
            "title": title,
            "action": action,
            "target": target,
            "appid": plan.get("appid") if action == "steam_verified" else None,
            "phrases": [strip_wake_name(phrase)],
            "enabled": True,
            "learned": True,
        }
        try:
            return self.save_custom(raw)
        except (ValueError, OSError):
            return None
