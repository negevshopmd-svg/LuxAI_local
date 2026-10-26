"""Exercise the real updater batch in cmd.exe without contacting GitHub.

The local curl executable only copies a fixture into the requested output;
Python selection, validation, self-replacement and exit handling remain real.
Run explicitly in Windows installer CI, outside the Linux unittest discovery.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv


REPO = Path(__file__).resolve().parents[1]


class UpdateBatchWindowsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform != "win32":
            raise RuntimeError("Run this Windows cmd.exe integration test on Windows.")
        cls.temp = tempfile.TemporaryDirectory(prefix="luxai-batch-")
        cls.base = Path(cls.temp.name)
        cls.bin = cls.base / "stub tools"
        cls.bin.mkdir()
        cls.curl = cls.bin / "curl.exe"
        # Windows PowerShell includes the C# compiler. No compiler download,
        # real curl, GitHub access, private key or installed application is used.
        script = r'''
$ErrorActionPreference = 'Stop'
Add-Type -OutputAssembly $env:LUXAI_TEST_CURL_EXE -OutputType ConsoleApplication -TypeDefinition @'
using System;
using System.IO;
public class FixtureCurl {
    public static int Main(string[] args) {
        int output = Array.IndexOf(args, "-o");
        if (output < 0 || output + 1 >= args.Length) return 2;
        File.Copy(Environment.GetEnvironmentVariable("LUXAI_TEST_SOURCE"), args[output + 1], true);
        return 0;
    }
}
'@
'''
        environment = dict(os.environ, LUXAI_TEST_CURL_EXE=str(cls.curl))
        compiled = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            env=environment, capture_output=True, timeout=60,
        )
        if compiled.returncode:
            cls.temp.cleanup()
            raise RuntimeError(compiled.stderr.decode("utf-8", errors="replace"))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_batch(self, updater_source):
        folder = tempfile.TemporaryDirectory(prefix="instalare ășț-", dir=self.base)
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        venv.EnvBuilder(with_pip=False).create(root / ".venv")
        shutil.copyfile(REPO / "Update.bat", root / "Update.bat")
        installed = root / "Update.py"
        installed.write_text("# previous working updater\n", encoding="utf-8")
        source = root / "downloaded fixture.py"
        source.write_text(updater_source, encoding="utf-8")
        environment = dict(
            os.environ,
            PATH=str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
            LUXAI_TEST_SOURCE=str(source),
        )
        # EOF lets a genuine failure pause finish. Success must not print a
        # pause prompt at all. A double-click uses the equivalent cmd /c flow.
        result = subprocess.run(
            [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "Update.bat"],
            cwd=root, env=environment, input=b"", capture_output=True, timeout=30,
        )
        return root, result

    def test_success_exits_after_replacing_running_batch_without_pause_or_backup(self):
        root, result = self.run_batch(
            "from pathlib import Path\n"
            "Path('ran.txt').write_text('downloaded updater executed')\n"
            "Path('Update.bat').write_text('@echo off\\nexit /b 99\\n')\n"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((root / "ran.txt").is_file())
        self.assertEqual((root / "Update.py").read_text(), "# previous working updater\n")
        self.assertFalse((root / "Update.py.new").exists())
        self.assertFalse((root / ".luxai_data" / "updater-bootstrap").exists())
        self.assertFalse((root / "backups").exists())
        self.assertEqual(result.stdout.decode("utf-8", errors="replace").splitlines(), [
            "=== Lux AI Updater ===",
            "Inchide Jarvis inainte de actualizare.",
            "Descarc versiunea actuala a programului de actualizare din GitHub...",
        ])

    def test_failed_downloaded_updater_preserves_installed_copy_and_failure_exit(self):
        root, result = self.run_batch("raise SystemExit(7)\n")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual((root / "Update.py").read_text(), "# previous working updater\n")
        self.assertFalse((root / "Update.py.new").exists())
        self.assertFalse((root / ".luxai_data" / "updater-bootstrap").exists())
        self.assertIn(b"NU s-a incheiat", result.stdout)

    def test_invalid_bootstrap_cannot_replace_or_execute_installed_updater(self):
        root, result = self.run_batch("def invalid(:\n")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual((root / "Update.py").read_text(), "# previous working updater\n")
        self.assertFalse((root / "Update.py.new").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
