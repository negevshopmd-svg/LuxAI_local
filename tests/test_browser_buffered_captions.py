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
        worker._prepare_available(None, 4, np.full(4 * 16000, 0.2, dtype=np.float32))
        self.assertTrue(worker.ready.is_set())
        self.assertLess(clock.position(), timeline.cues[0].start)
        cue = timeline.cues[0]
        self.assertEqual(cue.translation, "Bună ziua")
        self.assertEqual(cue.shown(4.79), (0, 0))
        self.assertEqual(cue.shown(4.81)[1], 4)


if __name__ == "__main__":
    unittest.main()
