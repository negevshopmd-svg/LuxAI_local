"""Which recognition setup understands Russian commands best (dev only): no prompt / a command prompt /
more silence before the phrase. Replays the audio saved by stt_bench.py.

Usage: python tests/command_bench/prompt_bench.py <bench folder> <model>
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from stt_bench import wer  # noqa: E402

NUMBERS = {"5": "пять", "10": "десять", "20": "двадцать", "20%": "двадцать процентов"}


def normalized(text: str) -> str:
    """Digits are fine for commands («5 минут» = «пять минут»): compare words, not spelling of numbers."""
    for digit, word in sorted(NUMBERS.items(), key=lambda item: -len(item[0])):
        text = text.replace(digit, word)
    return text


def run(model, items, folder, options, pad=0.0):
    errors, times, misses = [], [], []
    for item in items:
        audio = np.load(folder / item["file"])
        if pad:
            audio = np.concatenate([np.zeros(int(pad * 16000), dtype=np.float32), audio])
        started = time.perf_counter()
        segments, _ = model.transcribe(audio, **options)
        text = " ".join(s.text.strip() for s in segments).strip()
        times.append(time.perf_counter() - started)
        error = wer(item["text"], normalized(text))
        errors.append(error)
        if error:
            misses.append(f"{item['text']} -> {text}")
    return round(float(np.mean(errors)), 3), round(float(np.mean(times)), 2), misses


def main():
    folder, name = Path(sys.argv[1]), sys.argv[2]
    from faster_whisper import WhisperModel
    from luxai.voice_rules import recognition_options
    items = [i for i in json.loads((folder / "commands.json").read_text(encoding="utf-8")) if i["language"] == "ru"]
    model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=6, num_workers=1)
    base = recognition_options("ru", 1)
    try:
        from luxai.voice_rules import RUSSIAN_PROMPT
    except ImportError:
        RUSSIAN_PROMPT = ("Разговор с голосовым помощником Джарвис. Открой YouTube, Discord, Steam, калькулятор. "
                          "Сделай громче, сделай тише. Поставь таймер. Сделай скриншот. Закрой окно.")
    variants = {"now": (base, 0.0), "prompt": (dict(base, initial_prompt=RUSSIAN_PROMPT), 0.0),
                "pad": (base, 0.4), "prompt+pad": (dict(base, initial_prompt=RUSSIAN_PROMPT), 0.4)}
    report = {}
    for label, (options, pad) in variants.items():
        error, seconds, misses = run(model, items, folder, options, pad)
        report[label] = {"wer": error, "pass_s": seconds, "misses": misses}
        print(name, label, "wer", error, "pass", seconds, flush=True)
    (folder / f"prompt_{name}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
