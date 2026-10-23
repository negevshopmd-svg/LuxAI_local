"""Safe llama-cpp wheel installation and automatic setup/update wiring."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from luxai import local_ai_setup


class LocalAISetupTests(unittest.TestCase):
    def test_skips_pip_if_native_import_already_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.object(local_ai_setup, "LOG_FILE", Path(tmp) / "install.log"),
                mock.patch.object(local_ai_setup, "check_backend", return_value=True),
                mock.patch("luxai.local_ai_setup.subprocess.run") as runner,
            ):
                self.assertTrue(local_ai_setup.install_backend("some-python.exe"))
                runner.assert_not_called()

    def test_binary_wheels_only_and_real_import_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.object(local_ai_setup, "LOG_FILE", Path(tmp) / "install.log"),
                mock.patch.object(local_ai_setup, "check_backend", side_effect=[False, True]),
                mock.patch("luxai.local_ai_setup.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as runner,
            ):
                self.assertTrue(local_ai_setup.install_backend("some-python.exe"))
                command = runner.call_args.args[0]
                self.assertIn("--only-binary=:all:", command)
                self.assertIn("--extra-index-url", command)
                self.assertIn("llama-cpp-python>=0.3.20", command)
                self.assertTrue((Path(tmp) / "install.log").exists())

    def test_reports_failure_without_building_from_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.object(local_ai_setup, "LOG_FILE", Path(tmp) / "install.log"),
                mock.patch.object(local_ai_setup, "check_backend", return_value=False),
                mock.patch("luxai.local_ai_setup.subprocess.run", return_value=subprocess.CompletedProcess([], 1)),
            ):
                self.assertFalse(local_ai_setup.install_backend("some-python.exe"))
                log = (Path(tmp) / "install.log").read_text(encoding="utf-8")
                self.assertIn("FAILED", log)

    def test_windows_setup_and_updater_both_install_optional_gguf_engine(self):
        root = Path(__file__).resolve().parents[1]
        powershell = (root / "scripts" / "install_windows.ps1").read_text(encoding="utf-8")
        updater = (root / "Update.py").read_text(encoding="utf-8")
        wrapper = (root / "install_local_ai.bat").read_text(encoding="utf-8")
        self.assertIn("'luxai.local_ai_setup'", powershell)
        self.assertIn("def ensure_local_ai_backend()", updater)
        self.assertIn("ensure_local_ai_backend()", updater.split("if current_sha == latest_sha:", 1)[1])
        self.assertIn("ensure_local_ai_backend()", updater.split("# Prepare Tesseract OCR", 1)[0].split("# Refresh the optional llama.cpp backend", 1)[1])
        self.assertIn("luxai.local_ai_setup", wrapper)


if __name__ == "__main__":
    unittest.main()
