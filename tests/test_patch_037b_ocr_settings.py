"""0.3.7b: OCR is integrated; Settings no longer needs a Tesseract panel."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock


class OCRSettingsCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("PySide6 not installed")
        cls.app = QApplication.instance() or QApplication([])

    def settings(self, cfg=None):
        from luxai.settings_panel import SettingsPanel

        panel = SettingsPanel(
            {"tesseract_path": "C:/old/legacy/tesseract.exe", **(cfg or {})},
            on_save=lambda: None,
            on_pick_model=lambda: None,
            on_test_voice=lambda: None,
        )
        self.addCleanup(panel.close)
        return panel

    def test_ocr_installation_and_external_picker_not_visible_in_settings(self):
        from PySide6.QtWidgets import QLabel, QPushButton, QLineEdit
        panel = self.settings()
        labels = [widget.text() for widget in panel.findChildren(QLabel)]
        buttons = [widget.text() for widget in panel.findChildren(QPushButton)]
        placeholders = [widget.placeholderText() for widget in panel.findChildren(QLineEdit)]
        for text in labels + buttons + placeholders:
            self.assertNotIn("Tesseract", text)
            self.assertNotIn("OCR проверяется", text)
        self.assertFalse(hasattr(panel, "tesseract_path"))
        self.assertFalse(hasattr(panel, "ocr_status"))
        self.assertFalse(hasattr(panel, "ocr_status_icon"))
        self.assertFalse(hasattr(panel, "_select_tesseract"))
        self.assertTrue(any("Город для прогноза погоды" in text for text in labels))

    def test_save_settings_preserves_legacy_ocr_path_without_visible_picker(self):
        panel = self.settings()
        data = panel.collect()
        self.assertEqual(data["tesseract_path"], "C:/old/legacy/tesseract.exe")
        self.assertIn("weather_city", data)
        self.assertIn("microphone_enabled", data)
        self.assertIn("ui_language", data)

    def test_no_legacy_path_defaults_to_integrated_auto_discovery(self):
        panel = self.settings({"tesseract_path": ""})
        self.assertEqual(panel.collect()["tesseract_path"], "")

    def window(self):
        import main
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        cfg = Path(temp.name) / "config.json"
        cfg.write_text(
            '{"microphone_enabled":false,"tts_enabled":false,'
            '"online_agent_enabled":false}', encoding="utf-8",
        )
        p = mock.patch.object(main, "CONFIG", cfg)
        p.start()
        self.addCleanup(p.stop)
        with mock.patch("sounddevice.query_devices", return_value=[]):
            win = main.MainWindow()
        self.addCleanup(win.close)
        return win

    def test_main_window_does_not_require_deleted_ocr_status_widgets(self):
        window = self.window()
        self.assertFalse(hasattr(window.settings_panel, "ocr_status"))
        window._on_ocr_setup_ready(True, "Tesseract OCR готов")
        self.assertTrue(window._ocr_ready)
        window._on_ocr_setup_ready(False, "OCR недоступен")
        self.assertFalse(window._ocr_ready)
        self.assertIn("OCR недоступен", window.mic_status.toolTip())

    def test_integrated_bootstrap_still_attempts_ocr_setup(self):
        window = self.window()
        with (
            mock.patch("main.ensure_tesseract", return_value=(
                Path("C:/LuxAI/.luxai_data/ocr/Tesseract-OCR/tesseract.exe"),
                Path("C:/LuxAI/.luxai_data/ocr/tessdata"),
            )) as ensure,
            mock.patch.object(window.ocr_setup_ready, "emit") as signal,
        ):
            window._ocr_setup_worker()
        ensure.assert_called_once_with(window.cfg.get("tesseract_path", ""))
        signal.assert_called_once()
        self.assertTrue(signal.call_args.args[0])

    def test_bundled_ocr_used_before_optional_stale_config(self):
        from luxai import ocr_setup
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / "Tesseract-OCR" / "tesseract.exe"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"MZ")
            with (
                mock.patch.object(ocr_setup, "WINDOWS_EXECUTABLE", binary),
                mock.patch("luxai.ocr_setup.shutil.which", return_value=None),
            ):
                self.assertEqual(
                    ocr_setup.find_tesseract("C:/missing/tesseract.exe"),
                    binary,
                )


if __name__ == "__main__":
    unittest.main()
