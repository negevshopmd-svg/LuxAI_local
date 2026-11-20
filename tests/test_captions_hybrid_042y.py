"""0.4.2y: hybrid live captions (instant draft + precise correction), quiet sources, large-v3 option."""
from __future__ import annotations

import time
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np
from PySide6.QtWidgets import QApplication

from luxai import extensions_catalog as catalog
from luxai import live_captions as lc

RATE = 16000


def tone(seconds, level=0.2):
    t = np.arange(int(RATE * seconds)) / RATE
    return (level * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def quiet(seconds):
    return np.zeros(int(RATE * seconds), dtype=np.float32)


class FakeModel:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    def transcribe(self, audio, **_kwargs):
        self.calls += 1
        return ([SimpleNamespace(text=self.text)] if self.text else []), None

    def detect_language(self, _audio):
        return "en", 0.99, [("en", 0.99)]


class ModelChoiceTests(unittest.TestCase):
    def test_hybrid_is_the_default_and_models_follow_the_language(self):
        plugin = catalog.PLUGIN_BY_ID["live_captions"]
        self.assertEqual(catalog.default_settings(plugin)["quality"], "hybrid")
        self.assertEqual(lc.hybrid_draft_model("en"), "base")
        self.assertEqual(lc.hybrid_precise_model("en"), "small")
        for language in ("ru", "ro", None):
            self.assertEqual(lc.hybrid_draft_model(language), "small")
            self.assertEqual(lc.hybrid_precise_model(language), "large-v3-turbo")

    def test_large_v3_is_offered_for_voice_recognition(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / "luxai" / "settings_panel.py").read_text(encoding="utf-8")
        for name in ('"small"', '"medium"', '"large-v3-turbo"', '"large-v3")'):
            self.assertIn(name, source)


class HybridEngineTests(unittest.TestCase):
    def run_phrase(self, draft_text, precise_text):
        finals, corrections = [], []
        precise = FakeModel(precise_text)
        engine = lc.CaptionEngine(lambda: None, "en", lambda _t: None, finals.append,
                                  precise_provider=lambda: precise,
                                  on_correct=lambda old, new: corrections.append((old, new)))
        engine.feed(tone(1.5))
        engine.feed(quiet(0.6))
        with mock.patch("luxai.dictation.voiced_seconds", return_value=1.0):
            self.assertTrue(engine.step(FakeModel(draft_text)))
            end = time.time() + 3
            while time.time() < end and engine._corrector is not None and not engine._corrector.idle():
                time.sleep(0.01)
            if engine._corrector is not None:
                engine._corrector.wait(3)
        return finals, corrections

    def test_draft_line_first_then_precise_correction(self):
        finals, corrections = self.run_phrase("when you close", "when you call")
        self.assertEqual(finals, ["when you close"])
        self.assertEqual(corrections, [("when you close", "when you call")])

    def test_same_words_need_no_correction(self):
        _finals, corrections = self.run_phrase("You are here.", "you are here")
        self.assertEqual(corrections, [])

    def test_a_phrase_the_draft_dropped_is_read_by_the_precise_model(self):
        finals, corrections = self.run_phrase("", "the lost half sentence")
        self.assertEqual(finals, [])
        self.assertEqual(corrections, [("", "the lost half sentence")])

    def test_without_hybrid_nothing_runs_in_the_background(self):
        finals = []
        engine = lc.CaptionEngine(lambda: None, "en", lambda _t: None, finals.append)
        engine.feed(tone(1.5))
        engine.feed(quiet(0.6))
        with mock.patch("luxai.dictation.voiced_seconds", return_value=1.0):
            engine.step(FakeModel("hello there"))
        self.assertEqual(finals, ["hello there"])
        self.assertIsNone(engine._corrector)


class QuietSourceTests(unittest.TestCase):
    def test_quiet_speech_opens_the_gate(self):
        """A quiet video (peak ~0.01) never reached the fixed 0.008 gate: whole sentences were lost."""
        segmenter = lc.PhraseSegmenter()
        segmenter.feed(tone(1.0, level=0.005))
        self.assertTrue(segmenter.heard_speech)

    def test_loud_source_keeps_the_normal_gate(self):
        segmenter = lc.PhraseSegmenter()
        segmenter.feed(tone(1.0, level=0.5))
        self.assertEqual(segmenter.active_threshold, segmenter.threshold)

    def test_silence_is_still_silence(self):
        segmenter = lc.PhraseSegmenter()
        segmenter.feed(quiet(2))
        self.assertFalse(segmenter.heard_speech)

    def test_level_up_amplifies_quiet_audio_only(self):
        self.assertAlmostEqual(float(np.abs(lc.level_up(tone(0.5, 0.01))).max()), 0.1, places=2)
        loud = tone(0.5, 0.5)
        self.assertIs(lc.level_up(loud), loud)


class BarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def bar(self):
        bar = lc.CaptionBar()
        self.addCleanup(bar.deleteLater)
        return bar

    def test_corrected_line_keeps_its_translation_until_the_new_one(self):
        bar = self.bar()
        bar.add_final("when you close", "когда ты закроешь")
        self.assertTrue(bar.correct_line("when you close", "when you call", pending=True))
        self.assertEqual(bar.lines[-1], ("when you call", "когда ты закроешь"))
        bar.set_translation("when you call", "когда ты звонишь")
        self.assertEqual(bar.lines[-1], ("when you call", "когда ты звонишь"))

    def test_failed_retranslation_keeps_the_old_translation(self):
        bar = self.bar()
        bar.add_final("a", "а")
        bar.correct_line("a", "b", pending=True)
        bar.set_translation("b", "")
        self.assertEqual(bar.lines[-1], ("b", "а"))

    def test_draft_translation_is_shown_on_the_partial_line(self):
        bar = self.bar()
        bar.set_partial("hello wor", "привет ми")
        self.assertEqual(bar.visible_lines()[-1], ("hello wor", "привет ми"))
        bar.set_partial("hello world")  # the old draft translation stays until a newer one arrives
        self.assertEqual(bar.visible_lines()[-1], ("hello world", "привет ми"))

    def test_scrolled_away_line_is_not_corrected(self):
        self.assertFalse(self.bar().correct_line("gone", "new"))


class MigrationTests(unittest.TestCase):
    def test_saved_balanced_becomes_hybrid_once(self):
        from luxai.extensions_runtime import ExtensionsRuntime
        QApplication.instance() or QApplication([])
        host = mock.Mock()
        host.cfg = {"language": "ru", "extensions_meta": {}}
        runtime = ExtensionsRuntime(host)
        self.addCleanup(runtime.deleteLater)
        runtime.state = catalog.normalize_state({"live_captions": {"enabled": True, "settings": {"quality": "balanced"}}})
        runtime._migrate_caption_quality()
        host.update_extension_setting.assert_called_once_with("live_captions", "quality", "hybrid")
        self.assertTrue(host.cfg["extensions_meta"]["captions_hybrid_migrated"])
        host.update_extension_setting.reset_mock()
        runtime._migrate_caption_quality()  # never again: a later choice of the user stays
        host.update_extension_setting.assert_not_called()


if __name__ == "__main__":
    unittest.main()
