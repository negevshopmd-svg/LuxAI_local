"""0.4.3a: a Windows audio error (0x8000FFFF «catastrophic failure») no longer stops the captions."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from luxai import loopback_audio as la


class FakeComError(Exception):
    pass


@unittest.skipUnless(sys.platform == "win32", "Windows audio")
class RetryTests(unittest.TestCase):
    def run_capture(self, outcomes, *, app_pid=0, app_name=""):
        """``outcomes``: per attempt, an exception to raise or None (= ran and was stopped)."""
        errors, notices, pids = [], [], []
        capture = la.LoopbackCapture(lambda _a: None, app_pid=app_pid, app_name=app_name,
                                     on_error=errors.append, on_notice=notices.append)
        capture.RETRY_SECONDS = 0.01
        attempts = iter(outcomes)

        def once():
            pids.append(capture.app_pid)
            outcome = next(attempts)
            if outcome is not None:
                raise outcome
            if getattr(capture, "_had_error", False):
                capture._had_error = False
                notices.append("recovered")
        folder = Path(tempfile.mkdtemp())
        with mock.patch.object(capture, "_capture_once", side_effect=once), \
                mock.patch.object(la, "_log_capture_error"), \
                mock.patch.object(la, "app_pid", return_value=777), \
                mock.patch.object(la.Path, "resolve", return_value=folder / "x" / "y"):
            import threading
            worker = threading.Thread(target=capture._run)  # a fresh thread, as in Jarvis (its own COM apartment)
            worker.start()
            worker.join(10)
        return errors, notices, pids

    def test_one_failure_is_retried_quietly(self):
        errors, notices, _ = self.run_capture([FakeComError("catastrophic failure"), None])
        self.assertEqual(errors, [])
        self.assertEqual(notices, ["recovered"])

    def test_a_restarted_program_is_found_again(self):
        _errors, _notices, pids = self.run_capture([FakeComError("x"), None], app_pid=100, app_name="chrome.exe")
        self.assertEqual(pids, [100, 777])

    def test_a_program_that_keeps_failing_falls_back_to_all_sound(self):
        errors, notices, pids = self.run_capture([FakeComError("x")] * 3 + [None], app_pid=100, app_name="chrome.exe")
        self.assertEqual(errors, [])
        self.assertIn("system", notices)
        self.assertEqual(pids[-1], 0)

    def test_only_a_capture_that_keeps_failing_is_shown(self):
        errors, _notices, _ = self.run_capture([FakeComError("x")] * 3 + [None])
        self.assertEqual(len(errors), 1)


if __name__ == "__main__":
    unittest.main()
