"""Live-captions benchmark: feed a corpus stream IN REAL TIME through CaptionEngine (the app's «Hybrid» setup)
and measure what a viewer sees.

    python tests/captions_bench/run_bench.py <code folder> <corpus folder> <lang> [auto|fixed] [result.json]

<code folder> is the checkout whose ``luxai`` is measured (so an older version can be measured the same way).
Metrics (stream time = seconds of audio played so far):
- wer_draft / wer_final: word error rate of the lines before / after the precise correction (lower is better);
- lost_words: reference words with no counterpart in the final text (deletions);
- first_words_s: from a sentence's start until its first word is on the bar (draft or line);
- line_lag_s: from the end of a phrase until its finished line appears;
- fix_lag_s: from the end of a phrase until its correction arrives.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np

code, corpus, language = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
mode = sys.argv[4] if len(sys.argv) > 4 else "auto"
result_path = Path(sys.argv[5]) if len(sys.argv) > 5 else None
sys.path.insert(0, str(code))

from luxai import live_captions as lc  # noqa: E402

SR = lc.SAMPLE_RATE
reference = json.loads((corpus / f"{language}.json").read_text(encoding="utf-8"))
with wave.open(str(corpus / f"{language}.wav"), "rb") as wav:
    stream = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0

spoken = None if mode == "auto" else language
draft_name, precise_name = lc.hybrid_draft_model(spoken), lc.hybrid_precise_model(spoken)
import os  # noqa: E402
draft_threads, precise_threads = (int(value) for value in os.environ.get("BENCH_THREADS", "6,8").split(","))
draft_model = lc.caption_model(draft_name, threads=draft_threads)
precise_model = lc.caption_model(precise_name, threads=precise_threads)
for model in (draft_model, precise_model):  # warm up: model loading is not part of the steady-state numbers
    list(model.transcribe(np.zeros(SR, dtype=np.float32), language="en")[0])

fed = {"samples": 0}
events = []  # (kind, stream seconds, payload)
phrase_end = {}  # draft text -> stream seconds where its audio ended
lock = threading.Lock()


def now_s() -> float:
    return fed["samples"] / SR


original_take = lc.PhraseSegmenter.take


def take(self, until=None):
    audio = original_take(self, until)
    end = (fed["samples"] - len(self.buffer) - len(self._pending)) / SR
    self._bench_last_end = end
    return audio


lc.PhraseSegmenter.take = take
engine_holder = {}


def on_partial(text):
    if text:
        with lock:
            events.append(("partial", now_s(), text))


def on_final(text):
    with lock:
        end = getattr(engine_holder["engine"].segmenter, "_bench_last_end", now_s())
        phrase_end.setdefault(text, end)
        events.append(("final", now_s(), (text, end)))


def on_correct(draft, precise):
    with lock:
        events.append(("correct", now_s(), (draft, precise, phrase_end.get(draft))))


def on_correct_many(drafts, new_lines):
    with lock:
        ends = [phrase_end[draft] for draft in drafts if draft in phrase_end]
        events.append(("correct_many", now_s(), (list(drafts), list(new_lines), max(ends) if ends else None)))


import inspect  # noqa: E402
extra = {"on_correct_many": on_correct_many} if "on_correct_many" in inspect.signature(lc.CaptionEngine).parameters else {}
engine = lc.CaptionEngine(lambda: draft_model, spoken, on_partial, on_final,
                          precise_provider=lambda: precise_model, on_correct=on_correct, **extra)
engine_holder["engine"] = engine
engine.start()
chunk = int(SR * 0.03)
started = time.monotonic()
for offset in range(0, len(stream), chunk):
    target = started + offset / SR
    delay = target - time.monotonic()
    if delay > 0:
        time.sleep(delay)
    piece = stream[offset:offset + chunk]
    engine.feed(piece)
    fed["samples"] = offset + len(piece)
# let the last phrase finish and its correction arrive (silence keeps flowing like a paused video)
tail_end = time.monotonic() + 20
silence = np.zeros(chunk, dtype=np.float32)
while time.monotonic() < tail_end:
    time.sleep(0.03)
    engine.feed(silence)
    fed["samples"] += chunk
engine.stop()
time.sleep(0.5)

# -- the lines as the bar shows them at the end ------------------------------------------------------------
lines = []
for kind, _at, payload in events:
    if kind == "final":
        lines.append(payload[0])
    elif kind == "correct":
        draft, precise, _end = payload
        if not draft:
            lines.append(precise)
        elif draft in lines:
            lines[len(lines) - 1 - lines[::-1].index(draft)] = precise
    elif kind == "correct_many":
        drafts, new_lines, _end = payload
        drafts = [draft for draft in drafts if draft]
        if not drafts:
            lines.extend(new_lines)
            continue
        for index in range(len(lines) - len(drafts), -1, -1):
            if lines[index:index + len(drafts)] == drafts:
                lines[index:index + len(drafts)] = new_lines
                break
drafts = [payload[0] for kind, _at, payload in events if kind == "final"]


def words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold().replace("ё", "е"))


def align(ref: list[str], hyp: list[str]):
    """(substitutions, deletions, insertions) of the word alignment."""
    rows, cols = len(ref) + 1, len(hyp) + 1
    cost = np.zeros((rows, cols), dtype=np.int32)
    cost[:, 0] = np.arange(rows)
    cost[0, :] = np.arange(cols)
    for i in range(1, rows):
        for j in range(1, cols):
            cost[i, j] = min(cost[i - 1, j] + 1, cost[i, j - 1] + 1, cost[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]))
    i, j, subs, dels, ins = len(ref), len(hyp), 0, 0, 0
    while i or j:
        if i and j and cost[i, j] == cost[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]):
            subs += ref[i - 1] != hyp[j - 1]
            i, j = i - 1, j - 1
        elif i and cost[i, j] == cost[i - 1, j] + 1:
            dels, i = dels + 1, i - 1
        else:
            ins, j = ins + 1, j - 1
    return subs, dels, ins


ref_words = [word for sentence in reference["sentences"] for word in words(sentence["text"])]


def wer(hypothesis_lines):
    subs, dels, ins = align(ref_words, [word for line in hypothesis_lines for word in words(line)])
    return round((subs + dels + ins) / len(ref_words), 3), dels


wer_draft, _ = wer(drafts)
wer_final, lost = wer(lines)

first_words = []
for sentence in reference["sentences"]:
    head = [word for word in words(sentence["text"]) if len(word) > 2][:2]
    hits = [at for kind, at, payload in events if kind in ("partial", "final") and at >= sentence["start"]
            and any(word in words(payload if isinstance(payload, str) else payload[0]) for word in head)]
    if hits:
        first_words.append(min(hits) - sentence["start"])
line_lags = [at - payload[1] for kind, at, payload in events if kind == "final"]
fix_lags = [at - payload[2] for kind, at, payload in events if kind in ("correct", "correct_many")
            and payload[2] is not None]


def summary(values):
    return {"median": round(statistics.median(values), 2), "max": round(max(values), 2)} if values else None


result = {"language": language, "mode": mode, "models": [draft_name, precise_name], "ref_words": len(ref_words),
          "wer_draft": wer_draft, "wer_final": wer_final, "lost_words": lost, "lines": len(lines),
          "partials": sum(1 for kind, _a, _p in events if kind == "partial"),
          "corrections": sum(1 for kind, _a, _p in events if kind in ("correct", "correct_many")),
          "first_words_s": summary(first_words), "line_lag_s": summary(line_lags), "fix_lag_s": summary(fix_lags),
          "dropped_s": round(getattr(engine.segmenter, "dropped_seconds", 0.0), 1),
          "detected": [engine.detected, engine._confident, {k: round(v, 2) for k, v in engine._votes.items()}],
          "final_text": lines}
print(json.dumps({key: value for key, value in result.items() if key != "final_text"}, ensure_ascii=False))
if result_path:
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
