"""Device scans preserve recording identity across changing numeric indices."""
from __future__ import annotations

import unittest
from unittest import mock


class MicrophonePickerIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def panel(self, config, devices, hosts):
        from luxai.settings_panel import SettingsPanel
        with (
            mock.patch("sounddevice.query_devices", return_value=devices),
            mock.patch("sounddevice.query_hostapis", return_value=hosts),
        ):
            panel = SettingsPanel(
                {"microphone_enabled": False, **config},
                lambda: None, lambda: None, lambda: None,
            )
        self.addCleanup(panel.close)
        return panel

    def test_saved_host_beats_a_reused_index_for_same_named_inputs(self):
        panel = self.panel(
            {"microphone_device": 0, "microphone_name": "USB microphone",
             "microphone_hostapi": "PulseAudio"},
            [{"name": "USB microphone", "hostapi": 0, "max_input_channels": 1},
             {"name": "USB microphone", "hostapi": 1, "max_input_channels": 1}],
            [{"name": "ALSA"}, {"name": "PulseAudio"}],
        )
        self.assertEqual(panel.collect()["microphone_device"], 1)
        self.assertEqual(panel.collect()["microphone_hostapi"], "PulseAudio")
        self.assertFalse(panel._autosave_timer.isActive())

    def test_partial_non_mme_device_name_cannot_select_a_different_microphone(self):
        name = "Microphone (Wireless Headset)"
        panel = self.panel(
            {"microphone_device": 5, "microphone_name": name,
             "microphone_hostapi": "Windows WASAPI"},
            [{"name": name + " Second headset", "hostapi": 0, "max_input_channels": 1}],
            [{"name": "Windows WASAPI"}],
        )
        self.assertEqual(panel.collect()["microphone_device"], 5)
        self.assertEqual(panel.collect()["microphone_name"], name)
        self.assertIn("Недоступен", panel.mic_device.currentText())


if __name__ == "__main__":
    unittest.main()
