"""0.4.2f: run Jarvis as administrator through one scheduled task."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from luxai import admin_mode


class AdminModeTests(unittest.TestCase):
    def root(self, with_exe=True):
        root = Path(tempfile.mkdtemp())
        scripts = root / ".venv" / "Scripts"
        scripts.mkdir(parents=True)
        (scripts / "pythonw.exe").write_bytes(b"")
        if with_exe:
            (scripts / "Jarvis.exe").write_bytes(b"")
            (scripts / "Jarvis.exe.stamp").write_text("k", encoding="utf-8")
        return root

    def test_task_starts_jarvis_exe_with_highest_rights_and_normal_priority(self):
        root = self.root()
        xml = admin_mode.task_xml(root, user="PC\\vlad")
        self.assertIn("<RunLevel>HighestAvailable</RunLevel>", xml)
        self.assertIn("<LogonType>InteractiveToken</LogonType>", xml)
        self.assertIn(str(root / ".venv" / "Scripts" / "Jarvis.exe"), xml)
        self.assertIn(str(root / "launch_windows.py"), xml)
        self.assertIn("<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>", xml)  # never stopped after 3 days
        self.assertIn("<Priority>4</Priority>", xml)  # not the slow default task priority
        self.assertIn("<UserId>PC\\vlad</UserId>", xml)

    def test_falls_back_to_pythonw_without_jarvis_exe(self):
        exe, _script = admin_mode.launcher(self.root(with_exe=False))
        self.assertEqual(exe.name, "pythonw.exe")

    def test_autostart_uses_this_folders_task_when_it_exists(self):
        root = self.root()
        name = admin_mode.task_name(root)
        with mock.patch.object(admin_mode, "our_task", return_value=name):
            self.assertEqual(admin_mode.autostart_command(root), f'schtasks.exe /Run /TN "{name}"')
        with mock.patch.object(admin_mode, "our_task", return_value=None):
            self.assertIn("Jarvis.exe", admin_mode.autostart_command(root))

    def test_enable_writes_xml_and_asks_windows_once(self):
        calls = []
        root = self.root()
        with mock.patch.object(admin_mode, "_elevated_schtasks",
                               side_effect=lambda args, **_kw: calls.append(args) or True), \
                mock.patch.object(admin_mode, "task_belongs_here", side_effect=lambda name, r: name != admin_mode.LEGACY_TASK_NAME):
            self.assertTrue(admin_mode.enable(root))
        self.assertEqual(len(calls), 1)
        self.assertIn(f'/Create /TN "{admin_mode.task_name(root)}" /XML', calls[0])
        # run_windows.bat reads the per-folder name from here
        self.assertEqual(admin_mode.name_file(root).read_text(encoding="ascii"), admin_mode.task_name(root))

    def test_declined_prompt_reports_failure(self):
        with mock.patch.object(admin_mode, "_elevated_schtasks", return_value=False), \
                mock.patch.object(admin_mode, "task_belongs_here", return_value=False):
            self.assertFalse(admin_mode.enable(self.root()))

    def test_each_folder_has_its_own_task_name(self):
        """Audit 2 #5: two installations never share (or replace, or delete) one task."""
        a, b = self.root(), self.root()
        self.assertNotEqual(admin_mode.task_name(a), admin_mode.task_name(b))
        self.assertTrue(admin_mode.task_name(a).startswith("LuxAI Jarvis (admin) "))
        self.assertNotEqual(admin_mode.run_value_name(a), admin_mode.run_value_name(b))

    def test_another_folders_task_is_not_ours(self):
        root = self.root()
        other = "<Task><Actions><Exec><Command>C:\\Other\\.venv\\Scripts\\Jarvis.exe</Command>" \
                "<WorkingDirectory>C:\\Other</WorkingDirectory></Exec></Actions></Task>"
        mine = (f"<Task><Actions><Exec><Command>{root / '.venv' / 'Scripts' / 'Jarvis.exe'}</Command>"
                f"<WorkingDirectory>{root}</WorkingDirectory></Exec></Actions></Task>")
        with mock.patch.object(admin_mode.sys, "platform", "win32"):
            with mock.patch.object(admin_mode.subprocess, "run",
                                   return_value=mock.Mock(returncode=0, stdout=other.encode("utf-8"))):
                self.assertFalse(admin_mode.task_belongs_here(admin_mode.LEGACY_TASK_NAME, root))
            with mock.patch.object(admin_mode.subprocess, "run",
                                   return_value=mock.Mock(returncode=0, stdout=mine.encode("utf-8"))):
                self.assertTrue(admin_mode.task_belongs_here(admin_mode.LEGACY_TASK_NAME, root))

    def test_disable_never_deletes_another_folders_task(self):
        calls = []
        with mock.patch.object(admin_mode, "our_tasks", return_value=[]), \
                mock.patch.object(admin_mode, "_elevated_schtasks", side_effect=lambda a, **k: calls.append(a)):
            self.assertTrue(admin_mode.disable(self.root()))
        self.assertEqual(calls, [])

    def test_autostart_value_of_another_folder_is_not_ours(self):
        root = self.root()
        with mock.patch.object(admin_mode, "our_tasks", return_value=[]):
            self.assertTrue(admin_mode.autostart_value_is_ours(f'"x.exe" "{root / "launch_windows.py"}"', root))
            self.assertFalse(admin_mode.autostart_value_is_ours('"x.exe" "C:\\Other\\launch_windows.py"', root))
            self.assertFalse(admin_mode.autostart_value_is_ours('schtasks.exe /Run /TN "LuxAI Jarvis (admin)"', root))

    def test_run_windows_bat_starts_through_the_task_first(self):
        bat = (Path(__file__).resolve().parents[1] / "run_windows.bat").read_text(encoding="utf-8")
        self.assertIn('schtasks /Run /TN "%ADMIN_TASK%"', bat)
        self.assertIn('set /p ADMIN_TASK=<".luxai_data\\admin_task.txt"', bat)
        self.assertLess(bat.index('schtasks /Run /TN "%ADMIN_TASK%"'),
                        bat.index('start "" "%JARVIS_EXE%" "%~dp0launch_windows.py"'))
        # 0.4.2r (audit #6): the task runs only when it belongs to this folder.
        self.assertLess(bat.index("<WorkingDirectory>%HERE%</WorkingDirectory>"),
                        bat.index('schtasks /Run /TN "%ADMIN_TASK%"'))


if __name__ == "__main__":
    unittest.main()
