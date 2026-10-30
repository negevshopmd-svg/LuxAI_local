"""Edited/deleted presets must affect real dispatch, including native shortcuts."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import main
from luxai.command_registry import CommandRegistry, checked_command


class BuiltinRuntime093cTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.registry = CommandRegistry(Path(folder.name) / "commands.json")
        self.preset = next(item for item in self.registry.entries()
                           if item["action"] == "launch_game" and item["target"] == "dota2")
        self.phrase = self.preset["phrases"][0]

    def window(self, phrase):
        return SimpleNamespace(
            _processing=False, _closed=False,
            _command_queue=[{"parts": [phrase], "answers": [], "routes": []}],
            _pending_agent_task=None, _pending_discord_message=None,
            cfg={"wake_prefix": "Jarvis", "response_language": "ru"},
            mic_status=mock.Mock(), command_registry=self.registry,
            _execute_registered=mock.Mock(), _start_native_plan=mock.Mock(),
            _resolved_command=mock.Mock(), _error_message=lambda error: str(error),
            agent=mock.Mock(), _start_local_chat=mock.Mock(),
        )

    def test_customized_builtin_uses_reviewed_actions_instead_of_native_game(self):
        edited = self.registry.save_command(dict(
            self.preset, action="time", target="", title="Edited game shortcut"))
        window = self.window(self.phrase)
        main.MainWindow._dispatch_command(window)
        window._execute_registered.assert_called_once_with(self.phrase, edited)
        window._start_native_plan.assert_not_called()
        window._resolved_command.assert_not_called()

    def test_untouched_builtin_keeps_native_game_route(self):
        window = self.window(self.phrase)
        main.MainWindow._dispatch_command(window)
        window._execute_registered.assert_not_called()
        window._resolved_command.assert_not_called()
        window._start_native_plan.assert_called_once()
        self.assertEqual(window._start_native_plan.call_args.args[0], self.phrase)
        self.assertEqual(window._start_native_plan.call_args.args[1]["target"], "dota2")

    def test_deleted_builtin_cannot_fall_through_to_native_game(self):
        self.registry.remove_command(self.preset["id"])
        window = self.window(self.phrase)
        main.MainWindow._dispatch_command(window)
        window._execute_registered.assert_not_called()
        window._start_native_plan.assert_not_called()
        self.assertIn("отключена", window._resolved_command.call_args.args[1])

    def test_replaced_phrase_stops_old_native_action_and_new_phrase_works(self):
        edited = self.registry.save_command(dict(self.preset, phrases=["personal game shortcut"]))
        obsolete = self.window(self.phrase)
        main.MainWindow._dispatch_command(obsolete)
        obsolete._execute_registered.assert_not_called()
        obsolete._start_native_plan.assert_not_called()
        self.assertIn("отключена", obsolete._resolved_command.call_args.args[1])
        current = self.window("personal game shortcut")
        main.MainWindow._dispatch_command(current)
        current._execute_registered.assert_called_once_with("personal game shortcut", edited)

    def test_async_fallback_rechecks_deletion_before_fast_executor(self):
        self.registry.remove_command(self.preset["id"])
        window = self.window(self.phrase)
        main.MainWindow._safe_local_fallback(window, self.phrase, "cloud unavailable")
        window.agent.handle_fast.assert_not_called()
        window._execute_registered.assert_not_called()
        self.assertIn("отключена", window._resolved_command.call_args.args[1])

    def test_builtin_trigger_compares_actions_without_ui_metadata(self):
        edited = self.registry.save_command(dict(self.preset, hotkey="ctrl+alt+f8"))
        verified = checked_command(edited, builtin=True)
        window = self.window(self.phrase)
        window._command_queue[0].update(saved_entry=verified, triggered_id=edited["id"])
        main.MainWindow._dispatch_command(window)
        window._execute_registered.assert_called_once_with(self.phrase, verified)
        window._resolved_command.assert_not_called()

    def test_builtin_trigger_still_drops_real_edits_after_queueing(self):
        edited = self.registry.save_command(dict(self.preset, hotkey="ctrl+alt+f8"))
        verified = checked_command(edited, builtin=True)
        window = self.window(self.phrase)
        window._command_queue[0].update(saved_entry=verified, triggered_id=edited["id"])
        self.registry.save_command(dict(edited, title="Changed while queued"))
        main.MainWindow._dispatch_command(window)
        window._execute_registered.assert_not_called()
        self.assertIn("до запуска", window._resolved_command.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
