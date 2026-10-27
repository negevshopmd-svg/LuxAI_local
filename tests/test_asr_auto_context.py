"""Auto-language context and noise-loop rejection without a microphone/model."""
import importlib.util
import math
import sys
import types
import unittest
from unittest import mock

from luxai.voice_rules import (
    AUTO_PROMPT, ROMANIAN_PROMPT, is_repetitive_transcript, recognition_options,
)


class AutomaticRecognitionRulesTests(unittest.TestCase):
    def test_auto_uses_all_three_command_languages_without_forcing_one(self):
        for requested_beam, expected_beam in ((1, 3), (3, 3), (5, 5)):
            options = recognition_options(None, requested_beam)
            self.assertIsNone(options["language"])
            self.assertEqual(options["beam_size"], expected_beam)
            self.assertEqual(options["initial_prompt"], AUTO_PROMPT)
            self.assertFalse(options["condition_on_previous_text"])
        for phrase in ("Apasă", "нажми клавишу Q", "press the Q key", "War Thunder"):
            self.assertIn(phrase, AUTO_PROMPT)

    def test_explicit_languages_keep_their_existing_preferences(self):
        for language in ("ru", "en"):
            options = recognition_options(language, 1)
            self.assertEqual(options["language"], language)
            self.assertEqual(options["beam_size"], 1)
            self.assertIsNone(options["initial_prompt"])
        romanian = recognition_options("ro", 1)
        self.assertEqual(romanian["language"], "ro")
        self.assertEqual(romanian["initial_prompt"], ROMANIAN_PROMPT)
        self.assertEqual(romanian["beam_size"], 3)

    def test_near_whole_noise_character_and_token_loops_are_rejected(self):
        for text in ("B" + "e" * 1000, "Ṣe " * 18, "වි" * 40,
                     "ha " * 12, "tick tock " * 12):
            with self.subTest(text=text[:40]):
                self.assertTrue(is_repetitive_transcript(text))
        self.assertFalse(is_repetitive_transcript("ha " * 11))

    def test_quoted_literals_dictation_and_keyboard_requests_keep_repetitions(self):
        for text in ('"' + "a" * 30 + '"', "«" + "ha " * 14 + "»",
                     "Type " + "a" * 30, "Scrie " + "ha " * 14,
                     "Напиши " + "a" * 30, "Press " + "q" * 24,
                     "Жми " + "q" * 24, "Apasă " + "q" * 24,
                     "Press Q, then press Q", "Apasă tasta Q."):
            with self.subTest(text=text):
                self.assertFalse(is_repetitive_transcript(text))


@unittest.skipUnless(importlib.util.find_spec("numpy") and importlib.util.find_spec("sounddevice"),
                     "Audio prerequisites unavailable")
class CaptureRecognitionGuardTests(unittest.TestCase):
    def test_captured_noise_transcripts_are_discarded_before_next_valid_command(self):
        import numpy as np
        from luxai import voice

        voice.playback_active.clear()
        self.addCleanup(voice.playback_active.clear)
        self.addCleanup(voice.barge_in_ready.clear)
        frame = (np.sin(np.arange(480) * 2 * math.pi * 440 / 16000) * 0.02).astype(np.float32)
        phrase_audio = np.concatenate((np.zeros(480 * 5, dtype=np.float32),
                                       np.tile(frame, 12), np.zeros(480 * 96, dtype=np.float32)))
        audio = np.tile(phrase_audio, 4)
        model = mock.Mock()
        texts = ("B" + "e" * 1000, "Ṣe " * 18, "වි" * 40, "Apasă tasta Q.")
        model.transcribe.side_effect = [([types.SimpleNamespace(text=text)], None) for text in texts]
        fake_whisper = types.SimpleNamespace(WhisperModel=mock.Mock(return_value=model))
        events = []
        closed = []

        class Stream:
            active = True

            def __init__(self, **settings):
                self.callback = settings["callback"]

            def __enter__(self):
                for offset in range(0, len(audio), 480):
                    samples = audio[offset:offset + 480].reshape(-1, 1)
                    self.callback(samples, len(samples), None, False)
                return self

            def __exit__(self, *_):
                closed.append(True)

        # Exhausted synthetic frames fail immediately instead of waiting for a
        # physical driver's timeout if forwarding/regating regresses.
        class BufferedQueue(voice.queue.Queue):
            def get(self, *args, **kwargs):
                try:
                    return super().get(block=False)
                except voice.queue.Empty as exc:
                    raise AssertionError("Valid command after rejected noise was lost") from exc

        device = {"name": "Synthetic input", "max_input_channels": 1, "default_samplerate": 16000}
        with mock.patch.dict(sys.modules, {"faster_whisper": fake_whisper, "webrtcvad": None}), \
                mock.patch.object(voice.sd, "query_devices", return_value=device), \
                mock.patch.object(voice.sd, "check_input_settings"), \
                mock.patch.object(voice.sd, "InputStream", Stream), \
                mock.patch.object(voice.queue, "Queue", BufferedQueue):
            listener = voice.VoiceListener(language="auto", beam_size=1,
                                           status_callback=lambda event, _: events.append(event))
            generator = listener.listen()
            try:
                self.assertEqual(next(generator), "Apasă tasta Q.")
            finally:
                generator.close()
        self.assertEqual(model.transcribe.call_count, 4)
        self.assertEqual(events.count("ignored_hallucination"), 3)
        self.assertEqual(closed, [True])
        for call in model.transcribe.call_args_list:
            self.assertIsInstance(call.args[0], np.ndarray)
            self.assertIsNone(call.kwargs["language"])
            self.assertEqual(call.kwargs["initial_prompt"], AUTO_PROMPT)
            self.assertEqual(call.kwargs["beam_size"], 3)


if __name__ == "__main__":
    unittest.main()
