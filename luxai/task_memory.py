"""Bounded local task history and verified procedure hints.

Memory is untrusted context, never an execution queue or a source of permission.
Only a task with an explicitly verified successful outcome can teach a reusable
procedure. A future task still needs fresh observations and its normal runtime
tool policy; failed tasks and old answers cannot grant new permissions.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import unicodedata
import uuid


MEMORY_FILE = Path(__file__).resolve().parents[1] / ".luxai_data" / "agent_memory.json"
STATES = frozenset({"planned", "waiting", "running", "succeeded", "failed", "cancelled", "unverified"})
TOOLS = frozenset({"open_app", "screenshot", "visual_task", "research", "shell", "desktop_action"})
TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_TEXT = 800
MAX_GOAL = 2000
MAX_STEPS = 32
REDACTED = "[redacted]"
SHELL_RECONFIRM_QUESTION = (
    "Continue the shell task? Jarvis must create a fresh command proposal and "
    "apply the current execution policy before running it."
)
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b((?:[A-Za-z0-9_]+_)?(?:api[ _-]?key|access[ _-]?token|refresh[ _-]?token|token|password|passwd|"
    r"secret|authorization|cookie)(?:_[A-Za-z0-9_]+)?|bearer|пароль|токен|cheie[ _-]?api)\b"
    r"[\"']?\s*(?::|=|\bis\b|\beste\b)?\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;\"']+)"
)
_TOKEN = re.compile(
    r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{16,}|"
    r"AIza[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}|"
    r"eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})\b"
)
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S)
_BINARY_TEXT = re.compile(r"data:[^\s,;]+(?:;base64)?,[^\s]+|\b[A-Za-z0-9+/=_-]{100,}\b", re.I)
_SENSITIVE_MEDIA = re.compile(r"(?i)(?:[a-z]:[\\/]|/)?[^\s\"'<>]*\.(?:png|jpe?g|bmp|webp|wav|mp3|flac|ogg)\b")
_TOOL_ARGUMENTS = {
    "open_app": frozenset({"app", "name", "application", "target"}),
    "screenshot": frozenset({"reason", "scope", "monitor", "window", "target"}),
    "visual_task": frozenset({"instruction", "goal", "target", "clicks", "count", "button"}),
    "research": frozenset({"query", "topic", "language", "limit", "max_results"}),
    # Never retain command lines, environment values, stdout or stderr.
    "shell": frozenset({"purpose", "executable_class"}),
    "desktop_action": frozenset({"action", "target", "location", "count", "button", "key", "duration", "x", "y", "enabled", "delay_seconds"}),
}
_FORBIDDEN_ACTIONS = frozenset({"run_cmd", "run_powershell", "shell", "exec", "execute", "eval"})


class MemoryFormatError(ValueError):
    """Existing memory cannot be read safely and must not be overwritten."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _text(value, limit=MAX_TEXT):
    if not isinstance(value, str):
        return ""
    value = value[:max(limit * 4, 4096)]
    value = _PRIVATE_KEY.sub(REDACTED, value)
    value = _TOKEN.sub(REDACTED, value)
    value = _SECRET_ASSIGNMENT.sub(lambda item: item.group(1) + " " + REDACTED, value)
    value = _BINARY_TEXT.sub(REDACTED, value)
    value = _SENSITIVE_MEDIA.sub("[media omitted]", value)
    value = "".join(ch for ch in value if ord(ch) >= 32 or ch in "\n\t")
    return value.strip()[:limit]


def normalize_goal(goal):
    """Normalize case/punctuation, preserving words, accents and numbers."""
    text = unicodedata.normalize("NFKC", _text(goal, MAX_GOAL)).casefold()
    return " ".join("".join(ch if ch.isalnum() else " " for ch in text).split())


def redact_text(value, limit=MAX_TEXT):
    """Bound and redact known credential/media patterns before storing context.

    This is defense in depth, not a general secret detector. Callers must still
    avoid passing environment dumps, credential files, recordings or raw binary
    results. Bytes and other non-text values are omitted instead of stringified.
    """
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 8000:
        raise ValueError("Text limit must be between 1 and 8000")
    return _text(value, limit)


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise ValueError("Invalid task identifier")
    return value


def _evidence(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for key in ("kind", "summary", "source", "expected", "observed"):
        if isinstance(value.get(key), str):
            result[key] = _text(value[key], 400 if key in {"expected", "observed"} else MAX_TEXT)
    for key in ("matched", "exists", "visible", "confirmed"):
        if isinstance(value.get(key), bool):
            result[key] = value[key]
    if isinstance(value.get("exit_code"), int) and not isinstance(value["exit_code"], bool):
        result["exit_code"] = max(-255, min(255, value["exit_code"]))
    return result


def _has_evidence(value):
    return bool(value.get("summary") or value.get("kind"))


def _safe_step(step):
    if not isinstance(step, dict) or step.get("tool") not in TOOLS:
        raise ValueError("Unsupported procedure tool")
    tool = step["tool"]
    arguments = step.get("arguments", {})
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be structured")
    result = {}
    for key in _TOOL_ARGUMENTS[tool]:
        value = arguments.get(key)
        if key == "enabled" and key in arguments:
            if type(value) is not bool:
                raise ValueError("Remembered enabled must be a boolean")
            result[key] = value
            continue
        if key == "delay_seconds" and key in arguments:
            if type(value) is not int or not 30 <= value <= 300:
                raise ValueError("Remembered shutdown delay must be from 30 to 300 seconds")
            result[key] = value
            continue
        if isinstance(value, str):
            result[key] = _text(value, 400)
        elif isinstance(value, bool):
            result[key] = value
        elif isinstance(value, (int, float)) and math.isfinite(value):
            result[key] = max(-1_000_000, min(1_000_000, value))
    if tool == "desktop_action" and str(result.get("action", "")).casefold() in _FORBIDDEN_ACTIONS:
        raise ValueError("Raw shell actions cannot be saved in automatic procedure memory")
    if tool == "shell" and result.get("executable_class") not in {None, "cmd", "powershell", "python", "bash", "other"}:
        result["executable_class"] = "other"
    return {"tool": tool, "arguments": result}


def _tool_result(tool, ok, summary, evidence, verified, *, sequence=0, when=None):
    if tool not in TOOLS or not isinstance(ok, bool) or not isinstance(verified, bool):
        raise ValueError("A tool result needs a known tool and explicit boolean outcome")
    evidence = _evidence(evidence)
    if verified and (not ok or not _has_evidence(evidence)):
        raise ValueError("Verified success needs a successful result and explicit observation evidence")
    return {
        "sequence": sequence, "time": when or _now(), "kind": "tool_result",
        "tool": tool, "ok": ok, "verified": verified,
        "summary": _text(summary), "evidence": evidence,
    }


class TaskMemory:
    """Atomic, bounded history shared by instances in the application process.

    Mutations reload the file under a path-specific lock before saving, so
    background workers do not overwrite each other's task events. Returned
    dictionaries are copies. A corrupt/oversized file is reported rather than
    silently erased. This class never executes remembered tools.
    """

    def __init__(self, path=None, *, max_tasks=50, max_events=32, max_procedures=50):
        self.path = Path(path) if path is not None else MEMORY_FILE
        for name, value in (("max_tasks", max_tasks), ("max_events", max_events), ("max_procedures", max_procedures)):
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 200:
                raise ValueError(name + " must be between 1 and 200")
        self.max_tasks, self.max_events, self.max_procedures = max_tasks, max_events, max_procedures
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(os.path.normcase(str(self.path.resolve())), threading.RLock())

    def _read(self):
        if not self.path.exists():
            return {"version": 1, "tasks": [], "procedures": []}
        try:
            if self.path.stat().st_size > MAX_FILE_BYTES:
                raise MemoryFormatError("Task memory is too large to read safely")
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if (not isinstance(data, dict) or data.get("version") != 1
                    or not isinstance(data.get("tasks"), list) or not isinstance(data.get("procedures"), list)):
                raise MemoryFormatError("Unsupported task memory format")
        except (OSError, UnicodeError, ValueError, RecursionError) as exc:
            raise MemoryFormatError("Task memory cannot be read; existing data was preserved") from exc
        # Sanitize again on read: memory edited outside the app is untrusted.
        clean = {"version": 1, "tasks": [], "procedures": []}
        for raw in data["tasks"][-self.max_tasks:]:
            try:
                task = self._clean_task(raw)
            except (TypeError, ValueError, KeyError, OverflowError):
                continue
            clean["tasks"].append(task)
        for raw in data["procedures"][-self.max_procedures:]:
            try:
                procedure = self._clean_procedure(raw)
            except (TypeError, ValueError, KeyError, OverflowError):
                continue
            clean["procedures"].append(procedure)
        return clean

    def _clean_task(self, raw):
        if not isinstance(raw, dict) or raw.get("state") not in STATES:
            raise ValueError("Invalid task")
        task = {
            "id": _identifier(raw["id"]), "goal": _text(raw.get("goal"), MAX_GOAL),
            "state": raw["state"], "summary": _text(raw.get("summary")),
            "created_at": _text(raw.get("created_at"), 40), "updated_at": _text(raw.get("updated_at"), 40),
            "verified": bool(raw.get("verified") is True and raw["state"] == "succeeded"),
            "events": [], "last_feedback": None,
        }
        task["normalized_goal"] = normalize_goal(task["goal"])
        for entry in raw.get("events", [])[-self.max_events:]:
            if not isinstance(entry, dict):
                continue
            sequence = max(0, int(entry.get("sequence", 0)))
            when = _text(entry.get("time"), 40)
            if entry.get("kind") == "tool_result":
                try:
                    item = _tool_result(entry.get("tool"), entry.get("ok"), entry.get("summary", ""),
                                        entry.get("evidence"), entry.get("verified", False), sequence=sequence, when=when)
                except ValueError:
                    continue
            elif entry.get("kind") == "state" and entry.get("state") in STATES:
                item = {"kind": "state", "sequence": sequence, "time": when,
                        "state": entry["state"], "summary": _text(entry.get("summary"))}
            elif entry.get("kind") == "feedback":
                item = {"kind": "feedback", "sequence": sequence, "time": when,
                        "question": _text(entry.get("question"), MAX_GOAL), "answer": _text(entry.get("answer")),
                        "scope_task_id": task["id"]}
            else:
                continue
            task["events"].append(item)
        if isinstance(raw.get("last_feedback"), dict):
            item = raw["last_feedback"]
            task["last_feedback"] = {"question": _text(item.get("question"), MAX_GOAL),
                                     "answer": _text(item.get("answer")), "scope_task_id": task["id"]}
        task["next_sequence"] = max([0] + [item["sequence"] for item in task["events"]]) + 1
        if isinstance(raw.get("checkpoint"), dict):
            task["checkpoint"] = self._clean_checkpoint(task["id"], **{
                key: raw["checkpoint"].get(key, default) for key, default in {
                    "steps": [], "user_answers": [], "pending_question": "", "status": "running",
                    "actions": [], "attempts": 0, "elapsed_seconds": 0,
                    "pending_tool": None,
                }.items()
            })
        return task

    def _clean_procedure(self, raw):
        if not isinstance(raw, dict) or raw.get("verified") is not True:
            raise ValueError("Unverified procedure")
        steps = raw.get("steps")
        if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
            raise ValueError("Invalid procedure steps")
        evidence = _evidence(raw.get("verification"))
        if not _has_evidence(evidence):
            raise ValueError("Missing verification")
        goal = _text(raw.get("goal"), MAX_GOAL)
        return {
            "id": _identifier(raw["id"]), "goal": goal, "normalized_goal": normalize_goal(goal),
            "steps": [_safe_step(step) for step in steps], "verification": evidence,
            "verified": True, "source_task_id": _identifier(raw["source_task_id"]),
            "updated_at": _text(raw.get("updated_at"), 40),
            "success_count": max(1, min(100000, int(raw.get("success_count", 1)))),
        }

    def _write(self, data):
        data["tasks"] = sorted(data["tasks"], key=lambda item: item["updated_at"])[-self.max_tasks:]
        data["procedures"] = sorted(data["procedures"], key=lambda item: item["updated_at"])[-self.max_procedures:]
        payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
        while len(payload) > MAX_FILE_BYTES and (len(data["tasks"]) > 1 or data["procedures"]):
            if len(data["tasks"]) > 1:
                data["tasks"].pop(0)
            else:
                data["procedures"].pop(0)
            payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
        if len(payload) > MAX_FILE_BYTES:
            raise ValueError("Task memory size limit reached; existing data was preserved")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    @staticmethod
    def _find(data, task_id):
        task_id = _identifier(task_id)
        for task in data["tasks"]:
            if task["id"] == task_id:
                return task
        raise KeyError("Task not found")

    def _append(self, task, entry):
        entry["sequence"] = task["next_sequence"]
        entry["time"] = _now()
        task["next_sequence"] += 1
        task["events"] = (task["events"] + [entry])[-self.max_events:]
        task["updated_at"] = entry["time"]

    def create_task(self, goal, task_id=None):
        if not isinstance(goal, str) or len(goal) > MAX_GOAL:
            raise ValueError("A task goal must be text up to 2000 characters")
        goal = _text(goal, MAX_GOAL)
        if not normalize_goal(goal):
            raise ValueError("A task needs a nonempty goal")
        task_id = _identifier(task_id if task_id is not None else uuid.uuid4().hex)
        with self._lock:
            data = self._read()
            if any(task["id"] == task_id for task in data["tasks"]):
                raise ValueError("Task identifier already exists")
            now = _now()
            task = {"id": task_id, "goal": goal, "normalized_goal": normalize_goal(goal), "state": "planned",
                    "summary": "", "verified": False, "created_at": now, "updated_at": now,
                    "events": [], "last_feedback": None, "next_sequence": 1}
            data["tasks"].append(task)
            self._write(data)
        return task_id

    def get_task(self, task_id):
        with self._lock:
            try:
                return deepcopy(self._find(self._read(), task_id))
            except KeyError:
                return None

    load_task = get_task

    def list_tasks(self, *, status=None, limit=10):
        if status is not None and status not in STATES:
            raise ValueError("Invalid task status filter")
        limit = max(1, min(self.max_tasks, int(limit)))
        with self._lock:
            tasks = self._read()["tasks"]
        matches = [item for item in tasks if status is None or item["state"] == status]
        return deepcopy(sorted(matches, key=lambda item: item["updated_at"], reverse=True)[:limit])

    def latest_waiting_task(self):
        tasks = self.list_tasks(status="waiting", limit=1)
        return tasks[0] if tasks else None

    def set_state(self, task_id, state, summary="", verified=False):
        if state not in STATES or not isinstance(verified, bool):
            raise ValueError("Invalid task state")
        with self._lock:
            data = self._read()
            task = self._find(data, task_id)
            previous = task["state"]
            if previous in TERMINAL and state != previous:
                raise ValueError("A finished task cannot be silently restarted")
            if state == "succeeded":
                results = [event for event in task["events"] if event["kind"] == "tool_result"]
                if not verified or not results or not results[-1]["ok"] or not results[-1]["verified"]:
                    raise ValueError("Success requires a fresh verified successful tool result")
            elif verified:
                raise ValueError("Only a successful task can be marked verified")
            task.update(state=state, summary=_text(summary), verified=state == "succeeded" and verified)
            self._append(task, {"kind": "state", "time": _now(), "state": state, "summary": _text(summary)})
            self._write(data)

    def record_tool_result(self, task_id, tool, ok, summary="", evidence=None, verified=False):
        event = _tool_result(tool, ok, summary, evidence, verified)
        with self._lock:
            data = self._read()
            task = self._find(data, task_id)
            self._append(task, event)
            self._write(data)

    def record_feedback(self, task_id, text, question=""):
        answer, question = _text(text), _text(question, MAX_GOAL)
        if not answer:
            raise ValueError("Feedback must not be empty")
        with self._lock:
            data = self._read()
            task = self._find(data, task_id)
            task["last_feedback"] = {"question": question, "answer": answer, "scope_task_id": task["id"]}
            self._append(task, {"kind": "feedback", "time": _now(), "question": question,
                                "answer": answer, "scope_task_id": task["id"]})
            self._write(data)

    @staticmethod
    def _clean_checkpoint(task_id, *, steps, user_answers, pending_question="", status="running",
                          actions=None, attempts=0, elapsed_seconds=0.0, pending_tool=None):
        if status not in STATES or not isinstance(steps, list) or not isinstance(user_answers, list):
            raise ValueError("Invalid task checkpoint")
        clean_steps = []
        for step in steps[-MAX_STEPS:]:
            if not isinstance(step, dict) or step.get("tool") not in TOOLS:
                continue
            evidence = _evidence(step.get("evidence"))
            ok = step.get("ok") is True
            executed = step.get("executed", True) is True
            verified = executed and ok and step.get("verified") is True and _has_evidence(evidence)
            clean_steps.append({
                "step": max(0, min(10000, int(step.get("step", len(clean_steps) + 1)))),
                "tool": step["tool"], "ok": ok, "executed": executed,
                "verified": verified,
                "goal_satisfied": verified and step.get("goal_satisfied") is True,
                "summary": _text(step.get("summary")), "evidence": evidence,
            })
        clean_answers = []
        for item in user_answers[-16:]:
            if isinstance(item, dict):
                clean_answers.append({"question": _text(item.get("question"), MAX_GOAL),
                                      "answer": _text(item.get("answer")), "scope_task_id": task_id})
        fingerprints = [item for item in (actions or []) if isinstance(item, str) and re.fullmatch(r"[a-f0-9]{64}", item)]
        elapsed = float(elapsed_seconds)
        if not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("Invalid elapsed task time")
        pending = None
        if isinstance(pending_tool, dict):
            pending = _safe_step(pending_tool)
            pending["question_key"] = _text(pending_tool.get("question_key"), 100)
            pending["requires_fresh_policy_check"] = True
        # The live approval prompt may display the exact command. Keep that
        # useful review detail in the current UI only; command lines must not
        # leak into durable history through the conversational question field.
        question = _text(pending_question, MAX_GOAL)
        if question and pending and pending["tool"] == "shell":
            question = SHELL_RECONFIRM_QUESTION
        return {"steps": clean_steps, "user_answers": clean_answers, "scope_task_id": task_id,
                "pending_question": question, "status": status,
                "actions": fingerprints[-MAX_STEPS:], "attempts": max(0, min(1000, int(attempts))),
                "elapsed_seconds": min(3600.0, elapsed), "pending_tool": pending}

    def save_checkpoint(self, task_id, *, steps, user_answers, pending_question="", status="running",
                        actions=None, attempts=0, elapsed_seconds=0.0, pending_tool=None):
        checkpoint = self._clean_checkpoint(task_id, steps=steps, user_answers=user_answers,
                                           pending_question=pending_question, status=status,
                                           actions=actions, attempts=attempts, elapsed_seconds=elapsed_seconds,
                                           pending_tool=pending_tool)
        with self._lock:
            data = self._read()
            task = self._find(data, task_id)
            task["checkpoint"] = checkpoint
            task["updated_at"] = _now()
            self._write(data)

    def save_procedure(self, task_id, steps, verification, approved=False):
        if approved is not True:
            raise ValueError("Only structured steps approved for the completed task may be learned")
        if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
            raise ValueError("A procedure needs 1 to 32 structured steps")
        safe_steps = [_safe_step(step) for step in steps]
        proof = _evidence(verification)
        if not _has_evidence(proof):
            raise ValueError("A procedure needs explicit outcome verification")
        with self._lock:
            data = self._read()
            task = self._find(data, task_id)
            if task["state"] != "succeeded" or task["verified"] is not True:
                raise ValueError("Failed, cancelled and unverified tasks cannot teach reusable procedures")
            results = [event for event in task["events"] if event["kind"] == "tool_result"]
            if not results or not results[-1]["verified"] or not results[-1]["ok"]:
                raise ValueError("Procedure learning needs the latest verified successful outcome")
            completed = iter(event["tool"] for event in results if event["ok"])
            if not all(any(tool == step["tool"] for tool in completed) for step in safe_steps):
                raise ValueError("A procedure may describe only tools that actually succeeded in this task")
            canonical = json.dumps(safe_steps, sort_keys=True, ensure_ascii=False)
            same = next((item for item in data["procedures"] if item["normalized_goal"] == task["normalized_goal"]
                         and json.dumps(item["steps"], sort_keys=True, ensure_ascii=False) == canonical), None)
            if same is None:
                same = {"id": uuid.uuid4().hex, "success_count": 0}
                data["procedures"].append(same)
            same.update(goal=task["goal"], normalized_goal=task["normalized_goal"], steps=safe_steps,
                        verification=proof, verified=True, source_task_id=task_id, updated_at=_now(),
                        success_count=same["success_count"] + 1)
            self._write(data)
            return same["id"]

    def lookup(self, goal):
        """Return procedure hints only for an exact normalized goal.

        Conflicting successful procedures produce a clarification question,
        never a guessed target. Feedback/checkpoints are deliberately excluded
        because user answers apply only to their original task.
        """
        normalized = normalize_goal(goal)
        with self._lock:
            data = self._read()
        matches = [item for item in data["procedures"] if normalized and item["normalized_goal"] == normalized]
        result = {"status": "none", "procedure": None, "question": "", "candidates": [],
                  "requires_fresh_observation": True, "permission_scope": "current_task_only"}
        recent = [item for item in data["tasks"] if normalized and item["normalized_goal"] == normalized]
        result["recent_outcomes"] = [{"task_id": item["id"], "state": item["state"],
                                      "verified": item["verified"], "summary": item["summary"]}
                                     for item in sorted(recent, key=lambda item: item["updated_at"], reverse=True)[:5]]
        # Records edited externally may repeat the same hint; only materially
        # different procedures create a genuine ambiguity.
        unique = {}
        for item in matches:
            fingerprint = hashlib.sha256(json.dumps(item["steps"], sort_keys=True).encode("utf-8")).hexdigest()
            unique[fingerprint] = item
        matches = list(unique.values())
        omitted = any(marker in _text(goal) for marker in (REDACTED, "[media omitted]"))
        if matches:
            omitted = omitted or any(marker in json.dumps(matches, ensure_ascii=False)
                                     for marker in (REDACTED, "[media omitted]"))
        if len(matches) > 1 or (matches and omitted):
            result["status"] = "ambiguous"
            result["question"] = "Which target or successful procedure do you mean? Please clarify this task."
            result["candidates"] = [{"id": item["id"], "goal": item["goal"],
                                     "tools": [step["tool"] for step in item["steps"]]} for item in matches[:5]]
        elif matches:
            result["status"] = "match"
            result["procedure"] = deepcopy(matches[0])
        return result
