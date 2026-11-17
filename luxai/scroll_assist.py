"""Scrolling without a mouse wheel (0.4.1k), for every page of Jarvis.

Installed once on the QApplication:
- Middle-click autoscroll like browsers: press the wheel button, move the
  mouse up/down — speed grows with distance; any click or Esc stops it.
  Holding the button and releasing after a drag also stops it.
- Drag-to-scroll: press the left button on an empty background (not on a
  button, field, list or slider) and drag, like on a phone.
- PageUp / PageDown / Home / End / Space scroll the area under the cursor
  when the keyboard focus is not in a text field.
Nothing here changes data; it only moves scroll bars.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox, QApplication,
    QComboBox, QLabel, QLineEdit, QMenu, QPlainTextEdit, QTextEdit, QWidget,
)

DEAD_ZONE = 12
DRAG_THRESHOLD = 6
_INTERACTIVE = (QAbstractButton, QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSlider, QAbstractSpinBox,
                QComboBox, QAbstractItemView, QMenu)


def scroll_area_at(widget):
    """Nearest ancestor scroll area that can actually scroll vertically."""
    node = widget
    while node is not None:
        if isinstance(node, QAbstractScrollArea) and node.verticalScrollBar().maximum() > 0:
            return node
        node = node.parentWidget()
    return None


def autoscroll_step(offset: int) -> int:
    """Pixels per 16 ms tick for a cursor ``offset`` pixels from the anchor."""
    distance = abs(offset) - DEAD_ZONE
    if distance <= 0:
        return 0
    step = max(1, int(distance / 6 + (distance / 60) ** 2))
    return min(step, 120) * (1 if offset > 0 else -1)


def direction_of(offset: int) -> int:
    """-1 up, 0 resting (inside the dead zone), 1 down."""
    return 0 if abs(offset) <= DEAD_ZONE else (1 if offset > 0 else -1)


_CURSORS = {}


def _draw_cursor(direction: int):
    """Windows-style autoscroll pointer (as in browsers and the Claude app):
    at rest a light disc with ▲ • ▼; while scrolling a small ring with one
    arrow pointing where the page moves."""
    from PySide6.QtGui import QPixmap, QPolygonF
    from PySide6.QtCore import QPointF
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    light, dark = QColor("#f4f1e4"), QColor("#202020")
    outline = QPen(dark, 1.2)
    if direction == 0:
        painter.setPen(outline)
        painter.setBrush(light)
        painter.drawEllipse(QPointF(16, 16), 11, 11)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dark)
        painter.drawPolygon(QPolygonF([QPointF(16, 7), QPointF(12.5, 11.5), QPointF(19.5, 11.5)]))
        painter.drawPolygon(QPolygonF([QPointF(16, 25), QPointF(12.5, 20.5), QPointF(19.5, 20.5)]))
        painter.drawEllipse(QPointF(16, 16), 2, 2)
    else:
        sign = 1 if direction > 0 else -1
        # ring at the hotspot
        painter.setPen(outline)
        painter.setBrush(light)
        painter.drawEllipse(QPointF(16, 16), 4.5, 4.5)
        painter.setBrush(dark)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(16, 16), 1.5, 1.5)
        # one arrow on the scrolling side
        tip, base = 16 + sign * 14, 16 + sign * 6.5
        painter.setPen(outline)
        painter.setBrush(light)
        painter.drawPolygon(QPolygonF([QPointF(16, tip), QPointF(10, base), QPointF(22, base)]))
    painter.end()
    return pixmap


def direction_cursor(direction: int) -> QCursor:
    """The mouse pointer itself shows the scroll direction (hotspot = centre)."""
    if direction not in _CURSORS:
        _CURSORS[direction] = QCursor(_draw_cursor(direction), 16, 16)
    return _CURSORS[direction]


class ScrollAssist(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.area = None
        self.anchor = QPoint()
        self.autoscrolling = False
        self._moved_while_held = False
        self.direction = 0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._drag_area = None
        self._drag_start = QPoint()
        self._drag_value = 0
        self._dragging = False

    # -- install ---------------------------------------------------------
    @classmethod
    def install(cls, app=None):
        app = app or QApplication.instance()
        existing = getattr(app, "_jarvis_scroll_assist", None)
        if existing is not None:
            return existing
        assist = cls(app)
        app.installEventFilter(assist)
        app._jarvis_scroll_assist = assist
        return assist

    # -- autoscroll --------------------------------------------------------
    def start_autoscroll(self, area, global_pos):
        self.stop()
        self.area = area
        self.anchor = QPoint(global_pos)
        self.autoscrolling = True
        self._moved_while_held = False
        self.direction = 0
        QGuiApplication.setOverrideCursor(direction_cursor(0))
        self._timer.start()

    def stop(self):
        if self.autoscrolling:
            QGuiApplication.restoreOverrideCursor()
        self.autoscrolling = False
        self._timer.stop()
        self.area = None
        self.direction = 0

    def _tick(self):
        area = self.area
        try:
            if area is None or not area.isVisible():
                self.stop()
                return
            offset = QCursor.pos().y() - self.anchor.y()
            direction = direction_of(offset)
            if direction != self.direction:
                self.direction = direction
                QGuiApplication.changeOverrideCursor(direction_cursor(direction))
            step = autoscroll_step(offset)
            if step:
                bar = area.verticalScrollBar()
                bar.setValue(bar.value() + step)
        except RuntimeError:  # the area was deleted
            self.stop()

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _is_empty_background(widget):
        if widget is None or isinstance(widget, _INTERACTIVE):
            return False
        if isinstance(widget, QLabel) and widget.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse:
            return False
        node = widget
        while node is not None:  # inside an interactive control (e.g. a list's viewport)
            if isinstance(node, _INTERACTIVE) or node.objectName() == "WindowHeader":
                return False
            if isinstance(node, QAbstractScrollArea):
                return not isinstance(node, (QTextEdit, QPlainTextEdit, QAbstractItemView))
            node = node.parentWidget()
        return False

    @staticmethod
    def _typing(widget):
        return isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox))

    # -- event filter ------------------------------------------------------
    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress and isinstance(watched, QWidget):
            if self.autoscrolling:
                self.stop()
                return True  # this click only ends autoscroll
            if event.button() == Qt.MouseButton.MiddleButton:
                area = scroll_area_at(watched)
                if area is not None:
                    self.start_autoscroll(area, event.globalPosition().toPoint())
                    return True
            elif event.button() == Qt.MouseButton.LeftButton and self._is_empty_background(watched):
                area = scroll_area_at(watched)
                if area is not None:
                    self._drag_area = area
                    self._drag_start = event.globalPosition().toPoint()
                    self._drag_value = area.verticalScrollBar().value()
                    self._dragging = False
        elif kind == QEvent.Type.MouseMove:
            if self.autoscrolling and event.buttons() & Qt.MouseButton.MiddleButton:
                if abs(event.globalPosition().toPoint().y() - self.anchor.y()) > DEAD_ZONE:
                    self._moved_while_held = True
            if self._drag_area is not None and event.buttons() & Qt.MouseButton.LeftButton:
                delta = event.globalPosition().toPoint().y() - self._drag_start.y()
                if self._dragging or abs(delta) > DRAG_THRESHOLD:
                    if not self._dragging:
                        self._dragging = True
                        QGuiApplication.setOverrideCursor(Qt.CursorShape.ClosedHandCursor)
                    try:
                        self._drag_area.verticalScrollBar().setValue(self._drag_value - delta)
                    except RuntimeError:
                        self._end_drag()
                    return True
        elif kind == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.MiddleButton and self.autoscrolling:
                if self._moved_while_held:
                    self.stop()  # hold-and-drag mode ends on release
                return True
            if event.button() == Qt.MouseButton.LeftButton and self._drag_area is not None:
                dragged = self._dragging
                self._end_drag()
                if dragged:
                    return True
        elif kind == QEvent.Type.KeyPress:
            if self.autoscrolling and event.key() == Qt.Key.Key_Escape:
                self.stop()
                return True
            if event.key() in (Qt.Key.Key_PageDown, Qt.Key.Key_PageUp, Qt.Key.Key_Home, Qt.Key.Key_End):
                focus = QApplication.focusWidget()
                if not self._typing(focus):
                    area = scroll_area_at(QApplication.widgetAt(QCursor.pos())) or scroll_area_at(focus)
                    if area is not None:
                        bar = area.verticalScrollBar()
                        page = max(40, area.viewport().height() - 40)
                        target = {Qt.Key.Key_PageDown: bar.value() + page, Qt.Key.Key_PageUp: bar.value() - page,
                                  Qt.Key.Key_Home: bar.minimum(), Qt.Key.Key_End: bar.maximum()}[event.key()]
                        bar.setValue(target)
                        return True
        return False

    def _end_drag(self):
        if self._dragging:
            QGuiApplication.restoreOverrideCursor()
        self._drag_area = None
        self._dragging = False
