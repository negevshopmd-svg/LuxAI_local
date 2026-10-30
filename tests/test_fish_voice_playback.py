"""Optional Fish synthesis uses the normal interruptible audio output path."""
from __future__ import annotations

import io
import sys
import threading
import types
import unittest
import wave
from unittest import mock

import numpy as np

from luxai import fish_tts, voices


def sample_wav():
    data = io.BytesIO()
    with wave.open(data, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes(b"\0\0" * 32)
    return data.getvalue()


class FishVoicePlaybackTests(unittest.TestCase):
    def patch(self, patcher):
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def setUp(self):
        self.settings = {
            "tts_enabled": True,
            "voice_engine": "fish",
            "fish_voice_id": "a" * 32,
            "voice_speed": 1.2,
            "voice_volume": 40,
            "language": "ru",
        }
        self.manager = voices.VoiceManager()
        self.patch(mock.patch.object(self.manager, "_load_config", return_value=self.settings))
        self.log = self.patch(mock.patch.object(self.manager, "_log"))
        self.select = self.patch(mock.patch.object(self.manager, "_select_model"))
        self.windows = self.patch(mock.patch.object(self.manager, "_windows_speak"))
        self.key = self.patch(mock.patch("luxai.secure_keys.get_api_key", return_value="private-fish-key"))
        self.wav = sample_wav()
        self.synthesize = self.patch(mock.patch.object(fish_tts, "synthesize", return_value=self.wav))
        self.samples = np.array([0.5, -0.5, 0.0], dtype=np.float32)
        self.soundfile = types.SimpleNamespace(read=mock.Mock(return_value=(self.samples, 24000)))
        self.audio = types.SimpleNamespace(play=mock.Mock(), wait=mock.Mock(), stop=mock.Mock())
        self.patch(mock.patch.dict(sys.modules, {"soundfile": self.soundfile, "sounddevice": self.audio}))
        voices.barge_in_ready.clear()
        voices.playback_active.clear()
        self.addCleanup(voices.barge_in_ready.clear)
        self.addCleanup(voices.playback_active.clear)

    def speak(self, text="Сэр, всё готово.", language="ru"):
        return self.manager.speak(text, language=language, cancel_token=voices._cancel_token())

    def assert_no_fallback(self):
        self.select.assert_not_called()
        self.windows.assert_not_called()

    def test_startup_does_not_request_cloud_speech_or_prepare_a_local_voice(self):
        self.assertFalse(self.manager.prepare(self.settings))
        self.synthesize.assert_not_called()
        self.key.assert_not_called()
        self.audio.play.assert_not_called()
        self.assert_no_fallback()

    def test_configured_voice_speed_language_volume_and_playback_flags(self):
        def synthesize(*_args, **kwargs):
            self.assertFalse(voices.barge_in_ready.is_set())
            self.assertFalse(kwargs["is_cancelled"]())
            return self.wav

        def wait():
            self.assertTrue(voices.barge_in_ready.is_set())

        self.synthesize.side_effect = synthesize
        self.audio.wait.side_effect = wait
        self.assertTrue(self.speak())
        self.key.assert_called_once_with("fish")
        args, kwargs = self.synthesize.call_args
        self.assertEqual(args, ("Сэр, всё готово.", "private-fish-key"))
        self.assertEqual(kwargs["voice_id"], "a" * 32)
        self.assertEqual(kwargs["speed"], 1.2)
        self.assertEqual(kwargs["language"], "ru")
        decode_args, decode_kwargs = self.soundfile.read.call_args
        self.assertEqual(decode_args[0].getvalue(), self.wav)
        self.assertEqual(decode_kwargs, {"dtype": "float32"})
        samples, rate = self.audio.play.call_args.args
        np.testing.assert_allclose(samples, self.samples * 0.4)
        self.assertEqual(rate, 24000)
        self.audio.wait.assert_called_once()
        self.assertFalse(voices.barge_in_ready.is_set())
        self.assert_no_fallback()

    def test_linked_jarvis_voice_is_used_when_no_custom_voice_is_configured(self):
        self.settings.pop("fish_voice_id")
        self.assertTrue(self.speak(language="ro"))
        self.assertEqual(self.synthesize.call_args.kwargs["voice_id"], fish_tts.DEFAULT_FISH_VOICE)
        self.assertEqual(self.synthesize.call_args.kwargs["language"], "ro")

    def test_missing_key_does_not_send_text_or_silently_change_provider(self):
        self.key.return_value = ""
        self.assertFalse(self.speak())
        self.synthesize.assert_not_called()
        self.audio.play.assert_not_called()
        self.assertIn("key not configured", self.log.call_args.args[0])
        self.assert_no_fallback()

    def test_provider_failure_is_sanitized_and_does_not_use_paid_or_local_fallback(self):
        self.synthesize.side_effect = fish_tts.FishTTSError("rate_limit")
        self.assertFalse(self.speak())
        self.assertEqual(self.log.call_args.args[0], "Fish Audio synthesis failed (rate_limit).")
        self.audio.play.assert_not_called()
        self.assertFalse(voices.barge_in_ready.is_set())
        self.assert_no_fallback()

    def test_unexpected_key_or_decoder_error_logs_no_key_text_or_error_body(self):
        self.soundfile.read.side_effect = RuntimeError("private-fish-key Сэр, всё готово. remote body")
        self.assertFalse(self.speak())
        self.assertEqual(self.log.call_args.args[0], "Fish Audio playback failed (RuntimeError).")
        self.audio.play.assert_not_called()
        self.assert_no_fallback()

    def test_reply_cancelled_before_start_never_looks_up_a_key(self):
        token = voices._cancel_token()
        voices.stop_speaking()
        self.assertFalse(self.manager.speak("Old reply", "en", token))
        self.key.assert_not_called()
        self.synthesize.assert_not_called()
        self.audio.play.assert_not_called()

    def test_stop_during_network_wait_prevents_a_late_success_from_playing(self):
        started = threading.Event()
        released = threading.Event()
        result = []
        observed_cancelled = []

        def synthesize(*_args, **kwargs):
            started.set()
            if not released.wait(2):
                raise RuntimeError("Test release timed out")
            observed_cancelled.append(kwargs["is_cancelled"]())
            # Even if the remote request has already succeeded, its old audio
            # must never play after the user stopped the pending reply.
            return self.wav

        self.synthesize.side_effect = synthesize
        worker = threading.Thread(target=lambda: result.append(self.speak()))
        try:
            worker.start()
            self.assertTrue(started.wait(1))
            self.assertFalse(voices.barge_in_ready.is_set())
            voices.stop_speaking()
        finally:
            released.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [False])
        self.assertEqual(observed_cancelled, [True])
        self.soundfile.read.assert_not_called()
        self.audio.play.assert_not_called()
        self.assertFalse(voices.barge_in_ready.is_set())

    def test_stop_after_decode_and_before_play_still_cancels_audio(self):
        def decode(*_args, **_kwargs):
            voices.stop_speaking()
            return self.samples, 24000

        self.soundfile.read.side_effect = decode
        self.assertFalse(self.speak())
        self.audio.play.assert_not_called()
        self.assertFalse(voices.barge_in_ready.is_set())

    def test_stopping_actual_playback_clears_both_speech_flags(self):
        self.audio.wait.side_effect = voices.stop_speaking
        with mock.patch.object(voices, "_manager", self.manager):
            self.assertFalse(voices.speak("Stop this reply", language="en"))
        self.audio.play.assert_called_once()
        self.audio.stop.assert_called_once()
        self.assertFalse(voices.playback_active.is_set())
        self.assertFalse(voices.barge_in_ready.is_set())


if __name__ == "__main__":
    unittest.main()
