"""Offline translation (0.4.2i): NLLB-200 distilled 600M, CTranslate2 int8.

Fast (≈0.1-0.4 s per caption phrase on the CPU), private and never slowed by
a busy online provider. The model folder lives in ``models/`` next to the app
(kept by Update.bat) and is downloaded once on first use; the online model is
the fallback when it is missing or fails.

Model: facebook/nllb-200-distilled-600M (CC-BY-NC 4.0, non-commercial use),
converted by JustFrederik/nllb-200-distilled-600M-ct2-int8.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

from .local_models import MODELS_DIR

REPO = "JustFrederik/nllb-200-distilled-600M-ct2-int8"
FOLDER = "nllb-200-600M-ct2-int8"
FILES = ["config.json", "model.bin", "shared_vocabulary.txt", "tokenizer.json", "special_tokens_map.json"]
CODES = {"en": "eng_Latn", "ro": "ron_Latn", "ru": "rus_Cyrl"}
_RO_COMMA = str.maketrans("şţŞŢ", "șțȘȚ")
MAX_PIECE = 400  # characters per model call; longer text is split at sentences

_lock = threading.Lock()
_loaded: "OfflineTranslator | None" = None
_failed = False
_downloading = False


def model_dir(directory: Path | None = None) -> Path:
    return Path(directory) if directory is not None else MODELS_DIR / FOLDER


def installed(directory: Path | None = None) -> bool:
    folder = model_dir(directory)
    return all((folder / name).is_file() for name in ("model.bin", "tokenizer.json", "config.json"))


def supports(source: str, target: str) -> bool:
    return source in CODES and target in CODES and source != target


def _pieces(text: str) -> list[str]:
    """One piece per sentence (NLLB drops the first of two half-sentences), each ≤ MAX_PIECE."""
    value = " ".join(str(text or "").split())
    if not value:
        return []
    sentences = re.split(r"(?<=[.!?…])\s+", value)
    pieces, current = [], ""
    for sentence in sentences:
        if len(sentence) <= MAX_PIECE:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence)
            continue
        while len(sentence) > MAX_PIECE:
            cut = sentence.rfind(" ", 0, MAX_PIECE)
            cut = cut if cut > 0 else MAX_PIECE
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:cut])
            sentence = sentence[cut:].strip()
        if current and len(current) + 1 + len(sentence) > MAX_PIECE:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


class OfflineTranslator:
    def __init__(self, directory: Path | None = None, threads: int = 4):
        import ctranslate2
        from tokenizers import Tokenizer

        folder = model_dir(directory)
        self.tokenizer = Tokenizer.from_file(str(folder / "tokenizer.json"))
        self.translator = ctranslate2.Translator(str(folder), device="cpu", compute_type="int8",
                                                 inter_threads=1, intra_threads=threads)
        self._run = threading.Lock()

    def _tokens(self, text: str, source: str) -> list[str]:
        # NLLB source = <lang> tokens </s>; the tokenizer adds </s> but its language token
        # is fixed at build time, so the right one is set here.
        tokens = self.tokenizer.encode(text, add_special_tokens=False).tokens
        return [CODES[source]] + tokens + ["</s>"]

    def translate(self, text: str, source: str, target: str) -> str:
        if not supports(source, target):
            return ""
        pieces = _pieces(text)
        if not pieces:
            return ""
        batch = [self._tokens(piece, source) for piece in pieces]
        with self._run:
            results = self.translator.translate_batch(
                batch, target_prefix=[[CODES[target]]] * len(batch), beam_size=2,
                max_decoding_length=256, repetition_penalty=1.1, no_repeat_ngram_size=4)
        out = []
        for result in results:
            tokens = [token for token in result.hypotheses[0] if token not in CODES.values()]
            ids = [self.tokenizer.token_to_id(token) for token in tokens]
            out.append(self.tokenizer.decode([i for i in ids if i is not None], skip_special_tokens=True).strip())
        joined = " ".join(piece for piece in out if piece)
        if target == "ro":  # the model writes the old cedilla letters (ş ţ)
            joined = joined.translate(_RO_COMMA)
        return joined


def get(directory: Path | None = None) -> "OfflineTranslator | None":
    """The shared translator, loaded once (≈1 s); None when it is not installed or broken."""
    global _loaded, _failed
    if _loaded is not None:
        return _loaded
    if _failed or not installed(directory):
        return None
    with _lock:
        if _loaded is None and not _failed:
            try:
                _loaded = OfflineTranslator(directory)
            except Exception:
                _failed = True
    return _loaded


def ensure_downloaded(directory: Path | None = None) -> bool:
    """Download the model (≈640 MB) once, in the calling thread. True when it is ready."""
    global _downloading
    if installed(directory):
        return True
    with _lock:
        if _downloading:
            return False
        _downloading = True
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(REPO, local_dir=str(model_dir(directory)), allow_patterns=FILES)
    except Exception:
        return False
    finally:
        _downloading = False
    return installed(directory)


def download_in_background(directory: Path | None = None):
    import os
    if installed(directory) or _downloading or os.environ.get("LUXAI_NO_DOWNLOADS"):
        return
    threading.Thread(target=ensure_downloaded, args=(directory,), daemon=True,
                     name="JarvisTranslatorDownload").start()


def translate(text: str, source: str, target: str) -> str | None:
    """Offline translation, or None when it is not possible here (the caller falls back)."""
    if not supports(source, target):
        return None
    translator = get()
    if translator is None:
        return None
    try:
        return translator.translate(text, source, target) or None
    except Exception:
        return None
