"""Decorative rings and sliders render without a rectangular backing frame."""
import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSlider, QWidget

from luxai.styles import build_styles, theme_colors
from luxai.ui_home import HomePage, OrbVisual


def pixel(widget, x, y):
    image = widget.grab().toImage()
    ratio = image.devicePixelRatio()
    return image.pixelColor(round(x * ratio), round(y * ratio))


class HomeBackdrop038aTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_detached_orb_keeps_reserved_home_width_controls_and_animation_object(self):
        home = HomePage({"prefix_enabled": True, "voice_volume": 71})
        host = QWidget()
        self.addCleanup(home.close)
        self.addCleanup(host.close)
        home.resize(960, 650)
        home.show()
        self.app.processEvents()
        previous = home.avatar
        previous.set_animated(True)
        detached = home.detach_avatar(host)
        self.assertIs(detached, previous)
        self.assertIs(detached.parentWidget(), host)
        self.assertIsNot(home.hero_space, detached)
        self.assertGreaterEqual(home.layout().indexOf(home.hero_space), 0)
        self.assertEqual(home.layout().indexOf(detached), -1)
        self.assertEqual(home.volume.value(), 71)
        self.assertTrue(home.home_prefix.isChecked())
        self.assertTrue(detached._animated)
        self.assertTrue(detached.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        placeholder = home.hero_space
        home.detach_avatar(host)
        self.assertIs(home.hero_space, placeholder)
        self.assertEqual(home.layout().count(), 2)

    def test_full_height_rings_leave_left_outside_transparent_and_reach_top_bottom(self):
        host = QWidget()
        host.resize(440, 720)
        host.setStyleSheet("QWidget#BackdropHost { background: #15253a; }")
        host.setObjectName("BackdropHost")
        orb = OrbVisual(host)
        orb.setGeometry(host.rect())
        orb.setStyleSheet("QWidget#HeroOrb { background: transparent; border: none; }")
        orb.set_theme("dark", "#873eff")
        host.show()
        self.addCleanup(host.close)
        self.app.processEvents()
        outside = QColor("#15253a")
        self.assertEqual(pixel(host, 2, host.height() // 2), outside)
        self.assertEqual(pixel(host, 2, 2), outside)
        # The backdrop fills the right edge above/below the content cards.
        self.assertNotEqual(pixel(host, host.width() - 8, 0), outside)
        self.assertNotEqual(pixel(host, host.width() - 8, host.height() - 1), outside)

    def test_slider_has_only_a_thin_track_without_dark_outer_box(self):
        for theme, parent_color in (("dark", "#192d38"), ("light", "#e0eddf")):
            with self.subTest(theme=theme):
                host = QWidget()
                host.resize(230, 55)
                host.setObjectName("SliderHost")
                host.setStyleSheet(build_styles(theme, "#873eff") +
                                   f"QWidget#SliderHost {{ background: {parent_color}; }}")
                slider = QSlider(Qt.Orientation.Horizontal, host)
                slider.setGeometry(10, 12, 210, 30)
                slider.setRange(0, 100)
                slider.setValue(40)
                slider.clearFocus()
                host.show()
                self.addCleanup(host.close)
                self.app.processEvents()
                host.activateWindow()
                slider.setFocus()
                self.app.processEvents()
                # Above and below the groove the parent surface is visible.
                for x, y in ((20, 12), (20, 41), (200, 12), (200, 41)):
                    self.assertEqual(pixel(host, x, y), QColor(parent_color))
                center_y = slider.y() + slider.height() // 2
                self.assertEqual(pixel(host, 35, center_y), QColor("#873eff"))
                QTest.keyClick(slider, Qt.Key.Key_Right)
                self.assertEqual(slider.value(), 41)

    def test_custom_background_is_validated_and_shared_by_css_and_orb(self):
        for theme in ("dark", "light"):
            default = theme_colors(theme, "#873eff")
            for invalid in (None, "", "red", "#112233; background:red", "#12345"):
                self.assertEqual(theme_colors(theme, "#873eff", invalid)["bg"], default["bg"])
            colors = theme_colors(theme, "#873eff", "#182D27")
            self.assertEqual(colors["bg"], "#182d27")
            self.assertEqual(colors["black"], colors["bg"])
            self.assertEqual(colors["accent"], "#873eff")
            css = build_styles(theme, "#873eff", "#182D27")
            self.assertIn("background: #182d27", css)
            self.assertNotIn("$", css)
            home = HomePage({"ui_theme": theme, "ui_background": "#182D27"})
            self.addCleanup(home.close)
            self.assertEqual(home.avatar._background, colors["bg"])


if __name__ == "__main__":
    unittest.main()
