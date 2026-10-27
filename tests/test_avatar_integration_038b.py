"""The home avatar follows capture and actual output, without audio hardware."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication

import main
from luxai.ui_i18n import get_ui_language, set_ui_language


class AvatarIntegration038bTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.addCleanup(set_ui_language, get_ui_language())
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        config = Path(folder.name) / "config.json"
        config.write_text(json.dumps({
            "microphone_enabled": False, "tts_enabled": False,
            "minimize_to_tray": False, "ui_animations": True,
        }), encoding="utf-8")
        self.playing = threading.Event()
        with (mock.patch.object(main, "CONFIG", config),
              mock.patch.object(main, "voice_output_playing", self.playing),
              mock.patch("sounddevice.query_devices", return_value=[]),
              mock.patch.object(main.MainWindow, "_ocr_setup_worker")):
            self.window = main.MainWindow()
        self.addCleanup(self.window.close)

    def test_capture_levels_and_failure_reach_avatar(self):
        avatar = self.window.avatar
        with (mock.patch.object(avatar, "set_listening", wraps=avatar.set_listening) as listening,
              mock.patch.object(avatar, "set_audio_level", wraps=avatar.set_audio_level) as level):
            self.window._on_audio_state("loading_model", {})
            listening.assert_called_with(False)
            self.window._on_audio_state("listening", {"device": "Headset"})
            listening.assert_called_with(True)
            self.window._on_audio_level(0.01)
            self.assertAlmostEqual(level.call_args.args[0],
                                   self.window.home_page.microphone_level.value() / 100)
            self.assertGreater(level.call_args.args[0], 0)
            self.window._on_audio_state("error", {"message": "Disconnected"})
            listening.assert_called_with(False)
            level.assert_called_with(0.0)
            self.window._on_audio_state("transcribing", {})
            listening.assert_called_with(False)

    def test_only_actual_output_drives_speaking_and_home_visibility_stops_timer(self):
        from luxai import voices
        self.window.show()
        self.app.processEvents()
        avatar = self.window.avatar
        with mock.patch.object(voices, "playback_active", threading.Event()) as preparing:
            preparing.set()
            avatar._advance()
            self.assertFalse(avatar._speaking)
            self.playing.set()
            avatar._advance()
            self.assertTrue(avatar._speaking)
            self.playing.clear()
            avatar._advance()
            self.assertFalse(avatar._speaking)
        self.window.show_page(1)
        self.app.processEvents()
        self.assertFalse(avatar._timer.isActive())
        self.playing.set()
        self.window.show_page(0)
        self.app.processEvents()
        self.assertTrue(avatar._timer.isActive())
        self.assertTrue(avatar._speaking)
        avatar.set_animated(False)
        self.assertFalse(avatar._timer.isActive())


if __name__ == "__main__":
    unittest.main()
