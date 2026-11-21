"""0.4.3m: wait for the first phrase after a jump; one line per sentence; the three small risks of 0.4.3l."""
from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
from PySide6.QtWidgets import QApplication

from luxai import film_captions as fc

ROOT = Path(__file__).resolve().parents[1]


class DuplicateTests(unittest.TestCase):
    def test_the_same_sentence_from_two_passes_is_shown_once(self):
        """Reported: the fast draft and the precise line of the same sentence were both on the bar."""
        timeline = fc.CueTimeline()
        timeline.add([fc.Cue(10.0, 14.0, "Броняо-британского марк первый была толщиной от 6 до 12 мм.", pass_id=1)], 8, 18)
        timeline.add([fc.Cue(10.3, 14.4, "Броня у британского марк 1 была толщиной от 6 до 12 мм.", pass_id=2)], 8, 30)
        self.assertEqual([c.text for c in timeline.cues], ["Броня у британского марк 1 была толщиной от 6 до 12 мм."])
        self.assertEqual(len(timeline.lines_at(14.5)), 1)

    def test_nearly_identical_words_merge_even_with_shifted_timing(self):
        timeline = fc.CueTimeline()
        timeline.add([fc.Cue(10.0, 13.0, "Расплавленную сталь заливают в форму.", pass_id=1)], 8, 15)
        timeline.add([fc.Cue(12.0, 15.5, "Расплавленную сталь заливают в форму", pass_id=2)], 8, 20)
        self.assertEqual(len(timeline.cues), 1)

    def test_consecutive_lines_of_one_pass_stay_even_added_one_by_one(self):
        timeline = fc.CueTimeline()
        timeline.add([fc.Cue(1, 4, "You can watch now", pass_id=7)], 0, 4)
        timeline.add([fc.Cue(2, 5, "You cannot watch now", pass_id=7)], 0, 10)
        self.assertEqual([c.text for c in timeline.cues], ["You can watch now", "You cannot watch now"])

    def test_short_line_inside_a_longer_one_from_another_pass_stays(self):
        timeline = fc.CueTimeline()
        timeline.add([fc.Cue(1.0, 2.0, "Go", pass_id=1)], 0, 3)
        timeline.add([fc.Cue(1.0, 2.5, "Do not go", pass_id=2)], 0, 3)
        self.assertEqual(sorted(c.text for c in timeline.cues), ["Do not go", "Go"])

    def test_the_worker_marks_its_lines_with_one_pass(self):
        worker = fc.FilmTranscriber([], "", fc.PlayerClock(), fc.CueTimeline(), lambda: None, language="en")
        segments = [SimpleNamespace(start=1, end=3, text="One line.", words=None),
                    SimpleNamespace(start=4, end=6, text="Another line.", words=None)]
        model = SimpleNamespace(transcribe=lambda *a, **k: (iter(segments), None))
        worker._prepare_audio(model, np.full(16000 * 10, 0.2, dtype=np.float32), 0.0, 0.0, 10.0, final=True)
        passes = {cue.pass_id for cue in worker.timeline.cues}
        self.assertEqual(len(passes), 1)
        self.assertNotIn(0, passes)


class JumpTests(unittest.TestCase):
    def test_the_clock_counts_jumps_not_normal_playback(self):
        clock = fc.PlayerClock()
        clock.update(10.0, paused=False, now=100.0)
        clock.update(11.0, paused=False, now=101.0)
        clock.update(13.1, paused=False, now=103.0)
        self.assertEqual(clock.jumps, 0)
        clock.update(130.0, paused=False, now=104.0)  # a seek
        self.assertEqual(clock.jumps, 1)
        clock.update(130.0, paused=True, now=110.0)  # paused there: no jump
        clock.update(129.0, paused=True, now=115.0)
        self.assertEqual(clock.jumps, 1)

    def test_work_on_the_old_place_stops_after_a_jump(self):
        clock = fc.PlayerClock()
        clock.update(10.0, paused=False)
        worker = fc.FilmTranscriber([], "", clock, fc.CueTimeline(), lambda: None, language="en",
                                    translate=lambda text, source: "T:" + text)
        translated = []

        def segments():
            yield SimpleNamespace(start=1, end=3, text="First line.", words=None)
            clock.update(400.0, paused=True)  # the user jumps while this piece is being recognised
            yield SimpleNamespace(start=4, end=6, text="Second line.", words=None)

        worker.translate = lambda text, source: translated.append(text) or "T:" + text
        model = SimpleNamespace(transcribe=lambda *a, **k: (segments(), None))
        following = worker._prepare_audio(model, np.full(16000 * 30, 0.2, dtype=np.float32), 10.0, 10.0, 40.0,
                                          final=False)
        self.assertEqual(translated, ["First line."])           # nothing more spent on the old place
        self.assertLess(following, 20.0)                        # the rest is not marked prepared
        self.assertFalse(worker.timeline.is_covered(30.0))

    def test_preparing_ahead_is_not_a_jump(self):
        clock = fc.PlayerClock()
        clock.update(0.0, paused=False)
        worker = fc.FilmTranscriber([], "", clock, fc.CueTimeline(), lambda: None, language="en")
        segments = [SimpleNamespace(start=1, end=3, text="Far ahead.", words=None)]
        model = SimpleNamespace(transcribe=lambda *a, **k: (iter(segments), None))
        self.assertEqual(worker._prepare_audio(model, np.full(16000 * 30, 0.2, dtype=np.float32), 120.0, 120.0,
                                               150.0, final=False), 150.0)


class SeekReadyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_after_a_jump_the_first_phrase_is_enough(self):
        """Measured on a real YouTube film: the first phrase was ready after 3.5 s but the video waited 6 s."""
        from luxai.extensions_runtime import ExtensionsRuntime
        host = mock.Mock()
        host.cfg = {"language": "ru", "extensions_meta": {}}
        runtime = ExtensionsRuntime(host)
        self.addCleanup(runtime.deleteLater)
        report = {"tab": 2, "frame": 0, "page": "https://www.youtube.com/watch?v=x", "doc": "abc", "session": 3,
                  "time": 360.0, "duration": 1200, "active": True, "visible": True, "preroll": True}
        timeline = fc.CueTimeline()
        worker = SimpleNamespace(stopped=False, ahead_seconds=180, audio_range=(358.9, 380.0), video_duration=1200)
        runtime._film = (runtime._film_key(report), fc.PlayerClock(), timeline, worker)
        timeline.add([fc.Cue(360.2, 363.0, "Расплавленную сталь заливают в форму.", "Oțelul topit e turnat.")],
                     359.0, 364.3)
        self.assertTrue(runtime._browser_opening_ready(dict(report, preroll_kind="seek")))
        self.assertFalse(runtime._browser_opening_ready(dict(report, preroll_kind="start")))  # the start keeps 12 s
        runtime._film = None


class BridgeTests(unittest.TestCase):
    def test_seek_hold_limit_and_kind(self):
        report = fc.parse_report(json.dumps({"tab": 1, "preroll": True, "preroll_kind": "seek"}).encode())
        self.assertEqual(report["preroll_kind"], "seek")
        self.assertEqual(fc.parse_report(json.dumps({"tab": 1, "preroll_kind": "x"}).encode())["preroll_kind"], "start")
        self.assertLessEqual(fc.SEEK_HOLD_MS, 8000)

    def test_audio_stamped_outside_the_film_is_ignored(self):
        import av
        import io
        from fractions import Fraction
        buffer = io.BytesIO()
        with av.open(buffer, "w", format="webm") as out:
            stream = out.add_stream("libopus", rate=48000)
            stream.layout = "mono"
            pts = 0
            for _ in range(100):
                frame = av.AudioFrame.from_ndarray(np.full((1, 960), 3000, dtype=np.int16), format="s16", layout="mono")
                frame.sample_rate = 48000
                frame.pts = pts
                frame.time_base = Fraction(1, 48000)
                pts += 960
                for packet in stream.encode(frame):
                    out.mux(packet)
            for packet in stream.encode(None):
                out.mux(packet)
        data = buffer.getvalue()
        inside = list(fc.decode_browser_audio("webm", 100.0, data, duration=600.0))
        outside = list(fc.decode_browser_audio("webm", 5000.0, data, duration=600.0))
        self.assertTrue(inside)
        self.assertEqual(outside, [])


class ExtensionCodeTests(unittest.TestCase):
    def test_extension_contract(self):
        content = (ROOT / "browser_extension" / "content.js").read_text(encoding="utf-8")
        background = (ROOT / "browser_extension" / "background.js").read_text(encoding="utf-8")
        manifest = json.loads((ROOT / "browser_extension" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "1.10.0")
        # Seeks: a real jump (10 s or more) waits for the first phrase; small skips never.
        self.assertIn("SEEK_JUMP = 10", content)
        self.assertIn('tryOpening(video, "seek")', content)
        self.assertIn("seekAllowedAt = performance.now() + 4000", content)
        # Risk 1: the player hook is permanent only on YouTube, elsewhere only while captions are on.
        hook = next(item for item in manifest["content_scripts"] if item["js"] == ["youtube_audio.js"])
        self.assertEqual(hook["matches"], ["*://*.youtube.com/*", "*://*.youtube-nocookie.com/*"])
        self.assertIn("scripting", manifest["permissions"])
        self.assertIn("registerContentScripts", background)
        self.assertIn("unregisterContentScripts", background)
        # Risk 2: audio only from a MediaSource player that is followed.
        self.assertIn("!/^blob:/i.test(packet.src)", content)
        # Risk 3: a closed tab is reported even when the worker forgot the tab.
        self.assertIn('else if (wanted !== false) enqueue(tabId, "closed", [])', background)
        self.assertIn("if (wanted !== false && slot.closed)", background)


if __name__ == "__main__":
    unittest.main()
