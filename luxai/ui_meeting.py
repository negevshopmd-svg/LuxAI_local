"""The «● REC 12:34  ❚❚  ■» pill shown while call notes are recorded (0.4.4b).

Always on top, never takes the focus, can be dragged; the red dot breathes with the sound level. Painted
(no child widgets), so it looks the same on every theme.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

WIDTH, HEIGHT = 214, 44


class MeetingPill(QWidget):
    pause_clicked = Signal()
    stop_clicked = Signal()

    def __init__(self, language: str = "ru"):
        super().__init__(None)
        self.setObjectName("MeetingPill")
        self.setProperty("i18n_skip", True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setFixedSize(WIDTH + 16, HEIGHT + 16)
        self.setMouseTracking(True)
        self.language = language
        self.elapsed = "00:00:00"
        self.paused = False
        self.level = 0.0
        self._hover = ""
        self._drag = None
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self.update)
        self._timer.start()
        labels = {"ru": ("Пауза", "Продолжить", "Остановить и сделать конспект"),
                  "en": ("Pause", "Resume", "Stop and write the notes"),
                  "ro": ("Pauză", "Continuă", "Oprește și fă rezumatul")}
        self.labels = labels.get(language, labels["ru"])

    def show_in_corner(self):
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.right() - self.width() - 16, area.top() + 16)
        self.show()

    def set_state(self, elapsed: str, paused: bool, level: float = 0.0):
        self.elapsed, self.paused, self.level = elapsed, paused, level
        self._update_tooltip()

    # geometry
    def _pill(self) -> QRectF:
        return QRectF(8, 8, WIDTH, HEIGHT)

    def _buttons(self) -> dict:
        pill = self._pill()
        side = HEIGHT - 12
        stop = QRectF(pill.right() - 6 - side, pill.top() + 6, side, side)
        pause = QRectF(stop.left() - 6 - side, stop.top(), side, side)
        return {"pause": pause, "stop": stop}

    def _update_tooltip(self):
        tip = {"pause": self.labels[1] if self.paused else self.labels[0], "stop": self.labels[2]}.get(self._hover, "")
        if self.toolTip() != tip:
            self.setToolTip(tip)

    # painting
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pill = self._pill()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 60))
        painter.drawRoundedRect(pill.adjusted(-2, 0, 2, 4), HEIGHT / 2 + 2, HEIGHT / 2 + 2)
        painter.setPen(QPen(QColor(255, 255, 255, 26), 1))
        painter.setBrush(QColor(14, 16, 21, 240))
        painter.drawRoundedRect(pill, HEIGHT / 2, HEIGHT / 2)
        center = QPointF(pill.left() + 22, pill.center().y())
        if self.paused:
            color = QColor("#ffd60a")
            radius = 5.0
        else:
            color = QColor("#ff453a")
            breath = 0.5 + 0.5 * math.sin(time.monotonic() * 3.2)
            radius = 5.0 + 1.2 * breath + 3.0 * min(1.0, self.level * 8)
            glow = QColor(color)
            glow.setAlpha(60)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(center, radius + 4, radius + 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(center, radius, radius)
        font = QFont(self.font())
        font.setPixelSize(10)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(QRectF(pill.left() + 36, pill.top() + 5, 60, 14), Qt.AlignmentFlag.AlignLeft, "REC")
        font.setPixelSize(15)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255, 235))
        painter.drawText(QRectF(pill.left() + 36, pill.top() + 15, 90, 24),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.elapsed)
        for name, rect in self._buttons().items():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 46 if self._hover == name else 20))
            painter.drawEllipse(rect)
            inner = rect.adjusted(rect.width() * 0.34, rect.height() * 0.34, -rect.width() * 0.34, -rect.height() * 0.34)
            painter.setBrush(QColor(255, 255, 255, 235))
            if name == "stop":
                painter.setBrush(QColor("#ff453a"))
                painter.drawRoundedRect(inner, 2, 2)
            elif self.paused:  # resume: a play triangle
                path = QPainterPath()
                path.moveTo(inner.left() + 1, inner.top())
                path.lineTo(inner.right() + 1, inner.center().y())
                path.lineTo(inner.left() + 1, inner.bottom())
                path.closeSubpath()
                painter.drawPath(path)
            else:
                bar = inner.width() * 0.32
                painter.drawRoundedRect(QRectF(inner.left(), inner.top(), bar, inner.height()), 1, 1)
                painter.drawRoundedRect(QRectF(inner.right() - bar, inner.top(), bar, inner.height()), 1, 1)

    # mouse
    def mouseMoveEvent(self, event):
        point = event.position()
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move((event.globalPosition() - self._drag).toPoint())
            return
        hover = next((name for name, rect in self._buttons().items() if rect.contains(point)), "")
        if hover != self._hover:
            self._hover = hover
            self.setCursor(Qt.CursorShape.PointingHandCursor if hover else Qt.CursorShape.SizeAllCursor)
            self._update_tooltip()
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._hover:
            self._drag = event.globalPosition() - QPointF(self.pos())

    def mouseReleaseEvent(self, event):
        was_dragging = self._drag is not None
        self._drag = None
        if event.button() != Qt.MouseButton.LeftButton or was_dragging:
            return
        for name, rect in self._buttons().items():
            if rect.contains(event.position()):
                (self.pause_clicked if name == "pause" else self.stop_clicked).emit()
                return

    def leaveEvent(self, event):
        self._hover = ""
        self.update()
        super().leaveEvent(event)
