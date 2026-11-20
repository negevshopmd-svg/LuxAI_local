"""Film captions in advance (0.4.2z): subtitles for a video playing in the browser, prepared BEFORE it is heard.

Live captions only hear what the speakers play right now. A film in the browser is usually loaded minutes
ahead, so the small Chrome extension in ``browser_extension/`` tells Jarvis two things:

* which media the page plays (the HLS playlist ``.m3u8`` or the ``.mp4``/``.webm`` file it requested), and
* where the player is (current time, paused, speed) — every second and on play/pause/seek.

Jarvis then opens the same media with FFmpeg (PyAV), decodes the audio AHEAD of the player in 30 s pieces,
recognises it with the precise Whisper model, translates every line offline and shows each line exactly at
its time in the film. A seek jumps the work to the new place; what was already prepared is kept.

Limits: media protected with DRM (Netflix, Disney+, Prime Video…) is encrypted and is not touched; a page
whose media needs browser cookies may refuse FFmpeg — then the normal live captions are used.
The local bridge listens on 127.0.0.1 only and accepts requests only from a browser extension.
"""
from __future__ import annotations

import bisect
import json
import re
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import numpy as np

PORT = 47321
AHEAD_SECONDS = 600.0      # prepare up to 10 minutes in front of the player
CHUNK_SECONDS = 30.0       # one Whisper pass (its natural window)
FIRST_CHUNK_SECONDS = 10.0  # where nothing is prepared yet (start, a seek): the first lines come sooner
CATCH_UP_SECONDS = 20.0    # closer than this to the player, the fast model works (it must get ahead first)
EDGE_SECONDS = 1.5         # a line ending this close to a piece's end is redone with the next piece
MAX_BODY = 64 * 1024
MAX_URLS = 20
STALE_SECONDS = 4.0        # no report from the browser for this long → the film mode pauses
MEDIA_EXTENSIONS = (".m3u8", ".mp4", ".webm", ".m4v", ".mov", ".mkv")
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0 Safari/537.36")


# -- the player's clock --------------------------------------------------------------------------------
class PlayerClock:
    """Where the browser's player is now, extrapolated between reports."""

    def __init__(self):
        self._lock = threading.Lock()
        self.time = 0.0
        self.paused = True
        self.rate = 1.0
        self.duration = 0.0
        self.reported = 0.0  # time.monotonic() of the last report, 0 = never

    def update(self, position: float, paused: bool, rate: float = 1.0, duration: float = 0.0, now=None):
        with self._lock:
            self.time = max(0.0, float(position))
            self.paused = bool(paused)
            self.rate = min(4.0, max(0.1, float(rate or 1.0)))
            self.duration = max(0.0, float(duration or 0.0))
            self.reported = time.monotonic() if now is None else now

    def position(self, now=None) -> float:
        with self._lock:
            if self.paused or not self.reported:
                return self.time
            now = time.monotonic() if now is None else now
            return self.time + max(0.0, now - self.reported) * self.rate

    def alive(self, now=None) -> bool:
        now = time.monotonic() if now is None else now
        return bool(self.reported) and now - self.reported <= STALE_SECONDS


# -- prepared lines ------------------------------------------------------------------------------------
@dataclass
class Cue:
    start: float
    end: float
    text: str
    translation: str = ""
    # (film time the word starts, characters of ``text`` shown once it is spoken), in order
    words: tuple = ()

    def shown(self, position: float) -> tuple[int, int]:
        """(characters of the text, characters of the translation) heard by ``position``.

        Words appear as they are spoken; the translation follows the same share of the line (its word
        order differs, so it is revealed by proportion, at word boundaries)."""
        if position >= self.end or not self.words:
            return len(self.text), len(self.translation)
        spoken = 0
        for moment, characters in self.words:
            if moment <= position:
                spoken = characters
            else:
                break
        if not spoken:
            return 0, 0
        return spoken, cut_at_word(self.translation, spoken / max(1, len(self.text)))


def cut_at_word(text: str, share: float) -> int:
    """Characters of ``text`` covering ``share`` of its words (whole words only)."""
    if share >= 1.0 or not text:
        return len(text)
    ends = [match.end() for match in re.finditer(r"\S+", text)]
    if not ends:
        return len(text)
    count = max(1, round(len(ends) * share))
    return ends[min(count, len(ends)) - 1]


def word_marks(words, begin: float, text: str) -> tuple:
    """Whisper's words → (start in film time, characters of the stripped line text up to that word)."""
    marks = []
    joined = ""
    lead = None
    for word in words:
        joined += str(getattr(word, "word", ""))
        if lead is None:
            lead = len(joined) - len(joined.lstrip())
        marks.append((begin + float(word.start), min(len(text), max(0, len(joined.rstrip()) - (lead or 0)))))
    return tuple(marks)


class CueTimeline:
    """Recognised lines in film time, plus the stretches of the film already prepared."""

    def __init__(self):
        self._lock = threading.Lock()
        self.cues: list[Cue] = []
        self.covered: list[list[float]] = []  # merged [start, end) intervals

    def add(self, cues, start: float, end: float) -> None:
        with self._lock:
            for cue in cues:
                # A piece that was redone (a seek, an edge line) never doubles a line.
                self.cues = [old for old in self.cues if not (old.start < cue.end and cue.start < old.end)]
                bisect.insort(self.cues, cue, key=lambda item: item.start)
            self._cover(start, end)

    def _cover(self, start: float, end: float) -> None:
        if end <= start:
            return
        intervals = sorted(self.covered + [[start, end]])
        merged = [intervals[0]]
        for a, b in intervals[1:]:
            if a <= merged[-1][1] + 0.05:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        self.covered = merged

    def is_covered(self, position: float) -> bool:
        with self._lock:
            return any(a <= position < b for a, b in self.covered)

    def covered_until(self, position: float) -> float:
        """End of the prepared stretch that contains ``position`` (``position`` itself when none)."""
        with self._lock:
            for a, b in self.covered:
                if a <= position < b:
                    return b
            return position

    def lines_at(self, position: float, keep: int = 2, linger: float = 3.0) -> list[Cue]:
        """The lines to show now: the current one and the ones that ended at most ``linger`` s ago."""
        with self._lock:
            shown = [cue for cue in self.cues if cue.start <= position + 0.05 and cue.end + linger >= position]
            return shown[-keep:]


# -- media ---------------------------------------------------------------------------------------------
def media_options(referer: str) -> dict:
    options = {"user_agent": USER_AGENT, "reconnect": "1", "reconnect_streamed": "1", "rw_timeout": "20000000"}
    if referer:
        parsed = urlparse(referer)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        options["headers"] = f"Referer: {referer}\r\nOrigin: {origin}\r\n"
    return options


def safe_media_url(url) -> bool:
    if not isinstance(url, str) or len(url) > 4000:
        return False
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def looks_like_media(url: str) -> bool:
    path = urlparse(url).path.casefold()
    return path.endswith(MEDIA_EXTENSIONS)


def rank_candidates(urls) -> list[str]:
    """Playlists first (newest first), then single files; segments and others dropped."""
    unique = []
    for url in urls:
        if safe_media_url(url) and url not in unique:
            unique.append(url)
    playlists = [url for url in unique if urlparse(url).path.casefold().endswith(".m3u8")]
    files = [url for url in unique if url not in playlists and looks_like_media(url)]
    return playlists + files


def open_media(url: str, referer: str, opener=None):
    """(container, audio stream) or raises. The audio with the lowest bit rate is enough for speech."""
    import av
    opener = opener or av.open
    container = opener(url, options=media_options(referer), timeout=20)
    audio = [stream for stream in container.streams if stream.type == "audio"]
    if not audio:
        container.close()
        raise ValueError("no audio in this media")
    stream = min(audio, key=lambda item: item.bit_rate or 0)
    return container, stream


def media_seconds(container) -> float:
    return float(container.duration) / 1_000_000 if container.duration else 0.0


def decode_audio(container, stream, start: float, end: float) -> tuple[np.ndarray, float]:
    """16 kHz mono float32 audio of [start, end) and the film time where it really begins."""
    import av
    container.seek(int(max(0.0, start) * 1_000_000), backward=True, any_frame=False)
    resampler = av.AudioResampler(format="flt", layout="mono", rate=16000)
    parts = []
    begin = None
    for packet in container.demux(stream):
        done = False
        try:
            frames = packet.decode()
        except av.error.InvalidDataError:
            continue  # a damaged packet (often the first one after a seek): skip it, keep the rest
        for frame in frames:
            moment = frame.time
            if moment is None:
                continue
            length = frame.samples / float(frame.sample_rate or 16000)
            if moment + length <= start:
                continue
            if moment >= end:
                done = True
                break
            if begin is None:
                begin = moment
            frame.pts = None
            for piece in resampler.resample(frame):
                parts.append(piece.to_ndarray().reshape(-1))
        if done:
            break
    if not parts or begin is None:
        return np.zeros(0, dtype=np.float32), start
    audio = np.concatenate(parts).astype(np.float32)
    if begin < start:  # the seek landed a little earlier (key frame): cut to the asked start
        audio = audio[int((start - begin) * 16000):]
        begin = start
    return audio[: int((end - begin) * 16000)], begin


# -- the worker ----------------------------------------------------------------------------------------
class FilmTranscriber:
    """Prepares the lines of one film ahead of the player, on its own thread."""

    def __init__(self, candidates, referer, clock: PlayerClock, timeline: CueTimeline, model_provider,
                 language=None, translate=None, on_error=None, video_duration: float = 0.0, opener=None,
                 fast_model_provider=None):
        self.candidates = rank_candidates(candidates)
        self.referer = referer
        self.clock = clock
        self.timeline = timeline
        self.model_provider = model_provider
        # Right after the start or a seek the precise model (~4-5 s a pass on a CPU) would never get
        # ahead of the player; the fast one prepares the first stretch, then the precise one takes over.
        self.fast_model_provider = fast_model_provider
        self.language = language
        self.translate = translate          # text, source language -> translation or "" (None = off)
        self.on_error = on_error
        self.video_duration = float(video_duration or 0.0)
        self.opener = opener
        self.url = ""
        self.ready = threading.Event()      # media opened and checked
        self._stop = threading.Event()
        self._thread = None
        self._prompt = ""

    def start(self):
        self._thread = threading.Thread(target=self._run, name="JarvisFilmCaptions", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def _choose(self):
        """The candidate whose length matches the video in the page (a page loads ads and previews too)."""
        last_error = None
        for url in self.candidates[:5]:
            try:
                container, stream = open_media(url, self.referer, self.opener)
            except Exception as error:  # refused, not media, no audio
                last_error = error
                continue
            seconds = media_seconds(container)
            if self.video_duration and seconds and abs(seconds - self.video_duration) > max(3.0, seconds * 0.02):
                container.close()
                continue
            self.url = url
            return container, stream
        raise RuntimeError(f"no usable media ({type(last_error).__name__ if last_error else 'none matched'})")

    def _run(self):
        try:
            container, stream = self._choose()
        except Exception as error:
            if self.on_error is not None:
                self.on_error(str(error))
            self._stop.set()
            return
        self.ready.set()
        models = {}
        total = media_seconds(container) or self.video_duration or 0.0
        next_start = None
        try:
            while not self._stop.is_set():
                position = self.clock.position()
                frontier = self.timeline.covered_until(position)
                if next_start is None or not (position - 2.0 <= next_start <= frontier + 0.5):
                    next_start = frontier  # a seek (or the start): work from where the film is now
                if (total and next_start >= total - 0.2) or next_start - position >= AHEAD_SECONDS:
                    self._stop.wait(0.5)  # far enough ahead (or the end): wait for the player
                    continue
                catching_up = self.fast_model_provider is not None and next_start - position < CATCH_UP_SECONDS
                kind = "fast" if catching_up else "precise"
                if kind not in models:
                    models[kind] = (self.fast_model_provider if catching_up else self.model_provider)()
                model = models[kind]
                fresh = not self.timeline.is_covered(position) and next_start - position < 5.0
                end = next_start + (FIRST_CHUNK_SECONDS if fresh else CHUNK_SECONDS)
                if total:
                    end = min(end, total)
                next_start = self._prepare(model, container, stream, next_start, end, final=bool(total) and end >= total)
        except Exception as error:
            if self.on_error is not None and not self._stop.is_set():
                self.on_error(f"{type(error).__name__}: {error}")
        finally:
            try:
                container.close()
            except Exception:
                pass

    def _prepare(self, model, container, stream, start: float, end: float, final: bool) -> float:
        """Recognise and translate [start, end); returns where the next piece starts."""
        audio, begin = decode_audio(container, stream, start, end)
        if len(audio) < 16000 * 0.5:
            self.timeline.add([], start, end)
            return end
        peak = float(np.max(np.abs(audio)))
        if 0.0 < peak < 0.1:
            audio = (audio * min(16.0, 0.1 / peak)).astype(np.float32)
        language = self.language
        if not language and hasattr(model, "detect_language"):
            try:
                language = model.detect_language(audio)[0]
                self.language = language
            except Exception:
                language = None
        from luxai.live_captions import lone_filler, trustworthy
        from luxai.voice_rules import is_hallucinated_outro, is_repetitive_transcript
        segments, _info = model.transcribe(
            audio, language=language, beam_size=2, temperature=0.0, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 200},
            condition_on_previous_text=False, initial_prompt=self._prompt or None, word_timestamps=True,
            no_speech_threshold=0.6, log_prob_threshold=-1.0, compression_ratio_threshold=2.4)
        cues = []
        for segment in segments:
            text = segment.text.strip()
            if not text or not trustworthy(segment) or lone_filler(text) \
                    or is_hallucinated_outro(text) or is_repetitive_transcript(text):
                continue
            words = getattr(segment, "words", None) or []
            # Word times are exact; a segment's own start can be up to a second early.
            first = float(words[0].start) if words else float(segment.start)
            last = float(words[-1].end) if words else float(segment.end)
            cues.append(Cue(begin + first, begin + max(last, first + 0.3), text, words=word_marks(words, begin, text)))
        reached = begin + len(audio) / 16000
        next_start = reached
        if not final and cues and cues[-1].end > reached - EDGE_SECONDS:
            # The last line may be cut in the middle of a word: it is redone with the next piece.
            next_start = max(begin + 0.5, cues[-1].start - 0.2)
            cues = cues[:-1]
        if self.translate is not None:
            for cue in cues:
                if self._stop.is_set():
                    break
                try:
                    cue.translation = self.translate(cue.text, language or "") or ""
                except Exception:
                    cue.translation = ""
        if cues:
            self._prompt = cues[-1].text[-160:]
        self.timeline.add(cues, start, next_start)
        return next_start


# -- the local bridge for the browser extension --------------------------------------------------------
def parse_report(raw: bytes) -> dict | None:
    """A validated report from the extension, or None."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        report = {
            "tab": int(data.get("tab", 0)),
            "page": str(data.get("page", ""))[:2000],
            "time": float(data.get("time", 0.0)),
            "paused": bool(data.get("paused", True)),
            "rate": float(data.get("rate", 1.0) or 1.0),
            "duration": float(data.get("duration", 0.0) or 0.0),
        }
    except (TypeError, ValueError):
        return None
    if not (0.0 <= report["time"] < 10 ** 6) or report["duration"] != report["duration"]:
        return None
    if report["page"] and not safe_media_url(report["page"]):
        report["page"] = ""
    media = data.get("media", [])
    media = media if isinstance(media, list) else []
    src = data.get("src", "")
    report["media"] = [url for url in ([src] if src else []) + media[:MAX_URLS] if safe_media_url(url)]
    return report


def parse_hello(raw: bytes) -> dict:
    """«The extension is installed»: its version and browser (short, cleaned)."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        data = {}
    data = data if isinstance(data, dict) else {}
    version = re.sub(r"[^0-9.]", "", str(data.get("version", "")))[:16]
    browser = "edge" if data.get("browser") == "edge" else "chrome"
    return {"version": version, "browser": browser}


class _Handler(BaseHTTPRequestHandler):
    server_version = "JarvisBridge/1"

    def log_message(self, *_args):  # nothing in the console or logs
        pass

    def _allowed_origin(self) -> str:
        origin = self.headers.get("Origin", "")
        return origin if re.fullmatch(r"chrome-extension://[a-p]{32}", origin) else ""

    def do_OPTIONS(self):  # noqa: N802 - the browser's CORS preflight
        origin = self._allowed_origin()
        self.send_response(204 if origin else 403)
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "POST")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):  # noqa: N802
        origin = self._allowed_origin()
        length = int(self.headers.get("Content-Length", "0") or 0)
        if not origin or self.path not in ("/v1/state", "/v1/hello") or not 0 < length <= MAX_BODY:
            self.send_response(403)
            self.end_headers()
            return
        raw = self.rfile.read(length)
        if self.path == "/v1/hello":
            report = parse_hello(raw)
            report["extension"] = origin.rsplit("/", 1)[-1]
            target = self.server.on_hello
        else:
            report = parse_report(raw)
            target = self.server.on_report
        if report is None:
            self.send_response(400)
            self.end_headers()
            return
        try:
            if target is not None:
                target(report)
        except Exception:
            pass
        body = json.dumps({"ok": True}).encode("utf-8")
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _ExclusiveServer(ThreadingHTTPServer):
    """On Windows SO_REUSEADDR lets a SECOND program bind the same port: two Jarvis copies (or another
    program) would split the reports. The port is taken exclusively instead."""
    allow_reuse_address = False

    def server_bind(self):
        import socket
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()


class BridgeServer:
    """127.0.0.1:PORT, extension origins only. ``on_report`` runs on the server thread."""

    def __init__(self, on_report, port: int = PORT, on_hello=None):
        self.on_report = on_report
        self.on_hello = on_hello
        self.port = port
        self._server = None

    def start(self) -> bool:
        try:
            self._server = _ExclusiveServer(("127.0.0.1", self.port), _Handler)
        except OSError:
            return False  # the port is taken (another Jarvis copy): the film mode stays off
        self._server.daemon_threads = True
        self._server.on_report = self.on_report
        self._server.on_hello = self.on_hello
        threading.Thread(target=self._server.serve_forever, name="JarvisBrowserBridge", daemon=True).start()
        return True

    def stop(self):
        server, self._server = self._server, None
        if server is not None:
            threading.Thread(target=lambda: (server.shutdown(), server.server_close()), daemon=True).start()

    @property
    def running(self) -> bool:
        return self._server is not None
