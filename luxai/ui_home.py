"""Luxify-inspired Jarvis home page.

Pure presentation module: the main window owns the microphone and action
handlers. The fields on HomePage deliberately mirror the older UI controls.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea, QSlider, QTextEdit,
    QVBoxLayout, QWidget,
)
from luxai.icons import set_button_icon, set_label_icon
from luxai.styles import theme_colors, mix_colors


class ToggleSwitch(QCheckBox):
    """Compact painted toggle with a movable round knob."""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setText("")
        self.setChecked(bool(checked))
        self.setFixedSize(54, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._colors = theme_colors()

    def set_theme(self, theme, accent="#3978f6"):
        self._colors = theme_colors(theme, accent)
        self.update()

    def hitButton(self, pos):
        """Use the entire PAINTED switch as the click target.

        QCheckBox's default style hit-test can be restricted to its small
        indicator even though this custom control paints a 54px-wide pill.
        This made clicking the right half silently do nothing.
        """
        return self.isEnabled() and self.rect().contains(pos)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(3, 5, -3, -5)
        active = self.isChecked()
        if not self.isEnabled():
            painter.setOpacity(0.45)
        color = QColor(self._colors["accent"] if active else self._colors["control"])
        painter.setPen(QPen(QColor(self._colors["accent"] if active else self._colors["border"]), 1))
        painter.setBrush(color)
        painter.drawRoundedRect(rect, 10, 10)
        knob_x = rect.right() - 17 if active else rect.left() + 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffffff") if active else QColor(self._colors["muted"]))
        painter.drawEllipse(int(knob_x), int(rect.top() + 2), 14, 14)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(self._colors["focus"]), 1))
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
        self._accent = "#3978f6"
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

    def set_theme(self, theme, accent="#3978f6"):
        self._theme = "light" if theme == "light" else "dark"
        self._accent = theme_colors(theme, accent)["accent"]
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
        ratios = (1.00, 0.86, 0.70, 0.54, 0.39, 0.24)
        amounts = (0.23, 0.38, 0.57, 0.76, 0.92)
        background = theme_colors(self._theme, self._accent)["bg"]
        if self._theme == "light":
            amounts = (0.12, 0.25, 0.40, 0.60, 0.80, 0.95)
        colors = [mix_colors(background, self._accent, amount) for amount in amounts]
        if self._theme != "light":
            colors.append(mix_colors(self._accent, "#ffffff", 0.10))
        painter.setPen(Qt.PenStyle.NoPen)
        for color, ratio in zip(colors, ratios):
            r = radius * ratio + pulse * ratio
            painter.setBrush(QColor(color))
            painter.drawEllipse(int(x-r), int(y-r), int(2*r), int(2*r))


def _card(title, icon_name):
    frame = QFrame()
    frame.setObjectName("HomeCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(12)
    heading = QHBoxLayout()
    heading.setSpacing(10)
    mark = QLabel()
    mark.setProperty("jarvisIconBoxSize", 23)
    set_label_icon(mark, icon_name, size=21, role="accent")
    mark.setFixedSize(23, 23)
    heading.addWidget(mark)
    title_label = QLabel(title)
    title_label.setObjectName("HomeCardTitle")
    heading.addWidget(title_label, 1)
    layout.addLayout(heading)
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

        history_card, history_layout = _card("История команд", "history")
        self.home_history = QTextEdit()
        self.home_history.setObjectName("HomeHistory")
        self.home_history.setReadOnly(True)
        self.home_history.setPlaceholderText("Здесь появятся распознанные команды и ответы Jarvis.")
        history_layout.addWidget(self.home_history, 1)
        self.history_activity = QLabel()
        self.history_activity.setObjectName("TaskActivity")
        self.history_activity.setTextFormat(Qt.TextFormat.PlainText)
        self.history_activity.setWordWrap(True)
        self.history_activity.setAccessibleName("Activity")
        self.history_activity.hide()
        history_layout.addWidget(self.history_activity)
        left.addWidget(history_card, 3)

        control_card, control_layout = _card("Панель управления", "sliders-horizontal")
        self.home_prefix = self._switch_row(
            control_layout, "Режим префикса", config.get("prefix_enabled", False), "audio-lines"
        )
        self.home_quiet = self._switch_row(
            control_layout, "Тихий режим", not config.get("tts_enabled", True), "volume-x"
        )
        self.home_avatar = self._switch_row(
            control_layout, "Анимация аватара", config.get("ui_animations", True), "sparkles"
        )
        self.home_top = self._switch_row(
            control_layout, "Окно поверх", config.get("always_on_top", False), "pin"
        )

        volume = QHBoxLayout()
        volume.setContentsMargins(0, 4, 0, 0)
        volume.setSpacing(12)
        volume_mark = QLabel()
        set_label_icon(volume_mark, "volume-2", size=18, role="muted")
        volume.addWidget(volume_mark)
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
        self.microphone_state = QLabel("Микрофон выключен")
        self.microphone_state.setWordWrap(True)
        control_layout.addWidget(self.microphone_state)
        self.microphone_level = QProgressBar()
        self.microphone_level.setRange(0, 100)
        self.microphone_level.setValue(0)
        self.microphone_level.setFormat("%p%")
        self.microphone_level.setAccessibleName("Уровень микрофона")
        control_layout.addWidget(self.microphone_level)
        control_layout.addStretch(1)
        left.addWidget(control_card, 2)

        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setFrameShape(QFrame.Shape.NoFrame)
        controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        controls_scroll.setWidget(column)
        root.addWidget(controls_scroll, 5)
        self.avatar = OrbVisual()
        root.addWidget(self.avatar, 5)
        self.set_theme(config.get("ui_theme", "dark"), config.get("ui_accent", "#3978f6"))

    def set_theme(self, theme, accent="#3978f6"):
        """Apply the same selected accent to custom-painted home controls."""
        self.avatar.set_theme(theme, accent)
        for switch in (self.home_prefix, self.home_quiet, self.home_avatar, self.home_top):
            switch.set_theme(theme, accent)

    @staticmethod
    def _switch_row(layout, title, checked, icon_name):
        row = QHBoxLayout()
        row.setSpacing(12)
        mark = QLabel()
        set_label_icon(mark, icon_name, size=18, role="muted")
        row.addWidget(mark)
        name = QLabel(title)
        name.setObjectName("HomeRowLabel")
        row.addWidget(name, 1)
        switch = ToggleSwitch(checked)
        switch.setAccessibleName(title)
        row.addWidget(switch, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(row)
        return switch
