"""Validated, atomic command-library exchange; imports never activate commands."""
from __future__ import annotations

from copy import deepcopy
import json
import uuid

from luxai.command_registry import MAX_USER_COMMANDS, checked_command, is_agent_command


FORMAT = "luxai-commands"
VERSION = 2
MAX_BUNDLE_BYTES = 4 * 1024 * 1024
_KINDS = ("folders", "collections")
_DEFAULT_CATEGORIES = {"Мои команды", "Выученные команды", "Команды агента"}


def _scope(value):
    if value is not None and not isinstance(value, bool):
        raise ValueError("Invalid command scope")
    return value


def _name(value):
    if (not isinstance(value, str) or not 1 <= len(value.strip()) <= 60
            or any(ord(char) < 32 for char in value)):
        raise ValueError("Invalid group name")
    return value.strip()


def _bounded(payload):
    try:
        size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("Invalid command export format") from exc
    if size > MAX_BUNDLE_BYTES:
        raise ValueError("Command file exceeds the safe 4 MB import limit")


def _group(name, kind, agent):
    if kind not in _KINDS:
        raise ValueError("Unsupported group type")
    if not isinstance(agent, bool):
        raise ValueError("Invalid command scope")
    return {"name": _name(name), "kind": kind, "agent": agent}


def _available_name(name, used):
    candidate, number = name, 2
    while candidate.casefold() in used:
        suffix = f" ({number})"
        candidate = name[:60 - len(suffix)] + suffix
        number += 1
    used.add(candidate.casefold())
    return candidate


def _export_group_names(groups, records):
    """Represent legacy aliases without changing the source registry.

    Old files could name a folder and collection identically, although commands
    store only their category name. The first exact alias owns those commands,
    as it does in the tree; later aliases remain present as empty groups. Case-
    distinct categories retain their own members under separate export names.
    """
    declared = {(group["name"], group["agent"]) for group in groups}
    # Renaming an alias must not take the name of a separate implicit category
    # which has no metadata row of its own (for example an existing "Work (2)").
    used = {scope: {record["category"].casefold() for record in records
                    if is_agent_command(record) == scope
                    and (record["category"], scope) not in declared}
            for scope in (False, True)}
    categories, renamed = {}, []
    for group in groups:
        scope, original = group["agent"], group["name"]
        name = _available_name(original, used[scope])
        categories.setdefault((original, scope), name)
        renamed.append(dict(group, name=name))
    records = [dict(record, category=categories.get(
        (record["category"], is_agent_command(record)), record["category"]))
        for record in records]
    return renamed, records


def export_payload(registry, *, identifiers=None, group=None, agent=None,
                   include_empty_groups=None):
    """Export exact selected members, or personal records when no IDs are given.

    Virtual/default tree groups use the supplied member IDs and become an
    ordinary personal folder on import. Empty explicit collections are data too.
    """
    _scope(agent)
    entries = registry.entries()
    by_id = {record["id"]: record for record in entries}
    if group is not None and not isinstance(group, dict):
        raise ValueError("Invalid group")
    if identifiers is None and group is not None and "ids" in group:
        identifiers = group["ids"]
    if identifiers is None:
        records = [record for record in entries if not record["builtin"]]
        if group is not None:
            records = [record for record in records if record["category"] == group.get("name")]
        whole = group is None
    else:
        if not isinstance(identifiers, (list, tuple, set)):
            raise ValueError("Invalid command list")
        wanted = list(dict.fromkeys(identifiers))
        if any(not isinstance(value, str) or value not in by_id for value in wanted):
            raise ValueError("Unknown command")
        # Preserve registry/action order rather than an unordered tree selection.
        wanted = set(wanted)
        records = [record for record in entries if record["id"] in wanted]
        scoped_ids = {record["id"] for record in entries
                      if agent is None or is_agent_command(record) == agent}
        whole = wanted == scoped_ids and group is None
    if agent is not None:
        records = [record for record in records if is_agent_command(record) == agent]
    if len(records) > MAX_USER_COMMANDS:
        raise ValueError("Too many custom commands")
    groups = []
    if group is not None:
        group_agent = agent if agent is not None else group.get("agent", bool(records and is_agent_command(records[0])))
        selected_group = _group(group.get("name"), group.get("kind") or "folders", group_agent)
        groups.append(selected_group)
        records = [dict(record, category=selected_group["name"]) for record in records]
    else:
        categories = {(record["category"], is_agent_command(record)) for record in records}
        if include_empty_groups is not None:
            if not isinstance(include_empty_groups, bool):
                raise ValueError("Invalid group selection")
            whole = include_empty_groups
        for source in (False, True):
            if agent is not None and agent != source:
                continue
            names = registry.groups_for(source)
            for kind in _KINDS:
                for name in names[kind]:
                    if whole or (name, source) in categories:
                        groups.append(_group(name, kind, source))
    groups, records = _export_group_names(groups, records)
    payload = {"format": FORMAT, "version": VERSION,
               "commands": [checked_command(record, builtin=record.get("builtin", False)) for record in records],
               "groups": groups}
    _bounded(payload)
    return deepcopy(payload)


def _import_groups(payload):
    groups = payload.get("groups", [])
    if isinstance(groups, dict):
        # Accept the obvious old metadata shape without depending on it.
        if (any(key not in _KINDS for key in groups)
                or any(not isinstance(names, list) for names in groups.values())):
            raise ValueError("Invalid group list")
        groups = [{"name": name, "kind": kind, "agent": False}
                  for kind, names in groups.items() for name in names]
    if not isinstance(groups, list) or len(groups) > 400:
        raise ValueError("Invalid group list")
    checked, seen = [], set()
    for raw in groups:
        if not isinstance(raw, dict):
            raise ValueError("Invalid group")
        item = _group(raw.get("name"), raw.get("kind"), raw.get("agent", False))
        key = (item["name"].casefold(), item["agent"])
        if key in seen:
            raise ValueError("Duplicate group name")
        seen.add(key)
        checked.append(item)
    return checked


def import_payload(registry, payload, *, agent=None):
    """Validate the whole bundle before a single atomic registry replacement.

    Preserve reviewed triggers/options but import every command disabled. A new
    name is allocated for each incoming collection instead of silently merging
    it with an unrelated existing folder or category.
    """
    _scope(agent)
    if not isinstance(payload, dict):
        raise ValueError("Invalid command export format")
    _bounded(payload)
    version = payload.get("version", 1)
    if (not isinstance(version, int) or isinstance(version, bool) or version not in (1, VERSION)
            or payload.get("format") not in (None, FORMAT)):
        raise ValueError("Unsupported command export format or version")
    records = payload.get("commands")
    if not isinstance(records, list) or len(records) > MAX_USER_COMMANDS:
        raise ValueError("Invalid command list")
    if len(registry.custom) + len(records) > MAX_USER_COMMANDS:
        raise ValueError("Too many custom commands")
    groups = _import_groups(payload)
    items = []
    source_scopes = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Invalid command entry")
        raw = deepcopy(record)
        raw.update(id="user_" + uuid.uuid4().hex[:16], builtin=False, enabled=False)
        source_scopes.append(is_agent_command(checked_command(raw)))
        if agent is not None:
            raw["agent"] = agent
            if not agent:
                raw["learned"] = False
        items.append(checked_command(raw))

    # Only the incoming scope is affected. Existing same-name groups on the
    # other tab neither collide nor receive any of the imported commands.
    used = {scope: {"Мои команды".casefold(), "Выученные команды".casefold(), "Команды агента".casefold()}
            for scope in (False, True)}
    existing = registry.entries()
    for scope in (False, True):
        used[scope].update(name.casefold() for names in registry.groups_for(scope).values() for name in names)
        used[scope].update(record["category"].casefold() for record in existing if is_agent_command(record) == scope)
    planned = []
    mapping = {}

    def allocate(name, kind, scope, source_scope):
        # Two source tabs may each have a collection named "Work". Forcing
        # both into one destination tab must still keep the collections apart.
        key = (name, source_scope)
        if key in mapping:
            return mapping[key]
        candidate = _available_name(name, used[scope])
        mapping[key] = candidate
        planned.append(_group(candidate, kind, scope))
        return candidate

    for group in groups:
        scope = group["agent"] if agent is None else agent
        allocate(group["name"], group["kind"], scope, group["agent"])
    for item, source_scope in zip(items, source_scopes):
        scope = is_agent_command(item)
        category = item["category"]
        key = (category, source_scope)
        if key in mapping:
            item["category"] = mapping[key]
        elif category not in _DEFAULT_CATEGORIES:
            item["category"] = allocate(_name(category), "folders", scope, source_scope)
        elif agent is not None and category in _DEFAULT_CATEGORIES:
            item["category"] = "Команды агента" if agent else "Мои команды"

    final_counts = {(scope, kind): len(registry.groups_for(scope)[kind])
                    for scope in (False, True) for kind in _KINDS}
    for group in planned:
        key = (group["agent"], group["kind"])
        final_counts[key] += 1
        if final_counts[key] > 100:
            raise ValueError("Too many groups")

    def update():
        for group in planned:
            registry.groups_for(group["agent"])[group["kind"]].append(group["name"])
        registry.custom.extend(deepcopy(items))
    registry._change(update)
    return deepcopy(items)


export_bundle = export_payload
import_bundle = import_payload
