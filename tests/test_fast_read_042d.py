"""0.4.2d: faster read aloud — short first piece, Fish prefetch, robust copy."""
from __future__ import annotations

import unittest
from unittest import mock

from luxai import translation


class ChunkTests(unittest.TestCase):
    def test_first_piece_is_short_then_bigger(self):
        text = "Первое предложение. " + "Это длинное продолжение текста с разными словами. " * 30
        pieces = translation.split_chunks(text)
        self.assertLessEqual(len(pieces[0]), 180)
        self.assertTrue(all(len(piece) <= 450 for piece in pieces))
        self.assertGreater(max(len(piece) for piece in pieces[1:]), 300)
        self.assertEqual(" ".join(pieces), " ".join(text.split()))  # nothing lost

    def test_short_text_stays_one_piece(self):
        self.assertEqual(translation.split_chunks("Короткий текст."), ["Короткий текст."])


class PrefetchTests(unittest.TestCase):
    def test_next_piece_is_prepared_and_played_from_memory(self):
        from luxai import voices
        manager = voices.VoiceManager.__new__(voices.VoiceManager)
        manager.config = {"voice_engine": "fish", "language": "ru", "voice_volume": 80}
        voices._prefetched.clear()
        token = voices._cancel_generation

        class Inline:
            def __init__(self, target, **kwargs):
                self.target = target

            def start(self):
                self.target()

        with mock.patch.object(voices.VoiceManager, "_load_config", return_value=manager.config), \
                mock.patch("luxai.secure_keys.get_api_key", return_value="k"), \
                mock.patch("luxai.fish_tts.synthesize", return_value=b"WAV") as synth, \
                mock.patch("luxai.voices.threading.Thread", Inline):
            manager.prefetch("Вторая часть.", "ru")
        synth.assert_called_once()
        with mock.patch.object(manager, "_play_wav", return_value=True) as play:
            self.assertTrue(manager._fish_speak("Вторая часть.", "ru", token))
        play.assert_called_once_with(b"WAV", token)
        self.assertEqual(voices._prefetched, {})

    def test_other_engines_are_not_prefetched(self):
        from luxai import voices
        manager = voices.VoiceManager.__new__(voices.VoiceManager)
        voices._prefetched.clear()
        with mock.patch.object(voices.VoiceManager, "_load_config", return_value={"voice_engine": "piper"}), \
                mock.patch("luxai.fish_tts.synthesize") as synth:
            manager.prefetch("Текст.", "ru")
        synth.assert_not_called()


class ReadLanguageTests(unittest.TestCase):
    def test_without_translation_each_piece_keeps_its_language(self):
        from PySide6.QtWidgets import QApplication
        from luxai import extensions_catalog as catalog
        from luxai.extensions_runtime import ExtensionsRuntime
        QApplication.instance() or QApplication([])
        host = mock.Mock()
        host.cfg = {"language": "ru"}
        host._speech_queue.qsize.return_value = 0
        runtime = ExtensionsRuntime(host)
        runtime.state = catalog.normalize_state({"read_aloud": {"enabled": True, "settings": {"translate": False}}})
        emitted = []
        runtime._read_chunk.connect(lambda text, language, generation: emitted.append((text, language)))
        runtime.read_text("This is an English sentence that should be read in English.", wait=True)
        QApplication.processEvents()
        self.assertEqual(emitted[0][1], "en")
        runtime.deleteLater()


if __name__ == "__main__":
    unittest.main()
