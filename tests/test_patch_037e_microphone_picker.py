"""0.3.7e: reduce Windows microphone duplicates without changing routing."""
from __future__ import annotations

import unittest
from unittest import mock

from luxai.audio_devices import (
    microphone_display_entries, microphone_display_name, resolve_microphone_device,
)


HOSTS = [
    {"name": "MME"}, {"name": "Windows DirectSound"},
    {"name": "Windows WASAPI"}, {"name": "Windows WDM-KS"},
]


def device(name, hostapi=2, inputs=1):
    return {"name": name, "hostapi": hostapi, "max_input_channels": inputs,
            "default_samplerate": 48000}


class CompactAudioDeviceTests(unittest.TestCase):
    def test_prefers_wasapi_and_friendly_labels(self):
        devices = [
            device("Микрофон (BlackShark V3 X PS USB)", 0),
            device("Микрофон (Steam Streaming Microphone)", 0),
            device("Микрофон (BlackShark V3 X PS USB)", 1),
            device("Микрофон (High Definition Audio Device)", 1),
            device("Микрофон (BlackShark V3 X PS USB)", 2),
            device("Микрофон (Steam Streaming Microphone)", 2),
            device("Микрофон (High Definition Audio Device)", 2),
            device("Микрофон (HD Audio Microphone)", 3),
            device("Speakers (playback)", 2, inputs=0),
        ]
        actual = microphone_display_entries(devices, HOSTS)
        self.assertEqual([i for i, _, _ in actual], [4, 5, 6])
        self.assertEqual([microphone_display_name(name) for _, name, _ in actual],
                         ["BlackShark V3 X PS USB", "Steam Streaming Microphone",
                          "High Definition Audio Device"])

    def test_fallback_without_wasapi_and_non_windows_unchanged(self):
        devices = [device("Headset", 0), device("Headset", 1),
                   device("Headset", 3), device("Playback", 2, inputs=0)]
        self.assertEqual(
            microphone_display_entries(devices, HOSTS),
            [(1, "Headset", "Windows DirectSound")],
        )
        self.assertEqual(
            microphone_display_entries([device("Mic A", 0), device("Mic B", 1)],
                                       [{"name": "ALSA"}, {"name": "PulseAudio"}]),
            [(0, "Mic A", "ALSA"), (1, "Mic B", "PulseAudio")],
        )

    def test_duplicate_real_devices_on_one_backend_are_kept(self):
        actual = microphone_display_entries(
            [device("USB Microphone"), device("USB Microphone")], HOSTS)
        self.assertEqual(len(actual), 2)

    def test_display_name_does_not_modify_audio_identity(self):
        self.assertEqual(microphone_display_name("Microphone (Blue Yeti)"), "Blue Yeti")
        self.assertEqual(microphone_display_name("Mic (USB Audio)"), "USB Audio")
        self.assertEqual(microphone_display_name("Steam Streaming Microphone"),
                         "Steam Streaming Microphone")

    def test_ui_no_backend_suffix_and_migrates_old_mme_headset(self):
        try:
            from PySide6.QtWidgets import QApplication
            from luxai.settings_panel import SettingsPanel
        except ImportError:
            self.skipTest("PySide6 not available")
        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)
        devices = [
            device("Микрофон (BlackShark V3 X PS USB)", 0),
            device("Микрофон (Steam Streaming Microphone)", 0),
            device("Микрофон (BlackShark V3 X PS USB)", 2),
            device("Микрофон (Steam Streaming Microphone)", 2),
        ]
        config = {
            "microphone_device": 0, "microphone_name": devices[0]["name"],
            "microphone_hostapi": "MME", "microphone_enabled": False,
        }
        with (mock.patch("sounddevice.query_hostapis", return_value=HOSTS),
              mock.patch("sounddevice.query_devices", return_value=devices)):
            panel = SettingsPanel(config, lambda: None, lambda: None, lambda: None)
            self.addCleanup(panel.close)
            self.assertEqual(
                [panel.mic_device.itemText(i) for i in range(panel.mic_device.count())],
                ["По умолчанию", "BlackShark V3 X PS USB", "Steam Streaming Microphone"],
            )
            self.assertEqual(panel.collect()["microphone_device"], 2)
            self.assertEqual(panel.collect()["microphone_hostapi"], "Windows WASAPI")
            self.assertEqual(panel.collect()["microphone_name"], devices[0]["name"])
            # Refreshing devices is not an edit and must not restart the mic.
            panel.refresh_microphone_devices()
            self.assertFalse(panel._autosave_timer.isActive())

    def test_disconnected_selection_is_not_silently_changed(self):
        from PySide6.QtWidgets import QApplication
        from luxai.settings_panel import SettingsPanel
        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)
        with (mock.patch("sounddevice.query_hostapis", return_value=HOSTS),
              mock.patch("sounddevice.query_devices", return_value=[
                  device("Webcam", 2)])):
            panel = SettingsPanel({
                "microphone_device": 0, "microphone_name": "Missing headset",
                "microphone_hostapi": "MME", "microphone_enabled": False,
            }, lambda: None, lambda: None, lambda: None)
        self.addCleanup(panel.close)
        self.assertIn("Недоступен", panel.mic_device.currentText())
        self.assertEqual(panel.collect()["microphone_name"], "Missing headset")
        panel.mic_device.setCurrentIndex(1)
        self.assertEqual(panel.collect()["microphone_name"], "Webcam")

    def test_old_mme_truncated_name_maps_only_when_unique(self):
        from PySide6.QtWidgets import QApplication
        from luxai.settings_panel import SettingsPanel
        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)
        full = "Микрофон (BlackShark V3 X PS USB)"
        with (mock.patch("sounddevice.query_hostapis", return_value=HOSTS),
              mock.patch("sounddevice.query_devices", return_value=[
                  device(full, 2)])):
            panel = SettingsPanel({
                "microphone_device": 15,
                "microphone_name": full[:28],
                "microphone_hostapi": "MME", "microphone_enabled": False,
            }, lambda: None, lambda: None, lambda: None)
        self.addCleanup(panel.close)
        self.assertEqual(panel.collect()["microphone_device"], 0)
        self.assertEqual(panel.collect()["microphone_name"], full)


if __name__ == "__main__":
    unittest.main()
