"""Windows startup errors are visible even when launched with pythonw.exe."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import launch_windows


class WindowsStartupTests(unittest.TestCase):
    def test_crash_is_logged_with_traceback_and_python_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = SimpleNamespace(main=mock.Mock(side_effect=RuntimeError("example failure")))
            with (
                mock.patch.object(launch_windows, "ROOT", root),
                mock.patch.object(launch_windows, "STARTUP_LOG", root / "logs" / "startup_error.log"),
                mock.patch.object(launch_windows, "enable_native_crash_log"),
                mock.patch("launch_windows.os.chdir"),
                mock.patch.dict(sys.modules, {"main": fake}),
                mock.patch.object(launch_windows, "_show_failure_dialog") as dialog,
            ):
                self.assertEqual(launch_windows.main(), 1)
                dialog.assert_called_once()
            log = (root / "logs" / "startup_error.log").read_text(encoding="utf-8")
            self.assertIn("RuntimeError: example failure", log)
            self.assertIn("Python:", log)
            self.assertIn("Executable:", log)

    def test_entrypoints_use_diagnostic_wrapper(self):
        root = Path(__file__).resolve().parents[1]
        launch = (root / "run_windows.bat").read_text(encoding="utf-8")
        diagnostic = (root / "diagnose_windows.bat").read_text(encoding="utf-8")
        self.assertIn("launch_windows.py", launch)
        self.assertIn("launch_windows.py", diagnostic)
        self.assertIn("startup_error.log", diagnostic)


if __name__ == "__main__":
    unittest.main()
