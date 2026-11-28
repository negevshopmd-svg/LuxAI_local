"""How long after the last word Jarvis has the command (dev only): the real VoiceListener.listen() fed in real
time by a fake microphone, with and without the 0.4.4c early answer. Uses the audio saved by stt_bench.py.

Usage: python tests/command_bench/endpoint_bench.py <bench folder> <model> [old|new|both]
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

FRAME = 480  # 30 ms at 16 kHz


class FakeStream:
    """Plays prepared audio into the listener's callback at real speed."""

    def __init__(self, audio, ends, *args, callback=None, **kwargs):
        self.audio, self.callback, self.ends = audio, callback, ends
        self.active = True
        self._thread = threading.Thread(target=self._play, daemon=True)

    def _play(self):
        started = time.perf_counter()
        for index in range(0, len(self.audio), FRAME):
            due = started + index / 16000
            delay = due - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            if index + FRAME >= self.ends["speech_end_sample"] and "speech_end" not in self.ends:
                self.ends["speech_end"] = time.perf_counter()
            chunk = self.audio[index:index + FRAME].reshape(-1, 1)
            if len(chunk) < FRAME:
                chunk = np.vstack([chunk, np.zeros((FRAME - len(chunk), 1), dtype=np.float32)])
            self.callback(chunk, FRAME, None, None)
        self.ends["played"] = True

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *args):
        self.active = False
        return False


def listener(model, early_accept):
    from luxai import voice
    item = voice.VoiceListener.__new__(voice.VoiceListener)
    item.status_callback = item.level_callback = item.capture_allowed = None
    item.interrupt_predicate = voice.is_stop_speech_command
    item.preserve_interrupt_text = False
    item._stop_event = threading.Event()
    item.prefix_enabled, item.prefix = False, "Jarvis"
    item.language, item.beam_size = "ru", 1
    item.speech_pause = 2.3
    item.sensitivity = 1.25
    item.microphone_device, item._device_info = 0, {"name": "bench", "default_samplerate": 16000}
    item.model = model
    item.early_accept = early_accept
    item.early_pause = voice.EARLY_PAUSE_SECONDS
    return item


def speech_end(audio) -> int:
    """The last sample above the noise (the end of the last word)."""
    frames = np.sqrt(np.mean(np.square(audio[: len(audio) // FRAME * FRAME].reshape(-1, FRAME)), axis=1))
    loud = np.nonzero(frames > 0.02)[0]
    return int((loud[-1] + 1) * FRAME) if len(loud) else len(audio)


def one(model, audio, early_accept):
    from luxai import voice
    ends = {"speech_end_sample": speech_end(audio)}
    padded = np.concatenate([audio, np.zeros(16000 * 4, dtype=np.float32)])
    item = listener(model, early_accept)
    result = {}
    with mock.patch.object(voice.sd, "InputStream", lambda *a, **k: FakeStream(padded, ends, *a, **k)):
        generator = item.listen()
        for text in generator:
            result["text"], result["at"] = text, time.perf_counter()
            break
        item._stop_event.set()
        try:
            generator.close()
        except Exception:
            pass
    if "at" not in result:
        return None, ""
    return result["at"] - ends.get("speech_end", result["at"]), result["text"]


def main():
    folder, name = Path(sys.argv[1]), sys.argv[2]
    mode = sys.argv[3] if len(sys.argv) > 3 else "both"
    from faster_whisper import WhisperModel
    from luxai.command_registry import CommandRegistry
    from luxai.early_command import complete
    model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=6, num_workers=1)
    registry = CommandRegistry(str(ROOT / ".bench_no_commands.json"))  # the shipped commands only
    items = [i for i in json.loads((folder / "commands.json").read_text(encoding="utf-8")) if i["language"] == "ru"]
    report = {}
    for label, accept in (("old", None), ("new", lambda text: complete(text, registry))):
        if mode not in ("both", label):
            continue
        rows = []
        for item in items:
            seconds, text = one(model, np.load(folder / item["file"]), accept)
            rows.append({"command": item["text"], "heard": text, "after_last_word_s": round(seconds or -1, 2)})
            print(label, rows[-1], flush=True)
        values = [r["after_last_word_s"] for r in rows if r["after_last_word_s"] >= 0]
        report[label] = {"mean_s": round(float(np.mean(values)), 2), "median_s": round(float(np.median(values)), 2),
                         "rows": rows}
        print(label, "mean", report[label]["mean_s"], "median", report[label]["median_s"], flush=True)
    (folder / f"endpoint_{name}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
