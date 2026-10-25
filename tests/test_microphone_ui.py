"""Microphone readiness and headset controls, without hardware or model downloads."""
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication
import main
from luxai.settings_panel import SettingsPanel
from luxai.ui_i18n import get_ui_language, set_ui_language
from luxai.voice import ModelLoadError


def endpoint(name, hostapi=0):
    return {"name": name, "hostapi": hostapi, "max_input_channels": 1, "default_samplerate": 48000}


class MicrophoneControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.language = get_ui_language()
        set_ui_language("ru")
        self.hosts = mock.patch("sounddevice.query_hostapis", return_value=[{"name": "WASAPI"}])
        self.hosts.start()
        self.addCleanup(self.hosts.stop)
        self.addCleanup(set_ui_language, self.language)

    def panel(self, config, devices):
        with mock.patch("sounddevice.query_devices", return_value=devices):
            panel = SettingsPanel(config, lambda: None, lambda: None, lambda: None)
        self.addCleanup(panel.close)
        return panel

    def test_reconnected_headset_is_selected_by_name_and_host_api(self):
        panel = self.panel({"microphone_device": 0, "microphone_name": "Wireless input", "microphone_hostapi": "WASAPI"},
                           [endpoint("Webcam"), endpoint("Wireless input")])
        settings = panel.collect()
        self.assertEqual(settings["microphone_device"], 1)
        self.assertEqual(settings["microphone_name"], "Wireless input")
        self.assertEqual(settings["microphone_hostapi"], "WASAPI")

    def test_disconnected_headset_never_becomes_webcam_with_same_index(self):
        panel = self.panel({"microphone_device": 0, "microphone_name": "Wireless input", "microphone_hostapi": "WASAPI"},
                           [endpoint("Webcam")])
        self.assertIn("Недоступен", panel.mic_device.currentText())
        self.assertEqual(panel.collect()["microphone_name"], "Wireless input")
        # An explicit user selection of the webcam still works despite reused indices.
        panel.mic_device.setCurrentIndex(1)
        self.assertEqual(panel.collect()["microphone_name"], "Webcam")

    def test_refresh_recovers_a_returning_headset_and_keeps_sensitivity(self):
        panel = self.panel({"microphone_device": 0, "microphone_name": "Wireless input", "microphone_sensitivity": 1.8},
                           [endpoint("Webcam")])
        with mock.patch("sounddevice.query_devices", return_value=[endpoint("Webcam"), endpoint("Wireless input")]):
            panel.refresh_microphone_devices()
        self.assertEqual(panel.collect()["microphone_device"], 1)
        self.assertEqual(panel.collect()["microphone_sensitivity"], 1.8)

    def test_model_loading_does_not_claim_microphone_is_listening(self):
        states = []

        class FailingStream:
            def __init__(self, **kwargs):
                self.status = kwargs["status_callback"]
                self.status("loading_model", {})
                self.status("model_ready", {})

            def listen(self):
                raise OSError("Selected headset is disconnected")

            def stop(self):
                pass

        worker = main.VoiceWorker({"whisper_model": "small"})
        worker.state.connect(lambda event, details: states.append((event, details)))
        with mock.patch.object(main, "VoiceListener", FailingStream):
            worker.run()
        self.assertNotIn("listening", [event for event, _ in states])
        self.assertEqual(states[-1][0], "error")
        self.assertIn("disconnected", states[-1][1]["message"])

    def test_missing_headset_does_not_trigger_another_model_download(self):
        worker = main.VoiceWorker({"whisper_model": "medium"})
        with mock.patch.object(main, "VoiceListener", side_effect=RuntimeError("No microphone")) as listener:
            worker.run()
        self.assertEqual(listener.call_count, 1)

    def test_only_a_model_load_failure_uses_small_fallback(self):
        listener = types.SimpleNamespace(listen=lambda: iter(()), stop=lambda: None)
        worker = main.VoiceWorker({"whisper_model": "medium"})
        with mock.patch.object(main, "VoiceListener", side_effect=[ModelLoadError("not enough memory"), listener]) as constructor:
            worker.run()
        self.assertEqual([call.kwargs["model_path"] for call in constructor.call_args_list], ["medium", "small"])

    def test_live_state_error_and_language_are_independent_of_requested_switch(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(main, "CONFIG", Path(temporary) / "config.json"):
            main.CONFIG.write_text(json.dumps({"microphone_enabled": False, "tts_enabled": False}), encoding="utf-8")
            with mock.patch("sounddevice.query_devices", return_value=[]):
                window = main.MainWindow()
            self.addCleanup(window.close)
            window._on_audio_state("loading_model", {})
            self.assertEqual(window.header_mic_button.property("jarvisIcon"), "loader-circle")
            self.assertFalse(window.header_mic_button.icon().isNull())
            window._on_audio_state("listening", {"device": "Headset"})
            window._on_audio_level(0.01)
            self.assertGreater(window.settings_panel.audio_level.value(), 0)
            window._on_audio_state("error", {"message": "Disconnected"})
            self.assertEqual(window.header_mic_button.property("jarvisIcon"), "circle-alert")
            self.assertFalse(window.header_mic_button.icon().isNull())
            self.assertEqual(window.home_page.microphone_level.value(), 0)
            window.cfg["ui_language"] = "ro"
            window.apply_ui_language()
            self.assertIn("Microfonul nu a pornit", window.settings_panel.audio_status.text())
            self.assertIn("Disconnected", window.settings_panel.audio_status.text())

    def test_probe_worker_never_loads_whisper_and_passes_stable_endpoint(self):
        reports = []
        worker = main.AudioDiagnosticsWorker({"microphone_device": 3, "microphone_name": "Wireless", "microphone_hostapi": "WASAPI"}, probe=True)
        worker.completed.connect(reports.append)
        with mock.patch("luxai.diagnostics.collect_diagnostics", return_value={"runtime": {}}), mock.patch(
            "luxai.diagnostics.microphone_probe", return_value={"ok": True, "silent": False},
        ) as probe, mock.patch.object(main, "VoiceListener", side_effect=AssertionError("Whisper must not load")):
            worker.run()
        self.assertTrue(reports[0]["microphone_probe"]["ok"])
        self.assertEqual(probe.call_args.kwargs["microphone_name"], "Wireless")
        self.assertEqual(probe.call_args.kwargs["microphone_hostapi"], "WASAPI")

    def make_window(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        config = Path(folder.name) / "config.json"
        config.write_text(json.dumps({"microphone_enabled": False, "tts_enabled": False}), encoding="utf-8")
        patch = mock.patch.object(main, "CONFIG", config)
        patch.start()
        self.addCleanup(patch.stop)
        with mock.patch("sounddevice.query_devices", return_value=[]):
            window = main.MainWindow()
        self.addCleanup(window.close)
        return window

    def test_obsolete_worker_cannot_change_state_or_execute_queued_speech(self):
        window = self.make_window()
        old = main.VoiceWorker({})
        current = main.VoiceWorker({})
        window.worker = current
        window.cfg["microphone_enabled"] = True
        old.state.connect(window._on_voice_state)
        old.level.connect(window._on_voice_level)
        old.transcript.connect(window._on_voice_transcript)
        current.state.connect(window._on_voice_state)
        window._on_audio_state("loading_model", {})
        with mock.patch.object(window, "handle_voice") as handle:
            old.state.emit("error", {"message": "Stale failure"})
            old.level.emit(0.5)
            old.transcript.emit("approve the action")
            self.assertEqual(window._audio_event, "loading_model")
            self.assertEqual(window.settings_panel.audio_level.value(), 0)
            handle.assert_not_called()
        current.state.emit("listening", {})
        self.assertEqual(window._audio_event, "listening")
        window.worker = None

    def test_pending_probe_blocks_export_and_repeated_tests_until_capture_stops(self):
        window = self.make_window()
        window.worker = types.SimpleNamespace(isRunning=lambda: True)
        with mock.patch.object(window, "stop_listener"), mock.patch.object(window, "_start_audio_diagnostics") as start:
            window.test_microphone()
            self.assertFalse(window.settings_panel.export_diagnostics.isEnabled())
            self.assertFalse(window.settings_panel.test_microphone.isEnabled())
            self.assertEqual(window._audio_event, "waiting_for_capture")
            window.export_diagnostics()
            window.test_microphone()
            start.assert_not_called()
        window.worker = None
        window._pending_microphone_test = None

    def test_existing_diagnostic_worker_is_never_replaced_while_running(self):
        window = self.make_window()
        existing = types.SimpleNamespace(isRunning=lambda: True)
        window.audio_diagnostics_worker = existing
        with mock.patch.object(main, "AudioDiagnosticsWorker") as constructor:
            self.assertFalse(window._start_audio_diagnostics({}, True))
            constructor.assert_not_called()
        self.assertIs(window.audio_diagnostics_worker, existing)
        window.audio_diagnostics_worker = None

    def test_restart_synchronizes_header_switch(self):
        window = self.make_window()
        self.assertFalse(window.header_mic_button.isChecked())
        with mock.patch.object(window, "save_settings", return_value=True), mock.patch.object(window, "stop_listener"), mock.patch.object(window, "start_listener"):
            window.restart_microphone()
        self.assertTrue(window.header_mic_button.isChecked())
        self.assertTrue(window.settings_panel.mic.isChecked())

    def test_recognition_failure_remains_visible_when_stream_returns_to_listening(self):
        window = self.make_window()
        window._on_audio_state("transcription_error", {"message": "Model unavailable"})
        window._on_audio_state("listening", {})
        self.assertIn("Model unavailable", window.settings_panel.audio_feedback.text())

    def test_switching_off_cancels_pending_probe_and_restores_controls(self):
        window = self.make_window()
        window.worker = types.SimpleNamespace(isRunning=lambda: True, listener=None)
        with mock.patch.object(window, "stop_listener"):
            window.test_microphone()
            self.assertIsNotNone(window._pending_microphone_test)
            window.cfg["microphone_enabled"] = True
            window.settings_panel.mic.setChecked(False)
            window.apply_settings()
        self.assertIsNone(window._pending_microphone_test)
        self.assertFalse(window._probe_resume_listener)
        self.assertTrue(window.settings_panel.test_microphone.isEnabled())
        self.assertTrue(window.settings_panel.export_diagnostics.isEnabled())
        window.worker = None

    def test_legacy_toggle_off_cancels_pending_recording(self):
        window = self.make_window()
        window._pending_microphone_test = {"microphone_device": -1}
        window._probe_resume_listener = True
        window._set_diagnostic_controls(False)
        window.toggle_mic(False)
        self.assertIsNone(window._pending_microphone_test)
        self.assertFalse(window._probe_resume_listener)
        self.assertTrue(window.settings_panel.export_diagnostics.isEnabled())

    def test_stopping_running_probe_resets_meter_and_requested_status(self):
        window = self.make_window()
        diagnostic = types.SimpleNamespace(isRunning=lambda: True, stop_capture=mock.Mock())
        window.audio_diagnostics_worker = diagnostic
        window._on_audio_state("testing", {})
        window._on_audio_level(0.1)
        window.stop_listener()
        diagnostic.stop_capture.assert_called_once()
        self.assertEqual(window._audio_event, "stopped")
        self.assertEqual(window.settings_panel.audio_level.value(), 0)
        window.audio_diagnostics_worker = None

    def test_voice_stop_interrupts_speech_without_requiring_wake_prefix(self):
        window = self.make_window()
        window.cfg["prefix_enabled"] = True
        before = len(window.history)
        with mock.patch.object(main, "stop_voice_output") as output, \
             mock.patch.object(window, "run_command") as command:
            window.handle_voice("Спасибо за внимание!")
            self.assertEqual(len(window.history), before)
            command.assert_not_called()
            window.handle_voice("Стоп!")
            output.assert_called_once()
            command.assert_not_called()
        self.assertGreater(window._speech_generation, 0)
        self.assertIn("остановлено", window.mic_status.text())

    def test_queued_listener_start_after_switch_off_never_loads_a_model(self):
        window = self.make_window()
        self.assertFalse(window.cfg["microphone_enabled"])
        with mock.patch.object(main, "VoiceWorker") as constructor:
            window.start_listener()
        constructor.assert_not_called()
        self.assertIsNone(window.worker)
        self.assertEqual(window._audio_event, "stopped")


if __name__ == "__main__":
    unittest.main()
