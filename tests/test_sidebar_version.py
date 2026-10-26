"""The installed version remains readable below the sidebar collapse control."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from luxai.styles import build_styles
from luxai.ui_i18n import translate_widgets
from luxai.ui_sidebar import NavigationSidebar, VERSION_FILE, application_version


class SidebarVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def sidebar(self):
        sidebar = NavigationSidebar()
        sidebar.resize(sidebar.width(), 700)
        self.addCleanup(sidebar.close)
        return sidebar

    def test_installed_version_appears_below_collapse_and_survives_language_changes(self):
        sidebar = self.sidebar()
        expected = VERSION_FILE.read_text(encoding="utf-8-sig").strip()
        self.assertEqual(sidebar.version_label.text(), expected)
        layout = sidebar.layout()
        self.assertEqual(layout.indexOf(sidebar.version_label), layout.indexOf(sidebar.collapse) + 1)
        for language in ("ro", "en", "ru"):
            sidebar.set_language(language)
            translate_widgets(sidebar, language)
            self.assertEqual(sidebar.version_label.text(), expected)
            self.assertIn(expected, sidebar.version_label.accessibleName())

    def test_version_fits_both_sidebar_widths_and_themes(self):
        sidebar = self.sidebar()
        for theme in ("dark", "light"):
            sidebar.setStyleSheet(build_styles(theme))
            for collapsed in (False, True):
                if sidebar._collapsed != collapsed:
                    sidebar.toggle_collapsed()
                sidebar.show()
                self.app.processEvents()
                label = sidebar.version_label
                self.assertTrue(label.isVisible())
                self.assertGreater(label.geometry().top(), sidebar.collapse.geometry().bottom())
                self.assertGreaterEqual(label.contentsRect().width(),
                                        label.fontMetrics().horizontalAdvance(label.text()))
                self.assertGreaterEqual(label.contentsRect().height(), label.fontMetrics().height())
                self.assertTrue(sidebar.rect().contains(label.geometry()))

    def test_version_file_errors_do_not_prevent_sidebar_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            version_file = Path(directory) / "version.txt"
            with mock.patch("luxai.ui_sidebar.VERSION_FILE", version_file):
                self.assertEqual(application_version(), "—")
                version_file.write_bytes(b"\xff\xff")
                self.assertEqual(application_version(), "—")
                version_file.write_text("\n" * 5, encoding="utf-8")
                self.assertEqual(self.sidebar().version_label.text(), "—")

    def test_oversized_native_or_inherited_font_cannot_clip_collapsed_version(self):
        sidebar = self.sidebar()
        inherited = QFont("Courier New")
        inherited.setPixelSize(40)
        inherited.setStretch(150)
        inherited.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 5)
        sidebar.setFont(inherited)
        sidebar.toggle_collapsed()
        for theme in ("dark", "light"):
            sidebar.setStyleSheet(
                build_styles(theme)
                + "\nQFrame#Sidebar QLabel#SidebarVersion { font-size:40px; letter-spacing:5px; }"
            )
            sidebar.version_label.setFont(inherited)
            sidebar.show()
            self.app.processEvents()
            label = sidebar.version_label
            self.assertEqual(sidebar.width(), 76)
            self.assertEqual(label.text(), VERSION_FILE.read_text(encoding="utf-8-sig").strip())
            self.assertGreaterEqual(label.contentsRect().width(),
                                    label.fontMetrics().horizontalAdvance(label.text()))
            self.assertGreaterEqual(label.contentsRect().height(), label.fontMetrics().height())
            self.assertLessEqual(label.font().pixelSize(), 10)
            self.assertGreaterEqual(label.font().pixelSize(), 8)


if __name__ == "__main__":
    unittest.main()
