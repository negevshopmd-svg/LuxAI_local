"""Restoring the navigation preference stays silent; user changes emit once."""
import unittest

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from luxai.styles import build_styles
from luxai.ui_sidebar import NavigationSidebar


class SidebarPersistence039Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def sidebar(self):
        sidebar = NavigationSidebar()
        sidebar.resize(sidebar.width(), 700)
        sidebar.show()
        self.app.processEvents()
        self.addCleanup(sidebar.close)
        return sidebar

    def test_restore_is_silent_and_idempotent_in_both_widths(self):
        sidebar = self.sidebar()
        changed = []
        sidebar.collapsed_changed.connect(changed.append)
        sidebar.set_active(3)
        for collapsed in (True, True, False, False):
            with self.subTest(collapsed=collapsed):
                sidebar.set_collapsed(collapsed)
                self.app.processEvents()
                self.assertEqual(sidebar.width(), 76 if collapsed else 177)
                self.assertEqual(sidebar.brand_text.isVisible(), not collapsed)
                self.assertEqual(bool(sidebar.nav_buttons[3].text()), not collapsed)
                self.assertTrue(sidebar.nav_buttons[3].property("active"))
                self.assertTrue(sidebar.version_label.isVisible())
        self.assertEqual(changed, [])

    def test_click_emits_one_boolean_per_user_change_and_page_click_does_not(self):
        sidebar = self.sidebar()
        changes, pages = [], []
        sidebar.collapsed_changed.connect(changes.append)
        sidebar.page_selected.connect(pages.append)
        QTest.mouseClick(sidebar.collapse, Qt.MouseButton.LeftButton)
        self.assertEqual(changes, [True])
        self.assertEqual(sidebar.width(), 76)
        QTest.mouseClick(sidebar.nav_buttons[2], Qt.MouseButton.LeftButton)
        self.assertEqual(pages, [2])
        self.assertEqual(changes, [True])
        QTest.mouseClick(sidebar.collapse, Qt.MouseButton.LeftButton)
        self.assertEqual(changes, [True, False])
        self.assertEqual(sidebar.width(), 177)
        self.assertTrue(all(type(value) is bool for value in changes))

    def test_language_and_theme_changes_preserve_restored_state_without_saving(self):
        sidebar = self.sidebar()
        changes = []
        sidebar.collapsed_changed.connect(changes.append)
        sidebar.set_collapsed(True)
        for language, settings in (("ro", "Setări"), ("en", "Settings"), ("ru", "Настройки")):
            for theme in ("dark", "light"):
                sidebar.set_language(language)
                sidebar.setStyleSheet(build_styles(theme))
                self.app.processEvents()
                self.assertEqual(sidebar.width(), 76)
                self.assertEqual(sidebar.nav_buttons[4].text(), "")
                self.assertEqual(sidebar.nav_buttons[4].toolTip(), settings)
                self.assertFalse(sidebar.nav_buttons[4].icon().isNull())
        sidebar.set_collapsed(False)
        self.assertEqual(sidebar.nav_buttons[4].text(), "Настройки")
        self.assertEqual(changes, [])

    def test_malformed_persisted_values_do_not_enable_collapse(self):
        sidebar = self.sidebar()
        changes = []
        sidebar.collapsed_changed.connect(changes.append)
        for value in (None, "false", "true", 0, 1, [], {}):
            with self.subTest(value=value):
                sidebar.set_collapsed(True)
                sidebar.set_collapsed(value)
                self.assertEqual(sidebar.width(), 177)
                self.assertTrue(sidebar.brand_text.isVisible())
        self.assertEqual(changes, [])


if __name__ == "__main__":
    unittest.main()
