"""Live captions: turn what the PC plays into text on an always-on-top bar.

Audio comes from ``loopback_audio`` (all PC sound, or one program). The
recogniser re-reads the current phrase as often as the model allows (partial
text grows while someone speaks) and finishes it after a short pause or at
most 5 seconds — cut at the quietest moment, so continuous speech in videos
keeps flowing. A fast model of its own keeps it live. Finished phrases can be
translated by the cloud AI. Audio is never saved or sent.
"""
from __future__ import annotations

import os
import threading

import numpy as np

SAMPLE_RATE = 16000
FRAME = 480                 # 30 ms
PAUSE_SECONDS = 0.45        # quiet this long after speech = the phrase is finished
MAX_PHRASE_SECONDS = 5.0    # continuous speech is cut into short phrases
CUT_SEARCH_SECONDS = 1.5    # look for the quietest moment in the last 1.5 s
MIN_PARTIAL_GROWTH = 0.25   # re-read only when at least this much new audio came
KEEP_FINAL = 12
REDETECT_SECONDS = 30.0     # re-check the spoken language after this much speech


_FILLERS = frozenset({"you", "you.", "thank you.", "thanks.", "bye.", "спасибо.", "мне.", "и", "а", "ну"})


def lone_filler(text: str) -> bool:
    """A single word Whisper writes for a pause or a breath («you», «Спасибо.»)."""
    return text.strip().casefold() in _FILLERS


def trustworthy(segment) -> bool:
    """Whisper's own confidence: drop invented words (silence, music, noise)."""
    no_speech = getattr(segment, "no_speech_prob", 0.0)
    logprob = getattr(segment, "avg_logprob", 0.0)
    ratio = getattr(segment, "compression_ratio", 1.0)
    if no_speech > 0.6 and logprob < -0.7:
        return False
    return logprob > -1.25 and ratio < 2.4

# quality setting -> faster-whisper model ("precise" = the voice-command model)
QUALITY_MODELS = {"fast": "tiny", "balanced": "small"}
_models: dict = {}
_models_lock = threading.Lock()


def caption_model(name: str):
    """A captions-only model, loaded once (int8 on the CPU)."""
    with _models_lock:
        if name not in _models:
            from faster_whisper import WhisperModel
            _models[name] = WhisperModel(name, device="cpu", compute_type="int8",
                                         cpu_threads=max(2, min(8, (os.cpu_count() or 4) // 2)), num_workers=1)
        return _models[name]


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

    @property
    def paused(self) -> bool:
        return self.heard_speech and self.quiet_frames * FRAME / SAMPLE_RATE >= PAUSE_SECONDS

    def phrase_finished(self) -> bool:
        if not self.heard_speech:
            return False
        return self.paused or self.seconds >= MAX_PHRASE_SECONDS

    def cut_point(self) -> int:
        """Sample index after the quietest 30 ms frame in the last 1.5 s (between words)."""
        rms = frame_rms(self.buffer)
        if not len(rms):
            return len(self.buffer)
        first = max(1, len(rms) - int(CUT_SEARCH_SECONDS * SAMPLE_RATE / FRAME))
        quietest = first + int(np.argmin(rms[first:]))
        return (quietest + 1) * FRAME

    def take(self, until: int | None = None) -> np.ndarray:
        """The phrase audio; with ``until`` the rest stays for the next phrase."""
        if until is None or until >= len(self.buffer):
            audio, self.buffer = self.buffer, np.zeros(0, dtype=np.float32)
            self.heard_speech = False
            self.quiet_frames = 0
            return audio
        audio, self.buffer = self.buffer[:until], self.buffer[until:]
        rms = frame_rms(self.buffer)
        self.heard_speech = bool(len(rms) and (rms >= self.threshold).any())
        quiet = 0
        for value in rms[::-1]:
            if value >= self.threshold:
                break
            quiet += 1
        self.quiet_frames = quiet
        return audio


class CaptionEngine:
    """Recognition thread. Callbacks run on that thread — re-emit them as Qt signals."""

    def __init__(self, model_provider, language, on_partial, on_final, on_error=None):
        self.model_provider = model_provider
        self.language = language          # None = detect the spoken language
        self.detected = None              # sticky detected language
        self._speech_since_detect = 0.0
        self._votes: dict[str, float] = {}  # language -> summed probability of the recent checks
        self._confident = False
        self._prompt = ""                 # end of the previous phrase: context for the next one
        self._last_final = ""
        self.on_partial = on_partial
        self.on_final = on_final
        self.on_error = on_error
        self.segmenter = PhraseSegmenter()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._partial_len = 0
        self._partial_text = ""

    def feed(self, audio: np.ndarray) -> None:
        with self._lock:
            self.segmenter.feed(audio)

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="JarvisCaptions")
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def _spoken_language(self, model, audio):
        """The language to decode with: fixed, or voted over several checks, then re-checked every ~30 s.

        One check on a short or noisy piece can be wrong (a Romanian video once
        locked as Russian for 30 s), so checks repeat on every pass until the
        summed probabilities clearly agree; after that only every ~30 s.
        """
        if self.language:
            return self.language
        due = not self._confident or self._speech_since_detect >= REDETECT_SECONDS
        if due and len(audio) >= SAMPLE_RATE * 1.5 and hasattr(model, "detect_language"):
            try:
                language, probability, ranked = model.detect_language(audio)
                self._vote(language, probability, ranked)
                self._speech_since_detect = 0.0
            except Exception:
                pass
        return self.detected

    def _vote(self, language: str, probability: float, ranked) -> None:
        if self._confident:  # a re-check: older votes count half
            self._votes = {code: value * 0.5 for code, value in self._votes.items()}
        candidates = list(ranked or [])[:3] or [(language, probability)]
        for code, value in candidates:
            self._votes[code] = self._votes.get(code, 0.0) + float(value)
        ordered = sorted(self._votes.items(), key=lambda item: item[1], reverse=True)
        top, score = ordered[0]
        second = ordered[1][1] if len(ordered) > 1 else 0.0
        self.detected = top
        self._confident = score >= 1.5 and score - second >= 0.8

    def _transcribe(self, model, audio, final: bool = False) -> str:
        from luxai.dictation import voiced_seconds
        from luxai.voice_rules import is_hallucinated_outro, is_repetitive_transcript
        if len(audio) < SAMPLE_RATE * 0.3 or voiced_seconds(audio) < 0.2:
            return ""
        peak = float(np.max(np.abs(audio)))
        if 0.0 < peak < 0.1:
            audio = (audio * min(16.0, 0.1 / peak)).astype(np.float32)
        language = self._spoken_language(model, audio)
        segments, _info = model.transcribe(
            audio, language=language, beam_size=1, best_of=1, temperature=0.0,
            # Silero VAD drops music/noise, where Whisper invents words.
            vad_filter=True, vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 200},
            condition_on_previous_text=False, without_timestamps=True,
            no_speech_threshold=0.6, log_prob_threshold=-1.0, compression_ratio_threshold=2.4,
            initial_prompt=(self._prompt or None) if final else None)
        kept = [segment.text.strip() for segment in segments if trustworthy(segment)]
        text = " ".join(part for part in kept if part).strip()
        if is_hallucinated_outro(text) or is_repetitive_transcript(text) or lone_filler(text):
            return ""
        return text

    def step(self, model) -> bool:
        """One pass: finish a phrase or refresh the growing partial text. True = did work."""
        with self._lock:
            segmenter = self.segmenter
            finished = segmenter.phrase_finished()
            if finished:
                audio = segmenter.take() if segmenter.paused else segmenter.take(segmenter.cut_point())
            else:
                audio = segmenter.buffer.copy()
            speaking = segmenter.heard_speech
        if finished:
            # The last partial already read (almost) this audio: no second pass.
            extra = frame_rms(audio[self._partial_len:]) if self._partial_len <= len(audio) else None
            only_quiet_added = extra is not None and (not len(extra) or float(extra.max()) < self.segmenter.threshold)
            if self._partial_text and self._partial_len <= len(audio) and (
                    only_quiet_added or len(audio) - self._partial_len <= SAMPLE_RATE * MIN_PARTIAL_GROWTH):
                text = self._partial_text
            else:
                text = self._transcribe(model, audio, final=True)
            self._partial_len, self._partial_text = 0, ""
            self._speech_since_detect += len(audio) / SAMPLE_RATE
            self.on_partial("")
            if text and text.casefold() != self._last_final.casefold():  # no doubled lines
                self._last_final = text
                self._prompt = text[-160:]
                self.on_final(text)
            return True
        if speaking and len(audio) >= SAMPLE_RATE * 0.5 \
                and len(audio) - self._partial_len >= SAMPLE_RATE * MIN_PARTIAL_GROWTH:
            text = self._transcribe(model, audio)
            self._partial_len = len(audio)
            if text:
                self._partial_text = text
                self.on_partial(text)
            return True
        return False

    def _run(self):
        model = None
        while not self._stop.is_set():
            try:
                if model is None:
                    model = self.model_provider()
                    if model is None:
                        raise RuntimeError("speech model is not loaded")
                if not self.step(model):
                    self._stop.wait(0.05)
            except Exception as error:
                if self.on_error is not None:
                    self.on_error(f"{type(error).__name__}: {error}")
                self._stop.wait(3)


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


PENDING = "\u2026pending"


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

    def add_final(self, original: str, translation: str = "", pending: bool = False):
        """``pending``: a translation is coming; with «only translation» the
        original is never shown, a «…» waits instead."""
        if pending and not translation:
            translation = PENDING
        self.lines.append((original, translation))
        self.lines = self.lines[-KEEP_FINAL:]
        self.render()

    def set_translation(self, original: str, translation: str):
        """``translation`` "" = it failed or came too late: the original is shown instead."""
        for index in range(len(self.lines) - 1, -1, -1):
            if self.lines[index][0] == original and self.lines[index][1] in ("", PENDING):
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
            if translation == PENDING:
                if self.show_original:
                    translation = ""  # the original shows now, the translation will follow
                else:
                    blocks.append(f"<div style='margin:0; font-size:{small}px; color:rgba(255,255,255,0.5);'>…</div>")
                    continue
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
