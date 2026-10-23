"""Luxify-inspired Jarvis home page.

Pure presentation module: the main window owns the microphone and action
handlers. The fields on HomePage deliberately mirror the older UI controls.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QTextEdit,
    QVBoxLayout, QWidget,
)


class ToggleSwitch(QCheckBox):
    """Compact painted toggle with a movable round knob."""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setText("")
        self.setChecked(bool(checked))
        self.setFixedSize(54, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(3, 5, -3, -5)
        active = self.isChecked()
        color = QColor("#4388f9") if active else QColor("#25272c")
        painter.setPen(QPen(QColor("#4388f9") if active else QColor("#505258"), 1))
        painter.setBrush(color)
        painter.drawRoundedRect(rect, 10, 10)
        knob_x = rect.right() - 17 if active else rect.left() + 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffffff") if active else QColor("#a1a5ac"))
        painter.drawEllipse(int(knob_x), int(rect.top() + 2), 14, 14)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#85aeff"), 1))
            painter.drawRoundedRect(self.rect().adjusted(1, 2, -1, -2), 12, 12)


class OrbVisual(QWidget):
    """Large clipped concentric circles, with optional very subtle motion."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HeroOrb")
        self.setMinimumWidth(155)
        self._phase = 0.0
        self._animated = False
        self._theme = "dark"
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._advance)

    def set_animated(self, enabled):
        self._animated = bool(enabled)
        if self._animated and self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def set_theme(self, theme):
        self._theme = theme
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self._animated:
            self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _advance(self):
        self._phase += 0.045
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(self.rect())
        # Center sits outside the right edge, just like the Luxify reference.
        w, h = float(self.width()), float(self.height())
        x, y = w * 1.13, h * 0.50
        radius = max(h * 0.76, w * 0.93)
        pulse = math.sin(self._phase) * 4.0 if self._animated else 0.0
        colors = (
            ("#1b2b48", 1.00),
            ("#244474", 0.86),
            ("#2d58a0", 0.70),
            ("#3572d5", 0.54),
            ("#4286f3", 0.39),
            ("#4b90ff", 0.24),
        )
        if self._theme == "light":
            colors = (
                ("#d7e4fb", 1.00),
                ("#b7cef6", 0.86),
                ("#91b6f2", 0.70),
                ("#6397e9", 0.54),
                ("#4785e9", 0.39),
                ("#3479e6", 0.24),
            )
        painter.setPen(Qt.PenStyle.NoPen)
        for color, ratio in colors:
            r = radius * ratio + pulse * ratio
            painter.setBrush(QColor(color))
            painter.drawEllipse(int(x-r), int(y-r), int(2*r), int(2*r))


def _card(title):
    frame = QFrame()
    frame.setObjectName("HomeCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(12)
    title_label = QLabel(title)
    title_label.setObjectName("HomeCardTitle")
    layout.addWidget(title_label)
    return frame, layout


class HomePage(QWidget):
    """Home cards plus ring visual; all controls remain bindable by main.py."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setObjectName("HomePage")
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(26)

        column = QWidget()
        column.setObjectName("HomeLeft")
        column.setMinimumWidth(350)
        column.setMaximumWidth(490)
        left = QVBoxLayout(column)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(18)

        history_card, history_layout = _card("История команд")
        self.home_history = QTextEdit()
        self.home_history.setObjectName("HomeHistory")
        self.home_history.setReadOnly(True)
        self.home_history.setPlaceholderText("Здесь появятся распознанные команды и ответы Jarvis.")
        history_layout.addWidget(self.home_history, 1)
        left.addWidget(history_card, 3)

        control_card, control_layout = _card("Панель управления")
        self.home_prefix = self._switch_row(
            control_layout, "Режим префикса", config.get("prefix_enabled", False)
        )
        self.home_quiet = self._switch_row(
            control_layout, "Тихий режим", not config.get("tts_enabled", True)
        )
        self.home_avatar = self._switch_row(
            control_layout, "Анимация аватара", config.get("ui_animations", True)
        )
        self.home_top = self._switch_row(
            control_layout, "Окно поверх", config.get("always_on_top", False)
        )

        volume = QHBoxLayout()
        volume.setContentsMargins(0, 4, 0, 0)
        volume.setSpacing(12)
        volume_name = QLabel("Громкость")
        volume_name.setObjectName("HomeRowLabel")
        volume.addWidget(volume_name)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setObjectName("HomeVolume")
        self.volume.setRange(0, 100)
        self.volume.setValue(int(config.get("voice_volume", 80)))
        volume.addWidget(self.volume, 1)
        self.volume_label = QLabel(f"{self.volume.value()}%")
        self.volume_label.setObjectName("HomeVolumeValue")
        self.volume_label.setFixedWidth(44)
        self.volume_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        volume.addWidget(self.volume_label)
        control_layout.addLayout(volume)
        self.screen_assist_button = QPushButton("▣  Посмотреть кнопки на экране")
        self.screen_assist_button.setObjectName("ScreenAssistButton")
        self.screen_assist_button.setToolTip(
            "Показать локальный снимок и кнопки Да/Нет активной программы. "
            "Можно также сказать: «Жарвис, покажи кнопки на экране»."
        )
        self.screen_assist_button.setMinimumHeight(36)
        control_layout.addWidget(self.screen_assist_button)
        self.selection_summary_button = QPushButton("▤  Пересказать выделенный текст")
        self.selection_summary_button.setObjectName("SelectedTextSummaryButton")
        self.selection_summary_button.setToolTip(
            "Выделите текст в браузере или Word. Затем нажмите здесь "
            "или скажите: «Жарвис, перескажи выделенное». "
            "Jarvis копирует выделенный текст, возвращает прежний буфер "
            "обмена и делает краткий пересказ на русском."
        )
        self.selection_summary_button.setMinimumHeight(36)
        control_layout.addWidget(self.selection_summary_button)
        control_layout.addStretch(1)
        left.addWidget(control_card, 2)

        root.addWidget(column, 5)
        self.avatar = OrbVisual()
        root.addWidget(self.avatar, 5)

    @staticmethod
    def _switch_row(layout, title, checked):
        row = QHBoxLayout()
        row.setSpacing(12)
        name = QLabel(title)
        name.setObjectName("HomeRowLabel")
        row.addWidget(name, 1)
        switch = ToggleSwitch(checked)
        switch.setAccessibleName(title)
        row.addWidget(switch, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(row)
        return switch
