"""0.4.3e: the fifth audit report (0.4.3d, 2026-11-21)."""
from __future__ import annotations

import datetime as dt
import hashlib
import http.server
import json
import os
import socket
import ssl
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PySide6.QtWidgets import QApplication

from luxai import film_captions as fc
from luxai import media_proxy as mp

ROOT = Path(__file__).resolve().parents[1]


class _Server(http.server.BaseHTTPRequestHandler):
    """/redirect → localhost; /slow → never answers; /list.m3u8 → a playlist; anything else → bytes."""
    hold = threading.Event()

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{self.server.server_port}/secret.mp4")
            self.end_headers()
        elif self.path.startswith("/slow"):
            _Server.hold.wait(10)
        elif self.path.startswith("/list"):
            body = b"#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\nseg1.ts\n#EXT-X-ENDLIST\n"
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = b"0123456789" * 100
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, *_args):
        pass


class GatewayTests(unittest.TestCase):
    """#1, #12, #13, #18"""

    def setUp(self):
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Server)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.gateway = mp.MediaGateway().start()
        self.addCleanup(self.gateway.stop)
        self.session = self.gateway.open_session()
        real = mp.allowed_addresses
        patcher = mock.patch.object(mp, "allowed_addresses",
                                    lambda host, port: ["127.0.0.1"] if host == "127.0.0.1" else real(host, port))
        patcher.start()
        self.addCleanup(patcher.stop)

    def local(self, path):
        return f"http://127.0.0.1:{self.server.server_port}{path}"

    def get(self, url, timeout=10):
        import urllib.request
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(url, timeout=timeout) as answer:
                return answer.status, answer.read()
        except urllib.error.HTTPError as error:
            return error.code, b""

    def test_https_is_verified_with_the_host_name(self):
        self.assertEqual(self.gateway.tls.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(self.gateway.tls.check_hostname)

    def test_a_certificate_that_does_not_verify_is_refused(self):
        with mock.patch.object(self.gateway.tls, "wrap_socket",
                               side_effect=ssl.SSLCertVerificationError("self-signed certificate")):
            status, _ = self.get(self.session.url_for(self.local("/x.mp4").replace("http:", "https:")))
        self.assertEqual(status, 403)
        self.assertEqual(self.gateway.refused[-1], "127.0.0.1")

    def test_redirect_to_this_computer_is_refused(self):
        status, _ = self.get(self.session.url_for(self.local("/redirect.mp4")))
        self.assertEqual(status, 403)
        self.assertIn("localhost", self.gateway.refused)

    def test_playlists_are_rewritten_through_the_gateway(self):
        status, body = self.get(self.session.url_for(self.local("/list.m3u8")))
        self.assertEqual(status, 200)
        segment = [line for line in body.decode().splitlines() if line and not line.startswith("#")][0]
        self.assertTrue(segment.startswith(self.gateway.base + "/" + self.session.id + "/"))
        self.assertTrue(segment.endswith("/seg1.ts"))  # the file name stays (FFmpeg checks extensions)
        self.assertEqual(self.session.target(int(segment.split("/")[4])), self.local("/seg1.ts"))

    def test_rewrite_covers_keys_maps_and_relative_addresses(self):
        text = ('#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n#EXT-X-MAP:URI="https://cdn.example/init.mp4"\n'
                '#EXTINF:4,\n../seg/1.ts\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://drm"\n')
        out = mp.rewrite_playlist(text, "https://cdn.example/a/b/list.m3u8", lambda url: "G(" + url + ")")
        self.assertIn('URI="G(https://cdn.example/a/b/key.bin)"', out)
        self.assertIn('URI="G(https://cdn.example/init.mp4)"', out)
        self.assertIn("G(https://cdn.example/a/seg/1.ts)", out)
        self.assertIn('URI="skd://drm"', out)  # not http(s): left as is, FFmpeg may not open it anyway

    def test_unknown_session_or_address_is_not_served(self):
        self.assertEqual(self.get(f"{self.gateway.base}/{'0' * 32}/0/x.mp4")[0], 404)
        self.assertEqual(self.get(f"{self.gateway.base}/{self.session.id}/99/x.mp4")[0], 404)

    def test_closing_the_session_ends_a_waiting_request_at_once(self):
        """#13"""
        _Server.hold.clear()
        self.addCleanup(_Server.hold.set)
        result = {}

        def ask():
            started = time.monotonic()
            try:
                self.get(self.session.url_for(self.local("/slow.mp4")), timeout=10)
            except OSError:
                pass
            result["seconds"] = time.monotonic() - started

        worker = threading.Thread(target=ask)
        worker.start()
        time.sleep(0.5)
        self.session.close()
        worker.join(5)
        self.assertLess(result.get("seconds", 99), 2.0)

    def test_refusals_are_bounded(self):
        """#18"""
        for i in range(100):
            self.gateway._note_refused(f"host{i}")
        self.assertEqual(len(self.gateway.refused), 20)
        self.assertEqual(self.gateway.refused_count, 100)

    def test_real_decoder_goes_only_through_the_gateway_and_environment_is_untouched(self):
        """#1, #12: FFmpeg gets the gateway address, no https/tls of its own, and os.environ stays as it was."""
        options = fc.media_options("https://site.example/w")
        self.assertEqual(options["protocol_whitelist"], "http,tcp,crypto")
        self.assertEqual(options["http_proxy"], "")
        with mock.patch.dict(os.environ, {"no_proxy": "corp.example", "NO_PROXY": "corp.example"}):
            with mock.patch.object(fc, "public_destination", return_value=True):
                with self.assertRaises(Exception):
                    fc.open_media(self.local("/redirect.mp4"), "", session=self.session)
            self.assertEqual(os.environ.get("no_proxy"), "corp.example")
            self.assertEqual(os.environ.get("NO_PROXY"), "corp.example")

    def test_a_stopped_worker_closes_its_session(self):
        worker = fc.FilmTranscriber(["https://a.example/1.m3u8"], "", fc.PlayerClock(), fc.CueTimeline(), lambda: None)
        session = worker._gateway_session()
        worker.stop()
        self.assertTrue(session.closed)


class OffsetTests(unittest.TestCase):
    def test_media_whose_clock_starts_late_is_read_in_player_time(self):
        """#4: an MPEG-TS whose timestamps start near 30 s; the player shows 0."""
        import av
        from fractions import Fraction
        path = Path(tempfile.mkdtemp()) / "late.ts"
        with av.open(str(path), "w", format="mpegts") as out:
            stream = out.add_stream("mp2", rate=48000)
            stream.layout = "mono"
            pts = 30 * 48000
            for _ in range(200):  # ~4.3 s
                frame = av.AudioFrame.from_ndarray(np.full((1, 1152), 3000, dtype=np.int16), format="s16", layout="mono")
                frame.sample_rate = 48000
                frame.pts = pts
                frame.time_base = Fraction(1, 48000)
                pts += 1152
                for packet in stream.encode(frame):
                    out.mux(packet)
            for packet in stream.encode(None):
                out.mux(packet)
        with av.open(str(path)) as container:
            self.assertGreater(fc.media_offset(container), 29.0)
            audio, begin = fc.decode_audio(container, container.streams.audio[0], 0.0, 3.0)
        self.assertGreater(len(audio), 16000 * 2.5)
        self.assertLess(begin, 0.5)

    def test_nothing_decoded_is_not_marked_as_prepared(self):
        worker = fc.FilmTranscriber([], "", fc.PlayerClock(), fc.CueTimeline(), lambda: None)
        with mock.patch.object(fc, "decode_audio", return_value=(np.zeros(0, dtype=np.float32), 10.0)):
            self.assertEqual(worker._prepare(None, None, None, 10.0, 40.0, final=False), 10.0)
            self.assertFalse(worker.timeline.is_covered(20.0))
            worker._prepare(None, None, None, 10.0, 40.0, final=False)
            with self.assertRaises(RuntimeError):
                worker._prepare(None, None, None, 10.0, 40.0, final=False)


class RuntimeTests(unittest.TestCase):
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
        return runtime

    @staticmethod
    def report(**changes):
        base = {"event": "state", "tab": 1, "frame": 0, "page": "https://s/p", "time": 3.0, "paused": False,
                "stalled": False, "ended": False, "rate": 1.0, "duration": 5400.0, "src": "",
                "media": [{"url": "https://c/a.m3u8", "type": ""}], "doc": "d1", "seq": 1, "session": 1,
                "visible": True, "focused": True}
        base.update(changes)
        return base

    def test_a_reloaded_page_is_a_new_session(self):
        """#6"""
        runtime = self.runtime()
        runtime._film_bridge = object()
        self.addCleanup(lambda: setattr(runtime, "_film_bridge", None))
        with mock.patch.object(fc.FilmTranscriber, "start") as start:
            runtime._on_film_report(self.report(doc="d1"))
            first = runtime._film[3]
            runtime._on_film_report(self.report(doc="d2"))
        self.assertEqual(start.call_count, 2)
        self.assertTrue(first.stopped)

    def test_bridge_start_is_retried_while_the_port_frees(self):
        """#3"""
        runtime = self.runtime()
        runtime._film_bridge = None
        attempts = []

        def new_bridge():
            attempts.append(1)
            return None if len(attempts) < 3 else mock.Mock()

        with mock.patch.object(runtime, "_new_film_bridge", side_effect=new_bridge):
            runtime._start_film_bridge()
            end = time.time() + 3
            while time.time() < end and runtime._film_bridge is None:
                self.app.processEvents()
                time.sleep(0.02)
        self.assertEqual(len(attempts), 3)
        self.assertIsNotNone(runtime._film_bridge)
        runtime._film_bridge = None

    def test_a_failed_save_is_retried_on_the_next_contact(self):
        """#15"""
        runtime = self.runtime()
        runtime.host.save_extensions_meta.return_value = False
        runtime._remember_extension({"version": "1.3.0", "browser": "chrome"})
        self.assertNotIn("browser_extension_seen", runtime.host.cfg["extensions_meta"])
        runtime.host.save_extensions_meta.return_value = True
        runtime._note_extension_alive()
        self.assertEqual(runtime.host.save_extensions_meta.call_count, 2)
        self.assertIn("browser_extension_seen", runtime.host.cfg["extensions_meta"])

    def test_close_has_one_budget(self):
        """#14: an earlier save that takes the whole budget leaves no time for another wait."""
        runtime = self.runtime()
        runtime.CLIP_EXIT_BUDGET = 0.6
        release = threading.Event()
        self.addCleanup(release.set)
        runtime._clip_saver.submit(lambda: release.wait(5))
        written = []
        threads = []
        real = threading.Thread

        def spy(*args, **kwargs):
            thread = real(*args, **kwargs)
            threads.append(thread)
            return thread

        with mock.patch("luxai.extensions_runtime.threading.Thread", side_effect=spy):
            runtime._finish_clip_saves_at_exit(lambda: written.append(1))
        started = time.monotonic()
        threads[0].join(5)
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(written, [])


class TimelineTests(unittest.TestCase):
    def test_a_short_line_inside_a_different_one_stays(self):
        """#10"""
        timeline = fc.CueTimeline()
        timeline.add([fc.Cue(1.0, 2.0, "Go"), fc.Cue(1.0, 2.5, "Do not go")], 0, 10)
        self.assertEqual(sorted(c.text for c in timeline.cues), ["Do not go", "Go"])

    def test_a_line_cut_at_the_edge_is_still_the_same_line(self):
        timeline = fc.CueTimeline()
        timeline.add([fc.Cue(1.0, 4.0, "cut wor")], 0, 4)
        timeline.add([fc.Cue(1.0, 4.2, "cut words here")], 0, 10)
        self.assertEqual([c.text for c in timeline.cues], ["cut words here"])

    def test_many_separate_stretches_stay_sorted_and_fast(self):
        """#17: thousands of seeks."""
        timeline = fc.CueTimeline()
        started = time.perf_counter()
        for i in range(3000):
            start = ((i * 7919) % 3000) * 10.0
            timeline.add([], start, start + 5.0)
        timeline.add([], 0.0, 30000.0)  # finally everything
        self.assertLess(time.perf_counter() - started, 2.0)
        self.assertEqual(timeline.covered, [[0.0, 30000.0]])
        other = fc.CueTimeline()
        for start in (100.0, 10.0, 50.0):
            other.add([], start, start + 5.0)
        self.assertEqual(other.covered, [[10.0, 15.0], [50.0, 55.0], [100.0, 105.0]])
        self.assertTrue(other.is_covered(52.0))
        self.assertFalse(other.is_covered(56.0))
        self.assertEqual(other.covered_until(11.0), 15.0)
        other.add([], 15.0, 50.0)
        self.assertEqual(other.covered, [[10.0, 55.0], [100.0, 105.0]])

    def test_paused_player_gets_only_a_minute_ahead(self):
        """#16"""
        self.assertEqual(fc.PAUSED_AHEAD_SECONDS, 60.0)
        from luxai.extensions_catalog import PLUGINS
        live = next(plugin for plugin in PLUGINS if plugin.id == "live_captions")
        ahead = next(setting for setting in live.settings if setting.key == "film_ahead")
        self.assertEqual(ahead.default, "180")


class RecoveryPathTests(unittest.TestCase):
    """#7: the recovery uses the same destination rules as the installation."""

    def setUp(self):
        import Update
        self.Update = Update
        self.root = Path(tempfile.mkdtemp())
        self.staging = Path(tempfile.mkdtemp())
        for patcher in (mock.patch.object(Update, "ROOT", self.root),
                        mock.patch.object(Update, "_staging_root", return_value=self.staging)):
            patcher.start()
            self.addCleanup(patcher.stop)

    @unittest.skipUnless(sys.platform == "win32", "junctions")
    def test_a_junction_in_the_destination_blocks_the_recovery(self):
        import _winapi
        outside = Path(tempfile.mkdtemp())
        _winapi.CreateJunction(str(outside), str(self.root / "luxai"))
        (self.staging / "s1" / "luxai").mkdir(parents=True)
        (self.staging / "s1" / "luxai" / "x.py").write_bytes(b"new")
        (self.root / ".luxai_update_journal.json").write_text(json.dumps(
            {"staging": "s1", "files": ["luxai/x.py"], "sha256": {"luxai/x.py": hashlib.sha256(b"new").hexdigest()}}),
            encoding="utf-8")
        self.assertEqual(self.Update.resume_interrupted_update(), -1)
        self.assertFalse((outside / "x.py").exists())  # nothing written through the junction

    @unittest.skipUnless(sys.platform == "win32", "junctions")
    def test_a_staged_folder_behind_a_junction_is_refused(self):
        import _winapi
        elsewhere = Path(tempfile.mkdtemp())
        (elsewhere / "x.py").write_bytes(b"new")
        (self.staging / "s1").mkdir()
        _winapi.CreateJunction(str(elsewhere), str(self.staging / "s1" / "luxai"))
        (self.root / ".luxai_update_journal.json").write_text(json.dumps(
            {"staging": "s1", "files": ["luxai/x.py"], "sha256": {"luxai/x.py": hashlib.sha256(b"new").hexdigest()}}),
            encoding="utf-8")
        self.assertEqual(self.Update.resume_interrupted_update(), -1)
        self.assertFalse((self.root / "luxai" / "x.py").exists())


class ReminderTests(unittest.TestCase):
    now = dt.datetime(2026, 11, 21, 7, 0)

    def parse(self, text):
        from luxai.timers import parse_request
        return parse_request(text, self.now)

    def test_tomorrow_inside_the_message_does_not_move_the_day(self):
        """#8"""
        request = self.parse("remind me to check tomorrow forecast at 08:00")
        self.assertEqual((request.at.day, request.at.hour, request.label), (21, 8, "check tomorrow forecast"))
        request = self.parse("remind me at 08:00 tomorrowland opens")
        self.assertEqual((request.at.day, request.label), (21, "tomorrowland opens"))

    def test_tomorrow_next_to_the_time_still_counts(self):
        for text in ("remind me at 08:00 tomorrow to call Ana", "remind me tomorrow at 8:00 to call Ana",
                     "remind me tomorrow to call Ana at 8", "remind me to call Ana tomorrow at 8"):
            request = self.parse(text)
            self.assertEqual((request.at.day, request.at.hour, request.label), (22, 8, "call Ana"), text)

    def test_romanian_evening_word_is_not_in_the_label(self):
        request = self.parse("amintește-mi la 8 seara să sun pe Ana")
        self.assertEqual((request.at.hour, request.label), (20, "sun pe Ana"))

    def test_every_occurrence_counts_and_any_sign_refuses(self):
        """#9"""
        from luxai.timers import parse_duration
        self.assertEqual(self.parse("remind me in half an hour and half an hour to call Ana").seconds, 3600)
        self.assertIsNone(parse_duration("timer minus five minutes"))
        self.assertIsNone(parse_duration("таймер -час"))
        self.assertIsNone(parse_duration("таймер минус 5 минут"))
        self.assertEqual(parse_duration("таймер на час"), 3600)

    def test_reminder_understands_the_same_durations_as_the_timer(self):
        request = self.parse("Amintește-mi în un sfert de oră să sun")
        self.assertEqual((request.kind, request.seconds, request.label), ("timer", 900, "sun"))


class ExtensionCodeTests(unittest.TestCase):
    def test_extension_contract(self):
        """#2, #5, #11"""
        background = (ROOT / "browser_extension" / "background.js").read_text(encoding="utf-8")
        content = (ROOT / "browser_extension" / "content.js").read_text(encoding="utf-8")
        manifest = json.loads((ROOT / "browser_extension" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "1.3.0")
        self.assertIn('addEventListener("pageshow"', content)         # #2 a restored page is a new document
        self.assertIn("event.persisted", content)
        self.assertIn("old.url === item.url && old.frame === item.frame", background)  # #5 per frame
        self.assertIn("if (!wanted || details.tabId < 0", background)   # #11 nothing recorded with captions off
        self.assertIn("forgetMedia()", background)
        self.assertIn('getEntriesByType("resource")', content)         # the frame's own list instead


if __name__ == "__main__":
    unittest.main()
