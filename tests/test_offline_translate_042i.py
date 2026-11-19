"""0.4.2i: offline NLLB translator first, the online model as fallback."""
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from luxai import offline_translate as ot  # noqa: E402
from luxai import translation  # noqa: E402


class PieceTests(unittest.TestCase):
    def test_short_text_is_one_piece(self):
        self.assertEqual(ot._pieces("  Hello   world. "), ["Hello world."])

    def test_long_text_splits_at_sentences_within_limit(self):
        text = " ".join(f"Sentence number {n} is here." for n in range(60))
        pieces = ot._pieces(text)
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(len(piece) <= ot.MAX_PIECE for piece in pieces))
        self.assertEqual(" ".join(pieces), " ".join(text.split()))

    def test_endless_sentence_is_cut_at_words(self):
        pieces = ot._pieces("word " * 300)
        self.assertTrue(all(0 < len(piece) <= ot.MAX_PIECE for piece in pieces))

    def test_supported_pairs(self):
        self.assertTrue(ot.supports("en", "ru"))
        self.assertFalse(ot.supports("ru", "ru"))
        self.assertFalse(ot.supports("other", "ru"))


class FallbackTests(unittest.TestCase):
    def test_missing_model_returns_none(self):
        with mock.patch.object(ot, "get", return_value=None):
            self.assertIsNone(ot.translate("Hello there.", "en", "ru"))

    def test_source_is_guessed_from_text(self):
        with mock.patch.object(ot, "translate", return_value="Привет") as call:
            self.assertEqual(translation.translate_offline("Hello, how are you doing today?", "ru"), "Привет")
        call.assert_called_once_with("Hello, how are you doing today?", "en", "ru")

    def test_known_source_wins(self):
        with mock.patch.object(ot, "translate", return_value="x") as call:
            translation.translate_offline("Bună ziua", "ru", source="ro")
        call.assert_called_once_with("Bună ziua", "ro", "ru")

    def test_no_download_during_tests(self):
        with mock.patch.dict(os.environ, {"LUXAI_NO_DOWNLOADS": "1"}), \
                mock.patch.object(ot, "installed", return_value=False), \
                mock.patch("threading.Thread") as thread:
            ot.download_in_background()
        thread.assert_not_called()


class CaptionQueueTests(unittest.TestCase):
    def _runtime(self, planner):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from luxai.extensions_runtime import ExtensionsRuntime
        host = mock.Mock()
        host.cfg = {}
        host.online_planner = planner
        return ExtensionsRuntime(host)

    def _wait(self, runtime, results):
        from PySide6.QtWidgets import QApplication
        end = time.time() + 5
        while not results and time.time() < end:
            QApplication.processEvents()
            time.sleep(0.01)

    def test_offline_is_used_before_the_online_model(self):
        planner = mock.Mock()
        runtime = self._runtime(planner)
        results = []
        runtime._cap_translated.connect(lambda o, t: results.append(t))
        with mock.patch("luxai.translation.translate_offline", return_value="Привет") as offline:
            runtime._queue_caption_translation(planner, "Hello there", "ru", "en")
            self._wait(runtime, results)
        self.assertEqual(results, ["Привет"])
        offline.assert_called_once_with("Hello there", "ru", "en")
        planner.translate_text.assert_not_called()

    def test_online_model_is_the_fallback(self):
        planner = mock.Mock()
        planner.translate_text.return_value = "Привет!"
        runtime = self._runtime(planner)
        results = []
        runtime._cap_translated.connect(lambda o, t: results.append(t))
        with mock.patch("luxai.translation.translate_offline", return_value=None):
            runtime._queue_caption_translation(planner, "Hello there", "ru", "en")
            self._wait(runtime, results)
        self.assertEqual(results, ["Привет!"])

    def test_works_without_online_planner(self):
        runtime = self._runtime(None)
        results = []
        runtime._cap_translated.connect(lambda o, t: results.append(t))
        with mock.patch("luxai.translation.translate_offline", return_value="Salut"):
            runtime._queue_caption_translation(None, "Hello", "ro", "en")
            self._wait(runtime, results)
        self.assertEqual(results, ["Salut"])


@unittest.skipUnless(ot.installed(), "the NLLB model is not downloaded here")
class RealModelTests(unittest.TestCase):
    def test_translates_and_uses_comma_letters(self):
        result = ot.translate("Don't forget to subscribe to the channel.", "en", "ro")
        self.assertTrue(result)
        self.assertNotIn("ş", result)
        self.assertNotIn("ţ", result)


if __name__ == "__main__":
    unittest.main()
