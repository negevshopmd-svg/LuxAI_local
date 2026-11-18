"""Live captions: turn what the PC plays into text on an always-on-top bar.

Audio comes from ``loopback_audio`` (all sound except Jarvis, or one
program). The recogniser re-reads the current phrase about once a second
(partial text) and finishes it after a short pause or 12 seconds. Finished
phrases can be translated by the cloud AI. Audio is never saved or sent.
"""
from __future__ import annotations

import threading
import time

import numpy as np

SAMPLE_RATE = 16000
FRAME = 480                 # 30 ms
PAUSE_SECONDS = 0.7         # quiet this long after speech = the phrase is finished
MAX_PHRASE_SECONDS = 12.0
PARTIAL_EVERY = 0.9
KEEP_FINAL = 12


def frame_rms(audio: np.ndarray) -> np.ndarray:
    usable = len(audio) // FRAME * FRAME
    if not usable:
        return np.zeros(0, dtype=np.float32)
    frames = audio[:usable].reshape(-1, FRAME)
    return np.sqrt(np.mean(frames * frames, axis=1))


class PhraseSegmenter:
    """Pure logic: collects audio, says when a phrase is ready to be read."""

    def __init__(self, threshold: float = 0.008):
        self.threshold = threshold
        self.buffer = np.zeros(0, dtype=np.float32)
        self.heard_speech = False
        self.quiet_frames = 0
        self._pending = np.zeros(0, dtype=np.float32)

    def feed(self, audio: np.ndarray) -> None:
        audio = np.asarray(audio, dtype=np.float32)
        self._pending = np.concatenate([self._pending, audio])
        usable = len(self._pending) // FRAME * FRAME
        if not usable:
            return
        chunk, self._pending = self._pending[:usable], self._pending[usable:]
        for value in frame_rms(chunk):
            if value >= self.threshold:
                self.heard_speech = True
                self.quiet_frames = 0
            else:
                self.quiet_frames += 1
        if self.heard_speech:
            self.buffer = np.concatenate([self.buffer, chunk])
        else:
            # Keep a little lead-in so the first word is not cut.
            self.buffer = np.concatenate([self.buffer, chunk])[-int(SAMPLE_RATE * 0.3):]

    @property
    def seconds(self) -> float:
        return len(self.buffer) / SAMPLE_RATE

    def phrase_finished(self) -> bool:
        if not self.heard_speech:
            return False
        return self.quiet_frames * FRAME / SAMPLE_RATE >= PAUSE_SECONDS or self.seconds >= MAX_PHRASE_SECONDS

    def take(self) -> np.ndarray:
        audio = self.buffer
        self.buffer = np.zeros(0, dtype=np.float32)
        self.heard_speech = False
        self.quiet_frames = 0
        return audio


class CaptionEngine:
    """Recognition thread. Callbacks run on that thread — re-emit them as Qt signals."""

    def __init__(self, model_provider, language, on_partial, on_final, on_error=None):
        self.model_provider = model_provider
        self.language = language
        self.on_partial = on_partial
        self.on_final = on_final
        self.on_error = on_error
        self.segmenter = PhraseSegmenter()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._last_partial = 0.0

    def feed(self, audio: np.ndarray) -> None:
        with self._lock:
            self.segmenter.feed(audio)

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="JarvisCaptions")
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def _transcribe(self, model, audio) -> str:
        from luxai.dictation import transcribe
        return transcribe(model, audio, self.language, 1)

    def step(self, model) -> None:
        """One pass: finish a phrase or refresh the partial text."""
        with self._lock:
            finished = self.segmenter.phrase_finished()
            audio = self.segmenter.take() if finished else self.segmenter.buffer.copy()
            speaking = self.segmenter.heard_speech
        if finished:
            text = self._transcribe(model, audio)
            self.on_partial("")
            if text:
                self.on_final(text)
            return
        if speaking and time.monotonic() - self._last_partial >= PARTIAL_EVERY and len(audio) >= SAMPLE_RATE * 0.6:
            self._last_partial = time.monotonic()
            text = self._transcribe(model, audio)
            if text:
                self.on_partial(text)

    def _run(self):
        model = None
        while not self._stop.is_set():
            try:
                if model is None:
                    model = self.model_provider()
                    if model is None:
                        raise RuntimeError("speech model is not loaded")
                self.step(model)
            except Exception as error:
                if self.on_error is not None:
                    self.on_error(f"{type(error).__name__}: {error}")
                self._stop.wait(3)
            self._stop.wait(0.2)


# -- the bar -------------------------------------------------------------------
from PySide6.QtCore import QPoint, Qt, Signal  # noqa: E402
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter  # noqa: E402
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget  # noqa: E402


class _Handle(QLabel):
    def __init__(self, bar):
        super().__init__("⋮⋮")
        self.bar = bar
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setStyleSheet("color: rgba(255,255,255,0.6); padding: 0 6px;")
        font = self.font()
        font.setPointSize(16)
        font.setBold(True)
        self.setFont(font)
        self._grab = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._grab = event.globalPosition().toPoint() - self.bar.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._grab is not None:
            self.bar.move(event.globalPosition().toPoint() - self._grab)

    def mouseReleaseEvent(self, event):
        if self._grab is not None:
            self._grab = None
            self.bar.moved.emit(self.bar.x(), self.bar.y())


class CaptionBar(QWidget):
    """Always-on-top strip with the last lines of text. Never takes the focus."""
    closed_by_user = Signal()
    moved = Signal(int, int)

    def __init__(self):
        super().__init__(None)
        self.setObjectName("CaptionBar")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setProperty("i18n_skip", True)
        self.font_size = 26
        self.opacity = 0.72
        self.max_lines = 2
        self.show_original = True
        self.lines: list[tuple[str, str]] = []   # (original, translation)
        self.partial = ""
        self.placeholder = ""
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 8, 6, 8)
        row.setSpacing(6)
        row.addWidget(_Handle(self), 0, Qt.AlignmentFlag.AlignVCenter)
        column = QVBoxLayout()
        column.setSpacing(2)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.text)
        row.addLayout(column, 1)
        close = QToolButton()
        close.setText("×")
        close.setAutoRaise(True)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet("QToolButton{color: rgba(255,255,255,0.7); border: none; background: transparent; padding: 0 6px;}"
                            "QToolButton:hover{color: white;}")
        font = close.font()
        font.setPointSize(15)
        close.setFont(font)
        close.clicked.connect(self.closed_by_user.emit)
        row.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        self.render()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(12, 14, 18, int(255 * self.opacity)))
        painter.drawRoundedRect(self.rect(), 14, 14)

    def configure(self, *, font_size=None, opacity=None, lines=None, show_original=None):
        if font_size is not None:
            self.font_size = int(font_size)
        if opacity is not None:
            self.opacity = max(0.0, min(1.0, float(opacity)))
        if lines is not None:
            self.max_lines = max(1, min(3, int(lines)))
        if show_original is not None:
            self.show_original = bool(show_original)
        self.render()
        self.update()

    def add_final(self, original: str, translation: str = ""):
        self.lines.append((original, translation))
        self.lines = self.lines[-KEEP_FINAL:]
        self.render()

    def set_translation(self, original: str, translation: str):
        for index in range(len(self.lines) - 1, -1, -1):
            if self.lines[index][0] == original and not self.lines[index][1]:
                self.lines[index] = (original, translation)
                break
        self.render()

    def set_partial(self, text: str):
        self.partial = text
        self.render()

    def visible_lines(self) -> list[tuple[str, str]]:
        shown = list(self.lines)
        if self.partial:
            shown.append((self.partial, ""))
        return shown[-self.max_lines:]

    def render(self):
        import html
        small = max(10, int(self.font_size * 0.8))
        blocks = []
        for original, translation in self.visible_lines():
            parts = []
            if self.show_original or not translation:
                parts.append(f"<div style='margin:0; font-size:{self.font_size}px; color:white;'>{html.escape(original)}</div>")
            if translation:
                size = small if self.show_original else self.font_size
                color = "#ffd166" if self.show_original else "white"
                parts.append(f"<div style='margin:0; font-size:{size}px; color:{color};'>{html.escape(translation)}</div>")
            blocks.append("".join(parts))
        if not blocks and self.placeholder:
            blocks.append(f"<div style='margin:0; font-size:{small}px; color:rgba(255,255,255,0.6);'>{html.escape(self.placeholder)}</div>")
        self.text.setText("".join(blocks))
        inner = max(200, self.width() - 90)
        self.text.setFixedHeight(max(24, self.text.heightForWidth(inner)))
        # Grow upwards: the bottom edge stays where the user put the bar.
        bottom = self.geometry().bottom() if self.isVisible() else None
        self.adjustSize()
        if bottom is not None:
            self.move(self.x(), bottom - self.height() + 1)

    def place(self, saved=None):
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        width = min(1100, int(area.width() * 0.8))
        self.setFixedWidth(width)
        self.adjustSize()
        if saved and len(saved) == 2 and any(s.availableGeometry().contains(QPoint(*saved)) for s in QGuiApplication.screens()):
            self.move(int(saved[0]), int(saved[1]))
        else:
            self.move(area.center().x() - width // 2, area.bottom() - self.height() - 70)

    def reset_position(self):
        self.place(None)
        self.moved.emit(self.x(), self.y())
