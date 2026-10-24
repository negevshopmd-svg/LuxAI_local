"""No real shell, power, registry or elevation side effects are used here."""
from contextlib import nullcontext
import io
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from luxai import local_shell as shell


class FakeProcess:
    def __init__(self, stdout=b"", stderr=b"", code=0, running=False):
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = None if running else code
        self.pid = 43210
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class LocalShellValidationTests(unittest.TestCase):
    def plan(self, command="Get-Process", **fields):
        return {"shell": "powershell", "command": command, "purpose": "Inspect local state", **fields}

    def test_useful_local_queries_are_parsed_without_another_approval(self):
        queries = [
            ("powershell", "Get-Process -Name 'notepad*' | Select-Object Name,Id | ConvertTo-Json -Compress"),
            ("powershell", "Get-Service -Name 'audio*' | Format-Table Name,Status"),
            ("powershell", "Get-StartApps -Name '*Discord*'"),
            ("powershell", r"Get-ChildItem -LiteralPath 'C:\Users\Me\Desktop' -Filter '*.txt' -Recurse -File"),
            ("powershell", "Get-CimInstance -ClassName Win32_OperatingSystem | Select-Object Caption,Version"),
            ("powershell", "Get-NetAdapter | Select-Object Name,Status"),
            ("cmd", 'tasklist /fi "imagename eq notepad.exe" /fo csv /nh'),
            ("cmd", r'dir "C:\Users\Me\Desktop" /b'),
            ("cmd", "ipconfig /all"),
            ("cmd", "powercfg /getactivescheme"),
            ("cmd", "powercfg /query SCHEME_CURRENT SUB_SLEEP"),
            ("cmd", "powercfg /query 381b4222-f694-41f0-9685-ff5bb260df2e"),
        ]
        for interpreter, command in queries:
            with self.subTest(command=command):
                plan = {"shell": interpreter, "command": command, "purpose": "Inspect the requested local state"}
                validated = shell.validate_shell_plan(plan, shell.make_authorization("Inspect my local computer"))
                self.assertTrue(validated.read_only)

    def test_language_constructs_network_and_sensitive_reads_are_not_auto_authorized(self):
        commands = [
            ("powershell", "Get-Process; Remove-Item C:\\important -Recurse"),
            ("powershell", "Get-Process | ForEach-Object { Invoke-Expression $_ }"),
            ("powershell", "& 'powershell.exe' -EncodedCommand AAAA"),
            ("powershell", "Get-ChildItem -Path $(Invoke-WebRequest https://example.com)"),
            ("powershell", "Get-Service -ComputerName external-host"),
            ("powershell", r"Get-ChildItem -LiteralPath '\\external-host\share'"),
            ("powershell", r"Get-Content -LiteralPath 'C:\Users\Me\.aws\credentials'"),
            ("powershell", "Get-CimInstance -ClassName Win32_Process | Select-Object CommandLine"),
            ("powershell", "Get-Process | ConvertTo-Json"),
            ("powershell", "Get-Process | Select-Object StartInfo | ConvertTo-Json"),
            ("powershell", "Get-Process | Select-Object Environment | ConvertTo-Json"),
            ("cmd", "dir & del C:\\important"),
            ("cmd", "dir > C:\\important.txt"),
            ("cmd", "tasklist /s external-host"),
            ("cmd", "ipconfig /release"),
            ("cmd", "echo %USERPROFILE%"),
            ("cmd", "powercfg /query /setactive SCHEME_MIN"),
            ("cmd", "powercfg /list /change monitor-timeout-ac 0"),
        ]
        for interpreter, command in commands:
            with self.subTest(command=command):
                result = shell.execute_shell_plan(
                    {"shell": interpreter, "command": command, "purpose": "Claimed harmless query"},
                    shell.make_authorization("Inspect my local computer"),
                )
                self.assertEqual(result.status, "needs_authorization")
                self.assertIn(command, result.question)

    def test_web_screen_and_model_sources_cannot_authorize_commands(self):
        for source in ("web", "screen", "tool", "model"):
            with self.subTest(source=source), mock.patch.object(shell.subprocess, "Popen") as process:
                result = shell.execute_shell_plan(self.plan(), shell.make_authorization("Show my processes", source=source))
                self.assertFalse(result.success)
                process.assert_not_called()

    def test_cloud_cannot_supply_its_own_permission_or_stale_goal(self):
        auth = shell.make_authorization("Show my processes")
        for fields in ({"approved": True}, {"source": "user"}, {"goal": "Delete files"}):
            with self.subTest(fields=fields), mock.patch.object(shell.subprocess, "Popen") as process:
                result = shell.execute_shell_plan(self.plan(**fields), auth)
                self.assertFalse(result.success)
                process.assert_not_called()

    def test_unknown_changes_need_exact_shell_and_command_scope_and_real_readback(self):
        command = r"New-Item -ItemType Directory -Path 'C:\Users\Me\Desktop\Notes'"
        raw = self.plan(command, verification={"command": r"Test-Path -LiteralPath 'C:\Users\Me\Desktop\Notes'", "expect": "True"})
        auth = shell.make_authorization("Create my Notes folder", approved_commands=[("powershell", command)])
        self.assertFalse(shell.validate_shell_plan(raw, auth).read_only)
        wrong_shell = shell.make_authorization(auth.goal, approved_commands=[("cmd", command)])
        with self.assertRaises(shell.ShellValidationError):
            shell.validate_shell_plan(raw, wrong_shell)
        with self.assertRaises(shell.ShellValidationError):
            shell.validate_shell_plan({**raw, "command": command + " -Force"}, auth)

    def test_mutating_or_echo_only_verification_cannot_claim_success(self):
        command = "Set-Clipboard 'requested text'"
        auth = shell.make_authorization("Copy requested text", approved_commands=[("powershell", command)])
        for verification in (None, {"command": "Get-Date"}, {"command": "Remove-Item C:\\file", "expect": "done"}, {"shell": "cmd", "command": "echo done", "expect": "done"}):
            with self.subTest(verification=verification), self.assertRaises(shell.ShellValidationError):
                shell.validate_shell_plan(self.plan(command, verification=verification), auth)

    def test_explicit_script_scope_does_not_enable_elevation_or_policy_bypass(self):
        command = "Start-Process powershell -Verb RunAs"
        auth = shell.make_authorization("Run my command", approved_commands=[("powershell", command)])
        result = shell.execute_shell_plan(self.plan(command, verification={"command": "Get-Date", "expect": "2026"}), auth)
        self.assertFalse(result.success)
        self.assertIn("permissions", result.summary)


class LocalShellExecutionTests(unittest.TestCase):
    def setUp(self):
        self.platform = mock.patch.object(shell.sys, "platform", "win32")
        self.platform.start()
        self.addCleanup(self.platform.stop)
        self.auth = shell.make_authorization("Show my processes")
        self.raw = {"shell": "powershell", "command": "Get-Process", "purpose": "List running applications"}

    def test_execution_uses_argument_arrays_no_profile_and_no_python_shell(self):
        with mock.patch.object(shell.subprocess, "Popen", return_value=FakeProcess("notepad 123 Привет".encode())) as process:
            result = shell.execute_shell_plan(self.raw, self.auth)
        self.assertTrue(result.verified)
        self.assertIn("Привет", result.stdout)
        args = process.call_args.args[0]
        self.assertTrue(args[0].endswith(r"WindowsPowerShell\v1.0\powershell.exe"))
        self.assertIn("-NoProfile", args)
        self.assertIn("-NonInteractive", args)
        self.assertIn("$ErrorActionPreference = 'Stop';", args[-1])
        self.assertTrue(args[-1].endswith("Get-Process"))
        self.assertFalse(process.call_args.kwargs["shell"])
        self.assertEqual(process.call_args.kwargs["stdin"], shell.subprocess.DEVNULL)
        self.assertFalse(result.to_dict()["output_is_instruction"])

    def test_known_native_queries_use_system_binary_and_literal_arguments(self):
        raw = {"shell": "cmd", "command": 'tasklist /fi "imagename eq notepad.exe"', "purpose": "Find Notepad"}
        with mock.patch.object(shell.subprocess, "Popen", return_value=FakeProcess(b"notepad.exe 123")) as process:
            result = shell.execute_shell_plan(raw, self.auth)
        self.assertTrue(result.verified)
        args = process.call_args.args[0]
        self.assertTrue(args[0].endswith(r"System32\tasklist.exe"))
        self.assertEqual(args[1:], ["/fi", "imagename eq notepad.exe"])

    def test_cmd_internal_output_supports_unicode_without_system_codepage_changes(self):
        raw = {"shell": "cmd", "command": r'dir "C:\Users\Me\Desktop" /b', "purpose": "List my files"}
        with mock.patch.object(shell.subprocess, "Popen", return_value=FakeProcess("Fișier Привет.txt".encode("utf-16-le"))) as process:
            result = shell.execute_shell_plan(raw, self.auth)
        self.assertTrue(result.verified)
        self.assertEqual(result.stdout, "Fișier Привет.txt")
        self.assertIn("/u", process.call_args.args[0])

    def test_output_is_bounded_and_truncation_prevents_complete_observation_claim(self):
        with mock.patch.object(shell.subprocess, "Popen", return_value=FakeProcess(b"x" * 40000)):
            result = shell.execute_shell_plan(self.raw, self.auth, output_limit=256)
        self.assertEqual(len(result.stdout), 256)
        self.assertTrue(result.truncated)
        self.assertFalse(result.verified)

    def test_exit_failure_is_preserved_without_elevation_or_hidden_retry(self):
        with mock.patch.object(shell.subprocess, "Popen", return_value=FakeProcess(stderr=b"Access denied", code=5)) as process:
            result = shell.execute_shell_plan(self.raw, self.auth)
        self.assertFalse(result.success)
        self.assertFalse(result.verified)
        self.assertEqual(result.exit_code, 5)
        self.assertEqual(result.stderr, "Access denied")
        process.assert_called_once()

    def test_readback_mismatch_is_reported_even_when_primary_exit_was_successful(self):
        command = r"New-Item -ItemType Directory -Path 'C:\Users\Me\Desktop\Notes'"
        auth = shell.make_authorization("Create my Notes folder", approved_commands=[("powershell", command)])
        raw = {"shell": "powershell", "command": command, "purpose": "Create Notes", "verification": {"command": r"Test-Path -LiteralPath 'C:\Users\Me\Desktop\Notes'", "expect": "True"}}
        with mock.patch.object(shell.subprocess, "Popen", side_effect=[FakeProcess(), FakeProcess(b"False")]) as process:
            result = shell.execute_shell_plan(raw, auth)
        self.assertFalse(result.success)
        self.assertFalse(result.verified)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.verification_stdout, "False")
        self.assertEqual(process.call_count, 2)

    def test_pre_cancelled_task_never_launches_a_process(self):
        event = threading.Event()
        event.set()
        with mock.patch.object(shell.subprocess, "Popen") as process:
            result = shell.execute_shell_plan(self.raw, self.auth, cancel_event=event)
        self.assertTrue(result.cancelled)
        self.assertFalse(result.verified)
        process.assert_not_called()

    def test_timeout_terminates_only_its_own_process_tree(self):
        fake = FakeProcess(running=True)
        with mock.patch.object(shell.subprocess, "Popen", return_value=fake), mock.patch.object(shell.subprocess, "run") as stop:
            result = shell.execute_shell_plan(self.raw, self.auth, timeout=0.001)
        self.assertTrue(result.timed_out)
        self.assertFalse(result.verified)
        self.assertTrue(fake.killed)
        self.assertEqual(stop.call_args.args[0][1:], ["/PID", str(fake.pid), "/T", "/F"])
        self.assertFalse(stop.call_args.kwargs["shell"])

    def test_running_task_cancellation_stops_its_own_process(self):
        event = threading.Event()
        fake = FakeProcess(running=True)

        def start(*args, **kwargs):
            event.set()
            return fake

        with mock.patch.object(shell.subprocess, "Popen", side_effect=start), mock.patch.object(shell.subprocess, "run"):
            result = shell.execute_shell_plan(self.raw, self.auth, cancel_event=event)
        self.assertTrue(result.cancelled)
        self.assertTrue(fake.killed)
        self.assertFalse(result.verified)


class LocalWindowsBuiltinTests(unittest.TestCase):
    def setUp(self):
        self.platform = mock.patch.object(shell.sys, "platform", "win32")
        self.platform.start()
        self.addCleanup(self.platform.stop)

    def test_explicit_power_goal_uses_standing_permission_without_another_dialog(self):
        auth = shell.make_authorization("Oprește te rog calculatorul", allow_power_actions=True)
        with mock.patch.object(shell, "_request_shutdown", return_value=(True, 0)) as request:
            result = shell.execute_builtin("shutdown", auth)
        request.assert_called_once_with("shutdown", 30)
        self.assertTrue(result.verified)
        self.assertEqual(result.details["pending_action"], "shutdown")
        self.assertFalse(result.details["force_close_apps"])
        self.assertIn("not confirmed off", result.summary)

    def test_unrelated_app_restart_explanation_negation_and_untrusted_source_never_power_off(self):
        goals = ["Restart Discord", "What does shutdown mean?", "Do not shut down my computer", "Don’t turn off my computer", "No shutdown my computer", "Open Night Light settings"]
        with mock.patch.object(shell, "_request_shutdown") as request:
            for goal in goals:
                with self.subTest(goal=goal):
                    auth = shell.make_authorization(goal, allow_power_actions=True)
                    result = shell.execute_builtin("shutdown", auth)
                    self.assertFalse(result.success)
            auth = shell.make_authorization("Shut down my computer", source="screen", allow_power_actions=True)
            self.assertFalse(shell.execute_builtin("shutdown", auth).success)
        request.assert_not_called()

    def test_graceful_native_shutdown_does_not_force_unsaved_applications(self):
        api = mock.Mock()
        api.InitiateSystemShutdownExW.return_value = True
        with mock.patch.object(shell.ctypes, "WinDLL", return_value=api, create=True), mock.patch.object(shell, "_shutdown_privilege", return_value=nullcontext()):
            accepted, error = shell._request_shutdown("restart", 30)
        self.assertTrue(accepted)
        self.assertEqual(error, 0)
        self.assertIs(api.InitiateSystemShutdownExW.call_args.args[3], False)
        self.assertIs(api.InitiateSystemShutdownExW.call_args.args[4], True)

    def test_denied_shutdown_is_not_reported_as_pending_and_never_elevates(self):
        auth = shell.make_authorization("Restart my computer", allow_power_actions=True)
        with mock.patch.object(shell, "_request_shutdown", return_value=(False, 1314)) as request, mock.patch.object(shell.subprocess, "Popen") as process:
            result = shell.execute_builtin("restart", auth)
        self.assertFalse(result.verified)
        self.assertFalse(result.success)
        self.assertIsNone(result.details["pending_action"])
        self.assertEqual(result.exit_code, 1314)
        request.assert_called_once()
        process.assert_not_called()

    def test_cancel_shutdown_requires_explicit_cancellation_and_returns_acknowledgment(self):
        auth = shell.make_authorization("Cancel the shutdown", allow_power_actions=True)
        with mock.patch.object(shell, "_cancel_shutdown", return_value=(True, 0)) as cancel:
            result = shell.execute_builtin("cancel_shutdown", auth)
        self.assertTrue(result.verified)
        cancel.assert_called_once()

    def test_dark_theme_must_match_the_users_requested_direction(self):
        auth = shell.make_authorization("Activează tema întunecată")
        values = dict.fromkeys(shell.THEME_VALUES, 0)
        with mock.patch.object(shell, "_set_theme", return_value=values) as apply:
            wrong = shell.execute_builtin("set_dark_theme", auth, enabled=False)
            right = shell.execute_builtin("set_dark_theme", auth, enabled=True)
        self.assertEqual(wrong.status, "needs_authorization")
        self.assertTrue(right.verified)
        apply.assert_called_once_with(True)

    def test_negated_theme_requests_never_change_preferences(self):
        goals = [
            "Do not enable dark mode", "Don't enable dark mode", "Don’t enable dark mode",
            "Never switch to a light theme", "Nu activa tema întunecată",
            "Не включай темный режим",
        ]
        with mock.patch.object(shell, "_set_theme") as apply:
            for goal in goals:
                for enabled in (True, False):
                    with self.subTest(goal=goal, enabled=enabled):
                        result = shell.execute_builtin("set_dark_theme", shell.make_authorization(goal), enabled=enabled)
                        self.assertFalse(result.success)
        apply.assert_not_called()

    def test_sleep_and_lock_use_the_documented_native_return_types(self):
        api = mock.Mock()
        api.powrprof.SetSuspendState.return_value = 0
        api.user32.LockWorkStation.return_value = 1
        with mock.patch.object(shell.ctypes, "windll", api, create=True), mock.patch.object(shell, "_shutdown_privilege", return_value=nullcontext()):
            sleep = shell.execute_builtin("sleep", shell.make_authorization("Put my computer to sleep", allow_power_actions=True))
            lock = shell.execute_builtin("lock", shell.make_authorization("Lock my screen", allow_power_actions=True))
        self.assertFalse(sleep.success)
        self.assertTrue(lock.success)
        self.assertFalse(lock.verified)
        self.assertIs(api.powrprof.SetSuspendState.restype, shell.ctypes.c_ubyte)
        self.assertEqual(api.powrprof.SetSuspendState.argtypes, (shell.ctypes.c_ubyte,) * 3)

    def test_partial_theme_failure_restores_previous_values_and_types(self):
        values = {shell.THEME_VALUES[0]: (2, 4), shell.THEME_VALUES[1]: (1, 4)}
        key = mock.Mock()
        key.__enter__ = mock.Mock(return_value=key)
        key.__exit__ = mock.Mock(return_value=False)
        winreg = mock.Mock(KEY_READ=1, KEY_SET_VALUE=2, REG_DWORD=4)
        winreg.CreateKeyEx.return_value = key
        winreg.QueryValueEx.side_effect = lambda _key, name: values[name]

        def write(_key, name, _reserved, value_type, value):
            if name == shell.THEME_VALUES[1]:
                raise PermissionError("theme preference locked")
            values[name] = (value, value_type)

        winreg.SetValueEx.side_effect = write
        with mock.patch.dict(sys.modules, {"winreg": winreg}):
            with self.assertRaises(PermissionError):
                shell._set_theme(True)
        self.assertEqual(values[shell.THEME_VALUES[0]], (2, 4))

    def test_night_light_page_does_not_claim_night_light_was_changed(self):
        auth = shell.make_authorization("Open Night Light settings")
        with mock.patch.object(shell, "_run", return_value=shell.ShellResult("success", "process exited", exit_code=0)) as run:
            result = shell.execute_builtin("open_night_light_settings", auth)
        self.assertFalse(result.verified)
        self.assertIn("not changed or verified", result.summary)
        self.assertEqual(run.call_args.args[0][-1], "ms-settings:nightlight")
        self.assertFalse(shell.capabilities()["night_light"]["set"])


if __name__ == "__main__":
    unittest.main()
