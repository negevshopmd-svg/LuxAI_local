"""0.4.1k Scrolling without a mouse wheel: autoscroll, drag, keys, visible bars."""
import unittest

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from luxai.scroll_assist import ScrollAssist, autoscroll_step, scroll_area_at


def mouse(kind, widget, pos, button, buttons):
    local = QPointF(pos)
    return QMouseEvent(kind, local, QPointF(widget.mapToGlobal(pos)), button, buttons, Qt.KeyboardModifier.NoModifier)


class ScrollAssistTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.assist = ScrollAssist.install(cls.app)

    def setUp(self):
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        content = QWidget()
        column = QVBoxLayout(content)
        self.label = QLabel("Пустое место")
        self.button = QPushButton("Кнопка")
        self.field = QLineEdit()
        column.addWidget(self.label)
        column.addWidget(self.button)
        column.addWidget(self.field)
        column.addSpacing(3000)
        self.area.setWidget(content)
        self.area.resize(300, 300)
        self.area.show()
        self.app.processEvents()
        self.bar = self.area.verticalScrollBar()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.assist.stop()
        self.assist._end_drag()
        self.area.close()
        self.area.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_step_has_dead_zone_and_direction(self):
        self.assertEqual(autoscroll_step(5), 0)
        self.assertGreater(autoscroll_step(80), 0)
        self.assertLess(autoscroll_step(-80), 0)
        self.assertGreater(autoscroll_step(300), autoscroll_step(80))
        self.assertIs(scroll_area_at(self.label), self.area)

    def test_middle_click_autoscroll_starts_scrolls_and_stops(self):
        press = mouse(QEvent.Type.MouseButtonPress, self.label, QPoint(10, 10), Qt.MouseButton.MiddleButton,
                      Qt.MouseButton.MiddleButton)
        QApplication.sendEvent(self.label, press)
        self.assertTrue(self.assist.autoscrolling)
        self.assist.anchor = QPoint(self.assist.anchor.x(), self.assist.anchor.y() - 200)  # cursor far below
        for _ in range(5):
            self.assist._tick()
        self.assertGreater(self.bar.value(), 0)
        click = mouse(QEvent.Type.MouseButtonPress, self.label, QPoint(10, 10), Qt.MouseButton.LeftButton,
                      Qt.MouseButton.LeftButton)
        QApplication.sendEvent(self.label, click)
        self.assertFalse(self.assist.autoscrolling)

    def test_drag_on_empty_background_scrolls_but_not_on_controls(self):
        start = QPoint(20, 10)
        QApplication.sendEvent(self.label, mouse(QEvent.Type.MouseButtonPress, self.label, start,
                                                 Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton))
        QApplication.sendEvent(self.label, mouse(QEvent.Type.MouseMove, self.label, start - QPoint(0, 150),
                                                 Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton))
        QApplication.sendEvent(self.label, mouse(QEvent.Type.MouseButtonRelease, self.label, start - QPoint(0, 150),
                                                 Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton))
        self.assertEqual(self.bar.value(), 150)
        self.bar.setValue(0)
        QApplication.sendEvent(self.field, mouse(QEvent.Type.MouseButtonPress, self.field, QPoint(5, 5),
                                                 Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton))
        QApplication.sendEvent(self.field, mouse(QEvent.Type.MouseMove, self.field, QPoint(5, -150),
                                                 Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton))
        self.assertEqual(self.bar.value(), 0)  # selecting text in a field never scrolls the page

    def test_page_keys_scroll_when_not_typing(self):
        self.button.setFocus()
        self.app.processEvents()
        with unittest.mock.patch("luxai.scroll_assist.QApplication.widgetAt", return_value=self.label):
            QTest.keyClick(self.button, Qt.Key.Key_PageDown)
            self.assertGreater(self.bar.value(), 0)
            QTest.keyClick(self.button, Qt.Key.Key_End)
            self.assertEqual(self.bar.value(), self.bar.maximum())
            QTest.keyClick(self.button, Qt.Key.Key_Home)
            self.assertEqual(self.bar.value(), 0)

    def test_scrollbars_are_wide_and_visible(self):
        from luxai.styles import build_styles
        css = build_styles("dark", "#f97316")
        self.assertIn("width: 14px", css.split("QScrollBar:vertical {", 1)[1][:80])
        self.assertNotIn("$barhandle", css)
        self.assertIn("QScrollBar::handle:vertical:hover", css)


import unittest.mock  # noqa: E402

if __name__ == "__main__":
    unittest.main()
