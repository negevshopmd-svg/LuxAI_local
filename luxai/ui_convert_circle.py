"""Converter UI: radial action menu at the cursor, screen-region picker, crop.

The radial menu is chosen with the mouse, arrow keys + Enter, or digits 1–9;
Esc / click in the centre / click outside closes it.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPainterPath, QPen,
                           QPixmap, QRadialGradient)
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from luxai.icons import icon


THEMES = {
    "dark": {"disc": QColor(24, 27, 34, 246), "disc_edge": QColor(17, 19, 24, 246), "hub": QColor(34, 38, 48, 255),
             "chip": QColor(255, 255, 255, 16), "chip_edge": QColor(255, 255, 255, 22), "text": QColor("#f2f4f8"),
             "muted": QColor("#8f97a6"), "line": QColor(255, 255, 255, 26), "shadow": QColor(0, 0, 0, 70)},
    "light": {"disc": QColor(252, 252, 254, 248), "disc_edge": QColor(238, 241, 246, 248), "hub": QColor(255, 255, 255, 255),
              "chip": QColor(20, 30, 50, 12), "chip_edge": QColor(20, 30, 50, 18), "text": QColor("#18212f"),
              "muted": QColor("#6b7586"), "line": QColor(20, 30, 50, 24), "shadow": QColor(20, 30, 50, 40)},
}
OPEN_SECONDS = 0.2
HINT = "1–9 · Enter · Esc"


def label_lines(label: str, metrics, width: float, most: int = 2) -> list[str]:
    """A label in at most two lines that fit ``width``; only the last line is cut with «…»."""
    words = str(label or "").split()
    lines: list[str] = []
    while words and len(lines) < most:
        line = words.pop(0)
        while words and metrics.horizontalAdvance(line + " " + words[0]) <= width:
            line += " " + words.pop(0)
        lines.append(line)
    if words:
        lines[-1] = lines[-1] + " " + " ".join(words)
    return [metrics.elidedText(line, Qt.TextElideMode.ElideRight, width) for line in lines]


def _ease_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


class RadialMenu(QWidget):
    """items: [(id, label, icon_name)]. Emits picked(id) or cancelled().

    0.4.4a: drawn as a ring of round buttons around a hub. The hub shows the pointed item's full name; every
    button has its group's colour (``tint(id)``), grows and glows when pointed at, and the menu opens with a
    short zoom. The geometry the tests and the keyboard rely on (sectors clockwise from the top) is unchanged.
    """
    picked = Signal(str)
    cancelled = Signal()

    def __init__(self, items, title="", *, theme="dark", accent="#3978f6", parent=None, tint=None, hint=HINT):
        super().__init__(parent)
        self.items = list(items)[:12]
        self.title = title
        self.hint = hint
        self.colors = THEMES.get(theme, THEMES["dark"])
        self.dark = theme != "light"
        self.accent = QColor(accent)
        self.tint = tint
        self.current = -1
        self._done = False
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.radius = 176 if len(self.items) > 8 else 158
        self.inner = 64
        self.margin = 26  # room for the shadow
        size = self.radius * 2 + self.margin * 2
        self.resize(size, size)
        self._opened = time.monotonic()
        self._hover = [0.0] * len(self.items)  # 0..1, follows the pointer smoothly
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._animate)
        self._timer.start()

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

    def _item_center(self, index: int) -> QPointF:
        center = self._center()
        angle = math.radians(index * 360 / max(1, len(self.items)))
        distance = (self.radius + self.inner) / 2 + 4
        return QPointF(center.x() + math.sin(angle) * distance, center.y() - math.cos(angle) * distance)

    def _color(self, index: int) -> QColor:
        identifier = self.items[index][0]
        value = None
        if self.tint is not None:
            try:
                value = self.tint(identifier)
            except Exception:
                value = None
        color = QColor(value) if value else QColor(self.accent)
        return color if color.isValid() else QColor(self.accent)

    def show_at(self, point=None):
        point = point or QCursor.pos()
        screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(area.left(), point.x() - self.width() // 2), area.right() - self.width())
        y = min(max(area.top(), point.y() - self.height() // 2), area.bottom() - self.height())
        self.move(x, y)
        self._opened = time.monotonic()
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    # animation
    def _animate(self):
        moving = time.monotonic() - self._opened < OPEN_SECONDS + 0.05
        for index in range(len(self._hover)):
            target = 1.0 if index == self.current else 0.0
            value = self._hover[index]
            if abs(target - value) > 0.01:
                self._hover[index] = value + (target - value) * 0.32
                moving = True
            else:
                self._hover[index] = target
        if moving:
            self.update()

    # painting
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        opening = _ease_out((time.monotonic() - self._opened) / OPEN_SECONDS)
        center = self._center()
        painter.translate(center)
        painter.scale(0.9 + 0.1 * opening, 0.9 + 0.1 * opening)
        painter.translate(-center)
        painter.setOpacity(opening)
        self._paint_disc(painter, center)
        for index in range(len(self.items)):
            self._paint_item(painter, index)
        self._paint_hub(painter, center)

    def _paint_disc(self, painter: QPainter, center: QPointF):
        colors = self.colors
        for step in range(5, 0, -1):  # a soft shadow under the disc
            shade = QColor(colors["shadow"])
            shade.setAlpha(int(colors["shadow"].alpha() * (6 - step) / 14))
            grow = step * 4
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(shade)
            painter.drawEllipse(QPointF(center.x(), center.y() + 6), self.radius + grow, self.radius + grow)
        gradient = QRadialGradient(center, self.radius)
        gradient.setColorAt(0.0, colors["disc"])
        gradient.setColorAt(1.0, colors["disc_edge"])
        painter.setBrush(gradient)
        painter.setPen(QPen(colors["line"], 1))
        painter.drawEllipse(center, self.radius, self.radius)
        if 0 <= self.current < len(self.items):  # a soft beam from the hub to the pointed button
            span = 360 / len(self.items)
            outer = QRectF(center.x() - self.radius + 2, center.y() - self.radius + 2, (self.radius - 2) * 2,
                           (self.radius - 2) * 2)
            start = 90 - self.current * span + span / 2
            path = QPainterPath()
            path.moveTo(center)
            path.arcTo(outer, start, -span)
            path.closeSubpath()
            beam = QRadialGradient(center, self.radius)
            color = self._color(self.current)
            soft = QColor(color)
            soft.setAlpha(0)
            strong = QColor(color)
            strong.setAlpha(46 if self.dark else 34)
            beam.setColorAt(0.3, soft)
            beam.setColorAt(1.0, strong)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(beam)
            painter.drawPath(path)
            pen = QPen(color, 3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(outer.adjusted(2, 2, -2, -2), int((start - span * 0.18) * 16), int(-span * 0.64 * 16))

    def _paint_item(self, painter: QPainter, index: int):
        identifier, label, icon_name = self.items[index][:3]
        point = self._item_center(index)
        hover = self._hover[index] if index < len(self._hover) else 0.0
        color = self._color(index)
        radius = 23 + 4 * hover
        if hover > 0.02:  # glow
            for step in range(3, 0, -1):
                glow = QColor(color)
                glow.setAlpha(int(34 * hover / step))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(glow)
                painter.drawEllipse(point, radius + step * 4, radius + step * 4)
        base = QColor(color)
        base.setAlpha(int(28 + 227 * hover))
        rest = QColor(self.colors["chip"])
        painter.setPen(QPen(self.colors["chip_edge"], 1))
        painter.setBrush(rest)
        painter.drawEllipse(point, radius, radius)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(base)
        painter.drawEllipse(point, radius, radius)
        glyph = QColor("#ffffff") if hover > 0.5 else (color.lighter(135) if self.dark else color.darker(115))
        if icon_name:
            side = 20 + 2 * hover
            try:
                icon(icon_name, color=glyph.name(), size=22).paint(
                    painter, QRectF(point.x() - side / 2, point.y() - side / 2, side, side).toAlignedRect())
            except Exception:
                pass
        if index < 9:  # the digit that picks it, in a tiny badge
            badge = QPointF(point.x() + radius * 0.74, point.y() - radius * 0.74)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.colors["hub"])
            painter.drawEllipse(badge, 8, 8)
            font = QFont(self.font())
            font.setPixelSize(9)
            font.setWeight(QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(color if hover > 0.5 else self.colors["muted"])
            painter.drawText(QRectF(badge.x() - 8, badge.y() - 8, 16, 16), Qt.AlignmentFlag.AlignCenter, str(index + 1))
        font = QFont(self.font())
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.DemiBold if hover > 0.5 else QFont.Weight.Medium)
        painter.setFont(font)
        span = 2 * math.pi * ((self.radius + self.inner) / 2 + 4) / max(1, len(self.items))
        width = max(60.0, min(100.0, span + 4))
        lines = label_lines(label, QFontMetricsF(font), width)
        painter.setPen(self.colors["text"] if hover > 0.5 else self.colors["muted"])
        painter.drawText(QRectF(point.x() - width / 2, point.y() + radius + 2, width, 30),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "\n".join(lines))

    def _paint_hub(self, painter: QPainter, center: QPointF):
        colors = self.colors
        painter.setPen(QPen(colors["line"], 1))
        painter.setBrush(colors["hub"])
        painter.drawEllipse(center, self.inner - 4, self.inner - 4)
        box = QRectF(center.x() - self.inner + 12, center.y() - self.inner + 14, (self.inner - 12) * 2,
                     (self.inner - 14) * 2)
        pointed = 0 <= self.current < len(self.items)
        name = self.items[self.current][1] if pointed else self.title
        font = QFont(self.font())
        font.setPixelSize(13 if pointed else 12)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(self._color(self.current) if pointed and not self.dark else colors["text"])
        painter.drawText(box.adjusted(0, 0, 0, -16),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom | Qt.TextFlag.TextWordWrap, name)
        small = QFont(self.font())
        small.setPixelSize(9)
        painter.setFont(small)
        painter.setPen(colors["muted"])
        hint = f"{self.current + 1} · Enter" if pointed and self.current < 9 else ("Enter" if pointed else self.hint)
        painter.drawText(QRectF(box.left(), box.bottom() - 13, box.width(), 13), Qt.AlignmentFlag.AlignCenter, hint)

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
        elif not self.items:
            super().keyPressEvent(event)  # nothing to choose: arrows used to divide by zero
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


def _drag_rect(origin, point) -> QRect:
    """The rectangle a drag covers: 10→110 is 100 px (QRect(p1, p2) would give 101)."""
    return QRect(min(origin.x(), point.x()), min(origin.y(), point.y()),
                 abs(point.x() - origin.x()), abs(point.y() - origin.y()))


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
        self.rect_ = QRect(self.origin, QSize(0, 0))
        self.update()

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            self.rect_ = _drag_rect(self.origin, event.position().toPoint())
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
        self.rect_ = QRect(self.origin, QSize(0, 0))

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            self.rect_ = _drag_rect(self.origin, event.position().toPoint())
            self.update()

    def image_box(self):
        target = self._target()
        box = QRectF(self.rect_).intersected(target)
        if box.width() < 3 or box.height() < 3:
            return None
        scale = target.width() / max(1, self.source.width())
        return ((box.left() - target.x()) / scale, (box.top() - target.y()) / scale,
                (box.right() - target.x()) / scale, (box.bottom() - target.y()) / scale)
