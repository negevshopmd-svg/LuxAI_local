"""How long one Whisper pass takes and how accurate it is, per model and encoder window (chunk_length).

Whisper encodes a 30 s window for any phrase; a shorter window (faster-whisper ``chunk_length``) costs less per
pass. Every corpus sentence is transcribed on its own (like a finished caption phrase).

    python tests/captions_bench/window_bench.py <corpus folder> <model> <chunk lengths, e.g. 30,15,10>
"""
from __future__ import annotations

import json
import re
import sys
import time
import wave
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

corpus, name, chunks = Path(sys.argv[1]), sys.argv[2], [int(value) for value in sys.argv[3].split(",")]
SR = 16000


def words(text):
    return re.findall(r"\w+", text.casefold().replace("ё", "е"))


def errors(ref, hyp):
    rows, cols = len(ref) + 1, len(hyp) + 1
    cost = np.zeros((rows, cols), dtype=np.int32)
    cost[:, 0], cost[0, :] = np.arange(rows), np.arange(cols)
    for i in range(1, rows):
        for j in range(1, cols):
            cost[i, j] = min(cost[i - 1, j] + 1, cost[i, j - 1] + 1, cost[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]))
    return int(cost[-1, -1])


model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=6)
list(model.transcribe(np.zeros(SR, dtype=np.float32), language="en")[0])
for chunk in chunks:
    for language in ("en", "ru", "ro"):
        reference = json.loads((corpus / f"{language}.json").read_text(encoding="utf-8"))
        with wave.open(str(corpus / f"{language}.wav"), "rb") as wav:
            stream = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        total_errors = total_words = 0
        seconds = []
        for sentence in reference["sentences"]:
            audio = stream[int((sentence["start"] - 0.2) * SR):int((sentence["end"] + 0.3) * SR)]
            started = time.monotonic()
            segments, _info = model.transcribe(audio, language=language, beam_size=1, best_of=1, temperature=0.0,
                                               without_timestamps=True, condition_on_previous_text=False,
                                               chunk_length=chunk, vad_filter=False)
            text = " ".join(segment.text for segment in segments)
            seconds.append(time.monotonic() - started)
            ref = words(sentence["text"])
            total_errors += errors(ref, words(text))
            total_words += len(ref)
        print(json.dumps({"model": name, "chunk": chunk, "language": language,
                          "wer": round(total_errors / total_words, 3),
                          "pass_s": round(float(np.median(seconds)), 2)}))
