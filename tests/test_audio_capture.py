"""Real capture-loop regressions with synthetic audio, never a physical mic/model."""
from __future__ import annotations

import math
import importlib.util
from contextlib import nullcontext
import sys
import types
import unittest
from unittest import mock

from luxai.audio_devices import resolve_microphone_device

if importlib.util.find_spec("numpy") is not None and importlib.util.find_spec("sounddevice") is not None:
    import numpy as np
    from luxai import voice
else:
    np = None
    voice = None


def device(name, inputs=1, hostapi=0, rate=48000):
    return {"name": name, "max_input_channels": inputs,
            "hostapi": hostapi, "default_samplerate": rate}


class DeviceSelectionTests(unittest.TestCase):
    def backend(self, devices, default=None):
        backend = types.SimpleNamespace(PortAudioError=RuntimeError)
        backend.query_devices = mock.Mock(side_effect=lambda *args: devices if not args else default)
        backend.query_hostapis = mock.Mock(side_effect=lambda index: {"name": ["MME", "WASAPI"][index]})
        return backend

    def test_default_is_explicitly_the_system_recording_device(self):
        headset = device("Headset microphone")
        backend = self.backend([headset], headset)
        selected, info = resolve_microphone_device(backend=backend)
        self.assertIsNone(selected)
        self.assertEqual(info["name"], "Headset microphone")
        backend.query_devices.assert_called_once_with(None, "input")

    def test_bluetooth_reconnect_recovers_name_and_host_api_after_index_reorders(self):
        devices = [device("Unrelated laptop mic"), device("Wireless headset", hostapi=0),
                   device("Wireless headset", hostapi=1)]
        selected, info = resolve_microphone_device(0, "Wireless headset", "WASAPI", backend=self.backend(devices))
        self.assertEqual(selected, 2)
        self.assertEqual(info["hostapi"], 1)

    def test_disconnected_selection_never_switches_to_unrelated_default_mic(self):
        backend = self.backend([device("Laptop mic")], device("Laptop mic"))
        with self.assertRaisesRegex(RuntimeError, "disconnected"):
            resolve_microphone_device(0, "Wireless headset", backend=backend)

    def test_stereo_playback_endpoint_is_not_a_microphone(self):
        backend = self.backend([device("Wireless stereo", inputs=0)])
        with self.assertRaisesRegex(RuntimeError, "playback endpoints cannot record"):
            resolve_microphone_device(0, backend=backend)

    def test_ambiguous_name_requires_selection(self):
        backend = self.backend([device("Headset"), device("Headset", hostapi=1)])
        with self.assertRaisesRegex(RuntimeError, "Several input devices"):
            resolve_microphone_device(9, "Headset", backend=backend)

    def test_missing_default_has_actionable_privacy_and_recording_guidance(self):
        backend = self.backend([], device("Speakers", inputs=0))
        with self.assertRaisesRegex(RuntimeError, "Windows Privacy"):
            resolve_microphone_device(backend=backend)


@unittest.skipIf(voice is None, "Audio dependencies unavailable; install numpy, sounddevice and PortAudio")
class CaptureLoopTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(voice.playback_active.clear)
        voice.playback_active.clear()
        self.models = []

        def build_model(*args, **kwargs):
            model = mock.Mock()
            model.transcribe.return_value = ([types.SimpleNamespace(text="Salut Jarvis")], None)
            self.models.append(model)
            return model

        self.model_module = types.SimpleNamespace(WhisperModel=mock.Mock(side_effect=build_model))
        self.patch_model = mock.patch.dict(sys.modules, {"faster_whisper": self.model_module})
        self.patch_model.start()
        self.addCleanup(self.patch_model.stop)
        self.patch_device = mock.patch.object(voice.sd, "query_devices", return_value=device("Test microphone", rate=16000))
        self.patch_device.start()
        self.addCleanup(self.patch_device.stop)
        self.patch_check = mock.patch.object(voice.sd, "check_input_settings")
        self.patch_check.start()
        self.addCleanup(self.patch_check.stop)

    def speech(self, amplitude=0.02):
        frame = np.sin(np.arange(480, dtype=np.float32) * (2 * math.pi * 440 / 16000)) * amplitude
        return np.concatenate([np.zeros(480 * 5, dtype=np.float32), np.tile(frame, 12),
                               np.zeros(480 * 96, dtype=np.float32)])

    def run_capture(self, audio, chunk_size=480, **kwargs):
        events = []
        listener = voice.VoiceListener(status_callback=lambda event, details: events.append((event, details)), **kwargs)
        streams = []

        class Stream:
            active = True

            def __init__(self, **settings):
                self.settings = settings
                self.closed = False
                streams.append(self)

            def __enter__(self):
                for offset in range(0, len(audio), chunk_size):
                    chunk = audio[offset:offset + chunk_size].reshape(-1, 1)
                    self.settings["callback"](chunk, len(chunk), None, False)
                return self

            def __exit__(self, *exc):
                self.closed = True

        with mock.patch.object(voice.sd, "InputStream", Stream), mock.patch.dict(sys.modules, {"webrtcvad": None}):
            generator = listener.listen()
            try:
                text = next(generator)
            finally:
                generator.close()
        self.assertTrue(streams[0].closed)
        return text, events, self.models[-1], streams[0]

    def test_quiet_microphone_crosses_gate_and_is_normalized_for_whisper(self):
        text, events, model, _ = self.run_capture(self.speech(amplitude=0.0012))
        self.assertEqual(text, "Salut Jarvis")
        captured = model.transcribe.call_args.args[0]
        self.assertGreater(float(np.max(np.abs(captured))), 0.01)
        self.assertLessEqual(float(np.max(np.abs(captured))), 1.0)
        self.assertIn("speech_started", [event for event, _ in events])
        self.assertIn("transcribing", [event for event, _ in events])

    def test_variable_callback_sizes_are_reassembled_not_discarded(self):
        text, events, model, stream = self.run_capture(self.speech(), chunk_size=240)
        self.assertEqual(text, "Salut Jarvis")
        self.assertEqual(stream.settings["channels"], 1)
        self.assertEqual(stream.settings["samplerate"], 16000)
        self.assertEqual(model.transcribe.call_count, 1)

    def test_sample_rate_falls_back_to_native_wireless_format(self):
        listener = voice.VoiceListener()
        listener._device_info["default_samplerate"] = 48000
        with mock.patch.object(voice.sd, "check_input_settings", side_effect=[voice.sd.PortAudioError("unsupported"), None]) as check:
            self.assertEqual(listener._sample_rate(), 48000)
        self.assertEqual([call.kwargs["samplerate"] for call in check.call_args_list], [16000, 48000])

    def test_open_failure_never_reports_listening(self):
        events = []
        listener = voice.VoiceListener(status_callback=lambda event, _: events.append(event))
        with mock.patch.object(voice.sd, "InputStream", side_effect=voice.sd.PortAudioError("access denied")):
            with self.assertRaises(voice.sd.PortAudioError):
                next(listener.listen())
        self.assertNotIn("listening", events)

    def test_model_load_error_is_distinct_from_microphone_error(self):
        self.model_module.WhisperModel.side_effect = OSError("broken model")
        with self.assertRaisesRegex(voice.ModelLoadError, "broken model"):
            voice.VoiceListener()

    def test_missing_microphone_fails_before_model_download(self):
        self.model_module.WhisperModel.reset_mock()
        with mock.patch.object(voice.sd, "query_devices", side_effect=voice.sd.PortAudioError("no input")):
            with self.assertRaisesRegex(RuntimeError, "No default recording microphone"):
                voice.VoiceListener()
        self.model_module.WhisperModel.assert_not_called()

    def test_zero_audio_and_loud_audio_are_not_amplified(self):
        zero = np.zeros(10, dtype=np.float32)
        loud = np.array([0.8, -0.8], dtype=np.float32)
        self.assertIs(voice.VoiceListener._normalize_audio(zero), zero)
        self.assertIs(voice.VoiceListener._normalize_audio(loud), loud)

    def test_resampling_preserves_duration_and_dtype(self):
        original = np.linspace(-0.5, 0.5, 1440, dtype=np.float32)
        resampled = voice.VoiceListener._resample_chunk(original, 48000, 480)
        self.assertEqual(len(resampled), 480)
        self.assertEqual(resampled.dtype, np.float32)
        self.assertAlmostEqual(float(resampled[0]), -0.5)

    def test_callback_exception_does_not_stop_capture(self):
        callback = mock.Mock(side_effect=RuntimeError("UI listener failed"))
        listener = voice.VoiceListener()
        listener.status_callback = callback
        with self.assertLogs("luxai.voice", level="ERROR"):
            listener._emit("listening", sample_rate=16000)
        self.assertFalse(listener._stop_event.is_set())

    def test_missing_driver_frames_raise_instead_of_keeping_green_mic_forever(self):
        events = []
        listener = voice.VoiceListener(status_callback=lambda event, _: events.append(event))

        class Stream:
            active = True

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                pass

        empty = mock.Mock()
        empty.get.side_effect = voice.queue.Empty
        clock = iter(range(100))
        with mock.patch.object(voice.sd, "InputStream", return_value=Stream()), \
                mock.patch.object(voice.queue, "Queue", return_value=empty), \
                mock.patch.object(voice.time, "monotonic", side_effect=lambda: next(clock)):
            with self.assertRaisesRegex(RuntimeError, "No audio frames received"):
                next(listener.listen())
        self.assertIn("input_stalled", events)
        self.assertEqual(self.models[0].transcribe.call_count, 0)

    def test_jarvis_speech_is_discarded_at_capture_time_during_transcription(self):
        self.assert_playback_exclusion()

    def test_post_playback_audio_is_not_lost_when_clock_ticks_tie(self):
        self.assert_playback_exclusion(coarse_clock=True)

    def assert_playback_exclusion(self, coarse_clock=False):
        listener = voice.VoiceListener()
        initial = self.speech()
        later = self.speech(amplitude=0.03)
        callback = None

        def feed(audio):
            for offset in range(0, len(audio), 480):
                chunk = audio[offset:offset + 480].reshape(-1, 1)
                callback(chunk, len(chunk), None, False)

        class Stream:
            active = True

            def __init__(self, **settings):
                nonlocal callback
                callback = settings["callback"]

            def __enter__(self):
                feed(initial)
                return self

            def __exit__(self, *exc):
                pass

        model = self.models[0]

        def transcribe(audio, **kwargs):
            if model.transcribe.call_count == 1:
                voice.playback_active.set()
                feed(self.speech(amplitude=0.8))
                voice.playback_active.clear()
                feed(later)
            return [types.SimpleNamespace(text="voice input")], None

        model.transcribe.side_effect = transcribe
        # All samples are synchronously supplied by this synthetic stream.
        # Exhausting them must fail directly, rather than waiting for a real
        # driver's timeout (or hanging when the test intentionally freezes time).
        class BufferedQueue(voice.queue.Queue):
            def get(self, *args, **kwargs):
                try:
                    return super().get(block=False)
                except voice.queue.Empty as exc:
                    raise AssertionError("Post-playback microphone frames were lost") from exc

        clock = mock.patch.object(voice.time, "monotonic", return_value=100.0) if coarse_clock else nullcontext()
        with mock.patch.object(voice.sd, "InputStream", Stream), \
                mock.patch.dict(sys.modules, {"webrtcvad": None}), \
                mock.patch.object(voice.queue, "Queue", BufferedQueue), clock:
            generator = listener.listen()
            try:
                self.assertEqual(next(generator), "voice input")
                self.assertEqual(next(generator), "voice input")
            finally:
                generator.close()
        self.assertEqual(model.transcribe.call_count, 2)
        for call in model.transcribe.call_args_list:
            self.assertLessEqual(float(np.max(np.abs(call.args[0]))), 0.101)


if __name__ == "__main__":
    unittest.main()
