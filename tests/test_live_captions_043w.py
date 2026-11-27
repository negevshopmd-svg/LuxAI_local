"""0.4.3w: live captions — every line corrected (one precise pass for all waiting phrases, ending at a pause),
a correction that lost words is refused, the precise context is corrected text, language detection in the pass.

Benchmark (tests/captions_bench, real-time, Piper speech + noise, «Hybrid», auto language), final word error rate
before → after: en 1.9 % → 1.3–1.9 %, ru 20.3 % → 3.3–5.7 %, ro 15.4 % → 6.0–10.1 %; lost words ru 16 → 2.
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from luxai import live_captions as lc  # noqa: E402

RATE = lc.SAMPLE_RATE


def tone(seconds, level=0.2):
    t = np.arange(int(RATE * seconds)) / RATE
    return (level * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


class Precise:
    def __init__(self, text):
        self.text, self.calls = text, []

    def transcribe(self, audio, **kwargs):
        self.calls.append((len(audio), kwargs.get("initial_prompt")))
        return [SimpleNamespace(text=self.text, no_speech_prob=0.0, avg_logprob=-0.2, compression_ratio=1.2)], None


def engine_with(precise_text):
    many = []
    precise = Precise(precise_text)
    engine = lc.CaptionEngine(lambda: None, "ru", lambda _t: None, lambda _t: None,
                              precise_provider=lambda: precise, on_correct=lambda *_: None,
                              on_correct_many=lambda drafts, lines: many.append((drafts, lines)))
    engine._corrector = SimpleNamespace(submit=lambda job: None, close=lambda: None)  # run batches by hand
    return engine, precise, many


class HelperTests(unittest.TestCase):
    def test_sentences_become_lines(self):
        self.assertEqual(lc.split_sentences("Добрый вечер. Завтра будет дождь! Да? Хорошо."),
                         ["Добрый вечер.", "Завтра будет дождь!", "Да? Хорошо."])
        self.assertEqual(lc.split_sentences(""), [])

    def test_a_correction_must_say_about_as_much(self):
        drafts = ["Muzeul orașului va rămâne deschis până seara", "și în încheiere un câine din Scoția a învățat"]
        self.assertFalse(lc.plausible_correction(drafts, "Muzeul orașului va rămâne deschidat."))
        self.assertTrue(lc.plausible_correction(drafts, " ".join(drafts)))
        self.assertFalse(lc.plausible_correction(drafts, " ".join(drafts * 3)))
        self.assertTrue(lc.plausible_correction([], "a phrase only the precise model read"))


class BatchTests(unittest.TestCase):
    def test_all_waiting_phrases_are_corrected_in_one_pass(self):
        engine, precise, many = engine_with("Добрый вечер, в эфире новости. Завтра будет дождь.")
        engine._correct_later(tone(5.0), "добрый вечер в эфире", "", paused=False)  # cut in the middle of speech
        engine._correct_later(tone(2.0), "новости завтра будет дош", "", paused=True)
        engine._correct_batch()
        self.assertEqual(len(precise.calls), 1)  # ONE pass for both
        self.assertGreater(precise.calls[0][0], RATE * 7)
        self.assertEqual(many, [(["добрый вечер в эфире", "новости завтра будет дош"],
                                 ["Добрый вечер, в эфире новости.", "Завтра будет дождь."])])

    def test_a_pass_never_ends_at_a_cut_in_the_middle_of_speech(self):
        engine, precise, many = engine_with("whatever")
        engine._correct_later(tone(5.0), "first part of a long sentence", "", paused=False)
        engine._correct_batch()
        self.assertEqual(precise.calls, [])  # waits for the rest of the sentence
        self.assertEqual(len(engine._fix_queue), 1)

    def test_continuous_speech_is_still_corrected_when_much_is_waiting(self):
        engine, precise, many = engine_with("one two three four five six seven eight nine ten eleven twelve")
        for _ in range(4):
            engine._correct_later(tone(5.0), "one two three", "", paused=False)
        engine._correct_batch()
        self.assertEqual(len(precise.calls), 1)

    def test_the_next_pass_gets_the_corrected_text_as_context(self):
        engine, precise, _many = engine_with("Mulțumesc, după cum vedeți.")
        engine._correct_later(tone(2.0), "multumesc dupa cum vedeti", "multumesc", paused=True)
        engine._correct_batch()
        engine._correct_later(tone(2.0), "trenurile circula", "dupa cum vedeti", paused=True)
        engine._correct_batch()
        self.assertEqual(precise.calls[1][1], "Mulțumesc, după cum vedeți.")  # not the draft without diacritics

    def test_a_correction_that_lost_words_keeps_the_drafts(self):
        engine, _precise, many = engine_with("Muzeul orașului va rămâne deschidat.")
        engine._correct_later(tone(3.0), "Muzeul orașului va rămâne deschis până seara târziu", "", paused=False)
        engine._correct_later(tone(3.0), "și în încheiere un câine din Scoția a învățat să sune", "", paused=True)
        engine._correct_batch()
        self.assertEqual(many, [])


class DetectionTests(unittest.TestCase):
    def test_the_language_is_voted_from_the_transcription_pass(self):
        info = SimpleNamespace(language="ro", language_probability=0.93,
                               all_language_probs=[("ro", 0.93), ("it", 0.04), ("pt", 0.01)])
        model = mock.Mock()
        model.transcribe.return_value = ([SimpleNamespace(text="Bună seara", no_speech_prob=0.0, avg_logprob=-0.2,
                                                          compression_ratio=1.1)], info)
        engine = lc.CaptionEngine(lambda: model, None, lambda _t: None, lambda _t: None)
        with mock.patch("luxai.dictation.voiced_seconds", return_value=1.5):
            self.assertEqual(engine._transcribe(model, tone(2.0)), "Bună seara")
        model.detect_language.assert_not_called()  # no second pass for the detection
        self.assertIsNone(model.transcribe.call_args.kwargs["language"])
        self.assertEqual(engine._votes["ro"], 0.93)


class FilmLanguageTests(unittest.TestCase):
    """The film worker takes its language from the transcription pass, and only when Whisper is sure."""

    def run_piece(self, probability):
        from luxai import film_captions as fc
        info = SimpleNamespace(language="ro", language_probability=probability)
        model = mock.Mock()
        model.transcribe.return_value = ([], info)
        worker = fc.FilmTranscriber([], "", fc.PlayerClock(), fc.CueTimeline(), lambda: model)
        worker._prepare_audio(model, tone(3.0), 0.0, 0.0, 3.0, False)
        model.detect_language.assert_not_called()  # no extra pass while the video waits
        self.assertIsNone(model.transcribe.call_args.kwargs["language"])
        return worker.language

    def test_a_sure_detection_is_kept(self):
        self.assertEqual(self.run_piece(0.92), "ro")

    def test_an_unsure_detection_is_tried_again(self):
        self.assertIsNone(self.run_piece(0.45))  # e.g. a music intro: the next piece detects again


class BarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def bar(self):
        bar = lc.CaptionBar()
        self.addCleanup(bar.deleteLater)
        return bar

    def test_draft_lines_are_replaced_by_the_sentences(self):
        bar = self.bar()
        bar.lines = [("старая строка", "old line"), ("добрый вечер в", "good evening in"), ("эфире новости", "")]
        self.assertTrue(bar.replace_lines(["добрый вечер в", "эфире новости"], ["Добрый вечер, в эфире новости."],
                                          pending=True))
        self.assertEqual(bar.lines[0], ("старая строка", "old line"))
        self.assertEqual(bar.lines[1], ("Добрый вечер, в эфире новости.", "good evening in"))  # until the new one
        self.assertIn("Добрый вечер, в эфире новости.", bar.retranslating)

    def test_scrolled_away_drafts_change_nothing(self):
        bar = self.bar()
        bar.lines = [("a", ""), ("b", "")]
        self.assertFalse(bar.replace_lines(["x", "y"], ["X."]))
        self.assertEqual(bar.lines, [("a", ""), ("b", "")])

    def test_a_phrase_without_draft_is_added(self):
        bar = self.bar()
        self.assertTrue(bar.replace_lines([], ["Only the precise model heard this."]))
        self.assertEqual(bar.lines, [("Only the precise model heard this.", "")])


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_corrected_sentences_are_translated(self):
        from PySide6.QtCore import QCoreApplication, QEvent
        from luxai import extensions_catalog as catalog
        from luxai import extensions_runtime as runtime
        host = SimpleNamespace(cfg={"language": "ru"}, tray_icon=None, online_planner=None,
                               _queue_speech=lambda *a: None, stop_speaking=lambda: None)
        engine = runtime.ExtensionsRuntime(host)
        engine.state = catalog.normalize_state({"live_captions": {"enabled": True, "settings": {"translate": True}}})
        self.addCleanup(lambda: (engine.deleteLater(), QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)))
        engine._captions_bar = lc.CaptionBar()
        self.addCleanup(engine._captions_bar.deleteLater)
        engine._captions_bar.lines = [("good evening in the", ""), ("news tomorrow rain", "")]
        queued = []
        with mock.patch.object(engine, "_caption_target", return_value="ru"), \
                mock.patch.object(engine, "_queue_caption_translation",
                                  side_effect=lambda text, target, source="": queued.append(text)):
            engine._on_cap_corrected_many(["good evening in the", "news tomorrow rain"],
                                          ["Good evening, in the news.", "Tomorrow it will rain."])
        self.assertEqual([line for line, _t in engine._captions_bar.lines],
                         ["Good evening, in the news.", "Tomorrow it will rain."])
        self.assertEqual(queued, ["Good evening, in the news.", "Tomorrow it will rain."])

    def test_the_engine_reports_many_corrections_through_its_own_signal(self):
        source = (ROOT / "luxai" / "extensions_runtime.py").read_text(encoding="utf-8")
        self.assertIn("on_correct_many=(lambda drafts, lines: self._cap_engine_corrected_many.emit(", source)


if __name__ == "__main__":
    unittest.main()
