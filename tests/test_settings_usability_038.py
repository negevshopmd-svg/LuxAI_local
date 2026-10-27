"""Current slider values and settings section navigation stay visible and live."""
from __future__ import annotations

import unittest
from unittest import mock

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from luxai.settings_panel import SettingsPanel
from luxai.styles import build_styles
from luxai.ui_i18n import get_ui_language, set_ui_language


class SettingsUsability038Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def panel(self, config=None):
        self.addCleanup(set_ui_language, get_ui_language())
        set_ui_language("ru")
        calls = []
        with mock.patch("sounddevice.query_devices", return_value=[]):
            panel = SettingsPanel(
                {"microphone_enabled": False, "tts_enabled": False, **(config or {})},
                lambda: calls.append(panel.collect()), lambda: None, lambda: None,
            )
        panel.setStyleSheet(build_styles())
        panel.resize(1000, 700)
        panel.show()
        self.app.processEvents()
        self.addCleanup(panel.close)
        return panel, calls

    @staticmethod
    def selected(panel):
        return [i for i, button in enumerate(panel.section_buttons)
                if button.property("selected")]

    def test_slider_readouts_restore_and_change_with_exact_saved_values(self):
        panel, calls = self.panel({
            "microphone_sensitivity": 1.15, "voice_volume": 73,
            "voice_speed": 1.15, "ui_transparency": 23,
            "speech_pause_seconds": 2.7,
        })
        controls = (
            (panel.mic_sensitivity, panel.mic_sensitivity_value, "115%", 300, "300%"),
            (panel.voice_volume, panel.voice_volume_value, "73%", 0, "0%"),
            (panel.voice_speed, panel.voice_speed_value, "115%", 140, "140%"),
            (panel.transparency, panel.transparency_value, "23%", 35, "35%"),
            (panel.speech_pause, panel.speech_pause_value, "2.7 s", 40, "4.0 s"),
        )
        for slider, label, original, new_value, expected in controls:
            self.assertEqual(label.text(), original)
            slider.setValue(new_value)
            self.assertEqual(label.text(), expected)
        panel.flush_auto_save()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["microphone_sensitivity"], 3.0)
        self.assertEqual(calls[0]["voice_volume"], 0)
        self.assertEqual(calls[0]["voice_speed"], 1.4)
        self.assertEqual(calls[0]["ui_transparency"], 35)
        self.assertEqual(calls[0]["speech_pause_seconds"], 4.0)
        self.assertFalse(panel._autosave_timer.isActive())

    def test_readouts_fit_translated_layouts_and_keep_their_values(self):
        panel, _ = self.panel({"microphone_sensitivity": 3, "voice_speed": 1.4})
        for language in ("ro", "en", "ru"):
            panel.retranslate(language)
            self.app.processEvents()
            for label in (
                panel.mic_sensitivity_value, panel.voice_volume_value,
                panel.voice_speed_value, panel.transparency_value,
                panel.speech_pause_value,
            ):
                with self.subTest(language=language, value=label.text()):
                    self.assertGreaterEqual(label.contentsRect().width(),
                                            label.fontMetrics().horizontalAdvance(label.text()))
                    self.assertGreaterEqual(label.contentsRect().height(), label.fontMetrics().height())
            self.assertEqual(panel.mic_sensitivity_value.text(), "300%")
            self.assertEqual(panel.voice_speed_value.text(), "140%")

    def test_scrollbar_and_manual_wheel_follow_section_without_saving_preferences(self):
        panel, calls = self.panel()
        bar = panel.scroll.verticalScrollBar()
        self.assertEqual(self.selected(panel), [0])
        for index in (1, 2, 3, 4):
            bar.setValue(panel.sections[index].y())
            self.app.processEvents()
            self.assertEqual(self.selected(panel), [index])
        bar.setValue(0)
        viewport = panel.scroll.viewport()
        for _ in range(100):
            event = QWheelEvent(
                QPointF(viewport.rect().center()), QPointF(viewport.mapToGlobal(viewport.rect().center())),
                QPoint(), QPoint(0, -120 * 10), Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.ScrollUpdate, False,
            )
            self.app.sendEvent(viewport, event)
            self.app.processEvents()
            if bar.value() == bar.maximum():
                break
        self.assertGreater(bar.value(), 0)
        self.assertEqual(bar.value(), bar.maximum())
        self.assertEqual(self.selected(panel), [len(panel.sections) - 1])
        bar.setValue(0)
        self.assertEqual(self.selected(panel), [0])
        self.assertFalse(panel._autosave_timer.isActive())
        panel.flush_auto_save()
        self.assertEqual(calls, [])

    def test_sidebar_click_filter_resize_and_bottom_keep_current_section_in_sync(self):
        panel, calls = self.panel()
        panel.section_buttons[3].click()
        self.app.processEvents()
        self.assertEqual(self.selected(panel), [3])
        panel.search.setText(panel.section_buttons[4].text())
        self.app.processEvents()
        self.assertEqual(self.selected(panel), [4])
        self.assertFalse(panel.sections[4].isHidden())
        panel.resize(1000, 500)
        self.app.processEvents()
        self.assertEqual(self.selected(panel), [4])
        panel.search.setText("no such section")
        self.assertEqual(self.selected(panel), [])
        self.app.processEvents()
        self.assertEqual(self.selected(panel), [])
        panel.search.clear()
        self.app.processEvents()
        bar = panel.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.app.processEvents()
        self.assertEqual(self.selected(panel), [6])
        self.assertFalse(panel._autosave_timer.isActive())
        panel.flush_auto_save()
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
