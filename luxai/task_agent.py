"""A bounded, evidence-driven task loop; actual planning and tools are injected.

The model chooses a next step after every actual tool result. This module has no
network or desktop access and never interprets model prose as execution proof.
Checkpoints contain summaries and action hashes, not screenshots or tool payloads.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
import threading
import time
import uuid


MAX_STEPS = 12
MAX_SECONDS = 300.0
MAX_GOAL = 2000
MAX_CONSECUTIVE_FAILURES = 3
TOOLS = ("open_app", "screenshot", "visual_task", "research", "shell", "desktop_action")
TOOL_MANIFEST = [
    {"name": "open_app", "description": "Open an installed application natively and verify its window.",
     "arguments": {"target": "application name (or use the name alias)"},
     "optional_arguments": {"name": "alias for target"}},
    {"name": "screenshot", "description": "Observe the current desktop only when visual work is needed.",
     "arguments": {"reason": "why the user's task needs an observation"},
     "optional_arguments": {"scope": "desktop; capture is saved locally"}},
    {"name": "visual_task", "description": "Perform bounded visual interaction and inspect the resulting state.",
     "arguments": {"goal": "remaining visual task"}},
    {"name": "research", "description": "Research a question and return observed sources and findings.",
     "arguments": {"query": "question to investigate"}},
    {"name": "shell", "description": "Run a locally permitted command through the runtime's approval policy.",
     "arguments": {"shell": "cmd or powershell", "command": "command",
                   "purpose": "relationship to the user goal",
                   "verification": {"command": "read-only result check", "expect": "expected output text",
                                    "shell": "optional: cmd or powershell; defaults to the command shell"}}},
    {"name": "desktop_action", "description": "Run a supported native desktop action and verify its effect.",
     "arguments": {"action": "an action advertised by runtime_facts.native_actions"},
     "optional_arguments": {"target": "action target", "location": "supported action location",
                            "enabled": "boolean, required for set_dark_theme",
                            "delay_seconds": "integer 30 through 300 for shutdown/restart; default 30"}},
]

_TRANSIENT = OrderedDict()
_TRANSIENT_LOCK = threading.Lock()
_OPEN = re.compile(r"(?<!\w)(?:открой|открыть|запусти|запустить|open|launch|start|deschide|pornește|porneste)(?!\w)", re.I)
_VISUAL = re.compile(r"(?<!\w)(?:экран\w*|скриншот\w*|кнопк\w*|нажми|клик\w*|заполни|напечатай|введи|screen\w*|screenshot\w*|click|button\w*|type|fill|ecran\w*|apasă|apasa|buton\w*)(?!\w)", re.I)
_COMPOUND = re.compile(
    r"(?<!\w)(?:затем|потом|then|apoi)(?!\w)|"
    r"(?<!\w)(?:и|and|și|si)\s+(?:нажми|клик\w*|расскажи|найди|запиши|сохрани|"
    r"открой|запусти|посчитай|проверь|покажи|click|type|tell|find|write|save|open|launch|"
    r"research|calculate|check|show|scrie|apasă|apasa|caută|cauta)(?!\w)", re.I)


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    verified: bool
    summary: str
    evidence: object = field(default_factory=dict)
    data: dict = field(default_factory=dict)
    question: str = ""


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    status: str
    summary: str
    steps: list = field(default_factory=list)
    question: str = ""
    evidence: list = field(default_factory=list)
    reason: str = ""

    @property
    def ok(self):
        return self.status == "completed"

    @property
    def verified(self):
        return self.ok

    def to_dict(self):
        return asdict(self)


def _facts(execute):
    value = getattr(execute, "runtime_facts", {})
    value = value() if callable(value) else value
    return deepcopy(value) if isinstance(value, dict) else {}


def _decision(value):
    if not isinstance(value, dict):
        raise ValueError("The next step must be a JSON object.")
    action = value.get("action")
    allowed = {
        "tool": {"action", "tool", "arguments"},
        "ask": {"action", "question"},
        "finish": {"action", "summary"},
    }
    if action not in allowed or set(value) - allowed[action]:
        raise ValueError("Unsupported next-step action or fields.")
    if action == "tool":
        if value.get("tool") not in TOOLS or not isinstance(value.get("arguments"), dict):
            raise ValueError("A tool step needs a supported tool and argument object.")
        encoded = json.dumps(value["arguments"], sort_keys=True, ensure_ascii=False, allow_nan=False)
        if len(encoded) > 16000:
            raise ValueError("Tool arguments are too large.")
    else:
        key = "question" if action == "ask" else "summary"
        if not isinstance(value.get(key), str) or not value[key].strip() or len(value[key]) > 4000:
            raise ValueError("A question or completion summary must be a nonempty bounded string.")
    return deepcopy(value)


def _tool_result(value):
    if isinstance(value, dict):
        if set(value) - {"ok", "verified", "summary", "evidence", "data", "question"}:
            raise ValueError("Unsupported tool-result fields.")
        value = ToolResult(**value)
    if not isinstance(value, ToolResult):
        raise ValueError("Tool callback must return ToolResult or its JSON representation.")
    if type(value.ok) is not bool or type(value.verified) is not bool:
        raise ValueError("Tool outcome flags must be booleans.")
    if not isinstance(value.summary, str) or not isinstance(value.question, str) or not isinstance(value.data, dict):
        raise ValueError("Invalid tool summary, question, or data.")
    if not isinstance(value.evidence, (dict, list, str, tuple)):
        raise ValueError("Tool evidence must contain observed facts.")
    evidence = deepcopy(value.evidence)
    if isinstance(evidence, str):
        evidence = {"kind": "tool_observation", "summary": evidence[:4000]} if evidence.strip() else {}
    elif isinstance(evidence, (list, tuple)):
        observations = [str(item)[:1000] for item in evidence[:8] if item]
        evidence = {"kind": "tool_observation", "summary": "; ".join(observations)} if observations else {}
    has_evidence = bool(evidence.get("kind") or evidence.get("summary"))
    # A successful process launch or a model's claim alone is not verification.
    return ToolResult(value.ok, bool(value.ok and value.verified and has_evidence and value.data.get("executed") is not False),
                      value.summary[:4000], evidence, deepcopy(value.data), value.question[:4000])


def _fingerprint(tool, arguments):
    body = json.dumps([tool, arguments], sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _checkpoint(state):
    # The live data of a tool may include screenshots, credentials, or opaque
    # runtime objects. Only scoped summaries and replay-prevention hashes persist.
    return {
        "steps": [{key: deepcopy(step[key]) for key in
                   ("step", "tool", "ok", "verified", "summary", "evidence", "executed", "goal_satisfied") if key in step}
                  for step in state["steps"]],
        "user_answers": deepcopy(state["user_answers"]),
        "pending_question": state["pending_question"],
        "status": state["status"], "actions": list(state["actions"]),
        "attempts": state["attempts"], "elapsed_seconds": state["elapsed_seconds"],
        "pending_tool": deepcopy(state.get("pending_tool")),
    }


def _load(memory, task_id):
    if memory is not None:
        return memory.get_task(task_id)
    with _TRANSIENT_LOCK:
        return deepcopy(_TRANSIENT.get(task_id))


def _persist(memory, state):
    checkpoint = _checkpoint(state)
    if memory is not None:
        if checkpoint["status"] == "completed":
            checkpoint["status"] = "succeeded"
        memory.save_checkpoint(state["task_id"], **checkpoint)
    else:
        with _TRANSIENT_LOCK:
            _TRANSIENT[state["task_id"]] = {"goal": state["goal"], "checkpoint": checkpoint,
                                             "summary": state.get("summary", "")}
            _TRANSIENT.move_to_end(state["task_id"])
            while len(_TRANSIENT) > 50:
                _TRANSIENT.popitem(last=False)


def run_task(goal, decide, execute, *, memory=None, cancelled=None, progress=None,
             task_id=None, clarification=None):
    """Run or resume a task without executing prior steps again.

    ``decide(context)`` returns exactly one tool/ask/finish decision.
    ``execute(tool, arguments, context)`` returns actual, independently verified
    tool results. Its optional ``runtime_facts`` mapping supplies capabilities,
    ``opening_goal`` and ``explicit_visual_need``. Runtime policy remains the
    executor's responsibility: model output never grants shell or desktop access.
    ``progress(event)`` receives structured events and must never block for input.
    Waiting tasks return immediately; pass their id and a clarification to resume.
    """
    if not isinstance(goal, str) or not goal.strip() or len(goal) > MAX_GOAL:
        return TaskResult(str(task_id or ""), "failed", "A bounded, nonempty task goal is required.", reason="invalid_goal")
    if clarification is not None and (not isinstance(clarification, str) or not clarification.strip() or len(clarification) > 4000):
        return TaskResult(str(task_id or ""), "failed", "A nonempty clarification is required.", reason="invalid_clarification")
    started = time.monotonic()
    try:
        saved = _load(memory, task_id) if task_id else None
        if task_id and not saved:
            return TaskResult(str(task_id), "failed", "The task could not be found; no actions were replayed.", reason="unknown_task")
        if saved and memory is not None:
            from luxai.task_memory import normalize_goal
            same_goal = saved.get("normalized_goal") == normalize_goal(goal)
        else:
            same_goal = not saved or saved.get("goal") == goal
        if not same_goal:
            return TaskResult(str(task_id), "failed", "This task id belongs to a different goal.", reason="goal_mismatch")
        if not task_id:
            task_id = memory.create_task(goal) if memory is not None else uuid.uuid4().hex
        old = saved.get("checkpoint", {}) if saved else {}
        state = {
            "task_id": task_id, "goal": goal, "steps": deepcopy(old.get("steps", [])),
            "user_answers": deepcopy(old.get("user_answers", [])),
            "pending_question": old.get("pending_question", ""),
            "status": old.get("status", "running"), "actions": list(old.get("actions", [])),
            "attempts": int(old.get("attempts", 0)), "elapsed_seconds": float(old.get("elapsed_seconds", 0)),
            "summary": saved.get("summary", "") if saved else "",
            "pending_tool": deepcopy(old.get("pending_tool")),
        }
        facts = _facts(execute)
        hints = memory.lookup(goal) if memory is not None and hasattr(memory, "lookup") else {}
    except Exception:
        return TaskResult(str(task_id or ""), "failed", "Task memory or runtime facts could not be loaded.", reason="initialization_error")

    previous_elapsed = state["elapsed_seconds"]
    live_results = []
    opening = bool(facts.get("opening_goal", _OPEN.search(goal)))
    visual = bool(facts.get("explicit_visual_need", _VISUAL.search(goal)))
    multiple = bool(facts.get("requires_multiple_steps", _COMPOUND.search(goal)))

    def emit(event, **payload):
        if progress:
            try:
                progress({"event": event, "task_id": task_id, **payload})
            except Exception:
                # A detached UI must not change an already executed action.
                pass

    def elapsed():
        return previous_elapsed + max(0.0, time.monotonic() - started)

    def finish(status, summary, *, question="", reason=""):
        state.update(status=status, summary=summary, pending_question=question, elapsed_seconds=elapsed())
        evidence = [deepcopy(step["evidence"]) for step in state["steps"]
                    if step.get("ok") and step.get("verified") and step.get("evidence")]
        try:
            _persist(memory, state)
            if memory is not None:
                memory.set_state(task_id, "succeeded" if status == "completed" else status,
                                 summary=summary, verified=status == "completed")
        except Exception:
            status, reason = "unverified", "memory_error"
            summary = "Task checkpoint could not be saved. Review the observed results before continuing."
            state.update(status=status, summary=summary)
            try:
                _persist(memory, state)
            except Exception:
                pass
        result = TaskResult(task_id, status, summary, deepcopy(state["steps"]), question, evidence, reason)
        emit("finished", result=result.to_dict())
        return result

    if state["status"] in {"completed", "succeeded", "failed", "cancelled", "unverified"}:
        return TaskResult(task_id, "completed" if state["status"] == "succeeded" else state["status"],
                          state["summary"], deepcopy(state["steps"]),
                          evidence=[deepcopy(step["evidence"]) for step in state["steps"]
                                    if step.get("ok") and step.get("verified") and step.get("evidence")],
                          reason="already_finished")
    if state["pending_question"]:
        if clarification is None:
            return finish("waiting", "The task is waiting for your answer.", question=state["pending_question"], reason="clarification_required")
        question = state["pending_question"]
        state["user_answers"].append({"question": question, "answer": clarification.strip()})
        state["pending_question"] = ""
        if memory is not None:
            try:
                memory.record_feedback(task_id, clarification.strip(), question=question)
            except Exception:
                return finish("unverified", "The clarification could not be saved.", reason="memory_error")
    elif clarification is not None:
        return finish("failed", "There is no pending question for this task.", reason="unexpected_clarification")
    state["status"] = "running"
    try:
        _persist(memory, state)
        if memory is not None:
            memory.set_state(task_id, "running")
    except Exception:
        return finish("unverified", "The task checkpoint could not be saved.", reason="memory_error")
    emit("started", resumed=bool(saved), goal=goal)

    failures = 0
    for step in reversed(state["steps"]):
        if step.get("ok") and step.get("verified"):
            break
        failures += 1

    while state["attempts"] < MAX_STEPS:
        if cancelled and cancelled():
            return finish("cancelled", "The task was cancelled.", reason="cancelled")
        if elapsed() >= MAX_SECONDS:
            return finish("unverified" if state["steps"] else "failed", "The task reached its time limit.", reason="deadline")
        context = {
            "task_id": task_id, "goal": goal,
            "tools": deepcopy(TOOL_MANIFEST), "runtime_facts": deepcopy(facts),
            "history": deepcopy(state["steps"]), "tool_results": deepcopy(live_results or state["steps"]),
            "user_answers": deepcopy(state["user_answers"]),
            "pending_tool": deepcopy(state["pending_tool"]),
            "memory": deepcopy(hints),
            "remaining_steps": MAX_STEPS - state["attempts"],
            "remaining_seconds": max(0.0, MAX_SECONDS - elapsed()),
            "policy": {"native_open_first": opening, "explicit_visual_need": visual,
                       "completion_requires_verified_evidence": True,
                       "do_not_repeat_completed_actions": True,
                       "screenshots_are_observations_not_completed_goals": True},
        }
        state["attempts"] += 1
        try:
            decision = _decision(decide(deepcopy(context)))
        except Exception as exc:
            return finish("unverified" if state["steps"] else "failed",
                          "The planner did not return a valid next step.", reason="invalid_decision:" + type(exc).__name__)
        if cancelled and cancelled():
            return finish("cancelled", "The task was cancelled.", reason="cancelled")
        if elapsed() >= MAX_SECONDS:
            return finish("unverified" if state["steps"] else "failed", "The task reached its time limit.", reason="deadline")
        emit("decision", decision=deepcopy(decision))
        action = decision["action"]
        if action == "ask":
            question = decision["question"].strip()
            return finish("waiting", "The task needs clarification.", question=question, reason="clarification_required")
        if action == "finish":
            last = state["steps"][-1] if state["steps"] else {}
            last_live = live_results[-1] if live_results else {}
            explicit_complete = last_live.get("data", {}).get("goal_complete") is True
            # Old proof is not a promise that later actions preserved the
            # goal. The latest executed step must re-observe its satisfaction.
            latest_effect = next((item for item in reversed(state["steps"])
                                  if item.get("executed", True)), {})
            proof = bool(latest_effect.get("goal_satisfied") and latest_effect.get("verified")
                         and latest_effect.get("ok"))
            complete = bool(last.get("ok") and last.get("verified") and last.get("evidence"))
            if facts.get("requires_goal_evidence"):
                complete = complete and proof
            else:
                complete = (complete and last.get("tool") != "screenshot"
                            and not (last.get("tool") == "open_app" and (visual or multiple) and not explicit_complete))
            if complete:
                return finish("completed", decision["summary"].strip())
            return finish("unverified", "The requested result has not been verified; completion was not confirmed.", reason="unverified_finish")

        tool, arguments = decision["tool"], decision["arguments"]
        fingerprint = _fingerprint(tool, arguments)
        prior_tools = [item for item in state["steps"] if item.get("tool") in TOOLS and item.get("executed", True)]
        latest_native = next((item for item in reversed(prior_tools) if item["tool"] == "open_app"), None)
        native_failed = bool(latest_native and not (latest_native.get("ok") and latest_native.get("verified")))
        error = ""
        if opening and not any(item["tool"] == "open_app" for item in prior_tools) and tool != "open_app":
            error = "Open the application natively with open_app before using another tool."
        elif tool in {"screenshot", "visual_task"} and not (visual or native_failed):
            error = "The user has not requested visual work and native opening has not failed."
        elif fingerprint in state["actions"]:
            previous_ok = any(item.get("action_hash") == fingerprint and item.get("ok") for item in state["steps"])
            # Resumed checkpoints deliberately omit arguments/action_hash; a
            # persisted fingerprint is conservatively treated as already done.
            was_resumed = saved and fingerprint in old.get("actions", [])
            if previous_ok or was_resumed or state["actions"].count(fingerprint) >= 2:
                error = "This action was already attempted; inspect its result and choose a different next step."
        if error:
            result = ToolResult(False, False, error)
            emit("policy_blocked", tool=tool, summary=error)
        else:
            state["actions"].append(fingerprint)
            try:
                _persist(memory, state)
            except Exception:
                return finish("unverified", "The action checkpoint could not be saved; the tool was not run.", reason="memory_error")
            emit("tool_started", tool=tool)
            try:
                result = _tool_result(execute(tool, deepcopy(arguments), deepcopy(context)))
            except Exception as exc:
                result = ToolResult(False, False, "The tool failed (" + type(exc).__name__ + ").")

        executed = not bool(error) and result.data.get("executed") is not False
        if not executed and not error and fingerprint in state["actions"]:
            # The trusted adapter explicitly confirms there were no effects
            # (e.g. it asked for authorization before starting). A later answer
            # may retry this proposal through the runtime's policy afresh.
            state["actions"].remove(fingerprint)
        record = {"step": state["attempts"], "tool": tool, "ok": result.ok,
                  "verified": result.verified, "summary": result.summary,
                  "evidence": deepcopy(result.evidence), "action_hash": fingerprint, "executed": executed,
                  "goal_satisfied": bool(executed and result.ok and result.verified and result.data.get("goal_satisfied") is True)}
        state["steps"].append(record)
        live_results.append({**deepcopy(record), "data": deepcopy(result.data)})
        state["elapsed_seconds"] = elapsed()
        try:
            if memory is not None:
                memory.record_tool_result(task_id, tool, result.ok, summary=result.summary,
                                          evidence=result.evidence, verified=result.verified)
            _persist(memory, state)
        except Exception:
            return finish("unverified", "A tool ran but its checkpoint could not be saved.", reason="memory_error")
        emit("tool_result", result=deepcopy(live_results[-1]))
        if result.question:
            state["pending_tool"] = deepcopy(result.data.get("pending_tool") or {
                "tool": tool, "arguments": arguments, "question_key": "",
            })
            return finish("waiting", result.summary, question=result.question, reason="tool_question")
        state["pending_tool"] = None
        failures = 0 if result.ok and result.verified else failures + 1
        if failures >= MAX_CONSECUTIVE_FAILURES:
            return finish("failed", "Repeated tool failures prevented completion. Review the recorded results.", reason="repeated_failure")
    return finish("unverified" if state["steps"] else "failed", "The task reached its step limit.", reason="step_limit")
