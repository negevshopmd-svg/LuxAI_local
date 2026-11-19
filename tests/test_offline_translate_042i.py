"""0.4.2i/0.4.2j: the offline NLLB translator is Jarvis' only translator."""
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
    def _runtime(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from luxai.extensions_runtime import ExtensionsRuntime
        host = mock.Mock()
        host.cfg = {}
        host.online_planner = None
        return ExtensionsRuntime(host)

    def _wait(self, results):
        from PySide6.QtWidgets import QApplication
        end = time.time() + 5
        while not results and time.time() < end:
            QApplication.processEvents()
            time.sleep(0.01)

    def test_offline_translator_with_spoken_language(self):
        runtime = self._runtime()
        results = []
        runtime._cap_translated.connect(lambda o, t: results.append(t))
        with mock.patch("luxai.translation.translate_offline", return_value="Привет") as offline:
            runtime._queue_caption_translation("Hello there", "ru", "en")
            self._wait(results)
        self.assertEqual(results, ["Привет"])
        offline.assert_called_once_with("Hello there", "ru", "en")

    def test_failure_shows_the_original(self):
        runtime = self._runtime()
        results = []
        runtime._cap_translated.connect(lambda o, t: results.append((o, t)))
        with mock.patch("luxai.translation.translate_offline", return_value=None):
            runtime._queue_caption_translation("Hello", "ro", "en")
            self._wait(results)
        self.assertEqual(results, [("Hello", "")])


class NoCloudTests(unittest.TestCase):
    def test_cloud_translation_is_gone(self):
        from luxai.online_agent import OnlinePlanner
        self.assertFalse(hasattr(OnlinePlanner, "translate_text"))
        self.assertFalse(hasattr(translation, "translate_locally"))
        source = (ROOT / "luxai" / "extensions_runtime.py").read_text(encoding="utf-8")
        self.assertNotIn("translate_text(", source)

    def test_source_languages(self):
        self.assertEqual(ot.source_language("Hello, how are you doing today?"), "en")
        self.assertEqual(ot.source_language("Bună ziua, ce mai faci astăzi?"), "ro")
        self.assertEqual(ot.source_language("Привет, как у тебя дела?"), "ru")
        self.assertEqual(ot.source_language("Привіт, як у тебе справи? Що нового?"), "uk")
        self.assertEqual(ot.source_language("Der Mond ist aufgegangen und die Sterne sind nicht da."), "de")
        self.assertEqual(ot.source_language("Je ne sais pas ce que tu veux dire avec ça."), "fr")
        self.assertEqual(ot.source_language("¿Dónde está el baño? No lo sé, pero es para todos."), "es")
        self.assertFalse(ot.supports("de", "de"))
        self.assertTrue(ot.supports("en", "de"))  # the chat may ask for German
        self.assertFalse(ot.supports("en", "ja"))

    def test_one_word_phrases_use_the_dictionary(self):
        self.assertEqual(ot._short_answer("Да.", "en"), "Yes.")
        self.assertEqual(ot._short_answer("- Thanks!", "ru"), "Спасибо!")
        self.assertEqual(ot._short_answer("Nein?", "ro"), "Nu?")
        self.assertEqual(ot._short_answer("Thank you.", "ro"), "Mulțumesc.")
        self.assertIsNone(ot._short_answer("You.", "ru"))  # a Whisper filler, not «thank you»
        self.assertIsNone(ot._short_answer("Да, я приду.", "en"))

    def test_short_pieces_skip_the_model(self):
        fake = mock.Mock()
        translator = ot.OfflineTranslator.__new__(ot.OfflineTranslator)
        translator.translator = fake
        translator._run = __import__("threading").Lock()
        self.assertEqual(translator.translate("Да. Нет!", "ru", "en"), "Yes. No!")
        fake.translate_batch.assert_not_called()

    def test_missing_model_starts_the_download(self):
        with mock.patch.object(ot, "get", return_value=None), \
                mock.patch.object(ot, "download_in_background") as download:
            self.assertIsNone(ot.translate("Hello there.", "en", "ru"))
        download.assert_called_once()


@unittest.skipUnless(ot.installed(), "the NLLB model is not downloaded here")
class RealModelTests(unittest.TestCase):
    def test_translates_and_uses_comma_letters(self):
        result = ot.translate("Don't forget to subscribe to the channel.", "en", "ro")
        self.assertTrue(result)
        self.assertNotIn("ş", result)
        self.assertNotIn("ţ", result)


if __name__ == "__main__":
    unittest.main()
