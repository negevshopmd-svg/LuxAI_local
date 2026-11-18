"""0.4.1t: visual avatar like Luxify — states, sound, window, page, voice."""
from __future__ import annotations

import unittest
from unittest import mock

import numpy as np
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect
from PySide6.QtWidgets import QApplication

from luxai import avatar as av
from luxai import extensions_catalog as catalog

DEFAULTS = catalog.default_settings(catalog.PLUGIN_BY_ID["visual_avatar"])


class LogicTests(unittest.TestCase):
    def test_state_priority_and_colours(self):
        base = "#1f8fe0"
        self.assertEqual(av.resolve_state({}, DEFAULTS, base), ("idle", base))
        self.assertEqual(av.resolve_state({"listening": True}, DEFAULTS, base), ("listening", base))
        self.assertEqual(av.resolve_state({"speak": True}, DEFAULTS, base), ("speak", "#f5b942"))
        self.assertEqual(av.resolve_state({"speak": True, "exec": True}, DEFAULTS, base)[0], "exec")
        self.assertEqual(av.resolve_state({"exec": True, "error": True}, DEFAULTS, base)[0], "error")
        self.assertEqual(av.resolve_state({"mic_off": True}, DEFAULTS, base), ("mic_off", "#7c8696"))
        self.assertEqual(av.resolve_state({"mic_off": True, "speak": True}, DEFAULTS, base)[0], "speak")
        own = dict(DEFAULTS, c_exec="#112233", s_speak=False)
        self.assertEqual(av.resolve_state({"exec": True}, own, base), ("exec", "#112233"))
        self.assertEqual(av.resolve_state({"speak": True}, own, base), ("speak", base))  # this state switched off
        self.assertEqual(av.resolve_state({"error": True}, dict(DEFAULTS, state_colors=False), base), ("error", base))

    def test_loudness_and_sensitivity(self):
        self.assertEqual(av.loudness(0.0, 0.5), 0.0)
        quiet = av.loudness(0.003, 0.5)
        self.assertLess(quiet, av.loudness(0.003, 1.0))
        self.assertGreater(av.loudness(0.3, 0.5), 0.9)

    def test_positions_and_edges(self):
        area = QRect(0, 0, 1920, 1040)
        side, radius = 170, av.orb_radius(170)

        def orb(point):  # visible orb box of a window placed at ``point``
            cx, cy = point.x() + side // 2, point.y() + side // 2
            return cx - radius, cy - radius, cx + radius, cy + radius

        # The grid puts the ORB itself 12 px from the corner, not the glow box.
        left, top, right, bottom = orb(av.preset_point("br", area, side))
        self.assertEqual((area.right() - right, area.bottom() - bottom), (av.EDGE_GAP, av.EDGE_GAP))
        left, top, _r, _b = orb(av.preset_point("tl", area, side))
        self.assertEqual((left, top), (av.EDGE_GAP, av.EDGE_GAP))
        # Dropped near the top-right corner: sticks to BOTH edges.
        point, edge = av.snap_to_edges(QRect(1730, 20, side, side), area, mini=False)
        left, top, right, bottom = orb(point)
        self.assertEqual(edge, "right-top")
        self.assertEqual((area.right() - right, top - area.top()), (av.EDGE_GAP, av.EDGE_GAP))
        # Mini mode in the corner: the window sits flush with both edges (never cut off)…
        point, edge = av.snap_to_edges(QRect(1730, 20, side, side), area, mini=True)
        self.assertEqual(edge, "right-top")
        self.assertEqual((point.x() + side - 1, point.y()), (area.right(), area.top()))
        self.assertEqual(av.touching_walls(QRect(point.x(), point.y(), side, side), area), {"right", "top"})
        # …and the orb is pressed flat against the walls, with a rounded transition.
        self.assertAlmostEqual(av.soft_press(-50.0, 3.0, 5.0), 3.0, delta=0.01)
        self.assertAlmostEqual(av.soft_press(80.0, 3.0, 5.0), 80.0, delta=0.01)
        self.assertGreater(av.soft_press(3.0, 3.0, 5.0), 3.0)
        # The glow margin no longer keeps it away: a window whose BOX is 40 px off still snaps.
        point, edge = av.snap_to_edges(QRect(1920 - side - 40, 500, side, side), area)
        self.assertEqual(edge, "right")
        point, edge = av.snap_to_edges(QRect(800, 400, side, side), area)
        self.assertEqual((point, edge), (QPoint(800, 400), ""))

    def test_screenshot_overlay_is_not_a_fullscreen_game(self):
        self.assertIn("screenclippinghost.exe", av.OVERLAY_APPS)
        self.assertIn("snippingtool.exe", av.OVERLAY_APPS)
        with mock.patch("sys.platform", "linux"):
            self.assertFalse(av.fullscreen_app_running())

    def test_failures_flash_red(self):
        self.assertTrue(av.looks_failed("Не удалось открыть Discord"))
        self.assertTrue(av.looks_failed("Nu am putut găsi fișierul"))
        self.assertTrue(av.looks_failed("Could not connect"))
        self.assertFalse(av.looks_failed("Открыл Discord."))

    def test_meter_reads_loudness(self):
        meter = av.LevelMeter()
        meter.push(np.full(800, 0.2, dtype=np.float32))
        self.assertGreater(meter.level(), 0.8)
        meter.push(np.zeros(800, dtype=np.float32))


class WidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_view_follows_settings_and_level(self):
        view = av.AvatarView()
        self.addCleanup(view.deleteLater)
        view.configure(dict(DEFAULTS, opacity=40, fps="30"), "#ff0000")
        self.assertAlmostEqual(view.opacity, 0.4)
        self.assertEqual(view.target.name(), "#ff0000")
        view.demo_level = lambda phase: 1.0
        import time
        for _ in range(30):
            view._last = time.monotonic() - 0.05
            view._tick()
        self.assertGreater(view._level, 0.5)
        view.react = False
        for _ in range(200):
            view._last = time.monotonic() - 0.05
            view._tick()
        self.assertLess(view._level, 0.05)

    def test_orb_is_pressed_against_the_wall_not_cut(self):
        view = av.AvatarView()
        self.addCleanup(view.deleteLater)
        view.resize(170, 170)
        view.walls = {"top"}
        radius = 170 * 0.27
        center = view.orb_center(radius)
        path = view.shape(radius, 0, center, radius)
        box = path.boundingRect()
        self.assertGreaterEqual(box.top(), view.WALL_GAP - 0.01)   # nothing above the screen edge
        self.assertLess(box.top(), view.WALL_GAP + 3)               # flat side right at the edge
        self.assertGreater(box.width(), box.height())               # a «D» lying on its flat side
        view.walls = set()
        round_box = view.shape(radius, 0).boundingRect()
        self.assertAlmostEqual(round_box.width(), round_box.height(), delta=radius * 0.3)

    def test_window_size_lock_and_preset(self):
        window = av.AvatarWindow(av.LevelMeter())
        self.addCleanup(window.deleteLater)
        window.apply(dict(DEFAULTS, size=150, lock=True, position="tl"), "#1f8fe0")
        self.assertEqual(window.width(), int(av.BASE_SIZE * 1.5))
        from PySide6.QtCore import Qt
        self.assertTrue(window.windowFlags() & Qt.WindowType.WindowTransparentForInput)
        area = window.screen_area(0)
        self.assertEqual(window.pos(), av.preset_point("tl", area, window.width()))
        window.apply(dict(DEFAULTS, position=f"{area.left() + 300},{area.top() + 200}"), "#1f8fe0")
        self.assertEqual(window.pos(), QPoint(area.left() + 300, area.top() + 200))


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from luxai.extensions_runtime import ExtensionsRuntime
        self.host = mock.Mock()
        self.host.cfg = {"language": "ru", "microphone_enabled": True, "tts_enabled": True, "ui_accent": "#ff8800"}
        self.host._processing = False
        self.runtime = ExtensionsRuntime(self.host)
        self.meter = mock.patch("luxai.avatar.LevelMeter.start").start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self.runtime._close_avatar()
        self.runtime.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def state(self, **settings):
        return catalog.normalize_state({"visual_avatar": {"enabled": True, "settings": settings}})

    def test_shown_with_colours_by_state(self):
        self.runtime.apply(self.state())
        window = self.runtime._avatar_window
        self.assertIsNotNone(window)
        self.meter.assert_called_once_with("voice", [])
        self.host._processing = True
        self.runtime._tick_avatar()
        self.assertEqual(window.view.target.name(), "#2ecf8f")
        self.host._processing = False
        self.runtime.avatar_event("error")
        self.runtime._tick_avatar()
        self.assertEqual(window.view.target.name(), "#ef5350")
        self.runtime._avatar_error_until = 0
        self.host.cfg["microphone_enabled"] = False
        self.runtime._tick_avatar()
        self.assertEqual(window.view.target.name(), "#7c8696")

    def test_theme_colour_and_autostart_off(self):
        self.runtime.apply(self.state(color_mode="theme"))
        self.assertEqual(self.runtime._avatar_base_color(), "#ff8800")
        self.runtime._close_avatar()
        from luxai.extensions_runtime import ExtensionsRuntime
        fresh = ExtensionsRuntime(self.host)
        self.addCleanup(fresh._close_avatar)
        fresh.apply(self.state(autostart=False))
        self.assertIsNone(fresh._avatar_window)  # waits for «покажи аватар»
        fresh.host.set_extension_enabled = mock.Mock()
        self.assertEqual(fresh.handle_text_request("Джарвис, покажи аватар"), "Показал аватар.")
        self.assertIsNotNone(fresh._avatar_window)
        self.assertEqual(fresh.handle_text_request("скрой аватар"), "Скрыл аватар.")
        self.assertIsNone(fresh._avatar_window)

    def test_fullscreen_hides_and_moving_saves_place(self):
        self.runtime.apply(self.state())
        window = self.runtime._avatar_window
        with mock.patch("luxai.avatar.fullscreen_app_running", return_value=True):
            for _ in range(10):
                self.runtime._tick_avatar()
            self.assertTrue(window.isVisible())  # one second is not enough (screenshot overlay)
            for _ in range(10):
                self.runtime._tick_avatar()
        self.assertFalse(window.isVisible())
        with mock.patch("luxai.avatar.fullscreen_app_running", return_value=False):
            for _ in range(10):
                self.runtime._tick_avatar()
        self.assertTrue(window.isVisible())  # back at once after the game
        window.hide()  # hidden by something else
        with mock.patch("luxai.avatar.fullscreen_app_running", return_value=False):
            for _ in range(10):
                self.runtime._tick_avatar()
        self.assertTrue(window.isVisible())
        self.runtime._avatar_moved(100, 200)
        self.host.update_extension_setting.assert_called_with("visual_avatar", "position", "100,200")


class PageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_page_like_luxify(self):
        from luxai.extensions_runtime import ExtensionsRuntime
        from luxai.ui_extension_settings import ColorField, PluginSettingsView, PositionGrid
        host = mock.Mock()
        host.cfg = {"language": "ru"}
        runtime = ExtensionsRuntime(host)
        runtime.state = catalog.normalize_state({"visual_avatar": {"settings": {"position": "tl"}}})
        plugin = catalog.PLUGIN_BY_ID["visual_avatar"]
        self.assertTrue(plugin.ready)
        view = PluginSettingsView(plugin, runtime.state["visual_avatar"], "ru", runtime=runtime)
        self.addCleanup(view.deleteLater)
        self.assertEqual(list(view.cards), ["look", "motion", "reaction", "states", "source", "behaviour", "basic"])
        self.assertIsInstance(view.fields["c_exec"], ColorField)
        self.assertEqual(view.position_grid.value, "tl")  # loaded hidden value reaches the grid
        view.position_grid.changed.emit("mc")
        self.assertEqual(view.collect()["position"], "mc")
        view.fields["state_colors"].setChecked(False)
        self.assertFalse(view.rows["s_exec"].isEnabled())
        self.assertTrue(hasattr(view, "avatar_preview"))
        view._next_preview_state()
        self.assertEqual(view.avatar_state_label.text(), "Слушает")
        self.assertIsInstance(view.position_grid, PositionGrid)
        view.detach()


if __name__ == "__main__":
    unittest.main()
