"""Health reports and microphone level checks without hardware or networks."""
import contextlib
import io
import json
import threading
import types
import unittest
from unittest import mock

import numpy as np

from luxai import diagnostics


class DiagnosticsTests(unittest.TestCase):
    def audio(self):
        devices = [
            {"name": "Speaker", "max_input_channels": 0, "hostapi": 0},
            {"name": "USB microphone", "max_input_channels": 1, "hostapi": 0,
             "default_samplerate": 48000},
        ]
        hostapis = [{"name": "Windows WASAPI"}]
        def query_devices(device=None, kind=None):
            if kind is None and device is None:
                return devices
            return devices[1 if device is None else device]

        return types.SimpleNamespace(
            default=types.SimpleNamespace(device=(1, 0)),
            query_hostapis=mock.Mock(side_effect=lambda index=None: hostapis if index is None else hostapis[index]),
            query_devices=mock.Mock(side_effect=query_devices),
            devices=devices,
            PortAudioError=OSError,
        )

    def test_report_has_devices_versions_and_no_private_configuration(self):
        sd = self.audio()
        config = {
            "microphone_device": 1, "language": "ro", "whisper_model": "medium",
            "whisper_model_path": r"C:\Users\Private\Desktop\secret-model",
            "api_key": "do-not-export-this-key", "wake_prefix": "private phrase",
            "microphone_sensitivity": 1.5,
        }
        with mock.patch.dict("sys.modules", {"sounddevice": sd}), mock.patch(
            "luxai.ocr_setup.find_tesseract", return_value=None,
        ), mock.patch("luxai.ocr_setup.language_data_ready", return_value=False), mock.patch(
            "urllib.request.urlopen", side_effect=AssertionError("No network allowed"),
        ), mock.patch("luxai.secure_keys.get_api_key", side_effect=AssertionError("No key reads")):
            report = diagnostics.collect_diagnostics(config)
        encoded = json.dumps(report)
        self.assertNotIn("do-not-export-this-key", encoded)
        self.assertNotIn("Private", encoded)
        self.assertNotIn("private phrase", encoded)
        self.assertEqual(report["recognition"]["model"], "local/custom")
        self.assertEqual(report["recognition"]["language"], "ro")
        self.assertEqual(report["recognition"]["microphone_sensitivity"], 1.5)
        self.assertTrue(report["microphone"]["available"])
        self.assertTrue(report["microphone"]["selected_device_present"])
        self.assertEqual(report["microphone"]["devices"], [{
            "index": 1, "name": "USB microphone", "hostapi": "Windows WASAPI",
            "input_channels": 1, "default_sample_rate": 48000.0, "is_default": True,
        }])
        self.assertIn("PySide6", report["dependencies"])
        self.assertFalse(report["ocr"]["ready"])

    def test_driver_errors_are_reported_without_private_error_details(self):
        sd = self.audio()
        sd.query_devices.side_effect = RuntimeError("Driver failed for C:\\Users\\Private\\token.txt")
        with mock.patch.dict("sys.modules", {"sounddevice": sd}), mock.patch(
            "luxai.ocr_setup.find_tesseract", return_value=None,
        ), mock.patch("luxai.ocr_setup.language_data_ready", return_value=False):
            report = diagnostics.collect_diagnostics()
        self.assertFalse(report["microphone"]["available"])
        self.assertEqual(report["microphone"]["error"], "RuntimeError")
        self.assertNotIn("Private", json.dumps(report))

    def test_probe_measures_real_buffer_values_and_discards_audio(self):
        sd = self.audio()
        sd.check_input_settings = mock.Mock()
        block = np.full((3200, 1), 0.02, dtype=np.float32)
        stream_args = {}

        class Stream:
            def __init__(self, **kwargs):
                stream_args.update(kwargs)

            def __enter__(self):
                stream_args["callback"](block, len(block), None, types.SimpleNamespace(input_overflow=False))
                return self

            def __exit__(self, *_args):
                return False

        sd.InputStream = Stream
        levels = []
        with mock.patch.dict("sys.modules", {"sounddevice": sd}):
            result = diagnostics.microphone_probe(device=1, duration=0.2, level_callback=levels.append)
        self.assertTrue(result["ok"], result)
        self.assertEqual(stream_args["device"], 1)
        self.assertEqual(result["sample_rate"], 16000)
        self.assertEqual(result["frames"], 3200)
        self.assertAlmostEqual(result["rms"], 0.02, places=5)
        self.assertAlmostEqual(result["peak"], 0.02, places=5)
        self.assertFalse(result["silent"])
        self.assertFalse(result["clipped"])
        self.assertAlmostEqual(levels[0], 0.02, places=5)
        self.assertNotIn("audio", result)

    def test_probe_rate_fallback_stays_on_selected_device_and_reports_clipping(self):
        sd = self.audio()
        sd.check_input_settings = mock.Mock(side_effect=[ValueError("16000 not supported"), None])
        stream_args = {}

        class Stream:
            def __init__(self, **kwargs):
                stream_args.update(kwargs)

            def __enter__(self):
                stream_args["callback"](np.ones((9600, 1), dtype=np.float32), 9600, None,
                                        types.SimpleNamespace(input_overflow=True))
                return self

            def __exit__(self, *_args):
                return False

        sd.InputStream = Stream
        with mock.patch.dict("sys.modules", {"sounddevice": sd}):
            result = diagnostics.microphone_probe(device=1, duration=0.2,
                                                  level_callback=mock.Mock(side_effect=RuntimeError("UI closed")))
        self.assertTrue(result["ok"], result)
        self.assertEqual(stream_args["device"], 1)
        self.assertEqual(result["sample_rate"], 48000)
        self.assertTrue(result["clipped"])
        self.assertEqual(result["input_overflows"], 1)
        self.assertEqual([call.kwargs["device"] for call in sd.check_input_settings.call_args_list], [1, 1])

    def test_cancel_before_probe_does_not_open_a_device(self):
        cancel = threading.Event()
        cancel.set()
        with mock.patch.dict("sys.modules", {"sounddevice": None}):
            result = diagnostics.microphone_probe(stop_event=cancel)
        self.assertTrue(result["cancelled"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["frames"], 0)

    def test_probe_rejects_invalid_device_and_duration_without_driver_access(self):
        for kwargs in ({"device": -4}, {"device": True}, {"device": 1.5},
                       {"duration": -1}, {"duration": float("nan")}):
            with self.subTest(kwargs=kwargs), mock.patch.dict("sys.modules", {"sounddevice": None}):
                result = diagnostics.microphone_probe(**kwargs)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "ValueError")

    def test_probe_with_silent_buffers_is_distinct_from_driver_failure(self):
        sd = self.audio()
        sd.check_input_settings = mock.Mock()

        class Stream:
            def __init__(self, **kwargs):
                self.callback = kwargs["callback"]

            def __enter__(self):
                self.callback(np.zeros((1600, 1), dtype=np.float32), 1600, None, None)
                return self

            def __exit__(self, *_args):
                return False

        sd.InputStream = Stream
        with mock.patch.dict("sys.modules", {"sounddevice": sd}):
            result = diagnostics.microphone_probe(duration=0.1)
        self.assertTrue(result["ok"])
        self.assertTrue(result["silent"])
        self.assertEqual(result["rms"], 0)

    def test_reconnected_named_headset_resolves_new_index_for_report_and_probe(self):
        sd = self.audio()
        sd.devices[1]["name"] = "Different microphone"
        sd.devices.append({"name": "Wireless headset input", "max_input_channels": 1,
                           "hostapi": 0, "default_samplerate": 48000})
        sd.check_input_settings = mock.Mock()

        @contextlib.contextmanager
        def stream(**kwargs):
            kwargs["callback"](np.full((1600, 1), 0.03), 1600, None, None)
            yield

        sd.InputStream = mock.Mock(side_effect=stream)
        config = {"microphone_device": 1, "microphone_name": "Wireless headset input",
                  "microphone_hostapi": "Windows WASAPI"}
        with mock.patch.dict("sys.modules", {"sounddevice": sd}), mock.patch(
            "luxai.ocr_setup.find_tesseract", return_value=None,
        ), mock.patch("luxai.ocr_setup.language_data_ready", return_value=False):
            report = diagnostics.collect_diagnostics(config)
            result = diagnostics.microphone_probe(
                device=1, duration=0.1, microphone_name="Wireless headset input",
                microphone_hostapi="Windows WASAPI",
            )
        self.assertEqual(report["microphone"]["selected_device"], 1)
        self.assertEqual(report["microphone"]["resolved_device"], 2)
        self.assertTrue(report["microphone"]["selected_device_present"])
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["device"], 2)
        self.assertEqual(sd.InputStream.call_args.kwargs["device"], 2)

    def test_disconnected_saved_headset_never_opens_another_microphone(self):
        sd = self.audio()
        sd.InputStream = mock.Mock()
        with mock.patch.dict("sys.modules", {"sounddevice": sd}):
            result = diagnostics.microphone_probe(
                device=1, duration=0.1, microphone_name="Disconnected headset",
                microphone_hostapi="Windows WASAPI",
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "RuntimeError")
        sd.InputStream.assert_not_called()

    def test_no_driver_buffers_is_a_probe_failure_not_silence_success(self):
        sd = self.audio()
        sd.check_input_settings = mock.Mock()
        sd.InputStream = mock.MagicMock()
        with mock.patch.dict("sys.modules", {"sounddevice": sd}):
            result = diagnostics.microphone_probe(duration=0.1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "No audio frames received")
        self.assertEqual(result["frames"], 0)

    def test_probe_duration_cap_and_invalid_samples(self):
        sd = self.audio()
        sd.check_input_settings = mock.Mock()

        @contextlib.contextmanager
        def stream(**kwargs):
            kwargs["callback"](np.zeros((160000, 1)), 160000, None, None)
            yield

        sd.InputStream = mock.Mock(side_effect=stream)
        with mock.patch.dict("sys.modules", {"sounddevice": sd}):
            result = diagnostics.microphone_probe(duration=3600)
        self.assertEqual(result["requested_duration_seconds"], 10)
        self.assertEqual(result["duration_seconds"], 10)
        self.assertTrue(result["ok"])

        @contextlib.contextmanager
        def invalid_stream(**kwargs):
            kwargs["callback"](np.array([[float("nan")]]), 1, None, None)
            yield

        sd.InputStream = mock.Mock(side_effect=invalid_stream)
        with mock.patch.dict("sys.modules", {"sounddevice": sd}):
            result = diagnostics.microphone_probe(duration=0.1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "ValueError")

    def test_cli_microphone_capture_requires_explicit_flag_and_preserves_failure(self):
        with mock.patch.object(diagnostics, "collect_diagnostics", return_value={}), mock.patch.object(
            diagnostics, "microphone_probe", return_value={"ok": False, "error": "No input"},
        ) as probe, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(diagnostics.main([]), 0)
            probe.assert_not_called()
            self.assertEqual(diagnostics.main(["--microphone", "--device", "2", "--duration", "1"]), 1)
        self.assertIn('"microphone_probe"', output.getvalue())
        probe.assert_called_once_with(device=2, duration=1.0)


if __name__ == "__main__":
    unittest.main()
