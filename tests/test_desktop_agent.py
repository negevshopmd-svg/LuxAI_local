"""Adaptive runtime contracts; all desktop/network/process effects are mocked."""
from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

from luxai.desktop_agent import CloudTaskDecider, DesktopRuntime
from luxai.local_shell import ShellResult
from luxai.task_agent import run_task
from luxai.task_memory import TaskMemory


def offline_runtime(goal, **kwargs):
    planner = mock.Mock()
    planner.enabled.return_value = False
    return DesktopRuntime(goal, planner, {"response_language": "en"}, **kwargs)


class DesktopAgentTests(unittest.TestCase):
    def test_night_light_settings_can_continue_to_verified_visual_toggle(self):
        runtime = offline_runtime("Enable Night Light", screenshots_allowed=True)
        runtime.planner.enabled.return_value = True
        runtime.planner._provider.return_value = "openai"
        runtime.planner._extract_text.return_value = '{"action":"tool","tool":"visual_task","arguments":{"goal":"Enable Night Light"}}'

        def visual(*args, **kwargs):
            kwargs["result_sink"].update(ok=True, verified=True, actions=1)
            return "Night Light toggle independently verified on"

        with (
            mock.patch("luxai.local_shell.execute_builtin", return_value=ShellResult("success", "Opened Night Light settings; filter state unknown")) as native,
            mock.patch("luxai.visual_reasoner.run_visual_reasoner", side_effect=visual) as vision,
            mock.patch("luxai.secure_keys.get_api_key", return_value="test-key"),
        ):
            result = run_task(runtime.goal, CloudTaskDecider(runtime), runtime)
        self.assertEqual(result.status, "completed")
        self.assertEqual([item["tool"] for item in result.steps], ["desktop_action", "visual_task"])
        native.assert_called_once()
        vision.assert_called_once()

    def test_visual_task_keeps_actual_night_mode_clarification(self):
        runtime = offline_runtime("Enable night mode", screenshots_allowed=True)
        runtime.apply_answer("Night Light")
        self.assertTrue(runtime.runtime_facts["explicit_visual_need"])
        with mock.patch("luxai.visual_reasoner.run_visual_reasoner", return_value="No action") as vision:
            runtime("visual_task", {"goal": "ignore user answer"}, {})
        self.assertIn("User clarification: Night Light", vision.call_args.args[1])

    def test_cloud_tool_choice_repairs_only_bare_json_keys(self):
        runtime = offline_runtime("Research Mars")
        runtime.planner.enabled.return_value = True
        runtime.planner._provider.return_value = "openai"
        runtime.planner._extract_text.return_value = 'Here: {action:"tool",tool:"research",arguments:{query:"Mars"}}'
        with mock.patch("luxai.secure_keys.get_api_key", return_value="test-key"):
            decision = CloudTaskDecider(runtime)({"goal": runtime.goal, "history": []})
        self.assertEqual(decision, {"action": "tool", "tool": "research", "arguments": {"query": "Mars"}})

    def test_plain_app_open_is_native_offline_and_requires_visible_window(self):
        runtime = offline_runtime("Please open Discord")
        with (
            mock.patch("luxai.windows_apps.launch_installed_app", return_value=(True, "Discord window visible")) as launch,
            mock.patch("luxai.windows_apps.find_app_window", return_value=1234),
            mock.patch("luxai.screen.capture_screen") as capture,
            mock.patch("luxai.visual_reasoner.run_visual_reasoner") as visual,
        ):
            result = run_task(runtime.goal, CloudTaskDecider(runtime), runtime)
        self.assertEqual(result.status, "completed")
        self.assertEqual(runtime.preferred_hwnd, 1234)
        launch.assert_called_once_with("discord")
        capture.assert_not_called()
        visual.assert_not_called()
        runtime.planner._request.assert_not_called()

    def test_native_open_without_observed_window_is_not_completed(self):
        runtime = offline_runtime("Open Discord")
        with (
            mock.patch("luxai.windows_apps.launch_installed_app", return_value=(True, "Launch request issued")),
            mock.patch("luxai.windows_apps.find_app_window", return_value=0),
        ):
            result = run_task(runtime.goal, CloudTaskDecider(runtime), runtime)
        self.assertEqual(result.status, "unverified")
        self.assertFalse(result.verified)
        self.assertEqual(result.steps[0]["summary"], "Launch request issued")

    def test_opening_app_does_not_discard_second_part_of_goal(self):
        runtime = offline_runtime("Open Discord and click settings")
        with (
            mock.patch("luxai.windows_apps.launch_installed_app", return_value=(True, "Discord visible")) as launch,
            mock.patch("luxai.windows_apps.find_app_window", return_value=1234),
        ):
            result = run_task(runtime.goal, CloudTaskDecider(runtime), runtime)
        launch.assert_called_once_with("discord")
        self.assertEqual(result.status, "unverified")
        self.assertEqual([step["tool"] for step in result.steps], ["open_app"])

    def test_local_screenshot_needs_neither_cloud_nor_upload_consent(self):
        runtime = offline_runtime("Take a screenshot")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.png"
            path.write_bytes(b"local screen capture")
            with (
                mock.patch("luxai.screen.capture_screen", return_value=str(path)) as capture,
                mock.patch("luxai.visual_reasoner.run_visual_reasoner") as visual,
            ):
                result = run_task(runtime.goal, CloudTaskDecider(runtime), runtime)
            self.assertEqual(result.status, "completed")
            self.assertIn(str(path), result.summary)
        capture.assert_called_once_with()
        visual.assert_not_called()
        runtime.planner._request.assert_not_called()
        self.assertFalse(runtime.screenshots_allowed)

    def test_empty_screenshot_file_is_not_verified(self):
        runtime = offline_runtime("Take a screenshot")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.png"
            path.touch()
            with mock.patch("luxai.screen.capture_screen", return_value=str(path)):
                result = runtime("screenshot", {}, {})
        self.assertFalse(result.ok)
        self.assertFalse(result.verified)
        self.assertFalse(result.data["goal_satisfied"])

    def test_visual_tool_waits_before_capture_or_cloud_analysis(self):
        runtime = offline_runtime("Click the Settings button")
        with mock.patch("luxai.visual_reasoner.run_visual_reasoner") as visual:
            result = runtime("visual_task", {"goal": runtime.goal}, {})
        self.assertTrue(result.question)
        self.assertFalse(result.data["executed"])
        self.assertEqual(result.data["pending_tool"]["question_key"], "cloud_screenshots")
        self.assertFalse(runtime.screenshots_allowed)
        visual.assert_not_called()

    def test_visual_permission_answer_resumes_same_goal(self):
        runtime = offline_runtime("Click the Settings button")
        question = runtime("visual_task", {"goal": "Model cannot substitute another goal"}, {})
        runtime.apply_answer("yes")
        decision = CloudTaskDecider(runtime)({
            "history": [{"ok": False}],
            "pending_tool": question.data["pending_tool"],
            "user_answers": [{"answer": "yes"}],
        })
        self.assertEqual(decision, {"action": "tool", "tool": "visual_task", "arguments": {"goal": runtime.goal}})
        self.assertTrue(runtime.screenshots_allowed)

    def test_declining_visual_permission_cannot_run_visual_action(self):
        runtime = offline_runtime("Click the Settings button")
        question = runtime("visual_task", {"goal": runtime.goal}, {})
        runtime.apply_answer("no")
        decision = CloudTaskDecider(runtime)({"history": [], "pending_tool": question.data["pending_tool"], "user_answers": [{"answer": "no"}]})
        self.assertEqual(decision["action"], "finish")
        self.assertFalse(runtime.screenshots_allowed)
        runtime.planner._request.assert_not_called()

    def test_visual_exception_after_real_action_preserves_partial_progress(self):
        runtime = offline_runtime("Click the Settings button", screenshots_allowed=True)

        def click_then_fail(*args, **kwargs):
            kwargs["result_sink"].update(ok=True, verified=False, actions=1)
            raise ValueError("Unusable verification JSON")

        with mock.patch("luxai.visual_reasoner.run_visual_reasoner", side_effect=click_then_fail) as visual:
            result = runtime("visual_task", {"goal": runtime.goal}, {})
        self.assertTrue(result.ok)
        self.assertFalse(result.verified)
        self.assertFalse(result.data["goal_satisfied"])
        self.assertEqual(result.data["actions"], 1)
        self.assertIn("issued", result.summary)
        self.assertEqual(visual.call_args.args[1], runtime.goal)

    def test_unverified_visual_action_does_not_automatically_repeat_click(self):
        runtime = offline_runtime("Click the Settings button", screenshots_allowed=True)
        runtime.planner.enabled.return_value = True
        decision = CloudTaskDecider(runtime)({"history": [{}], "tool_results": [{
            "tool": "visual_task", "ok": True, "verified": False,
            "summary": "Click issued, result unverified", "data": {"goal_satisfied": False},
        }]})
        self.assertEqual(decision["action"], "finish")
        self.assertIn("unverified", decision["summary"])
        runtime.planner._request.assert_not_called()

    def test_exception_before_visual_action_is_a_failure(self):
        runtime = offline_runtime("Click the Settings button", screenshots_allowed=True)
        with mock.patch("luxai.visual_reasoner.run_visual_reasoner", side_effect=ValueError("No visible target")):
            result = runtime("visual_task", {"goal": runtime.goal}, {})
        self.assertFalse(result.ok)
        self.assertFalse(result.verified)
        self.assertEqual(runtime.executed_steps, [])

    def test_shell_approval_is_bound_to_exact_command_and_current_goal(self):
        runtime = offline_runtime("Create my requested report")
        runtime.config["agent_auto_shell"] = False
        arguments = {"shell": "powershell", "command": "New-Item C:\\Reports\\report.txt", "purpose": "Create requested report", "verification": {"command": "Get-Item C:\\Reports\\report.txt", "expect": "report.txt"}}
        with mock.patch("luxai.local_shell.execute_shell_plan", return_value=ShellResult("needs_authorization", "Awaiting exact command approval", question="Run this exact command?")) as shell:
            result = runtime("shell", arguments, {})
        self.assertFalse(result.data["executed"])
        self.assertEqual(shell.call_args.args[1].goal, runtime.goal)
        self.assertEqual(shell.call_args.args[1].approved_commands, frozenset())
        runtime.apply_answer("yes")
        decision = CloudTaskDecider(runtime)({"history": [{}]})
        self.assertEqual(decision["arguments"], arguments)
        self.assertEqual(runtime._authorization().approved_commands,
                         frozenset({("powershell", arguments["command"])}))
        self.assertNotIn(("cmd", arguments["command"]), runtime._authorization().approved_commands)
        self.assertNotIn("command", result.data["pending_tool"]["arguments"])

    def test_auto_shell_authority_is_exact_per_proposal_and_not_retained(self):
        runtime = offline_runtime("Create my requested report")
        first = {"shell": "powershell", "command": "New-Item C:\\Reports\\first.txt", "purpose": "Create requested report", "verification": {"command": "Get-Item C:\\Reports\\first.txt", "expect": "first.txt"}}
        second = {**first, "command": "New-Item C:\\Reports\\second.txt", "verification": {"command": "Get-Item C:\\Reports\\second.txt", "expect": "second.txt"}}
        with mock.patch("luxai.local_shell.execute_shell_plan", return_value=ShellResult("success", "File readback verified", verified=True)) as shell:
            runtime("shell", first, {})
            first_authorization = shell.call_args.args[1]
            runtime("shell", second, {})
            second_authorization = shell.call_args.args[1]
        self.assertEqual(first_authorization.goal, runtime.goal)
        self.assertEqual(first_authorization.approved_commands, frozenset({("powershell", first["command"])}))
        self.assertEqual(second_authorization.approved_commands, frozenset({("powershell", second["command"])}))
        self.assertNotIn(("powershell", first["command"]), second_authorization.approved_commands)
        self.assertEqual(runtime.approved_commands, set())
        self.assertEqual(runtime._authorization().approved_commands, frozenset())

    def test_literal_shell_goal_requires_matching_shell_and_command(self):
        runtime = offline_runtime("Run in cmd 'ver'")
        verified = ShellResult("success", "Command output verified", verified=True)
        with mock.patch("luxai.local_shell.execute_shell_plan", return_value=verified):
            wrong_shell = runtime("shell", {"shell": "powershell", "command": "ver", "purpose": "Inspect Windows"}, {})
            wrong_command = runtime("shell", {"shell": "cmd", "command": "whoami", "purpose": "Inspect account"}, {})
            matching = runtime("shell", {"shell": "cmd", "command": "ver", "purpose": "Inspect Windows"}, {})
        self.assertFalse(wrong_shell.data["goal_satisfied"])
        self.assertFalse(wrong_command.data["goal_satisfied"])
        self.assertTrue(matching.data["goal_satisfied"])

    def test_literal_cmd_request_is_planned_as_shell_not_application(self):
        runtime = offline_runtime("run in cmd `ver`")
        runtime.planner.enabled.return_value = True
        runtime.planner._provider.return_value = "openai"
        expected = {"action": "tool", "tool": "shell", "arguments": {
            "shell": "cmd", "command": "ver", "purpose": "Run requested version query",
            "verification": {"command": "ver", "expect": "Windows"},
        }}
        runtime.planner._extract_text.return_value = json.dumps(expected)
        self.assertIsNone(runtime.app)
        self.assertIsNone(runtime.direct_app)
        with (
            mock.patch("luxai.api_providers.model_for", return_value="test-model"),
            mock.patch("luxai.secure_keys.get_api_key", return_value="test-key"),
            mock.patch("luxai.windows_apps.launch_installed_app") as launch,
        ):
            decision = CloudTaskDecider(runtime)({"history": [], "user_answers": []})
        self.assertEqual(decision, expected)
        runtime.planner._request.assert_called_once()
        launch.assert_not_called()

    def test_shell_readback_is_step_proof_not_compound_goal_proof(self):
        runtime = offline_runtime("Find my video driver and then enable dark theme")
        arguments = {"shell": "cmd", "command": "ver", "purpose": "Inspect Windows", "verification": {"command": "ver", "expect": "Windows"}}
        with mock.patch("luxai.local_shell.execute_shell_plan", return_value=ShellResult("success", "Windows version read", exit_code=0, stdout="Windows 11", verified=True)):
            result = runtime("shell", arguments, {})
        self.assertTrue(result.verified)
        self.assertFalse(result.data["goal_satisfied"])

    def test_requested_theme_direction_is_part_of_goal_evidence(self):
        runtime = offline_runtime("Enable dark theme")
        self.assertEqual(runtime.native_request, {"action": "set_dark_theme", "enabled": True})
        with mock.patch("luxai.local_shell.execute_builtin", return_value=ShellResult("success", "Light theme verified", verified=True)):
            result = runtime("desktop_action", {"action": "set_dark_theme", "enabled": False}, {})
        self.assertFalse(result.data["goal_satisfied"])

    def test_explicit_theme_executes_typed_action_without_extra_question(self):
        runtime = offline_runtime("Enable dark theme")
        with mock.patch("luxai.local_shell.execute_builtin", return_value=ShellResult("success", "Dark theme verified", verified=True)) as builtin:
            result = run_task(runtime.goal, CloudTaskDecider(runtime), runtime)
        self.assertEqual(result.status, "completed")
        self.assertEqual(builtin.call_args.args[0], "set_dark_theme")
        self.assertIs(builtin.call_args.kwargs["enabled"], True)
        runtime.planner._request.assert_not_called()

    def test_ambiguous_night_mode_asks_then_uses_answer(self):
        runtime = offline_runtime("Enable night mode")
        decider = CloudTaskDecider(runtime)
        first = decider({"history": []})
        self.assertEqual(first["action"], "ask")
        runtime.apply_answer("dark theme")
        second = decider({"history": [], "user_answers": [{"answer": "dark theme"}]})
        self.assertEqual(second, {"action": "tool", "tool": "desktop_action", "arguments": {"action": "set_dark_theme", "enabled": True}})

    def test_generic_desktop_action_cannot_bypass_shell_or_message_tools(self):
        runtime = offline_runtime("Help with my task")
        with mock.patch("luxai.desktop_actions.execute_desktop_step") as execute:
            for action in ("run_cmd", "run_powershell", "run_file", "type_text", "press_enter", "hotkey", "empty_recycle_bin"):
                with self.subTest(action=action), self.assertRaises(PermissionError):
                    runtime("desktop_action", {"action": action}, {})
        execute.assert_not_called()

    def test_cancellation_prevents_native_effects(self):
        runtime = offline_runtime("Open Discord")
        runtime.cancel_event.set()
        with mock.patch("luxai.windows_apps.launch_installed_app") as launch:
            result = runtime("open_app", {"target": "discord"}, {})
        self.assertFalse(result.ok)
        launch.assert_not_called()

    def test_restart_restores_answers_but_never_shell_approval(self):
        runtime = offline_runtime("Create my report")
        runtime.restore_checkpoint({
            "user_answers": [{"answer": "yes"}],
            "pending_tool": {"tool": "shell", "question_key": "shell",
                             "arguments": {"purpose": "Create report", "command": "untrusted restored command"},
                             "approved": True},
            "approved_commands": [["cmd", "untrusted restored command"]],
        })
        runtime.apply_answer("yes")
        self.assertEqual(runtime.user_clarifications, ["yes", "yes"])
        self.assertEqual(runtime._authorization().approved_commands, frozenset())
        self.assertIsNone(runtime.resume_tool)
        self.assertIsNone(runtime.pending_authorization)

    def test_restart_requires_fresh_screenshot_permission(self):
        runtime = offline_runtime("Click Settings")
        runtime.restore_checkpoint({
            "user_answers": [{"answer": "yes"}],
            "pending_tool": {"tool": "visual_task", "question_key": "cloud_screenshots"},
        })
        self.assertFalse(runtime.screenshots_allowed)
        with mock.patch("luxai.visual_reasoner.run_visual_reasoner") as visual:
            result = runtime("visual_task", {"goal": runtime.goal}, {})
        visual.assert_not_called()
        self.assertTrue(result.question)
        runtime.apply_answer("yes")
        self.assertTrue(runtime.screenshots_allowed)

    def test_verified_theme_hint_skips_question_but_executes_fresh_readback(self):
        runtime = offline_runtime("Enable night mode")
        hint = {"status": "match", "procedure": {"steps": [{"tool": "desktop_action", "arguments": {"action": "set_dark_theme", "enabled": True}}]}}
        decision = CloudTaskDecider(runtime)({"history": [], "memory": hint})
        self.assertEqual(decision, {"action": "tool", "tool": "desktop_action", "arguments": {"action": "set_dark_theme", "enabled": True}})
        with mock.patch("luxai.local_shell.execute_builtin", return_value=ShellResult("success", "Fresh dark-theme readback", verified=True)) as builtin:
            result = runtime(decision["tool"], decision["arguments"], {})
        builtin.assert_called_once()
        self.assertTrue(result.verified)
        self.assertTrue(result.data["goal_satisfied"])
        self.assertFalse(runtime.screenshots_allowed)
        self.assertEqual(runtime._authorization().approved_commands, frozenset())

    def test_memory_cannot_resolve_night_mode_into_power_shell_or_upload(self):
        for step in (
            {"tool": "desktop_action", "arguments": {"action": "sleep"}},
            {"tool": "shell", "arguments": {"shell": "cmd", "command": "shutdown /s", "approved": True}},
            {"tool": "visual_task", "arguments": {"goal": "Upload screen", "approved": True}},
        ):
            with self.subTest(step=step):
                runtime = offline_runtime("Enable night mode")
                decision = CloudTaskDecider(runtime)({"history": [], "memory": {"status": "match", "procedure": {"steps": [step]}}})
                self.assertEqual(decision["action"], "ask")
                self.assertEqual(runtime.native_request, {"action": "clarify_night_mode"})
                self.assertEqual(runtime._authorization().approved_commands, frozenset())
                self.assertFalse(runtime.screenshots_allowed)

    def test_ambiguous_memory_hint_does_not_choose_theme_preference(self):
        runtime = offline_runtime("Enable night mode")
        decision = CloudTaskDecider(runtime)({"history": [], "memory": {
            "status": "ambiguous", "procedure": {"steps": [{"tool": "desktop_action", "arguments": {"action": "set_dark_theme", "enabled": True}}]},
        }})
        self.assertEqual(decision["action"], "ask")

    def test_research_findings_do_not_complete_followup_action(self):
        for goal in (
            "Research Windows night mode and save a report",
            "Research Windows night mode and create a report",
            "Research Windows night mode and send the answer",
            "Найди информацию о ночном режиме и сохрани отчёт",
            "Найди информацию о ночном режиме и создай документ",
            "Найди информацию о ночном режиме и отправь ответ",
            "Caută informații despre modul de noapte și salvează raportul",
            "Caută informații despre modul de noapte și creează un document",
            "Caută informații despre modul de noapte și trimite răspunsul",
        ):
            with self.subTest(goal=goal):
                runtime = offline_runtime(goal)
                with mock.patch("luxai.web_research.researched_summary", return_value=("Observed findings", "https://example.org/source")):
                    result = runtime("research", {"query": "Windows night mode"}, {})
                self.assertTrue(result.verified)
                self.assertFalse(result.data["goal_satisfied"])

    def test_large_history_preserves_valid_json_goal_and_latest_observation(self):
        goal = "Inspect the network settings and diagnose their current state. " * 25
        runtime = offline_runtime(goal)
        runtime.planner.enabled.return_value = True
        runtime.planner._provider.return_value = "openai"
        runtime.planner._extract_text.return_value = '{"action":"ask","question":"Which adapter?"}'
        newest = {"tool": "shell", "ok": True, "verified": False, "summary": "Latest adapter evidence", "data": {"stdout": "Network adapter Ethernet disconnected"}}
        context = {
            "goal": goal,
            "history": [{"tool": "research", "summary": "old detail" * 5000} for _ in range(40)],
            "tool_results": [{"tool": "research", "summary": "old source" * 5000} for _ in range(15)] + [newest],
            "user_answers": [{"question": "Adapter name?", "answer": "Ethernet"}],
        }
        with (
            mock.patch("luxai.api_providers.model_for", return_value="test-model"),
            mock.patch("luxai.secure_keys.get_api_key", return_value="test-key"),
        ):
            decision = CloudTaskDecider(runtime)(context)
        self.assertEqual(decision["action"], "ask")
        messages = runtime.planner._request.call_args.args[3]
        sent = json.loads(messages[-1]["content"])
        self.assertEqual(sent["goal"], goal)
        self.assertEqual(sent["tool_results"][-1], newest)
        self.assertEqual(sent["user_answers"], context["user_answers"])
        self.assertLess(len(messages[-1]["content"]), 28000)

    def test_native_tool_question_resumes_same_task_with_explicit_theme_answer(self):
        runtime = offline_runtime("Change my Windows theme")
        question = ShellResult("needs_authorization", "Theme direction is missing", question="Dark or light theme?")
        verified = ShellResult("success", "Dark theme readback verified", verified=True)
        with tempfile.TemporaryDirectory() as directory:
            memory = TaskMemory(Path(directory) / "tasks.json")
            with mock.patch("luxai.local_shell.execute_builtin", side_effect=[question, verified]) as builtin:
                first = run_task(runtime.goal, lambda _: {"action": "tool", "tool": "desktop_action", "arguments": {"action": "set_dark_theme"}}, runtime, memory=memory)
                self.assertEqual(first.status, "waiting")
                self.assertFalse(first.steps[-1]["executed"])
                saved = memory.get_task(first.task_id)["checkpoint"]
                self.assertEqual(saved["pending_tool"]["question_key"], "native_action")
                self.assertEqual(saved["pending_tool"]["arguments"], {"action": "set_dark_theme"})
                runtime.apply_answer("dark theme")
                second = run_task(runtime.goal, CloudTaskDecider(runtime), runtime, memory=memory,
                                  task_id=first.task_id, clarification="dark theme")
        self.assertEqual(second.task_id, first.task_id)
        self.assertEqual(second.status, "completed")
        self.assertEqual(builtin.call_count, 2)
        self.assertIs(builtin.call_args.kwargs["enabled"], True)
        self.assertEqual(builtin.call_args.args[1].goal, "enable dark theme")
        self.assertEqual(runtime.native_request, {"action": "set_dark_theme", "enabled": True})

    def test_checkpoint_goal_evidence_finishes_without_rerunning_tool(self):
        runtime = offline_runtime("Change the requested Windows setting")
        runtime.planner.enabled.return_value = True
        checkpoint_step = {"tool": "desktop_action", "ok": True, "verified": True,
                           "executed": True, "goal_satisfied": True,
                           "summary": "Requested setting independently read back"}
        with mock.patch("luxai.local_shell.execute_builtin") as builtin:
            decision = CloudTaskDecider(runtime)({"history": [checkpoint_step], "tool_results": [checkpoint_step]})
        self.assertEqual(decision, {"action": "finish", "summary": checkpoint_step["summary"]})
        runtime.planner._request.assert_not_called()
        builtin.assert_not_called()


if __name__ == "__main__":
    unittest.main()
