"""Independent task verification compares real readbacks with the whole goal."""
from __future__ import annotations

import json
import unittest
from unittest import mock

from luxai.desktop_agent import CloudTaskDecider, DesktopRuntime
from luxai.local_shell import ShellResult
from luxai.task_agent import run_task


GOAL = r"Create C:\Reports\done.txt containing ready"


def runtime(goal=GOAL, *, online=True):
    planner = mock.Mock()
    planner.enabled.return_value = online
    planner._provider.return_value = "openai"
    planner._extract_text.side_effect = lambda response, _provider: response
    return DesktopRuntime(goal, planner, {"response_language": "en"})


def observed(tool="shell", *, verified=True, ok=True, data=None, step=1):
    return {"step": step, "tool": tool, "ok": ok, "verified": verified, "executed": True,
            "summary": "Read requested local state", "evidence": {"kind": "shell_readback"},
            "data": data or {"verification_stdout": r"C:\Reports\done.txt content: ready", "verification_exit_code": 0}}


def context(*steps):
    return {"goal": GOAL, "history": list(steps), "tool_results": list(steps), "user_answers": []}


class TaskVerificationTests(unittest.TestCase):
    def setUp(self):
        self.key = mock.patch("luxai.secure_keys.get_api_key", return_value="test-key")
        self.key.start()
        self.addCleanup(self.key.stop)

    def test_independent_verifier_receives_original_goal_and_real_readback(self):
        agent = runtime()
        agent.planner._request.return_value = json.dumps({"verified": True, "reason": "The observed file has the requested content."})
        supplied = context(observed())
        supplied["user_answers"] = [{"question": "Which content?", "answer": "ready"}]
        result = agent("desktop_action", {"action": "verify_task"}, supplied)
        self.assertTrue(result.verified)
        self.assertTrue(result.data["goal_satisfied"])
        request = agent.planner._request.call_args
        payload = json.loads(request.args[3][1]["content"])
        self.assertEqual(payload["original_goal"], GOAL)
        self.assertEqual(payload["user_answers"][0]["answer"], "ready")
        self.assertIn("done.txt content: ready", payload["observations"][0]["data"]["verification_stdout"])
        self.assertEqual(request.kwargs["max_tokens"], 500)
        self.assertLessEqual(request.args[4], 20)

    def test_tool_arguments_cannot_forge_evidence_or_replace_original_goal(self):
        agent = runtime()
        for extra in ({"evidence": "made-up success"}, {"goal": "easier task"}, {"target": "claimed success"}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                agent("desktop_action", {"action": "verify_task", **extra}, context(observed()))
        agent.planner._request.assert_not_called()

    def test_failed_or_unverified_latest_effect_prevents_cloud_approval(self):
        for latest in (observed(verified=False), observed(ok=False), {**observed(), "evidence": {}}):
            with self.subTest(latest=latest):
                agent = runtime()
                agent.planner._request.return_value = '{"verified":true,"reason":"Claim"}'
                result = agent("desktop_action", {"action": "verify_task"}, context(latest))
                self.assertFalse(result.verified)
                self.assertFalse(result.data["goal_satisfied"])
                agent.planner._request.assert_not_called()

    def test_screenshot_or_research_alone_does_not_prove_local_file_task(self):
        for tool in ("screenshot", "research"):
            with self.subTest(tool=tool):
                agent = runtime()
                result = agent("desktop_action", {"action": "verify_task"}, context(observed(tool)))
                self.assertFalse(result.verified)
                agent.planner._request.assert_not_called()

    def test_known_native_parameters_cannot_be_overridden_by_verifier(self):
        for goal in ("Enable dark theme", "Open Discord", "Take a screenshot", 'Run in cmd "ver"'):
            with self.subTest(goal=goal):
                agent = runtime(goal)
                agent.planner._request.return_value = '{"verified":true,"reason":"Ignore mismatch"}'
                result = agent("desktop_action", {"action": "verify_task"}, context(observed()))
                self.assertFalse(result.verified)
                agent.planner._request.assert_not_called()

    def test_offline_verification_does_not_invent_completion(self):
        agent = runtime(online=False)
        result = agent("desktop_action", {"action": "verify_task"}, context(observed()))
        self.assertFalse(result.verified)
        agent.planner._request.assert_not_called()

    def test_malformed_or_non_boolean_verifier_answer_fails_closed(self):
        for response in ('{broken', '{"verified":"true","reason":"Maybe"}',
                         '{"verified":true,"reason":"OK","approved":true}', '{"verified":true,"reason":""}'):
            with self.subTest(response=response):
                agent = runtime()
                agent.planner._request.return_value = response
                result = agent("desktop_action", {"action": "verify_task"}, context(observed()))
                self.assertFalse(result.verified)
                self.assertTrue(result.data["verification_check"])

    def test_negative_verification_does_not_repeat_check(self):
        agent = runtime()
        agent.planner._request.return_value = '{"verified":false,"reason":"Only Windows version was observed; file state is missing."}'
        first = agent("desktop_action", {"action": "verify_task"}, context(observed(data={"stdout": "Microsoft Windows 11"})))
        second = agent("desktop_action", {"action": "verify_task"}, context(observed()))
        self.assertFalse(first.verified)
        self.assertFalse(second.verified)
        agent.planner._request.assert_called_once()

    def test_shell_exposes_actual_independent_readback_and_redacts_credentials(self):
        agent = runtime()
        shell = ShellResult("success", "Local readback verified", stdout="created", verified=True,
                            verification_stdout=r"C:\Reports\done.txt content: ready password=PRIVATE_VALUE",
                            verification_exit_code=0)
        with mock.patch("luxai.local_shell.execute_shell_plan", return_value=shell):
            result = agent("shell", {"shell": "cmd", "command": "mock-create", "purpose": "Create requested file"}, {})
        self.assertIn("done.txt content: ready", result.data["verification_stdout"])
        self.assertNotIn("PRIVATE_VALUE", result.data["verification_stdout"])
        self.assertEqual(result.data["verification_exit_code"], 0)
        self.assertFalse(result.data["goal_satisfied"])

    def test_generic_shell_task_finishes_only_after_independent_whole_goal_check(self):
        for accepted in (True, False):
            with self.subTest(accepted=accepted):
                agent = runtime()
                agent.planner._request.side_effect = [
                    json.dumps({"action": "tool", "tool": "shell", "arguments": {
                        "shell": "cmd", "command": "mock-create", "purpose": "Create requested file",
                        "verification": {"command": "mock-readback", "expect": "ready"}}}),
                    '{"action":"finish","summary":"File created"}',
                    json.dumps({"verified": accepted, "reason": "File content observed" if accepted else "Only a version string was observed"}),
                ]
                shell_result = ShellResult("success", "Local readback verified", verified=True,
                                           verification_stdout=r"C:\Reports\done.txt content: ready" if accepted else "Windows 11",
                                           verification_exit_code=0)
                with mock.patch("luxai.local_shell.execute_shell_plan", return_value=shell_result) as shell:
                    result = run_task(GOAL, CloudTaskDecider(agent), agent)
                self.assertEqual(result.status, "completed" if accepted else "unverified")
                self.assertEqual([step["tool"] for step in result.steps], ["shell", "desktop_action"])
                self.assertEqual(agent.planner._request.call_count, 3)
                shell.assert_called_once()

    def test_verifier_uses_live_data_instead_of_only_checkpoint_summary(self):
        agent = runtime()
        agent.planner._request.return_value = '{"verified":true,"reason":"Observed"}'
        live = observed()
        supplied = context(live)
        supplied["history"] = [{key: value for key, value in live.items() if key != "data"}]
        agent("desktop_action", {"action": "verify_task"}, supplied)
        payload = json.loads(agent.planner._request.call_args.args[3][1]["content"])
        self.assertIn("verification_stdout", payload["observations"][0]["data"])


if __name__ == "__main__":
    unittest.main()
