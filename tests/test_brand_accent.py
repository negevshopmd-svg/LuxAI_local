"""Brand and registered navigation icons follow the selected accent."""
import unittest

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication, QWidget

from luxai.icons import icon, refresh_icons, theme_color
from luxai.ui_sidebar import NavigationSidebar


def logical_pixel(image, x, y):
    ratio = image.devicePixelRatio()
    return image.pixelColor(round(x * ratio), round(y * ratio))


class BrandAccentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def sidebar(self):
        sidebar = NavigationSidebar()
        sidebar.resize(177, 680)
        self.addCleanup(sidebar.close)
        self.addCleanup(refresh_icons, sidebar, "dark", "#3978f6")
        return sidebar

    def test_brand_tile_changes_from_blue_to_purple_and_green(self):
        values = []
        for accent in ("#3978f6", "#873eff", "#1bbf8b"):
            image = icon("jarvis", color=accent).pixmap(QSize(64, 64)).toImage()
            values.append(logical_pixel(image, 10, 25))
            # The robot glyph remains white, independent of tile color.
            glyph = logical_pixel(image, 32, 16)
            self.assertGreater(min(glyph.red(), glyph.green(), glyph.blue()), 240)
        blue, purple, green = values
        self.assertLess(blue.red(), blue.green())
        self.assertGreater(purple.red(), purple.green() + 30)
        self.assertGreater(purple.blue(), purple.green() + 60)
        self.assertGreater(green.green(), green.red() + 60)

    def test_sidebar_brand_and_selected_icon_refresh_with_ancestor_accent(self):
        sidebar = self.sidebar()
        sidebar.show()
        rendered = []
        selected = []
        for theme, accent in (("dark", "#873eff"), ("light", "#1bbf8b")):
            refresh_icons(sidebar, theme, accent)
            self.app.processEvents()
            rendered.append(logical_pixel(sidebar.mark.grab().toImage(), 7, 18))
            selected.append(sidebar.nav_buttons[0].icon().pixmap(21, 21).toImage())
            self.assertEqual(theme_color("accent", sidebar.mark), accent)
        self.assertGreater(rendered[0].red(), rendered[0].green() + 30)
        self.assertGreater(rendered[1].green(), rendered[1].red() + 60)
        self.assertNotEqual(bytes(selected[0].constBits()), bytes(selected[1].constBits()))
        self.assertEqual(sidebar.nav_buttons[0].text(), "Главная")
        self.assertEqual(sidebar.width(), 177)

    def test_semantic_status_colors_do_not_become_accent_colors(self):
        root = QWidget()
        self.addCleanup(root.close)
        self.addCleanup(refresh_icons, root, "dark", "#3978f6")
        refresh_icons(root, "dark", "#873eff")
        self.assertEqual(theme_color("accent", root), "#873eff")
        self.assertEqual(theme_color("danger", root), "#fb8d8d")
        self.assertEqual(theme_color("success", root), "#80c99b")


if __name__ == "__main__":
    unittest.main()
