"""Appearance controls change real preferences without leaking draft values."""
import unittest
from unittest import mock

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from luxai.settings_panel import SettingsPanel
from luxai.styles import build_styles
from luxai.ui_i18n import get_ui_language, set_ui_language, tr
from luxai.ui_preferences import PreferenceRow


class SettingsDesign038aTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def panel(self, values=None):
        self.addCleanup(set_ui_language, get_ui_language())
        set_ui_language("ru")
        saved = []
        with mock.patch("sounddevice.query_devices", return_value=[]):
            panel = SettingsPanel({"microphone_enabled": False, "tts_enabled": False,
                                   **(values or {})}, lambda: saved.append(panel.collect()),
                                  lambda: None, lambda: None, on_install_local_ai=mock.Mock())
        panel.setStyleSheet(build_styles())
        panel.resize(1000, 900)
        panel.show()
        self.app.processEvents()
        panel._jump(3)
        self.app.processEvents()
        self.addCleanup(panel.close)
        return panel, saved

    def test_mouse_segments_swatches_and_switches_save_one_real_snapshot(self):
        panel, saved = self.panel()
        QTest.mouseClick(panel.theme_control.buttons[1], Qt.MouseButton.LeftButton)
        QTest.mouseClick(panel.accent_control.buttons[1], Qt.MouseButton.LeftButton)
        QTest.mouseClick(panel.ui_language_control.buttons[2], Qt.MouseButton.LeftButton)
        QTest.mouseClick(panel.on_top, Qt.MouseButton.LeftButton)
        self.assertTrue(panel._autosave_timer.isActive())
        panel.flush_auto_save()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["ui_theme"], "light")
        self.assertEqual(saved[0]["ui_accent"], "#873eff")
        self.assertEqual(saved[0]["ui_language"], "ro")
        self.assertTrue(saved[0]["always_on_top"])
        self.assertTrue(panel.theme_control.buttons[1].isChecked())
        self.assertTrue(panel.accent_control.buttons[1].isChecked())
        panel.theme.setCurrentIndex(panel.theme.findData("dark"))
        self.assertTrue(panel.theme_control.buttons[0].isChecked())
        self.assertFalse(panel.theme_control.buttons[1].isChecked())

    def test_background_draft_only_commits_valid_hex_and_clear_restores_theme_default(self):
        panel, saved = self.panel({"ui_background": "#123456"})
        field = panel.background_control.hex
        field.setText("#bad")
        self.assertFalse(panel.background_control.commit())
        self.assertEqual(panel.collect()["ui_background"], "#123456")
        self.assertTrue(field.property("invalid"))
        panel.flush_auto_save()
        self.assertEqual(saved, [])
        field.setText("#AACCEE")
        self.assertTrue(panel.background_control.commit())
        panel.flush_auto_save()
        self.assertEqual(saved[-1]["ui_background"], "#aaccee")
        self.assertFalse(field.property("invalid"))
        self.assertEqual(field.text(), "#AACCEE")
        field.clear()
        panel.background_control.commit()
        panel.flush_auto_save()
        self.assertEqual(saved[-1]["ui_background"], "")

    def test_custom_picker_cancel_is_inert_and_selected_color_is_persisted(self):
        panel, saved = self.panel({"ui_accent": "#873EFF"})
        self.assertEqual(panel.accent.currentData(), "#873eff")
        QTest.mouseClick(panel.accent_control.buttons[1], Qt.MouseButton.LeftButton)
        self.assertTrue(panel.accent_control.buttons[1].isChecked())
        self.assertFalse(panel._autosave_timer.isActive())
        with mock.patch("luxai.ui_preferences.QColorDialog.getColor", return_value=QColor()):
            QTest.mouseClick(panel.accent_control.custom, Qt.MouseButton.LeftButton)
        panel.flush_auto_save()
        self.assertEqual(saved, [])
        with mock.patch("luxai.ui_preferences.QColorDialog.getColor", return_value=QColor("#abcdef")):
            QTest.mouseClick(panel.accent_control.custom, Qt.MouseButton.LeftButton)
        panel.flush_auto_save()
        self.assertEqual(saved[-1]["ui_accent"], "#abcdef")
        self.assertEqual(panel.accent.currentData(), "#abcdef")

    def test_appearance_reset_keeps_voice_language_and_other_preferences(self):
        panel, saved = self.panel({"ui_theme": "light", "ui_accent": "#123abc",
                                   "ui_background": "#222333", "ui_transparency": 23,
                                   "ui_animations": False, "always_on_top": True,
                                   "ui_language": "ro", "language": "en", "weather_city": "Orhei"})
        QTest.mouseClick(panel.interface_reset, Qt.MouseButton.LeftButton)
        panel.flush_auto_save()
        state = saved[-1]
        for key, value in {"ui_theme": "dark", "ui_accent": "#3978f6", "ui_background": "",
                           "ui_transparency": 0, "ui_animations": True, "always_on_top": False}.items():
            self.assertEqual(state[key], value)
        self.assertEqual(state["ui_language"], "ro")
        self.assertEqual(state["language"], "en")
        self.assertEqual(state["weather_city"], "Orhei")

    def test_provider_names_are_compact_and_manual_backend_install_button_is_absent(self):
        panel, _ = self.panel()
        self.assertEqual([panel.voice_engine.itemText(i) for i in range(panel.voice_engine.count())],
                         ["Piper", "Windows"])
        self.assertEqual([panel.voice_engine.itemData(i) for i in range(panel.voice_engine.count())],
                         ["piper", "windows"])
        self.assertFalse(any("llama-cpp-python" in button.text()
                             for button in panel.findChildren(QPushButton)))

    def test_language_refresh_preserves_draft_and_api_result_while_translating_live_statuses(self):
        panel, saved = self.panel()
        panel.api_key_entry.setText("unfinished-test-key")
        panel.set_test_busy(True)
        set_ui_language("en")
        panel.retranslate("en")
        self.assertEqual(panel.api_key_entry.text(), "unfinished-test-key")
        self.assertEqual(panel.key_status.text(), tr("Проверка ключа и выбранной модели через API…"))
        panel.show_test_result("Provider supplied exact result", False)
        set_ui_language("ro")
        panel.retranslate("ro")
        self.assertEqual(panel.key_status.text(), "Provider supplied exact result")
        self.assertEqual(panel.api_key_entry.text(), "unfinished-test-key")
        self.assertEqual(panel.api_key_ready_for_save(), "")
        self.assertEqual(panel.collect()["ui_language"], "ru")
        self.assertEqual(saved, [])

    def test_responsive_rows_keep_real_controls_inside_card_after_resize(self):
        panel, saved = self.panel()
        for width in (1000, 720):
            panel.resize(width, 900)
            for _ in range(3):
                self.app.processEvents()
            for row in panel.sections[3].findChildren(PreferenceRow):
                with self.subTest(width=width, row=row.control.objectName()):
                    self.assertGreaterEqual(row.control.x(), 0)
                    self.assertLessEqual(row.control.geometry().right(), row.width())
                    self.assertGreaterEqual(row.control.y(), 0)
                    self.assertLessEqual(row.control.geometry().bottom(), row.height())
                    self.assertLessEqual(row.labels.geometry().bottom(), row.height())
                    if row.width() < 540:
                        self.assertGreater(row.control.y(), row.labels.geometry().bottom())
        self.assertFalse(panel._autosave_timer.isActive())
        self.assertEqual(saved, [])


if __name__ == "__main__":
    unittest.main()
