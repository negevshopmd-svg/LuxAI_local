"""0.4.2z: film captions prepared in advance (Chrome extension + local bridge)."""
from __future__ import annotations

import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
from PySide6.QtWidgets import QApplication

from luxai import film_captions as fc

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "chrome-extension://" + "a" * 32


class ClockTests(unittest.TestCase):
    def test_position_runs_while_playing_and_stops_when_paused(self):
        clock = fc.PlayerClock()
        clock.update(100.0, paused=False, rate=1.5, now=10.0)
        self.assertAlmostEqual(clock.position(now=12.0), 103.0)
        clock.update(103.0, paused=True, now=12.0)
        self.assertAlmostEqual(clock.position(now=20.0), 103.0)

    def test_a_silent_browser_makes_the_clock_stale(self):
        clock = fc.PlayerClock()
        self.assertFalse(clock.alive(now=1.0))
        clock.update(1.0, paused=False, now=1.0)
        self.assertTrue(clock.alive(now=3.0))
        self.assertFalse(clock.alive(now=1.0 + fc.STALE_SECONDS + 0.1))


class TimelineTests(unittest.TestCase):
    def test_coverage_merges_and_reports_its_end(self):
        timeline = fc.CueTimeline()
        timeline.add([], 0, 30)
        timeline.add([], 30, 60)
        timeline.add([], 100, 130)
        self.assertEqual(timeline.covered, [[0, 60], [100, 130]])
        self.assertTrue(timeline.is_covered(59.9))
        self.assertFalse(timeline.is_covered(70))
        self.assertEqual(timeline.covered_until(10), 60)
        self.assertEqual(timeline.covered_until(70), 70)

    def test_redone_lines_never_double(self):
        timeline = fc.CueTimeline()
        timeline.add([fc.Cue(10, 13, "cut wor")], 0, 13)
        timeline.add([fc.Cue(9.8, 14, "cut words here")], 12.8, 40)
        self.assertEqual([cue.text for cue in timeline.cues], ["cut words here"])

    def test_lines_shown_at_their_time_and_linger_briefly(self):
        timeline = fc.CueTimeline()
        timeline.add([fc.Cue(1, 3, "one"), fc.Cue(4, 6, "two"), fc.Cue(20, 22, "three")], 0, 30)
        self.assertEqual([c.text for c in timeline.lines_at(0.5)], [])
        self.assertEqual([c.text for c in timeline.lines_at(5)], ["one", "two"])
        self.assertEqual([c.text for c in timeline.lines_at(8.5)], ["two"])
        self.assertEqual([c.text for c in timeline.lines_at(15)], [])


class WordRevealTests(unittest.TestCase):
    """Words appear when they are spoken in the film, not the whole line at once."""

    def cue(self):
        words = [SimpleNamespace(word=" When", start=0.0), SimpleNamespace(word=" you", start=0.4),
                 SimpleNamespace(word=" call", start=0.6), SimpleNamespace(word=" someone.", start=1.0)]
        text = "When you call someone."
        return fc.Cue(100, 101.5, text, "Когда вы звоните кому-то.", words=fc.word_marks(words, 100.0, text))

    def test_words_appear_one_by_one(self):
        cue = self.cue()
        seen = []
        for moment in (99.9, 100.0, 100.5, 100.7, 101.2, 102.0):
            a, b = cue.shown(moment)
            seen.append((cue.text[:a], cue.translation[:b]))
        self.assertEqual(seen, [("", ""), ("When", "Когда"), ("When you", "Когда"), ("When you call", "Когда вы"),
                                ("When you call someone.", "Когда вы звоните кому-то."),
                                ("When you call someone.", "Когда вы звоните кому-то.")])

    def test_a_line_without_word_times_shows_whole(self):
        cue = fc.Cue(1, 3, "Hello there.", "Привет.")
        self.assertEqual(cue.shown(1.5), (12, 7))

    def test_translation_is_cut_only_between_words(self):
        self.assertEqual("Один два три четыре"[:fc.cut_at_word("Один два три четыре", 0.5)], "Один два")
        self.assertEqual(fc.cut_at_word("x", 1.0), 1)

    def test_bar_keeps_the_place_of_words_not_yet_spoken(self):
        from luxai.live_captions import CaptionBar
        QApplication.instance() or QApplication([])
        bar = CaptionBar()
        self.addCleanup(bar.deleteLater)
        bar.show_original = True
        bar.lines = [("When you call someone", "Когда вы звоните")]
        bar.reveal = {"When you call someone": (8, 5)}
        bar.render()
        html = bar.text.text()
        self.assertIn("When you<span style='color:rgba(0,0,0,0);'> call someone</span>", html)
        self.assertIn("Когда<span style='color:rgba(0,0,0,0);'> вы звоните</span>", html)


class ReportTests(unittest.TestCase):
    def test_valid_report(self):
        report = fc.parse_report(json.dumps({
            "tab": 3, "page": "https://site.example/film", "time": 181.5, "paused": False, "rate": 1,
            "duration": 5400, "src": "blob:https://x/1",
            "media": ["https://cdn.example/a.m3u8", "javascript:alert(1)", "file:///C:/x.mp4"]}).encode())
        self.assertEqual(report["media"], [{"url": "https://cdn.example/a.m3u8", "type": ""}])  # only http(s)
        self.assertEqual(report["time"], 181.5)

    def test_garbage_is_refused(self):
        for raw in (b"{", b"[]", json.dumps({"time": "x"}).encode(), json.dumps({"time": -5}).encode()):
            self.assertIsNone(fc.parse_report(raw), raw)

    def test_playlists_first_and_segments_dropped(self):
        ranked = fc.rank_candidates(["https://c/x/seg1.ts", "https://c/film.mp4", "https://c/master.m3u8",
                                     "https://c/film.mp4"])
        self.assertEqual(ranked, ["https://c/master.m3u8", "https://c/film.mp4"])


class BridgeTests(unittest.TestCase):
    def post(self, port, body, origin=ORIGIN, path="/v1/state", token="t" * 48):
        request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, method="POST",
                                         headers={"Content-Type": "application/json", "Origin": origin,
                                                  "X-Jarvis-Token": token})
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    def test_only_a_browser_extension_may_talk_to_jarvis(self):
        reports = []
        bridge = fc.BridgeServer(reports.append, port=47399, token="t" * 48)
        self.assertTrue(bridge.start())
        self.addCleanup(bridge.stop)
        body = json.dumps({"tab": 1, "time": 5, "paused": False, "media": ["https://c/a.m3u8"]}).encode()
        self.assertEqual(self.post(47399, body, origin="https://evil.example"), 403)  # a web page
        self.assertEqual(self.post(47399, body, origin=""), 403)
        self.assertEqual(self.post(47399, body, path="/other"), 403)
        self.assertEqual(self.post(47399, body, token="x" * 48), 401)  # another extension: no pairing secret
        self.assertEqual(self.post(47399, body, token=""), 401)
        self.assertEqual(self.post(47399, b"{", ), 400)
        self.assertEqual(reports, [])
        self.assertEqual(self.post(47399, body), 200)
        self.assertEqual(reports[0]["media"], [{"url": "https://c/a.m3u8", "type": ""}])

    def test_a_taken_port_does_not_crash(self):
        first = fc.BridgeServer(lambda _r: None, port=47398)
        self.assertTrue(first.start())
        self.addCleanup(first.stop)
        self.assertFalse(fc.BridgeServer(lambda _r: None, port=47398).start())


class FakeModel:
    def __init__(self, segments):
        self.segments = segments

    def transcribe(self, audio, **_kwargs):
        return self.segments, None


def segment(start, end, text):
    return SimpleNamespace(start=start, end=end, text=text, words=None)


class PrepareTests(unittest.TestCase):
    def transcriber(self, translate=None):
        return fc.FilmTranscriber(["https://c/a.m3u8"], "", fc.PlayerClock(), fc.CueTimeline(), lambda: None,
                                  language="en", translate=translate)

    def test_lines_are_placed_in_film_time_and_translated(self):
        worker = self.transcriber(translate=lambda text, source: "RU:" + text)
        audio = np.full(16000 * 30, 0.2, dtype=np.float32)
        with mock.patch.object(fc, "decode_audio", return_value=(audio, 120.0)):
            next_start = worker._prepare(FakeModel([segment(1, 4, "Hello there."), segment(10, 12, "See you soon.")]),
                                         None, None, 120.0, 150.0, final=False)
        self.assertEqual(next_start, 150.0)
        self.assertEqual([(c.start, c.end, c.text, c.translation) for c in worker.timeline.cues],
                         [(121.0, 124.0, "Hello there.", "RU:Hello there."), (130.0, 132.0, "See you soon.", "RU:See you soon.")])
        self.assertTrue(worker.timeline.is_covered(149))

    def test_a_line_cut_at_the_piece_end_is_redone_with_the_next_piece(self):
        worker = self.transcriber()
        audio = np.full(16000 * 30, 0.2, dtype=np.float32)
        with mock.patch.object(fc, "decode_audio", return_value=(audio, 0.0)):
            next_start = worker._prepare(FakeModel([segment(2, 5, "Kept."), segment(27, 29.8, "Cut in the mid")]),
                                         None, None, 0.0, 30.0, final=False)
        self.assertEqual([c.text for c in worker.timeline.cues], ["Kept."])
        self.assertAlmostEqual(next_start, 26.8)

    def test_translation_of_first_phrase_is_visible_to_timeline_before_decoding_next(self):
        worker = self.transcriber(translate=lambda text, source: "RO:" + text)
        audio = np.full(16000 * 30, 0.2, dtype=np.float32)

        def phrases():
            yield segment(1, 4, "First sentence.")
            self.assertTrue(worker.timeline.opening_ready(0))
            self.assertEqual(worker.timeline.lines_at(1)[0].translation, "RO:First sentence.")
            yield segment(27, 29.5, "Second sentence.")

        with mock.patch.object(fc, "decode_audio", return_value=(audio, 0.0)):
            worker._prepare(FakeModel(phrases()), None, None, 0.0, 30.0, final=False)
        self.assertNotIn("Second sentence.", [cue.text for cue in worker.timeline.lines_at(26.999)])
        second = worker.timeline.lines_at(27.0)[-1]
        self.assertEqual(second.translation, "RO:Second sentence.")
        self.assertTrue(second.provisional)

    def test_opening_waits_for_a_line_and_its_translation(self):
        timeline = fc.CueTimeline()
        timeline.add([], 0, 4)
        self.assertFalse(timeline.opening_ready(0))
        line = fc.Cue(1, 2, "First", translation_ready=False)
        timeline.add([line], 0, 4)
        self.assertFalse(timeline.opening_ready(0))
        line.translation_ready = True
        self.assertTrue(timeline.opening_ready(0))

    def test_choose_skips_ads_by_length(self):
        def opener(url, options, timeout):
            seconds = 30 if url.rsplit("/", 1)[-1] == "ad.mp4" else 5400  # the gateway keeps the file name
            return SimpleNamespace(duration=seconds * 1_000_000, close=lambda: None,
                                   streams=[SimpleNamespace(type="audio", bit_rate=64000)])
        worker = fc.FilmTranscriber(["https://c/ad.mp4", "https://c/film.m3u8"], "https://site/p", fc.PlayerClock(),
                                    fc.CueTimeline(), lambda: None, video_duration=5400, opener=opener)
        self.addCleanup(worker.stop)
        worker._choose()
        self.assertEqual(worker.url, "https://c/film.m3u8")

    def test_referer_and_browser_agent_are_sent(self):
        options = fc.media_options("https://site.example/watch/1")
        self.assertIn("Referer: https://site.example/watch/1", options["headers"])
        self.assertIn("Origin: https://site.example", options["headers"])
        self.assertIn("Mozilla", options["user_agent"])


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def runtime(self):
        from luxai import extensions_catalog as catalog
        from luxai.extensions_runtime import ExtensionsRuntime
        host = mock.Mock()
        host.cfg = {"language": "ru"}
        runtime = ExtensionsRuntime(host)
        self.addCleanup(runtime.deleteLater)
        runtime.state = catalog.normalize_state({"live_captions": {"enabled": True, "settings": {"translate": False}}})
        return runtime

    def test_prepared_lines_replace_the_live_captions_and_pause_them(self):
        from luxai.live_captions import CaptionBar
        runtime = self.runtime()
        bar = CaptionBar()
        self.addCleanup(bar.deleteLater)
        runtime._captions_bar = bar
        runtime._captions_engine = SimpleNamespace(paused=False)
        clock, timeline = fc.PlayerClock(), fc.CueTimeline()
        timeline.add([fc.Cue(10, 12, "Prepared line", "Строка")], 0, 60)
        clock.update(11.0, paused=True)
        runtime._film = (("k",), clock, timeline, SimpleNamespace(stopped=False, stop=lambda: None))
        runtime._film_tick()
        self.assertTrue(runtime._film_active)
        self.assertTrue(runtime._captions_engine.paused)
        self.assertEqual(bar.lines, [("Prepared line", "Строка")])
        runtime._on_cap_final("live text")  # the live engine's late line is ignored meanwhile
        self.assertEqual(bar.lines, [("Prepared line", "Строка")])
        timeline.add([fc.Cue(13, 14, "Already finished", "Too late")], 12, 15)
        clock.update(15.0, paused=True)
        runtime._film_tick()
        self.assertNotIn(("Already finished", "Too late"), bar.lines)
        runtime._on_cap_partial_translated("Old draft", "Late translation", runtime._cap_phrase)
        self.assertFalse(bar.partial_translation)
        clock.update(70.0, paused=True)  # not prepared there: back to live captions
        runtime._film_tick()
        self.assertFalse(runtime._film_active)
        self.assertFalse(runtime._captions_engine.paused)

    def test_reserve_uses_audio_available_for_the_selected_session(self):
        runtime = self.runtime()
        report = {"tab": 2, "frame": 0, "page": "https://example.org/film", "doc": "abc", "session": 3,
                  "time": 120, "duration": 500, "active": True, "visible": True}
        timeline = fc.CueTimeline()
        worker = SimpleNamespace(stopped=False, ahead_seconds=180, audio_range=(119, 145), video_duration=500)
        runtime._film = (runtime._film_key(report), fc.PlayerClock(), timeline, worker)
        self.assertTrue(runtime._browser_underrun(report))
        self.assertFalse(runtime._browser_opening_ready(report))
        timeline.add([fc.Cue(121, 124, "A line", "O replică")], 120, 125)
        self.assertFalse(runtime._browser_underrun(report))
        self.assertFalse(runtime._browser_opening_ready(report))
        worker.waiting_for_audio = True
        timeline.add([], 125, 133)
        self.assertTrue(runtime._browser_opening_ready(report))
        worker.waiting_for_audio = False
        # 12 s prepared is enough to start (OPENING_RESERVE_SECONDS); the worker stays ahead while it plays.
        self.assertTrue(runtime._browser_opening_ready(report))
        timeline.add([], 133, 143)
        self.assertTrue(runtime._browser_opening_ready(report))
        self.assertIsNone(runtime._browser_opening_ready(dict(report, session=4)))
        self.assertFalse(runtime._browser_underrun(dict(report, visible=False)))

    def test_a_new_film_starts_its_own_preparation(self):
        runtime = self.runtime()
        runtime.captions_visible = True
        runtime._film_bridge = object()
        started = []
        with mock.patch.object(fc.FilmTranscriber, "start", side_effect=lambda: started.append(1)):
            report = {"tab": 1, "page": "https://s/p", "time": 3.0, "paused": False, "rate": 1.0,
                      "duration": 5400.0, "media": ["https://c/a.m3u8"]}
            runtime._on_film_report(report)
            runtime._on_film_report(dict(report, time=4.0))       # same film: only the clock moves
            runtime._on_film_report(dict(report, page="https://s/other"))  # another film
        self.assertEqual(len(started), 2)
        self.assertEqual(runtime._film[0][1], "https://s/other")
        runtime._film_bridge = None


class ExtensionFilesTests(unittest.TestCase):
    def test_extension_is_shipped_and_talks_only_to_this_pc(self):
        folder = ROOT / "browser_extension"
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_version"], 3)
        background = (folder / "background.js").read_text(encoding="utf-8")
        self.assertIn('const JARVIS = "http://127.0.0.1:47321/v1/";', background)
        self.assertEqual(background.count("fetch(JARVIS"), 1)  # one destination only (+ its own pairing.json)
        self.assertIn('fetch(chrome.runtime.getURL("pairing.json")', background)
        self.assertTrue((folder / "icon128.png").is_file())
        import Update
        for name in ("manifest.json", "background.js", "content.js", "icon128.png"):
            self.assertFalse(Update.is_development_file(Path("browser_extension") / name))


if __name__ == "__main__":
    unittest.main()
