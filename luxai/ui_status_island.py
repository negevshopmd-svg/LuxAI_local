"""The status island window (0.4.3x): a black pill at the screen edge that morphs.

Everything is painted (no child widgets), so the shape can grow and shrink
smoothly like a phone's Dynamic Island: a small idle pill or clock, a compact
live activity with a second bubble beside it, and an expanded card with
controls when the mouse rests on it. Fully transparent pixels let clicks pass
through to the windows below, so only the pill itself catches the mouse.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from luxai.status_island import BACKGROUNDS, COLORS, SIZES, Activity, format_left

# Unscaled geometry (multiplied by the «size» setting).
CANVAS_W, CANVAS_H = 470, 250
MARGIN = 14                    # room for the glow around the pill
COMPACT_H = 36
EXPANDED_W = 392
IDLE = {"dot": (96, 24), "clock": (118, 30), "clock_date": (190, 30)}
QUICK_ICONS = {"mic": "mic", "quiet": "volume-x", "captions": "captions", "screenshot": "camera",
               "timer": "clock", "clipboard": "clipboard", "jarvis": "jarvis"}
KIND_ICONS = {"listening": "mic", "speaking": "audio-lines", "working": "sparkles", "waiting": "message-circle",
              "error": "x", "reply": "jarvis", "break": "coffee", "dictation": "mic", "convert": "download",
              "notification": "bell", "captions": "captions", "demo": "sparkles", "timer": "clock", "ring": "bell",
              "game": "gamepad-2", "played": "gamepad-2", "discord": "headphones", "steam": "download", "meeting": "clipboard-list",
              "steam_done": "check"}
DAYS = {"ru": ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"), "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
        "ro": ("Lu", "Ma", "Mi", "Jo", "Vi", "Sâ", "Du")}


def compact_text(activity: Activity) -> str:
    """One line for the small pill: what is said / asked / received, not only its kind."""
    if activity.kind in ("reply", "working") and activity.subtitle:
        return activity.subtitle
    if activity.kind == "discord" and activity.data.get("where"):
        return activity.data["where"]
    if activity.kind in ("notification", "error", "break") and activity.subtitle:
        return f"{activity.title}: {activity.subtitle}"
    return activity.title


def ease_spring(t: float) -> float:
    """A soft overshoot like the island on a phone (ends exactly at 1)."""
    t = max(0.0, min(1.0, t))
    return 1 - math.exp(-6.5 * t) * math.cos(7.5 * t) if t < 1 else 1.0


def lerp_rect(a: QRectF, b: QRectF, t: float) -> QRectF:
    return QRectF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t,
                  max(0.0, a.width() + (b.width() - a.width()) * t), max(0.0, a.height() + (b.height() - a.height()) * t))


class IslandWindow(QWidget):
    """Frameless, always on top, never takes the focus."""
    action = Signal(str)

    def __init__(self):
        super().__init__(None)
        self.setObjectName("StatusIsland")
        self.setProperty("i18n_skip", True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setMouseTracking(True)
        self.settings: dict = {}
        self.language = "ru"
        self.scale = 1.0
        self.main: Activity | None = None
        self.second: Activity | None = None
        self.flags: dict = {}
        self.quick: list[str] = []
        self.accent = "#3978f6"
        self.expanded = False
        self.pinned = False
        self.suppressed = False
        self._hover = False
        self._hover_button = ""
        self._buttons: list[tuple[QRectF, str]] = []
        self._rect = QRectF()
        self._from = QRectF()
        self._to = QRectF()
        self._anim_start = 0.0
        self._anim_seconds = 0.45
        self._content_since = 0.0
        self._last_shape_key = None
        self._thumb_key = None
        self._thumb = None
        self._game_key = None
        self._steam_key = None
        self._steam_icon = None
        self._game_icon = None
        self._game_banner = None
        self._peek_timer = QTimer(self)
        self._peek_timer.setSingleShot(True)
        self._peek_timer.timeout.connect(self._end_peek)
        self._phase = 0.0
        self._screen_name = ""
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._expand_from_hover)
        self._leave_timer = QTimer(self)
        self._leave_timer.setSingleShot(True)
        self._leave_timer.timeout.connect(self._collapse_after_leave)
        self._frame = QTimer(self)
        self._frame.timeout.connect(self._tick)
        self._frame.start(33)

    # -- configuration --------------------------------------------------------------------------
    def apply(self, settings: dict, language: str, accent: str):
        self.settings = dict(settings)
        self.language = language if language in ("ru", "en", "ro") else "ru"
        self.accent = accent or "#3978f6"
        self.scale = SIZES.get(str(settings.get("size", "100")), 1.0)
        self.quick = [name for name in ("mic", "quiet", "captions", "screenshot", "timer", "clipboard", "jarvis")
                      if settings.get(f"qa_{name}", name in ("mic", "quiet", "captions", "screenshot", "jarvis"))]
        speed = str(settings.get("animation", "smooth"))
        self._anim_seconds = {"smooth": 0.5, "fast": 0.28, "off": 0.0}.get(speed, 0.5)
        self.setFixedSize(round((CANVAS_W + 2 * MARGIN) * self.scale), round((CANVAS_H + MARGIN) * self.scale))
        self._last_shape_key = None
        self.place()
        self._retarget()

    def s(self, value: float) -> float:
        return value * self.scale

    @property
    def top(self) -> bool:
        return str(self.settings.get("edge", "top")) != "bottom"

    @property
    def notch(self) -> bool:
        return self.top and str(self.settings.get("style", "island")) == "notch"

    def target_screen(self):
        screens = QGuiApplication.screens()
        choice = str(self.settings.get("monitor", "primary"))
        if choice == "cursor":
            from PySide6.QtGui import QCursor
            return QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if choice.isdigit() and 0 <= int(choice) < len(screens):
            return screens[int(choice)]
        return QGuiApplication.primaryScreen()

    def place(self):
        screen = self.target_screen()
        if screen is None:
            return
        self._screen_name = screen.name()
        full, area = screen.geometry(), screen.availableGeometry()
        offset = round(self.s(float(self.settings.get("offset", 8) or 0)))
        x = full.x() + (full.width() - self.width()) // 2
        if self.notch:
            y = full.y()
        elif self.top:
            y = area.y() + offset - round(self.s(MARGIN))
        else:
            y = area.y() + area.height() - self.height() - offset + round(self.s(MARGIN))
        self.move(x, y)

    def follow_cursor_screen(self):
        """«Monitor: where the mouse is» — move while collapsed when the mouse went to another screen."""
        if str(self.settings.get("monitor")) == "cursor" and not self.expanded:
            screen = self.target_screen()
            if screen is not None and screen.name() != self._screen_name:
                self.place()

    def keep_on_top(self):
        import sys
        if sys.platform == "win32" and self.isVisible():
            import ctypes
            ctypes.windll.user32.SetWindowPos(int(self.winId()), -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040)

    # -- content --------------------------------------------------------------------------------
    def set_content(self, main: Activity | None, second: Activity | None, flags: dict):
        changed_kind = (getattr(self.main, "kind", None), getattr(self.main, "key", None), getattr(self.main, "title", None)) != \
                       (getattr(main, "kind", None), getattr(main, "key", None), getattr(main, "title", None))
        self.main, self.second, self.flags = main, second, dict(flags)
        if changed_kind:
            self._content_since = time.monotonic()
        if main is not None and main.kind == "media":
            self._set_thumb(main.data.get("thumb") or b"")
        elif second is not None and second.kind == "media":
            self._set_thumb(second.data.get("thumb") or b"")
        game = next((a for a in (main, second) if a is not None and a.kind == "game"), None)
        if game is not None:
            self._set_game_pictures(game)
        steam = next((a for a in (main, second) if a is not None and a.kind == "steam"), None)
        if steam is not None and steam.key != self._steam_key:
            self._steam_key = steam.key
            self._steam_icon = None
            if steam.data.get("icon"):
                pixmap = QPixmap()
                self._steam_icon = pixmap if pixmap.loadFromData(steam.data["icon"]) else None
        self._retarget()
        self.update()

    def set_suppressed(self, value: bool):
        if value != self.suppressed:
            self.suppressed = value
            self._retarget()

    def peek(self, seconds: float):
        """Open the card for a moment by itself (a game just started), then close it again."""
        if self.suppressed or self.pinned:
            return
        self.expanded = True
        self._retarget()
        self._peek_timer.start(int(seconds * 1000))

    def _end_peek(self):
        if not self._hover and not self.pinned:
            self.expanded = False
            self._retarget()

    def _set_game_pictures(self, game: Activity):
        """Steam's own icon and banner; without them the .exe's icon (read once per game)."""
        if game.key == self._game_key:
            return
        self._game_key = game.key
        self._game_icon = self._game_banner = None
        icon, banner = game.data.get("icon") or b"", game.data.get("banner") or b""
        if icon:
            pixmap = QPixmap()
            if pixmap.loadFromData(icon):
                self._game_icon = pixmap
        if self._game_icon is None and game.data.get("exe"):
            try:
                from PySide6.QtCore import QFileInfo, QSize
                from PySide6.QtWidgets import QFileIconProvider
                picture = QFileIconProvider().icon(QFileInfo(game.data["exe"])).pixmap(QSize(64, 64))
                self._game_icon = None if picture.isNull() else picture
            except Exception:
                self._game_icon = None
        if banner:
            pixmap = QPixmap()
            if pixmap.loadFromData(banner):
                self._game_banner = pixmap

    def toggle_pinned(self):
        self.pinned = not self.pinned
        self.expanded = self.pinned
        self._retarget()

    def _set_thumb(self, data: bytes):
        key = hashlib.sha1(data).hexdigest() if data else ""
        if key == self._thumb_key:
            return
        self._thumb_key = key
        self._thumb = None
        if data:
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                self._thumb = pixmap

    # -- shape ----------------------------------------------------------------------------------
    def _idle_mode(self) -> str:
        return str(self.settings.get("idle", "dot"))

    def _target_size(self) -> tuple[float, float]:
        if self.suppressed:
            return 0.0, 0.0
        if self.expanded and (self.main is not None or self.quick or self._idle_mode() != "hide"):
            return self.s(EXPANDED_W), self._expanded_height()
        if self.main is None:
            idle = self._idle_mode()
            if idle == "hide" or idle not in IDLE:
                return 0.0, 0.0
            width, height = IDLE[idle]
            return self.s(width), self.s(height)
        return self._compact_width(), self.s(COMPACT_H)

    def _compact_width(self) -> float:
        metrics = QFontMetricsF(self._font(12.5, True))
        main = self.main
        if main.kind == "volume":
            return self.s(240)
        text = compact_text(main)
        if main.kind in ("timer", "game", "discord", "steam", "meeting"):
            indicator = 92
        elif main.kind in ("media", "listening", "speaking", "volume", "working", "convert"):
            indicator = 64
        else:
            indicator = 24
        width = self.s(44 + indicator) + min(metrics.horizontalAdvance(text), self.s(200))
        return max(self.s(150), min(self.s(340), width))

    def _expanded_height(self) -> float:
        height = 18 + 50
        main = self.main
        if main is not None and (main.progress is not None or main.kind in ("media", "discord")):
            height += 26
        if main is not None and self._controls(main):
            height += 50
        if main is None:
            height = 18 + 34
        if self.quick:
            height += 46
        return self.s(height + 4)

    def _pill_rect(self, width: float, height: float) -> QRectF:
        x = (self.width() - width) / 2
        if self.notch:
            y = 0.0
        elif self.top:
            y = self.s(MARGIN)
        else:
            y = self.height() - self.s(MARGIN) - height
        return QRectF(x, y, width, height)

    def _retarget(self):
        width, height = self._target_size()
        target = self._pill_rect(width, height)
        key = (round(target.x()), round(target.y()), round(target.width()), round(target.height()))
        if key == self._last_shape_key:
            return
        self._last_shape_key = key
        if width > 0 and not self.isVisible():
            self.place()
            self.show()
            self.keep_on_top()
            if self._rect.isEmpty():
                self._rect = self._pill_rect(self.s(40), self.s(20) if height > self.s(20) else height)
        self._from = QRectF(self._rect)
        self._to = target
        self._anim_start = time.monotonic()
        self._frame.setInterval(16)

    def _animating(self) -> bool:
        return self._anim_seconds > 0 and time.monotonic() - self._anim_start < self._anim_seconds

    def _tick(self):
        now = time.monotonic()
        if self._anim_seconds <= 0:
            self._rect = QRectF(self._to)
        else:
            t = (now - self._anim_start) / self._anim_seconds
            self._rect = lerp_rect(self._from, self._to, ease_spring(t)) if t < 1 else QRectF(self._to)
        if self._to.width() <= 0 and not self._animating() and self.isVisible():
            self._rect = QRectF()
            self.hide()
        self._phase = now
        lively = self._animating() or self._has_motion() or now - self._content_since < 0.5
        fps = 16 if str(self.settings.get("fps", "60")) == "60" else 33
        self._frame.setInterval(fps if lively else 250)
        if self.isVisible():
            self.update()

    def _has_motion(self) -> bool:
        kinds = {getattr(self.main, "kind", ""), getattr(self.second, "kind", "")}
        if self.main is not None and self.main.kind == "media" and not self.main.data.get("playing"):
            kinds.discard("media")
        if self.second is not None and self.second.kind == "media" and not self.second.data.get("playing"):
            kinds.discard("media")
        return bool(kinds & {"listening", "speaking", "working", "media", "dictation", "ring", "convert"})

    # -- mouse ----------------------------------------------------------------------------------
    def enterEvent(self, event):
        self._hover = True
        self._leave_timer.stop()
        if str(self.settings.get("expand", "hover")) == "hover" and not self.expanded:
            self._hover_timer.start(int(self.settings.get("hover_delay", 300)))
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self._hover_button = ""
        self._hover_timer.stop()
        if self.expanded and not self.pinned:
            self._leave_timer.start(450)
        self.update()
        super().leaveEvent(event)

    def _expand_from_hover(self):
        if self._hover and not self.suppressed:
            self.expanded = True
            self._retarget()

    def _collapse_after_leave(self):
        if not self._hover and not self.pinned:
            self.expanded = False
            self._retarget()

    def mouseMoveEvent(self, event):
        point = event.position()
        hovered = next((name for rect, name in self._buttons if rect.contains(point)), "")
        if hovered != self._hover_button:
            self._hover_button = hovered
            self.setCursor(Qt.CursorShape.PointingHandCursor if hovered else Qt.CursorShape.ArrowCursor)
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        point = event.position()
        if event.button() == Qt.MouseButton.RightButton:
            if self.expanded:
                self.pinned = False
                self.expanded = False
                self._retarget()
            elif self.main is not None:
                self.action.emit("dismiss")
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        for rect, name in self._buttons:
            if rect.contains(point):
                self.action.emit(name)
                return
        if not self._rect.contains(point) and not self._second_rect().contains(point):
            return
        if self._second_rect().contains(point) and self.second is not None:
            self.action.emit(f"tap:{self.second.kind}")
            return
        if not self.expanded and str(self.settings.get("expand", "hover")) == "click":
            self.expanded = True
            self.pinned = True
            self._retarget()
            return
        if self.expanded and str(self.settings.get("expand", "hover")) == "click" and self.main is None:
            self.expanded = self.pinned = False
            self._retarget()
            return
        self.action.emit(f"tap:{self.main.kind}" if self.main is not None else "open")

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not any(r.contains(event.position()) for r, _ in self._buttons):
            self.action.emit("open")

    # -- painting -------------------------------------------------------------------------------
    def _font(self, size: float, bold: bool = False) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(max(8, round(self.s(size))))
        font.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
        return font

    def color_of(self, activity: Activity | None) -> QColor:
        if activity is None:
            return QColor(self.accent)
        if str(self.settings.get("accent", "activity")) == "theme":
            return QColor(self.accent)
        return QColor(COLORS.get(activity.kind, self.accent))

    def _background(self) -> QColor:
        choice = str(self.settings.get("background", "black"))
        if choice == "theme":
            color = QColor(self.accent).darker(330)
        else:
            color = QColor(BACKGROUNDS.get(choice, "#000000"))
        opacity = max(40, min(100, int(self.settings.get("opacity", 100) or 100)))
        if choice == "glass":
            opacity = min(opacity, 78)
        color.setAlphaF(opacity / 100)
        return color

    def _shape(self, rect: QRectF) -> QPainterPath:
        radius = min(rect.height() / 2, self.s(30 if rect.height() > self.s(60) else 99))
        path = QPainterPath()
        if not self.notch:
            path.addRoundedRect(rect, radius, radius)
            return path
        # The notch: square top glued to the screen edge, round bottom, soft «ears» at the top corners.
        ear = min(self.s(10), rect.width() / 6)
        r = min(radius, rect.height() - 1)
        x0, y0, x1, y1 = rect.left(), rect.top(), rect.right(), rect.bottom()
        path.moveTo(x0 - ear, y0)
        path.lineTo(x1 + ear, y0)
        path.quadTo(x1, y0, x1, y0 + ear)
        path.lineTo(x1, y1 - r)
        path.quadTo(x1, y1, x1 - r, y1)
        path.lineTo(x0 + r, y1)
        path.quadTo(x0, y1, x0, y1 - r)
        path.lineTo(x0, y0 + ear)
        path.quadTo(x0, y0, x0 - ear, y0)
        path.closeSubpath()
        return path

    def _second_rect(self) -> QRectF:
        if self.second is None or self.expanded or self._rect.isEmpty() or self.main is None:
            return QRectF()
        side = self._rect.height()
        return QRectF(self._rect.right() + self.s(7), self._rect.top(), side, side)

    def paintEvent(self, event):
        if self._rect.width() < 2 or self._rect.height() < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._buttons = []
        rect = QRectF(self._rect)
        self._paint_body(painter, rect, self.main)
        second = self._second_rect()
        if not second.isEmpty():
            self._paint_body(painter, second, self.second, glow=False)
            self._paint_bubble(painter, second, self.second)
        # Content appears once the shape is almost there (as the phone does), never squeezed.
        grown = 1.0 if self._to.width() <= 0 else min(1.0, rect.width() / max(1.0, self._to.width()),
                                                         rect.height() / max(1.0, self._to.height()))
        if grown < 0.82 or self._to.width() <= 0:
            return
        painter.setOpacity(min(1.0, (grown - 0.82) / 0.18) * min(1.0, (time.monotonic() - self._content_since) / 0.18 + 0.2))
        painter.save()
        painter.setClipPath(self._shape(rect))
        if self.expanded:
            self._paint_expanded(painter, rect)
        elif self.main is None:
            self._paint_idle(painter, rect)
        else:
            self._paint_compact(painter, rect, self.main)
        painter.restore()

    def _paint_body(self, painter: QPainter, rect: QRectF, activity: Activity | None, glow: bool = True):
        if glow and activity is not None and self.settings.get("glow", True):
            color = self.color_of(activity)
            pulse = 0.55 + 0.45 * math.sin(self._phase * 3.2) if activity.kind in ("ring", "listening", "error") else 0.7
            for step in range(4, 0, -1):
                halo = QColor(color)
                halo.setAlphaF(0.07 * pulse * (5 - step) / 4)
                grow = self.s(step * 2.2)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(halo)
                painter.drawPath(self._shape(rect.adjusted(-grow, -grow, grow, grow)))
        painter.setPen(QPen(QColor(255, 255, 255, 22), 1))
        painter.setBrush(self._background())
        painter.drawPath(self._shape(rect))

    # compact: [icon] title ........ [indicator]
    def _paint_compact(self, painter: QPainter, rect: QRectF, activity: Activity):
        pad = self.s(6)
        side = rect.height() - 2 * pad
        icon_rect = QRectF(rect.left() + pad + self.s(2), rect.top() + pad, side, side)
        self._paint_icon(painter, icon_rect, activity)
        right = rect.right() - self.s(12)
        width = self._paint_indicator(painter, QRectF(right - self.s(58), rect.top(), self.s(58), rect.height()), activity)
        text_left = icon_rect.right() + self.s(9)
        text_rect = QRectF(text_left, rect.top(), max(0.0, right - width - self.s(8) - text_left), rect.height())
        if activity.kind not in ("timer", "volume"):
            painter.setFont(self._font(12.5, True))
            painter.setPen(QColor(255, 255, 255, 235))
            metrics = QFontMetricsF(painter.font())
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             metrics.elidedText(compact_text(activity), Qt.TextElideMode.ElideRight, text_rect.width()))
        elif activity.kind == "volume":
            bar = QRectF(text_left, rect.center().y() - self.s(3), max(0.0, text_rect.width()), self.s(6))
            self._paint_bar(painter, bar, activity.progress or 0.0, QColor("#ffffff"))
        elif activity.kind == "timer":
            painter.setFont(self._font(12, False))
            painter.setPen(QColor(255, 255, 255, 170))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, activity.title)

    def _paint_idle(self, painter: QPainter, rect: QRectF):
        idle = self._idle_mode()
        if idle == "dot":
            return
        now = _dt.datetime.now()
        value = now.strftime("%H:%M")
        if idle == "clock_date":
            day = DAYS.get(self.language, DAYS["en"])[now.weekday()]
            value = f"{day} {now.day:02d}.{now.month:02d}  ·  {value}"
        painter.setFont(self._font(13, True))
        painter.setPen(QColor(255, 255, 255, 225))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, value)
        if not self.flags.get("mic_on", True):
            painter.setBrush(QColor("#ff453a"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(rect.right() - self.s(12), rect.center().y()), self.s(3), self.s(3))

    def _paint_bubble(self, painter: QPainter, rect: QRectF, activity: Activity):
        """The second live activity: a round bubble with its progress ring or picture."""
        inner = rect.adjusted(self.s(5), self.s(5), -self.s(5), -self.s(5))
        if activity.kind == "media" and self._thumb is not None:
            self._paint_thumb(painter, inner, round_=True)
        elif activity.kind == "game" and self._game_icon is not None:
            self._paint_thumb(painter, inner, round_=True, pixmap=self._game_icon)
        elif activity.kind == "steam" and self._steam_icon is not None:
            self._paint_thumb(painter, inner, round_=True, pixmap=self._steam_icon)
        else:
            self._paint_glyph(painter, inner.adjusted(self.s(3), self.s(3), -self.s(3), -self.s(3)), activity)
        if activity.progress is not None:
            self._paint_ring(painter, rect.adjusted(self.s(2), self.s(2), -self.s(2), -self.s(2)), activity.progress,
                             self.color_of(activity))

    # -- pieces ----------------------------------------------------------------------------------
    def _paint_icon(self, painter: QPainter, rect: QRectF, activity: Activity):
        if activity.kind == "media" and self._thumb is not None:
            self._paint_thumb(painter, rect)
            return
        if activity.kind == "game" and self._game_icon is not None:
            self._paint_thumb(painter, rect, pixmap=self._game_icon)
            return
        if activity.kind == "steam" and self._steam_icon is not None:
            self._paint_thumb(painter, rect.adjusted(self.s(3), self.s(3), -self.s(3), -self.s(3)), pixmap=self._steam_icon)
            if activity.progress is not None:
                self._paint_ring(painter, rect.adjusted(self.s(0.5), self.s(0.5), -self.s(0.5), -self.s(0.5)),
                                 activity.progress, self.color_of(activity))
            return
        color = self.color_of(activity)
        back = QColor(color)
        back.setAlphaF(0.2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(back)
        painter.drawEllipse(rect)
        if activity.kind in ("timer", "steam") and activity.progress is not None:
            self._paint_ring(painter, rect.adjusted(self.s(1.5), self.s(1.5), -self.s(1.5), -self.s(1.5)),
                             1 - activity.progress if activity.kind == "timer" else activity.progress, color)
        self._paint_glyph(painter, rect.adjusted(rect.width() * 0.24, rect.height() * 0.24,
                                                 -rect.width() * 0.24, -rect.height() * 0.24), activity)

    def _paint_glyph(self, painter: QPainter, rect: QRectF, activity: Activity):
        color = self.color_of(activity)
        if activity.kind == "volume":
            self._icon(painter, rect, "volume-x" if activity.data.get("muted") else "volume-2", "#ffffff")
        elif activity.kind == "media":
            self._icon(painter, rect, "audio-lines", color.name())
        elif activity.kind == "battery":
            self._paint_battery(painter, rect, activity.progress or 0.0, color)
        else:
            self._icon(painter, rect, KIND_ICONS.get(activity.kind, "sparkles"), color.name())

    def _icon(self, painter: QPainter, rect: QRectF, name: str, color: str):
        try:
            from luxai.icons import icon
            icon(name, color=color).paint(painter, rect.toAlignedRect())
        except Exception:
            painter.setPen(QPen(QColor(color), self.s(1.6)))
            painter.drawEllipse(rect.adjusted(2, 2, -2, -2))

    def _paint_thumb(self, painter: QPainter, rect: QRectF, round_: bool = False, pixmap: QPixmap | None = None):
        path = QPainterPath()
        if round_:
            path.addEllipse(rect)
        else:
            path.addRoundedRect(rect, rect.width() * 0.24, rect.height() * 0.24)
        painter.save()
        painter.setClipPath(path)
        pixmap = pixmap if pixmap is not None else self._thumb
        ratio = max(rect.width() / max(1, pixmap.width()), rect.height() / max(1, pixmap.height()))
        w, h = pixmap.width() * ratio, pixmap.height() * ratio
        painter.drawPixmap(QRectF(rect.center().x() - w / 2, rect.center().y() - h / 2, w, h), pixmap, QRectF(pixmap.rect()))
        painter.restore()

    def _paint_ring(self, painter: QPainter, rect: QRectF, value: float, color: QColor):
        track = QColor(255, 255, 255, 38)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(track, self.s(2.4)))
        painter.drawEllipse(rect)
        pen = QPen(color, self.s(2.4))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, 90 * 16, -round(360 * 16 * max(0.0, min(1.0, value))))

    def _paint_indicator(self, painter: QPainter, rect: QRectF, activity: Activity) -> float:
        """Right side of the compact pill; returns the width it used."""
        color = self.color_of(activity)
        kind = activity.kind
        if kind in ("timer", "game", "discord", "steam", "meeting"):
            painter.setFont(self._font(15 if kind == "timer" else 13.5, True))
            painter.setPen(color if kind != "discord" else QColor(255, 255, 255, 220))
            value = {"timer": "left", "game": "elapsed", "discord": "elapsed", "steam": "percent", "meeting": "elapsed"}[kind]
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, activity.data.get(value, ""))
            if kind == "discord" and activity.data.get("mic_muted"):
                width = QFontMetricsF(painter.font()).horizontalAdvance(activity.data.get("elapsed", ""))
                dot = QRectF(rect.right() - width - self.s(22), rect.center().y() - self.s(8), self.s(16), self.s(16))
                self._icon(painter, dot, "mic-off", "#ff453a")
            return rect.width()
        if kind in ("listening", "speaking", "dictation") or (kind == "media" and activity.data.get("playing")):
            self._paint_waves(painter, QRectF(rect.right() - self.s(30), rect.top(), self.s(30), rect.height()), color,
                              calm=(kind == "listening"))
            return self.s(30)
        if kind == "media":
            self._paint_play(painter, QRectF(rect.right() - self.s(16), rect.center().y() - self.s(7), self.s(14), self.s(14)),
                             QColor(255, 255, 255, 200))
            return self.s(18)
        if kind in ("working", "convert"):
            self._paint_spinner(painter, QPointF(rect.right() - self.s(10), rect.center().y()), self.s(8), color,
                                activity.progress)
            return self.s(22)
        if kind == "volume":
            painter.setFont(self._font(12, True))
            painter.setPen(QColor(255, 255, 255, 220))
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, activity.subtitle)
            return self.s(40)
        if kind == "ring":
            self._paint_waves(painter, QRectF(rect.right() - self.s(30), rect.top(), self.s(30), rect.height()), color)
            return self.s(30)
        return 0.0

    def _paint_waves(self, painter: QPainter, rect: QRectF, color: QColor, calm: bool = False):
        bars = 5
        gap = rect.width() / (bars * 2 - 1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        for index in range(bars):
            speed = 5.5 if not calm else 2.6
            wave = 0.5 + 0.5 * math.sin(self._phase * speed + index * 1.3) * math.sin(self._phase * 2.1 + index * 0.7)
            height = rect.height() * (0.18 + (0.5 if not calm else 0.28) * abs(wave))
            x = rect.left() + index * gap * 2
            painter.drawRoundedRect(QRectF(x, rect.center().y() - height / 2, gap, height), gap / 2, gap / 2)

    def _paint_spinner(self, painter: QPainter, center: QPointF, radius: float, color: QColor, progress=None):
        rect = QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)
        if progress is not None:
            self._paint_ring(painter, rect, progress, color)
            return
        pen = QPen(color, self.s(2.2))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(rect, round(-self._phase * 360 * 1.4) * 16, 100 * 16)

    def _paint_bar(self, painter: QPainter, rect: QRectF, value: float, color: QColor):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 40))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        filled = QRectF(rect.left(), rect.top(), rect.width() * max(0.0, min(1.0, value)), rect.height())
        if filled.width() > 0.5:
            painter.setBrush(color)
            painter.drawRoundedRect(filled, rect.height() / 2, rect.height() / 2)

    def _paint_battery(self, painter: QPainter, rect: QRectF, value: float, color: QColor):
        body = QRectF(rect.left(), rect.top() + rect.height() * 0.25, rect.width() * 0.85, rect.height() * 0.5)
        painter.setPen(QPen(QColor(255, 255, 255, 220), self.s(1.3)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(body, self.s(2), self.s(2))
        painter.fillRect(QRectF(body.right() + 1, body.center().y() - body.height() * 0.2, rect.width() * 0.08, body.height() * 0.4),
                         QColor(255, 255, 255, 220))
        inner = body.adjusted(self.s(2), self.s(2), -self.s(2), -self.s(2))
        painter.fillRect(QRectF(inner.left(), inner.top(), inner.width() * max(0.05, value), inner.height()),
                         color if value > 0.2 else QColor("#ff453a"))

    def _paint_play(self, painter: QPainter, rect: QRectF, color: QColor):
        path = QPainterPath()
        path.moveTo(rect.left() + rect.width() * 0.2, rect.top())
        path.lineTo(rect.right(), rect.center().y())
        path.lineTo(rect.left() + rect.width() * 0.2, rect.bottom())
        path.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPath(path)

    def _paint_pause(self, painter: QPainter, rect: QRectF, color: QColor):
        width = rect.width() * 0.3
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(rect.left() + rect.width() * 0.08, rect.top(), width, rect.height()), 1.5, 1.5)
        painter.drawRoundedRect(QRectF(rect.right() - rect.width() * 0.08 - width, rect.top(), width, rect.height()), 1.5, 1.5)

    def _paint_skip(self, painter: QPainter, rect: QRectF, color: QColor, forward: bool):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        half = rect.width() / 2
        for index in range(2):
            path = QPainterPath()
            left = rect.left() + index * half * 0.9
            if forward:
                path.moveTo(left, rect.top())
                path.lineTo(left + half, rect.center().y())
                path.lineTo(left, rect.bottom())
            else:
                path.moveTo(left + half, rect.top())
                path.lineTo(left, rect.center().y())
                path.lineTo(left + half, rect.bottom())
            path.closeSubpath()
            painter.drawPath(path)

    # -- expanded card ----------------------------------------------------------------------------
    def _controls(self, activity: Activity) -> list[tuple[str, str]]:
        """(action id, glyph / label) buttons for the activity, shown in the expanded card."""
        kind = activity.kind
        t = self._label
        if kind == "media":
            items = []
            if activity.data.get("can_previous", True):
                items.append(("media:previous", "@prev"))
            items.append(("media:play_pause", "@pause" if activity.data.get("playing") else "@play"))
            if activity.data.get("can_next", True):
                items.append(("media:next", "@next"))
            return items
        if kind == "timer":
            return [("timer:add60", t("+1 мин", "+1 min", "+1 min")), ("timer:add300", t("+5 мин", "+5 min", "+5 min")),
                    ("timer:cancel", t("Отменить", "Cancel", "Anulează"))]
        if kind == "ring":
            return [("ring:snooze", t("Отложить", "Snooze", "Amână")), ("ring:stop", t("Стоп", "Stop", "Stop"))]
        if kind == "speaking":
            return [("voice:stop", t("Замолчать", "Stop talking", "Taci"))]
        if kind == "break":
            return [("break:done", t("Сделал", "Done", "Gata")), ("break:later", t("Позже", "Later", "Mai târziu")),
                    ("break:skip", t("Пропустить", "Skip", "Sar"))]
        if kind == "dictation":
            return [("dictation:stop", t("Готово", "Done", "Gata")), ("dictation:cancel", t("Отмена", "Cancel", "Anulează"))]
        if kind == "captions":
            return [("captions:hide", t("Скрыть субтитры", "Hide captions", "Ascunde subtitrările"))]
        if kind == "discord":
            return [("discord:mic", "@icon:mic-off" if activity.data.get("mic_muted") else "@icon:mic"),
                    ("discord:deaf", "@icon:volume-x" if activity.data.get("deafened") else "@icon:headphones"),
                    ("discord:down", "@icon:minus"), ("discord:up", "@icon:plus")]
        if kind == "meeting":
            return [("meeting:pause", t("Продолжить", "Resume", "Continuă") if activity.data.get("paused")
                     else t("Пауза", "Pause", "Pauză")),
                    ("meeting:stop", t("Стоп и конспект", "Stop and notes", "Stop și rezumat"))]
        if kind == "steam":
            return [("steam:open", t("Открыть загрузки Steam", "Open Steam downloads", "Deschide descărcările Steam"))]
        if kind == "game":
            return [("quick:screenshot", t("Снимок экрана", "Screenshot", "Captură")),
                    ("game:hide", t("Скрыть до выхода", "Hide until I quit", "Ascunde până ies"))]
        if kind in ("notification", "reply", "error", "volume", "battery", "demo", "played", "steam_done"):
            return [("dismiss", t("Закрыть", "Close", "Închide"))]
        return []

    def _label(self, ru: str, en: str, ro: str) -> str:
        return {"ru": ru, "en": en, "ro": ro}[self.language]

    def _paint_expanded(self, painter: QPainter, rect: QRectF):
        pad = self.s(16)
        y = rect.top() + self.s(14)
        main = self.main
        if main is not None:
            if main.kind == "game" and self._game_banner is not None:
                self._paint_banner(painter, QRectF(rect.left(), rect.top(), rect.width(), self.s(76)))
            icon_rect = QRectF(rect.left() + pad, y, self.s(46), self.s(46))
            self._paint_icon(painter, icon_rect, main)
            right = rect.right() - pad
            indicator = self._paint_indicator(painter, QRectF(right - self.s(58), y, self.s(58), self.s(46)), main) \
                if main.kind not in ("volume",) else 0.0
            text_left = icon_rect.right() + self.s(12)
            text_width = max(0.0, right - indicator - self.s(10) - text_left)
            self._paint_texts(painter, QRectF(text_left, y, text_width, self.s(46)), main)
            y += self.s(54)
            if main.progress is not None or main.kind in ("media", "discord"):
                self._paint_progress_row(painter, QRectF(rect.left() + pad, y, rect.width() - 2 * pad, self.s(20)), main)
                y += self.s(26)
            controls = self._controls(main)
            if controls:
                self._paint_controls(painter, QRectF(rect.left() + pad, y, rect.width() - 2 * pad, self.s(40)), controls, main)
                y += self.s(50)
        else:
            painter.setFont(self._font(13, True))
            painter.setPen(QColor(255, 255, 255, 220))
            now = _dt.datetime.now()
            day = DAYS.get(self.language, DAYS["en"])[now.weekday()]
            painter.drawText(QRectF(rect.left() + pad, y, rect.width() - 2 * pad, self.s(26)),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             f"{day} {now.day:02d}.{now.month:02d}  ·  {now.strftime('%H:%M')}")
            y += self.s(34)
        if self.quick:
            self._paint_quick(painter, QRectF(rect.left() + pad, y, rect.width() - 2 * pad, self.s(38)))

    def _paint_banner(self, painter: QPainter, rect: QRectF):
        """The game's Steam banner behind the card's top, fading into the black below."""
        from PySide6.QtGui import QLinearGradient
        pixmap = self._game_banner
        ratio = max(rect.width() / max(1, pixmap.width()), rect.height() / max(1, pixmap.height()))
        w, h = pixmap.width() * ratio, pixmap.height() * ratio
        painter.save()
        painter.setClipRect(rect)
        painter.setOpacity(painter.opacity() * 0.55)
        painter.drawPixmap(QRectF(rect.center().x() - w / 2, rect.center().y() - h / 2, w, h), pixmap, QRectF(pixmap.rect()))
        painter.restore()
        fade = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        back = self._background()
        clear = QColor(back)
        clear.setAlphaF(0.15)
        fade.setColorAt(0.0, clear)
        fade.setColorAt(1.0, back)
        painter.fillRect(rect, fade)

    def _paint_texts(self, painter: QPainter, rect: QRectF, activity: Activity):
        title, subtitle = activity.title, activity.subtitle
        if activity.kind == "timer" and activity.data.get("ends"):
            subtitle = (activity.subtitle + " · " if activity.subtitle else "") + activity.data["ends"]
        painter.setFont(self._font(14, True))
        painter.setPen(QColor(255, 255, 255, 240))
        metrics = QFontMetricsF(painter.font())
        if subtitle:
            top = QRectF(rect.left(), rect.top() + self.s(3), rect.width(), rect.height() / 2)
            painter.drawText(top, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
                             metrics.elidedText(title, Qt.TextElideMode.ElideRight, rect.width()))
            painter.setFont(self._font(12, False))
            painter.setPen(QColor(255, 255, 255, 150))
            metrics = QFontMetricsF(painter.font())
            bottom = QRectF(rect.left(), rect.center().y() + self.s(3), rect.width(), rect.height() / 2 - self.s(3))
            painter.drawText(bottom, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                             metrics.elidedText(subtitle, Qt.TextElideMode.ElideRight, rect.width()))
        else:
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             metrics.elidedText(title, Qt.TextElideMode.ElideRight, rect.width()))

    def _paint_progress_row(self, painter: QPainter, rect: QRectF, activity: Activity):
        color = self.color_of(activity)
        painter.setFont(self._font(10.5, False))
        painter.setPen(QColor(255, 255, 255, 140))
        if activity.kind == "media" and activity.data.get("duration", 0) > 1:
            left = format_left(activity.data.get("position", 0))
            total = "-" + format_left(activity.data["duration"] - activity.data.get("position", 0))
            label_w = self.s(42)
            painter.drawText(QRectF(rect.left(), rect.top(), label_w, rect.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, left)
            painter.drawText(QRectF(rect.right() - label_w, rect.top(), label_w, rect.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, total)
            bar = QRectF(rect.left() + label_w, rect.center().y() - self.s(2.5), rect.width() - 2 * label_w, self.s(5))
            self._paint_bar(painter, bar, activity.progress or 0.0, QColor(255, 255, 255, 230))
            return
        if activity.kind == "discord":
            volume = activity.data.get("volume")
            label_w = self.s(96)
            text = self._label("Громкость", "Volume", "Volum") + (f" {round(volume * 100)}%" if volume is not None else " —")
            painter.drawText(QRectF(rect.left(), rect.top(), label_w, rect.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
            bar = QRectF(rect.left() + label_w, rect.center().y() - self.s(2.5), rect.width() - label_w, self.s(5))
            self._paint_bar(painter, bar, volume or 0.0, color)
            return
        if activity.kind == "steam" and activity.data.get("eta"):
            label_w = self.s(92)
            from luxai.status_island import word
            painter.drawText(QRectF(rect.right() - label_w, rect.top(), label_w, rect.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                             word("eta", self.language, t=activity.data["eta"]))
            rect = QRectF(rect.left(), rect.top(), rect.width() - label_w - self.s(8), rect.height())
        if activity.progress is not None:
            bar = QRectF(rect.left(), rect.center().y() - self.s(2.5), rect.width(), self.s(5))
            self._paint_bar(painter, bar, activity.progress, color)

    def _paint_controls(self, painter: QPainter, rect: QRectF, controls, activity: Activity):
        glyphs = [c for c in controls if c[1].startswith("@")]
        if glyphs and len(glyphs) == len(controls):
            side = self.s(40)
            gap = self.s(26)
            total = len(controls) * side + (len(controls) - 1) * gap
            x = rect.center().x() - total / 2
            for name, glyph in controls:
                button = QRectF(x, rect.top(), side, side)
                self._button_back(painter, button, name, round_=True)
                inner = button.adjusted(side * 0.3, side * 0.3, -side * 0.3, -side * 0.3)
                white = QColor(255, 255, 255, 235)
                if glyph.startswith("@icon:"):
                    alert = glyph in ("@icon:mic-off", "@icon:volume-x")
                    if alert:
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(QColor(255, 69, 58, 70))
                        painter.drawEllipse(button)
                    self._icon(painter, inner.adjusted(-side * 0.04, -side * 0.04, side * 0.04, side * 0.04),
                               glyph[6:], "#ff453a" if alert else "#ffffff")
                elif glyph == "@play":
                    self._paint_play(painter, inner.adjusted(self.s(1.5), 0, self.s(1.5), 0), white)
                elif glyph == "@pause":
                    self._paint_pause(painter, inner, white)
                else:
                    self._paint_skip(painter, inner, white, forward=(glyph == "@next"))
                self._buttons.append((button, name))
                x += side + gap
            return
        gap = self.s(8)
        width = (rect.width() - gap * (len(controls) - 1)) / len(controls)
        x = rect.left()
        painter.setFont(self._font(12.5, True))
        for index, (name, label) in enumerate(controls):
            button = QRectF(x, rect.top(), width, rect.height() - self.s(2))
            primary = (index == 0 and activity.kind in ("ring", "break", "dictation", "speaking")) or \
                (name == "meeting:stop")
            self._button_back(painter, button, name, primary=primary, color=self.color_of(activity))
            painter.setPen(QColor(0, 0, 0, 230) if primary else QColor(255, 255, 255, 230))
            painter.drawText(button, Qt.AlignmentFlag.AlignCenter,
                             QFontMetricsF(painter.font()).elidedText(label, Qt.TextElideMode.ElideRight, button.width() - 8))
            self._buttons.append((button, name))
            x += width + gap

    def _button_back(self, painter: QPainter, rect: QRectF, name: str, *, round_: bool = False, primary: bool = False,
                     color: QColor | None = None):
        hovered = name == self._hover_button
        if primary and color is not None:
            back = QColor(color).lighter(115 if hovered else 100)
        else:
            back = QColor(255, 255, 255, 46 if hovered else 24)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(back)
        if round_:
            painter.drawEllipse(rect)
        else:
            painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)

    def _paint_quick(self, painter: QPainter, rect: QRectF):
        """Quick actions: round buttons; mic / quiet / captions light up when on."""
        side = rect.height()
        count = len(self.quick)
        gap = min(self.s(14), (rect.width() - count * side) / max(1, count - 1)) if count > 1 else 0
        total = count * side + (count - 1) * gap
        x = rect.center().x() - total / 2
        painter.setPen(QPen(QColor(255, 255, 255, 18), 1))
        painter.drawLine(QPointF(rect.left(), rect.top() - self.s(6)), QPointF(rect.right(), rect.top() - self.s(6)))
        for name in self.quick:
            button = QRectF(x, rect.top(), side, side)
            active = {"mic": self.flags.get("mic_on", True), "quiet": self.flags.get("quiet", False),
                      "captions": self.flags.get("captions", False)}.get(name, False)
            hovered = f"quick:{name}" == self._hover_button
            painter.setPen(Qt.PenStyle.NoPen)
            if active:
                back = QColor(self.accent)
                back.setAlphaF(0.85 if hovered else 0.7)
            else:
                back = QColor(255, 255, 255, 46 if hovered else 22)
            painter.setBrush(back)
            painter.drawEllipse(button)
            glyph = QUICK_ICONS[name]
            if name == "mic" and not self.flags.get("mic_on", True):
                glyph = "mic-off"
            inner = button.adjusted(side * 0.28, side * 0.28, -side * 0.28, -side * 0.28)
            self._icon(painter, inner, glyph, "#ffffff" if (active or name != "jarvis") else "#3978f6")
            self._buttons.append((button, f"quick:{name}"))
            x += side + gap
