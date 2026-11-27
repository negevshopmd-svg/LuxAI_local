"""0.4.3z: the update window counts only what the updater downloads, not the whole network card.

A Steam download running during an update made the window say «Downloaded 2.12 GB» for a ~3 MB update.
"""
from __future__ import annotations

import io
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
from luxai import download_meter as meter  # noqa: E402


class EventsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.events = Path(self.temp.name) / "events.jsonl"
        patcher = mock.patch.object(updater, "UI_EVENTS", self.events)
        patcher.start()
        self.addCleanup(patcher.stop)

    def read(self):
        if not self.events.exists():
            return []
        return [json.loads(line) for line in self.events.read_text(encoding="utf-8").splitlines()]

    def got(self):
        return sum(event["bytes"] for event in self.read() if event["t"] == "got")

    def test_the_archive_download_counts_its_own_bytes(self):
        class Response(io.BytesIO):
            headers = {"Content-Length": str(700_000)}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False
        with mock.patch.object(updater.urllib.request, "urlopen", return_value=Response(b"x" * 700_000)):
            updater.download("https://example.invalid/a.zip", Path(self.temp.name) / "a.zip")
        self.assertEqual(self.got(), 700_000)

    def test_helper_markers_and_pip_downloads_are_counted_but_cached_files_are_not(self):
        fake = mock.Mock()
        fake.stdout = iter(["Collecting llama-cpp-python\n",
                            "  Downloading llama_cpp_python-0.3.36-cp311-cp311-win_amd64.whl (6.9 MB)\n",
                            "Using cached winrt_runtime-4.2.1-cp311-cp311-win_amd64.whl (253 kB)\n",
                            "LUXAI_GOT 1048576\n", "Installed\n"])
        fake.wait.return_value = 0
        fake.returncode = 0
        with mock.patch.object(updater.subprocess, "Popen", return_value=fake) as popen, \
                mock.patch.object(updater, "_report_console"):
            updater.run_streamed(["pip"], timeout=5)
        self.assertEqual(self.got(), 6_900_000 + 1_048_576)
        logs = [event.get("text") for event in self.read() if event["t"] == "log"]
        self.assertNotIn("LUXAI_GOT 1048576", logs)  # a count for the window, not a log line
        self.assertEqual(popen.call_args.kwargs["env"][updater.METER_ENV], "1")  # helpers know they may report


class MeterTests(unittest.TestCase):
    def test_pip_sizes(self):
        text = ("  Downloading a-1.whl (6.9 MB)\nUsing cached b-1.whl (253 kB)\n"
                "Downloading c-1.tar.gz (12 kB)\n  Downloading d-1.whl (1,5 GB)\n")
        self.assertEqual(meter.pip_bytes(text), 6_900_000 + 12_000 + 1_500_000_000)
        self.assertEqual(meter.pip_bytes(""), 0)

    def test_the_updater_and_the_helpers_agree_on_the_marker_and_pip_lines(self):
        for line in ("LUXAI_GOT 42", "  Downloading x-1.whl (3.5 MB)", "Using cached y-1.whl (2 MB)", "LUXAI_GOT -1"):
            ours = meter.parse_line(line)
            if ours is not None:
                self.assertEqual(updater.downloaded_in_line(line), (ours, True))
            else:
                self.assertEqual(updater.downloaded_in_line(line)[0], meter.pip_bytes(line))

    def test_helpers_are_silent_unless_the_updater_listens(self):
        with mock.patch.dict(os.environ, {meter.ENV: ""}), mock.patch("builtins.print") as printed:
            meter.report(100)
        printed.assert_not_called()
        with mock.patch.dict(os.environ, {meter.ENV: "1"}), mock.patch("builtins.print") as printed:
            meter.report(100)
            meter.report(0)
        printed.assert_called_once_with("LUXAI_GOT 100", flush=True)

    def test_local_ai_counts_what_pip_wrote_to_its_log_after_it_started(self):
        from luxai import local_ai_setup as setup
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "local_ai.log"
            log.write_text("  Downloading old-1.whl (99 MB)\n", encoding="utf-8")  # an earlier run
            start = log.stat().st_size
            with log.open("a", encoding="utf-8") as handle:
                handle.write("  Downloading llama_cpp_python-0.3.36.whl (6.9 MB)\n")
            with mock.patch.object(setup, "LOG_FILE", log), mock.patch("luxai.download_meter.report") as reported:
                setup._report_pip_downloads(start)
        reported.assert_called_once_with(6_900_000)


class WindowTests(unittest.TestCase):
    def test_the_window_counts_got_events_not_the_network_card(self):
        source = (ROOT / "scripts" / "setup_ui.ps1").read_text(encoding="utf-8-sig")
        self.assertNotIn("GetIPStatistics", source)
        self.assertIn("'got' { $state.got +=", source)
        # Counting starts at zero: bytes reported before the first speed sample are not lost (seen live).
        self.assertIn("lastRx = 0.0;", source)

    @unittest.skipUnless(sys.platform == "win32", "PowerShell window script")
    def test_the_window_script_parses(self):
        command = ("$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
                   f"'{ROOT / 'scripts' / 'setup_ui.ps1'}',[ref]$null,[ref]$e); $e.Count")
        result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command], capture_output=True, text=True,
                                timeout=60)
        self.assertEqual(result.stdout.strip(), "0")


if __name__ == "__main__":
    unittest.main()
