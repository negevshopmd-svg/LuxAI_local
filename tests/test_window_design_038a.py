"""Integrated title controls and full-bleed home decoration remain usable."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication


class WindowDesign038aTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import main
        from luxai.ui_i18n import get_ui_language, set_ui_language
        self.addCleanup(set_ui_language, get_ui_language())
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config = Path(directory.name) / "config.json"
        self.config.write_text(json.dumps({
            "microphone_enabled": False, "tts_enabled": False,
            "online_agent_enabled": False, "ui_theme": "dark", "ui_language": "ru",
            "language": "ro",
            "ui_accent": "#873eff", "ui_animations": False,
        }), encoding="utf-8")
        patcher = mock.patch.object(main, "CONFIG", self.config)
        patcher.start()
        self.addCleanup(patcher.stop)
        with (mock.patch("sounddevice.query_devices", return_value=[]),
              mock.patch.object(main.MainWindow, "_ocr_setup_worker")):
            self.window = main.MainWindow()
        self.addCleanup(self.window.close)
        self.window.resize(1120, 720)
        self.window.show()
        self.app.processEvents()

    def test_single_header_places_microphone_over_cards_and_window_controls_at_right(self):
        window = self.window
        self.assertTrue(window.windowFlags() & Qt.WindowType.FramelessWindowHint)
        mic = window.header_mic_button
        cards = window.home_page.controls_scroll.widget()
        card_right = cards.mapTo(window, QPoint(cards.width(), 0)).x()
        mic_right = mic.mapTo(window, QPoint(mic.width(), 0)).x()
        self.assertLessEqual(abs(card_right - mic_right), 2)
        close = window.window_header.close_button
        self.assertGreater(close.mapTo(window, QPoint()).x(), mic_right + 100)
        self.assertLessEqual(window.width() - close.mapTo(window, QPoint(close.width(), 0)).x(), 10)
        self.assertEqual(close.accessibleName(), "Закрыть")
        self.assertEqual(window.window_header.minimize_button.accessibleName(), "Свернуть окно")

    def test_orb_spans_entire_content_height_and_only_shows_on_home_after_resize(self):
        window = self.window
        orb = window.avatar
        for width, height in ((1120, 720), (1350, 850), (900, 600)):
            window.resize(width, height)
            self.app.processEvents()
            self.assertIs(orb.parentWidget(), window.content_frame)
            self.assertEqual(orb.y(), 0)
            self.assertEqual(orb.height(), window.content_frame.height())
            self.assertEqual(orb.x() + orb.width(), window.content_frame.width())
            self.assertGreater(orb.x(), 350)
            self.assertFalse(orb.isHidden())
        window.show_page(4)
        self.app.processEvents()
        self.assertTrue(orb.isHidden())
        window.show_page(0)
        self.app.processEvents()
        self.assertFalse(orb.isHidden())

    def test_minimize_maximize_restore_and_close_keep_standard_window_actions(self):
        window = self.window
        header = window.window_header
        header.maximize_button.click()
        self.app.processEvents()
        self.assertTrue(window.isMaximized())
        self.assertEqual(header.maximize_button.accessibleName(), "Восстановить")
        self.assertTrue(all(handle.isHidden() for handle in window._window_chrome.handles))
        header.maximize_button.click()
        self.app.processEvents()
        self.assertFalse(window.isMaximized())
        self.assertTrue(all(not handle.isHidden() for handle in window._window_chrome.handles))
        header.minimize_button.click()
        self.app.processEvents()
        self.assertTrue(window.isMinimized())
        window.showNormal()
        header.close_button.click()
        self.assertTrue(window._closed)

    def test_background_and_title_control_language_apply_live_without_changing_voice_language(self):
        window = self.window
        original = window.cfg.get("language")
        panel = window.settings_panel
        panel.background.addItem("Custom", "#111827")
        panel.background.setCurrentIndex(panel.background.findData("#111827"))
        panel.ui_language.setCurrentIndex(panel.ui_language.findData("ro"))
        panel.flush_auto_save()
        self.assertEqual(window.window_header.close_button.accessibleName(), "Închide")
        self.assertIn("#111827", self.app.styleSheet())
        self.assertEqual(window.avatar._background, "#111827")
        self.assertEqual(window.cfg.get("language"), original)
        self.assertEqual(json.loads(self.config.read_text(encoding="utf-8"))["ui_background"], "#111827")

    def test_drag_and_resize_fallback_preserve_minimum_size_without_native_frame(self):
        window = self.window
        native = SimpleNamespace(startSystemMove=mock.Mock(return_value=False),
                                 startSystemResize=mock.Mock(return_value=False))
        def mouse(kind, point, pressed=True):
            return QMouseEvent(kind, QPointF(2, 2), QPointF(point),
                               Qt.MouseButton.LeftButton if kind == QEvent.Type.MouseButtonPress else Qt.MouseButton.NoButton,
                               Qt.MouseButton.LeftButton if pressed else Qt.MouseButton.NoButton,
                               Qt.KeyboardModifier.NoModifier)
        with mock.patch.object(window, "windowHandle", return_value=native):
            position = QPoint(window.pos())
            origin = window.mapToGlobal(QPoint(100, 20))
            window.window_header.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, origin))
            window.window_header.mouseMoveEvent(mouse(QEvent.Type.MouseMove, origin + QPoint(25, 30)))
            self.assertEqual(window.pos(), position + QPoint(25, 30))
            window.window_header.mouseReleaseEvent(mouse(QEvent.Type.MouseButtonRelease, origin, False))
            handle = window._window_chrome.handles[-1]
            size = window.size()
            origin = window.mapToGlobal(QPoint(window.width() - 2, window.height() - 2))
            handle.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, origin))
            handle.mouseMoveEvent(mouse(QEvent.Type.MouseMove, origin + QPoint(120, 80)))
            self.assertEqual(window.width(), size.width() + 120)
            self.assertEqual(window.height(), size.height() + 80)
            handle.mouseMoveEvent(mouse(QEvent.Type.MouseMove, origin - QPoint(10000, 10000)))
            self.assertEqual(window.width(), window.minimumWidth())
            self.assertEqual(window.height(), window.minimumHeight())
            handle.mouseReleaseEvent(mouse(QEvent.Type.MouseButtonRelease, origin, False))
        native.startSystemMove.assert_called_once()
        native.startSystemResize.assert_called_once_with(Qt.Edge.BottomEdge | Qt.Edge.RightEdge)

    def test_direct_entry_prepares_engine_for_existing_windows_autostart_paths(self):
        import main
        with (mock.patch("luxai.local_ai_setup.start_background_setup") as schedule,
              mock.patch.object(main, "QApplication") as application,
              mock.patch.object(main, "MainWindow") as factory):
            application.return_value.exec.return_value = 0
            self.assertEqual(main.main(), 0)
        schedule.assert_called_once_with()
        factory.return_value.show.assert_called_once_with()
