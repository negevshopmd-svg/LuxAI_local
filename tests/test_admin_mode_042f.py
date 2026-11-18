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

    def test_autostart_uses_the_task_when_it_exists(self):
        root = self.root()
        with mock.patch.object(admin_mode, "task_exists", return_value=True):
            self.assertEqual(admin_mode.autostart_command(root), 'schtasks.exe /Run /TN "LuxAI Jarvis (admin)"')
        with mock.patch.object(admin_mode, "task_exists", return_value=False):
            self.assertIn("Jarvis.exe", admin_mode.autostart_command(root))

    def test_enable_writes_xml_and_asks_windows_once(self):
        calls = []
        with mock.patch.object(admin_mode, "_elevated_schtasks",
                               side_effect=lambda args, timeout=60: calls.append(args) or True), \
                mock.patch.object(admin_mode, "task_exists", return_value=True):
            self.assertTrue(admin_mode.enable(self.root()))
        self.assertEqual(len(calls), 1)
        self.assertIn('/Create /TN "LuxAI Jarvis (admin)" /XML', calls[0])

    def test_declined_prompt_reports_failure(self):
        with mock.patch.object(admin_mode, "_elevated_schtasks", return_value=False), \
                mock.patch.object(admin_mode, "task_exists", return_value=False):
            self.assertFalse(admin_mode.enable(self.root()))

    def test_run_windows_bat_starts_through_the_task_first(self):
        bat = (Path(__file__).resolve().parents[1] / "run_windows.bat").read_text(encoding="utf-8")
        self.assertIn('schtasks /Run /TN "LuxAI Jarvis (admin)"', bat)
        self.assertLess(bat.index('schtasks /Run /TN "LuxAI Jarvis (admin)"'),
                        bat.index('".venv\\Scripts\\Jarvis.exe" "%~dp0launch_windows.py"'))


if __name__ == "__main__":
    unittest.main()
