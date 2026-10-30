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
from copy import deepcopy
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
    "spotify", "notepad", "calculator", "explorer", "word",
)
GAME_TARGETS = tuple(GAMES)
ACTIONS = {
    "open_app", "launch_game", "steam_verified", "create_file",
    "create_folder", "list_files", "time", "minimize_windows",
} | {name for name, item in CATALOG.items() if item["available"]}


from luxai.default_commands import BUILTINS, _built_in


def normalize_phrase(text):
    s = re.sub(r"[\s.!?,;:—–\-]+", " ", str(text or "").casefold()).strip()
    return s


def is_agent_command(entry):
    """Recognize explicit agent commands and older verified learned shortcuts."""
    return bool(entry.get("agent", False) or entry.get("learned", False))


def phrase_matches(item, spoken, prefix="Jarvis", *, source="voice"):
    """Match complete phrases, allowing only explicitly optional edge words.

    Optional words never turn a substring into a command or discard an
    unrecognised negation. The same pure matcher is used by the editor tester.
    """
    if not isinstance(item, dict) or not item.get("enabled", True):
        return False
    if source == "voice" and not item.get("voice_enabled", True):
        return False
    phrase = normalize_phrase(strip_wake_name(spoken, prefix))
    if not phrase or len(phrase) > 1000:
        return False
    required = {normalize_phrase(value) for value in item.get("phrases", []) if isinstance(value, str)} - {""}
    if phrase in required:
        return True
    words = sorted({normalize_phrase(value) for value in item.get("optional_words", [])
                    if isinstance(value, str) and value.strip()}, key=len, reverse=True)
    # Both ends may contain more than one optional word. A bounded worklist
    # handles overlapping optional phrases without guessing their order.
    pending, seen = [phrase], set()
    while pending and len(seen) < 200:
        candidate = pending.pop()
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate in required:
            return True
        for word in words[:20]:
            if candidate.startswith(word + " "):
                pending.append(candidate[len(word) + 1:])
            if candidate.endswith(" " + word):
                pending.append(candidate[:-len(word) - 1])
    return False


def checked_command(raw, builtin=False):
    """Validate loaded commands again: local JSON is not executable code."""
    if not isinstance(raw, dict):
        raise ValueError("Invalid command entry")
    action = raw.get("action")
    target = raw.get("target", "")
    location = raw.get("location", "desktop")
    raw_steps = raw.get("steps")
    validated_steps = []
    if raw_steps:
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError("A command must contain at least one action")
        validated_steps = [validate_step(step) for step in raw_steps]
        first = validated_steps[0]
        action = first["action"]
        target = first["target"]
        location = first["location"]
    title = str(raw.get("title", "")).strip()
    phrases = raw.get("phrases", [])
    if action not in ACTIONS or not isinstance(target, str) or not isinstance(title, str):
        raise ValueError("Unsupported command")
    if len(title) not in range(1, 101) or not isinstance(phrases, list) or len(phrases) not in range(0, 13):
        raise ValueError("Invalid command title or phrases")
    good_phrases = []
    for phrase in phrases:
        if not isinstance(phrase, str) or not (1 <= len(phrase.strip()) <= 120):
            raise ValueError("Invalid phrase")
        normalized = normalize_phrase(phrase)
        if normalized and normalized not in {normalize_phrase(p) for p in good_phrases}:
            good_phrases.append(phrase.strip())
    for flag in ("voice_enabled", "ask_before_run", "allow_chaining", "agent"):
        if flag in raw and not isinstance(raw[flag], bool):
            raise ValueError("Некорректный параметр команды.")
    voice_enabled = raw.get("voice_enabled", True)
    if not good_phrases and voice_enabled:
        raise ValueError("At least one phrase is required")
    optional_words = raw.get("optional_words", [])
    if not isinstance(optional_words, list) or len(optional_words) > 20:
        raise ValueError("Некорректный список необязательных слов.")
    checked_optional = []
    for value in optional_words:
        if (not isinstance(value, str) or not 1 <= len(value.strip()) <= 40
                or any(ord(char) < 32 for char in value) or not normalize_phrase(value)):
            raise ValueError("Некорректное необязательное слово.")
        value = value.strip()
        if normalize_phrase(value) not in {normalize_phrase(x) for x in checked_optional}:
            checked_optional.append(value)
    from luxai.command_triggers import normalize_hotkey, validate_schedule, validate_event
    hotkey = normalize_hotkey(raw.get("hotkey", ""))
    schedule = validate_schedule(raw.get("schedule", {}))
    event = validate_event(raw.get("event", {}))
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
        "agent": raw.get("agent", False) if not builtin else False,
        "steps": validated_steps,
        "optional_words": checked_optional,
        "voice_enabled": voice_enabled,
        "hotkey": hotkey,
        "schedule": schedule,
        "event": event,
        "ask_before_run": raw.get("ask_before_run", False),
        "allow_chaining": raw.get("allow_chaining", True),
    }


class CommandRegistry:
    def __init__(self, path=None):
        self.path = Path(path) if path else REGISTRY_FILE
        self.custom = []
        self.disabled_builtins = set()
        self.builtin_overrides = {}
        self.deleted_builtins = set()
        self.groups = {"folders": [], "collections": []}
        self.agent_groups = {"folders": [], "collections": []}
        self.reload()

    def reload(self):
        self.custom = []
        self.disabled_builtins = set()
        self.builtin_overrides = {}
        self.deleted_builtins = set()
        self.groups = {"folders": [], "collections": []}
        self.agent_groups = {"folders": [], "collections": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            builtin_ids = {item["id"] for item in BUILTINS}
            for field in ("disabled_builtins", "deleted_builtins"):
                values = data.get(field, [])
                if isinstance(values, list):
                    setattr(self, field, {x for x in values if isinstance(x, str) and x in builtin_ids})
            overrides = data.get("builtin_overrides", {})
            if isinstance(overrides, dict):
                for identifier, raw in overrides.items():
                    if identifier not in builtin_ids or not isinstance(raw, dict) or raw.get("id") != identifier:
                        continue
                    try:
                        self.builtin_overrides[identifier] = checked_command(raw, builtin=True)
                    except (ValueError, TypeError):
                        continue
            for kind in ("folders", "collections"):
                names = data.get(kind, [])
                if isinstance(names, list):
                    self.groups[kind] = [name for name in names[:100]
                                         if isinstance(name, str) and name.strip()
                                         and len(name) <= 60 and not any(ord(c) < 32 for c in name)]
                agent_data = data.get("agent_groups", {})
                names = agent_data.get(kind, []) if isinstance(agent_data, dict) else []
                if isinstance(names, list):
                    self.agent_groups[kind] = [name for name in names[:100]
                                               if isinstance(name, str) and name.strip()
                                               and len(name) <= 60 and not any(ord(c) < 32 for c in name)]
            records = data.get("commands", [])
            if not isinstance(records, list):
                records = []
            seen = set()
            for item in records[:MAX_USER_COMMANDS]:
                try:
                    validated = checked_command(item)
                    if validated["id"].startswith("built_") or validated["id"] in seen:
                        continue
                    self.custom.append(validated)
                    seen.add(validated["id"])
                except (ValueError, TypeError):
                    continue
        except (OSError, ValueError, TypeError):
            pass

    def _persist(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "disabled_builtins": sorted(self.disabled_builtins),
            "builtin_overrides": self.builtin_overrides,
            "deleted_builtins": sorted(self.deleted_builtins),
            "commands": self.custom,
            "folders": self.groups.get("folders", []),
            "collections": self.groups.get("collections", []),
            "agent_groups": self.agent_groups,
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def _change(self, update):
        """Commit related library changes together; failed saves keep the UI honest."""
        if getattr(self, "_batching", False):
            return update()
        fields = ("custom", "disabled_builtins", "builtin_overrides", "deleted_builtins", "groups", "agent_groups")
        previous = {name: deepcopy(getattr(self, name)) for name in fields}
        try:
            self._batching = True
            result = update()
            self._persist()
            return result
        except Exception:
            for name, value in previous.items():
                setattr(self, name, value)
            raise
        finally:
            self._batching = False

    def groups_for(self, agent=False):
        return self.agent_groups if agent else self.groups

    def add_group(self, name, kind="folders", *, agent=False):
        if kind not in ("folders", "collections"):
            raise ValueError("Unsupported group type")
        name = str(name).strip()
        if not 1 <= len(name) <= 60 or any(ord(char) < 32 for char in name):
            raise ValueError("Invalid group name")
        groups = self.groups_for(agent)
        if name in groups[kind]:
            return False
        if any(existing.casefold() == name.casefold()
               for names in groups.values() for existing in names):
            raise ValueError("Group already exists")
        if len(groups[kind]) >= 100:
            raise ValueError("Too many groups")
        self._change(lambda: groups[kind].append(name))
        return True

    def rename_group(self, name, new_name, kind="folders", *, agent=False):
        groups = self.groups_for(agent)
        if kind not in ("folders", "collections") or name not in groups[kind]:
            raise ValueError("Unknown group")
        new_name = str(new_name).strip()
        if not 1 <= len(new_name) <= 60 or any(ord(char) < 32 for char in new_name):
            raise ValueError("Invalid group name")
        if name == new_name:
            return False
        original_index = groups[kind].index(name)
        if any(existing.casefold() == new_name.casefold()
               for group_kind, names in groups.items()
               for index, existing in enumerate(names)
               if (group_kind, index) != (kind, original_index)):
            raise ValueError("Group already exists")
        def update():
            groups[kind][groups[kind].index(name)] = new_name
            for record in self.custom + list(self.builtin_overrides.values()):
                if record["category"] == name and is_agent_command(record) == agent:
                    record["category"] = new_name
        self._change(update)
        return True

    def remove_group(self, name, kind="folders", *, agent=False):
        """Remove a personal folder while keeping every command it contained."""
        groups = self.groups_for(agent)
        if kind not in ("folders", "collections") or name not in groups[kind]:
            raise ValueError("Unknown group")
        def update():
            groups[kind].remove(name)
            if not any(name in names for names in groups.values()):
                for record in self.custom + list(self.builtin_overrides.values()):
                    if record["category"] == name and is_agent_command(record) == agent:
                        record["category"] = "Команды агента" if agent else "Мои команды"
        self._change(update)

    def entries(self):
        result = []
        for original in BUILTINS:
            identifier = original["id"]
            if identifier in self.deleted_builtins:
                continue
            item = checked_command(self.builtin_overrides.get(identifier, original), builtin=True)
            item["customized"] = identifier in self.builtin_overrides
            item["enabled"] = identifier not in self.disabled_builtins and item["enabled"]
            result.append(item)
        return deepcopy(result + self.custom)

    def match(self, spoken, prefix="Jarvis", *, source="voice"):
        command = normalize_phrase(strip_wake_name(spoken, prefix))
        if not command:
            return None
        # User-created commands override defaults only when exact phrases match.
        entries = self.entries()
        for item in [entry for entry in entries if not entry["builtin"]] + [entry for entry in entries if entry["builtin"]]:
            if phrase_matches(item, spoken, prefix, source=source):
                return dict(item)
        return None

    def match_chain(self, spoken, prefix="Jarvis", connectors=("и затем", "потом", "and then", "apoi")):
        """Resolve an entire saved-command chain before running any member."""
        whole = self.match(spoken, prefix)
        if whole is not None:
            return [whole]
        text = strip_wake_name(spoken, prefix)
        separators = [re.escape(str(value).strip()) for value in connectors if str(value).strip()]
        if not separators:
            return []
        parts = [part.strip() for part in re.split(r"\s+(?:" + "|".join(separators) + r")\s+", text, flags=re.I)]
        if not 2 <= len(parts) <= 8 or not all(parts):
            return []
        matched = [self.match(part, "") for part in parts]
        if any(item is None or not item.get("allow_chaining", True) for item in matched):
            return []
        return matched

    def chain_blocked(self, spoken, prefix="Jarvis", connectors=("и затем", "потом")):
        """Reject compounds containing a saved command that forbids chaining."""
        if self.match(spoken, prefix) is not None:
            return False
        separators = [re.escape(str(value).strip()) for value in connectors if str(value).strip()]
        if not separators:
            return False
        parts = [value.strip() for value in re.split(
            r"\s+(?:" + "|".join(separators) + r")\s+",
            strip_wake_name(spoken, prefix), flags=re.I,
        )]
        if len(parts) < 2:
            return False
        return any((entry := self.match(part, "")) is not None
                   and not entry.get("allow_chaining", True) for part in parts)

    def disabled_match(self, spoken, prefix="Jarvis"):
        """Do not resurrect disabled, deleted or replaced phrases via native/AI routing."""
        if self.match(spoken, prefix) is not None:
            return False
        for item in self.entries():
            if item.get("enabled") and item.get("voice_enabled", True):
                continue
            if phrase_matches(dict(item, enabled=True), spoken, prefix, source="manual"):
                return True
        for original in BUILTINS:
            if original["id"] in self.deleted_builtins or original["id"] in self.builtin_overrides:
                if phrase_matches(original, spoken, prefix, source="manual"):
                    return True
        return False

    def save_command(self, raw):
        data = dict(raw)
        if not data.get("id"):
            data["id"] = "user_" + uuid.uuid4().hex[:16]
        identifier = data["id"]
        builtin = isinstance(identifier, str) and identifier in {item["id"] for item in BUILTINS}
        if isinstance(identifier, str) and identifier.startswith("built_") and not builtin:
            raise ValueError("Unknown built-in command")
        data["builtin"] = False
        validated = checked_command(data, builtin=builtin)
        if builtin:
            if identifier in self.deleted_builtins:
                raise ValueError("Command was deleted")
            def update_builtin():
                self.builtin_overrides[identifier] = validated
                if validated["enabled"]:
                    self.disabled_builtins.discard(identifier)
                else:
                    self.disabled_builtins.add(identifier)
            self._change(update_builtin)
            return dict(deepcopy(validated), customized=True)
        existing = next((i for i, x in enumerate(self.custom) if x["id"] == validated["id"]), None)
        if existing is None:
            if len(self.custom) >= MAX_USER_COMMANDS:
                raise ValueError("Too many custom commands")
            self._change(lambda: self.custom.append(validated))
        else:
            self._change(lambda: self.custom.__setitem__(existing, validated))
        return deepcopy(validated)

    # Retain old integrations while allowing the same editor to save presets.
    save_custom = save_command
    upsert = save_command

    def save_commands(self, records):
        """Validate/save a folder edit or clone as a single recoverable change."""
        if not isinstance(records, (list, tuple)) or len(records) > len(BUILTINS) + MAX_USER_COMMANDS:
            raise ValueError("Invalid command list")
        return self._change(lambda: [self.save_command(record) for record in records])

    def set_enabled(self, identifier, enabled):
        self.set_group_enabled([identifier], enabled)

    def set_group_enabled(self, identifiers, enabled):
        identifiers = set(identifiers)
        entries = {item["id"]: item for item in self.entries()}
        if not identifiers.issubset(entries):
            raise ValueError("Unknown command")
        def update():
            for identifier in identifiers:
                if entries[identifier]["builtin"]:
                    if enabled:
                        self.disabled_builtins.discard(identifier)
                    else:
                        self.disabled_builtins.add(identifier)
                    if identifier in self.builtin_overrides:
                        self.builtin_overrides[identifier]["enabled"] = bool(enabled)
                else:
                    next(item for item in self.custom if item["id"] == identifier)["enabled"] = bool(enabled)
        self._change(update)

    def remove_command(self, identifier):
        if identifier not in {item["id"] for item in self.entries()}:
            raise ValueError("Command not found")
        def update():
            if identifier in {item["id"] for item in BUILTINS}:
                self.deleted_builtins.add(identifier)
                self.builtin_overrides.pop(identifier, None)
                self.disabled_builtins.discard(identifier)
            else:
                self.custom = [item for item in self.custom if item["id"] != identifier]
        self._change(update)

    remove_custom = remove_command
    delete = remove_command

    def remove_commands(self, identifiers):
        identifiers = tuple(dict.fromkeys(identifiers))
        if not set(identifiers).issubset({item["id"] for item in self.entries()}):
            raise ValueError("Command not found")
        self._change(lambda: [self.remove_command(identifier) for identifier in identifiers])

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
