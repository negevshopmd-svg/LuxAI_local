"""UI adapter routing without starting threads, devices or a Qt window."""
from __future__ import annotations

from types import MethodType, SimpleNamespace
import threading
import unittest
from unittest import mock


class TaskRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        cls.main = main

    def window(self, text, **group_data):
        registry = mock.Mock()
        registry.disabled_match.return_value = False
        registry.match.return_value = None
        return SimpleNamespace(
            _processing=False, _closed=False,
            _command_queue=[{"parts": [text], "answers": [], "routes": [], "original_text": text, **group_data}],
            cfg={"wake_prefix": "Jarvis", "response_language": "en"},
            command_registry=registry,
            _start_adaptive_task=mock.Mock(), _start_visual_reasoner=mock.Mock(),
            _start_selection_request=mock.Mock(), _start_discord_mic_visual=mock.Mock(),
            _execute_registered=mock.Mock(), _resolved_command=mock.Mock(),
            _direct_macro_worker=mock.Mock(), _finish_command_group=mock.Mock(),
            mic_status=mock.Mock(), online_planner=mock.Mock(),
        )

    def queue_window(self, text):
        window = self.window(text)
        window.cfg["tts_enabled"] = False
        window._pending_agent_task = None
        window._adaptive_runtime = None
        window._adaptive_token = None
        window._active_text = None
        window._current_route = "adaptive tools"
        window.append_message = mock.Mock()
        window.save_settings = mock.Mock()
        window.dictation_active = False
        window.command_wizard = SimpleNamespace(active=False)
        window._task_memory = mock.Mock()
        for name in ("_dispatch_command", "_resolved_command", "_finish_command_group"):
            setattr(window, name, MethodType(getattr(self.main.MainWindow, name), window))
        return window

    def test_plain_app_request_routes_to_native_first_runtime(self):
        for phrase in ("Открой дискорд", "Open Discord", "Deschide Discord"):
            with self.subTest(phrase=phrase):
                window = self.window(phrase)
                self.main.MainWindow._dispatch_command(window)
                window._start_adaptive_task.assert_called_once_with(phrase)
                window._start_visual_reasoner.assert_not_called()
                window._execute_registered.assert_not_called()

    def test_plain_screenshot_routes_locally_without_chatbot(self):
        window = self.window("Take a screenshot")
        self.main.MainWindow._dispatch_command(window)
        window._start_adaptive_task.assert_called_once_with("Take a screenshot")
        window._start_visual_reasoner.assert_not_called()

    def test_manually_saved_command_retains_explicit_user_precedence(self):
        window = self.window("Open Discord")
        saved = {"name": "My own Discord command", "action": "open_app", "target": "discord", "builtin": False, "learned": False}
        window.command_registry.match.return_value = saved
        self.main.MainWindow._dispatch_command(window)
        window._execute_registered.assert_called_once_with("Open Discord", saved)
        window._start_adaptive_task.assert_not_called()

    def test_learned_single_step_shortcut_cannot_erase_compound_goal(self):
        phrase = "Open Discord and click the settings icon"
        window = self.window(phrase)
        window.command_registry.match.return_value = {"action": "open_app", "target": "discord", "learned": True}
        self.main.MainWindow._dispatch_command(window)
        window._start_visual_reasoner.assert_called_once_with(phrase)
        window._execute_registered.assert_not_called()

    def test_correction_does_not_send_discord_message_through_generic_mouse(self):
        phrase = "Нажми в Discord на пользователя Hanzo и отправь привет."
        window = self.window(phrase, visual_feedback="Ты не попал. Давай заново.")
        window.online_planner.enabled.return_value = True
        with mock.patch.object(self.main.threading, "Thread") as thread:
            self.main.MainWindow._dispatch_command(window)
        window._start_visual_reasoner.assert_not_called()
        window._start_adaptive_task.assert_not_called()
        thread.assert_called_once()
        self.assertEqual(thread.call_args.kwargs["target"], window._direct_macro_worker)

    def test_resume_preserves_goal_task_id_and_clarification(self):
        runtime = object()
        window = self.window("Open Discord and click settings", adaptive_resume={"runtime": runtime, "task_id": "task-1", "clarification": "Yes"})
        self.main.MainWindow._dispatch_command(window)
        window._start_adaptive_task.assert_called_once_with(
            "Open Discord and click settings", runtime=runtime, task_id="task-1", clarification="Yes")
        window.command_registry.match.assert_not_called()

    def test_clarification_answer_is_queued_under_original_goal(self):
        runtime = SimpleNamespace(goal="Enable night mode", apply_answer=mock.Mock())
        window = SimpleNamespace(
            _adaptive_runtime=runtime, _pending_agent_task={"task_id": "task-1", "runtime": runtime},
            dictation_active=False, command_wizard=SimpleNamespace(active=False),
            _command_queue=[], _dispatch_command=mock.Mock(), save_settings=mock.Mock(),
        )
        self.main.MainWindow.run_command(window, "dark theme")
        runtime.apply_answer.assert_called_once_with("dark theme")
        window._dispatch_command.assert_called_once_with()
        self.assertEqual(window._command_queue[0]["parts"], [runtime.goal])
        self.assertEqual(window._command_queue[0]["adaptive_resume"]["clarification"], "dark theme")
        self.assertEqual(window._command_queue[0]["adaptive_resume"]["task_id"], "task-1")
        window.save_settings.assert_not_called()

    def test_waiting_result_keeps_runtime_and_task_for_next_answer(self):
        from luxai.task_agent import TaskResult
        runtime = SimpleNamespace(screenshots_allowed=False)
        window = SimpleNamespace(
            _closed=False, _adaptive_token="token", _processing=True, _active_text="Enable night mode",
            _adaptive_runtime=runtime, _pending_agent_task=None, _command_queue=[{"parts": [], "answers": [], "routes": []}],
            _resolved_command=mock.Mock(), cfg={"response_language": "en"},
        )
        result = TaskResult("task-1", "waiting", "", question="Which kind of night mode?")
        self.main.MainWindow._on_adaptive_task_ready(window, "token", "Enable night mode", result)
        self.assertEqual(window._pending_agent_task, {"task_id": "task-1", "runtime": runtime})
        self.assertEqual(window._command_queue[0]["outcome_status"], "waiting")
        window._resolved_command.assert_called_once_with("Enable night mode", result.question)

    def test_unverified_action_result_does_not_render_success(self):
        from luxai.task_agent import TaskResult
        runtime = SimpleNamespace(screenshots_allowed=False)
        window = SimpleNamespace(
            _closed=False, _adaptive_token="token", _processing=True, _active_text="Click settings",
            _adaptive_runtime=runtime, _pending_agent_task=None, _command_queue=[{"parts": [], "answers": [], "routes": []}],
            _resolved_command=mock.Mock(), cfg={"response_language": "en"},
        )
        result = TaskResult("task-1", "unverified", "Could not verify", steps=[{"summary": "Click issued; verification failed"}])
        self.main.MainWindow._on_adaptive_task_ready(window, "token", "Click settings", result)
        response = window._resolved_command.call_args.args[1]
        self.assertIn("not yet verified", response)
        self.assertIn("Click issued", response)
        self.assertEqual(window._command_queue[0]["outcome_status"], "unverified")
        self.assertIsNone(window._adaptive_runtime)

    def test_startup_restores_question_without_starting_any_action(self):
        saved = {"id": "task-1", "goal": "Enable night mode", "checkpoint": {
            "pending_question": "Which kind of night mode?",
            "user_answers": [], "steps": [{"tool": "research", "executed": True}],
        }}
        memory = mock.Mock()
        memory.latest_waiting_task.return_value = saved
        window = SimpleNamespace(
            _closed=False, _processing=False, _pending_agent_task=None,
            _task_memory=mock.Mock(return_value=memory),
            cfg={"response_language": "en"}, online_planner=mock.Mock(),
            append_message=mock.Mock(), mic_status=mock.Mock(),
        )
        with (
            mock.patch("luxai.local_shell.execute_builtin") as builtin,
            mock.patch("luxai.local_shell.execute_shell_plan") as shell,
            mock.patch("luxai.windows_apps.launch_installed_app") as launch,
            mock.patch.object(self.main.threading, "Thread") as thread,
        ):
            self.main.MainWindow._restore_pending_adaptive_task(window)
        self.assertEqual(window._pending_agent_task["task_id"], "task-1")
        self.assertEqual(window._pending_agent_task["runtime"].goal, saved["goal"])
        self.assertIs(window._adaptive_runtime, window._pending_agent_task["runtime"])
        self.assertFalse(window._adaptive_runtime.screenshots_allowed)
        self.assertIn(saved["checkpoint"]["pending_question"], window.append_message.call_args.args[1])
        window.mic_status.setText.assert_called_once_with(saved["checkpoint"]["pending_question"])
        memory.save_checkpoint.assert_not_called()
        builtin.assert_not_called()
        shell.assert_not_called()
        launch.assert_not_called()
        thread.assert_not_called()

    def test_startup_preserves_active_task_instead_of_restoring_another(self):
        for state in ({"_closed": True}, {"_processing": True}, {"_pending_agent_task": {"task_id": "active"}}):
            with self.subTest(state=state):
                window = SimpleNamespace(_closed=False, _processing=False, _pending_agent_task=None, _task_memory=mock.Mock())
                for key, value in state.items():
                    setattr(window, key, value)
                self.main.MainWindow._restore_pending_adaptive_task(window)
                window._task_memory.assert_not_called()

    def test_pending_question_pauses_queued_command_without_consuming_it(self):
        window = self.window("Open Calculator")
        window._pending_agent_task = {"task_id": "waiting-task", "runtime": object()}
        self.main.MainWindow._dispatch_command(window)
        self.assertEqual(window._command_queue[0]["parts"], ["Open Calculator"])
        self.assertFalse(window._processing)
        window._start_adaptive_task.assert_not_called()
        window.command_registry.match.assert_not_called()

    def test_waiting_chain_displays_question_and_resumes_before_deferred_work(self):
        from luxai.task_agent import TaskResult
        goal = "Enable night mode"
        runtime = SimpleNamespace(goal=goal, screenshots_allowed=False, apply_answer=mock.Mock())
        window = self.queue_window(goal)
        window._command_queue[0]["parts"] = ["Open Calculator"]
        later = {"parts": ["Open Notepad"], "answers": [], "routes": [], "original_text": "Open Notepad"}
        window._command_queue.append(later)
        window._adaptive_runtime = runtime
        window._adaptive_token = "first-token"
        window._active_text = goal
        window._processing = True
        callbacks = []
        with mock.patch.object(self.main.QTimer, "singleShot", side_effect=lambda delay, callback: callbacks.append(callback)):
            self.main.MainWindow._on_adaptive_task_ready(
                window, "first-token", goal, TaskResult("task-1", "waiting", "", question="Dark theme or Night Light?"))
            self.assertEqual(window._command_queue[0]["parts"], [])
            self.assertEqual(window._command_queue[1]["parts"], ["Open Calculator"])
            self.assertIs(window._command_queue[2], later)
            while callbacks:
                callbacks.pop(0)()
            self.assertIn("Dark theme or Night Light?", window.append_message.call_args.args[1])
            self.assertEqual(window._command_queue[0]["parts"], ["Open Calculator"])
            window._start_adaptive_task.assert_not_called()
            self.main.MainWindow.run_command(window, "dark theme")
            runtime.apply_answer.assert_called_once_with("dark theme")
            window._start_adaptive_task.assert_called_once_with(goal, runtime=runtime, task_id="task-1", clarification="dark theme")
            self.assertEqual(window._command_queue[1]["parts"], ["Open Calculator"])
            self.assertIs(window._command_queue[2], later)
            # Completion releases the preserved next command in normal order.
            window._adaptive_token = "resume-token"
            self.main.MainWindow._on_adaptive_task_ready(
                window, "resume-token", goal, TaskResult("task-1", "completed", "Dark theme verified"))
            while callbacks:
                callbacks.pop(0)()
        self.assertEqual(window._start_adaptive_task.call_args.args, ("Open Calculator",))
        self.assertIs(window._command_queue[1], later)

    def test_fast_answer_flushes_question_before_inserting_resume(self):
        runtime = SimpleNamespace(goal="Enable night mode", apply_answer=mock.Mock())
        window = self.queue_window("Open Calculator")
        window._pending_agent_task = {"task_id": "task-1", "runtime": runtime}
        window._adaptive_runtime = runtime
        question_group = {"parts": [], "answers": ["Dark theme or Night Light?"], "routes": ["adaptive tools"], "outcome_status": "waiting"}
        window._command_queue.insert(0, question_group)
        with mock.patch.object(self.main.QTimer, "singleShot"):
            self.main.MainWindow.run_command(window, "dark theme")
        self.assertIn("Dark theme or Night Light?", window.append_message.call_args.args[1])
        self.assertNotIn(question_group, window._command_queue)
        window._start_adaptive_task.assert_called_once_with(runtime.goal, runtime=runtime, task_id="task-1", clarification="dark theme")
        self.assertEqual(window._command_queue[1]["parts"], ["Open Calculator"])

    def test_cancelling_pending_question_releases_queued_command(self):
        runtime = SimpleNamespace(goal="Enable night mode", cancel_event=threading.Event())
        window = self.queue_window("Open Calculator")
        window._pending_agent_task = {"task_id": "task-1", "runtime": runtime}
        window._adaptive_runtime = runtime
        self.main.MainWindow._cancel_adaptive_task(window)
        self.assertTrue(runtime.cancel_event.is_set())
        window._task_memory.return_value.set_state.assert_called_once_with("task-1", "cancelled", summary="Cancelled by user")
        self.assertIsNone(window._pending_agent_task)
        window._start_adaptive_task.assert_called_once_with("Open Calculator")


if __name__ == "__main__":
    unittest.main()
