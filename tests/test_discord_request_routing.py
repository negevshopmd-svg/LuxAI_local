"""High-level Discord requests retain their exact recipient, body and task.

No windows, messages, API requests, shell commands or configuration files are
touched: real routing methods run against an inert UI adapter.
"""
from __future__ import annotations

from types import MethodType, SimpleNamespace
import unittest
from unittest import mock

from luxai.desktop_agent import DesktopRuntime
from luxai.macro_planner import discord_message_details, validate_generated_macro
from luxai.task_agent import run_task


SHORT = "А то можешь написать в дискорде пользователю Hanzo привет."
DETAILED = (
    "Открой приложение Discord, потом нажми мышкой на пользователя Hanzo, "
    "после этого напиши привет и потом нажми Enter."
)
MUTE = "Закрой микрофон в дискорде."


class DiscordRequestRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        cls.main = main

    def setUp(self):
        self.callbacks = []
        timer = SimpleNamespace(singleShot=lambda delay, callback: self.callbacks.append(callback))
        patcher = mock.patch.object(self.main, "QTimer", timer)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def group(text):
        return {"parts": [text], "answers": [], "routes": [], "original_text": text}

    def window(self, text=None):
        registry = mock.Mock()
        registry.disabled_match.return_value = False
        registry.match.return_value = None
        planner = mock.Mock()
        planner.enabled.return_value = True
        planner.plan_macro.side_effect = AssertionError("Explicit Discord text needs no cloud planner")
        result = SimpleNamespace(
            cfg={"wake_prefix": "Jarvis", "response_language": "ru", "tts_enabled": False},
            _processing=False, _closed=False, _active_text=None, _current_route="",
            _command_queue=[self.group(text)] if text else [],
            _pending_discord_message=None, _pending_agent_task=None,
            _adaptive_runtime=None, _adaptive_token=None,
            _last_visual_goal=None, _last_visual_goal_at=0.0,
            dictation_active=False, command_wizard=SimpleNamespace(active=False),
            command_registry=registry, online_planner=planner,
            agent=SimpleNamespace(history=[], execute_plan=mock.Mock(), remember=mock.Mock()),
            direct_macro_ready=mock.Mock(), mic_status=mock.Mock(),
            append_message=mock.Mock(), save_settings=mock.Mock(),
            confirm_action=mock.Mock(return_value=False),
            _run_saved_steps=mock.Mock(), _start_adaptive_task=mock.Mock(),
            _start_visual_reasoner=mock.Mock(), _start_discord_mic_visual=mock.Mock(),
            _start_selection_request=mock.Mock(), _execute_registered=mock.Mock(),
            _error_message=lambda exc: f"ADAPTER_ERROR: {type(exc).__name__}: {exc}",
        )
        for name in ("_dispatch_command", "_resolved_command", "_finish_command_group",
                     "_ask_discord_message_details", "_continue_discord_message", "_direct_macro_worker"):
            setattr(result, name, MethodType(getattr(self.main.MainWindow, name), result))
        return result

    def drain(self):
        for _ in range(25):
            if not self.callbacks:
                return
            self.callbacks.pop(0)()
        self.fail("Routing callbacks did not settle")

    def dispatch_and_prepare(self, phrase):
        window = self.window(phrase)
        with mock.patch.object(self.main.threading, "Thread") as thread:
            window._dispatch_command()
        thread.assert_called_once()
        self.assertEqual(thread.call_args.kwargs["target"], window._direct_macro_worker)
        self.assertEqual(thread.call_args.kwargs["args"], (phrase,))
        window._direct_macro_worker(phrase)
        window.direct_macro_ready.emit.assert_called_once()
        original, proposal, error = window.direct_macro_ready.emit.call_args.args
        self.assertEqual(original, phrase)
        self.assertEqual(error, "")
        self.assertIsNotNone(proposal)
        window.online_planner.plan_macro.assert_not_called()
        window._start_adaptive_task.assert_not_called()
        window._start_visual_reasoner.assert_not_called()
        window.agent.execute_plan.assert_not_called()
        return window, proposal

    def test_screenshot_short_request_builds_one_guarded_message_operation(self):
        window, proposal = self.dispatch_and_prepare(SHORT)
        self.assertEqual(len(proposal["steps"]), 1)
        self.assertEqual(proposal["steps"][0]["action"], "discord_send_text")
        self.assertEqual(proposal["steps"][0]["target"], "Hanzo||привет")
        self.main.MainWindow._on_direct_macro_ready(window, SHORT, proposal, "")
        window._run_saved_steps.assert_called_once_with(SHORT, proposal["steps"])
        # Contact and final-send approval belong to the dedicated executor;
        # this callback does not ask for a second approval of the same plan.
        window.confirm_action.assert_not_called()

    def test_opening_verb_does_not_replace_the_requested_message(self):
        for phrase in ("Открой Discord и напиши пользователю Hanzo привет",
                       "Deschide Discord scrie-i lui Hanzo salut"):
            with self.subTest(phrase=phrase):
                window, proposal = self.dispatch_and_prepare(phrase)
                self.assertEqual(proposal["steps"][0]["action"], "discord_send_text")
                self.assertTrue(proposal["steps"][0]["target"].startswith("Hanzo||"))

    def test_builtin_open_shortcut_cannot_drop_message_body(self):
        phrase = "Открой Discord и напиши пользователю Hanzo привет"
        window = self.window(phrase)
        window.command_registry.match.return_value = {"builtin": True, "action": "open_app", "target": "discord"}
        with mock.patch.object(self.main.threading, "Thread") as thread:
            window._dispatch_command()
        thread.assert_called_once()
        self.assertEqual(thread.call_args.kwargs["target"], window._direct_macro_worker)
        window._execute_registered.assert_not_called()
        window._start_adaptive_task.assert_not_called()

    def test_screenshot_consent_is_not_an_autoapproved_ordinary_action(self):
        window = self.window()
        window.cfg["confirm_all_actions"] = False
        window.confirm_action = MethodType(self.main.MainWindow.confirm_action, window)
        dialog = mock.Mock()
        dialog.exec.return_value = self.main.QMessageBox.StandardButton.No
        factory = mock.Mock(return_value=dialog)
        factory.StandardButton = self.main.QMessageBox.StandardButton
        with (mock.patch.object(self.main, "QMessageBox", factory),
              mock.patch.object(self.main, "icon"),
              mock.patch.object(self.main, "set_button_icon")):
            self.assertFalse(self.main.MainWindow._allow_cloud_screenshots(window))
        factory.assert_called_once_with(window)
        self.assertFalse(getattr(window, "_visual_upload_consent_session", False))

    def test_different_contact_name_requires_a_real_decision(self):
        import threading
        window = self.window()
        window._processing = True
        window._macro_context = object()
        window.cfg["confirm_all_actions"] = False
        window.confirm_action = MethodType(self.main.MainWindow.confirm_action, window)
        response = {"context": window._macro_context, "spoken": "Hanzo", "displayed": "Other Hanzo", "event": threading.Event(), "approved": False}
        dialog = mock.Mock()
        dialog.exec.return_value = self.main.QMessageBox.StandardButton.No
        factory = mock.Mock(return_value=dialog)
        factory.StandardButton = self.main.QMessageBox.StandardButton
        with (mock.patch.object(self.main, "QMessageBox", factory),
              mock.patch.object(self.main, "icon"),
              mock.patch.object(self.main, "set_button_icon")):
            self.main.MainWindow._on_discord_contact_prompt(window, response)
        factory.assert_called_once_with(window)
        self.assertFalse(response["approved"])
        self.assertTrue(response["event"].is_set())

    def test_detailed_mouse_instructions_are_not_required_for_identical_intent(self):
        _, concise = self.dispatch_and_prepare(SHORT)
        _, detailed = self.dispatch_and_prepare(DETAILED)
        self.assertEqual(concise["steps"], detailed["steps"])
        self.assertEqual(detailed["steps"][0]["target"], "Hanzo||привет")

    def test_automatic_step_planning_preserves_final_real_draft_approval(self):
        window, proposal = self.dispatch_and_prepare(SHORT)
        self.main.MainWindow._on_direct_macro_ready(window, SHORT, proposal, "")
        window.confirm_action.assert_not_called()
        context = {"index": 1, "messages": []}
        window._macro_context = context
        window._finish_visual_macro = mock.Mock()
        draft = SimpleNamespace(username="Hanzo", message="привет")
        with mock.patch.object(self.main.threading, "Thread") as send_thread:
            self.main.MainWindow._on_discord_draft_ready(window, 1, draft, "")
        window.confirm_action.assert_called_once()
        preview = window.confirm_action.call_args.args[0]
        self.assertIn("@Hanzo", preview)
        self.assertIn("привет", preview)
        self.assertIn("НОВОМУ снимку", preview)
        self.assertIn("Enter не нажимался", context["messages"][-1])
        window._finish_visual_macro.assert_called_once()
        send_thread.assert_not_called()

    def test_changed_recipient_or_message_cannot_skip_plan_review(self):
        for target in ("OtherUser||привет", "Hanzo||different message"):
            with self.subTest(target=target):
                window = self.window()
                window._processing, window._active_text = True, SHORT
                proposal = {"steps": [{"action": "discord_send_text", "target": target}]}
                self.main.MainWindow._on_direct_macro_ready(window, SHORT, proposal, "")
                window.confirm_action.assert_called_once()
                window._run_saved_steps.assert_not_called()

    def test_generic_friend_asks_for_name_then_resumes_original_message_first(self):
        original = "Напиши моему другу в Discord привет"
        window = self.window()
        self.main.MainWindow.run_command(window, original)
        later = self.group("Open Calculator")
        window._command_queue.append(later)
        self.drain()
        self.assertEqual(window._pending_discord_message["recipient"], "")
        self.assertEqual(window._pending_discord_message["message"], "привет")
        self.assertIn("Кому написать", window.append_message.call_args.args[1])
        self.assertEqual(later["parts"], ["Open Calculator"])
        window._start_adaptive_task.assert_not_called()
        self.main.MainWindow.run_command(window, "Hanzo")
        source, steps = window._run_saved_steps.call_args.args
        self.assertIn(original, source)
        self.assertIn("Hanzo", source)
        self.assertEqual(steps[0]["target"], "Hanzo||привет")
        self.assertIsNotNone(validate_generated_macro({"steps": steps}, source))
        self.assertIsNone(window._pending_discord_message)
        self.assertIs(window._command_queue[1], later)
        self.assertEqual(later["parts"], ["Open Calculator"])

    def test_known_recipient_asks_for_message_without_inventing_body(self):
        original = "Напиши в Discord пользователю Hanzo"
        window = self.window()
        self.main.MainWindow.run_command(window, original)
        self.drain()
        self.assertEqual(window._pending_discord_message["recipient"], "Hanzo")
        self.assertEqual(window._pending_discord_message["missing"], ["message"])
        self.assertIn("Какой точный текст", window.append_message.call_args.args[1])
        window._run_saved_steps.assert_not_called()
        self.main.MainWindow.run_command(window, "привет")
        source, steps = window._run_saved_steps.call_args.args
        self.assertEqual(steps[0]["target"], "Hanzo||привет")
        self.assertIn(original, source)

    def test_two_missing_fields_are_collected_before_running_any_steps(self):
        window = self.window()
        self.main.MainWindow.run_command(window, "Напиши моему другу в Discord")
        self.drain()
        self.main.MainWindow.run_command(window, "Hanzo")
        self.drain()
        self.assertEqual(window._pending_discord_message["recipient"], "Hanzo")
        self.assertEqual(window._pending_discord_message["missing"], ["message"])
        window._run_saved_steps.assert_not_called()
        self.main.MainWindow.run_command(window, "привет")
        self.assertEqual(window._run_saved_steps.call_args.args[1][0]["target"], "Hanzo||привет")

    def test_actionlike_clarification_is_literal_message_not_a_new_action(self):
        for body in ("выключи микрофон в Discord", "прочитай выделенный текст"):
            with self.subTest(body=body):
                window = self.window()
                self.main.MainWindow.run_command(window, "Напиши Hanzo в Discord")
                self.drain()
                self.main.MainWindow.run_command(window, body)
                self.assertEqual(window._run_saved_steps.call_args.args[1][0]["target"], "Hanzo||" + body)
                window._start_discord_mic_visual.assert_not_called()
                window._start_selection_request.assert_not_called()
                window._start_adaptive_task.assert_not_called()

    def test_quoted_actionlike_message_does_not_trigger_mic_or_selection_tools(self):
        for body in ("выключи микрофон в Discord", "прочитай выделенный текст"):
            with self.subTest(body=body):
                window, proposal = self.dispatch_and_prepare(f'Напиши Hanzo в Discord "{body}"')
                self.assertEqual(proposal["steps"][0]["target"], "Hanzo||" + body)
                window._start_discord_mic_visual.assert_not_called()
                window._start_selection_request.assert_not_called()

    def test_unquoted_body_keeps_platform_words_after_explicit_message_delimiter(self):
        phrase = "Напиши Hanzo в Discord: выключи микрофон в Discord"
        details = discord_message_details(phrase)
        self.assertEqual(details["message"], "выключи микрофон в Discord")
        window, proposal = self.dispatch_and_prepare(phrase)
        self.assertEqual(proposal["steps"][0]["target"], "Hanzo||выключи микрофон в Discord")
        window._start_discord_mic_visual.assert_not_called()

    def test_pending_message_pauses_next_queue_entry_without_consuming_it(self):
        window = self.window("Open Calculator")
        window._pending_discord_message = {"source": SHORT, "recipient": "", "message": "привет", "missing": ["recipient"]}
        window._dispatch_command()
        self.assertEqual(window._command_queue[0]["parts"], ["Open Calculator"])
        self.assertFalse(window._processing)
        window.command_registry.match.assert_not_called()

    def test_cancelling_pending_message_releases_queue_without_sending(self):
        window = self.window()
        self.main.MainWindow.run_command(window, "Напиши моему другу в Discord привет")
        self.drain()
        later = self.group("Open Calculator")
        window._command_queue.append(later)
        self.main.MainWindow.run_command(window, "Отмени задачу")
        self.assertIsNone(window._pending_discord_message)
        window._run_saved_steps.assert_not_called()
        window._start_adaptive_task.assert_called_once_with("Open Calculator")

    def test_close_microphone_routes_to_state_verified_discord_tool(self):
        window = self.window(MUTE)
        with mock.patch.object(self.main.threading, "Thread") as thread:
            window._dispatch_command()
        window._start_discord_mic_visual.assert_called_once_with(MUTE)
        window._start_adaptive_task.assert_not_called()
        window._start_visual_reasoner.assert_not_called()
        window.online_planner.plan_macro.assert_not_called()
        thread.assert_not_called()

    def test_previous_pending_mic_task_can_resume_visual_work_without_policy_error(self):
        def unused_executor(*args):
            self.fail("The old question must not execute a tool")
        unused_executor.runtime_facts = {"explicit_visual_need": False, "opening_goal": False,
                                        "requires_goal_evidence": True}
        old = run_task(MUTE, lambda context: {"action": "ask", "question": "Which Discord window?"}, unused_executor)
        self.assertEqual(old.status, "waiting")
        planner = mock.Mock()
        planner.enabled.return_value = False
        runtime = DesktopRuntime(MUTE, planner, {"response_language": "ru"}, screenshots_allowed=True)
        self.assertTrue(runtime.runtime_facts["explicit_visual_need"])
        runtime.apply_answer("Ну просто с Дискордом.")
        observed_contexts, events = [], []

        def decide(context):
            observed_contexts.append(context)
            return ({"action": "tool", "tool": "visual_task", "arguments": {"goal": MUTE}}
                    if not context["history"] else {"action": "finish", "summary": "Muted state verified"})

        def verified_visual(*args, **kwargs):
            kwargs["result_sink"].update(ok=True, verified=True, actions=0)
            return "Muted state independently verified"

        with mock.patch("luxai.visual_reasoner.run_visual_reasoner", side_effect=verified_visual) as vision:
            result = run_task(MUTE, decide, runtime, task_id=old.task_id,
                              clarification="Ну просто с Дискордом.", progress=events.append)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.steps[0]["tool"], "visual_task")
        self.assertFalse(any(event["event"] == "policy_blocked" for event in events))
        self.assertEqual(observed_contexts[0]["user_answers"][-1]["answer"], "Ну просто с Дискордом.")
        self.assertIn("Ну просто с Дискордом.", vision.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
