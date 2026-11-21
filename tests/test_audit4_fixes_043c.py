"""0.4.3c: the fourth audit report (0.4.3b, 2026-11-21)."""
from __future__ import annotations

import datetime as dt
import hashlib
import http.client
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QApplication

from luxai import film_captions as fc

ROOT = Path(__file__).resolve().parents[1]


class RecoveryDigestTests(unittest.TestCase):
    """#1: staged files are checked BEFORE anything moves."""

    def setUp(self):
        import Update
        self.Update = Update
        self.root = Path(tempfile.mkdtemp())
        self.staging = Path(tempfile.mkdtemp())
        for patcher in (mock.patch.object(Update, "ROOT", self.root),
                        mock.patch.object(Update, "_staging_root", return_value=self.staging)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def journal(self, files, digests):
        (self.root / ".luxai_update_journal.json").write_text(json.dumps(
            {"staging": "s1", "files": files, "sha256": digests}), encoding="utf-8")

    def test_damaged_staged_file_blocks_and_nothing_moves(self):
        (self.staging / "s1").mkdir()
        (self.staging / "s1" / "a.py").write_bytes(b"good")
        (self.staging / "s1" / "b.py").write_bytes(b"damaged")
        (self.root / "a.py").write_bytes(b"old a")
        self.journal(["a.py", "b.py"], {"a.py": hashlib.sha256(b"good").hexdigest(),
                                        "b.py": hashlib.sha256(b"expected").hexdigest()})
        self.assertEqual(self.Update.resume_interrupted_update(), -1)
        self.assertEqual((self.root / "a.py").read_bytes(), b"old a")  # not even the good one moved
        self.assertTrue((self.root / ".luxai_update_journal.json").exists())

    def test_journal_without_digest_for_every_file_is_refused(self):
        (self.staging / "s1").mkdir()
        (self.staging / "s1" / "a.py").write_bytes(b"x")
        self.journal(["a.py"], {})
        self.assertEqual(self.Update.resume_interrupted_update(), -1)
        self.journal([], {})
        self.assertEqual(self.Update.resume_interrupted_update(), -1)

    def test_verified_staged_files_are_installed(self):
        (self.staging / "s1").mkdir()
        (self.staging / "s1" / "a.py").write_bytes(b"new")
        self.journal(["a.py"], {"a.py": hashlib.sha256(b"new").hexdigest()})
        self.assertEqual(self.Update.resume_interrupted_update(), 1)
        self.assertEqual((self.root / "a.py").read_bytes(), b"new")


class CandidateTests(unittest.TestCase):
    def test_type_survives_when_the_address_comes_first_without_it(self):
        """#3"""
        report = fc.parse_report(json.dumps({"tab": 1, "src": "https://c.example/stream",
                                             "media": [{"url": "https://c.example/stream",
                                                        "type": "application/vnd.apple.mpegurl"}]}).encode())
        self.assertEqual(fc.rank_candidates(report["media"]), ["https://c.example/stream"])

    def test_report_carries_document_order_session_and_visibility(self):
        """#4, #5, #6"""
        report = fc.parse_report(json.dumps({"tab": 1, "doc": "ab-12<script>", "seq": 7, "session": 3,
                                             "visible": False, "focused": True}).encode())
        self.assertEqual((report["doc"], report["seq"], report["session"], report["visible"], report["focused"]),
                         ("ab-12script", 7, 3, False, True))


class FilmRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def runtime(self, settings=None):
        from luxai import extensions_catalog as catalog
        from luxai.extensions_runtime import ExtensionsRuntime
        host = mock.Mock()
        host.cfg = {"language": "ru", "extensions_meta": {}}
        runtime = ExtensionsRuntime(host)
        self.addCleanup(runtime.deleteLater)
        runtime.state = catalog.normalize_state({"live_captions": {"enabled": True, "settings": dict(
            {"translate": False}, **(settings or {}))}})
        runtime.captions_visible = True
        runtime._film_bridge = object()
        self.addCleanup(lambda: setattr(runtime, "_film_bridge", None))
        return runtime

    @staticmethod
    def report(**changes):
        base = {"event": "state", "tab": 1, "frame": 0, "page": "https://s/p", "time": 3.0, "paused": False,
                "stalled": False, "ended": False, "rate": 1.0, "duration": 5400.0, "src": "",
                "media": [{"url": "https://c/a.m3u8", "type": ""}], "doc": "d1", "seq": 1, "session": 1,
                "visible": True, "focused": True}
        base.update(changes)
        return base

    def test_a_late_report_after_closing_does_not_start_again(self):
        """#4"""
        runtime = self.runtime()
        with mock.patch.object(fc.FilmTranscriber, "start") as start:
            runtime._on_film_report(self.report(seq=1))
            runtime._on_film_report({"event": "closed", "tab": 1, "docs": ["d1"]})
            runtime._on_film_report(self.report(seq=2))  # sent before the close, arrived after it
        self.assertIsNone(runtime._film)
        self.assertEqual(start.call_count, 1)

    def test_an_older_report_is_ignored(self):
        runtime = self.runtime()
        with mock.patch.object(fc.FilmTranscriber, "start"):
            runtime._on_film_report(self.report(seq=5, time=50.0))
            runtime._on_film_report(self.report(seq=4, time=10.0))
        self.assertAlmostEqual(runtime._film[1].time, 50.0)

    def test_a_new_source_in_the_same_player_is_a_new_film(self):
        """#5: a blob player that loads another playlist (same tab, frame, length)."""
        runtime = self.runtime()
        with mock.patch.object(fc.FilmTranscriber, "start") as start:
            runtime._on_film_report(self.report(session=1, seq=1))
            runtime._on_film_report(self.report(session=2, seq=2, media=[{"url": "https://c/b.m3u8", "type": ""}]))
        self.assertEqual(start.call_count, 2)

    def test_the_tab_the_user_looks_at_wins(self):
        """#6"""
        runtime = self.runtime()
        with mock.patch.object(fc.FilmTranscriber, "start"):
            runtime._on_film_report(self.report(visible=False, focused=False))
            runtime._on_film_report(self.report(tab=2, doc="d2", page="https://other/x"))
        self.assertEqual(runtime._film[0][0], 2)

    def test_a_background_tab_does_not_take_over_the_one_looked_at(self):
        runtime = self.runtime()
        with mock.patch.object(fc.FilmTranscriber, "start"):
            runtime._on_film_report(self.report())
            runtime._on_film_report(self.report(tab=2, doc="d2", page="https://other/x", visible=False, focused=False))
        self.assertEqual(runtime._film[0][0], 1)

    def test_prepare_ahead_setting_reaches_the_worker(self):
        """#17"""
        runtime = self.runtime({"film_ahead": "60"})
        with mock.patch.object(fc.FilmTranscriber, "start"):
            runtime._on_film_report(self.report())
        self.assertEqual(runtime._film[3].ahead_seconds, 60.0)

    def test_dateless_entry_is_not_installed_and_saves_add_up(self):
        """#10"""
        runtime = self.runtime()
        meta = runtime.host.cfg["extensions_meta"]
        meta["browser_extension_seen"] = {"version": "1.0.0", "browser": "chrome"}
        self.assertFalse(runtime.extension_installed())
        self.assertFalse(runtime.extension_contacted())
        runtime.host.save_extensions_meta.reset_mock()
        runtime._remember_extension({"version": "1.0.0", "browser": "chrome"})  # no date yet: saved
        self.assertEqual(runtime.host.save_extensions_meta.call_count, 1)
        saved_at = meta["browser_extension_seen"]["at"]
        meta["browser_extension_seen"]["at"] = saved_at - 86400 - 5  # a day passes between frequent reports
        for _ in range(5):
            runtime._note_extension_alive()
        self.assertEqual(runtime.host.save_extensions_meta.call_count, 2)
        self.assertTrue(runtime.extension_installed())
        self.assertTrue(runtime.extension_contacted())

    def test_pairing_write_failure_keeps_the_bridge_off(self):
        """#7"""
        runtime = self.runtime()
        runtime._film_bridge = None
        with mock.patch.object(fc, "pairing_token", side_effect=OSError("read-only")), \
                mock.patch.object(fc, "BridgeServer") as bridge:
            runtime._start_film_bridge()
        bridge.assert_not_called()
        self.assertIsNone(runtime._film_bridge)
        self.assertIn("read-only", runtime._pairing_error)


class PairingFileTests(unittest.TestCase):
    def test_unwritable_folder_raises(self):
        """#7"""
        with self.assertRaises(OSError):
            fc.pairing_token(Path(tempfile.mkdtemp()) / "missing" / "folder")

    def test_written_atomically_and_read_back(self):
        folder = Path(tempfile.mkdtemp())
        token = fc.pairing_token(folder)
        self.assertEqual(json.loads((folder / "pairing.json").read_text(encoding="utf-8"))["token"], token)
        self.assertEqual([p.name for p in folder.iterdir()], ["pairing.json"])  # no temporary file left


class TimelineTests(unittest.TestCase):
    def test_two_different_lines_that_overlap_a_lot_both_stay(self):
        """#9"""
        timeline = fc.CueTimeline()
        timeline.add([fc.Cue(1.0, 4.0, "Where were you last night?"), fc.Cue(2.0, 6.0, "I told you already")], 0, 10)
        self.assertEqual(len(timeline.cues), 2)

    def test_the_same_line_redone_is_not_doubled(self):
        timeline = fc.CueTimeline()
        timeline.add([fc.Cue(1.0, 4.0, "Where were you last night")], 0, 10)
        timeline.add([fc.Cue(1.1, 4.1, "Where were you last night?")], 0, 10)
        self.assertEqual([c.text for c in timeline.cues], ["Where were you last night?"])

    def test_insertion_looks_only_at_neighbours(self):
        """#19: thousands of lines added one by one stay fast and ordered."""
        timeline = fc.CueTimeline()
        started = time.perf_counter()
        for i in range(4000):
            timeline.add([fc.Cue(i * 3.0, i * 3.0 + 2.0, f"line {i}")], i * 3.0, i * 3.0 + 3.0)
        self.assertLess(time.perf_counter() - started, 3.0)
        self.assertEqual(timeline._starts, sorted(timeline._starts))
        self.assertEqual(len(timeline.cues), 4000)
        self.assertEqual([c.text for c in timeline.lines_at(4500.5)], ["line 1499", "line 1500"])


class BridgeTests(unittest.TestCase):
    def post(self, port, path, token="t" * 48, body=b"{}"):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("POST", path, body=body, headers={
            "Origin": "chrome-extension://" + "a" * 32, "X-Jarvis-Token": token, "Content-Type": "application/json"})
        answer = connection.getresponse()
        return answer.status, json.loads(answer.read() or b"{}")

    def test_want_says_whether_jarvis_shows_captions(self):
        """#14"""
        reports = []
        bridge = fc.BridgeServer(reports.append, port=47397, token="t" * 48)
        self.assertTrue(bridge.start())
        self.addCleanup(bridge.stop)
        self.assertEqual(self.post(47397, "/v1/want"), (200, {"ok": True, "want": False}))
        bridge.want = True
        self.assertEqual(self.post(47397, "/v1/want")[1]["want"], True)
        status, answer = self.post(47397, "/v1/state", body=json.dumps({"tab": 1}).encode())
        self.assertEqual((status, answer["want"]), (200, True))
        self.assertEqual(len(reports), 1)

    def test_connections_are_limited_when_accepted(self):
        """#13: slow clients that never finish their headers hold at most 8 slots."""
        bridge = fc.BridgeServer(lambda _r: None, port=47398, token="t" * 48)
        self.assertTrue(bridge.start())
        self.addCleanup(bridge.stop)
        slow = [socket.create_connection(("127.0.0.1", 47398), timeout=5) for _ in range(8)]
        self.addCleanup(lambda: [s.close() for s in slow])
        time.sleep(0.3)
        extra = socket.create_connection(("127.0.0.1", 47398), timeout=5)
        self.addCleanup(extra.close)
        self.assertEqual(extra.recv(10), b"")  # closed at once: no thread was created for it
        for s in slow:
            s.close()
        time.sleep(0.5)
        self.assertEqual(self.post(47398, "/v1/want")[0], 200)  # the slots came back


class ChooseTests(unittest.TestCase):
    def test_a_stop_ends_the_choice_between_candidates(self):
        """#16"""
        opened = []
        worker = fc.FilmTranscriber(["https://a.example/1.m3u8", "https://a.example/2.m3u8"], "",
                                    fc.PlayerClock(), fc.CueTimeline(), lambda: None)

        def fake_open(url, referer, opener, session=None):
            opened.append(url)
            worker.stop()  # the session stops while the first one opens
            raise OSError("slow")

        with mock.patch.object(fc, "open_media", fake_open):
            worker._run()
        self.assertEqual(opened, ["https://a.example/1.m3u8"])
        self.assertFalse(worker.failed)  # stopped on purpose is not a failure


class ReminderTests(unittest.TestCase):
    now = dt.datetime(2026, 11, 21, 7, 0)

    def parse(self, text):
        from luxai.timers import parse_request
        return parse_request(text, self.now)

    def test_tomorrow_after_the_time_is_not_in_the_label(self):
        """#11"""
        request = self.parse("remind me at 08:00 tomorrow to call Ana")
        self.assertEqual((request.at.day, request.at.hour, request.label), (22, 8, "call Ana"))
        self.assertEqual(self.parse("напомни в 9:30 завтра позвонить маме").label, "позвонить маме")
        self.assertEqual(self.parse("remind me at 9:30 tomorrow").label, "")

    def test_link_word_is_removed_only_as_a_whole_word(self):
        from luxai.timers import _clean_label
        self.assertEqual(_clean_label(" tomorrow's list"), "tomorrow's list")
        self.assertEqual(_clean_label(" to call Ana"), "call Ana")

    def test_negative_spoken_durations_are_refused(self):
        """#12"""
        from luxai.timers import parse_duration
        self.assertIsNone(self.parse("remind me in -half an hour to call Ana"))
        self.assertIsNone(parse_duration("−quarter of an hour"))
        self.assertEqual(parse_duration("half an hour"), 1800)


@unittest.skipUnless(sys.platform == "win32", "Windows audio")
class CaptureTests(unittest.TestCase):
    def test_a_program_started_later_is_captured_alone(self):
        """#8"""
        from luxai import loopback_audio as la
        capture = la.LoopbackCapture(lambda _a: None, app_pid=0, app_name="vlc.exe")
        self.assertTrue(capture._waiting_for_app)
        capture._fallback_since = time.monotonic() - la.LoopbackCapture.WAIT_FOR_APP_SECONDS - 0.1
        with mock.patch.object(la, "app_pid", return_value=4242):
            with self.assertRaises(la._BackToApp) as raised:
                capture._maybe_back_to_app()
        self.assertEqual(raised.exception.pid, 4242)

    def test_no_program_chosen_means_no_search(self):
        from luxai import loopback_audio as la
        capture = la.LoopbackCapture(lambda _a: None)
        self.assertFalse(capture._waiting_for_app)
        with mock.patch.object(la, "app_pid") as find:
            capture._maybe_back_to_app()
        find.assert_not_called()


class CloseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_closing_does_not_wait_for_a_slow_save(self):
        """#15: the Qt thread returns at once; a non-daemon thread finishes the save."""
        from luxai.extensions_runtime import ExtensionsRuntime
        host = mock.Mock()
        host.cfg = {"language": "en"}
        runtime = ExtensionsRuntime(host)
        self.addCleanup(runtime.deleteLater)
        release = threading.Event()
        runtime._clip_saver.submit(lambda: release.wait(5))
        threads = []
        real = threading.Thread

        def spy(*args, **kwargs):
            thread = real(*args, **kwargs)
            threads.append(thread)
            return thread

        with mock.patch("luxai.extensions_runtime.threading.Thread", side_effect=spy):
            started = time.monotonic()
            runtime._finish_clip_saves_at_exit(None)
            self.assertLess(time.monotonic() - started, 0.5)
        final = [t for t in threads if t.name == "JarvisClipboardFinalSave"]
        self.assertEqual(len(final), 1)
        self.assertFalse(final[0].daemon)
        release.set()
        final[0].join(5)


class ExtensionCodeTests(unittest.TestCase):
    def test_extension_contract(self):
        """#4, #5, #6, #14, #18"""
        background = (ROOT / "browser_extension" / "background.js").read_text(encoding="utf-8")
        content = (ROOT / "browser_extension" / "content.js").read_text(encoding="utf-8")
        manifest = json.loads((ROOT / "browser_extension" / "manifest.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(tuple(map(int, manifest["version"].split("."))), (1, 2, 0))
        self.assertIn("AbortController", background)        # #18 fetch time limit
        self.assertIn("busy.has(tab)", background)           # #18 one request in flight per tab
        self.assertIn('post("want"', background)             # #14 asks before sending anything
        self.assertNotIn("own.length ? own : all", background)  # #6 no random fallback to other frames
        self.assertIn("jarvis-bye", content)                 # #4 the document says goodbye
        self.assertIn("seq += 1", content)
        self.assertIn('"loadstart"', content)                # #5 a new source = a new session
        self.assertIn("document.hasFocus()", content)        # #6


if __name__ == "__main__":
    unittest.main()
