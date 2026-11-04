"""The project font is loaded locally and replaces saved Arial preferences."""
import unittest
from unittest import mock

from PySide6.QtGui import QFontDatabase, QFontInfo
from PySide6.QtWidgets import QApplication, QLabel

from luxai.styles import build_styles
from luxai.ui_fonts import PROJECT_FONT, register_project_fonts


class ProjectFontTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_project_faces_register_once_without_network_and_render_real_font(self):
        import main
        previous = self.app.styleSheet()
        self.addCleanup(self.app.setStyleSheet, previous)
        with mock.patch('urllib.request.urlopen', side_effect=AssertionError('Fonts must load offline')):
            self.assertTrue(main.load_project_font())
            with mock.patch.object(QFontDatabase, 'addApplicationFont') as add_font:
                self.assertTrue(register_project_fonts())
                add_font.assert_not_called()
        self.assertIn(PROJECT_FONT, QFontDatabase.families())
        self.assertIn('Bold', QFontDatabase.styles(PROJECT_FONT))
        self.app.setStyleSheet(build_styles(font_family='Arial'))
        label = QLabel('Setări și aplicații')
        self.addCleanup(label.close)
        label.show()
        self.app.processEvents()
        self.assertEqual(QFontInfo(label.font()).family(), PROJECT_FONT)
        self.assertIn("'Fuzzy Bubbles', 'Onest'", self.app.styleSheet())

    def test_existing_arial_selection_displays_project_font_and_saves_migration(self):
        from luxai.settings_panel import SettingsPanel
        with mock.patch('sounddevice.query_devices', return_value=[]):
            panel = SettingsPanel({'ui_font_family': 'Arial', 'microphone_enabled': False},
                                  lambda: None, lambda: None, lambda: None)
        self.addCleanup(panel.close)
        self.assertEqual(panel.font_family.currentText(), PROJECT_FONT)
        self.assertEqual(panel.collect()['ui_font_family'], PROJECT_FONT)
        self.assertEqual(panel.font_family.findData('Arial'), -1)
        for family in ('Onest', 'system', PROJECT_FONT):
            panel.font_family.setCurrentIndex(panel.font_family.findData(family))
            self.assertEqual(panel.collect()['ui_font_family'], family)
