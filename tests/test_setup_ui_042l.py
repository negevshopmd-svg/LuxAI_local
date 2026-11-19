"""0.4.2l: Update.bat and install_windows.bat show a setup window instead of a bare console."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import Update as updater  # noqa: E402


class EventTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.events = Path(self.temp.name) / "events.jsonl"
        patcher = mock.patch.object(updater, "UI_EVENTS", self.events)
        patcher.start()
        self.addCleanup(patcher.stop)

    def read(self):
        return [json.loads(line) for line in self.events.read_text(encoding="utf-8").splitlines()]

    def test_events_are_json_lines_in_three_languages(self):
        updater.ui_step("libs", "active")
        updater.ui_detail("Verific numpy", "Проверяю numpy", "Checking numpy")
        with mock.patch.object(updater, "_report_console"):
            updater.report("Aplic 3 fișiere...", "Применяю файлов: 3…", "Applying 3 files…")
        events = self.read()
        self.assertEqual(events[0], {"t": "step", "id": "libs", "state": "active"})
        self.assertEqual(events[1]["ru"], "Проверяю numpy")
        self.assertEqual(events[2]["t"], "log")
        self.assertEqual(events[2]["en"], "Applying 3 files…")

    def test_finish_reports_the_result(self):
        updater.ui_finish(True, "Gata", "Готово", "Done")
        self.assertEqual(self.read()[-1], {"t": "done", "ok": True, "message": "Gata", "ru": "Готово", "en": "Done"})

    def test_pip_lines_become_details(self):
        fake = mock.Mock()
        fake.stdout = iter(["Collecting PySide6>=6.7\n", "Requirement already satisfied: numpy in x\n", "\n"])
        fake.wait.return_value = 0
        fake.returncode = 0
        with mock.patch.object(updater.subprocess, "Popen", return_value=fake), \
                mock.patch.object(updater, "_report_console"):
            updater.run_streamed(["pip"], timeout=5)
        details = [event for event in self.read() if event["t"] == "detail"]
        self.assertEqual([d["ru"] for d in details], ["Проверяю PySide6>=6.7", "Проверяю numpy"])

    def test_update_emits_plan_steps_and_result(self):
        with mock.patch.object(updater, "request_json", return_value={"sha": "c" * 40}), \
                mock.patch.object(updater, "_remote_version", return_value="9.9.9"), \
                mock.patch.object(updater, "STATE_FILE", Path(self.temp.name) / "state.json"), \
                mock.patch.object(updater, "close_jarvis", return_value=0) as close, \
                mock.patch.object(updater, "upgrade_dependencies", return_value=True), \
                mock.patch.object(updater, "ensure_local_ai_backend", return_value=True), \
                mock.patch.object(updater, "ensure_ocr", return_value=True), \
                mock.patch.object(updater, "ensure_offline_translator", return_value=True), \
                mock.patch.object(updater, "cleanup_development_files"), \
                mock.patch.object(updater, "cleanup_legacy_backups"), \
                mock.patch.object(updater, "cleanup_retired_fish_local", return_value=True), \
                mock.patch.object(updater, "_report_console"):
            (Path(self.temp.name) / "state.json").write_text(json.dumps({"commit": "c" * 40}))
            self.assertEqual(updater.perform_update(), 0)
        close.assert_called_once()  # a running Jarvis is closed first
        events = self.read()
        self.assertEqual(events[0]["t"], "plan")
        self.assertIn({"t": "plan", "version": "9.9.9", "steps": []}, events)
        states = [(e["id"], e["state"]) for e in events if e["t"] == "step"]
        self.assertIn(("download", "skip"), states)
        self.assertIn(("translator", "done"), states)
        self.assertTrue(events[-1]["ok"])


class LaunchTests(unittest.TestCase):
    def test_no_window_in_tests_or_when_disabled(self):
        with mock.patch.dict(os.environ, {"LUXAI_NO_UI": "1"}), mock.patch.object(updater.subprocess, "Popen") as popen:
            self.assertFalse(updater.start_ui())
        popen.assert_not_called()

    def test_close_jarvis_never_runs_in_test_folders(self):
        with mock.patch.object(updater.subprocess, "run") as run:
            self.assertEqual(updater.close_jarvis(), 0)
        run.assert_not_called()


class ScriptTests(unittest.TestCase):
    def test_window_script_has_bom_and_parses(self):
        script = ROOT / "scripts" / "setup_ui.ps1"
        self.assertTrue(script.read_bytes().startswith(b"\xef\xbb\xbf"))  # PowerShell 5.1 reads Cyrillic only so
        if sys.platform != "win32":
            self.skipTest("Windows PowerShell")
        for name in ("setup_ui.ps1", "install_windows.ps1"):
            command = ("$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
                       f"'{ROOT / 'scripts' / name}',[ref]$null,[ref]$e); $e.Count")
            result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command], capture_output=True, text=True,
                                    timeout=60)
            self.assertEqual(result.stdout.strip(), "0", name)

    def test_window_texts_and_countdown(self):
        source = (ROOT / "scripts" / "setup_ui.ps1").read_text(encoding="utf-8-sig")
        for word in ("Скорость интернета", "Viteza internetului", "Internet speed", "Осталось", "closesIn"):
            self.assertIn(word, source)
        self.assertNotIn("IsMouseOver) { $state.countdown = 60 }", source)  # the countdown never stuck at 59

    def test_batch_files_do_not_pause_in_a_hidden_console(self):
        update = (ROOT / "Update.bat").read_text(encoding="utf-8")
        install = (ROOT / "install_windows.bat").read_text(encoding="utf-8")
        self.assertIn('set "LUXAI_BAT_UI=1"', update)
        self.assertIn('if exist ".luxai_update_ui"', update)
        self.assertIn('if exist "%~dp0logs\\.setup_ui"', install)
        setup = (ROOT / "scripts" / "install_windows.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("Start-SetupWindow", setup)
        self.assertIn("Stop-RunningJarvis", setup)
        self.assertIn("luxai.offline_translate", setup)


class BatchFileTests(unittest.TestCase):
    """0.4.2m: «»  in a LF-only Update.bat made cmd.exe cut commands («echo» → «ho»)."""

    def test_batch_files_are_plain_ascii(self):
        import subprocess as sp
        names = sp.run(["git", "ls-files", "*.bat", "*.cmd"], cwd=ROOT, capture_output=True, text=True).stdout.split()
        self.assertIn("Update.bat", names)
        for name in names:
            data = (ROOT / name).read_bytes()
            self.assertTrue(all(byte < 128 for byte in data), name)

    def test_git_keeps_crlf_for_batch_files(self):
        attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("*.bat text eol=crlf", attributes)

    def test_updater_writes_batch_files_with_crlf(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "src.bat"
            source.write_bytes(b"@echo off\necho hi\r\nexit /b 0\n")
            target = Path(temp) / "out" / "Update.bat"
            updater._atomic_copy(source, target)
            self.assertEqual(target.read_bytes(), b"@echo off\r\necho hi\r\nexit /b 0\r\n")
            other = Path(temp) / "x.py"
            other.write_bytes(b"a\nb\n")
            updater._atomic_copy(other, Path(temp) / "out" / "x.py")
            self.assertEqual((Path(temp) / "out" / "x.py").read_bytes(), b"a\nb\n")  # only batch files change


if __name__ == "__main__":
    unittest.main()
