"""Selected theme colors reach painted controls and native Qt surfaces."""
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QProgressBar, QSlider

from luxai.icons import refresh_icons
from luxai.styles import build_styles, theme_colors
from luxai.ui_home import HomePage, OrbVisual, ToggleSwitch


def pixel(widget, x, y):
    value = widget.grab().toImage()
    ratio = value.devicePixelRatio()
    return value.pixelColor(round(x * ratio), round(y * ratio))


class HomeAccentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def assert_purple(self, color):
        self.assertGreater(color.red(), color.green())
        self.assertGreater(color.blue(), color.red())

    def assert_green(self, color):
        self.assertGreater(color.green(), color.red())
        self.assertGreater(color.green(), color.blue())

    def test_orb_rings_follow_purple_and_green_in_both_themes(self):
        orb = OrbVisual()
        orb.resize(400, 600)
        orb.show()
        self.addCleanup(orb.close)
        for theme in ("dark", "light"):
            for accent, check in (("#873eff", self.assert_purple),
                                  ("#1bbf8b", self.assert_green)):
                orb.set_theme(theme, accent)
                self.app.processEvents()
                # Sample distinct actual rings, rather than inspecting the
                # palette implementation or hardcoding their geometry colors.
                for x in (20, 100, 220, 380):
                    with self.subTest(theme=theme, accent=accent, x=x):
                        check(pixel(orb, x, 300))

    def test_switch_and_progress_fill_follow_accent_instead_of_native_blue(self):
        switch = ToggleSwitch(True)
        switch.show()
        self.addCleanup(switch.close)
        progress = QProgressBar()
        progress.resize(200, 24)
        progress.setValue(50)
        progress.show()
        self.addCleanup(progress.close)
        for theme in ("dark", "light"):
            for accent, check in (("#873eff", self.assert_purple),
                                  ("#1bbf8b", self.assert_green)):
                switch.set_theme(theme, accent)
                progress.setStyleSheet(build_styles(theme, accent))
                self.app.processEvents()
                with self.subTest(theme=theme, accent=accent):
                    check(pixel(switch, 15, 14))
                    check(pixel(progress, 20, 12))
                    self.assertTrue(switch.isChecked())
                    self.assertEqual(progress.value(), 50)

    def test_home_theme_change_preserves_controls_history_and_hidden_activity(self):
        home = HomePage({"prefix_enabled": True, "voice_volume": 77,
                         "ui_animations": False, "ui_accent": "#873eff"})
        home.resize(1050, 680)
        home.show()
        self.addCleanup(home.close)
        home.home_history.setPlainText("Existing conversation")
        initial = [switch.isChecked() for switch in (
            home.home_prefix, home.home_quiet, home.home_avatar, home.home_top,
        )]
        changed = []
        for switch in (home.home_prefix, home.home_quiet, home.home_avatar, home.home_top):
            switch.toggled.connect(lambda checked: changed.append(checked))
        for theme, accent in (("dark", "#873eff"), ("light", "#1bbf8b")):
            home.setStyleSheet(build_styles(theme, accent))
            refresh_icons(home, theme, accent)
            home.set_theme(theme, accent)
            self.app.processEvents()
            self.assertEqual(home.home_history.toPlainText(), "Existing conversation")
            self.assertEqual(home.volume.value(), 77)
            self.assertEqual([switch.isChecked() for switch in (
                home.home_prefix, home.home_quiet, home.home_avatar, home.home_top,
            )], initial)
            self.assertFalse(home.history_activity.isVisible())
        self.assertEqual(changed, [])

    def test_invalid_accent_falls_back_consistently_and_surfaces_are_tinted(self):
        self.assertEqual(theme_colors("dark", "invalid")["accent"], "#3978f6")
        for theme in ("dark", "light"):
            purple = theme_colors(theme, "#873eff")
            blue = theme_colors(theme, "#3978f6")
            self.assertNotEqual(purple["selection"], blue["selection"])
            self.assertNotEqual(purple["hover"], blue["hover"])
            css = build_styles(theme, "#873eff")
            self.assertIn("background: #873eff", css)
            self.assertIn("QProgressBar::chunk", css)
            self.assertNotIn("$", css)

    def test_light_slider_handle_remains_visible_on_light_track(self):
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.resize(200, 24)
        slider.setValue(50)
        slider.setStyleSheet(build_styles("light", "#873eff"))
        slider.show()
        self.addCleanup(slider.close)
        self.app.processEvents()
        center = pixel(slider, slider.width() // 2, slider.height() // 2)
        self.assertLess(max(center.red(), center.green(), center.blue()), 150)


if __name__ == "__main__":
    unittest.main()
