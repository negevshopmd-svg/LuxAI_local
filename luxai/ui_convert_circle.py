"""Converter UI: radial action menu at the cursor, screen-region picker, crop.

The radial menu is chosen with the mouse, arrow keys + Enter, or digits 1–9;
Esc / click in the centre / click outside closes it.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from luxai.icons import icon


THEMES = {
    "dark": {"bg": QColor(22, 25, 31, 238), "ring": QColor(44, 49, 58, 245), "text": QColor("#f0f2f6"),
             "muted": QColor("#a6acb8"), "line": QColor(70, 76, 88)},
    "light": {"bg": QColor(250, 251, 253, 240), "ring": QColor(233, 237, 244, 250), "text": QColor("#1c2738"),
              "muted": QColor("#667184"), "line": QColor(205, 214, 228)},
}


class RadialMenu(QWidget):
    """items: [(id, label, icon_name)]. Emits picked(id) or cancelled()."""
    picked = Signal(str)
    cancelled = Signal()

    def __init__(self, items, title="", *, theme="dark", accent="#3978f6", parent=None):
        super().__init__(parent)
        self.items = list(items)[:12]
        self.title = title
        self.colors = THEMES.get(theme, THEMES["dark"])
        self.accent = QColor(accent)
        self.current = -1
        self._done = False
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.radius = 172 if len(self.items) > 6 else 145
        self.inner = 56
        size = self.radius * 2 + 16
        self.resize(size, size)

    # geometry
    def _center(self):
        return QPointF(self.width() / 2, self.height() / 2)

    def _sector_at(self, pos):
        center = self._center()
        dx, dy = pos.x() - center.x(), pos.y() - center.y()
        distance = math.hypot(dx, dy)
        if distance < self.inner or distance > self.radius + 6 or not self.items:
            return -1
        angle = (math.degrees(math.atan2(dx, -dy)) + 360) % 360  # 0 = up, clockwise
        span = 360 / len(self.items)
        return int(((angle + span / 2) % 360) // span)

    def show_at(self, point=None):
        point = point or QCursor.pos()
        screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(area.left(), point.x() - self.width() // 2), area.right() - self.width())
        y = min(max(area.top(), point.y() - self.height() // 2), area.bottom() - self.height())
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    # painting
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = self._center()
        outer = QRectF(center.x() - self.radius, center.y() - self.radius, self.radius * 2, self.radius * 2)
        painter.setPen(QPen(self.colors["line"], 1))
        painter.setBrush(self.colors["bg"])
        painter.drawEllipse(outer)
        count = max(1, len(self.items))
        span = 360 / count
        for index, (_, label, icon_name) in enumerate(self.items):
            start = 90 - index * span + span / 2  # Qt: 0° = 3 o'clock, counter-clockwise
            if index == self.current:
                path = QPainterPath()
                path.moveTo(center)
                path.arcTo(outer.adjusted(3, 3, -3, -3), start, -span)
                path.closeSubpath()
                highlight = QColor(self.accent)
                highlight.setAlpha(210)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(highlight)
                painter.drawPath(path)
            angle = math.radians(index * span)
            distance = (self.radius + self.inner) / 2 + 2
            x = center.x() + math.sin(angle) * distance
            y = center.y() - math.cos(angle) * distance
            color = QColor("#ffffff") if index == self.current else self.colors["text"]
            if icon_name:
                icon(icon_name, color=color.name(), size=22).paint(painter, int(x - 11), int(y - 22), 22, 22)
            font = QFont(self.font())
            font.setPixelSize(12)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.setPen(color)
            text_rect = QRectF(x - 44, y + 2, 88, 32)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, label)
            if index < 9:  # digit shortcut, small, above the icon
                small = QFont(font)
                small.setPixelSize(10)
                painter.setFont(small)
                painter.setPen(QColor("#ffffff") if index == self.current else self.colors["muted"])
                painter.drawText(QRectF(x - 20, y - 36, 40, 13), Qt.AlignmentFlag.AlignCenter, str(index + 1))
        # separators
        painter.setPen(QPen(self.colors["line"], 1))
        for index in range(count):
            angle = math.radians(index * span + span / 2)
            painter.drawLine(QPointF(center.x() + math.sin(angle) * self.inner, center.y() - math.cos(angle) * self.inner),
                             QPointF(center.x() + math.sin(angle) * self.radius, center.y() - math.cos(angle) * self.radius))
        # centre
        painter.setBrush(self.colors["ring"])
        painter.drawEllipse(center, self.inner, self.inner)
        painter.setPen(self.colors["muted"])
        font = QFont(self.font())
        font.setPixelSize(11)
        painter.setFont(font)
        painter.drawText(QRectF(center.x() - self.inner + 6, center.y() - self.inner + 6, (self.inner - 6) * 2,
                                (self.inner - 6) * 2), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.title)

    # interaction
    def mouseMoveEvent(self, event):
        index = self._sector_at(event.position())
        if index != self.current:
            self.current = index
            self.update()

    def mouseReleaseEvent(self, event):
        index = self._sector_at(event.position())
        if index >= 0:
            self._pick(index)
        else:
            self._cancel()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._cancel()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.current = (self.current + 1) % len(self.items)
            self.update()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.current = (self.current - 1) % len(self.items) if self.current >= 0 else len(self.items) - 1
            self.update()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space) and self.current >= 0:
            self._pick(self.current)
        elif Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
            index = key - Qt.Key.Key_1
            if index < len(self.items):
                self._pick(index)
        else:
            super().keyPressEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == event.Type.ActivationChange and not self.isActiveWindow() and self.isVisible():
            self._cancel()

    def _pick(self, index):
        if self._done:
            return
        self._done = True
        identifier = self.items[index][0]
        self.close()
        self.picked.emit(identifier)

    def _cancel(self):
        if self._done:
            return
        self._done = True
        self.close()
        self.cancelled.emit()


class RegionSelector(QWidget):
    """Frozen primary-screen snapshot; drag a rectangle. Emits the cropped pixmap."""
    selected = Signal(object)  # QPixmap
    cancelled = Signal()

    def __init__(self, hint: str = ""):
        super().__init__(None)
        screen = QGuiApplication.primaryScreen()
        self.snapshot = screen.grabWindow(0)
        self.hint = hint
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.origin = None
        self.rect_ = QRect()

    def start(self):
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.snapshot)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))
        if not self.rect_.isNull():
            ratio = self.snapshot.devicePixelRatio() or 1.0
            source = QRectF(self.rect_.x() * ratio, self.rect_.y() * ratio, self.rect_.width() * ratio, self.rect_.height() * ratio)
            painter.drawPixmap(QRectF(self.rect_), self.snapshot, source)
            painter.setPen(QPen(QColor("#3978f6"), 2))
            painter.drawRect(self.rect_)
        if self.hint:
            painter.setPen(QColor("#ffffff"))
            font = QFont(self.font())
            font.setPixelSize(16)
            painter.setFont(font)
            painter.drawText(self.rect().adjusted(0, 30, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.hint)

    def mousePressEvent(self, event):
        self.origin = event.position().toPoint()
        self.rect_ = QRect(self.origin, self.origin)
        self.update()

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            self.rect_ = QRect(self.origin, event.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, event):
        if self.origin is None:
            return
        rect = self.rect_
        self.close()
        if rect.width() < 4 or rect.height() < 4:
            self.cancelled.emit()
            return
        ratio = self.snapshot.devicePixelRatio() or 1.0
        physical = QRect(int(rect.x() * ratio), int(rect.y() * ratio), int(rect.width() * ratio), int(rect.height() * ratio))
        self.selected.emit(self.snapshot.copy(physical))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            self.cancelled.emit()


class CropDialog(QDialog):
    """Drag a rectangle over the picture; returns a box in image pixels."""

    def __init__(self, image_path, title, ok_label, cancel_label, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setProperty("i18n_skip", True)
        self.pixmap = QPixmap(str(image_path))
        self.box = None
        layout = QVBoxLayout(self)
        self.canvas = _CropCanvas(self.pixmap)
        layout.addWidget(self.canvas, 1)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton(cancel_label)
        cancel.clicked.connect(self.reject)
        ok = QPushButton(ok_label)
        ok.setObjectName("Primary")
        ok.clicked.connect(self._accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        layout.addLayout(row)
        self.resize(900, 650)

    def _accept(self):
        self.box = self.canvas.image_box()
        if self.box is not None:
            self.accept()


class _CropCanvas(QLabel):
    def __init__(self, pixmap):
        super().__init__()
        self.source = pixmap
        self.setMinimumSize(300, 200)
        self.origin = None
        self.rect_ = QRect()
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _target(self):
        if self.source.isNull():
            return QRectF()
        scale = min(self.width() / self.source.width(), self.height() / self.source.height())
        width, height = self.source.width() * scale, self.source.height() * scale
        return QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)

    def paintEvent(self, event):
        painter = QPainter(self)
        target = self._target()
        painter.drawPixmap(target, self.source, QRectF(self.source.rect()))
        if not self.rect_.isNull():
            painter.fillRect(target, QColor(0, 0, 0, 90))
            scale = target.width() / max(1, self.source.width())
            box = QRectF(self.rect_).intersected(target)
            source = QRectF((box.x() - target.x()) / scale, (box.y() - target.y()) / scale, box.width() / scale, box.height() / scale)
            painter.drawPixmap(box, self.source, source)
            painter.setPen(QPen(QColor("#3978f6"), 2))
            painter.drawRect(box)

    def mousePressEvent(self, event):
        self.origin = event.position().toPoint()
        self.rect_ = QRect(self.origin, self.origin)

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            self.rect_ = QRect(self.origin, event.position().toPoint()).normalized()
            self.update()

    def image_box(self):
        target = self._target()
        box = QRectF(self.rect_).intersected(target)
        if box.width() < 3 or box.height() < 3:
            return None
        scale = target.width() / max(1, self.source.width())
        return ((box.left() - target.x()) / scale, (box.top() - target.y()) / scale,
                (box.right() - target.x()) / scale, (box.bottom() - target.y()) / scale)
