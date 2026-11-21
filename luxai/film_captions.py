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

import base64
import bisect
import hmac
import io
import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import numpy as np

PORT = 47321
AHEAD_SECONDS = 600.0      # prepare at most 10 minutes in front of the player (setting «Prepare ahead»)
PAUSED_AHEAD_SECONDS = 60.0  # while the player is paused
CHUNK_SECONDS = 30.0       # one Whisper pass (its natural window)
FIRST_CHUNK_SECONDS = 10.0  # where nothing is prepared yet (start, a seek): the first lines come sooner
CATCH_UP_SECONDS = 20.0    # closer than this to the player, the fast model works (it must get ahead first)
EDGE_SECONDS = 1.5         # a line ending this close to a piece's end is redone with the next piece
MAX_BODY = 64 * 1024
MAX_AUDIO_BYTES = (2048 + 32) * 1024  # compressed media plus the initialization segment
MAX_AUDIO_BODY = ((MAX_AUDIO_BYTES + 2) // 3) * 4 + MAX_BODY
BROWSER_AHEAD_SECONDS = 60.0
BROWSER_PRECISE_LEAD = 6.0  # real seconds needed before committing a longer recognition window
BROWSER_START_CHUNK = 8.0
MAX_URLS = 20
STALE_SECONDS = 5.0        # no report for this long → prepared lines are not shown (heartbeat: 1 s / 3 s paused)
GONE_SECONDS = 20.0        # no report for this long → the preparation stops (tab closed, browser gone)
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

    def update(self, position: float, paused: bool, rate: float = 1.0, duration: float = 0.0, now=None,
               stalled: bool = False, ended: bool = False):
        """``stalled`` (buffering) and ``ended`` freeze the clock like a pause (audit 3 #23)."""
        with self._lock:
            self.time = max(0.0, float(position))
            self.paused = bool(paused or stalled or ended)
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

    def gone(self, now=None) -> bool:
        now = time.monotonic() if now is None else now
        return bool(self.reported) and now - self.reported > GONE_SECONDS


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
        if position < self.start:
            return 0, 0
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
        self._starts: list[float] = []  # cue starts, for a binary search (audit 3 #26)
        self._longest = 0.0              # the longest line: how far back a neighbour can start
        self.covered: list[list[float]] = []  # merged [start, end) intervals

    @staticmethod
    def same_line(old: Cue, cue: Cue, *, cut_at_edge: bool = False) -> bool:
        """A repeat, or the completion of a line cut at a known chunk boundary."""
        overlap = min(old.end, cue.end) - max(old.start, cue.start)
        shorter = max(0.01, min(old.end - old.start, cue.end - cue.start))
        if overlap <= 0.5 * shorter:
            return False
        words = r"\w+(?:['’]\w+)*"
        a = re.findall(words, old.text.casefold().replace("’", "'"))
        b = re.findall(words, cue.text.casefold().replace("’", "'"))
        if a == b:
            return bool(a) or old.text.strip() == cue.text.strip()
        return (cut_at_edge and 2 <= len(a) <= len(b) and len(a[-1]) >= 3
                and abs(old.start - cue.start) <= 0.5 and cue.end > old.end
                and a[:-1] == b[:len(a) - 1] and b[len(a) - 1].startswith(a[-1]))

    def add(self, cues, start: float, end: float) -> None:
        with self._lock:
            for cue in cues:
                # Only the neighbours in time are looked at, and the index is kept up to date in place
                # (audit 4 #19): a long film does not rescan every line for each new one.
                low = bisect.bisect_left(self._starts, cue.start - self._longest - 0.01)
                high = bisect.bisect_left(self._starts, cue.end)
                for index in range(high - 1, low - 1, -1):
                    old = self.cues[index]
                    overlap = min(old.end, cue.end) - max(old.start, cue.start)
                    if overlap <= 0:
                        continue
                    stretch = self._stretch(old.start)
                    cut_at_edge = stretch is not None and abs(stretch[1] - old.end) <= 0.05
                    if self.same_line(old, cue, cut_at_edge=cut_at_edge):
                        del self.cues[index]
                        del self._starts[index]
                    elif old.start < cue.start:
                        old.end = max(old.start + 0.01, min(old.end, cue.start))  # touching lines: both stay
                position = bisect.bisect_right(self._starts, cue.start)
                self.cues.insert(position, cue)
                self._starts.insert(position, cue.start)
                self._longest = max(self._longest, cue.end - cue.start)
            self._cover(start, end)

    def _cover(self, start: float, end: float) -> None:
        """Insert [start, end) into the sorted, disjoint stretches, merging only the neighbours it touches
        (audit 5 #17: no full sort per piece, even after many seeks)."""
        if end <= start:
            return
        covered = self.covered
        low = bisect.bisect_left(covered, [start - 0.05])
        if low > 0 and covered[low - 1][1] + 0.05 >= start:
            low -= 1
        high = low
        while high < len(covered) and covered[high][0] <= end + 0.05:
            high += 1
        if high > low:
            start = min(start, covered[low][0])
            end = max(end, covered[high - 1][1])
        covered[low:high] = [[start, end]]

    def _stretch(self, position: float):
        index = bisect.bisect_right(self.covered, [position, float("inf")]) - 1
        if index >= 0 and self.covered[index][0] <= position < self.covered[index][1]:
            return self.covered[index]
        return None

    def is_covered(self, position: float) -> bool:
        with self._lock:
            return self._stretch(position) is not None

    def covered_until(self, position: float) -> float:
        """End of the prepared stretch that contains ``position`` (``position`` itself when none)."""
        with self._lock:
            stretch = self._stretch(position)
            return stretch[1] if stretch else position

    def lines_at(self, position: float, keep: int = 2, linger: float = 3.0) -> list[Cue]:
        """The lines to show now: the current one and the ones that ended at most ``linger`` s ago."""
        with self._lock:
            last = bisect.bisect_right(self._starts, position + 0.05)
            shown = []
            for cue in reversed(self.cues[max(0, last - 12):last]):  # only the neighbourhood of the position
                if cue.end + linger >= position:
                    shown.append(cue)
                if len(shown) >= keep:
                    break
            return shown[::-1]


# -- media ---------------------------------------------------------------------------------------------
# FFmpeg may open only network media: no files, pipes or other protocols, also inside playlists (audit 3 #2).
# FFmpeg talks ONLY to Jarvis's media gateway on 127.0.0.1 (plain http, plus «crypto» for AES-128 HLS); it has
# no https/tls of its own: every real request, its certificate and its address are checked by the gateway.
PROTOCOLS = "http,tcp,crypto"
PLAYLIST_TYPES = re.compile(r"mpegurl", re.I)
MEDIA_TYPES = re.compile(r"mpegurl|video/(mp4|webm|x-matroska|quicktime)|audio/(mp4|mpeg|aac|webm)", re.I)


_GATEWAY = None
_GATEWAY_LOCK = threading.Lock()


def media_gateway():
    """The one media gateway of this Jarvis (luxai/media_proxy.py): checked addresses, verified HTTPS,
    rewritten playlists (audit 4 #2, audit 5 #1)."""
    global _GATEWAY
    from luxai.media_proxy import MediaGateway
    with _GATEWAY_LOCK:
        if _GATEWAY is None or not _GATEWAY.running:
            _GATEWAY = MediaGateway().start()
        return _GATEWAY


def media_options(referer: str) -> dict:
    options = {"user_agent": USER_AGENT, "reconnect": "1", "reconnect_streamed": "1", "rw_timeout": "20000000",
               "protocol_whitelist": PROTOCOLS,
               # Never a proxy from the environment (the gateway is local), and nothing in os.environ is
               # changed for it (audit 5 #12).
               "http_proxy": "",
               # A gateway URL can have no suffix. Identify HLS segment data by its contents.
               "allowed_extensions": "ALL", "allowed_segment_extensions": "ALL", "extension_picky": "0"}
    if referer and safe_media_url(referer):  # never a header built from an unchecked value
        parsed = urlparse(referer)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        options["headers"] = f"Referer: {referer}\r\nOrigin: {origin}\r\n"
    return options


def safe_media_url(url) -> bool:
    if not isinstance(url, str) or len(url) > 4000 or any(ord(ch) < 33 or ord(ch) == 127 for ch in url):
        return False
    try:
        parsed = urlparse(url)
        port = parsed.port
        return parsed.scheme in ("http", "https") and bool(parsed.hostname) and port != 0
    except ValueError:
        return False


def uses_live_audio(page: str) -> bool:
    """Use playback audio for YouTube, including its embedded and music players."""
    if not safe_media_url(page):
        return False
    host = (urlparse(page).hostname or "").rstrip(".")
    return any(host == name or host.endswith("." + name)
               for name in ("youtube.com", "youtube-nocookie.com", "youtu.be"))


def looks_like_media(url: str) -> bool:
    path = urlparse(url).path.casefold()
    return path.endswith(MEDIA_EXTENSIONS)


def _entry(item) -> tuple[str, str]:
    if isinstance(item, dict):
        return str(item.get("url", "")), str(item.get("type", ""))[:100]
    return (item, "") if isinstance(item, str) else ("", "")


def rank_candidates(urls) -> list[str]:
    """The player's own HTTP source first, then playlists and known media."""
    unique, kinds = [], {}
    primary = ""
    for item in urls:
        url, kind = _entry(item)
        if not safe_media_url(url):
            continue
        if isinstance(item, dict) and item.get("direct") is True and not primary:
            primary = url
        if url not in kinds:
            unique.append(url)
            kinds[url] = kind
        elif kind and not kinds[url]:
            kinds[url] = kind  # the same address seen again WITH its type: keep it (audit 4 #3)
    playlists = [url for url in unique
                 if urlparse(url).path.casefold().endswith(".m3u8") or PLAYLIST_TYPES.search(kinds[url])]
    files = [url for url in unique if url not in playlists and (looks_like_media(url) or MEDIA_TYPES.search(kinds[url]))]
    return ([primary] if primary else []) + [url for url in playlists + files if url != primary]


def open_media(url: str, referer: str, opener=None, *, session):
    """(container, audio stream) or raises. The audio with the lowest bit rate is enough for speech.
    The caller owns the film's gateway session. Address resolution and filtering are done there."""
    import av
    if not safe_media_url(url):
        raise PermissionError("media address not allowed")
    opener = opener or av.open
    container = opener(session.url_for(url), options=media_options(referer), timeout=20)
    audio = [stream for stream in container.streams if stream.type == "audio"]
    if not audio:
        container.close()
        raise ValueError("no audio in this media")
    stream = min(audio, key=lambda item: item.bit_rate or 0)
    return container, stream


def media_seconds(container) -> float:
    return float(container.duration) / 1_000_000 if container.duration else 0.0


def media_offset(container) -> float:
    """Where the media's own clock starts (seconds). MPEG-TS / HLS often start at 10 s, 30 s or more while
    the player shows 0: player time = media time - offset (audit 5 #4)."""
    start = getattr(container, "start_time", None)
    if not isinstance(start, (int, float)) or not 0 < start < 10 ** 12:
        return 0.0
    return float(start) / 1_000_000


def decode_audio(container, stream, start: float, end: float) -> tuple[np.ndarray, float]:
    """16 kHz mono float32 audio of [start, end) and the film time where it really begins (both in the
    PLAYER's time: the media's own start offset is applied to the seek and taken off every frame)."""
    import av
    offset = media_offset(container)
    container.seek(int((max(0.0, start) + offset) * 1_000_000), backward=True, any_frame=False)
    resampler = av.AudioResampler(format="flt", layout="mono", rate=16000)
    parts = []
    begin = None
    written = 0  # samples placed so far
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
            moment -= offset
            length = frame.samples / float(frame.sample_rate or 16000)
            if moment + length <= start:
                continue
            if moment >= end:
                done = True
                break
            if begin is None:
                begin = moment
            expected = int(round((moment - begin) * 16000))
            if expected - written > 800:  # a gap of more than 50 ms in the track: silence keeps the timeline
                parts.append(np.zeros(expected - written, dtype=np.float32))
                written = expected
            frame.pts = None
            for piece in resampler.resample(frame):
                samples = piece.to_ndarray().reshape(-1)
                parts.append(samples)
                written += len(samples)
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
                 fast_model_provider=None, ahead_seconds: float = AHEAD_SECONDS):
        self.candidates = rank_candidates(candidates)
        self.ahead_seconds = max(30.0, min(AHEAD_SECONDS, float(ahead_seconds or AHEAD_SECONDS)))
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
        self.failed = False                 # ended by an error (the runtime waits before trying this film again)
        self.ready = threading.Event()      # media opened and checked
        self._stop = threading.Event()
        self._thread = None
        self._session = None                # this film's gateway session (closed by stop())
        self._empty = 0                     # decodes in a row that returned no audio at all
        self._prompt = ""

    def start(self):
        self._thread = threading.Thread(target=self._run, name="JarvisFilmCaptions", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        session = self._session
        if session is not None:
            session.close()  # a decoder waiting on the network returns at once (audit 5 #13)

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    CHOOSE_SECONDS = 60.0  # all candidates together (each open has its own 20 s limit)

    def _gateway_session(self):
        if self._session is None:
            self._session = media_gateway().open_session()
            if self._stop.is_set():
                self._session.close()
        return self._session

    def _choose(self):
        """The candidate whose length matches the video in the page (a page loads ads and previews too).
        A stop is honoured before and after every attempt, and the whole choice is time-limited (audit 4 #16)."""
        last_error = None
        deadline = time.monotonic() + self.CHOOSE_SECONDS
        for url in self.candidates[:5]:
            if self._stop.is_set() or time.monotonic() > deadline:
                raise RuntimeError("stopped while choosing the media")
            try:
                container, stream = open_media(url, self.referer, self.opener, session=self._gateway_session())
            except Exception as error:  # refused, not media, no audio
                last_error = error
                continue
            if self._stop.is_set():
                container.close()
                raise RuntimeError("stopped while choosing the media")
            seconds = media_seconds(container)
            if self.video_duration and seconds and abs(seconds - self.video_duration) > max(3.0, seconds * 0.02):
                container.close()
                continue
            self.url = url
            return container, stream
        raise RuntimeError(f"no usable media ({type(last_error).__name__ if last_error else 'none matched'})")

    def _run(self):
        try:
            self._work()
        except Exception as error:
            self.failed = True
            if self.on_error is not None:
                self.on_error(f"{type(error).__name__}: {error}")
        finally:
            self.stop()  # whatever happened, the runtime sees a finished worker (and its connections end)

    def _work(self):
        try:
            container, stream = self._choose()
        except Exception:
            if self._stop.is_set():
                return  # stopped on purpose: not a failure
            self.failed = True
            raise
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
                # Paused: at most a minute ahead (no download and CPU for a film nobody watches, audit 5 #16).
                ahead = min(self.ahead_seconds, PAUSED_AHEAD_SECONDS) if self.clock.paused else self.ahead_seconds
                if (total and next_start >= total - 0.2) or next_start - position >= ahead:
                    self._stop.wait(0.5)  # far enough ahead (or the end): wait for the player
                    continue
                catching_up = self.fast_model_provider is not None and next_start - position < CATCH_UP_SECONDS
                kind = "fast" if catching_up else "precise"
                if kind not in models:
                    models[kind] = (self.fast_model_provider if catching_up else self.model_provider)()
                model = models[kind]
                fresh = not self.timeline.is_covered(position) and next_start - position < 5.0
                end = min(position + ahead, next_start + (FIRST_CHUNK_SECONDS if fresh else CHUNK_SECONDS))
                if total:
                    end = min(end, total)
                next_start = self._prepare(model, container, stream, next_start, end, final=bool(total) and end >= total)
        except Exception:
            if not self._stop.is_set():
                self.failed = True
                raise
        finally:
            try:
                container.close()
            except Exception:
                pass

    def _prepare(self, model, container, stream, start: float, end: float, final: bool) -> float:
        """Recognise and translate [start, end); returns where the next piece starts."""
        audio, begin = decode_audio(container, stream, start, end)
        if not len(audio):
            # Nothing decoded at all is NOT silence (audit 5 #4): the stretch stays uncovered (the live captions
            # keep showing it) and the same place is tried again; three times in a row → this film fails.
            self._empty += 1
            if self._empty >= 3:
                raise RuntimeError(f"no audio decoded at {start:.0f} s")
            self._stop.wait(1.0)
            return start
        self._empty = 0
        return self._prepare_audio(model, audio, begin, start, end, final)

    def _prepare_audio(self, model, audio, begin: float, start: float, end: float, final: bool) -> float:
        if len(audio) < 16000 * 0.5:
            self.timeline.add([], start, end)  # decoded and (nearly) silent: really nothing said here
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


def decode_browser_audio(kind: str, offset: float, data: bytes, *, start_at: float | None = None):
    """Yield contiguous 16 kHz audio with timestamps on the browser player's clock."""
    import av

    with av.open(io.BytesIO(data), format="matroska" if kind == "webm" else "mov") as container:
        if not container.streams.audio:
            return
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="flt", layout="mono", rate=16000)
        start = None
        parts = []
        count = 0
        total = 0
        max_samples = int((BROWSER_AHEAD_SECONDS + 1) * 16000)
        try:
            for frame in container.decode(stream):
                if frame.time is None:
                    continue
                moment = frame.time + offset
                if not -60 <= moment < 10 ** 7:
                    continue
                if start_at is not None:
                    if moment + frame.samples / (frame.sample_rate or 16000) <= start_at:
                        continue  # an older cluster in the rolling snapshot
                    if moment >= start_at + BROWSER_AHEAD_SECONDS + 1:
                        break
                frame.pts = None
                converted = resampler.resample(frame)
                if not converted:
                    continue
                samples = np.concatenate([piece.to_ndarray().reshape(-1) for piece in converted])
                total += len(samples)
                if total > max_samples:
                    break
                if start is None:
                    start = moment
                gap = round((moment - start) * 16000) - count
                if abs(gap) > 1600:
                    if parts:
                        yield start, np.concatenate(parts)
                    start, parts, count, gap = moment, [], 0, 0
                if gap > 0:
                    parts.append(np.zeros(gap, dtype=np.float32))
                    count += gap
                if gap < 0:
                    samples = samples[-gap:]
                parts.append(samples)
                count += len(samples)
        except av.FFmpegError:
            pass  # the last fragment may end in the middle of a packet
        if parts:
            yield start, np.concatenate(parts)


class BufferedFilmTranscriber(FilmTranscriber):
    """Prepare cues from the browser's already loaded media instead of opening a remote source."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._packet_ready = threading.Event()
        self._packet_lock = threading.Lock()
        self._packet = None

    def submit(self, packet):
        with self._packet_lock:
            self._packet = packet
            self._packet_ready.set()

    def stop(self):
        super().stop()
        self._packet_ready.set()

    def _work(self):
        import av

        models = {}
        while not self._stop.is_set():
            self._packet_ready.wait()
            with self._packet_lock:
                packet, self._packet = self._packet, None
                self._packet_ready.clear()
            if self._stop.is_set() or packet is None:
                continue
            kind, _track, offset, data = packet
            try:
                start_at = max(0.0, self.clock.position() - 0.8)
                for begin, audio in decode_browser_audio(kind, offset, data, start_at=start_at):
                    self._prepare_available(models, begin, audio)
            except av.FFmpegError:
                continue

    def _prepare_available(self, models, begin, audio):
        available_end = begin + len(audio) / 16000
        if self.video_duration:
            available_end = min(available_end, self.video_duration)
        start = begin
        while not self._stop.is_set():
            position = self.clock.position()
            start = self.timeline.covered_until(max(start, 0.0, position - 0.8))
            cap = min(available_end, position + min(self.ahead_seconds, BROWSER_AHEAD_SECONDS))
            if cap - start < 0.6:
                return
            realtime_lead = (start - position) / max(0.1, self.clock.rate)
            catching_up = realtime_lead < BROWSER_PRECISE_LEAD
            provider = (self.fast_model_provider if catching_up else None) or self.model_provider
            if provider not in models:
                models[provider] = provider()
            end = min(cap, start + (BROWSER_START_CHUNK if catching_up else CHUNK_SECONDS))
            first = max(0, round((start - begin) * 16000))
            last = min(len(audio), round((end - begin) * 16000))
            final = bool(self.video_duration and end >= self.video_duration - 0.25)
            following = self._prepare_audio(models[provider], audio[first:last], begin + first / 16000,
                                            start, end, final)
            self.ready.set()
            if end >= cap - 0.001 or following <= start + 0.01:
                return
            start = following


# -- the local bridge for the browser extension --------------------------------------------------------
def parse_report(raw: bytes, *, with_audio: bool = False) -> dict | None:
    """A validated report from the extension, or None."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    event = data.get("event", "state")
    try:
        report = {
            "event": event if event in ("state", "closed") else "state",
            "tab": int(data.get("tab", 0)),
            "frame": int(data.get("frame", 0) or 0),
            "page": str(data.get("page", ""))[:2000],
            "time": float(data.get("time", 0.0) or 0.0),
            "paused": bool(data.get("paused", True)),
            "stalled": bool(data.get("stalled", False)),   # buffering: the time does not move
            "ended": bool(data.get("ended", False)),
            "rate": float(data.get("rate", 1.0) or 1.0),
            "duration": float(data.get("duration", 0.0) or 0.0),
            # One page load = one document; its reports are numbered (a late one is ignored, audit 4 #4).
            "doc": re.sub(r"[^0-9A-Za-z-]", "", str(data.get("doc", "")))[:40],
            "seq": max(0, min(10 ** 12, int(data.get("seq", 0) or 0))),
            # A new source in the same player (blob players, a new episode) = a new media session (#5).
            "session": max(0, min(10 ** 9, int(data.get("session", 0) or 0))),
            "visible": bool(data.get("visible", True)),   # the tab the user looks at (#6)
            "active": bool(data.get("active", data.get("focused", False))),
            "focused": bool(data.get("focused", False)),
        }
    except (TypeError, ValueError, OverflowError):
        return None
    if not (0.0 <= report["time"] < 10 ** 6) or report["duration"] != report["duration"] \
            or not (0.0 <= report["duration"] < 10 ** 7):
        return None
    if report["page"] and not safe_media_url(report["page"]):
        report["page"] = ""
    docs = data.get("docs", [])
    report["docs"] = [re.sub(r"[^0-9A-Za-z-]", "", str(item))[:40] for item in docs[:20]] \
        if isinstance(docs, list) else []  # «closed»: the documents of the tab that went away
    media = data.get("media", [])
    media = media if isinstance(media, list) else []
    src = data.get("src", "")
    report["src"] = src if safe_media_url(src) else ""
    entries = [{"url": report["src"], "type": "", "direct": True}] if report["src"] else []
    for item in media[:MAX_URLS]:
        url, kind = _entry(item)
        if safe_media_url(url):
            entries.append({"url": url, "type": kind})
    report["media"] = entries
    if with_audio:
        packet = data.get("buffer")
        if (not uses_live_audio(report["page"]) or not report["active"] or not report["visible"]
                or not isinstance(packet, dict) or packet.get("kind") not in ("webm", "mp4")):
            return None
        try:
            offset = float(packet["offset"])
            track = int(packet["track"])
            encoded = packet["data"]
            if not -10 ** 6 < offset < 10 ** 6 or not 0 < track < 10 ** 9 or not isinstance(encoded, str):
                return None
            audio = base64.b64decode(encoded, validate=True)
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
        if not 0 < len(audio) <= MAX_AUDIO_BYTES:
            return None
        report["buffer"] = (packet["kind"], track, offset, audio)
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


def pairing_token(folder) -> str:
    """The secret shared with the Jarvis extension (audit 3 #2).

    It is written into the extension's own folder (``pairing.json``), which only the unpacked extension
    loaded from THIS installation can read (``chrome.runtime.getURL``); another extension or a web page never
    has it, so it cannot talk to the bridge. Created once, kept across updates (not part of the release).
    Raises OSError when the file cannot be written and read back: a key the extension cannot load would leave
    the bridge refusing everything without a word (audit 4 #7).
    """
    from pathlib import Path
    path = Path(folder) / "pairing.json"

    def read() -> str:
        try:
            value = str(json.loads(path.read_text(encoding="utf-8")).get("token", ""))
        except (OSError, ValueError, AttributeError):
            return ""
        return value if re.fullmatch(r"[0-9a-f]{48}", value) else ""

    token = read()
    if token:
        return token
    token = secrets.token_hex(24)
    temporary = path.with_name(f"pairing.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps({"token": token}), encoding="utf-8")
        os.replace(temporary, path)  # atomic: the extension never reads half a file
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass
    if read() != token:
        raise OSError(f"pairing.json could not be written in {folder}")
    return token


class _Handler(BaseHTTPRequestHandler):
    server_version = "JarvisBridge/1"
    timeout = 5  # a client that sends half a request cannot keep a thread (audit 3 #16)

    def log_message(self, *_args):  # nothing in the console or logs
        pass

    def _allowed_origin(self) -> str:
        origin = self.headers.get("Origin", "")
        return origin if re.fullmatch(r"chrome-extension://[a-p]{32}", origin) else ""

    def _paired(self) -> bool:
        token = getattr(self.server, "token", "")
        offered = self.headers.get("X-Jarvis-Token", "")
        return bool(token) and hmac.compare_digest(offered.encode("utf-8", "ignore"), token.encode("utf-8"))

    def _answer(self, code: int, origin: str = "", body: dict | None = None):
        data = json.dumps(body or {}).encode("utf-8")
        self.send_response(code)
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):  # noqa: N802 - the browser's CORS preflight
        origin = self._allowed_origin()
        self.send_response(204 if origin else 403)
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "POST")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Jarvis-Token")
        self.end_headers()

    def do_POST(self):  # noqa: N802 - connections are limited when accepted (_ExclusiveServer)
        origin = self._allowed_origin()
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            self._answer(400, origin)
            return
        audio_request = self.path == "/v1/audio"
        limit = MAX_AUDIO_BODY if audio_request else MAX_BODY
        if not origin or self.path not in ("/v1/state", "/v1/hello", "/v1/want", "/v1/audio") or not 0 < length <= limit:
            self._answer(403)
            return
        if not self._paired():
            self._answer(401, origin, {"error": "pairing"})  # the extension reloads pairing.json
            return
        try:
            raw = self.rfile.read(length)
        except OSError:
            return  # timed out or closed: nothing more to answer
        want = bool(getattr(self.server, "want", False))
        if self.path == "/v1/want":
            # «Are captions on?» Nothing is sent about the page until Jarvis says yes (audit 4 #14).
            self._answer(200, origin, {"ok": True, "want": want})
            return
        if audio_request and not want:
            self._answer(200, origin, {"ok": True, "want": False})
            return
        if self.path == "/v1/hello":
            report = parse_hello(raw)
            report["extension"] = origin.rsplit("/", 1)[-1]
            target = self.server.on_hello
        else:
            report = parse_report(raw, with_audio=audio_request)
            target = self.server.on_report
        if report is None or len(raw) != length:
            self._answer(400, origin)
            return
        try:
            if target is not None:
                target(report)
        except Exception:
            pass
        self._answer(200, origin, {"ok": True, "want": want})


class _ExclusiveServer(ThreadingHTTPServer):
    """On Windows SO_REUSEADDR lets a SECOND program bind the same port: two Jarvis copies (or another
    program) would split the reports. The port is taken exclusively instead."""
    allow_reuse_address = False
    gate = None

    def process_request(self, request, client_address):
        """At most 8 connections at once, counted at accept time (audit 4 #13): a slow client that never
        finishes its headers holds a slot, not an unbounded thread."""
        if self.gate is not None and not self.gate.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            if self.gate is not None:
                self.gate.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            if self.gate is not None:
                self.gate.release()

    def server_bind(self):
        import socket
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()


class BridgeServer:
    """127.0.0.1:PORT, extension origins only. ``on_report`` runs on the server thread."""

    def __init__(self, on_report, port: int = PORT, on_hello=None, token: str = ""):
        self.on_report = on_report
        self.on_hello = on_hello
        self.port = port
        self.token = token  # without a pairing token every request is refused
        self._want = False   # Jarvis shows captions and wants the player's state (audit 4 #14)
        self._server = None

    @property
    def want(self) -> bool:
        return self._want

    @want.setter
    def want(self, value: bool) -> None:
        self._want = bool(value)
        if self._server is not None:
            self._server.want = self._want

    def start(self) -> bool:
        try:
            self._server = _ExclusiveServer(("127.0.0.1", self.port), _Handler)
        except OSError:
            return False  # the port is taken (another Jarvis copy): the film mode stays off
        self._server.daemon_threads = True
        self._server.on_report = self.on_report
        self._server.on_hello = self.on_hello
        self._server.token = self.token
        self._server.gate = threading.BoundedSemaphore(8)
        self._server.want = self._want
        # A short poll: stop() frees the port within ~0.1 s (audit 5 #3; the runtime also retries).
        threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.1},
                         name="JarvisBrowserBridge", daemon=True).start()
        return True

    def stop(self):
        server, self._server = self._server, None
        if server is not None:
            threading.Thread(target=lambda: (server.shutdown(), server.server_close()), daemon=True).start()

    @property
    def running(self) -> bool:
        return self._server is not None
