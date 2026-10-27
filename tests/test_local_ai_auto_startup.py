"""Automatic engine maintenance never delays the UI or builds native source."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import launch_windows
from luxai import local_ai_setup


class AutomaticLocalEngineTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.log = self.folder / "local_ai_install.log"
        patcher = mock.patch.object(local_ai_setup, "LOG_FILE", self.log)
        patcher.start()
        self.addCleanup(patcher.stop)
        scheduling = mock.patch.object(local_ai_setup, "_BACKGROUND_REQUESTED", False)
        scheduling.start()
        self.addCleanup(scheduling.stop)

    def test_working_engine_is_reused_without_pip_or_network(self):
        with (mock.patch.object(local_ai_setup, "check_backend", return_value=True) as probe,
              mock.patch.object(local_ai_setup.subprocess, "run") as pip):
            self.assertTrue(local_ai_setup.ensure_backend("environment-python.exe"))
        probe.assert_called_once_with("environment-python.exe")
        pip.assert_not_called()
        self.assertEqual(local_ai_setup.setup_status(), "ready")

    def test_missing_engine_installs_only_official_binary_then_verifies_native_import(self):
        with (mock.patch.object(local_ai_setup, "check_backend", side_effect=[False, True]) as probe,
              mock.patch.object(local_ai_setup.subprocess, "run",
                                return_value=subprocess.CompletedProcess([], 0)) as pip):
            self.assertTrue(local_ai_setup.ensure_backend("environment-python.exe"))
        pip.assert_called_once()
        command = pip.call_args.args[0]
        self.assertEqual(command[:4], ["environment-python.exe", "-m", "pip", "install"])
        self.assertIn("--only-binary=:all:", command)
        self.assertIn(local_ai_setup.OFFICIAL_CPU_WHEELS, command)
        self.assertLessEqual(pip.call_args.kwargs["timeout"], 480)
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(local_ai_setup.setup_status(), "ready")

    def test_concurrent_launch_cannot_start_a_second_pip_installation(self):
        parallel_results = []

        def install(*args, **kwargs):
            parallel_results.append(local_ai_setup.ensure_backend("parallel-python.exe"))
            return subprocess.CompletedProcess(args[0], 0)

        with (mock.patch.object(local_ai_setup, "check_backend", side_effect=[False, True]),
              mock.patch.object(local_ai_setup.subprocess, "run", side_effect=install) as pip):
            self.assertTrue(local_ai_setup.ensure_backend("environment-python.exe"))
        self.assertEqual(parallel_results, [False])
        pip.assert_called_once()
        with local_ai_setup._setup_lock() as acquired:
            self.assertTrue(acquired, "Finished installation left its setup lock held")
        self.assertEqual(local_ai_setup.setup_status(), "ready")

    def test_failed_download_does_not_report_an_installed_engine(self):
        with (mock.patch.object(local_ai_setup, "check_backend", return_value=False),
              mock.patch.object(local_ai_setup.subprocess, "run",
                                return_value=subprocess.CompletedProcess([], 1))):
            self.assertFalse(local_ai_setup.ensure_backend("environment-python.exe"))
        self.assertEqual(local_ai_setup.setup_status(), "unavailable")
        with local_ai_setup._setup_lock() as acquired:
            self.assertTrue(acquired, "Failed installation left its setup lock held")

    def probe_lock_from_another_process(self, *, crash=False):
        source = (
            "import os, sys\n"
            "from pathlib import Path\n"
            "from luxai import local_ai_setup\n"
            "local_ai_setup.LOG_FILE = Path(sys.argv[1])\n"
            "with local_ai_setup._setup_lock() as acquired:\n"
            "    print(acquired, flush=True)\n"
        )
        if crash:
            source += "    os._exit(0)\n"
        result = subprocess.run(
            [sys.executable, "-c", source, str(self.log)],
            cwd=Path(__file__).resolve().parents[1], capture_output=True,
            text=True, timeout=5, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.stdout.strip()

    def test_os_lock_excludes_another_process_and_allows_it_after_release(self):
        with local_ai_setup._setup_lock() as acquired:
            self.assertTrue(acquired)
            self.assertEqual(self.probe_lock_from_another_process(), "False")
        self.assertEqual(self.probe_lock_from_another_process(), "True")

    def test_crashed_helper_cannot_leave_setup_permanently_locked(self):
        self.assertEqual(self.probe_lock_from_another_process(crash=True), "True")
        with local_ai_setup._setup_lock() as acquired:
            self.assertTrue(acquired, "The OS did not release the dead helper's lock")

    def test_stale_or_corrupt_setup_status_is_not_presented_as_current_work(self):
        state = self.log.with_suffix(".status.json")
        state.write_text(json.dumps({"state": "installing", "updated_at": 0,
                                     "environment": str(Path(sys.prefix).resolve())}), encoding="utf-8")
        self.assertEqual(local_ai_setup.setup_status(), "")
        state.write_text("not JSON", encoding="utf-8")
        self.assertEqual(local_ai_setup.setup_status(), "")

    def test_status_from_another_python_environment_does_not_mark_this_one_ready(self):
        local_ai_setup._write_status("ready")
        state = self.log.with_suffix(".status.json")
        data = json.loads(state.read_text(encoding="utf-8"))
        data["environment"] = str(self.folder / "different-environment")
        state.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(local_ai_setup.setup_status(), "")

    def test_windows_launcher_schedules_silent_helper_and_never_waits_for_it(self):
        process = mock.Mock()
        with (mock.patch.object(local_ai_setup.sys, "platform", "win32"),
              mock.patch.object(local_ai_setup, "runtime_python", return_value="environment-python.exe"),
              mock.patch.object(local_ai_setup.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True),
              mock.patch.object(local_ai_setup.subprocess, "Popen", return_value=process) as spawn):
            self.assertTrue(local_ai_setup.start_background_setup())
        spawn.assert_called_once()
        self.assertEqual(spawn.call_args.args[0], [
            "environment-python.exe", "-m", "luxai.local_ai_setup", "--ensure",
        ])
        self.assertEqual(spawn.call_args.kwargs["creationflags"] & 0x08000000, 0x08000000)
        for name in ("stdin", "stdout", "stderr"):
            self.assertEqual(spawn.call_args.kwargs[name], subprocess.DEVNULL)
        process.wait.assert_not_called()
        process.communicate.assert_not_called()

    def test_non_windows_launch_does_not_schedule_windows_package_maintenance(self):
        with (mock.patch.object(local_ai_setup.sys, "platform", "linux"),
              mock.patch.object(local_ai_setup, "_BACKGROUND_REQUESTED", True),
              mock.patch.object(local_ai_setup.subprocess, "Popen") as spawn):
            self.assertFalse(local_ai_setup.start_background_setup())
        spawn.assert_not_called()

    def test_launcher_and_main_entry_point_share_one_successful_schedule(self):
        with (mock.patch.object(local_ai_setup.sys, "platform", "win32"),
              mock.patch.object(local_ai_setup.subprocess, "Popen") as spawn):
            self.assertTrue(local_ai_setup.start_background_setup())
            self.assertTrue(local_ai_setup.start_background_setup())
        spawn.assert_called_once()

    def test_failed_spawn_can_retry_then_successful_schedule_is_reused(self):
        with (mock.patch.object(local_ai_setup.sys, "platform", "win32"),
              mock.patch.object(local_ai_setup.subprocess, "Popen",
                                side_effect=[OSError("temporarily unavailable"), mock.Mock()]) as spawn):
            self.assertFalse(local_ai_setup.start_background_setup())
            self.assertFalse(local_ai_setup._BACKGROUND_REQUESTED)
            self.assertTrue(local_ai_setup.start_background_setup())
            self.assertTrue(local_ai_setup.start_background_setup())
        self.assertEqual(spawn.call_count, 2)

    def test_helper_launch_failure_keeps_application_startup_available(self):
        with (mock.patch.object(local_ai_setup.sys, "platform", "win32"),
              mock.patch.object(local_ai_setup.subprocess, "Popen", side_effect=OSError("unavailable"))):
            self.assertFalse(local_ai_setup.start_background_setup())
        application = SimpleNamespace(main=mock.Mock(return_value=0))
        with (mock.patch.object(local_ai_setup, "start_background_setup", return_value=False) as schedule,
              mock.patch.object(launch_windows, "ROOT", self.folder),
              mock.patch.object(launch_windows, "enable_native_crash_log"),
              mock.patch.object(launch_windows.os, "chdir"),
              mock.patch.dict(sys.modules, {"main": application})):
            self.assertEqual(launch_windows.main(), 0)
        schedule.assert_called_once_with()
        application.main.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
