"""Browser-buffered captions are prepared before their playback timestamps."""

import base64
import io
import json
import unittest
from fractions import Fraction
from types import SimpleNamespace

import av
import numpy as np

from luxai import film_captions as fc


class BufferedCaptionsTests(unittest.TestCase):
    def test_report_only_accepts_audio_from_the_visible_youtube_player(self):
        report = {"page": "https://www.youtube.com/watch?v=fixture", "active": True, "visible": True,
                  "buffer": {"kind": "webm", "track": 1, "offset": 0, "data": base64.b64encode(b"fixture").decode()}}
        encode = lambda: json.dumps(report).encode()
        self.assertNotIn("buffer", fc.parse_report(encode()))
        self.assertEqual(fc.parse_report(encode(), with_audio=True)["buffer"], ("webm", 1, 0, b"fixture"))
        report["page"] = "https://example.test/embedded/player"
        self.assertIsNotNone(fc.parse_report(encode(), with_audio=True))
        report["visible"] = False
        self.assertIsNone(fc.parse_report(encode(), with_audio=True))

    def test_real_webm_timestamps_keep_the_browser_offset(self):
        source = io.BytesIO()
        with av.open(source, "w", format="webm") as container:
            track = container.add_stream("libopus", rate=48000)
            track.layout = "mono"
            for i in range(70):
                frame = av.AudioFrame.from_ndarray(np.zeros((1, 960), dtype=np.int16), format="s16", layout="mono")
                frame.pts = i * 960
                frame.sample_rate = 48000
                frame.time_base = Fraction(1, 48000)
                for packet in track.encode(frame):
                    container.mux(packet)
            for packet in track.encode(None):
                container.mux(packet)
        start, audio = next(fc.decode_browser_audio("webm", 7.0, source.getvalue()))
        self.assertAlmostEqual(start, 7.0, delta=0.06)
        self.assertGreater(len(audio), 16000)

    def test_prepared_translation_becomes_visible_at_the_word(self):
        clock, timeline = fc.PlayerClock(), fc.CueTimeline()
        clock.update(4, True)
        words = [SimpleNamespace(word=" Hello", start=0.8, end=1.2),
                 SimpleNamespace(word=" there", start=1.2, end=1.7)]
        segment = SimpleNamespace(text="Hello there", words=words, start=0.8, end=1.7, no_speech_prob=0.0,
                                  avg_logprob=-0.2, compression_ratio=1.0)
        model = SimpleNamespace(transcribe=lambda *args, **kwargs: ([segment], None))
        worker = fc.BufferedFilmTranscriber([], "", clock, timeline, lambda: model, language="en",
                                            translate=lambda *_: "Bună ziua", video_duration=8)
        worker._prepare_available({}, 4, np.full(4 * 16000, 0.2, dtype=np.float32))
        self.assertTrue(worker.ready.is_set())
        self.assertLess(clock.position(), timeline.cues[0].start)
        cue = timeline.cues[0]
        self.assertEqual(cue.translation, "Bună ziua")
        self.assertEqual(cue.shown(4.79), (0, 0))
        self.assertEqual(cue.shown(4.81)[1], 4)

    def test_a_minute_of_available_audio_uses_the_precise_model_after_catch_up(self):
        clock, timeline = fc.PlayerClock(), fc.CueTimeline()
        clock.update(10, True)
        fast, precise = object(), object()
        worker = fc.BufferedFilmTranscriber([], "", clock, timeline, lambda: precise,
                                            fast_model_provider=lambda: fast)
        windows = []

        def prepare(model, audio, begin, start, end, final):
            self.assertAlmostEqual(len(audio) / 16000, end - start)
            windows.append((model, start, end))
            timeline.add([], start, end)
            return end

        worker._prepare_audio = prepare
        worker._prepare_available({}, 10, np.zeros(70 * 16000, dtype=np.float32))
        self.assertEqual(windows[0], (fast, 10, 18))
        self.assertGreaterEqual(len(windows), 3)
        self.assertIs(windows[1][0], fast)
        self.assertIs(windows[-1][0], precise)
        self.assertGreaterEqual(windows[-1][1] - clock.position(), fc.BROWSER_PRECISE_LEAD)
        self.assertEqual(timeline.covered_until(10), 70)

    def test_short_buffer_never_claims_a_minute_of_coverage(self):
        clock, timeline = fc.PlayerClock(), fc.CueTimeline()
        clock.update(10, True)
        worker = fc.BufferedFilmTranscriber([], "", clock, timeline, lambda: object())

        def prepare(_model, _audio, _begin, start, end, _final):
            timeline.add([], start, end)
            return end

        worker._prepare_audio = prepare
        worker._prepare_available({}, 10, np.zeros(12 * 16000, dtype=np.float32))
        self.assertEqual(timeline.covered_until(10), 22)

    def test_a_cut_phrase_gets_a_longer_retry_before_playback_catches_up(self):
        clock, timeline = fc.PlayerClock(), fc.CueTimeline()
        clock.update(0, True)
        worker = fc.BufferedFilmTranscriber([], "", clock, timeline, lambda: object())
        windows = []

        def prepare(_model, _audio, _begin, start, end, _final):
            windows.append((start, end))
            covered = 4.8 if len(windows) == 1 else end
            timeline.add([], start, covered)
            return covered

        worker._prepare_audio = prepare
        worker._prepare_available({}, 0, np.zeros(20 * 16000, dtype=np.float32))
        self.assertEqual(windows, [(0, 8), (4.8, 20)])

    def test_urgent_continuous_speech_commits_the_stable_words_before_retrying(self):
        clock, timeline = fc.PlayerClock(), fc.CueTimeline()
        clock.update(0, True)
        words = [SimpleNamespace(start=i, end=i + 0.8, word=" " + word)
                 for i, word in enumerate("a voice keeps talking without a break here".split())]
        segment = SimpleNamespace(text="a voice keeps talking without a break here", words=words,
                                  no_speech_prob=0.0, avg_logprob=-0.2, compression_ratio=1.0)
        model = SimpleNamespace(transcribe=lambda *args, **kwargs: ([segment], None))
        worker = fc.BufferedFilmTranscriber([], "", clock, timeline, lambda: model, language="en")
        worker._prepare_available({}, 0, np.ones(8 * 16000, dtype=np.float32))
        self.assertEqual(timeline.cues[0].text, "a voice keeps talking without a")
        self.assertAlmostEqual(timeline.covered_until(0), 5.8)
        self.assertGreater(timeline.cues[0].shown(3.2)[0], timeline.cues[0].shown(2.2)[0])

    def test_transport_accepts_a_larger_audio_window_without_changing_state_limit(self):
        audio = b"\0" * (1024 * 1024)
        report = {"page": "https://www.youtube.com/watch?v=fixture", "active": True, "visible": True,
                  "buffer": {"kind": "webm", "track": 1, "offset": 0, "data": base64.b64encode(audio).decode()}}
        encoded = json.dumps(report).encode()
        self.assertGreater(len(encoded), fc.MAX_BODY)
        self.assertLess(len(encoded), fc.MAX_AUDIO_BODY)
        self.assertEqual(fc.parse_report(encoded, with_audio=True)["buffer"][-1], audio)


if __name__ == "__main__":
    unittest.main()
