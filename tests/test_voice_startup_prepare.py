"""Startup warms the real synthesis path without playing speech or opening input."""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

from luxai import voices


class VoicePreparationTests(unittest.TestCase):
    def patch(self, patcher):
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def setUp(self):
        self.settings = {
            "tts_enabled": True, "voice_engine": "piper",
            "language": "ru", "response_language": "en",
            "voice_speed": 1.2, "voice_volume": 75,
        }
        self.manager = voices.VoiceManager()
        self.model = Path("selected-english.onnx")
        self.select = self.patch(mock.patch.object(self.manager, "_select_model", return_value=self.model))
        self.patch(mock.patch.object(self.manager, "_load_config", return_value=self.settings))
        self.patch(mock.patch.object(self.manager, "_log"))
        self.calls = []

        def synthesize(text, output, **kwargs):
            self.calls.append(text)
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b"\0\0" * 32)

        self.voice = types.SimpleNamespace(synthesize_wav=mock.Mock(side_effect=synthesize))
        self.load = mock.Mock(return_value=self.voice)
        self.audio = mock.MagicMock()
        self.sounddevice = types.SimpleNamespace(play=mock.Mock(), wait=mock.Mock(), InputStream=mock.Mock())
        self.soundfile = types.SimpleNamespace(read=mock.Mock(return_value=(self.audio, 16000)))
        self.modules = {
            "piper": types.SimpleNamespace(PiperVoice=types.SimpleNamespace(load=self.load)),
            "piper.config": types.SimpleNamespace(SynthesisConfig=lambda **kwargs: kwargs),
            "soundfile": self.soundfile,
            "sounddevice": self.sounddevice,
        }
        self.patch(mock.patch.dict(sys.modules, self.modules))

    def test_prepare_uses_reply_language_silently_and_first_reply_reuses_loaded_voice(self):
        token = voices._cancel_token()
        self.assertTrue(self.manager.prepare(self.settings))
        self.select.assert_called_once_with("en")
        self.load.assert_called_once_with(str(self.model))
        self.assertEqual(self.calls, ["Ready."])
        self.sounddevice.play.assert_not_called()
        self.sounddevice.wait.assert_not_called()
        self.sounddevice.InputStream.assert_not_called()
        self.soundfile.read.assert_not_called()
        self.assertTrue(self.manager.speak("First reply", language="en", cancel_token=token))
        self.load.assert_called_once_with(str(self.model))
        self.assertEqual(self.calls, ["Ready.", "First reply"])
        self.sounddevice.play.assert_called_once()
        self.sounddevice.wait.assert_called_once()

    def test_repeated_prepare_does_not_repeat_model_load_or_first_inference(self):
        self.assertTrue(self.manager.prepare(self.settings))
        self.assertTrue(self.manager.prepare(dict(self.settings, voice_volume=40)))
        self.load.assert_called_once()
        self.assertEqual(self.calls, ["Ready."])

    def test_disabled_speech_or_windows_engine_does_not_download_piper(self):
        for config in (dict(self.settings, tts_enabled=False),
                       dict(self.settings, voice_engine="windows")):
            with self.subTest(config=config):
                self.assertFalse(self.manager.prepare(config))
        self.select.assert_not_called()
        self.load.assert_not_called()
        self.sounddevice.play.assert_not_called()

    def test_prepare_uses_explicit_snapshot_without_reading_another_config_file(self):
        with mock.patch.object(self.manager, "_load_config", side_effect=AssertionError("Unrelated config")):
            self.assertTrue(self.manager.prepare(self.settings))
        self.assertEqual(self.manager.config, self.settings)

    def test_explicit_voice_is_selected_by_its_language_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "custom-voice.onnx"
            model.write_bytes(b"model placeholder")
            model.with_suffix(".onnx.json").write_text(json.dumps({"language": {"code": "en_US"}}))
            config = dict(self.settings, voice_model_path=str(model))
            # Use real voice selection here, instead of the mock used to
            # isolate ONNX loading in the remaining tests.
            with mock.patch.object(self.manager, "_select_model", wraps=voices.VoiceManager._select_model.__get__(self.manager)):
                with mock.patch.object(self.manager, "_download_voice") as download:
                    self.assertTrue(self.manager.prepare(config))
            download.assert_not_called()
            self.load.assert_called_once_with(str(model))

    def test_load_failure_can_retry_for_the_first_reply_and_fallback_has_cancel_token(self):
        token = voices._cancel_token()
        self.load.side_effect = [RuntimeError("Temporary model load failure"), self.voice]
        self.assertFalse(self.manager.prepare(self.settings))
        self.assertTrue(self.manager.speak("Try again", "en", token))
        self.assertEqual(self.load.call_count, 2)
        self.select.return_value = None
        with mock.patch.object(self.manager, "_windows_speak", return_value=True) as fallback:
            self.assertTrue(self.manager.speak("Windows fallback", "en", token))
        fallback.assert_called_once_with("Windows fallback", "en", token)

    def test_cancelled_reply_is_not_spoken_after_preparation(self):
        token = voices._cancel_token()
        self.assertTrue(self.manager.prepare(self.settings))
        with mock.patch("luxai.voices._was_cancelled", return_value=True):
            self.assertFalse(self.manager.speak("Old reply", "en", token))
        self.assertEqual(self.calls, ["Ready."])
        self.sounddevice.play.assert_not_called()

    def test_concurrent_reply_waits_until_silent_model_preparation_finishes(self):
        warming = threading.Event()
        release = threading.Event()
        spoken = threading.Event()
        original = self.voice.synthesize_wav.side_effect

        def synthesize(text, output, **kwargs):
            if text == "Ready.":
                warming.set()
                if not release.wait(2):
                    raise RuntimeError("Preparation test timed out")
            else:
                spoken.set()
            original(text, output, **kwargs)

        self.voice.synthesize_wav.side_effect = synthesize
        prepare = threading.Thread(target=self.manager.prepare, args=(self.settings,))
        reply = threading.Thread(target=self.manager.speak, args=("Reply", "en", voices._cancel_token()))
        try:
            prepare.start()
            self.assertTrue(warming.wait(1))
            reply.start()
            self.assertFalse(spoken.wait(0.1), "Concurrent Piper inference during preparation")
        finally:
            release.set()
            prepare.join(2)
            if reply.ident is not None:
                reply.join(2)
        self.assertFalse(prepare.is_alive())
        self.assertFalse(reply.is_alive())
        self.assertEqual(self.calls, ["Ready.", "Reply"])
        self.load.assert_called_once()


if __name__ == "__main__":
    unittest.main()
