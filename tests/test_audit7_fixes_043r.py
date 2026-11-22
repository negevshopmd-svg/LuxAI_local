"""0.4.3r: the seventh audit report (47 findings, 0.4.3q). One test (or more) per finding, named by number.

Probed for real where it can be done on this PC: a slow local HTTP server (#6), a real SQLite notification
database (#18), real files for the cleanup race (#19) and the attachment copy (#20), real PyAV video (#21,
#22), the page hook in Node (#31, #32), the same OS lock taken by PowerShell and Python (#40).
"""
from __future__ import annotations

import datetime as dt
import http.server
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LUXAI_NO_DOWNLOADS", "1")

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from luxai import extensions_catalog as catalog  # noqa: E402
from luxai import extensions_runtime as runtime  # noqa: E402


class _Host:
    def __init__(self):
        self.cfg = {"ui_language": "ru", "language": "ru", "tts_enabled": True}
        self.tray_icon = None
        self.spoken = []
        self.online_planner = None

    def _queue_speech(self, text, language):
        self.spoken.append((text, language))

    def stop_speaking(self):
        pass

    def save_extensions_meta(self):
        return True


class RuntimeCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, host=None, **extensions):
        engine = runtime.ExtensionsRuntime(host or _Host())
        engine.apply(catalog.normalize_state(extensions))

        def dispose():
            engine.stop()
            engine.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        self.addCleanup(dispose)
        return engine


# ---------------------------------------------------------------- P2
class TranslateParserTests(unittest.TestCase):
    def test_01_words_that_only_start_like_a_label_are_kept(self):
        from luxai import chat_translate as ct
        self.assertEqual(ct.parse_request("translate thistle"), ("thistle", "", "en"))
        self.assertEqual(ct.parse_request("translate This is a test"), ("This is a test", "", "en"))
        self.assertEqual(ct.parse_request("tradu textul nostru")[0], "textul nostru")
        self.assertEqual(ct.parse_request("translate: this: hello")[0], "hello")  # an explicit label goes
        self.assertEqual(ct.parse_request("переведи это «Good night»")[0], "Good night")
        self.assertEqual(ct.parse_request("tradu-mi asta")[0], "")  # the label alone: nothing to translate


class MidnightReminderTests(unittest.TestCase):
    def test_02_a_reminder_just_before_midnight_fires_when_the_poll_crosses_it(self):
        from luxai.command_triggers import _due_times
        tz = dt.timezone.utc
        previous = dt.datetime(2026, 11, 21, 23, 58, 55, tzinfo=tz)
        now = dt.datetime(2026, 11, 22, 0, 0, 5, tzinfo=tz)
        self.assertEqual(_due_times({"mode": "daily", "time": "23:59"}, previous, now),
                         [dt.datetime(2026, 11, 21, 23, 59, tzinfo=tz)])
        self.assertEqual(_due_times({"mode": "daily", "time": "00:00"}, previous, now),
                         [dt.datetime(2026, 11, 22, 0, 0, tzinfo=tz)])
        once = {"mode": "once", "time": "23:59", "date": "2026-11-21"}
        self.assertEqual(len(_due_times(once, previous, now)), 1)
        weekly_other_day = {"mode": "weekly", "time": "23:59", "weekdays": [now.weekday()]}
        self.assertEqual(_due_times(weekly_other_day, previous, now), [])  # it belongs to yesterday

    def test_02_engine_dispatches_across_midnight(self):
        from luxai.command_triggers import CommandTriggerEngine
        engine = CommandTriggerEngine.__new__(CommandTriggerEngine)
        fired = []
        engine._entries = lambda: [{"id": "c1", "schedule": {"mode": "daily", "time": "23:59"}}]
        engine._dispatch = lambda entry: fired.append(entry["id"])
        engine._fired = {}
        engine._remember = lambda key, now: engine._fired.__setitem__(key, now)
        engine._apps = engine._headphones = None
        tz = dt.timezone.utc
        engine._last_poll = dt.datetime(2026, 11, 21, 23, 58, 55, tzinfo=tz)
        engine.poll(dt.datetime(2026, 11, 22, 0, 0, 5, tzinfo=tz))
        self.assertEqual(fired, ["c1"])


class DuplicatePhraseTests(unittest.TestCase):
    def test_03_a_second_command_with_the_same_phrase_is_reported(self):
        from luxai.command_registry import CommandRegistry
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        registry = CommandRegistry(folder / "commands.json")
        base = {"action": "open_app", "target": "telegram", "enabled": True}
        first = registry.save_command(dict(base, title="First", phrases=["open my page"]))
        second = registry.save_command(dict(base, title="Second", phrases=["Open my page!", "other"]))
        third = registry.save_command(dict(base, title="Third", phrases=["something else"]))
        self.assertEqual(registry.phrase_conflicts(second["id"]), ["First"])
        self.assertEqual(registry.phrase_conflicts(first["id"]), ["Second"])
        self.assertEqual(registry.phrase_conflicts(third["id"]), [])


class CommandOutcomeTests(unittest.TestCase):
    def test_04_only_jarvis_own_cancel_reply_clears_the_chain(self):
        from luxai.command_outcome import is_cancelled
        self.assertFalse(is_cancelled("This order was cancelled last week"))
        self.assertFalse(is_cancelled("Заказ отменён вчера, но деньги вернули."))
        self.assertTrue(is_cancelled("Action cancelled."))
        self.assertTrue(is_cancelled("Действие отменено."))
        self.assertTrue(is_cancelled("Ошибка: Команда отменена."))

    def test_05_no_errors_found_is_a_success(self):
        from luxai.command_outcome import is_failed
        self.assertFalse(is_failed("No errors found."))
        self.assertFalse(is_failed("Ошибок не найдено."))
        self.assertTrue(is_failed("Error: disk full"))
        self.assertTrue(is_failed("Не удалось открыть файл."))
        self.assertTrue(is_failed("Nu am putut porni aplicația."))

    def test_04_05_main_uses_the_structured_check(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertNotIn('("отмен", "anulat", "cancelled")', source)
        self.assertNotIn('"ошибк", "не удалось", "отмен", "error", "failed", "eroare"', source)


class GroupedNotificationTests(RuntimeCase):
    def items(self):
        return [{"app": "Telegram", "texts": ["https://evil.example/x 123456", "body one"]},
                {"app": "Telegram", "texts": ["Mom", "body two"]}]

    def test_07_grouped_senders_go_through_the_link_and_code_filters(self):
        engine = self.make(notification_reader={"enabled": True, "settings": {"group": True}})
        text = engine.notification_texts(self.items())[0]
        self.assertNotIn("evil.example", text)
        self.assertNotIn("123456", text)
        self.assertIn("Mom", text)

    def test_08_links_kept_when_the_user_wants_them(self):
        from luxai.notifications import compose
        text = compose("Mail", ["Ana", "see https://example.org/page"], skip_links=False, language="en")
        self.assertIn("https://example.org/page", text)
        text = compose("Mail", ["Ana", "see https://example.org/page"], skip_links=True, language="en")
        self.assertNotIn("example.org", text)

    def test_09_a_translation_finishing_after_turn_off_is_not_read(self):
        engine = self.make(notification_reader={"enabled": True})
        session = engine._notif_session
        engine.state = catalog.normalize_state({"notification_reader": {"enabled": False}})
        engine._apply_notifications()
        engine._notif_ready.emit("Telegram: late text", session)
        QApplication.processEvents()
        self.assertNotIn("Telegram: late text", list(engine.notification_memory))
        self.assertEqual(engine.host.spoken, [])

    def test_10_only_the_five_read_are_consumed(self):
        engine = self.make(notification_reader={"enabled": True})
        engine.missed_notifications.extend(f"App: message {n}" for n in range(8))
        first = engine.handle_notification_request("что пришло")
        self.assertIn("message 0", first)
        self.assertIn("message 4", first)
        self.assertNotIn("message 5", first)
        self.assertEqual(list(engine.missed_notifications), [f"App: message {n}" for n in range(5, 8)])
        second = engine.handle_notification_request("что пришло")
        self.assertIn("message 7", second)
        self.assertEqual(list(engine.missed_notifications), [])

    def test_11_null_notification_apps_does_not_break_turning_on(self):
        host = _Host()
        host.cfg["extensions_meta"] = {"notification_apps": None}
        with mock.patch("luxai.notifications.NotificationWatcher.prime", return_value=True):
            engine = self.make(host, notification_reader={"enabled": True})
        engine._remember_app("Signal")
        self.assertEqual(host.cfg["extensions_meta"]["notification_apps"], ["Signal"])
        host.cfg["extensions_meta"] = None
        engine._remember_app("Viber")
        self.assertIn("Viber", host.cfg["extensions_meta"]["notification_apps"])

    def test_11_config_validation_drops_a_wrong_nested_list(self):
        import main
        data = {"extensions_meta": {"notification_apps": None, "captions_position": [1, 2]}}
        fixed = main.validate_config(data)
        self.assertIn("extensions_meta.notification_apps", fixed)
        self.assertEqual(data["extensions_meta"], {"captions_position": [1, 2]})


class TimerSaveTests(RuntimeCase):
    def test_13_a_failed_save_of_the_cancel_button_stays_inside_the_slot(self):
        engine = self.make(timers={"enabled": True})
        notices = []
        engine.notice.connect(notices.append)
        with mock.patch.object(engine.timer_store, "remove", side_effect=OSError("locked")):
            self.assertFalse(engine.cancel_timer("t1"))
        self.assertTrue(notices)


class ClipboardTests(RuntimeCase):
    def test_15_a_pinned_saved_item_stays_pinned(self):
        engine = self.make(clipboard_history={"enabled": True, "settings": {"persist": False}})
        engine.clip_history.items = [{"id": 1, "key": "k", "kind": "text", "text": "a", "pinned": False}]
        loaded = SimpleNamespace(items=[{"id": 9, "key": "k", "kind": "text", "text": "a", "pinned": True}])
        engine._on_clip_history_loaded(loaded, engine._clip_load_generation)
        self.assertEqual(len(engine.clip_history.items), 1)
        self.assertTrue(engine.clip_history.items[0]["pinned"])

    def test_16_a_picture_encoded_before_clear_does_not_come_back(self):
        engine = self.make(clipboard_history={"enabled": True, "settings": {"persist": False}})
        generation = engine._clip_clear_generation
        engine.clear_clipboard()
        with mock.patch.object(engine.clip_history, "add_image") as add:
            engine._on_clip_image_ready(b"png", b"thumb", 10, 10, "", generation)
        add.assert_not_called()

    def test_17_turning_persistence_off_removes_the_saved_file_now(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        saved = folder / "clipboard.bin"
        saved.write_bytes(b"encrypted history")
        with mock.patch("luxai.clipboard_store.history_file", return_value=saved):
            engine = self.make(clipboard_history={"enabled": True, "settings": {"persist": True}})
            engine.state = catalog.normalize_state({"clipboard_history": {"enabled": True,
                                                                          "settings": {"persist": False}}})
            engine.apply(engine.state)
            self.assertTrue(engine._clip_saver.wait(5))
        self.assertFalse(saved.exists())


class PcControlTests(RuntimeCase):
    def test_29_autostart_off_is_kept_by_every_later_apply(self):
        bots = []

        class Bot:
            def __init__(self, *args):
                self.running = True
                bots.append(self)

            def start(self):
                pass

            def stop(self):
                self.running = False

        with mock.patch("luxai.telegram_control.TelegramBot", Bot), \
                mock.patch.object(runtime.ExtensionsRuntime, "_token", return_value="123:abc"):
            engine = self.make(pc_control={"enabled": True, "settings": {"autostart": False}})
            engine._apply_pc_control()  # another plugin's setting changed: still not started
            self.assertEqual(bots, [])
            engine.state["pc_control"]["enabled"] = False
            engine._apply_pc_control()
            engine.state["pc_control"]["enabled"] = True
            engine._apply_pc_control()  # the user turned it on: now it starts
            self.assertEqual(len(bots), 1)

    def test_30_an_older_token_check_cannot_overwrite_the_newer_one(self):
        engine = self.make()
        states = []
        engine.pc_status_changed.connect(lambda state, details: states.append(state))
        engine._pc_check_generation = 2
        engine._on_pc_status("error", {"message": "old token", "_check_gen": 1})
        engine._on_pc_status("checked", {"_check_gen": 2})
        self.assertEqual(states, ["checked"])


class CaptionGenerationTests(RuntimeCase):
    def test_37_a_line_of_a_stopped_engine_is_dropped(self):
        engine = self.make()
        shown = []
        with mock.patch.object(engine, "_on_cap_final", side_effect=shown.append):
            old = engine._cap_engine_gen
            engine._stop_caption_audio()
            engine._cap_engine_final.emit("old source line", old)
            engine._cap_engine_final.emit("current line", engine._cap_engine_gen)
            QApplication.processEvents()
        self.assertEqual(shown, ["current line"])


class LiveCaptionTests(unittest.TestCase):
    def test_34_waiting_audio_is_bounded(self):
        import numpy as np
        from luxai import live_captions as lc
        segmenter = lc.PhraseSegmenter()
        tone = (0.1 * np.sin(np.arange(lc.SAMPLE_RATE) * 0.05)).astype(np.float32)
        for _ in range(30):  # 30 s of speech while recognition is busy
            segmenter.feed(tone)
        self.assertLessEqual(segmenter.seconds, lc.MAX_BACKLOG_SECONDS)
        self.assertGreater(segmenter.dropped_seconds, 20)

    def test_36_two_lines_with_the_same_words_keep_their_own_progress(self):
        from luxai.live_captions import CaptionBar
        QApplication.instance() or QApplication([])
        bar = CaptionBar()
        self.addCleanup(bar.deleteLater)
        bar.show_original = True
        bar.lines = [("Yes indeed", ""), ("Yes indeed", "")]
        bar.line_reveal = [(10, 0), (3, 0)]
        bar.render()
        html = bar.text.text()
        self.assertIn("Yes indeed</div>", html)  # the first fully spoken
        self.assertIn("Yes<span style='color:rgba(0,0,0,0);'> indeed</span>", html)  # the second only begun


# ---------------------------------------------------------------- updater
class UpdaterTests(unittest.TestCase):
    def setUp(self):
        import Update
        self.updater = Update
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.root = self.base / "installed"
        self.root.mkdir()
        patcher = mock.patch.multiple(Update, ROOT=self.root, BACKUP_ROOT=self.root / "backups",
                                      STATE_FILE=self.root / ".luxai_update_state.json",
                                      PENDING_FILE=self.root / ".luxai_update_pending.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def archive(self):
        import zipfile
        path = self.base / "source.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("project/main.py", "VALUE = 'new'\n")
            archive.writestr("project/launch_windows.py", "VALUE = 'launcher'\n")
            archive.writestr("project/luxai/voice.py", "VALUE = 'voice'\n")
            archive.writestr("project/run_windows.bat", "@echo off\n")
            archive.writestr("project/requirements.txt", "PySide6>=6.7\n")
        return path

    def test_38_a_failure_after_finishing_an_interrupted_update_keeps_the_marker(self):
        updater = self.updater
        with mock.patch.object(updater, "resume_interrupted_update", return_value=3), \
                mock.patch.object(updater, "close_jarvis"), \
                mock.patch.object(updater, "request_json", side_effect=RuntimeError("no network")):
            self.assertEqual(updater.perform_update(), 1)
        self.assertTrue(updater.PENDING_FILE.exists())  # the launcher still warns

    def test_39_an_interruption_after_the_libraries_restores_them(self):
        updater = self.updater
        (self.root / "main.py").write_text("VALUE = 'old'\n", encoding="utf-8")
        archive = self.archive()
        with mock.patch.object(updater, "request_json", return_value={"sha": "b" * 40}), \
                mock.patch.object(updater, "download", side_effect=lambda _url, target: shutil.copyfile(archive, target)), \
                mock.patch.object(updater, "validate_staged_requirements"), \
                mock.patch.object(updater, "verify_release", return_value=""), \
                mock.patch.object(updater, "close_jarvis"), \
                mock.patch.object(updater, "snapshot_packages", return_value="a==1\n"), \
                mock.patch.object(updater, "upgrade_dependencies", return_value=True), \
                mock.patch.object(updater, "ensure_local_ai_backend", side_effect=KeyboardInterrupt), \
                mock.patch.object(updater, "restore_packages", return_value=True) as restore:
            with self.assertRaises(KeyboardInterrupt):
                updater.perform_update()
        restore.assert_called_once_with("a==1\n")
        self.assertEqual((self.root / "main.py").read_text(encoding="utf-8"), "VALUE = 'old'\n")
        self.assertTrue(updater.PENDING_FILE.exists())


@unittest.skipUnless(sys.platform == "win32", "Windows file locks")
class SharedLockTests(unittest.TestCase):
    def test_40_installer_and_updater_take_the_same_os_lock(self):
        """PowerShell's FileStream.Lock (the installer) and msvcrt.locking (Update.py) exclude each other."""
        import msvcrt
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        lock = folder / "updater.lock"
        script = (
            "$s = [System.IO.File]::Open($env:LOCKFILE, 'OpenOrCreate', 'ReadWrite', 'ReadWrite');"
            "if ($s.Length -eq 0) { $s.WriteByte(0); $s.Flush() }; $s.Lock(0, 1); 'locked'; Start-Sleep -Seconds 6")
        process = subprocess.Popen(["powershell.exe", "-NoProfile", "-Command", script],
                                   env=dict(os.environ, LOCKFILE=str(lock)), stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "locked")
            with lock.open("a+b") as handle:
                handle.seek(0)
                with self.assertRaises(OSError):
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        finally:
            process.kill()
            process.wait(10)
        installer = (ROOT / "scripts" / "install_windows.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("'updater.lock'", installer)
        self.assertIn("$script:SetupLock = Lock-Installation", installer)


class GgufTests(unittest.TestCase):
    def test_41_the_working_version_comes_back_after_a_failed_upgrade(self):
        from luxai import local_ai_setup
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            if "-c" in command:
                return subprocess.CompletedProcess(command, 0, stdout="0.3.20\n")
            return subprocess.CompletedProcess(command, 1)

        # works before, broken after the failed upgrade, works again after the restore
        with mock.patch.object(local_ai_setup, "LOG_FILE", folder / "install.log"), \
                mock.patch.object(local_ai_setup, "check_backend", side_effect=[True, False, True]), \
                mock.patch("luxai.local_ai_setup.subprocess.run", side_effect=run):
            self.assertTrue(local_ai_setup.install_backend("python.exe"))
        self.assertIn("llama-cpp-python==0.3.20", calls[-1])
        self.assertIn("RESTORED", (folder / "install.log").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- P3 / P4
class SlowServer(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", "200")
        self.end_headers()
        try:
            for _ in range(20):  # a trickle: 10 bytes every 0.1 s
                self.wfile.write(b" " * 10)
                self.wfile.flush()
                time.sleep(0.1)
        except OSError:
            pass  # the client gave up at its time limit — that is the point

    def log_message(self, *args):
        pass


class CloudTimeoutTests(unittest.TestCase):
    def test_06_the_whole_read_ends_at_the_time_limit(self):
        import urllib.request
        from luxai.cloud_http import read_json_response
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), SlowServer)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        request = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}/")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        started = time.monotonic()
        with self.assertRaises((TimeoutError, OSError)):
            read_json_response(opener, request, 0.25)
        self.assertLess(time.monotonic() - started, 0.8)  # was ~1.2 s and more


class ConfigTests(unittest.TestCase):
    def test_12_null_confirmation_words_get_their_default(self):
        import main
        data = {"confirm_yes_words": None, "confirm_no_words": None, "online_custom_url": None}
        fixed = main.validate_config(data)
        self.assertNotIn("confirm_yes_words", data)
        self.assertIn("confirm_yes_words", fixed)
        self.assertIn("online_custom_url", data)  # other text fields may stay null


class ExtensionSaveFailureTests(RuntimeCase):
    def test_14_the_page_shows_the_restored_values(self):
        from luxai.ui_extensions import ExtensionsPage
        engine = self.make()
        page = ExtensionsPage(engine)
        self.addCleanup(page.deleteLater)
        page.state["timers"]["enabled"] = True
        page.report_save_failed({"timers": {"enabled": False}})
        self.assertFalse(page.state["timers"]["enabled"])


class NotificationDatabaseTests(unittest.TestCase):
    def database(self, path, orders):
        from contextlib import closing
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("CREATE TABLE IF NOT EXISTS Notification ([Order] INTEGER, Payload BLOB, HandlerId INTEGER, Type TEXT)")
            connection.execute("CREATE TABLE IF NOT EXISTS NotificationHandler (RecordId INTEGER, PrimaryId TEXT)")
            if not connection.execute("SELECT COUNT(*) FROM NotificationHandler").fetchone()[0]:
                connection.execute("INSERT INTO NotificationHandler VALUES (1, 'Telegram')")
            for order in orders:
                payload = f"<toast><visual><binding><text>Msg {order}</text></binding></visual></toast>".encode()
                connection.execute("INSERT INTO Notification VALUES (?, ?, 1, 'toast')", (order, payload))

    def test_18_a_recreated_database_is_followed(self):
        from luxai.notifications import NotificationWatcher
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        path = folder / "wpndatabase.db"
        self.database(path, [500, 501])
        watcher = NotificationWatcher(path)
        self.assertTrue(watcher.prime())
        path.unlink()
        self.database(path, [1])  # Windows rebuilt it: the counter starts low
        self.assertEqual(watcher.poll(), [])  # the cursor follows the new database
        self.database(path, [2])
        self.assertEqual(len(watcher.poll()), 1)


class CleanupRaceTests(unittest.TestCase):
    def test_19_a_file_replaced_after_confirmation_is_not_touched(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        old = time.time() - 40 * 86400
        planned = folder / "setup.exe"
        planned.write_bytes(b"x" * 100)
        os.utime(planned, (old, old))
        steps = runtime.plan_cleanup(folder, min_age_days=1, installer_trash_days=30, language="en")
        self.assertEqual(len(steps), 1)
        planned.unlink()
        planned.write_bytes(b"another file with the same name")  # swapped between confirm and run
        trashed = []
        moved, sent, errors = runtime.run_cleanup(steps, trash=trashed.append)
        self.assertEqual((moved, sent, trashed), (0, 0, []))
        self.assertTrue(planned.exists())
        self.assertTrue(errors)


class AttachmentCopyTests(unittest.TestCase):
    def test_20_a_failed_copy_leaves_nothing_and_can_be_retried(self):
        from luxai import chat_attachments as ca
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        proposal = SimpleNamespace(attachment=SimpleNamespace(kind="text"), export_only=True,
                                   new_text="hello", new_content=b"hello")
        target = folder / "copy.txt"
        with mock.patch("luxai.chat_attachments.os.rename", side_effect=OSError("disk gone")):
            with self.assertRaises(ca.AttachmentError):
                ca.save_text_copy(proposal, target)
        self.assertEqual(list(folder.iterdir()), [])
        result = ca.save_text_copy(proposal, target)
        self.assertEqual(target.read_text(encoding="utf-8"), "hello")
        self.assertEqual(result.path, target)


class ConverterTests(unittest.TestCase):
    def video(self, path, start_seconds=0.0, frames=12):
        import av
        import numpy as np
        from fractions import Fraction
        with av.open(str(path), "w", format="mp4") as out:
            stream = out.add_stream("libx264", rate=12)
            stream.width, stream.height, stream.pix_fmt = 64, 32, "yuv420p"
            stream.codec_context.time_base = Fraction(1, 12)
            for index in range(frames):
                frame = av.VideoFrame.from_ndarray(np.full((32, 64, 3), index * 10, dtype=np.uint8), format="rgb24")
                frame.pts = int(start_seconds * 12) + index
                frame.time_base = Fraction(1, 12)
                for packet in stream.encode(frame):
                    out.mux(packet)
            for packet in stream.encode(None):
                out.mux(packet)

    def test_21_a_video_whose_clock_starts_late_still_gives_frames(self):
        from luxai import converter
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        source = folder / "late.mp4"
        self.video(source, start_seconds=40.0)
        target = converter._video_to_gif(source, folder / "out.gif")
        from PIL import Image
        with Image.open(target) as gif:
            self.assertGreater(getattr(gif, "n_frames", 1), 3)

    def test_22_a_turned_frame_is_drawn_upright(self):
        import av
        import numpy as np
        from luxai import converter
        frame = av.VideoFrame.from_ndarray(np.zeros((32, 64, 3), dtype=np.uint8), format="rgb24")
        turned = converter._upright(frame, 90)
        self.assertEqual((turned.width, turned.height), (32, 64))
        self.assertIs(converter._upright(frame, 0), frame)


@unittest.skipUnless(sys.platform == "win32", "Windows audio sessions")
class AudioSessionTests(unittest.TestCase):
    def test_23_one_broken_session_does_not_stop_the_list(self):
        from luxai import loopback_audio

        class Broken:
            @property
            def Process(self):
                raise OSError("COM error")

        good = SimpleNamespace(Process=SimpleNamespace(pid=4242, name=lambda: "player.exe", parent=lambda: None))
        with mock.patch("pycaw.pycaw.AudioUtilities.GetAllSessions", return_value=[Broken(), good]), \
                mock.patch.object(loopback_audio, "_window_pids", return_value=set()):
            self.assertEqual(loopback_audio.audio_apps(), [("player.exe", 4242)])


class TelegramTests(unittest.TestCase):
    def test_24_a_reply_after_stop_is_reported_not_lost(self):
        from luxai.telegram_control import TelegramBot
        statuses = []
        bot = TelegramBot("1:x", lambda update: None, lambda state, details: statuses.append(state))
        bot.stop()
        self.assertFalse(bot.send("sendMessage", {"text": "hi"}))
        self.assertEqual(statuses, ["undelivered"])

    def test_25_a_lost_answer_is_not_sent_again(self):
        from luxai import telegram_control as tg
        for error, expected_calls in ((tg.TelegramError("Нет связи с Telegram (TimeoutError)."), 1),
                                      (tg.TelegramNotSent("Нет связи с Telegram (ConnectionRefusedError)."), 2)):
            calls = []

            def caller(token, method, params=None, timeout=15):
                calls.append(method)
                raise error

            bot = tg.TelegramBot("1:x", lambda update: None, lambda state, details: None, caller=caller)
            bot._stop.wait = lambda seconds: False  # no real 2 s pause
            bot.outbox.put(("sendMessage", {}))
            bot.outbox.put(None)
            bot._send_loop()
            self.assertEqual(len(calls), expected_calls, type(error).__name__)


class VoicePrefetchTests(unittest.TestCase):
    def setUp(self):
        from luxai import voices
        self.voices = voices
        voices._prefetched.clear()
        self.addCleanup(voices._prefetched.clear)

    def manager(self, **config):
        manager = self.voices.VoiceManager.__new__(self.voices.VoiceManager)
        manager.config = dict({"voice_engine": "fish", "language": "ru"}, **config)
        return manager

    def test_26_a_burst_starts_at_most_two_syntheses(self):
        started = []

        class Hold:
            def __init__(self, target, **kwargs):
                started.append(target)

            def start(self):
                pass

        manager = self.manager()
        with mock.patch.object(self.voices.VoiceManager, "_load_config", return_value=manager.config), \
                mock.patch.object(self.voices.VoiceManager, "_fish_usable", return_value=True, create=True), \
                mock.patch("luxai.voices.threading.Thread", Hold):
            for index in range(9):
                manager.prefetch(f"Piece {index}.", "ru")
        self.assertEqual(len(started), 2)

    def test_27_stop_ends_the_wait_at_once(self):
        token = self.voices._cancel_generation
        manager = self.manager()
        key = ("Text.", "ru") + self.voices._fish_voice_identity(manager.config) + (token,)
        self.voices._prefetched[key] = {"done": threading.Event(), "wav": None}
        threading.Timer(0.2, self.voices.stop_speaking).start()
        started = time.monotonic()
        self.assertIsNone(manager._take_prefetched("Text.", "ru", token))
        self.assertLess(time.monotonic() - started, 2)

    def test_28_a_piece_of_another_voice_or_speed_is_not_played(self):
        token = self.voices._cancel_generation
        old = self.manager(fish_voice_id="old", voice_speed=1.0)
        key = ("Text.", "ru") + self.voices._fish_voice_identity(old.config) + (token,)
        done = threading.Event()
        done.set()
        self.voices._prefetched[key] = {"done": done, "wav": b"OLD"}
        self.assertIsNone(self.manager(fish_voice_id="new", voice_speed=1.0)._take_prefetched("Text.", "ru", token))
        self.assertIsNone(self.manager(fish_voice_id="old", voice_speed=1.3)._take_prefetched("Text.", "ru", token))
        self.assertEqual(old._take_prefetched("Text.", "ru", token), b"OLD")


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class PageHookTests(unittest.TestCase):
    def run_harness(self, scenario):
        result = subprocess.run(["node", str(ROOT / "tests" / "js" / "activation_harness.js"), scenario],
                                capture_output=True, text=True, timeout=60, check=True)
        return json.loads(result.stdout)

    def test_31_audio_loaded_before_captions_were_turned_on_is_sent(self):
        result = self.run_harness("late")
        self.assertEqual(result["before"], 0)  # nothing leaves the page while captions are off
        self.assertEqual(result["after"], 1)
        self.assertEqual(result["full"], [True])

    def test_32_a_removed_source_buffer_is_not_sent_again(self):
        result = self.run_harness("removed")
        self.assertEqual(result["after"], result["before"])


class TrackChoiceTests(unittest.TestCase):
    def test_33_the_dialogue_track_in_the_wanted_language(self):
        from luxai.film_captions import choose_audio_track

        def track(name, rate, language="", disposition=0):
            return SimpleNamespace(name=name, bit_rate=rate, language=language, metadata={},
                                   disposition=disposition)

        description = track("description", 32_000, "eng", 0x100 | 0x1)
        english = track("english", 96_000, "eng")
        russian = track("russian", 128_000, "rus", 0x1)
        self.assertEqual(choose_audio_track([description, english, russian]).name, "russian")  # default
        self.assertEqual(choose_audio_track([description, english, russian], "en").name, "english")
        self.assertEqual(choose_audio_track([description, english]).name, "english")


class TranslatorFilesTests(unittest.TestCase):
    def test_42_config_json_is_checked(self):
        from luxai import offline_translate as ot
        self.assertIn("config.json", ot.SHA256)
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        for name in ot.SHA256:
            (folder / name).write_bytes(b"x")
        with mock.patch.object(ot, "SHA256", {"config.json": __import__("hashlib").sha256(b"good").hexdigest()}):
            self.assertFalse(ot.verified(folder))
            (folder / "config.json").write_bytes(b"good")
            self.assertTrue(ot.verified(folder))


class InstallerScriptTests(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / "scripts" / "install_windows.ps1").read_text(encoding="utf-8-sig")

    def test_43_a_warning_is_not_overwritten_by_done(self):
        self.assertNotIn("Set-UiStep 'gguf' 'warn'\n        }\n    }\n    Set-UiStep 'gguf' 'done'", self.text)
        self.assertIn("if ($script:OptionalMissing -contains 'gguf') { Set-UiStep 'gguf' 'warn' }", self.text)
        self.assertIn("SUCCESS with warnings", self.text)

    def test_45_the_ready_stamp_includes_every_package_record(self):
        self.assertIn("'*.dist-info'", self.text)

    @unittest.skipUnless(sys.platform == "win32", "PowerShell")
    def test_45_ready_key_changes_when_a_package_record_changes(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        venv = folder / ".venv"
        package = venv / "Lib" / "site-packages" / "demo-1.0.dist-info"
        package.mkdir(parents=True)
        (venv / "Scripts").mkdir()
        for name in ("python.exe", "pythonw.exe"):
            (venv / "Scripts" / name).write_bytes(b"x")
        (venv / "pyvenv.cfg").write_text("home = x\n")
        record = package / "RECORD"
        record.write_text("a\n")
        body = self.text.split("function Get-VenvReadyKey {", 1)[1].split("\nif ($CheckVenv)", 1)[0]
        script = ("Set-StrictMode -Version Latest; $ErrorActionPreference = 'Stop';"
                  f"$script:Venv = '{venv}'; $script:VenvPython = '{venv}\\Scripts\\python.exe';"
                  f"$script:VenvPythonw = '{venv}\\Scripts\\pythonw.exe';"
                  "function Get-VenvReadyKey {" + body + "\nGet-VenvReadyKey")

        def key():
            return subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], capture_output=True,
                                  text=True, timeout=60, check=True).stdout.strip()

        before = key()
        site = venv / "Lib" / "site-packages"
        stamp = site.stat().st_mtime_ns
        record.write_text("a\nb\n")  # pip rewrote one package; the folder's own time may stay
        os.utime(site, ns=(stamp, stamp))
        self.assertTrue(before)
        self.assertNotEqual(before, key())


class SetupWindowTests(unittest.TestCase):
    def test_44_a_line_longer_than_the_buffer_is_skipped(self):
        text = (ROOT / "scripts" / "setup_ui.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("$state.skipLine = $true", text)
        self.assertIn("skipLine = $false", text)


class OcrTests(unittest.TestCase):
    def setUp(self):
        from luxai import ocr_setup
        self.ocr = ocr_setup
        patcher = mock.patch.object(ocr_setup, "_VERIFIED", set())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_46_a_broken_first_candidate_does_not_hide_a_working_one(self):
        broken, good = Path("C:/broken/tesseract.exe"), Path("C:/good/tesseract.exe")
        with mock.patch.object(self.ocr, "tesseract_candidates", return_value=[broken, good]), \
                mock.patch.object(self.ocr, "language_data_ready", return_value=True), \
                mock.patch.object(self.ocr, "_identity", side_effect=lambda path: (str(path),)), \
                mock.patch.object(self.ocr, "verify_tesseract",
                                  side_effect=lambda path: (path == good, "" if path == good else "broken")):
            self.assertEqual(self.ocr.ensure_tesseract(allow_download=False)[0], good)

    def test_47_a_verified_engine_is_not_hashed_again(self):
        good = Path("C:/good/tesseract.exe")
        self.ocr._VERIFIED.add((str(good),))
        with mock.patch.object(self.ocr, "tesseract_candidates", return_value=[good]), \
                mock.patch.object(self.ocr, "_identity", side_effect=lambda path: (str(path),)), \
                mock.patch.object(self.ocr, "language_data_ready") as hashed:
            self.assertEqual(self.ocr.ensure_tesseract(allow_download=False)[0], good)
        hashed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
