"""Visual avatar: a living orb on top of the screen.

It "breathes" by itself, reacts to sound (Jarvis's voice, all PC sound, the
microphone or chosen programs) and changes colour with Jarvis's state:
running a command, speaking, an error, microphone off, quiet mode, prefix
mode. Sound is only measured (loudness), never recorded or sent.
"""
from __future__ import annotations

import math
import os
import threading
import time

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QRadialGradient
from PySide6.QtWidgets import QWidget

BASE_SIZE = 170
DEFAULT_COLOR = "#1f8fe0"
STATES = ("exec", "speak", "error", "mic_off", "quiet", "prefix")
DEFAULT_STATE_COLORS = {"exec": "#2ecf8f", "speak": "#f5b942", "error": "#ef5350",
                        "mic_off": "#7c8696", "quiet": "#8f98a8", "prefix": "#40d3b5"}
# Highest first. Temporary events beat the permanent modes.
PRIORITY = ("error", "exec", "speak", "mic_off", "quiet", "prefix")
POSITIONS = ("tl", "tc", "tr", "ml", "mc", "mr", "bl", "bc", "br")
ERROR_SECONDS = 2.5


def resolve_state(flags: dict, settings: dict, base_color: str) -> tuple[str, str]:
    """(state, colour). ``flags`` holds booleans for STATES plus ``listening``."""
    if settings.get("state_colors", True):
        for state in PRIORITY:
            if flags.get(state) and settings.get(f"s_{state}", True):
                return state, settings.get(f"c_{state}") or DEFAULT_STATE_COLORS[state]
    for state in ("exec", "speak", "error"):
        if flags.get(state):
            return state, base_color
    return ("listening" if flags.get("listening") else "idle"), base_color


def loudness(rms: float, sensitivity: float) -> float:
    """0..1 from RMS. Higher sensitivity notices quieter sound."""
    if rms <= 0:
        return 0.0
    db = 20 * math.log10(max(rms, 1e-9))
    floor = -30.0 - 40.0 * max(0.0, min(1.0, sensitivity))
    return max(0.0, min(1.0, (db - floor) / 35.0))


ORB_RATIO = 0.29     # visible orb radius / window side (the rest is room for the glow)
EDGE_GAP = 12        # orb edge to screen edge when snapped or placed by the grid
MINI_SHOWN = 0.2     # mini mode: the orb centre stays this many radii inside the screen


def orb_radius(side: int) -> int:
    return int(side * ORB_RATIO)


def preset_point(position: str, area: QRect, size: int, margin: int = EDGE_GAP) -> QPoint:
    """Top-left of the window so the ORB (not the window box) sits ``margin`` from the edges."""
    column = {"l": 0, "c": 1, "r": 2}[position[1]]
    row = {"t": 0, "m": 1, "b": 2}[position[0]]
    reach = orb_radius(size) + margin
    cx = (area.left() + reach, area.center().x(), area.right() - reach)[column]
    cy = (area.top() + reach, area.center().y(), area.bottom() - reach)[row]
    return QPoint(cx - size // 2, cy - size // 2)


def snap_to_edges(rect: QRect, area: QRect, distance: int = 80, mini: bool = False) -> tuple[QPoint, str]:
    """Stick the ORB to the nearest edge(s) — both at once in a corner.

    Measured from the visible orb, not the window with its glow margin, so it
    really reaches the edge. In mini mode the orb tucks behind the edge(s):
    about half shows at a side, about a quarter in a corner (like Luxify).
    """
    radius = orb_radius(rect.width())
    cx, cy = rect.x() + rect.width() // 2, rect.y() + rect.height() // 2
    inside = (int(radius * MINI_SHOWN) if mini else radius + EDGE_GAP)
    edges = []
    if cx - radius - area.left() <= distance:
        cx, _ = area.left() + inside, edges.append("left")
    elif area.right() - (cx + radius) <= distance:
        cx, _ = area.right() - inside, edges.append("right")
    if cy - radius - area.top() <= distance:
        cy, _ = area.top() + inside, edges.append("top")
    elif area.bottom() - (cy + radius) <= distance:
        cy, _ = area.bottom() - inside, edges.append("bottom")
    if not edges:
        return rect.topLeft(), ""
    return QPoint(cx - rect.width() // 2, cy - rect.height() // 2), "-".join(edges)


class LevelMeter:
    """Loudness from one or more sources, read by the painter every frame."""

    def __init__(self):
        self._lock = threading.Lock()
        self._peak = 0.0
        self._stamp = 0.0
        self.sensitivity = 0.5
        self.captures = []
        self.mic_stream = None

    def push(self, chunk) -> None:
        if chunk is None or not len(chunk):
            return
        rms = float(np.sqrt(np.mean(np.asarray(chunk, dtype=np.float32) ** 2)))
        value = loudness(rms, self.sensitivity)
        with self._lock:
            now = time.monotonic()
            # Several sources: keep the loudest one of the last moment.
            if value >= self._peak or now - self._stamp > 0.08:
                self._peak, self._stamp = value, now

    def level(self) -> float:
        with self._lock:
            if time.monotonic() - self._stamp > 0.25:
                return 0.0
            return self._peak

    def start(self, source: str, apps=()) -> None:
        from luxai.loopback_audio import LoopbackCapture, app_pid
        self.stop()
        if source == "voice":
            # Jarvis plays its voice itself: only this program's sound.
            self.captures.append(LoopbackCapture(self.push, app_pid=os.getpid()).start())
        if source in ("system", "all"):
            self.captures.append(LoopbackCapture(self.push).start())
        if source == "apps":
            for name in list(apps)[:4]:
                pid = app_pid(name)
                if pid:
                    self.captures.append(LoopbackCapture(self.push, app_pid=pid).start())
        if source in ("mic", "all"):
            try:
                import sounddevice as sd
                self.mic_stream = sd.InputStream(samplerate=16000, channels=1, dtype="float32", blocksize=800,
                                                 callback=lambda data, *_: self.push(data[:, 0]))
                self.mic_stream.start()
            except Exception:
                self.mic_stream = None

    def stop(self) -> None:
        captures, self.captures = self.captures, []
        for capture in captures:
            threading.Thread(target=capture.stop, daemon=True).start()
        stream, self.mic_stream = self.mic_stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass


class AvatarView(QWidget):
    """Paints the orb. Used both on the desktop window and as the preview."""

    def __init__(self, parent=None, *, meter: LevelMeter | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.meter = meter
        self.color = QColor(DEFAULT_COLOR)
        self.target = QColor(DEFAULT_COLOR)
        self.opacity = 0.7
        self.glow = 0.8
        self.speed = 0.5
        self.intensity = 0.3
        self.amplitude = 0.5
        self.smoothness = 1.0
        self.react = True
        self.reaction = 0.45
        self.scale = 1.0
        self.demo_level = None  # preview: a made-up voice instead of a meter
        self._level = 0.0
        self._phase = 0.0
        self._last = time.monotonic()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.set_fps(60)

    def set_fps(self, fps: int) -> None:
        self.timer.start(max(10, int(1000 / max(15, min(60, int(fps))))))

    def configure(self, settings: dict, base_color: str) -> None:
        self.opacity = int(settings.get("opacity", 70)) / 100
        self.glow = int(settings.get("glow", 80)) / 100
        self.speed = int(settings.get("speed", 50)) / 100
        self.intensity = int(settings.get("intensity", 30)) / 100
        self.amplitude = int(settings.get("amplitude", 50)) / 100
        self.smoothness = int(settings.get("smoothness", 100)) / 100
        self.react = bool(settings.get("react", True))
        self.reaction = int(settings.get("reaction", 45)) / 100
        if self.meter is not None:
            self.meter.sensitivity = int(settings.get("sensitivity", 50)) / 100
        self.set_target(base_color)
        try:
            self.set_fps(int(settings.get("fps", "60")))
        except (TypeError, ValueError):
            self.set_fps(60)

    def set_target(self, color: str) -> None:
        candidate = QColor(color)
        if candidate.isValid():
            self.target = candidate

    def current_level(self) -> float:
        if self.demo_level is not None:
            return self.demo_level(self._phase)
        return self.meter.level() if self.meter is not None else 0.0

    def _tick(self):
        now = time.monotonic()
        delta = min(0.1, now - self._last)
        self._last = now
        self._phase += delta * (0.6 + 2.4 * self.speed)
        raw = self.current_level() if self.react else 0.0
        # Quick to rise, slower to fall: the orb "speaks" without flicker.
        rate = 18.0 if raw > self._level else 5.0
        self._level += (raw - self._level) * min(1.0, delta * rate)
        mix = min(1.0, delta * 6.0)
        self.color = QColor.fromRgbF(
            self.color.redF() + (self.target.redF() - self.color.redF()) * mix,
            self.color.greenF() + (self.target.greenF() - self.color.greenF()) * mix,
            self.color.blueF() + (self.target.blueF() - self.color.blueF()) * mix)
        self.update()

    def shape(self, radius: float, layer: int) -> QPainterPath:
        center = QPointF(self.width() / 2, self.height() / 2)
        points = 72
        wobble = (0.03 + 0.07 * self.amplitude) * (0.6 + self._level * self.reaction * 1.8)
        harmonics = 2 if self.smoothness > 0.75 else 3 if self.smoothness > 0.4 else 5
        path = QPainterPath()
        for index in range(points + 1):
            angle = 2 * math.pi * index / points
            offset = 0.0
            for h in range(2, 2 + harmonics):
                offset += math.sin(h * angle + self._phase * (1.0 + 0.37 * h) + layer * 0.9 + h) / h
            r = radius * (1 + wobble * offset)
            point = QPointF(center.x() + r * math.cos(angle), center.y() + r * math.sin(angle))
            if index == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = min(self.width(), self.height())
        breath = 1 + self.intensity * 0.09 * math.sin(self._phase * 1.3)
        swell = 1 + self._level * self.reaction * 0.32
        radius = size * 0.27 * breath * swell * self.scale
        center = QPointF(self.width() / 2, self.height() / 2)
        if self.glow > 0:
            gradient = QRadialGradient(center, radius * 1.75)
            glow = QColor(self.color)
            glow.setAlphaF(min(1.0, 0.55 * self.glow * (0.7 + self._level * 0.6)))
            gradient.setColorAt(0.0, glow)
            glow.setAlphaF(0.0)
            gradient.setColorAt(1.0, glow)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawEllipse(center, radius * 1.75, radius * 1.75)
        painter.setPen(Qt.PenStyle.NoPen)
        for layer, (factor, alpha, light) in enumerate(((1.0, 0.45, 100), (0.78, 0.6, 115), (0.57, 0.8, 130), (0.36, 1.0, 150))):
            color = QColor(self.color).lighter(light)
            color.setAlphaF(max(0.0, min(1.0, alpha * self.opacity / 0.7)))
            painter.setBrush(color)
            painter.drawPath(self.shape(radius * factor, layer))


class AvatarWindow(QWidget):
    """Frameless always-on-top window holding the orb."""
    moved = Signal(int, int)

    def __init__(self, meter: LevelMeter):
        super().__init__(None)
        self.setObjectName("AvatarWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setProperty("i18n_skip", True)
        self.view = AvatarView(self, meter=meter)
        self.settings: dict = {}
        self._grab = None
        self._edge = ""
        self._flags(on_top=True, locked=False)

    def _flags(self, *, on_top: bool, locked: bool):
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowDoesNotAcceptFocus
        if on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        if locked:
            flags |= Qt.WindowType.WindowTransparentForInput  # clicks pass through
        if self.windowFlags() != flags:
            visible = self.isVisible()
            self.setWindowFlags(flags)
            if visible:
                self.show()

    def apply(self, settings: dict, base_color: str, screen_index: int = 0):
        self.settings = dict(settings)
        side = int(BASE_SIZE * int(settings.get("size", 100)) / 100)
        self.setFixedSize(side, side)
        self.view.setGeometry(0, 0, side, side)
        self.view.configure(settings, base_color)
        self._flags(on_top=bool(settings.get("on_top", True)), locked=bool(settings.get("lock", False)))
        self.place(screen_index)

    def screen_area(self, screen_index: int) -> QRect:
        screens = QGuiApplication.screens()
        screen = screens[screen_index] if 0 <= screen_index < len(screens) else QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def place(self, screen_index: int = 0):
        position = str(self.settings.get("position") or "br")
        area = self.screen_area(screen_index)
        if position in POSITIONS:
            point = preset_point(position, area, self.width())
        else:
            try:
                x, y = (int(part) for part in position.split(","))
                point = QPoint(x, y)
            except ValueError:
                point = preset_point("br", area, self.width())
            if not any(s.availableGeometry().adjusted(-self.width(), -self.height(), self.width(), self.height()).contains(point)
                       for s in QGuiApplication.screens()):
                point = preset_point("br", area, self.width())
        self.move(point)

    # -- mouse --
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.settings.get("drag", True) \
                and not self.settings.get("lock", False):
            self._grab = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._grab is not None:
            self.view.scale = 1.0
            self.move(event.globalPosition().toPoint() - self._grab)

    def mouseReleaseEvent(self, event):
        if self._grab is None:
            return
        self._grab = None
        screen = QGuiApplication.screenAt(self.geometry().center()) or QGuiApplication.primaryScreen()
        self._edge = ""
        if self.settings.get("snap", True):
            point, self._edge = snap_to_edges(self.geometry(), screen.availableGeometry(),
                                              mini=bool(self.settings.get("mini", True)))
            self.move(point)
        self.moved.emit(self.x(), self.y())


_FAILURE = None


def looks_failed(answer: str) -> bool:
    """A command answer that reports a failure (the avatar flashes red)."""
    import re
    global _FAILURE
    if _FAILURE is None:
        _FAILURE = re.compile(r"^\W*(?:не\s+удалось|не\s+получилось|ошибка|не\s+могу|nu\s+am\s+putut|eroare|nu\s+pot|"
                              r"could\s+not|couldn't|failed|error|unable)", re.I)
    return bool(_FAILURE.search(str(answer or "")))
