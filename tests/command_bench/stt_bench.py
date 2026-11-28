"""Voice-command benchmark (dev only): how long and how well each Whisper model recognises short commands.

Commands are read by the local Piper voices (ru / ro / en) with light room noise, then recognised exactly as
the listener does (``voice_rules.recognition_options``). Prints the time of one pass and the word error rate
per model, and saves the audio + texts so ``endpoint_bench.py`` can replay them.

Usage: python tests/command_bench/stt_bench.py <install folder> <out folder> [models...]
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

COMMANDS = {
    "ru": ["Открой ютуб", "Сделай громче", "Поставь таймер на пять минут", "Какая сегодня погода",
           "Выключи микрофон в дискорде", "Открой стим", "Сделай скриншот", "Закрой окно", "Который час",
           "Напомни через десять минут позвонить маме", "Следующий трек", "Открой калькулятор",
           "Покажи субтитры", "Начни конспект", "Запусти Counter-Strike", "Сверни все окна",
           "Сделай тише на двадцать процентов", "Открой папку загрузки", "Переведи на английский привет как дела",
           "Найди в интернете рецепт блинов"],
    "ro": ["Deschide YouTube", "Dă mai tare", "Pune un cronometru de cinci minute", "Cum e vremea azi",
           "Fă o captură de ecran", "Închide fereastra", "Cât e ceasul", "Pornește Steam"],
    "en": ["Open YouTube", "Turn the volume up", "Set a timer for five minutes", "What's the weather today",
           "Take a screenshot", "Close the window", "What time is it", "Launch Steam"],
}
VOICES = {"ru": "ru_RU-dmitri-medium.onnx", "ro": "ro_RO-mihai-medium.onnx", "en": "en_US-lessac-medium.onnx"}


def words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold().replace("ё", "е"))


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = words(reference), words(hypothesis)
    rows = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        previous, rows[0] = rows[0], i
        for j, h in enumerate(hyp, 1):
            previous, rows[j] = rows[j], min(rows[j] + 1, rows[j - 1] + 1, previous + (r != h))
    return rows[-1] / max(1, len(ref))


def speak(voice, text: str) -> np.ndarray:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        voice.synthesize_wav(text, wav)
    buffer.seek(0)
    with wave.open(buffer, "rb") as wav:
        rate = wav.getframerate()
        audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    if rate != 16000:
        positions = np.linspace(0, len(audio) - 1, int(len(audio) * 16000 / rate))
        audio = np.interp(positions, np.arange(len(audio)), audio).astype(np.float32)
    return audio


def build(install: Path, out: Path):
    from piper import PiperVoice
    rng = np.random.default_rng(7)
    items = []
    for language, phrases in COMMANDS.items():
        voice = PiperVoice.load(str(install / "voices" / VOICES[language]))
        for index, text in enumerate(phrases):
            audio = speak(voice, text)
            silence = np.zeros(int(0.3 * 16000), dtype=np.float32)
            audio = np.concatenate([silence, audio, silence])
            audio = audio + rng.normal(0, 0.003, len(audio)).astype(np.float32)  # a quiet room
            name = f"{language}_{index:02d}.npy"
            np.save(out / name, audio.astype(np.float32))
            items.append({"file": name, "language": language, "text": text, "seconds": round(len(audio) / 16000, 2)})
    (out / "commands.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    return items


def main():
    install, out = Path(sys.argv[1]), Path(sys.argv[2])
    models = sys.argv[3:] or ["small", "medium", "large-v3-turbo"]
    out.mkdir(parents=True, exist_ok=True)
    items = json.loads((out / "commands.json").read_text(encoding="utf-8")) if (out / "commands.json").exists() \
        else build(install, out)
    from faster_whisper import WhisperModel
    from luxai.voice_rules import recognition_options
    report = {}
    for name in models:
        model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=6, num_workers=1)
        model.transcribe(np.zeros(16000, dtype=np.float32), language="ru")  # warm up
        per_language = {}
        for item in items:
            audio = np.load(out / item["file"])
            started = time.perf_counter()
            segments, _ = model.transcribe(audio, **recognition_options(item["language"], 1))
            text = " ".join(s.text.strip() for s in segments).strip()
            seconds = time.perf_counter() - started
            row = per_language.setdefault(item["language"], {"time": [], "wer": [], "misses": []})
            row["time"].append(seconds)
            error = wer(item["text"], text)
            row["wer"].append(error)
            if error > 0:
                row["misses"].append(f"{item['text']} -> {text}")
        report[name] = {lang: {"pass_s": round(float(np.mean(r["time"])), 2), "wer": round(float(np.mean(r["wer"])), 3),
                               "misses": r["misses"]} for lang, r in per_language.items()}
        print(name, json.dumps({k: {x: v[x] for x in ("pass_s", "wer")} for k, v in report[name].items()}), flush=True)
    (out / "stt_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
