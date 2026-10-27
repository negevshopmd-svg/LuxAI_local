"""Luxify-inspired Jarvis home page.

Pure presentation module: the main window owns the microphone and action
handlers. The fields on HomePage deliberately mirror the older UI controls.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea, QSlider, QTextEdit,
    QSizePolicy, QVBoxLayout, QWidget,
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

    def set_theme(self, theme, accent="#3978f6", background=None):
        self._colors = theme_colors(theme, accent, background)
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
    """Theme-colored rings with smooth, UI-thread audio activity feedback."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HeroOrb")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAutoFillBackground(False)
        self.setMinimumWidth(155)
        self._phase = 0.0
        self._animated = False
        self._listening = False
        self._speaking = False
        self._playback_probe = None
        self._audio_level = 0.0
        self._level = 0.0
        self._listen_mix = 0.0
        self._speak_mix = 0.0
        self._last_frame = None
        self._theme = "dark"
        self._accent = "#3978f6"
        self._background = None
        self._ring_colors = ()
        self.set_theme(self._theme, self._accent)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._advance)

    def _sync_timer(self):
        running = self._animated and self.isVisible()
        if running and not self._timer.isActive():
            self._refresh_playback()
            # Do not replay an activity fade that finished while hidden.
            if not self._speaking:
                self._speak_mix = 0.0
            if not self._listening:
                self._listen_mix = 0.0
            if not self._listening or self._speaking:
                self._level = 0.0
            self._last_frame = time.monotonic()
            self._timer.start()
        elif not running:
            self._timer.stop()
            self._last_frame = None

    def set_animated(self, enabled):
        self._animated = bool(enabled)
        self._sync_timer()
        self.update()

    def set_listening(self, enabled):
        """Set actual capture state, independently of the animation preference."""
        self._listening = bool(enabled)
        if not self._listening:
            self._audio_level = 0.0
        self.update()

    def set_audio_level(self, level):
        """Accept a normalized microphone level; discard invalid device values."""
        try:
            level = float(level)
        except (TypeError, ValueError, OverflowError):
            level = 0.0
        self._audio_level = max(0.0, min(1.0, level)) if math.isfinite(level) else 0.0

    def set_playback_probe(self, probe):
        """Read a thread-safe playback flag on the existing animation tick."""
        self._playback_probe = probe if callable(probe) else None
        if self._animated and self.isVisible():
            self._refresh_playback()

    def _refresh_playback(self):
        if self._playback_probe is not None:
            try:
                self._speaking = bool(self._playback_probe())
            except Exception:
                self._speaking = False

    def set_speaking(self, enabled):
        """Set actual output playback state, rather than synthesis/queue state."""
        self._speaking = bool(enabled)
        self.update()

    def set_theme(self, theme, accent="#3978f6", background=None):
        self._theme = "light" if theme == "light" else "dark"
        palette = theme_colors(theme, accent, background)
        self._accent = palette["accent"]
        self._background = palette["bg"]
        amounts = ((0.12, 0.25, 0.40, 0.60, 0.80, 0.95)
                   if self._theme == "light" else (0.23, 0.38, 0.57, 0.76, 0.92, 1.0))
        self._ring_colors = tuple(QColor(mix_colors(self._background, self._accent, amount))
                                  for amount in amounts)
        if self._theme != "light":
            self._ring_colors = self._ring_colors[:-1] + (
                QColor(mix_colors(self._accent, "#ffffff", 0.10)),)
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event):
        self._timer.stop()
        self._last_frame = None
        super().hideEvent(event)

    @staticmethod
    def _approach(value, target, elapsed, attack=0.10, release=0.28):
        # Exponential smoothing depends on elapsed time, not timer frequency.
        duration = attack if target > value else release
        return value + (target - value) * -math.expm1(-elapsed / duration)

    def _advance(self):
        if not self._animated or not self.isVisible():
            return
        self._refresh_playback()
        now = time.monotonic()
        elapsed = min(0.10, max(0.0, now - self._last_frame)) if self._last_frame is not None else 0.0
        self._last_frame = now
        self._phase = (self._phase + elapsed) % (math.tau * 20)
        self._listen_mix = self._approach(self._listen_mix, float(self._listening), elapsed)
        self._speak_mix = self._approach(self._speak_mix, float(self._speaking), elapsed)
        # The output animation takes precedence while the assistant speaks;
        # its own sound in the microphone must not amplify the listening ring.
        target = self._audio_level if self._listening and not self._speaking else 0.0
        self._level = self._approach(self._level, target, elapsed, attack=0.045, release=0.22)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(self.rect())
        # Keep the original full-height, transparent backdrop composition.
        w, h = float(self.width()), float(self.height())
        radius = max(h * 0.76, w * 0.93)
        x, y = max(w * 1.13, radius + 8.0), h * 0.50
        ratios = (1.00, 0.86, 0.70, 0.54, 0.39, 0.24)
        phase = self._phase
        speaking = self._speak_mix if self._animated else 0.0
        listening = self._listen_mix if self._animated else 0.0
        level = self._level if self._animated else 0.0
        if self._animated:
            y += math.sin(phase * 0.65) * (1.5 + listening + speaking * 1.5)
        painter.setPen(Qt.PenStyle.NoPen)
        for index, (color, ratio) in enumerate(zip(self._ring_colors, ratios)):
            pulse = 0.0
            dx = 0.0
            if self._animated:
                # Adjacent layers breathe out of phase. Microphone intensity
                # expands the inner rings; playback adds a distinct rolling wave.
                inner = 1.0 - ratio
                pulse = math.sin(phase * 0.9 - index * 0.42) * (2.2 + inner * 3.0)
                pulse += listening * (1.0 + level * 17.0) * inner
                pulse += speaking * math.sin(phase * 7.5 - index * 0.8) * (2.0 + inner * 9.0)
                dx = math.sin(phase * 0.55 + index * 0.36) * inner * (2.0 + speaking * 3.0)
            r = radius * ratio + pulse
            painter.setBrush(color)
            # Subpixel geometry avoids the one-pixel stepping of integer ellipses.
            painter.drawEllipse(QRectF(x + dx - r, y - r, 2.0 * r, 2.0 * r))


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
        controls_scroll.setObjectName("HomeScroll")
        controls_scroll.viewport().setObjectName("HomeViewport")
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setFrameShape(QFrame.Shape.NoFrame)
        controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        controls_scroll.setWidget(column)
        self.controls_scroll = controls_scroll
        root.addWidget(controls_scroll, 5)
        self.avatar = OrbVisual()
        self.hero_space = self.avatar
        root.addWidget(self.avatar, 5)
        self.set_theme(config.get("ui_theme", "dark"), config.get("ui_accent", "#3978f6"), config.get("ui_background"))

    def detach_avatar(self, parent):
        """Keep the home column width while giving its orb a full-height host.

        The main window positions this decorative backdrop behind its header
        and page, rather than clipping it to the rectangle below the header.
        The original avatar object, animation state and signal bindings stay
        intact; the caller controls its geometry and home-page visibility.
        """
        layout = self.layout()
        index = layout.indexOf(self.avatar)
        if index >= 0:
            layout.removeWidget(self.avatar)
            self.hero_space = QWidget(self)
            self.hero_space.setObjectName("HeroSpace")
            self.hero_space.setMinimumWidth(155)
            self.hero_space.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.hero_space.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.insertWidget(index, self.hero_space, 5)
        if self.avatar.parentWidget() is not parent:
            self.avatar.setParent(parent)
        return self.avatar

    def set_theme(self, theme, accent="#3978f6", background=None):
        """Apply the same selected accent to custom-painted home controls."""
        self.avatar.set_theme(theme, accent, background)
        for switch in (self.home_prefix, self.home_quiet, self.home_avatar, self.home_top):
            switch.set_theme(theme, accent, background)

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
