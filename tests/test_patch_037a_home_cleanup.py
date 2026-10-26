"""0.3.7a UI-only hotfix: remove three buttons, preserve underlying tools."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock


class HomeCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("PySide6 unavailable")
        cls.app = QApplication.instance() or QApplication([])

    def test_home_has_no_old_action_buttons_but_keeps_status_controls(self):
        from PySide6.QtWidgets import QPushButton
        from luxai.ui_home import HomePage

        home = HomePage({
            "prefix_enabled": False,
            "tts_enabled": True,
            "ui_animations": True,
            "always_on_top": False,
            "voice_volume": 80,
        })
        self.addCleanup(home.close)
        buttons = [widget.text() for widget in home.findChildren(QPushButton)]
        for unwanted in (
            "Проверить микрофон",
            "Посмотреть кнопки на экране",
            "Пересказать выделенный текст",
        ):
            self.assertNotIn(unwanted, buttons)
        for name in (
            "microphone_test_button",
            "screen_assist_button",
            "selection_summary_button",
        ):
            self.assertFalse(hasattr(home, name), name)
        self.assertIsNotNone(home.microphone_state)
        self.assertIsNotNone(home.microphone_level)
        self.assertEqual(home.volume.value(), 80)
        for name in ("home_prefix", "home_quiet", "home_avatar", "home_top"):
            self.assertIsNotNone(getattr(home, name))

    def _window(self):
        import main
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        config = Path(folder.name) / "config.json"
        config.write_text(
            '{"microphone_enabled":false,"tts_enabled":false,'
            '"online_agent_enabled":false}', encoding="utf-8",
        )
        patch = mock.patch.object(main, "CONFIG", config)
        patch.start()
        self.addCleanup(patch.stop)
        with (mock.patch("sounddevice.query_devices", return_value=[]),
              mock.patch("main.MainWindow._ocr_setup_worker")):
            window = main.MainWindow()
        self.addCleanup(window.close)
        return window

    def test_main_window_constructs_without_removed_button_references(self):
        window = self._window()
        for name in (
            "microphone_test_button",
            "screen_assist_button",
            "selection_summary_button",
        ):
            self.assertFalse(hasattr(window.home_page, name), name)
        self.assertTrue(callable(window.request_screen_inspection))
        self.assertTrue(callable(window.test_microphone))
        self.assertTrue(callable(window._start_selection_request))
        self.assertIsNotNone(window.home_page.home_history)

    def test_mic_diagnostic_enabled_state_remains_on_settings_page(self):
        window = self._window()
        window._set_diagnostic_controls(False)
        self.assertFalse(window.settings_panel.test_microphone.isEnabled())
        self.assertFalse(window.settings_panel.export_diagnostics.isEnabled())
        window._set_diagnostic_controls(True)
        self.assertTrue(window.settings_panel.test_microphone.isEnabled())
        self.assertTrue(window.settings_panel.export_diagnostics.isEnabled())


if __name__ == "__main__":
    unittest.main()
