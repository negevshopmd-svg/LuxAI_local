"""Offline Fish S2 speech runtime for Windows, with a retained worker process.

No user text ever goes to Fish Audio when this engine is selected. Assets are
installed separately and explicitly; synthesis does not download anything.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
FISH_DIR = ROOT / "models" / "fishaudio"
MODEL_NAME = "s2-pro-q4_k_m.gguf"
RUNTIME_DIR = FISH_DIR / "runtime"
WORKER = Path(__file__).with_name("fish_local_worker.py")
MAX_WAV_BYTES = 96_000 * 2 * 120 + 1000
PROTOCOL = "FISH_LOCAL_JSON:"


class FishLocalError(RuntimeError):
    pass


def paths():
    return {"model": FISH_DIR / MODEL_NAME, "tokenizer": FISH_DIR / "tokenizer.json",
            "runtime": RUNTIME_DIR, "reference": FISH_DIR / "jarvis_reference.wav"}


def choose_runtime():
    baseline = RUNTIME_DIR / "cpu-baseline" / "s2.dll"
    accelerated = RUNTIME_DIR / "cpu-avx2" / "s2.dll"
    if sys.platform != "win32" or not baseline.is_file():
        raise FishLocalError("fish_cpu_runtime_missing")
    # Probe the baseline DLL first. Importing AVX2 code on an unsupported CPU
    # can crash the entire process, so never load it merely to test support.
    try:
        dll = ctypes.CDLL(str(baseline.resolve()))
        probe = dll.GetFishCpuFeatureBits
        probe.argtypes, probe.restype = [], ctypes.c_uint32
        features = int(probe())
    except (OSError, AttributeError):
        raise FishLocalError("fish_cpu_runtime_invalid") from None
    return accelerated if features & 7 == 7 and accelerated.is_file() else baseline


def ready(reference=""):
    p = paths()
    if not p["model"].is_file() or p["model"].stat().st_size < 1_000_000_000:
        return False, "fish_model_missing"
    with p["model"].open("rb") as handle:
        if handle.read(4) != b"GGUF":
            return False, "fish_model_invalid"
    if not p["tokenizer"].is_file() or p["tokenizer"].stat().st_size < 1_000_000:
        return False, "fish_tokenizer_missing"
    try:
        choose_runtime()
    except FishLocalError as exc:
        return False, str(exc)
    if reference and not Path(reference).is_file():
        return False, "fish_reference_missing"
    return True, "ready"


class ResidentEngine:
    def __init__(self):
        self._guard = threading.RLock()
        self._process = None
        self._reader = None
        self._events = queue.Queue()
        self._signature = None
        self._serial = 0

    def stop(self):
        # Called by the UI thread while synthesis holds _guard. Never acquire
        # that same lock: terminate the subprocess immediately on a barge-in.
        process, self._process = self._process, None
        self._signature = None
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1.5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass

    def _listen(self, process, event_queue):
        try:
            for line in process.stdout:
                if line.startswith(PROTOCOL):
                    try:
                        event = json.loads(line[len(PROTOCOL):])
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if isinstance(event, dict):
                        event_queue.put(event)
        finally:
            event_queue.put({"event": "worker_closed"})

    def _await(self, process, event_queue, expected, deadline, cancelled):
        while time.monotonic() < deadline:
            if cancelled():
                self.stop()
                raise FishLocalError("cancelled")
            if process.poll() is not None and event_queue.empty():
                raise FishLocalError("fish_worker_exited")
            try:
                event = event_queue.get(timeout=0.15)
            except queue.Empty:
                continue
            if event.get("event") == "error":
                raise FishLocalError(str(event.get("code", "fish_native_error"))[:90])
            if event.get("event") == "worker_closed":
                raise FishLocalError("fish_worker_exited")
            if event.get("event") == expected:
                return
        self.stop()
        raise FishLocalError("fish_synthesis_timeout")

    def synthesize(self, text: str, *, reference="", transcript="", threads=0,
                   cancelled=lambda: False) -> bytes:
        valid, error = ready(reference)
        if not valid:
            raise FishLocalError(error)
        if not isinstance(text, str) or not text.strip():
            raise FishLocalError("empty_text")
        text = text.strip()
        if len(text) > 350:
            raise FishLocalError("fish_text_too_long")
        if reference and not transcript.strip():
            raise FishLocalError("fish_reference_transcript_required")
        p = paths()
        dll = choose_runtime()
        threads = max(1, min(16, int(threads or min(max(1, os.cpu_count() or 4), 8))))
        signature = (str(dll), str(p["model"]), str(p["tokenizer"]),
                     str(reference), str(transcript), threads)
        with self._guard:
            if cancelled():
                raise FishLocalError("cancelled")
            if self._signature != signature or self._process is None or self._process.poll() is not None:
                self.stop()
                event_queue = queue.Queue()
                args = [sys.executable, "-u", str(WORKER), "--dll", str(dll),
                        "--model", str(p["model"]), "--tokenizer", str(p["tokenizer"]),
                        "--reference", str(reference), "--transcript", transcript,
                        "--threads", str(threads)]
                startup = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE,
                           "stderr": subprocess.DEVNULL, "text": True,
                           "encoding": "utf-8", "errors": "replace", "bufsize": 1}
                if sys.platform == "win32":
                    startup["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                process = subprocess.Popen(args, **startup)
                self._process, self._events, self._signature = process, event_queue, signature
                self._reader = threading.Thread(target=self._listen, args=(process, event_queue),
                                                name="fish-s2-protocol", daemon=True)
                self._reader.start()
                self._await(process, event_queue, "ready", time.monotonic() + 240, cancelled)
            process, events = self._process, self._events
            self._serial += 1
            request_id = self._serial
            with tempfile.TemporaryDirectory(prefix="luxai-fish-") as folder:
                output = Path(folder) / "speech.wav"
                try:
                    process.stdin.write(json.dumps({
                        "op": "speak", "id": request_id, "text": text, "output": str(output)
                    }, ensure_ascii=False) + "\n")
                    process.stdin.flush()
                    self._await(process, events, "done", time.monotonic() + 420, cancelled)
                    if cancelled():
                        raise FishLocalError("cancelled")
                    if not output.is_file() or not (44 < output.stat().st_size <= MAX_WAV_BYTES):
                        raise FishLocalError("fish_audio_invalid")
                    with wave.open(str(output), "rb") as stream:
                        if (stream.getnchannels(), stream.getsampwidth()) != (1, 2) or not (16000 <= stream.getframerate() <= 96000):
                            raise FishLocalError("fish_audio_format")
                    return output.read_bytes()
                except (BrokenPipeError, OSError):
                    self.stop()
                    raise FishLocalError("fish_worker_exited") from None


_engine = ResidentEngine()


def synthesize(text: str, *, reference="", transcript="", threads=0, cancelled=lambda: False):
    return _engine.synthesize(text, reference=reference, transcript=transcript,
                              threads=threads, cancelled=cancelled)


def stop():
    _engine.stop()
