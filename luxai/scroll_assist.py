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


class _AnchorMark(QWidget):
    """Small round ↕ marker where autoscroll started."""

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.resize(30, 30)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#ffffff"), 1.5))
        painter.setBrush(QColor(30, 34, 42, 220))
        painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(Qt.PenStyle.NoPen)
        center = self.rect().center()
        painter.drawPolygon([QPoint(center.x(), 6), QPoint(center.x() - 5, 12), QPoint(center.x() + 5, 12)])
        painter.drawPolygon([QPoint(center.x(), 24), QPoint(center.x() - 5, 18), QPoint(center.x() + 5, 18)])
        painter.drawEllipse(center, 2, 2)


class ScrollAssist(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.area = None
        self.anchor = QPoint()
        self.autoscrolling = False
        self._moved_while_held = False
        self._mark = None
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
        if self._mark is None:
            self._mark = _AnchorMark()
        self._mark.move(self.anchor - QPoint(15, 15))
        self._mark.show()
        QGuiApplication.setOverrideCursor(Qt.CursorShape.SizeVerCursor)
        self._timer.start()

    def stop(self):
        if self.autoscrolling:
            QGuiApplication.restoreOverrideCursor()
        self.autoscrolling = False
        self._timer.stop()
        self.area = None
        if self._mark is not None:
            self._mark.hide()

    def _tick(self):
        area = self.area
        try:
            if area is None or not area.isVisible():
                self.stop()
                return
            step = autoscroll_step(QCursor.pos().y() - self.anchor.y())
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
