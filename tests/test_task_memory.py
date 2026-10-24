"""Durable bounded task history without recordings, secrets or saved permission."""
import concurrent.futures
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from luxai.task_memory import MemoryFormatError, TaskMemory, normalize_goal, redact_text


class TaskMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "data" / "agent_memory.json"
        self.memory = TaskMemory(self.path)

    def success(self, goal="Open Telegram", *, app="telegram"):
        task = self.memory.create_task(goal)
        self.memory.set_state(task, "running")
        self.memory.record_tool_result(task, "open_app", True, "Window opened", verified=True,
                                       evidence={"kind": "window_observation", "summary": "Requested window is visible"})
        self.memory.set_state(task, "succeeded", "Window verified", verified=True)
        procedure = self.memory.save_procedure(task, [{"tool": "open_app", "arguments": {"name": app}}],
                                               {"kind": "window_observation", "summary": "Requested app visible"}, approved=True)
        return task, procedure

    def test_atomic_reopen_preserves_ordered_results_and_verified_procedure(self):
        task, procedure = self.success()
        reopened = TaskMemory(self.path)
        history = reopened.get_task(task)
        self.assertEqual(history["state"], "succeeded")
        self.assertTrue(history["verified"])
        self.assertEqual([item["sequence"] for item in history["events"]], [1, 2, 3])
        self.assertEqual([item["kind"] for item in history["events"]], ["state", "tool_result", "state"])
        result = reopened.lookup("  OPEN telegram!!! ")
        self.assertEqual(result["status"], "match")
        self.assertEqual(result["procedure"]["id"], procedure)
        self.assertTrue(result["requires_fresh_observation"])
        self.assertNotIn("approved", result["procedure"])
        self.assertNotIn("permissions", result["procedure"])

    def test_success_requires_actual_verified_tool_evidence(self):
        task = self.memory.create_task("Do something")
        with self.assertRaises(ValueError):
            self.memory.set_state(task, "succeeded", verified=True)
        with self.assertRaises(ValueError):
            self.memory.record_tool_result(task, "open_app", True, "Looks good", verified=True)
        self.memory.record_tool_result(task, "open_app", True, "Process started", verified=False)
        with self.assertRaises(ValueError):
            self.memory.set_state(task, "succeeded", verified=True)
        with self.assertRaises(ValueError):
            self.memory.record_tool_result(task, "open_app", False, evidence={"kind": "observation"}, verified=True)
        self.memory.set_state(task, "unverified", "Process started, window not observed")
        self.assertFalse(self.memory.get_task(task)["verified"])
        self.assertEqual(self.memory.lookup("Do something")["status"], "none")

    def test_failed_cancelled_unverified_tasks_cannot_teach_or_restart(self):
        for state in ("failed", "cancelled", "unverified"):
            with self.subTest(state=state):
                task = self.memory.create_task("Same goal " + state)
                self.memory.set_state(task, state)
                with self.assertRaises(ValueError):
                    self.memory.save_procedure(task, [{"tool": "open_app", "arguments": {"name": "telegram"}}],
                                               {"kind": "observation"}, approved=True)
                self.assertEqual(self.memory.lookup("Same goal " + state)["status"], "none")
                if state != "unverified":
                    with self.assertRaises(ValueError):
                        self.memory.set_state(task, "running")

    def test_procedures_need_task_approval_and_only_completed_tools(self):
        task, _ = self.success()
        with self.assertRaises(ValueError):
            self.memory.save_procedure(task, [{"tool": "open_app", "arguments": {"name": "telegram"}}],
                                       {"kind": "observation"})
        with self.assertRaises(ValueError):
            self.memory.save_procedure(task, [{"tool": "research", "arguments": {"query": "unperformed"}}],
                                       {"kind": "observation"}, approved=True)
        with self.assertRaises(ValueError):
            self.memory.save_procedure(task, [{"tool": "invented_tool", "arguments": {}}],
                                       {"kind": "observation"}, approved=True)

    def test_exact_match_preserves_distinct_numbers_and_no_fuzzy_silent_guess(self):
        self.success("Open report 2025", app="notepad")
        self.assertEqual(self.memory.lookup("Open report 2026")["status"], "none")
        self.assertEqual(self.memory.lookup("Open report")["status"], "none")
        self.assertNotEqual(normalize_goal("Caută două fișiere"), normalize_goal("Caută trei fișiere"))

    def test_desktop_procedure_preserves_direction_and_bounded_delay_without_authority(self):
        for enabled, delay in ((True, 30), (False, 300)):
            with self.subTest(enabled=enabled, delay=delay):
                goal = "Set theme " + str(enabled)
                task = self.memory.create_task(goal)
                self.memory.record_tool_result(task, "desktop_action", True, "Theme observed", verified=True,
                                               evidence={"kind": "native_readback"})
                self.memory.set_state(task, "succeeded", "Theme verified", verified=True)
                self.memory.save_procedure(task, [{"tool": "desktop_action", "arguments": {
                    "action": "set_dark_theme", "enabled": enabled, "delay_seconds": delay,
                    "approved": True, "permissions": {"shell": True},
                }}], {"kind": "native_readback"}, approved=True)
                hint = TaskMemory(self.path).lookup(goal)
                self.assertEqual(hint["procedure"]["steps"][0]["arguments"], {
                    "action": "set_dark_theme", "enabled": enabled, "delay_seconds": delay,
                })
                self.assertTrue(hint["requires_fresh_observation"])
                self.assertNotIn("approved", hint["procedure"])

    def test_invalid_typed_desktop_parameters_cannot_become_saved_hints(self):
        task = self.memory.create_task("Change the theme")
        self.memory.record_tool_result(task, "desktop_action", True, verified=True,
                                       evidence={"kind": "native_readback"})
        self.memory.set_state(task, "succeeded", verified=True)
        for values in ({"enabled": "false"}, {"enabled": 1}, {"delay_seconds": True},
                       {"delay_seconds": 29}, {"delay_seconds": 301}, {"delay_seconds": 30.5}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.memory.save_procedure(task, [{"tool": "desktop_action", "arguments": {
                    "action": "set_dark_theme", **values,
                }}], {"kind": "native_readback"}, approved=True)
        self.assertEqual(self.memory.lookup("Change the theme")["status"], "none")

    def test_pending_native_task_retains_typed_parameters_for_fresh_policy_check(self):
        task = self.memory.create_task("Enable dark theme")
        self.memory.save_checkpoint(task, steps=[], user_answers=[], status="waiting",
                                    pending_question="Use dark theme?", pending_tool={
                                        "tool": "desktop_action", "arguments": {
                                            "action": "set_dark_theme", "enabled": False, "delay_seconds": 60,
                                            "approved": True,
                                        }, "question_key": "theme",
                                    })
        pending = TaskMemory(self.path).get_task(task)["checkpoint"]["pending_tool"]
        self.assertEqual(pending["arguments"], {"action": "set_dark_theme", "enabled": False,
                                                "delay_seconds": 60})
        self.assertTrue(pending["requires_fresh_policy_check"])

    def test_conflicting_successful_procedures_ask_instead_of_selecting_target(self):
        self.success("Open my chat", app="telegram")
        self.success("Open my chat", app="discord")
        result = self.memory.lookup("open MY chat")
        self.assertEqual(result["status"], "ambiguous")
        self.assertIsNone(result["procedure"])
        self.assertTrue(result["question"])
        self.assertEqual(len(result["candidates"]), 2)

    def test_repeated_identical_verified_procedure_updates_one_hint(self):
        _, first = self.success()
        _, second = self.success()
        self.assertEqual(first, second)
        result = self.memory.lookup("Open Telegram")
        self.assertEqual(result["status"], "match")
        self.assertEqual(result["procedure"]["success_count"], 2)

    def test_feedback_scope_and_answers_survive_only_with_original_task(self):
        first = self.memory.create_task("Send a message")
        self.memory.set_state(first, "waiting", "Which contact?")
        self.memory.record_feedback(first, "Alex", question="Which contact?")
        self.memory.save_checkpoint(first, steps=[], user_answers=[{"question": "Which contact?", "answer": "Alex"}],
                                    pending_question="Which text?", status="waiting")
        reopened = TaskMemory(self.path)
        waiting = reopened.latest_waiting_task()
        self.assertEqual(waiting["id"], first)
        self.assertEqual(waiting["last_feedback"]["scope_task_id"], first)
        self.assertEqual(waiting["checkpoint"]["user_answers"][0]["scope_task_id"], first)
        second = reopened.create_task("Send a message")
        self.assertIsNone(reopened.get_task(second)["last_feedback"])
        self.assertNotIn("Alex", json.dumps(reopened.lookup("Send a message")))
        self.assertIsNone(reopened.get_task("missing-task"))

    def test_checkpoint_preserves_resume_budget_and_executed_fingerprint_guard(self):
        task = self.memory.create_task("Open Discord and find Alex")
        self.memory.save_checkpoint(task, steps=[{
            "step": 1, "tool": "open_app", "ok": True, "executed": True, "verified": True,
            "summary": "Discord visible", "evidence": {"kind": "window_observation"},
            "data": {"screenshot": "PRIVATE_SCREEN_CONTENT"},
        }, {
            "step": 2, "tool": "shell", "ok": False, "executed": False, "summary": "Needs confirmation",
        }], user_answers=[{"question": "Which person?", "answer": "Alex"}],
            pending_question="Allow this shell task?", status="waiting", actions=["a" * 64, "not-a-fingerprint"],
            attempts=3, elapsed_seconds=42.5,
            pending_tool={"tool": "shell", "arguments": {"purpose": "Inspect window", "command": "DO_NOT_STORE_RAW_COMMAND",
                                                             "api_key": "DO_NOT_STORE_API_KEY"}, "question_key": "shell_confirmation"})
        checkpoint = TaskMemory(self.path).get_task(task)["checkpoint"]
        self.assertEqual(checkpoint["attempts"], 3)
        self.assertEqual(checkpoint["elapsed_seconds"], 42.5)
        self.assertEqual(checkpoint["actions"], ["a" * 64])
        self.assertTrue(checkpoint["steps"][0]["executed"])
        self.assertFalse(checkpoint["steps"][1]["executed"])
        self.assertTrue(checkpoint["pending_tool"]["requires_fresh_policy_check"])
        self.assertEqual(checkpoint["pending_tool"]["arguments"], {"purpose": "Inspect window"})
        stored = self.path.read_text(encoding="utf-8")
        for private in ("DO_NOT_STORE_RAW_COMMAND", "DO_NOT_STORE_API_KEY", "PRIVATE_SCREEN_CONTENT"):
            self.assertNotIn(private, stored)

    def test_shell_review_question_persists_only_a_fresh_policy_reminder(self):
        task = self.memory.create_task("Create the requested report")
        command = "New-Item -Path C:\\PrivateReportFolder -ItemType Directory"
        self.memory.save_checkpoint(task, steps=[], user_answers=[], status="waiting",
                                    pending_question="Allow powershell: " + command + "?", pending_tool={
                                        "tool": "shell", "arguments": {
                                            "command": command, "purpose": "Create requested report folder",
                                        }, "question_key": "shell",
                                    })
        restored = TaskMemory(self.path).get_task(task)["checkpoint"]
        self.assertNotIn(command, self.path.read_text(encoding="utf-8"))
        self.assertNotIn("PrivateReportFolder", restored["pending_question"])
        self.assertIn("fresh command proposal", restored["pending_question"])
        self.assertIn("current execution policy", restored["pending_question"])
        self.assertTrue(restored["pending_tool"]["requires_fresh_policy_check"])

    def test_resuming_shell_question_does_not_copy_raw_command_into_feedback(self):
        from luxai.task_agent import ToolResult, run_task
        command = "New-Item -Path C:\\PrivateReportFolder -ItemType Directory"
        proposal = {"action": "tool", "tool": "shell", "arguments": {
            "shell": "powershell", "command": command, "purpose": "Create requested folder",
        }}
        first = run_task("Create the requested folder", lambda _: proposal,
                         lambda *_: ToolResult(False, False, "Needs command authorization",
                                               data={"executed": False}, question="Run: " + command + "?"),
                         memory=self.memory)
        self.assertIn(command, first.question)  # The active UI still shows what would run.
        run_task("Create the requested folder", lambda _: {"action": "ask", "question": "Which folder name?"},
                 mock.Mock(side_effect=AssertionError("No command replay")), memory=TaskMemory(self.path),
                 task_id=first.task_id, clarification="yes")
        saved = self.memory.get_task(first.task_id)
        self.assertIn("fresh command proposal", saved["last_feedback"]["question"])
        stored = self.path.read_text(encoding="utf-8")
        self.assertNotIn(command, stored)
        self.assertNotIn("PrivateReportFolder", stored)

    def test_secret_media_binary_fields_are_never_automatically_persisted(self):
        key = "sk-proj-this_is_a_private_credential_123456789"
        task = self.memory.create_task('Open app with api_key="private key words"')
        self.memory.record_feedback(task, "password='private password words' " + key)
        self.memory.record_tool_result(task, "shell", True, "password=one-secret", verified=True,
                                       evidence={"kind": "observation", "summary": "data:image/png;base64," + "a" * 120,
                                                 "screenshot": "BINARY_PRIVATE_DATA", "audio": b"PRIVATE_AUDIO",
                                                 "api_key": key, "stdout": "RAW_STDOUT_PRIVATE"})
        self.memory.set_state(task, "succeeded", verified=True)
        self.memory.save_procedure(task, [{"tool": "shell", "arguments": {
            "purpose": "Inspect local state", "executable_class": "powershell", "command": "RAW_COMMAND_PRIVATE",
            "environment": {"API_KEY": key}, "screenshot_path": "private-screen.png",
        }}], {"kind": "observation", "summary": "Local state checked"}, approved=True)
        stored = self.path.read_text(encoding="utf-8")
        for private in (key, "private key words", "private password words", "one-secret", "BINARY_PRIVATE_DATA",
                        "PRIVATE_AUDIO", "RAW_STDOUT_PRIVATE", "RAW_COMMAND_PRIVATE", "private-screen.png", "a" * 120):
            self.assertNotIn(private, stored)
        self.assertIn("[redacted]", stored)
        self.assertEqual(self.memory.lookup('Open app with api_key="private key words"')["status"], "ambiguous")

    def test_task_event_procedure_and_text_bounds_are_enforced(self):
        memory = TaskMemory(self.path, max_tasks=2, max_events=3, max_procedures=1)
        oldest = memory.create_task("Old task")
        current = memory.create_task("Current task")
        for number in range(10):
            memory.record_feedback(current, "feedback " + str(number) + "x" * 2000)
        history = memory.get_task(current)
        self.assertEqual(len(history["events"]), 3)
        self.assertEqual([entry["sequence"] for entry in history["events"]], [8, 9, 10])
        self.assertLessEqual(len(history["last_feedback"]["answer"]), 800)
        memory.create_task("Latest task")
        self.assertIsNone(memory.get_task(oldest))
        self.assertEqual(len(memory.list_tasks()), 2)
        self.memory = memory
        self.success("First reusable task")
        self.success("Second reusable task", app="discord")
        self.assertEqual(memory.lookup("First reusable task")["status"], "none")
        self.assertEqual(memory.lookup("Second reusable task")["status"], "match")

    def test_atomic_write_failure_preserves_previous_file_and_removes_temporary(self):
        task = self.memory.create_task("Existing goal")
        before = self.path.read_bytes()
        with mock.patch("luxai.task_memory.os.replace", side_effect=OSError("Disk full")):
            with self.assertRaises(OSError):
                self.memory.record_feedback(task, "Not persisted")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_corrupt_or_oversized_memory_is_not_silently_overwritten(self):
        self.path.parent.mkdir(parents=True)
        for content in (b"{broken-json", b"{}", b"x" * 100):
            self.path.write_bytes(content)
            patches = {"MAX_FILE_BYTES": 64} if len(content) == 100 else {}
            with mock.patch.multiple("luxai.task_memory", **patches) if patches else nullcontext():
                with self.assertRaises(MemoryFormatError):
                    self.memory.create_task("New task")
            self.assertEqual(self.path.read_bytes(), content)

    def test_instances_and_threads_do_not_lose_concurrent_results(self):
        first = TaskMemory(self.path, max_events=200)
        second = TaskMemory(self.path, max_events=200)
        task = first.create_task("Concurrent background task")
        def update(number):
            memory = first if number % 2 else second
            memory.record_feedback(task, "Result " + str(number))
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(update, range(40)))
        history = first.get_task(task)
        self.assertEqual(len(history["events"]), 40)
        self.assertEqual([entry["sequence"] for entry in history["events"]], list(range(1, 41)))
        self.assertEqual(len({entry["answer"] for entry in history["events"]}), 40)

    def test_read_revalidates_external_edits_and_returns_copies(self):
        task, _ = self.success()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["procedures"][0]["steps"][0]["arguments"]["api_key"] = "EXTERNAL_SECRET"
        data["procedures"][0]["permissions"] = {"shell": True}
        self.path.write_text(json.dumps(data), encoding="utf-8")
        result = self.memory.lookup("Open Telegram")
        self.assertNotIn("EXTERNAL_SECRET", json.dumps(result))
        self.assertNotIn("permissions", result["procedure"])
        result["procedure"]["steps"][0]["arguments"]["name"] = "evil"
        self.assertEqual(self.memory.lookup("Open Telegram")["procedure"]["steps"][0]["arguments"]["name"], "telegram")
        self.memory.record_feedback(task, "Still safe")
        self.assertNotIn("EXTERNAL_SECRET", self.path.read_text(encoding="utf-8"))

    def test_long_goal_roundtrip_and_oversize_rejection_preserve_resume_identity(self):
        goal = ("Open the requested application " + "and verify the exact window title " * 40).strip()
        self.assertGreater(len(goal), 400)
        task = self.memory.create_task(goal)
        self.assertEqual(TaskMemory(self.path).get_task(task)["goal"], goal)
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.memory.create_task("x" * 2001)
        self.assertEqual(self.path.read_bytes(), before)

    def test_checkpoint_goal_proof_requires_executed_verified_success(self):
        task = self.memory.create_task("Verify the final task goal")
        steps = []
        for index, overrides in enumerate(({}, {"executed": False}, {"ok": False}, {"evidence": {}})):
            steps.append({"step": index + 1, "tool": "screenshot", "executed": True, "ok": True,
                          "verified": True, "goal_satisfied": True,
                          "evidence": {"kind": "whole_goal_observation"}, **overrides})
        self.memory.save_checkpoint(task, steps=steps, user_answers=[], status="waiting")
        restored = TaskMemory(self.path).get_task(task)["checkpoint"]["steps"]
        self.assertEqual([step["goal_satisfied"] for step in restored], [True, False, False, False])

    def test_public_redaction_handles_environment_labels_and_json_secrets(self):
        text = ('OPENAI_API_KEY="private API key words"; AZURE_CLIENT_SECRET=private-azure-value; '
                'GITHUB_TOKEN=private-github-value; {"password": "private password phrase"}')
        redacted = redact_text(text, limit=2000)
        for secret in ("private API key words", "private-azure-value", "private-github-value", "private password phrase"):
            self.assertNotIn(secret, redacted)
        self.assertEqual(redact_text(b"private binary"), "")
        self.assertEqual(len(redact_text("test " * 1000, limit=20)), 20)

    def test_omitted_media_target_never_becomes_an_ambiguous_silent_match(self):
        self.success("Inspect private-capture.png", app="notepad")
        result = self.memory.lookup("Inspect another-capture.png")
        self.assertEqual(result["status"], "ambiguous")
        self.assertIsNone(result["procedure"])
        self.assertTrue(result["question"])

    def test_size_budget_evicts_old_history_without_losing_current_task(self):
        first = self.memory.create_task("Old task " + "old word " * 80)
        goal = ("New task " + "new word " * 80).strip()
        with mock.patch("luxai.task_memory.MAX_FILE_BYTES", 3000):
            latest = self.memory.create_task(goal)
            self.assertLessEqual(self.path.stat().st_size, 3000)
            self.assertEqual(self.memory.get_task(latest)["goal"], goal)
            self.assertIsNone(self.memory.get_task(first))


if __name__ == "__main__":
    unittest.main()
