"""0.4.3b: the third audit report (2026-11-21)."""
from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
from PySide6.QtWidgets import QApplication

from luxai import film_captions as fc

ROOT = Path(__file__).resolve().parents[1]


class RecoveryTests(unittest.TestCase):
    """#1: an interrupted update whose state cannot be confirmed is never declared done."""

    def setUp(self):
        import Update
        self.Update = Update
        self.root = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(Update, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unreadable_journal_is_kept_and_reported(self):
        journal = self.root / ".luxai_update_journal.json"
        journal.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.Update.resume_interrupted_update(), -1)
        self.assertTrue(journal.exists())

    def test_missing_staged_file_that_is_not_in_place_blocks(self):
        (self.root / ".luxai_update_journal.json").write_text(json.dumps(
            {"staging": "abc", "files": ["main.py"], "sha256": {"main.py": "0" * 64}}), encoding="utf-8")
        (self.root / "main.py").write_text("old", encoding="utf-8")
        self.assertEqual(self.Update.resume_interrupted_update(), -1)
        self.assertTrue((self.root / ".luxai_update_journal.json").exists())

    def test_file_already_moved_is_recognised_by_its_digest(self):
        import hashlib
        (self.root / "main.py").write_bytes(b"new")
        (self.root / ".luxai_update_journal.json").write_text(json.dumps(
            {"staging": "abc", "files": ["main.py"], "sha256": {"main.py": hashlib.sha256(b"new").hexdigest()}}),
            encoding="utf-8")
        self.assertEqual(self.Update.resume_interrupted_update(), 0)
        self.assertFalse((self.root / ".luxai_update_journal.json").exists())

    def test_staging_records_digests(self):
        source = Path(tempfile.mkdtemp()) / "a.py"
        source.write_text("x", encoding="utf-8")
        self.Update._stage_files([(source, Path("a.py"))])
        journal = json.loads((self.root / ".luxai_update_journal.json").read_text(encoding="utf-8"))
        self.assertEqual(len(journal["sha256"]["a.py"]), 64)


class BridgeTrustTests(unittest.TestCase):
    """#2: only the paired extension may talk; media goes only to public addresses over http(s)."""

    def test_pairing_token_is_created_once_and_kept(self):
        folder = Path(tempfile.mkdtemp())
        first = fc.pairing_token(folder)
        self.assertRegex(first, r"^[0-9a-f]{48}$")
        self.assertEqual(fc.pairing_token(folder), first)

    def test_local_and_private_destinations_are_refused(self):
        for url in ("http://127.0.0.1/a.m3u8", "http://localhost/a.mp4", "http://192.168.1.1/a.mp4",
                    "http://10.0.0.5/x.m3u8", "http://169.254.1.1/a.mp4"):
            self.assertFalse(fc.public_destination(url), url)
        with mock.patch.dict("os.environ", {"LUXAI_FILM_ALLOW_LOCAL": "1"}):
            self.assertTrue(fc.public_destination("http://127.0.0.1/a.m3u8"))

    def test_decoder_is_limited_to_network_protocols(self):
        options = fc.media_options("https://site.example/w")
        self.assertEqual(options["protocol_whitelist"], "http,https,tls,tcp,crypto,httpproxy")  # + the checking proxy (audit 4 #2)
        self.assertNotIn("headers", fc.media_options("https://x\r\nEvil: 1"))  # no header from an unchecked value

    def test_open_refuses_before_connecting(self):
        opener = mock.Mock()
        with self.assertRaises(PermissionError):
            fc.open_media("http://127.0.0.1/a.m3u8", "", opener=opener)
        opener.assert_not_called()

    def test_bad_content_length_gets_an_answer(self):
        bridge = fc.BridgeServer(lambda _r: None, port=47396, token="z" * 48)
        self.assertTrue(bridge.start())
        self.addCleanup(bridge.stop)
        import http.client
        connection = http.client.HTTPConnection("127.0.0.1", 47396, timeout=5)
        connection.putrequest("POST", "/v1/state")
        connection.putheader("Origin", "chrome-extension://" + "a" * 32)
        connection.putheader("Content-Length", "abc")
        connection.endheaders()
        self.assertEqual(connection.getresponse().status, 400)


class PasteAndClipboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def runtime(self):
        from luxai.extensions_runtime import ExtensionsRuntime
        host = mock.Mock()
        host.cfg = {"language": "en"}
        runtime = ExtensionsRuntime(host)
        self.addCleanup(runtime.deleteLater)
        return runtime

    def test_paste_refused_when_something_else_was_copied(self):
        """#3"""
        from luxai import extensions_runtime as rt
        runtime = self.runtime()
        notices = []
        runtime.notice.connect(notices.append)
        with mock.patch.object(rt, "_set_foreground", return_value=True),                 mock.patch.object(rt, "_foreground_window", return_value=42),                 mock.patch("luxai.selection.clipboard_sequence", return_value=6),                 mock.patch.object(rt, "_send_paste") as paste:
            runtime._paste_into(42, sequence=5)  # Jarvis wrote sequence 5; something else made it 6
            end = time.time() + 2
            while time.time() < end and not notices:
                self.app.processEvents()
                time.sleep(0.01)
        self.assertTrue(notices)
        self.assertEqual(paste.call_count, 0)

    def test_clearing_wins_over_a_history_still_loading(self):
        """#4"""
        from luxai.clipboard_store import ClipboardHistory
        runtime = self.runtime()
        generation = runtime._clip_load_generation
        runtime.clear_clipboard_all()
        loaded = ClipboardHistory()
        loaded.add_text("old secret")
        runtime._on_clip_history_loaded(loaded, generation)
        self.assertEqual(runtime.clip_history.items, [])


class ReminderTests(unittest.TestCase):
    """#5"""
    now = dt.datetime(2026, 11, 21, 7, 0)

    def parse(self, text):
        from luxai.timers import parse_request
        return parse_request(text, self.now)

    def test_clock_first_keeps_the_duration_in_the_message(self):
        request = self.parse("remind me at 08:00 to water plants for 5 minutes")
        self.assertEqual((request.kind, request.at.hour, request.label), ("alarm", 8, "water plants for 5 minutes"))

    def test_pm_inside_the_message_does_not_move_the_time(self):
        request = self.parse("remind me at 08:00 to check PM report")
        self.assertEqual((request.at.hour, request.label), (8, "check PM report"))

    def test_marks_next_to_the_time_still_count(self):
        self.assertEqual(self.parse("remind me at 8 pm to call Ana").at.hour, 20)
        self.assertEqual(self.parse("remind me tomorrow at 9:00 to pay").at.day, 22)
        self.assertEqual(self.parse("разбуди в 7 вечера").at.hour, 19)


class ConfigTests(unittest.TestCase):
    def test_phrase_fields_of_the_wrong_type_are_dropped(self):
        """#6"""
        import main
        data = {"microphone_off_phrases": ["x"], "confirm_yes_words": 5, "microphone_device": "abc"}
        self.assertEqual(set(main.validate_config(data)), {"microphone_off_phrases", "confirm_yes_words",
                                                            "microphone_device"})
        self.assertEqual(data, {})


class FilmSessionTests(unittest.TestCase):
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
                "media": [{"url": "https://c/a.m3u8", "type": ""}]}
        base.update(changes)
        return base

    def test_a_paused_background_tab_does_not_take_over(self):
        """#7"""
        runtime = self.runtime()
        starts = []
        with mock.patch.object(fc.FilmTranscriber, "start", side_effect=lambda: starts.append(1)):
            runtime._on_film_report(self.report())
            for _ in range(3):
                runtime._on_film_report(self.report(tab=2, paused=True, page="https://other/x"))
                runtime._on_film_report(self.report(time=4.0))
        self.assertEqual(len(starts), 1)

    def test_a_new_address_on_the_same_page_is_a_new_film(self):
        """#8"""
        runtime = self.runtime()
        starts = []
        with mock.patch.object(fc.FilmTranscriber, "start", side_effect=lambda: starts.append(1)):
            runtime._on_film_report(self.report(src="https://c/one.mp4"))
            runtime._on_film_report(self.report(src="https://c/two.mp4"))
        self.assertEqual(len(starts), 2)

    def test_changed_language_settings_prepare_again(self):
        """#20"""
        runtime = self.runtime()
        first = runtime._film_key(self.report())
        runtime.state["live_captions"]["settings"]["language"] = "en"
        self.assertNotEqual(first, runtime._film_key(self.report()))

    def test_a_failed_film_is_not_retried_at_once(self):
        """#10, #11"""
        runtime = self.runtime()
        starts = []
        with mock.patch.object(fc.FilmTranscriber, "start", side_effect=lambda: starts.append(1)):
            runtime._on_film_report(self.report())
            runtime._film[3].failed = True
            runtime._film[3].stop()
            runtime._film_tick()  # the failed worker is dropped and remembered
            for _ in range(5):
                runtime._on_film_report(self.report())
        self.assertEqual(len(starts), 1)
        self.assertIsNone(runtime._film)

    def test_closed_tab_stops_the_preparation(self):
        """#14"""
        runtime = self.runtime()
        with mock.patch.object(fc.FilmTranscriber, "start"):
            runtime._on_film_report(self.report())
            worker = runtime._film[3]
            runtime._on_film_report({"event": "closed", "tab": 1})
        self.assertIsNone(runtime._film)
        self.assertTrue(worker.stopped)

    def test_silent_browser_stops_the_preparation(self):
        runtime = self.runtime()
        with mock.patch.object(fc.FilmTranscriber, "start"):
            runtime._on_film_report(self.report())
        runtime._film[1].reported = time.monotonic() - fc.GONE_SECONDS - 1
        runtime._film_tick()
        self.assertIsNone(runtime._film)

    def test_media_ignored_with_the_option_off(self):
        """#15"""
        runtime = self.runtime({"browser_films": False})
        with mock.patch.object(fc.FilmTranscriber, "start") as start:
            runtime._on_film_report(self.report())
        start.assert_not_called()
        self.assertTrue(runtime.extension_installed())  # it still confirms the extension

    def test_extension_seen_long_ago_is_offered_again(self):
        """#21"""
        runtime = self.runtime()
        runtime.host.cfg["extensions_meta"]["browser_extension_seen"] = {"version": "1.0.0", "browser": "chrome",
                                                                        "at": time.time() - 40 * 86400}
        self.assertFalse(runtime.extension_installed())
        runtime._note_extension_alive()
        self.assertTrue(runtime.extension_installed())


class ClockAndTimelineTests(unittest.TestCase):
    def test_buffering_freezes_the_clock(self):
        """#23"""
        clock = fc.PlayerClock()
        clock.update(50.0, paused=False, stalled=True, now=10.0)
        self.assertEqual(clock.position(now=15.0), 50.0)

    def test_lines_that_only_touch_both_stay(self):
        """#19"""
        timeline = fc.CueTimeline()
        timeline.add([fc.Cue(1.0, 4.0, "First line"), fc.Cue(3.9, 6.0, "Second line")], 0, 10)
        self.assertEqual([c.text for c in timeline.cues], ["First line", "Second line"])
        self.assertEqual(timeline.cues[0].end, 3.9)

    def test_lookup_stays_correct_on_a_long_film(self):
        """#26"""
        timeline = fc.CueTimeline()
        timeline.add([fc.Cue(i * 3.0, i * 3.0 + 2.0, f"line {i}") for i in range(3000)], 0, 9000)
        started = time.perf_counter()
        for _ in range(1000):
            lines = timeline.lines_at(4500.5)
        self.assertLess(time.perf_counter() - started, 0.5)
        self.assertEqual([c.text for c in lines], ["line 1499", "line 1500"])


class GapTests(unittest.TestCase):
    def test_audio_gaps_keep_their_place(self):
        """#12: frames at 0.0, 0.1, 0.8, 0.9 s → the later ones stay at 0.8 s."""
        import av
        from fractions import Fraction
        path = Path(tempfile.mkdtemp()) / "gap.wav"
        with av.open(str(path), "w", format="matroska") as out:
            stream = out.add_stream("pcm_s16le", rate=16000)
            stream.layout = "mono"
            for start in (0.0, 0.1, 0.8, 0.9):
                frame = av.AudioFrame.from_ndarray(np.full((1, 1600), 3000, dtype=np.int16), format="s16", layout="mono")
                frame.sample_rate = 16000
                frame.pts = int(start * 16000)
                frame.time_base = Fraction(1, 16000)
                for packet in stream.encode(frame):
                    out.mux(packet)
            for packet in stream.encode(None):
                out.mux(packet)
        with av.open(str(path)) as container:
            audio, begin = fc.decode_audio(container, container.streams.audio[0], 0.0, 2.0)
        self.assertGreater(len(audio) / 16000, 0.9)
        self.assertLess(float(np.abs(audio[int(0.4 * 16000):int(0.7 * 16000)]).max()), 0.01)  # the gap is silence


class GuideTests(unittest.TestCase):
    def test_edge_guide_speaks_about_edge(self):
        """#27"""
        from luxai.ui_browser_extension import ExtensionInstallDialog
        QApplication.instance() or QApplication([])
        dialog = ExtensionInstallDialog("en", browser="edge")
        self.addCleanup(dialog.deleteLater)
        texts = " ".join(label.text() for label in dialog.findChildren(type(dialog.status)))
        self.assertIn("edge://extensions", texts)
        self.assertNotIn("chrome://", texts)


@unittest.skipUnless(sys.platform == "win32", "Windows audio")
class CaptureTests(unittest.TestCase):
    def test_com_failure_is_reported(self):
        """#29"""
        from luxai import loopback_audio as la
        errors = []
        capture = la.LoopbackCapture(lambda _a: None, on_error=errors.append)
        with mock.patch.object(la.ctypes.oledll.ole32, "CoInitializeEx", side_effect=OSError("RPC_E_CHANGED_MODE")), \
                mock.patch.object(la, "_log_capture_error"):
            worker = threading.Thread(target=capture._run)
            worker.start()
            worker.join(5)
        self.assertTrue(capture.started.is_set())
        self.assertEqual(len(errors), 1)

    def test_goes_back_to_the_chosen_program(self):
        """#28"""
        from luxai import loopback_audio as la
        capture = la.LoopbackCapture(lambda _a: None, app_name="chrome.exe")
        capture._fallback_since = time.monotonic() - 31
        with mock.patch.object(la, "app_pid", return_value=777):
            with self.assertRaises(la._BackToApp) as raised:
                capture._maybe_back_to_app()
        self.assertEqual(raised.exception.pid, 777)


class ExtensionCodeTests(unittest.TestCase):
    def test_extension_contract(self):
        """#13, #18, #23, #25: one write queue, lists cleared on navigation, heartbeat, errors noticed."""
        background = (ROOT / "browser_extension" / "background.js").read_text(encoding="utf-8")
        content = (ROOT / "browser_extension" / "content.js").read_text(encoding="utf-8")
        self.assertIn("queue = queue.then(", background)
        self.assertIn("chrome.tabs.onUpdated.addListener", background)
        self.assertIn('event: "closed"', background)
        self.assertIn("X-Jarvis-Token", background)
        self.assertIn("answer.ok", background)
        self.assertIn('"waiting"', content)
        self.assertIn("video.paused ? 3000 : 1000", content)
        self.assertNotIn("querySelectorAll", content)  # follows one player, no page scans


if __name__ == "__main__":
    unittest.main()
