"""Speech endpoint and interruption tests."""
import sys
import types
import unittest
from unittest import mock

from luxai.voice_rules import is_hallucinated_outro, is_stop_speech_command, speech_pause_seconds
from luxai import voices


class SpeechRuleTests(unittest.TestCase):
    def test_outros_are_not_commands(self):
        for phrase in ("Спасибо за внимание!", "Спасибо за просмотр.",
                       "Thanks for watching!", "Mulțumesc pentru vizionare."):
            self.assertTrue(is_hallucinated_outro(phrase), phrase)
        self.assertFalse(is_hallucinated_outro("Открой Telegram"))

    def test_spoken_stop_across_languages(self):
        for phrase in ("Стоп!", "Stop.", "Замолчи", "oprește-te", "taci"):
            self.assertTrue(is_stop_speech_command(phrase), phrase)
        self.assertFalse(is_stop_speech_command("Пожалуйста, останови игру"))

    def test_configurable_speech_pause(self):
        self.assertEqual(speech_pause_seconds(None), 2.3)
        self.assertEqual(speech_pause_seconds(3.4), 3.4)
        self.assertEqual(speech_pause_seconds("99"), 2.3)


    def test_voice_is_stopped_during_speech_without_normal_command(self):
        import importlib.util
        if not importlib.util.find_spec("numpy") or not importlib.util.find_spec("sounddevice"):
            self.skipTest("Native audio prerequisites unavailable")
        import numpy as np
        from luxai import voice
        frame = (0.02 * np.sin(np.arange(480) * 2 * np.pi * 440 / 16000)).astype(np.float32)
        audio = np.concatenate((np.zeros(480 * 4, dtype=np.float32),
                                np.tile(frame, 19), np.zeros(480 * 21, dtype=np.float32)))
        model = mock.Mock()
        model.transcribe.return_value = ([types.SimpleNamespace(text="Стоп.")], None)
        fake_whisper = types.SimpleNamespace(WhisperModel=mock.Mock(return_value=model))
        class Stream:
            active = True
            def __init__(self, **kwargs):
                self.callback = kwargs["callback"]
            def __enter__(self):
                voice.playback_active.set()
                voice.barge_in_ready.set()
                for i in range(0, len(audio), 480):
                    frame_bytes = audio[i:i + 480].reshape(-1, 1)
                    self.callback(frame_bytes, len(frame_bytes), None, False)
                return self
            def __exit__(self, *_):
                voice.playback_active.clear()
                voice.barge_in_ready.clear()
        device = {"name": "Mic", "max_input_channels": 1,
                  "default_samplerate": 16000}
        try:
            with mock.patch.dict(sys.modules, {"faster_whisper": fake_whisper,
                                                "webrtcvad": None}), \
                 mock.patch.object(voice.sd, "query_devices", return_value=device), \
                 mock.patch.object(voice.sd, "check_input_settings"), \
                 mock.patch.object(voice.sd, "InputStream", Stream):
                listener = voice.VoiceListener(language="ru")
                gen = listener.listen()
                try:
                    self.assertEqual(next(gen), "stop")
                finally:
                    gen.close()
            model.transcribe.assert_called_once()
        finally:
            voice.playback_active.clear()
            voice.barge_in_ready.clear()

    def test_stop_requests_sounddevice_stop(self):
        audio = types.SimpleNamespace(stop=mock.Mock())
        token = voices._cancel_token()
        with mock.patch.dict(sys.modules, {"sounddevice": audio}):
            voices.stop_speaking()
        self.assertTrue(voices._was_cancelled(token))
        audio.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
