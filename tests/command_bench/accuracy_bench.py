"""Fewer recognition errors without a slower pass (dev only, 0.4.4d).

Sets:
- ``tuning``: the 20 Russian commands of ``stt_bench.py`` (Piper voice);
- ``held``: 129 OTHER commands (``phrases_ru.py``: Steam, Discord, apps, web, media, windows, timers, weather,
  Jarvis' own features, keys) read in turn by three different Russian voices — Piper «dmitri», Windows «Irina»
  and «Pavel» — fast / normal / slow, quiet / normal / loud microphone, three room-noise levels and, for a third
  of them, a small room echo. A change must help here, not only on the set it was tuned on.

Scores: word errors (``wer``, names written in Latin or Cyrillic count as the same word: «Discord» = «дискорде»),
``verb``: the share of commands whose FIRST word is wrong (the dangerous error: «Открой» heard as «Закрой»), and
the median time of one pass. A variant slower than ``now`` does not count as a win.

Usage: python tests/command_bench/accuracy_bench.py <install folder> <bench folder> <model> [variant...]
"""
from __future__ import annotations

import json
import re
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from phrases_ru import PHRASES  # noqa: E402
from stt_bench import speak  # noqa: E402

# The same word in either alphabet / any case ending; digits as words. Applied to the reference AND the result.
ALIASES = [
    (r"\b(?:youtube|ютуб\w*)", "ютуб"), (r"\b(?:discord\w*|дискорд\w*)", "дискорд"), (r"\b(?:steam|стим\w*)", "стим"),
    (r"\b(?:telegram|телеграм\w*)", "телеграм"), (r"\b(?:dota|дот[аыу])\b", "дота"), (r"\b(?:chrome|хром)\b", "хром"),
    (r"\b(?:counter[\s-]?strike|контр\w*[\s-]?страйк)", "контрстрайк"), (r"\b(?:war thunder|вар тандер)", "вартандер"),
    (r"\b(?:spotify|спотифа\w*)", "спотифай"), (r"\b(?:obs|обс)\b", "обс"), (r"\b(?:paint|пейнт)\b", "пейнт"),
    (r"\b(?:word|ворд)\b", "ворд"), (r"\b(?:excel|эксель)\b", "эксель"), (r"\b(?:twitch|твич)\b", "твич"),
    (r"\b(?:google|гугл\w*)", "гугл"), (r"\b(?:wikipedia|википеди\w*)", "википедия"), (r"\b(?:jarvis\w*|джарвис\w*)", "джарвис"),
    (r"\b(?:enter|энтер)\b", "энтер"), (r"\b(?:escape|эскейп)\b", "эскейп"), (r"\b(?:detroit|детройт)\b", "детройт"),
    (r"\bq\b|\bку\b", "ку"),
]
NUMBERS = [("20%", "двадцать процентов"), ("10%", "десять процентов"), ("50", "пятьдесят"), ("20", "двадцать"),
           ("10", "десять"), ("5", "пять"), ("2", "два"), ("7", "семь"), ("8", "восемь"), ("%", " процентов")]


def words(text: str) -> list[str]:
    value = str(text).casefold().replace("ё", "е")
    for digit, word in NUMBERS:
        value = value.replace(digit, " " + word + " ")
    for pattern, word in ALIASES:
        value = re.sub(pattern, word, value)
    return re.findall(r"\w+", value)


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = words(reference), words(hypothesis)
    rows = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        previous, rows[0] = rows[0], i
        for j, h in enumerate(hyp, 1):
            previous, rows[j] = rows[j], min(rows[j] + 1, rows[j - 1] + 1, previous + (r != h))
    return rows[-1] / max(1, len(ref))


def first_word_wrong(reference: str, hypothesis: str) -> bool:
    ref, hyp = words(reference), words(hypothesis)
    return bool(ref) and (not hyp or hyp[0] != ref[0])


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav:
        rate, width = wav.getframerate(), wav.getsampwidth()
        audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        if wav.getnchannels() == 2:
            audio = audio.reshape(-1, 2).mean(axis=1)
    if rate != 16000:
        positions = np.linspace(0, len(audio) - 1, int(len(audio) * 16000 / rate))
        audio = np.interp(positions, np.arange(len(audio)), audio).astype(np.float32)
    assert width == 2
    return audio


def windows_voice(name: str, text: str, rate: int, path: Path) -> np.ndarray:
    """A Windows (OneCore) Russian voice through SAPI, written to a 16 kHz wav."""
    import comtypes.client as cc
    voice = cc.CreateObject("SAPI.SpVoice")
    category = cc.CreateObject("SAPI.SpObjectTokenCategory")
    category.SetId(r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices", False)
    tokens = category.EnumerateTokens()
    voice.Voice = next(tokens.Item(i) for i in range(tokens.Count) if name in tokens.Item(i).GetDescription())
    stream = cc.CreateObject("SAPI.SpFileStream")
    audio_format = cc.CreateObject("SAPI.SpAudioFormat")
    audio_format.Type = 18  # SAFT16kHz16BitMono
    stream.Format = audio_format
    stream.Open(str(path), 3, False)
    voice.AudioOutputStream = stream
    voice.Rate = rate
    voice.Speak(text, 0)
    stream.Close()
    return read_wav(path)


def piper_voice(voice, text: str, scale: float) -> np.ndarray:
    try:
        from piper import SynthesisConfig
    except ImportError:
        return speak(voice, text)
    import io
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        voice.synthesize_wav(text, wav, syn_config=SynthesisConfig(length_scale=scale))
    buffer.seek(0)
    tmp = Path(__file__).resolve().parent / "_piper_tmp.wav"
    tmp.write_bytes(buffer.getvalue())
    try:
        return read_wav(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def room(audio: np.ndarray, rng) -> np.ndarray:
    """A small room: a 0.25 s decaying echo."""
    length = int(0.25 * 16000)
    response = rng.normal(0, 1, length).astype(np.float32) * np.exp(-np.arange(length) / (0.05 * 16000))
    response[0] = 1.0
    response[1:] *= 0.08
    wet = np.convolve(audio, response)[: len(audio)]
    return (wet / max(1e-6, np.max(np.abs(wet))) * np.max(np.abs(audio))).astype(np.float32)


def build_held_out(install: Path, folder: Path) -> list[dict]:
    path = folder / "held_out_v2.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    from piper import PiperVoice
    piper = PiperVoice.load(str(install / "voices" / "ru_RU-dmitri-medium.onnx"))
    rng = np.random.default_rng(11)
    items, index = [], 0
    for group, phrases in PHRASES.items():
        for text in phrases:
            speaker = ("dmitri", "Irina", "Pavel")[index % 3]
            pace = (index // 3) % 3  # fast / normal / slow
            if speaker == "dmitri":
                audio = piper_voice(piper, text, (0.85, 1.0, 1.2)[pace])
            else:
                audio = windows_voice(speaker, text, (2, 0, -2)[pace], folder / "_sapi.wav")
            audio = audio / max(1e-6, float(np.max(np.abs(audio))))
            audio = audio * (0.12, 0.4, 0.9)[(index // 2) % 3]  # quiet / normal / loud microphone
            if index % 3 == 1:
                audio = room(audio, rng)
            silence = np.zeros(int(0.3 * 16000), dtype=np.float32)
            audio = np.concatenate([silence, audio, silence])
            audio = audio + rng.normal(0, (0.003, 0.006, 0.01)[(index // 5) % 3], len(audio)).astype(np.float32)
            name = f"held2_{index:03d}.npy"
            np.save(folder / name, audio.astype(np.float32))
            items.append({"file": name, "language": "ru", "text": text, "group": group, "voice": speaker})
            index += 1
    (folder / "_sapi.wav").unlink(missing_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    return items


# Candidate prompts (general command vocabulary, never the bench phrases word for word).
PROMPTS = {
    # «Закрой окно» in the 0.4.4c prompt may pull «Открой» towards «Закрой»; the verb is said first here.
    "p_open_first": ("Джарвис, открой YouTube. Открой Discord, Steam, Telegram, калькулятор. "
                     "Сделай громче. Сделай тише. Поставь таймер. Сделай скриншот. Закрой окно."),
    # A short dialogue: Whisper continues the style of the prompt (punctuation, Latin app names, digits).
    "p_dialogue": ("Джарвис, открой YouTube. — Открываю. Сделай погромче. — Громкость 60%. "
                   "Поставь таймер на 5 минут. Открой Discord и Steam. Покажи субтитры. Закрой окно."),
    # More of the vocabulary of the assistant's own features.
    "p_wide": ("Разговор с голосовым помощником Джарвис. Открой YouTube, Discord, Steam, Telegram, калькулятор, "
               "папку «Загрузки». Сделай громче, сделай тише, следующий трек. Поставь таймер. Сделай скриншот. "
               "Покажи субтитры. Начни конспект. Найди в интернете. Переведи на английский. Закрой окно."),
}


def variants():
    from luxai import voice_rules
    base = voice_rules.recognition_options("ru", 1)
    out = {
        "now": base,
        "no_timestamps": dict(base, without_timestamps=True),
        "chunk15": dict(base, chunk_length=15),
        "chunk10": dict(base, chunk_length=10),
        "hotwords": dict(base, hotwords="Джарвис Открой Сделай YouTube Discord Steam Telegram"),
    }
    for label, prompt in PROMPTS.items():
        out[label] = dict(base, initial_prompt=prompt)
    extra = getattr(voice_rules, "BENCH_VARIANTS", {})
    out.update({label: dict(base, **options) for label, options in extra.items()})
    return out


def transcribe_all(model, items, folder, options):
    """(texts, seconds) — or an error string for an option this faster-whisper does not take."""
    from luxai.voice import VoiceListener
    texts, times = [], []
    for item in items:
        audio = VoiceListener._normalize_audio(np.load(folder / item["file"]))
        started = time.perf_counter()
        try:
            segments, _ = model.transcribe(audio, **options)
            texts.append(" ".join(s.text.strip() for s in segments).strip())
        except Exception as error:
            return f"{type(error).__name__}: {error}", []
        times.append(time.perf_counter() - started)
    return texts, times


def score(items, texts, times, fix=None):
    errors, verbs, misses, groups = [], [], [], {}
    for item, text in zip(items, texts):
        if fix is not None:
            text = fix(text)
        error, verb = wer(item["text"], text), first_word_wrong(item["text"], text)
        errors.append(error)
        verbs.append(verb)
        groups.setdefault(item.get("group", "tuning"), []).append(error)
        if error:
            misses.append(f"[{item.get('voice', 'dmitri')}] {item['text']} -> {text}")
    return {"wer": round(float(np.mean(errors)), 3), "verb": round(float(np.mean(verbs)), 3),
            "pass_s": round(float(np.median(times)), 2),
            "groups": {g: round(float(np.mean(v)), 3) for g, v in groups.items()}, "misses": misses,
            "texts": list(texts)}


def main():
    install, folder, name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    wanted = sys.argv[4:]
    tuning = [i for i in json.loads((folder / "commands.json").read_text(encoding="utf-8")) if i["language"] == "ru"]
    held = build_held_out(install, folder)
    print("held", len(held), "tuning", len(tuning), flush=True)
    if wanted == ["build"]:
        return
    from faster_whisper import WhisperModel
    model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=6, num_workers=1)
    model.transcribe(np.zeros(16000, dtype=np.float32), language="ru")
    from luxai import voice_rules
    fix = getattr(voice_rules, "fix_command_words", None)
    out_path = folder / f"accuracy_{name}.json"
    report = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    for label, options in variants().items():
        if wanted and label not in wanted:
            continue
        for set_name, items in (("tuning", tuning), ("held", held)):
            texts, times = transcribe_all(model, items, folder, options)
            if isinstance(texts, str):
                print(name, label, "error", texts, flush=True)
                break
            for suffix, fixer in (("", None), ("+fix", fix)):
                if suffix and fixer is None:
                    continue
                row = score(items, texts, times, fixer)
                report[f"{label}{suffix}/{set_name}"] = row
                print(name, label + suffix, set_name,
                      {k: v for k, v in row.items() if k in ("wer", "verb", "pass_s")}, flush=True)
            out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
