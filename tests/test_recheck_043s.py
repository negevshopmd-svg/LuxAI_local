"""0.4.3s: the three findings of the recheck of 0.4.3r (P3)."""
from __future__ import annotations

import datetime as dt
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TZ = dt.timezone.utc


class LongPauseTests(unittest.TestCase):
    """#1: every day of a long pause is looked at; what came due is reported once and never run late."""

    def test_every_day_between_the_two_polls_is_checked(self):
        from luxai.command_triggers import _due_times
        previous = dt.datetime(2026, 11, 21, 11, 0, tzinfo=TZ)
        now = dt.datetime(2026, 11, 24, 12, 0, tzinfo=TZ)
        daily = _due_times({"mode": "daily", "time": "12:00"}, previous, now)
        self.assertEqual([due.day for due in daily], [21, 22, 23, 24])
        once = _due_times({"mode": "once", "time": "09:30", "date": "2026-11-22"}, previous, now)
        self.assertEqual(once, [dt.datetime(2026, 11, 22, 9, 30, tzinfo=TZ)])

    def test_a_very_long_pause_is_bounded(self):
        from luxai.command_triggers import MISSED_LOOKBACK_DAYS, _due_times
        previous = dt.datetime(2025, 1, 1, tzinfo=TZ)
        now = dt.datetime(2026, 11, 24, 12, 0, tzinfo=TZ)
        self.assertEqual(len(_due_times({"mode": "daily", "time": "08:00"}, previous, now)),
                         MISSED_LOOKBACK_DAYS + 1)

    def engine(self, schedule):
        from luxai.command_triggers import CommandTriggerEngine
        registry = mock.Mock()
        registry.entries.return_value = []
        engine = CommandTriggerEngine(registry, mock.Mock(), state_path=None, on_missed=mock.Mock())
        engine._entries = lambda: [{"id": "c1", "title": "Backup", "schedule": schedule}]
        return engine

    def test_after_a_pause_missed_schedules_are_reported_not_run(self):
        engine = self.engine({"mode": "once", "time": "09:30", "date": "2026-11-22"})
        engine._last_poll = dt.datetime(2026, 11, 21, 11, 0, tzinfo=TZ)
        engine.poll(dt.datetime(2026, 11, 24, 12, 0, tzinfo=TZ), apps=set(), headphones=False)
        engine.callback.assert_not_called()  # a late «shut down at 23:00» must never happen
        engine.on_missed.assert_called_once_with([("Backup", dt.datetime(2026, 11, 22, 9, 30, tzinfo=TZ))])
        # the next (continuous) poll neither reports nor runs it again
        engine.poll(dt.datetime(2026, 11, 24, 12, 1, tzinfo=TZ), apps=set(), headphones=False)
        engine.on_missed.assert_called_once()
        engine.callback.assert_not_called()

    def test_the_same_pause_is_not_reported_twice_after_a_restart(self):
        engine = self.engine({"mode": "daily", "time": "12:00"})
        engine._last_poll = dt.datetime(2026, 11, 21, 11, 0, tzinfo=TZ)
        engine.poll(dt.datetime(2026, 11, 24, 12, 30, tzinfo=TZ), apps=set(), headphones=False)
        self.assertEqual(engine.on_missed.call_args.args[0][0][1], dt.datetime(2026, 11, 24, 12, 0, tzinfo=TZ))
        engine._last_poll = dt.datetime(2026, 11, 24, 11, 0, tzinfo=TZ)  # the same stretch seen again
        engine.poll(dt.datetime(2026, 11, 24, 12, 45, tzinfo=TZ), apps=set(), headphones=False)
        engine.on_missed.assert_called_once()

    def test_main_reports_them_in_the_chat(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("on_missed=self._report_missed_schedules", source)


class OcrFirstSetupTests(unittest.TestCase):
    """#2: with the language data missing, the working second candidate is still found after installing it."""

    def test_a_broken_first_candidate_with_missing_languages(self):
        from luxai import ocr_setup
        broken, good = Path("C:/broken/tesseract.exe"), Path("C:/good/tesseract.exe")
        with mock.patch.object(ocr_setup, "_VERIFIED", set()), \
                mock.patch.object(ocr_setup, "tesseract_candidates", return_value=[broken, good]), \
                mock.patch.object(ocr_setup, "language_data_ready", return_value=False), \
                mock.patch.object(ocr_setup, "_identity", side_effect=lambda path: (str(path),)), \
                mock.patch.object(ocr_setup, "_install_languages") as languages, \
                mock.patch.object(ocr_setup, "_install_binary") as install, \
                mock.patch.object(ocr_setup.sys, "platform", "win32"), \
                mock.patch.object(ocr_setup, "verify_tesseract",
                                  side_effect=lambda path: (path == good, "" if path == good else "damaged")):
            self.assertEqual(ocr_setup.ensure_tesseract()[0], good)
        languages.assert_called_once()
        install.assert_not_called()  # a working one exists: nothing is downloaded for the engine

    def test_every_broken_candidate_is_named(self):
        from luxai import ocr_setup
        first, second = Path("C:/a/tesseract.exe"), Path("C:/b/tesseract.exe")
        with mock.patch.object(ocr_setup, "_VERIFIED", set()), \
                mock.patch.object(ocr_setup, "tesseract_candidates", return_value=[first, second]), \
                mock.patch.object(ocr_setup, "language_data_ready", return_value=False), \
                mock.patch.object(ocr_setup, "_install_languages"), \
                mock.patch.object(ocr_setup, "_install_binary", return_value=first), \
                mock.patch.object(ocr_setup.sys, "platform", "win32"), \
                mock.patch.object(ocr_setup, "verify_tesseract", return_value=(False, "damaged")):
            with self.assertRaises(ocr_setup.OCRInstallError) as caught:
                ocr_setup.ensure_tesseract()
        self.assertIn(str(first), str(caught.exception))
        self.assertIn(str(second), str(caught.exception))


class CleanupBindingTests(unittest.TestCase):
    """#3: age and identity come from one lstat, and the move itself is bound to that identity."""

    def setUp(self):
        from luxai import extensions_runtime as runtime
        self.runtime = runtime
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        old = time.time() - 40 * 86400
        self.planned = self.folder / "setup.exe"
        self.planned.write_bytes(b"x" * 100)
        os.utime(self.planned, (old, old))

    def swap(self):
        self.planned.unlink()
        self.planned.write_bytes(b"a new download with the same name")

    def test_plan_reads_age_and_identity_once(self):
        calls = []
        real = os.lstat

        def counting(path, *args, **kwargs):
            calls.append(Path(path).name)
            return real(path, *args, **kwargs)

        with mock.patch("luxai.extensions_runtime.os.lstat", side_effect=counting), \
                mock.patch.object(Path, "stat", side_effect=AssertionError("a second read")):
            steps = self.runtime.plan_cleanup(self.folder, min_age_days=1, installer_trash_days=30)
        self.assertEqual(calls.count("setup.exe"), 1)
        self.assertEqual(len(steps), 1)

    def run_swapped_after_the_last_check(self, trash_days):
        steps = self.runtime.plan_cleanup(self.folder, min_age_days=1, installer_trash_days=trash_days)
        self.swap()
        trashed = []
        with mock.patch.object(self.runtime, "_still_planned_file", return_value=True):  # swapped after it
            result = self.runtime.run_cleanup(steps, trash=trashed.append)
        return result, trashed

    def test_a_file_swapped_after_the_last_check_is_not_trashed(self):
        (moved, sent, errors), trashed = self.run_swapped_after_the_last_check(30)
        self.assertEqual((moved, sent, trashed), (0, 0, []))
        self.assertTrue(errors)
        self.assertEqual(self.planned.read_bytes(), b"a new download with the same name")
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ["setup.exe"])

    def test_a_file_swapped_after_the_last_check_is_not_moved(self):
        (moved, sent, errors), _ = self.run_swapped_after_the_last_check(0)
        self.assertEqual((moved, sent), (0, 0))
        self.assertTrue(errors)
        self.assertEqual(self.planned.read_bytes(), b"a new download with the same name")

    def test_a_refused_recycle_bin_puts_the_file_back(self):
        steps = self.runtime.plan_cleanup(self.folder, min_age_days=1, installer_trash_days=30)

        def refuse(path):
            raise OSError("Recycle Bin unavailable")

        moved, sent, errors = self.runtime.run_cleanup(steps, trash=refuse)
        self.assertEqual((moved, sent), (0, 0))
        self.assertTrue(errors)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ["setup.exe"])

    def test_the_unchanged_file_still_goes_to_the_recycle_bin(self):
        steps = self.runtime.plan_cleanup(self.folder, min_age_days=1, installer_trash_days=30)
        sent = []

        def trash(path):
            sent.append(Path(path).name)
            os.remove(path)

        self.assertEqual(self.runtime.run_cleanup(steps, trash=trash), (0, 1, []))
        self.assertEqual(sent, ["setup.exe"])
        self.assertEqual(list(self.folder.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
