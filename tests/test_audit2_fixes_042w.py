"""0.4.2w: the second audit report (2026-11-20)."""
from __future__ import annotations

import datetime as dt
import json
import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class UpdateAndRecoveryTests(unittest.TestCase):
    def setUp(self):
        import Update
        self.Update = Update
        self.root = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(Update, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_dropped_files_come_back_when_a_later_step_fails(self):
        """#2: removed files are part of the transaction."""
        Update = self.Update
        old = self.root / "luxai" / "old_module.py"
        old.parent.mkdir(parents=True)
        old.write_text("old", encoding="utf-8")
        source = Path(tempfile.mkdtemp())
        (source / "main.py").write_text("new", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            with Update.file_transaction([(source / "main.py", Path("main.py"))], remove=["luxai/old_module.py"]):
                self.assertFalse(old.exists())  # deleted inside the transaction
                raise RuntimeError("state could not be written")
        self.assertEqual(old.read_text(encoding="utf-8"), "old")
        self.assertFalse((self.root / "main.py").exists())

    def test_dropped_files_only_lists_unchanged_files(self):
        Update = self.Update
        kept = self.root / "a.py"
        kept.write_text("x", encoding="utf-8")
        edited = self.root / "b.py"
        edited.write_text("edited by the user", encoding="utf-8")
        import hashlib
        previous = {"a.py": hashlib.sha256(b"x").hexdigest(), "b.py": hashlib.sha256(b"original").hexdigest(),
                    "main.py": "zz"}
        self.assertEqual(Update.dropped_files(previous, [Path("main.py")]), ["a.py"])

    def test_package_restore_removes_added_and_verifies(self):
        """#4: added packages are uninstalled and the result is compared with the snapshot."""
        Update = self.Update
        python = self.root / ".venv" / "Scripts" / "python.exe"
        python.parent.mkdir(parents=True)
        python.write_bytes(b"")
        freezes = iter(["a==1\nnew-pkg==2\n", "a==1\n"])
        calls = []
        with mock.patch.object(Update, "_freeze", side_effect=lambda: next(freezes)), \
                mock.patch.object(Update, "run_streamed", side_effect=lambda cmd, timeout: calls.append(cmd)):
            self.assertTrue(Update.restore_packages("a==1\n"))
        self.assertIn("uninstall", calls[0])
        self.assertIn("new-pkg", calls[0])
        self.assertIn("install", calls[1])

    def test_package_restore_reports_failure_when_the_result_differs(self):
        Update = self.Update
        python = self.root / ".venv" / "Scripts" / "python.exe"
        python.parent.mkdir(parents=True)
        python.write_bytes(b"")
        freezes = iter(["a==2\n", "a==2\n"])
        with mock.patch.object(Update, "_freeze", side_effect=lambda: next(freezes)), \
                mock.patch.object(Update, "run_streamed"):
            self.assertFalse(Update.restore_packages("a==1\n"))

    def test_unchanged_environment_needs_no_restore(self):
        Update = self.Update
        python = self.root / ".venv" / "Scripts" / "python.exe"
        python.parent.mkdir(parents=True)
        python.write_bytes(b"")
        with mock.patch.object(Update, "_freeze", return_value="a==1\nb @ file:///x.whl\n"), \
                mock.patch.object(Update, "run_streamed") as run:
            self.assertTrue(Update.restore_packages("a==1\nb @ file:///x.whl\n"))
        run.assert_not_called()

    def test_snapshot_keeps_direct_url_packages(self):
        lines = self.Update._package_lines("a==1\nb @ file:///C:/x.whl\n-e git+https://x\n")
        self.assertEqual(set(lines), {"a", "b"})

    def test_admin_task_name_comes_from_the_name_file(self):
        Update = self.Update
        (self.root / ".luxai_data").mkdir()
        (self.root / ".luxai_data" / "admin_task.txt").write_text("LuxAI Jarvis (admin) 1234abcd", encoding="ascii")
        self.assertEqual(Update._admin_task_names(), ["LuxAI Jarvis (admin) 1234abcd", "LuxAI Jarvis (admin)"])

    def test_update_bat_has_no_unsigned_route(self):
        """#3: without fetch_updater.py nothing is downloaded or run."""
        bat = (ROOT / "Update.bat").read_text(encoding="ascii")
        self.assertNotIn("curl", bat)
        self.assertNotIn("Update.py.new", bat)
        self.assertIn("fetch_updater.py", bat)

    def test_resume_refuses_while_the_updater_lock_is_held(self):
        """#1: the launcher sees the updater's OS lock (the same one --resume takes)."""
        import sys
        root = Path(tempfile.mkdtemp())
        (root / ".luxai_data").mkdir()
        lock = root / ".luxai_data" / "updater.lock"
        lock.write_bytes(b"\0")
        source = (ROOT / "Update.py").read_text(encoding="utf-8")
        resume = source[source.index('if sys.argv[1:] == ["--resume"]:'):]
        self.assertLess(resume.index("updater_lock()"), resume.index("resume_interrupted_update()"))
        import launch_windows
        with mock.patch.object(launch_windows, "ROOT", root):
            self.assertFalse(launch_windows.update_running())
            with lock.open("r+b") as handle:
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    try:
                        self.assertTrue(launch_windows.update_running())
                    finally:
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    def test_launcher_blocks_start_when_recovery_fails(self):
        import launch_windows
        root = Path(tempfile.mkdtemp())
        (root / ".luxai_update_journal.json").write_text("{}", encoding="utf-8")
        with mock.patch.object(launch_windows, "ROOT", root), \
                mock.patch("subprocess.run", return_value=mock.Mock(returncode=2)):
            self.assertEqual(launch_windows.finish_interrupted_update(), "updating")
        with mock.patch.object(launch_windows, "ROOT", root), \
                mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)):
            self.assertEqual(launch_windows.finish_interrupted_update(), "unfinished")
        with mock.patch.object(launch_windows, "ROOT", root), \
                mock.patch("subprocess.run", return_value=mock.Mock(returncode=0)):
            self.assertEqual(launch_windows.finish_interrupted_update(), "unfinished")  # journal still there

    def test_damaged_language_value_does_not_break_launcher_messages(self):
        import launch_windows
        root = Path(tempfile.mkdtemp())
        (root / "config.json").write_text('{"ui_language": ["ro"]}', encoding="utf-8")
        with mock.patch.object(launch_windows, "ROOT", root):
            self.assertEqual(launch_windows._language_index(), 0)

    def test_direct_main_py_goes_through_the_launcher(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        tail = source[source.rindex('if __name__ == "__main__":'):]
        self.assertIn("launch_windows.main()", tail)

    def test_config_json_and_bytecode_are_not_in_the_release(self):
        """#48: the signed release lists only real program files."""
        manifest = json.loads((ROOT / "release_manifest.json").read_text(encoding="utf-8"))["files"]
        self.assertNotIn("config.json", manifest)
        self.assertFalse([name for name in manifest if name.endswith(".pyc")])


class ConfigValidationTests(unittest.TestCase):
    def test_wrong_values_are_dropped_or_clamped(self):
        import main
        data = {"voice_volume": "abc", "ui_language": ["ru"], "confirmation_timeout": {"x": 1},
                "tts_enabled": "yes", "extensions": [], "online_timeout": 20, "voice_speed": 1.0}
        fixed = main.validate_config(data)
        self.assertEqual(data, {"online_timeout": 35, "voice_speed": 1.0})
        self.assertEqual(set(fixed), {"voice_volume", "ui_language", "confirmation_timeout", "tts_enabled",
                                      "extensions", "online_timeout"})

    def test_good_values_are_untouched(self):
        import main
        data = {"voice_volume": 80, "ui_language": "ro", "voice_speed": 1.2, "confirmation_timeout": 30}
        self.assertEqual(main.validate_config(dict(data)), [])


class TimerParsingTests(unittest.TestCase):
    now = dt.datetime(2026, 11, 20, 10, 0)

    def parse(self, text):
        from luxai.timers import parse_request
        return parse_request(text, self.now)

    def test_negative_reminders_are_refused(self):
        """#9"""
        self.assertIsNone(self.parse("remind me in -5 minutes to call Ana"))
        self.assertIsNone(self.parse("remind me in −5 minutes to call Ana"))
        self.assertIsNone(self.parse("напомни через -5 минут позвонить"))

    def test_reminder_message_never_changes_the_kind(self):
        """#10"""
        request = self.parse("remind me in 5 minutes to check the alarm")
        self.assertEqual((request.kind, request.seconds, request.label), ("timer", 300, "check the alarm"))

    def test_message_before_the_time_is_kept(self):
        request = self.parse("remind me to call Ana in 5 minutes")
        self.assertEqual((request.seconds, request.label), (300, "call Ana"))
        request = self.parse("напомни выключить плиту через 20 минут")
        self.assertEqual((request.seconds, request.label), (1200, "выключить плиту"))
        request = self.parse("remind me to call Ana at 7:30")
        self.assertEqual((request.at.hour, request.at.minute, request.label), (7, 30, "call Ana"))

    def test_hour_separator_h_is_one_clock_time(self):
        request = self.parse("remind me at 07h30 to call Ana")
        self.assertEqual((request.at.hour, request.at.minute, request.label), (7, 30, "call Ana"))

    def test_old_cases_still_work(self):
        self.assertEqual(self.parse("поставь таймер на 10 минут").seconds, 600)
        self.assertEqual(self.parse("remind me in 5 minutes to check the oven for 2 minutes").label,
                         "check the oven for 2 minutes")
        self.assertEqual(self.parse("отмени все таймеры").kind, "cancel")

    def test_cancel_all_writes_once(self):
        """#37"""
        from luxai.timers import TimerStore, new_timer
        store = TimerStore(Path(tempfile.mkdtemp()) / "t.json")
        ids = [store.add(new_timer("timer", time.time() + 60 + i, "", 60)).id for i in range(5)]
        with mock.patch.object(store, "save", wraps=store.save) as save:
            self.assertEqual(store.remove_many(ids), 5)
        save.assert_called_once()
        self.assertEqual(store.items, [])


class SnoozeTests(unittest.TestCase):
    def runtime(self):
        from PySide6.QtWidgets import QApplication
        from luxai import extensions_runtime as rt
        QApplication.instance() or QApplication([])
        host = mock.Mock()
        host.cfg = {"language": "ru"}
        runtime = rt.ExtensionsRuntime(host)
        self.addCleanup(runtime.deleteLater)
        return runtime

    def test_failed_snooze_keeps_the_alarm_window(self):
        """#18"""
        runtime = self.runtime()
        dialog = mock.Mock()
        other = mock.Mock()
        timer = SimpleNamespace(kind="alarm", label="", duration=0)
        runtime._ringing = [(timer, dialog), (SimpleNamespace(), other)]
        notices = []
        runtime.notice.connect(notices.append)
        with mock.patch.object(runtime.timer_store, "add", side_effect=OSError("disk")):
            self.assertFalse(runtime.snooze(timer, dialog))
        dialog.close.assert_not_called()
        self.assertTrue(notices)
        with mock.patch.object(runtime.timer_store, "add"):
            self.assertTrue(runtime.snooze(timer, dialog))
        dialog.close.assert_called_once()
        other.close.assert_not_called()  # the other ringing alarm stays
        self.assertEqual(len(runtime._ringing), 1)


class SpeechQueueTests(unittest.TestCase):
    def test_long_answer_is_one_queue_item_and_fully_spoken(self):
        """#7"""
        import main
        worker = SimpleNamespace(_closed=False, _speech_queue=queue.Queue(maxsize=8), _speech_generation=0,
                                 cfg={"tts_enabled": False}, tts_played=mock.Mock())
        worker._queue_speech_piece = lambda text, language: main.MainWindow._queue_speech_piece(worker, text, language)
        text = " ".join(f"Sentence number {i} is here and it is long enough to matter." for i in range(150))
        with mock.patch.object(main, "voice_output_playing", threading.Event()):
            main.MainWindow._queue_speech(worker, text, "en")
        self.assertEqual(worker._speech_queue.qsize(), 1)
        worker._speech_queue.put(None)
        spoken = []
        with mock.patch.object(main, "speak", side_effect=lambda piece, **k: spoken.append(piece) or True), \
                mock.patch("luxai.voices.prefetch") as prefetch:
            main.MainWindow._speech_loop(worker)
        self.assertGreater(len(spoken), 8)
        self.assertTrue(spoken[0].startswith("Sentence number 0"))
        self.assertEqual(prefetch.call_count, len(spoken) - 1)  # one piece ahead only


class ConverterTests(unittest.TestCase):
    def test_refused_conversion_leaves_no_empty_file(self):
        """#11"""
        from luxai import converter
        folder = Path(tempfile.mkdtemp())
        bad = folder / "bad.wav"
        bad.write_bytes(b"RIFF\0\0\0\0WAVEjunkjunkjunk")
        with self.assertRaises(Exception):
            converter.audio_convert(bad, "mp3")
        self.assertEqual(list(folder.glob("*.mp3")), [])

    def test_progress_is_reported_once_per_percent(self):
        """#29"""
        from luxai.converter import _throttled
        calls = []
        report = _throttled(calls.append)
        for step in range(1000):
            report(step / 1000)
        self.assertEqual(len(calls), 100)


class ClipboardTests(unittest.TestCase):
    def test_long_texts_with_the_same_beginning_stay_two_items(self):
        """#31"""
        from luxai.clipboard_store import MAX_TEXT, ClipboardHistory
        history = ClipboardHistory()
        prefix = "a" * (MAX_TEXT + 10)
        history.add_text(prefix + "one")
        history.add_text(prefix + "two")
        self.assertEqual(len(history.items), 2)
        self.assertTrue(history.items[0]["truncated"])

    def test_html_fragment_is_cut_by_the_header_offsets(self):
        from luxai.clipboard_native import html_fragment
        body = b"<html><b>x</b></html>"
        header = b"Version:0.9\r\nStartHTML:0000000105\r\nEndHTML:0000000126\r\n"
        raw = header.ljust(105, b" ") + body
        self.assertEqual(html_fragment(raw), "<html><b>x</b></html>")

    def test_dib_becomes_a_bmp_file(self):
        import struct
        from luxai.clipboard_native import dib_to_bmp
        header = struct.pack("<IiiHHIIiiII", 40, 2, 2, 1, 32, 0, 16, 0, 0, 0, 0)
        bmp = dib_to_bmp(header + b"\0" * 16)
        self.assertEqual(bmp[:2], b"BM")
        self.assertEqual(struct.unpack_from("<I", bmp, 10)[0], 54)


class BackgroundWorkerTests(unittest.TestCase):
    def test_latest_worker_runs_in_order_and_coalesces(self):
        """#15/#16: one thread, a waiting job is replaced by the newer one."""
        from luxai.background import LatestWorker
        worker = LatestWorker("test")
        gate = threading.Event()
        done = []
        worker.submit(lambda: (gate.wait(5), done.append(1)))
        time.sleep(0.05)
        worker.submit(lambda: done.append(2))
        worker.submit(lambda: done.append(3))
        gate.set()
        self.assertTrue(worker.wait(5))
        self.assertEqual(done, [1, 3])

    def test_serial_queue_keeps_every_job_in_order(self):
        from luxai.background import SerialQueue
        jobs = SerialQueue("test", limit=50)
        done = []
        finished = threading.Event()
        for index in range(20):
            self.assertTrue(jobs.submit(lambda i=index: done.append(i)))
        jobs.submit(finished.set)
        self.assertTrue(finished.wait(5))
        self.assertEqual(done, list(range(20)))


class PasteTargetTests(unittest.TestCase):
    def test_paste_is_refused_when_the_window_changed(self):
        """#6"""
        from PySide6.QtWidgets import QApplication
        from luxai import extensions_runtime as rt
        app = QApplication.instance() or QApplication([])
        host = mock.Mock()
        host.cfg = {"language": "en"}
        runtime = rt.ExtensionsRuntime(host)
        self.addCleanup(runtime.deleteLater)
        notices = []
        runtime.notice.connect(notices.append)
        with mock.patch.object(rt, "_set_foreground", return_value=True), \
                mock.patch.object(rt, "_foreground_window", return_value=999), \
                mock.patch.object(rt, "_send_paste") as paste:
            runtime._paste_into(123)
            end = time.time() + 2
            while time.time() < end and not notices:
                app.processEvents()
                time.sleep(0.01)
        paste.assert_not_called()
        self.assertTrue(notices)

    def test_failed_activation_never_pastes(self):
        from PySide6.QtWidgets import QApplication
        from luxai import extensions_runtime as rt
        app = QApplication.instance() or QApplication([])
        host = mock.Mock()
        host.cfg = {"language": "en"}
        runtime = rt.ExtensionsRuntime(host)
        self.addCleanup(runtime.deleteLater)
        with mock.patch.object(rt, "_set_foreground", return_value=False), \
                mock.patch.object(rt, "_send_paste") as paste:
            runtime._paste_into(123)
            end = time.time() + 0.6
            while time.time() < end:
                app.processEvents()
                time.sleep(0.01)
        paste.assert_not_called()


class TelegramGenerationTests(unittest.TestCase):
    def test_signals_of_an_old_bot_are_ignored(self):
        """#40"""
        from PySide6.QtWidgets import QApplication
        from luxai import extensions_runtime as rt
        QApplication.instance() or QApplication([])
        host = mock.Mock()
        host.cfg = {"language": "en"}
        runtime = rt.ExtensionsRuntime(host)
        self.addCleanup(runtime.deleteLater)
        runtime._bot_generation = 5
        states = []
        runtime.pc_status_changed.connect(lambda state, details: states.append(state))
        runtime._on_pc_status("connected", {"_bot_gen": 4})
        self.assertEqual(states, [])
        runtime._on_pc_status("connected", {"_bot_gen": 5})
        self.assertEqual(states, ["connected"])


class TranslatorSignatureTests(unittest.TestCase):
    def test_a_repaired_tokenizer_changes_the_signature(self):
        """#30"""
        from luxai import offline_translate as ot
        folder = Path(tempfile.mkdtemp())
        for name in ot.SHA256:
            (folder / name).write_bytes(b"x")
        with mock.patch.object(ot, "model_dir", return_value=folder):
            before = ot._signature()
            time.sleep(0.02)
            (folder / "tokenizer.json").write_bytes(b"repaired!")
            self.assertNotEqual(before, ot._signature())


class CommandTriggerCacheTests(unittest.TestCase):
    def test_checked_entries_are_reused_until_the_library_changes(self):
        """#26"""
        from luxai.command_triggers import CommandTriggerEngine
        registry = mock.Mock()
        registry.fingerprint.return_value = (1, 1, 0, 0, 0, 0)
        registry.entries.return_value = []
        engine = CommandTriggerEngine.__new__(CommandTriggerEngine)
        engine.registry = registry
        engine._entries()
        engine._entries()
        self.assertEqual(registry.entries.call_count, 1)
        registry.fingerprint.return_value = (2, 1, 0, 0, 0, 0)
        engine._entries()
        self.assertEqual(registry.entries.call_count, 2)
        engine._entries(fresh=True)  # a pressed hotkey always reads the library
        self.assertEqual(registry.entries.call_count, 3)


if __name__ == "__main__":
    unittest.main()
