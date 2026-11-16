"""Smart dictation: speak into any text field (0.4.1).

Flow: global shortcut → record the microphone → local Whisper → spoken
punctuation → optional cloud polish → type into the window that had focus.

``DICTATION_ACTIVE`` closes the command listener's capture gate while the
user dictates, so dictated words are never executed as Jarvis commands.
Audio never leaves the computer; only the optional "AI polish" sends the
recognized *text* to the cloud provider the user already configured.
"""
from __future__ import annotations

import ctypes
import re
import sys
import threading
import time

import numpy as np

DICTATION_ACTIVE = threading.Event()
MAX_SECONDS = 120
SAMPLE_RATE = 16000

# --- spoken punctuation -----------------------------------------------------

_MARKS = (
    # (phrases, symbol); longer phrases first inside each group.
    (("вопросительный знак", "знак вопроса", "semnul întrebării", "semn de întrebare", "semnul intrebarii",
      "semn de intrebare", "question mark"), "?"),
    (("восклицательный знак", "знак восклицания", "semnul exclamării", "semn de exclamare", "semnul exclamarii",
      "semn de exclamare", "exclamation mark", "exclamation point"), "!"),
    (("многоточие", "trei puncte", "ellipsis"), "…"),
    (("точка с запятой", "punct și virgulă", "punct si virgula", "semicolon"), ";"),
    (("двоеточие", "două puncte", "doua puncte", "colon"), ":"),
    (("запятая", "запятой", "запятую", "запитая", "virgulă", "virgula", "comma"), ","),
    (("точка", "punct", "period", "full stop"), "."),
    (("новый абзац", "с нового абзаца", "paragraf nou", "new paragraph"), "\n\n"),
    (("новая строка", "с новой строки", "rând nou", "rand nou", "new line", "newline"), "\n"),
    (("тире", "linie de dialog", "dash"), " —"),
    (("открыть скобку", "открой скобку", "deschide paranteza", "open bracket", "open parenthesis"), " ("),
    (("закрыть скобку", "закрой скобку", "închide paranteza", "inchide paranteza", "close bracket",
      "close parenthesis"), ")"),
    (("открыть кавычки", "открой кавычки", "deschide ghilimelele", "open quote"), " «"),
    (("закрыть кавычки", "закрой кавычки", "închide ghilimelele", "inchide ghilimelele", "close quote"), "»"),
)
_DELETE_WORD = re.compile(
    r"\s*(?:удали|удалить|сотри)\s+последнее\s+слово|\s*(?:șterge|sterge)\s+ultimul\s+cuv[âa]nt"
    r"|\s*delete\s+(?:the\s+)?last\s+word", re.IGNORECASE)
_QUOTES = re.compile(r"(?<!\w)(?:кавычки|ghilimele|quotes|quote)(?!\w)", re.IGNORECASE)
# Ordinary phrases that merely contain a mark word.
_PROTECT = re.compile(r"\b(точк[аи]\s+зрения|punct\s+de\s+vedere|точка\s+опоры)\b", re.I)
_SENTENCE_END = ".!?…"


def apply_spoken_punctuation(text: str) -> str:
    """Turn spoken mark names into symbols and tidy spacing/capitals.

    Whisper often adds its own commas around the spoken word ("Привет,
    запятая, как дела"); punctuation directly around a mark word is dropped.
    """
    value = " ".join(str(text or "").split())
    if not value:
        return ""
    protected = {}

    def protect(match):
        key = f"\x00{len(protected)}\x00"
        protected[key] = match.group(0)
        return key

    value = _PROTECT.sub(protect, value)
    # "удали последнее слово" removes the word spoken before it.
    while True:
        match = _DELETE_WORD.search(value)
        if not match:
            break
        before = re.sub(r"[\s,.;:!?…]*\S+[\s,.;:!?…]*$", "", value[:match.start()])
        after = value[match.end():].lstrip(" ,.;:")
        value = (before + " " + after).strip()
    # A lone "кавычки" alternates opening and closing quotes.
    opened = [False]

    def quote(match):
        opened[0] = not opened[0]
        return " открыть кавычки " if opened[0] else " закрыть кавычки "

    value = _QUOTES.sub(quote, value)
    phrases = sorted(((phrase, symbol) for group, symbol in _MARKS for phrase in group),
                     key=lambda item: -len(item[0]))
    for phrase, symbol in phrases:
        pattern = re.compile(r"[\s,.;:]*(?<!\w)" + re.escape(phrase).replace(r"\ ", r"\s+") + r"(?!\w)[\s,.;:]*",
                             re.IGNORECASE)
        placeholder = "\x01" + symbol + "\x02"
        value = pattern.sub(placeholder, value)
    if "\x01" not in value:
        for key, original in protected.items():
            value = value.replace(key, original)
        return value
    # Resolve placeholders and spacing.
    value = re.sub(r"\x01([^\x02]*)\x02", lambda m: m.group(1) + "\x03", value)
    value = value.replace("\x03", " ")
    value = re.sub(r"[ \t]+([,.;:!?…»)])", r"\1", value)
    # Whisper often adds its own mark right before the spoken one: keep one.
    value = re.sub(r"[,.;:!?…](?:[ \t]*[,.;:!?…])+", lambda m: m.group(0).replace(" ", "").replace("\t", "")[-1], value)
    value = re.sub(r"([«(])[ \t]+", r"\1", value)
    value = re.sub(r"[ \t]*\n[ \t]*", "\n", value)
    value = re.sub(r"([,.;:!?…])(?=[^\s\d,.;:!?…»)\n])", r"\1 ", value)
    value = re.sub(r"[ \t]{2,}", " ", value).strip(" ")
    value = _capitalize_sentences(value)
    for key, original in protected.items():
        value = value.replace(key, original)
    return value


def _capitalize_sentences(value: str) -> str:
    chars = list(value)
    capitalize = True
    for index, char in enumerate(chars):
        if char.isalpha():
            if capitalize:
                chars[index] = char.upper()
            capitalize = False
        elif char in _SENTENCE_END or char == "\n":
            capitalize = True
    return "".join(chars)


def resample(audio: np.ndarray, source_rate: int, target_rate: int = SAMPLE_RATE) -> np.ndarray:
    if source_rate == target_rate or not len(audio):
        return audio.astype(np.float32, copy=False)
    count = int(round(len(audio) * target_rate / source_rate))
    positions = np.linspace(0, len(audio), num=count, endpoint=False)
    return np.interp(positions, np.arange(len(audio)), audio).astype(np.float32)


# --- recording --------------------------------------------------------------

class Recorder:
    """Collect microphone audio until ``stop()``; at most MAX_SECONDS."""

    def __init__(self, cfg: dict, backend=None):
        import sounddevice as sd
        from luxai.audio_devices import resolve_microphone_device
        self.sd = backend or sd
        self.device, info = resolve_microphone_device(
            cfg.get("microphone_device", -1), cfg.get("microphone_name", ""),
            cfg.get("microphone_hostapi", ""), backend=self.sd)
        info = info or self.sd.query_devices(self.device, "input")
        self.rate = SAMPLE_RATE
        for rate in dict.fromkeys((SAMPLE_RATE, int(round(float(info.get("default_samplerate", 48000)))), 48000, 44100)):
            try:
                self.sd.check_input_settings(device=self.device, samplerate=rate, channels=1, dtype="float32")
                self.rate = rate
                break
            except Exception:
                continue
        self._chunks: list[np.ndarray] = []
        self._samples = 0
        self._lock = threading.Lock()
        self._stream = None
        self.level = 0.0
        self.noise = 0.0
        self.voiced_once = False
        self.last_voice = time.monotonic()

    def _callback(self, indata, frames, time_info, status):
        chunk = indata.copy().reshape(-1)
        with self._lock:
            if self._samples >= self.rate * MAX_SECONDS:
                return
            self._chunks.append(chunk)
            self._samples += len(chunk)
        if len(chunk):
            level = float(np.sqrt(np.mean(np.square(chunk, dtype=np.float64))))
            self.level = level
            threshold = max(0.004, self.noise * 3.0)
            if level >= threshold:
                self.voiced_once = True
                self.last_voice = time.monotonic()
            else:
                self.noise = level if self.noise == 0.0 else self.noise * 0.95 + level * 0.05

    def silent_for(self) -> float:
        return time.monotonic() - self.last_voice if self.voiced_once else 0.0

    def start(self):
        self._stream = self.sd.InputStream(device=self.device, samplerate=self.rate, channels=1,
                                           dtype="float32", blocksize=int(self.rate * 0.03),
                                           callback=self._callback)
        self._stream.start()

    @property
    def seconds(self) -> float:
        return self._samples / float(self.rate)

    @property
    def full(self) -> bool:
        return self._samples >= self.rate * MAX_SECONDS

    def stop(self) -> np.ndarray:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        with self._lock:
            audio = np.concatenate(self._chunks) if self._chunks else np.empty(0, dtype=np.float32)
            self._chunks = []
        return resample(audio, self.rate)


# --- transcription ----------------------------------------------------------

_model_lock = threading.Lock()
_own_model = {"path": None, "model": None}


def load_model(model_path: str):
    """Load (once) a private Whisper model when the listener has none."""
    with _model_lock:
        if _own_model["model"] is None or _own_model["path"] != model_path:
            from faster_whisper import WhisperModel
            import os
            _own_model["model"] = WhisperModel(model_path or "small", device="cpu", compute_type="int8",
                                               cpu_threads=max(2, min(6, os.cpu_count() or 4)), num_workers=1)
            _own_model["path"] = model_path
        return _own_model["model"]


def transcribe(model, audio: np.ndarray, language: str | None, beam_size: int = 1) -> str:
    from luxai.voice_rules import recognition_options, is_hallucinated_outro, is_repetitive_transcript
    if len(audio) < SAMPLE_RATE * 0.4:
        return ""
    peak = float(np.max(np.abs(audio)))
    if 0.0 < peak < 0.1:
        audio = (audio * min(16.0, 0.1 / peak)).astype(np.float32)
    options = recognition_options(language, beam_size)
    options["initial_prompt"] = None  # command vocabulary would bias free dictation
    segments, _info = model.transcribe(audio, **options)
    text = " ".join(segment.text.strip() for segment in segments).strip()
    if is_hallucinated_outro(text) or is_repetitive_transcript(text):
        return ""
    return text


# --- typing -----------------------------------------------------------------

def wait_for_modifiers_released(timeout: float = 1.5) -> None:
    """Typing while Ctrl/Alt are still held would trigger app shortcuts."""
    if sys.platform != "win32":
        return
    state = ctypes.windll.user32.GetAsyncKeyState
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(state(code) & 0x8000 for code in (0x10, 0x11, 0x12, 0x5B, 0x5C)):
            return
        time.sleep(0.03)


def type_text(text: str, *, typer=None, enter=None) -> None:
    """Type Unicode text with real Enter presses for line breaks."""
    if typer is None:
        from luxai.desktop_actions import _type_unicode_windows as typer
    if enter is None:
        def enter():
            user32 = ctypes.windll.user32
            user32.keybd_event(0x0D, 0, 0, 0)
            user32.keybd_event(0x0D, 0, 0x0002, 0)
    lines = str(text).split("\n")
    for index, line in enumerate(lines):
        if index:
            enter()
        for start in range(0, len(line), 150):
            piece = line[start:start + 150]
            if piece:
                typer(piece)
                time.sleep(0.01)


def right_ctrl_down() -> bool:
    return sys.platform == "win32" and bool(ctypes.windll.user32.GetAsyncKeyState(0xA3) & 0x8000)


class DoubleTapDetector:
    """Detect a quick double press of one key by polling (no keyboard hooks).

    ``update(down, now)`` returns "double" on the second press, "release"
    when the key goes up after a double press, otherwise "".
    """

    def __init__(self, window: float = 0.4):
        self.window = window
        self.was_down = False
        self.last_press = -10.0
        self.armed = False
        self.holding = False

    def update(self, down: bool, now: float) -> str:
        event = ""
        if down and not self.was_down:
            if self.armed and now - self.last_press <= self.window:
                self.armed = False
                self.holding = True
                event = "double"
            else:
                self.armed = True
                self.last_press = now
        elif not down and self.was_down and self.holding:
            self.holding = False
            event = "release"
        if self.armed and now - self.last_press > self.window:
            self.armed = False
        self.was_down = down
        return event


_WAKE = ("jarvis", "джарвис", "жарвис", "джервис", "жервис", "жарис", "джарис")


def voice_dictation_request(text: str, phrases: str, wake: str = "") -> str | None:
    """Return the text to type ("" = record until pause) or None if no match."""
    value = " ".join(str(text or "").split())
    names = [name.strip() for name in str(wake or "").split(",") if name.strip()] + list(_WAKE)
    pattern_names = "|".join(re.escape(name) for name in sorted(set(names), key=len, reverse=True))
    value = re.sub(r"^(?:" + pattern_names + r")(?=$|[\s,.:;!?—–-])[\s,.:;!?—–-]*", "", value, flags=re.IGNORECASE)
    for phrase in [item.strip() for item in str(phrases or "").split(",") if item.strip()][:12]:
        match = re.match(re.escape(phrase).replace(r"\ ", r"\s+") + r"(?=$|[\s,.:;!?—–-])[\s,.:;!?—–-]*",
                         value, flags=re.IGNORECASE)
        if match:
            return value[match.end():].strip()
    return None


def key_held(hotkey: str) -> bool:
    """True while every part of a normalized shortcut is physically held."""
    if sys.platform != "win32" or not hotkey:
        return False
    state = ctypes.windll.user32.GetAsyncKeyState
    parts = hotkey.split("+")
    codes = {"ctrl": (0x11,), "alt": (0x12,), "shift": (0x10,), "win": (0x5B, 0x5C)}
    for part in parts[:-1]:
        if not any(state(code) & 0x8000 for code in codes[part]):
            return False
    key = parts[-1]
    code = 0x6F + int(key[1:]) if key.startswith("f") and len(key) > 1 else ord(key.upper())
    return bool(state(code) & 0x8000)
