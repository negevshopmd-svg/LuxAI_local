"""Branch gutters never use the native green hover/selection palette."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyleFactory, QTreeWidgetItem

from luxai.styles import theme_colors
from luxai.ui_command_tree import CommandTreeWidget


class CommandTree093dTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tree(self, theme="dark"):
        tree = CommandTreeWidget()
        self.addCleanup(tree.close)
        tree.resize(360, 220)
        tree.setHeaderHidden(True)
        tree.setIndentation(22)
        tree.setRootIsDecorated(True)
        tree.setUniformRowHeights(True)
        colors = theme_colors(theme, "#f2790c")
        tree.set_colors(colors)
        # Deliberately poison native palette/branch styling. A native branch
        # draw would now leave exactly the vivid rectangle reported by users.
        palette = tree.palette()
        for role in (QPalette.ColorRole.Highlight, QPalette.ColorRole.Button,
                     QPalette.ColorRole.Light, QPalette.ColorRole.Midlight):
            palette.setColor(role, QColor("#00ff00"))
        tree.setPalette(palette)
        tree.setStyleSheet(f"""
            QTreeWidget {{background:{colors['surface']}; color:{colors['text']}; border:0;}}
            QTreeWidget::item {{height:34px;}}
            QTreeWidget::item:selected {{background:{colors['selection']};}}
            QTreeWidget::item:hover {{background:{colors['hover']};}}
            QTreeWidget::branch {{background:#00ff00;}}
        """)
        root = QTreeWidgetItem(["Collection"])
        folder = QTreeWidgetItem(["Nested folder"])
        leaf = QTreeWidgetItem(["Saved command"])
        folder.addChild(leaf)
        root.addChild(folder)
        tree.addTopLevelItem(root)
        root.setExpanded(True)
        tree.show()
        self.app.processEvents()
        return tree, root, folder, leaf, colors

    def assert_gutter(self, tree, item, background):
        row = tree.visualItemRect(item)
        image = tree.viewport().grab().toImage()
        self.assertGreater(row.left(), 0)
        self.assertEqual(image.pixelColor(2, row.center().y()), QColor(background))
        for y in range(row.top(), row.bottom() + 1):
            for x in range(row.left()):
                self.assertNotEqual(image.pixelColor(x, y).name(), "#00ff00")

    def test_selected_nested_and_root_rows_fill_the_entire_indentation(self):
        for theme in ("dark", "light"):
            with self.subTest(theme=theme):
                tree, root, folder, _leaf, colors = self.tree(theme)
                for item in (root, folder):
                    tree.setCurrentItem(item)
                    self.app.processEvents()
                    self.assert_gutter(tree, item, colors["selection"])

    def test_hover_and_mouse_leave_follow_row_colors_without_native_blocks(self):
        tree, _root, folder, _leaf, colors = self.tree()
        row = tree.visualItemRect(folder)
        QTest.mouseMove(tree.viewport(), QPoint(row.left() + 20, row.center().y()))
        self.app.processEvents()
        self.assert_gutter(tree, folder, colors["hover"])
        QTest.mouseMove(tree.viewport(), QPoint(2, tree.viewport().height() - 5))
        self.app.processEvents()
        self.assert_gutter(tree, folder, colors["surface"])

    def test_standard_mouse_and_keyboard_expansion_still_work(self):
        tree, root, folder, _leaf, _colors = self.tree()
        tree.setCurrentItem(folder)
        tree.setFocus()
        QTest.keyClick(tree, Qt.Key.Key_Right)
        self.assertTrue(folder.isExpanded())
        QTest.keyClick(tree, Qt.Key.Key_Left)
        self.assertFalse(folder.isExpanded())
        row = tree.visualItemRect(folder)
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton,
                         pos=QPoint(row.left() - tree.indentation() // 2, row.center().y()))
        self.assertTrue(folder.isExpanded())
        self.assertTrue(root.isExpanded())

    def test_windows_style_cannot_reintroduce_native_branch_background(self):
        if "Windows" not in QStyleFactory.keys():
            self.skipTest("Qt Windows style is unavailable")
        tree, root, _folder, _leaf, colors = self.tree()
        style = QStyleFactory.create("Windows")
        tree.setStyle(style)
        style.setParent(tree)
        tree.setCurrentItem(root)
        self.app.processEvents()
        self.assert_gutter(tree, root, colors["selection"])


if __name__ == "__main__":
    unittest.main()
