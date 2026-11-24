"""0.4.3t: a llama-cpp-python wheel that imports but does not START on this processor.

Measured on the user's Ryzen 7 5800X: 0.3.38 (installed by the update of 2026-11-24) imports fine and stops
with 0xc000001d (illegal instruction) in llama_backend_init; 0.3.36 starts and the Qwen3-8B model answers in
12 s. The import-only check said «verified», so every local AI request failed.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from luxai import local_ai_setup


class CpuCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        for name, value in (("LOG_FILE", self.folder / "install.log"),
                            ("BAD_VERSIONS_FILE", self.folder / "bad.json")):
            patcher = mock.patch.object(local_ai_setup, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_check_starts_the_engine(self):
        self.assertIn("llama_backend_init()", local_ai_setup.BACKEND_IMPORT)

    def test_a_wheel_that_does_not_start_is_replaced_by_an_older_one(self):
        installed = ["0.3.38"]
        pip_calls = []

        def run(command, **kwargs):
            if "-c" in command:  # the installed-version probe
                return subprocess.CompletedProcess(command, 0, stdout=installed[0] + "\n")
            pip_calls.append(command[-1])
            if any(",!=0.3.38" in part for part in command):
                installed[0] = "0.3.36"
            return subprocess.CompletedProcess(command, 0)

        def starts(_python):
            return installed[0] == "0.3.36"

        with mock.patch.object(local_ai_setup, "check_backend", side_effect=starts), \
                mock.patch("luxai.local_ai_setup.subprocess.run", side_effect=run):
            self.assertTrue(local_ai_setup.ensure_backend("python.exe"))
        self.assertEqual(pip_calls, ["llama-cpp-python>=0.3.20", "llama-cpp-python>=0.3.20,!=0.3.38"])
        self.assertEqual(local_ai_setup.bad_versions(), ["0.3.38"])
        log = (self.folder / "install.log").read_text(encoding="utf-8")
        self.assertIn("BROKEN on this PC: llama-cpp-python 0.3.38", log)
        self.assertIn("SUCCESS: newest compatible backend installed and its engine started", log)

    def test_known_broken_versions_are_excluded_from_every_upgrade(self):
        local_ai_setup._remember_bad_version("0.3.38")
        local_ai_setup._remember_bad_version("0.3.39")
        local_ai_setup._remember_bad_version("0.3.38")  # once
        self.assertEqual(local_ai_setup.requirement(), "llama-cpp-python>=0.3.20,!=0.3.39,!=0.3.38")

    def test_no_endless_loop_when_nothing_starts(self):
        def run(command, **kwargs):
            if "-c" in command:
                return subprocess.CompletedProcess(command, 0, stdout="0.3.36\n")
            return subprocess.CompletedProcess(command, 0)

        local_ai_setup._remember_bad_version("0.3.36")
        with mock.patch.object(local_ai_setup, "check_backend", return_value=False), \
                mock.patch("luxai.local_ai_setup.subprocess.run", side_effect=run) as runner:
            self.assertFalse(local_ai_setup.ensure_backend("python.exe"))
        pip = [call for call in runner.call_args_list if "-c" not in call.args[0]]
        self.assertEqual(len(pip), 1)

    def test_a_damaged_bad_versions_file_is_ignored(self):
        local_ai_setup.BAD_VERSIONS_FILE.write_text("{not json", encoding="utf-8")
        self.assertEqual(local_ai_setup.bad_versions(), [])
        local_ai_setup.BAD_VERSIONS_FILE.write_text('["0.3.38", 7, "bad version!"]', encoding="utf-8")
        self.assertEqual(local_ai_setup.bad_versions(), ["0.3.38"])


if __name__ == "__main__":
    unittest.main()
