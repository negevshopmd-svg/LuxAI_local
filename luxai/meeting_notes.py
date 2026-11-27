"""Video and call notes (0.4.4b): record PC sound + microphone, transcribe as it goes, then write notes.

No Qt here (the runtime adds the window and buttons):

- ``TrackWriter`` writes one source (the PC sound or the microphone) as 16 kHz mono 16-bit PCM straight to
  disk, on a wall-clock timeline: Windows sends no loopback packets while nothing plays, so the silence is
  filled in and both tracks stay in step. Hours of recording never sit in memory, and a crash leaves usable
  audio (the reader trusts the file size, not the header).
- ``Transcriber`` (its own thread) reads finished pieces of ~30 s, cut in the quietest moment near the end so
  no word is split, skips silence, and writes each phrase with its time and speaker («Me» = microphone,
  «Others» = PC sound) to ``transcript.txt`` as it goes.
- ``summarize`` turns the transcript into notes — short summary, topics, decisions, tasks, open questions —
  with the cloud AI or the local model, piece by piece for long meetings; ``notes_markdown`` writes the file.

Everything stays on this PC unless the user chose the cloud AI for the summary.
"""
from __future__ import annotations

import datetime as _dt
import difflib
import json
import re
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

RATE = 16_000
WINDOW_SECONDS = 30.0
MIN_CUT_SECONDS = 20.0          # a piece is cut in the quietest 0.1 s between 20 and 30 s
FRAME = RATE // 10
SPEAKERS = {"mic": ("Я", "Me", "Eu"), "system": ("Собеседники", "Others", "Ceilalți")}
LANG_INDEX = {"ru": 0, "en": 1, "ro": 2}
MAX_HOURS = 6
SUMMARY_CHUNK = 5500            # characters of transcript per AI request


# --- writing the audio ------------------------------------------------------------------------------

def _wav_header(samples: int) -> bytes:
    data = samples * 2
    return (b"RIFF" + struct.pack("<I", 36 + data) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, RATE, RATE * 2, 2, 16)
            + b"data" + struct.pack("<I", data))


class TrackWriter:
    """One source → ``<name>.wav`` (header fixed at close; readers use the file size)."""

    def __init__(self, path: Path, started: float, clock=time.monotonic):
        self.path = Path(path)
        self.started = started
        self.clock = clock
        self.samples = 0
        self._lock = threading.Lock()
        self._file = open(self.path, "wb")
        self._file.write(_wav_header(0))
        self.paused_at = 0.0
        self.paused_total = 0.0
        self.last_level = 0.0

    def write(self, chunk: np.ndarray):
        """A float32 16 kHz mono chunk; silence is added first when the source was quiet (no packets)."""
        if self.paused_at:
            return
        chunk = np.asarray(chunk, dtype=np.float32).reshape(-1)
        with self._lock:
            if self._file.closed or self.samples >= RATE * 3600 * MAX_HOURS:
                return
            expected_end = int((self.clock() - self.started - self.paused_total) * RATE)
            gap = expected_end - len(chunk) - self.samples
            if gap > RATE // 2:  # more than half a second missing: the source was silent
                self._file.write(np.zeros(min(gap, RATE * 600), dtype=np.int16).tobytes())
                self.samples += min(gap, RATE * 600)
            if len(chunk):
                self.last_level = float(np.sqrt(np.mean(np.square(chunk))))
            pcm = (np.clip(chunk, -1.0, 1.0) * 32767).astype(np.int16)
            self._file.write(pcm.tobytes())
            self._file.flush()
            self.samples += len(pcm)

    def pause(self):
        self.paused_at = self.clock()

    def resume(self):
        if self.paused_at:
            self.paused_total += self.clock() - self.paused_at
            self.paused_at = 0.0

    def close(self):
        with self._lock:
            if self._file.closed:
                return
            self._file.seek(0)
            self._file.write(_wav_header(self.samples))
            self._file.close()


def read_samples(path: Path, start: int, count: int) -> np.ndarray:
    """``count`` samples from ``start`` (float32), whatever the header says (it is fixed only at the end)."""
    try:
        with open(path, "rb") as handle:
            handle.seek(44 + start * 2)
            data = handle.read(max(0, count) * 2)
    except OSError:
        return np.empty(0, dtype=np.float32)
    usable = len(data) // 2 * 2
    return np.frombuffer(data[:usable], dtype=np.int16).astype(np.float32) / 32768.0


def available_samples(path: Path) -> int:
    try:
        return max(0, (Path(path).stat().st_size - 44) // 2)
    except OSError:
        return 0


# --- cutting and filtering ------------------------------------------------------------------------

def cut_point(audio: np.ndarray, final: bool) -> int:
    """Where this piece ends: all of it when the recording stopped, else the quietest 0.1 s after 20 s."""
    if final or len(audio) <= MIN_CUT_SECONDS * RATE:
        return len(audio)
    first = int(MIN_CUT_SECONDS * RATE) // FRAME
    frames = len(audio) // FRAME
    if frames <= first:
        return len(audio)
    energy = [float(np.mean(np.square(audio[i * FRAME:(i + 1) * FRAME]))) for i in range(first, frames)]
    quietest = first + int(np.argmin(energy))
    return (quietest + 1) * FRAME


def voiced(audio: np.ndarray) -> bool:
    """Anything worth transcribing: at least ~0.3 s of real sound. Pure silence (nothing played, a muted mic)
    is skipped to save the CPU; noise and music are left to Whisper's own voice filter and confidence checks —
    a threshold relative to the noise floor would skip a piece of speech without pauses."""
    if len(audio) < FRAME:
        return False
    frames = audio[: len(audio) // FRAME * FRAME].reshape(-1, FRAME)
    rms = np.sqrt(np.mean(np.square(frames), axis=1))
    return int(np.sum(rms > 0.008)) >= 3


_INVENTED = re.compile(r"(?:субтитр\w* (?:сделал|делал|создавал)|dimatorzok|редактор субтитров|продолжение следует|"
                       r"thanks? for watching|please subscribe|подпиш\w+ на канал|amara\.org|субтитры (?:by|от))", re.I)


def invented(text: str) -> bool:
    """Whisper's well-known inventions on silence and music."""
    return bool(_INVENTED.search(text)) or not re.search(r"\w", text)


@dataclass
class Line:
    start: float   # seconds from the beginning of the recording
    end: float
    source: str    # mic | system
    text: str


def sentence_lines(start: float, end: float, source: str, text: str) -> list[Line]:
    """A long Whisper segment (it can hold half a minute of speech) as one line per sentence, each with its own
    time, shared out by the length of the sentences."""
    from luxai.live_captions import split_sentences
    parts = split_sentences(text) if len(text) > 160 else [text]
    if len(parts) <= 1:
        return [Line(start, end, source, text)]
    total = sum(len(part) for part in parts)
    lines, moment = [], start
    for part in parts:
        length = (end - start) * len(part) / total
        lines.append(Line(moment, moment + length, source, part))
        moment += length
    return lines


def drop_echo(lines: list[Line]) -> list[Line]:
    """Without headphones the microphone hears the speakers too: a «Me» line that repeats an «Others» line at the
    same time is that echo, not something you said."""
    others = [line for line in lines if line.source == "system"]
    kept = []
    for line in lines:
        if line.source == "mic":
            twin = any(abs(other.start - line.start) < 6 and
                       difflib.SequenceMatcher(None, other.text.casefold(), line.text.casefold()).ratio() > 0.6
                       for other in others)
            if twin:
                continue
        kept.append(line)
    return kept


def stamp(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    return f"{hours:02d}:{rest // 60:02d}:{rest % 60:02d}"


def transcript_text(lines: list[Line], language: str, two_sources: bool) -> str:
    index = LANG_INDEX.get(language, 0)
    rows = []
    for line in sorted(lines, key=lambda item: item.start):
        who = f"{SPEAKERS[line.source][index]}: " if two_sources else ""
        rows.append(f"[{stamp(line.start)}] {who}{line.text}")
    return "\n".join(rows)


# --- transcribing as it goes --------------------------------------------------------------------------

class Transcriber:
    """Reads the tracks while they grow and transcribes finished pieces; ``finish()`` does the rest."""

    def __init__(self, folder: Path, sources: list[str], model_provider, language: str | None, on_line=None,
                 beam_size: int = 2):
        self.folder = Path(folder)
        self.sources = list(sources)
        self.model_provider = model_provider
        self.language = language
        self.on_line = on_line
        self.beam_size = beam_size
        self.done = {source: 0 for source in sources}   # samples already transcribed
        self.lines: list[Line] = []
        self.context = {source: "" for source in sources}
        self.errors: list[str] = []
        self._stop = threading.Event()
        self._final = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="JarvisMeetingTranscribe")
        self._thread.start()
        return self

    def _run(self):
        while not self._stop.is_set():
            worked = self.step(final=self._final.is_set())
            if self._final.is_set() and not worked:
                break
            if not worked:
                self._stop.wait(2.0)

    def finish(self, timeout: float | None = None) -> bool:
        """Transcribe what is left (the end of the recording) and stop. True when everything was read."""
        self._final.set()
        if self._thread is not None:
            self._thread.join(timeout)
            return not self._thread.is_alive()
        while self.step(final=True):
            pass
        return True

    def cancel(self):
        self._stop.set()

    def pending_seconds(self) -> float:
        return max((available_samples(self.folder / f"{s}.wav") - self.done[s]) / RATE for s in self.sources)

    def step(self, final: bool = False) -> bool:
        """One piece of the source that is most behind. False when nothing was ready."""
        for source in sorted(self.sources, key=lambda s: self.done[s]):
            path = self.folder / f"{source}.wav"
            ready = available_samples(path) - self.done[source]
            if ready <= 0 or (not final and ready < WINDOW_SECONDS * RATE):
                continue
            audio = read_samples(path, self.done[source], min(ready, int(WINDOW_SECONDS * RATE)))
            if not len(audio):
                continue
            end = cut_point(audio, final and ready <= WINDOW_SECONDS * RATE)
            piece, offset = audio[:end], self.done[source] / RATE
            self.done[source] += end
            if voiced(piece):
                self._transcribe(piece, offset, source)
            return True
        return False

    def _transcribe(self, audio: np.ndarray, offset: float, source: str):
        try:
            model = self.model_provider()
            from luxai.live_captions import level_up, trustworthy
            segments, _info = model.transcribe(
                level_up(audio), language=self.language, beam_size=self.beam_size, vad_filter=True,
                condition_on_previous_text=False, initial_prompt=self.context[source][-200:] or None,
                no_speech_threshold=0.6, log_prob_threshold=-1.0, compression_ratio_threshold=2.4)
            for segment in segments:
                text = " ".join(str(segment.text or "").split())
                if not text or invented(text) or not trustworthy(segment):
                    continue
                self.context[source] = (self.context[source] + " " + text)[-400:]
                for line in sentence_lines(offset + float(segment.start), offset + float(segment.end), source, text):
                    with self._lock:
                        self.lines.append(line)
                    self._save_line(line)
                    if self.on_line is not None:
                        self.on_line(line)
        except Exception as error:  # one bad piece must not stop the notes
            self.errors.append(type(error).__name__)

    def _save_line(self, line: Line):
        try:
            with open(self.folder / "transcript.jsonl", "a", encoding="utf-8") as handle:
                handle.write(json.dumps(line.__dict__, ensure_ascii=False) + "\n")
        except OSError:
            pass


def load_lines(folder: Path) -> list[Line]:
    """The transcript written so far (also after a crash)."""
    lines = []
    try:
        for row in (Path(folder) / "transcript.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                data = json.loads(row)
                lines.append(Line(float(data["start"]), float(data["end"]), str(data["source"]), str(data["text"])))
            except (ValueError, KeyError, TypeError):
                continue
    except OSError:
        pass
    return lines


# --- the notes ---------------------------------------------------------------------------------------

HEADINGS = {
    "summary": ("Коротко", "In short", "Pe scurt"),
    "topics": ("Темы", "Topics", "Teme"),
    "decisions": ("Решения", "Decisions", "Decizii"),
    "tasks": ("Задачи", "Tasks", "Sarcini"),
    "questions": ("Открытые вопросы", "Open questions", "Întrebări deschise"),
    "transcript": ("Расшифровка", "Transcript", "Transcriere"),
    "title": ("Конспект", "Notes", "Rezumat"),
    "duration": ("Длительность", "Duration", "Durată"),
    "sources": ("Источники", "Sources", "Surse"),
    "made_by": ("Конспект составил", "Notes by", "Rezumat făcut de"),
    "no_ai": ("Нейросеть не подключена — ниже только расшифровка. Подключите облачный ИИ или локальную модель в "
              "настройках Jarvis, и конспект будет составляться сам.",
              "No AI is connected — below is only the transcript. Connect a cloud AI or a local model in Jarvis' "
              "settings and the notes will be written by themselves.",
              "Nu e conectat niciun AI — mai jos e doar transcrierea. Conectează un AI în cloud sau un model local în "
              "setările Jarvis și rezumatul se va face singur."),
    "nothing": ("В записи не распознано ни одной фразы.", "No speech was recognised in the recording.",
                "În înregistrare nu s-a recunoscut nicio frază."),
    "none": ("—", "—", "—"),
}
LANGUAGE_NAMES = {"ru": "Russian", "en": "English", "ro": "Romanian"}


def heading(key: str, language: str) -> str:
    return HEADINGS[key][LANG_INDEX.get(language, 0)]


def _task(language: str, partial: bool) -> str:
    name = LANGUAGE_NAMES.get(language, "the language of the transcript")
    scope = ("This is one part of a longer meeting; note only what is in this part." if partial else "")
    return ("You write meeting notes from a transcript (times in brackets, speakers before the colon; «Me» is the "
            "user). " + scope + " Write in " + name + ". Answer ONLY with JSON: "
            '{"summary": "2-4 sentences", "topics": ["..."], "decisions": ["..."], '
            '"tasks": [{"who": "", "what": "", "when": ""}], "questions": ["..."]}. '
            "Use only what was really said; leave a list empty when there is nothing. Keep each item short.")


def _merge_task(language: str) -> str:
    name = LANGUAGE_NAMES.get(language, "the same language")
    return ("You receive notes of the consecutive parts of ONE meeting as JSON objects. Merge them into one set "
            "of notes: remove repeats, keep every decision and task. Write in " + name + ". Answer ONLY with the "
            'same JSON shape: {"summary": "3-5 sentences", "topics": [], "decisions": [], '
            '"tasks": [{"who": "", "what": "", "when": ""}], "questions": []}.')


def parse_notes(answer: str) -> dict | None:
    """The JSON the AI answered (also inside ```json fences or with text around it), cleaned; None if unusable."""
    if not answer:
        return None
    text = str(answer)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None

    def strings(value):
        return [" ".join(str(item).split())[:300] for item in (value if isinstance(value, list) else [])
                if isinstance(item, (str, int, float)) and str(item).strip()][:40]

    tasks = []
    for item in data.get("tasks") if isinstance(data.get("tasks"), list) else []:
        if isinstance(item, dict) and str(item.get("what") or "").strip():
            tasks.append({key: " ".join(str(item.get(key) or "").split())[:200] for key in ("who", "what", "when")})
        elif isinstance(item, str) and item.strip():
            tasks.append({"who": "", "what": item.strip()[:200], "when": ""})
    notes = {"summary": " ".join(str(data.get("summary") or "").split())[:2000], "topics": strings(data.get("topics")),
             "decisions": strings(data.get("decisions")), "tasks": tasks[:40], "questions": strings(data.get("questions"))}
    return notes if notes["summary"] or any(notes[key] for key in ("topics", "decisions", "tasks", "questions")) else None


def split_transcript(text: str, size: int = SUMMARY_CHUNK) -> list[str]:
    """Pieces of whole lines, each at most ``size`` characters."""
    pieces, current = [], ""
    for row in text.splitlines():
        if current and len(current) + len(row) + 1 > size:
            pieces.append(current)
            current = ""
        current = (current + "\n" + row).strip("\n") if current else row[:size]
    if current:
        pieces.append(current)
    return pieces


def summarize(transcript: str, language: str, ask) -> tuple[dict | None, str]:
    """Notes from the transcript. ``ask(text, task) -> answer | None`` is the AI. Returns (notes, error code)."""
    if not transcript.strip():
        return None, "empty"
    pieces = split_transcript(transcript)
    parts = []
    for piece in pieces:
        notes = parse_notes(ask(piece, _task(language, len(pieces) > 1)) or "")
        if notes is not None:
            parts.append(notes)
    if not parts:
        return None, "no_answer"
    if len(parts) == 1:
        return parts[0], ""
    joined = json.dumps(parts, ensure_ascii=False)
    merged = parse_notes(ask(joined, _merge_task(language)) or "") if len(joined) <= 5900 else None
    if merged is not None:
        return merged, ""
    combined = {"summary": " ".join(part["summary"] for part in parts)[:2000],
                "topics": [], "decisions": [], "tasks": [], "questions": []}
    for part in parts:  # the AI could not merge: the parts one after another, nothing lost
        for key in ("topics", "decisions", "tasks", "questions"):
            combined[key].extend(part[key])
    return combined, ""


def notes_markdown(notes: dict | None, transcript: str, *, language: str, started: _dt.datetime, seconds: float,
                   sources: list[str], made_by: str = "", include_transcript: bool = True) -> str:
    h = lambda key: heading(key, language)  # noqa: E731
    index = LANG_INDEX.get(language, 0)
    source_names = {"mic": ("микрофон", "microphone", "microfon"), "system": ("звук компьютера", "PC sound", "sunetul PC")}
    rows = [f"# {h('title')} — {started.strftime('%d.%m.%Y %H:%M')}", "",
            f"**{h('duration')}:** {stamp(seconds)} · **{h('sources')}:** "
            + ", ".join(source_names[s][index] for s in sources), ""]
    if notes is None:
        rows += [f"> {h('no_ai') if transcript.strip() else h('nothing')}", ""]
    else:
        rows += [f"## {h('summary')}", "", notes["summary"] or h("none"), ""]
        for key in ("topics", "decisions", "questions"):
            rows += [f"## {h(key)}", ""] + ([f"- {item}" for item in notes[key]] or [h("none")]) + [""]
        rows += [f"## {h('tasks')}", ""]
        if notes["tasks"]:
            for task in notes["tasks"]:
                extra = " · ".join(part for part in (task.get("who"), task.get("when")) if part)
                rows.append(f"- [ ] {task['what']}" + (f" ({extra})" if extra else ""))
        else:
            rows.append(h("none"))
        rows.append("")
        if made_by:
            rows += [f"_{h('made_by')}: {made_by}_", ""]
    if include_transcript and transcript.strip():
        rows += [f"## {h('transcript')}", "", "```text", transcript, "```", ""]
    return "\n".join(rows)


def notes_folder(configured: str, language: str) -> Path:
    if configured:
        return Path(configured)
    name = {"ru": "Конспекты", "en": "Notes", "ro": "Rezumate"}.get(language, "Notes")
    return Path.home() / "Documents" / "Jarvis" / name


def safe_name(started: _dt.datetime, language: str) -> str:
    return f"{heading('title', language)} {started.strftime('%Y-%m-%d %H-%M')}.md"
