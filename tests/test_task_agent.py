"""Task decisions must follow real outcomes, including partial work and resumes."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from luxai.task_agent import ToolResult, run_task
from luxai.task_memory import TaskMemory


def tool(name, **arguments):
    return {"action": "tool", "tool": name, "arguments": arguments}


def verified(summary="Observed expected state", **data):
    return ToolResult(True, True, summary, {"kind": "observation", "summary": summary}, data)


class TaskAgentTests(unittest.TestCase):
    def test_tool_manifest_advertises_the_runtime_required_arguments(self):
        contexts = []

        def decide(context):
            contexts.append(context)
            return {"action": "ask", "question": "Which task?"}

        run_task("Inspect this task", decide, mock.Mock())
        manifest = {item["name"]: item for item in contexts[0]["tools"]}
        self.assertEqual(set(manifest["shell"]["arguments"]),
                         {"shell", "command", "purpose", "verification"})
        self.assertEqual(set(manifest["shell"]["arguments"]["verification"]),
                         {"shell", "command", "expect"})
        self.assertIn("scope", manifest["screenshot"]["optional_arguments"])
        self.assertIn("enabled", manifest["desktop_action"]["optional_arguments"])
        self.assertIn("delay_seconds", manifest["desktop_action"]["optional_arguments"])

    def test_cancellation_after_issued_action_stops_before_next_decision(self):
        cancelled = [False]
        decide = mock.Mock(return_value=tool("research", query="information"))

        def execute(*_):
            cancelled[0] = True
            return verified("Information observed", goal_satisfied=True)

        execute.runtime_facts = {"requires_goal_evidence": True}
        result = run_task("Research information", decide, execute, cancelled=lambda: cancelled[0])
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(decide.call_count, 1)
        self.assertEqual(len(result.steps), 1)

    def test_compound_goal_observes_open_then_performs_remaining_work(self):
        contexts, calls = [], []
        decisions = iter([tool("open_app", target="Calculator"),
                          tool("visual_task", goal="Click 3"), {"action": "finish", "summary": "3 is visible."}])

        def decide(context):
            contexts.append(context)
            return next(decisions)

        def execute(name, arguments, context):
            calls.append((name, arguments))
            return verified("Calculator window visible" if name == "open_app" else "3 visible")

        result = run_task("Open Calculator and click 3", decide, execute)
        self.assertEqual(result.status, "completed")
        self.assertEqual([name for name, _ in calls], ["open_app", "visual_task"])
        self.assertEqual(contexts[1]["history"][0]["summary"], "Calculator window visible")
        self.assertEqual(contexts[2]["tool_results"][-1]["summary"], "3 visible")

    def test_plain_finish_claim_has_no_execution_evidence(self):
        execute = mock.Mock()
        result = run_task("Open Calculator", lambda _: {"action": "finish", "summary": "Opened"}, execute)
        self.assertEqual(result.status, "unverified")
        self.assertEqual(result.reason, "unverified_finish")
        execute.assert_not_called()

    def test_partial_open_does_not_complete_visual_goal(self):
        decisions = iter([tool("open_app", target="Calculator"), {"action": "finish", "summary": "All done"}])
        result = run_task("Open Calculator and click 3", lambda _: next(decisions), lambda *_: verified())
        self.assertEqual(result.status, "unverified")

    def test_tool_cannot_claim_verification_without_evidence(self):
        decisions = iter([tool("research", query="test"), {"action": "finish", "summary": "Done"}])
        result = run_task("Research this", lambda _: next(decisions), lambda *_: ToolResult(True, True, "Done"))
        self.assertEqual(result.status, "unverified")
        self.assertFalse(result.steps[0]["verified"])

    def test_failed_tool_result_is_seen_and_different_recovery_is_allowed(self):
        contexts = []
        decisions = iter([tool("open_app", target="Calculator"), tool("screenshot", reason="Native open failed"),
                          tool("visual_task", goal="Open Calculator from Start"),
                          {"action": "finish", "summary": "Calculator visible"}])

        def decide(context):
            contexts.append(context)
            return next(decisions)

        def execute(name, *_):
            return ToolResult(False, False, "No native match") if name == "open_app" else verified()

        result = run_task("Open Calculator", decide, execute)
        self.assertTrue(result.ok)
        self.assertFalse(contexts[1]["history"][0]["ok"])
        self.assertEqual([step["tool"] for step in result.steps], ["open_app", "screenshot", "visual_task"])

    def test_native_open_precedes_even_explicit_visual_work(self):
        decisions = iter([tool("screenshot", reason="Need screen"), tool("visual_task", goal="Click 3"),
                          tool("open_app", target="Calculator"), tool("visual_task", goal="Click 3"),
                          {"action": "finish", "summary": "3 visible"}])
        calls = []

        def execute(name, *_):
            calls.append(name)
            return verified()

        result = run_task("Open Calculator and click 3", lambda _: next(decisions), execute)
        self.assertTrue(result.ok)
        self.assertEqual(calls, ["open_app", "visual_task"])
        self.assertFalse(result.steps[0]["executed"])
        self.assertFalse(result.steps[1]["executed"])

    def test_plain_native_open_cannot_trigger_unnecessary_screenshot(self):
        decisions = iter([tool("open_app", target="Calculator"), tool("screenshot", reason="I want a screenshot"),
                          {"action": "finish", "summary": "Done"}])
        execute = mock.Mock(return_value=verified())
        result = run_task("Open Calculator", lambda _: next(decisions), execute)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(result.status, "unverified")

    def test_verified_screenshot_is_observation_not_task_completion(self):
        decisions = iter([tool("screenshot", reason="Inspect screen"), {"action": "finish", "summary": "Done"}])
        result = run_task("Click a button on screen", lambda _: next(decisions), lambda *_: verified())
        self.assertEqual(result.status, "unverified")

    def test_repeat_failed_action_has_one_retry_then_stops(self):
        execute = mock.Mock(return_value=ToolResult(False, False, "Unavailable"))
        result = run_task("Research this", lambda _: tool("research", query="same"), execute)
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "repeated_failure")

    def test_repeat_successful_action_is_not_reexecuted(self):
        execute = mock.Mock(return_value=verified())
        result = run_task("Research this", lambda _: tool("research", query="same"), execute)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(result.status, "failed")

    def test_failed_final_tool_prevents_false_finish_after_prior_success(self):
        decisions = iter([tool("research", query="facts"), tool("shell", command="write report"),
                          {"action": "finish", "summary": "Report saved"}])
        results = iter([verified(), ToolResult(False, False, "Write failed")])
        result = run_task("Research and save a report", lambda _: next(decisions), lambda *_: next(results))
        self.assertEqual(result.status, "unverified")

    def test_waiting_resume_keeps_prior_work_and_scopes_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = TaskMemory(Path(directory) / "tasks.json")
            decisions = iter([tool("research", query="facts"), {"action": "ask", "question": "Which report name?"}])
            execute = mock.Mock(return_value=verified("Facts observed", screenshot="do not persist"))
            first = run_task("Research and save report", lambda _: next(decisions), execute, memory=memory)
            self.assertEqual(first.status, "waiting")
            self.assertNotIn("do not persist", memory.path.read_text())
            no_answer = run_task("Research and save report", mock.Mock(side_effect=AssertionError), execute,
                                 memory=memory, task_id=first.task_id)
            self.assertEqual(no_answer.status, "waiting")
            contexts = []
            decisions = iter([tool("shell", command="write report", purpose="save requested report"),
                              {"action": "finish", "summary": "Report saved"}])

            def decide(context):
                contexts.append(context)
                return next(decisions)

            second = run_task("Research and save report", decide, execute, memory=memory,
                              task_id=first.task_id, clarification="report.txt")
            self.assertEqual(second.status, "completed")
            self.assertEqual(execute.call_count, 2)
            self.assertEqual(contexts[0]["history"][0]["tool"], "research")
            self.assertEqual(contexts[0]["user_answers"][0]["answer"], "report.txt")
            saved = memory.get_task(first.task_id)
            self.assertEqual(saved["state"], "succeeded")
            self.assertEqual(saved["last_feedback"]["scope_task_id"], first.task_id)
            self.assertNotIn("write report", memory.path.read_text())

    def test_tool_question_persists_pending_tool_without_replaying(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = TaskMemory(Path(directory) / "tasks.json")
            first = run_task("Save a report", lambda _: tool("shell", command="write", purpose="save report"),
                             lambda *_: ToolResult(False, False, "Need location", question="Where?",
                                                   data={"pending_tool": {"tool": "shell", "arguments": {"command": "private command", "purpose": "save report"}, "question_key": "path"}}),
                             memory=memory)
            contexts = []

            def decide(context):
                contexts.append(context)
                return {"action": "ask", "question": "Confirm the filename?"}

            run_task("Save a report", decide, mock.Mock(side_effect=AssertionError), memory=memory,
                     task_id=first.task_id, clarification="Documents")
            self.assertEqual(contexts[0]["pending_tool"]["question_key"], "path")
            self.assertNotIn("command", contexts[0]["pending_tool"]["arguments"])

    def test_resume_fingerprint_prevents_replaying_completed_action(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = TaskMemory(Path(directory) / "tasks.json")
            decisions = iter([tool("research", query="same"), {"action": "ask", "question": "Next?"}])
            execute = mock.Mock(return_value=verified())
            first = run_task("Research", lambda _: next(decisions), execute, memory=memory)
            run_task("Research", lambda _: tool("research", query="same"), execute,
                     memory=memory, task_id=first.task_id, clarification="continue")
            self.assertEqual(execute.call_count, 1)

    def test_cancellation_prevents_tool_execution(self):
        execute = mock.Mock()
        result = run_task("Research", lambda _: tool("research", query="test"), execute, cancelled=lambda: True)
        self.assertEqual(result.status, "cancelled")
        execute.assert_not_called()

    def test_decider_time_budget_is_checked_before_tool_execution(self):
        execute = mock.Mock()
        tick = [0]

        def decide(_):
            tick[0] = 301
            return tool("research", query="test")

        with mock.patch("luxai.task_agent.time.monotonic", side_effect=lambda: tick[0]):
            result = run_task("Research", decide, execute)
        self.assertEqual(result.reason, "deadline")
        execute.assert_not_called()

    def test_strict_decision_rejects_unknown_fields_without_execution(self):
        execute = mock.Mock()
        result = run_task("Research", lambda _: {**tool("research", query="test"), "script": "unsafe"}, execute)
        self.assertEqual(result.status, "failed")
        execute.assert_not_called()

    def test_context_mutation_does_not_forge_evidence(self):
        def decide(context):
            context["history"].append({"ok": True, "verified": True, "evidence": "forged"})
            return {"action": "finish", "summary": "Done"}

        result = run_task("Research", decide, mock.Mock())
        self.assertEqual(result.status, "unverified")
        self.assertEqual(result.steps, [])

    def test_runtime_requires_whole_goal_proof_not_just_native_open(self):
        execute = mock.Mock(return_value=verified("Window visible"))
        execute.runtime_facts = {"opening_goal": True, "explicit_visual_need": True,
                                 "requires_goal_evidence": True}
        decisions = iter([tool("open_app", target="Calculator"),
                          {"action": "finish", "summary": "Calculated everything"}])
        result = run_task("Open Calculator and click 3", lambda _: next(decisions), execute)
        self.assertEqual(result.status, "unverified")

    def test_explicit_whole_goal_screenshot_proof_can_complete_capture_goal(self):
        execute = mock.Mock(return_value=verified("Screenshot saved and reopened", goal_satisfied=True))
        execute.runtime_facts = {"opening_goal": False, "explicit_visual_need": True,
                                 "requires_goal_evidence": True}
        decisions = iter([tool("screenshot", reason="Requested capture"),
                          {"action": "finish", "summary": "Screenshot saved"}])
        result = run_task("Take a screenshot", lambda _: next(decisions), execute)
        self.assertTrue(result.ok)

    def test_authorization_question_without_effects_can_resume_same_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = TaskMemory(Path(directory) / "tasks.json")
            execute = mock.Mock(side_effect=[
                ToolResult(False, False, "Awaiting approval", data={"executed": False}, question="Run this command?"),
                verified("Requested report verified", goal_satisfied=True),
            ])
            execute.runtime_facts = {"requires_goal_evidence": True}
            first = run_task("Write report", lambda _: tool("shell", command="write", purpose="report"),
                             execute, memory=memory)
            self.assertEqual(first.status, "waiting")
            self.assertFalse(first.steps[0]["executed"])
            self.assertEqual(memory.get_task(first.task_id)["checkpoint"]["actions"], [])
            decisions = iter([tool("shell", command="write", purpose="report"),
                              {"action": "finish", "summary": "Report saved"}])
            result = run_task("Write report", lambda _: next(decisions), execute, memory=memory,
                              task_id=first.task_id, clarification="yes")
            self.assertTrue(result.ok)
            self.assertEqual(execute.call_count, 2)

    def test_whole_goal_proof_survives_waiting_checkpoint_without_raw_data(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = TaskMemory(Path(directory) / "tasks.json")
            execute = mock.Mock(return_value=verified("Report exists", goal_satisfied=True, screenshot="PRIVATE_RAW_DATA"))
            execute.runtime_facts = {"requires_goal_evidence": True}
            decisions = iter([tool("research", query="report"), {"action": "ask", "question": "Anything else?"}])
            first = run_task("Research report", lambda _: next(decisions), execute, memory=memory)
            checkpoint = memory.get_task(first.task_id)["checkpoint"]
            self.assertTrue(checkpoint["steps"][0]["goal_satisfied"])
            self.assertNotIn("PRIVATE_RAW_DATA", memory.path.read_text())
            result = run_task("Research report", lambda _: {"action": "finish", "summary": "Verified report complete"},
                              execute, memory=memory, task_id=first.task_id, clarification="No")
            self.assertTrue(result.ok)
            self.assertEqual(execute.call_count, 1)

    def test_step_budget_stops_distinct_successful_actions_without_false_completion(self):
        count = [0]

        def decide(_):
            count[0] += 1
            return tool("research", query=str(count[0]))

        with mock.patch("luxai.task_agent.MAX_STEPS", 3):
            result = run_task("Research", decide, lambda *_: verified())
        self.assertEqual(len(result.steps), 3)
        self.assertEqual(result.status, "unverified")
        self.assertEqual(result.reason, "step_limit")

    def test_completed_task_id_does_not_reexecute_on_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = TaskMemory(Path(directory) / "tasks.json")
            decisions = iter([tool("research", query="report"), {"action": "finish", "summary": "Done"}])
            execute = mock.Mock(return_value=verified())
            first = run_task("Research", lambda _: next(decisions), execute, memory=memory)
            result = run_task("Research", mock.Mock(side_effect=AssertionError), execute,
                              memory=memory, task_id=first.task_id)
            self.assertTrue(result.ok)
            self.assertEqual(execute.call_count, 1)

    def test_uncertain_interruption_saves_fingerprint_before_starting_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = TaskMemory(Path(directory) / "tasks.json")
            task_ids = []

            def interrupted(_name, _args, context):
                task_ids.append(context["task_id"])
                saved = memory.get_task(context["task_id"])["checkpoint"]
                self.assertEqual(len(saved["actions"]), 1)
                raise SystemExit("Simulated interrupted process after side effect")

            with self.assertRaises(SystemExit):
                run_task("Research", lambda _: tool("research", query="same"), interrupted, memory=memory)
            execute = mock.Mock(side_effect=AssertionError("Must not replay uncertain action"))
            result = run_task("Research", lambda _: tool("research", query="same"), execute,
                              memory=memory, task_id=task_ids[0])
            self.assertEqual(result.status, "failed")
            execute.assert_not_called()

    def test_successful_native_recovery_closes_screenshot_fallback(self):
        decisions = iter([tool("open_app", target="first name"), tool("open_app", target="resolved name"),
                          tool("screenshot", reason="Historic native failure"),
                          {"action": "finish", "summary": "Done"}])
        execute = mock.Mock(side_effect=[ToolResult(False, False, "Not found"), verified("Window visible")])
        result = run_task("Open Calculator", lambda _: next(decisions), execute)
        self.assertEqual(execute.call_count, 2)
        self.assertFalse(result.steps[-1]["executed"])
        self.assertEqual(result.status, "unverified")

    def test_later_action_cannot_reuse_stale_whole_goal_proof(self):
        decisions = iter([tool("desktop_action", action="set_dark_theme", enabled=True),
                          tool("desktop_action", action="set_dark_theme", enabled=False),
                          {"action": "finish", "summary": "Dark theme enabled"}])
        execute = mock.Mock(side_effect=[verified("Dark theme observed", goal_satisfied=True),
                                         verified("Light theme observed", goal_satisfied=False)])
        execute.runtime_facts = {"requires_goal_evidence": True}
        result = run_task("Enable dark theme", lambda _: next(decisions), execute)
        self.assertEqual(result.status, "unverified")


if __name__ == "__main__":
    unittest.main()
