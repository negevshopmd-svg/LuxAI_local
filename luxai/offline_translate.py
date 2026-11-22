"""Offline translation (0.4.2i): NLLB-200 distilled 600M, CTranslate2 int8.

The only translator of Jarvis (0.4.2j): ≈0.3-0.8 s per sentence on the CPU,
nothing leaves the PC. The model folder lives in ``models/`` next to the app
(kept by Update.bat) and is downloaded once, in the background, on first use.
Ten languages both ways (ru uk en ro de fr es it pt pl); captions and reading translate into ru/en/ro.

Model: facebook/nllb-200-distilled-600M (CC-BY-NC 4.0, non-commercial use),
converted by JustFrederik/nllb-200-distilled-600M-ct2-int8.
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path

from .local_models import MODELS_DIR

REPO = "JustFrederik/nllb-200-distilled-600M-ct2-int8"
FOLDER = "nllb-200-600M-ct2-int8"
FILES = ["config.json", "model.bin", "shared_vocabulary.txt", "tokenizer.json", "special_tokens_map.json"]
REVISION = "302d78f00e6fdb50a1064059df7c392b735e9d05"  # pinned commit: a changed repo is never picked up
SHA256 = {  # SHA-256 of every file of that commit (LFS objects and the small files)
    "model.bin": "ed1beaf75134de7505315a5223162f56acff397eff6b50638a500d3936fe707b",
    "tokenizer.json": "e316b82de11d0f951f370943b3c438311629547285129b0b81dadabd01bca665",
    # Audit 7 #42: the configuration and vocabulary are checked too — a damaged config.json made the
    # translator fail while the repair still called the installation good. (Measured at REVISION.)
    "config.json": "0c2f6fa2057c7264d052fb4a62ba3476eeae70487acddfa8e779a53a00cbf44c",
    "shared_vocabulary.txt": "a132a83330f45514c2476eb81d1d69b3c41762264d16ce0a7ea982e5d6c728e5",
    "special_tokens_map.json": "992bd4ed610d644d6823081937bcc91bb8878dd556cea4ae5327f2480361330e",
}
CODES = {"en": "eng_Latn", "ro": "ron_Latn", "ru": "rus_Cyrl", "uk": "ukr_Cyrl", "de": "deu_Latn",
         "fr": "fra_Latn", "es": "spa_Latn", "it": "ita_Latn", "pt": "por_Latn", "pl": "pol_Latn"}
TARGETS = tuple(CODES)  # captions / reading use ru/en/ro; the chat may ask for any of these
_WORDS = {
    "en": set("""the a an and or of to in on for with is are was were be been it this that you your we our they
their he she his her i my me not no yes but if then than as at by from have has had do does did will would can
could should about there what which who when where how all so too very just also into over after before because
don't it's i'm we're you're going get got""".split()),
    "ro": set("""și si sau de la în in pe cu din pentru este sunt era au a fost fi nu da dar dacă daca că ca care ce
cum când cand unde mai foarte doar acest această aceasta acesta aceste lui ei el ea noi voi ele lor meu mea tău tau
său un o unei unui al ale prin după dupa până pana fără fara despre mâine azi vom merge uita""".split()),
    "de": set("""der die das und ist nicht ich du wir sie ein eine einen mit auf für von zu den dem des auch sich es
wird werden morgen deshalb wir fahren deine dein mein nur noch schon aber oder wenn dass bin bist sind war""".split()),
    "fr": set("""le la les et est une un des pas je tu nous vous il elle que qui dans pour avec sur ce ne n' c'est
alors demain fera mais très ou où au aux du sont suis avons oublie veux dire ça""".split()),
    "es": set("""el los las y es una un que no yo tú nosotros con por para del en se lo como pero más muy está hay
porque mañana vamos así olvides tu su sus mi hará estoy son fue también ya sé qué quieres decir gracias
muchas hola bueno ahora aquí""".split()),
    "it": set("""il lo gli e è una un che non io tu noi con per del della di in si come ma sono domani andiamo
montagna dimenticare giacca anche questo questa molto sempre perché so cosa vuoi dire grazie mille
ci sarà quindi ciao bene adesso qui""".split()),
    "pt": set("""o os as e é uma um que não eu você nós com por para do da em se como mas são amanhã vamos
esqueça jaqueta também muito está isso então""".split()),
    "pl": set("""i w nie jest to się na że z do jak ale co tak jestem są tego czy jutro będzie więc jedziemy
zapomnij kurtki""".split()),
}
_LETTERS = {"ro": "ăâîșțşţ", "de": "äöüß", "fr": "çœèêëàùû", "es": "ñ¿¡", "it": "", "pt": "ãõ",
            "pl": "ąęłńśźż"}
_RO_COMMA = str.maketrans("şţŞŢ", "șțȘȚ")
# One-word phrases: NLLB was trained on subtitles and turns «Да.» into «- Da, da. - Ce?».
_SHORT = {
    "yes": ("Yes", "Da", "Да"), "no": ("No", "Nu", "Нет"), "ok": ("OK", "Bine", "Хорошо"),
    "thanks": ("Thank you", "Mulțumesc", "Спасибо"), "hello": ("Hello", "Salut", "Привет"),
    "bye": ("Bye", "Pa", "Пока"), "sorry": ("Sorry", "Scuze", "Извините"),
}
_SHORT_WORDS = {
    "yes": "yes yeah yep da да ага так ja oui sí sì sim tak",
    "no": "no nope nu нет неа ні nein non não nie",
    "ok": "ok okay окей ок ладно bine хорошо добре gut d'accord vale dobrze",
    "thanks": "thanks mersi mulțumesc mulţumesc multumesc спасибо дякую danke merci gracias grazie obrigado obrigada dziękuję",
    "hello": "hi hello hey salut bună buna привет привіт здравствуйте hallo bonjour hola ciao olá oi cześć",
    "bye": "bye goodbye pa пока tschüss adiós adios arrivederci tchau",
    "sorry": "sorry scuze pardon извините простите вибачте entschuldigung perdón perdon scusa desculpa przepraszam",
}
_SHORT_LOOKUP = {}
for _meaning, _words in _SHORT_WORDS.items():
    for _word in _words.split():
        _SHORT_LOOKUP[_word] = _meaning
_SHORT_LOOKUP.update({"thank you": "thanks", "la revedere": "bye", "au revoir": "bye", "va bene": "ok",
                      "tudo bem": "ok", "до свидания": "bye"})


def _short_answer(piece: str, target: str) -> str | None:
    """A known one-word phrase («Да.», «Thanks!») in the target language, or None."""
    match = re.fullmatch(r"\s*[-–—]?\s*(.*?)\s*([.!?…]*)\s*", piece)
    core = (match.group(1) if match else piece).casefold().strip(" ,")
    meaning = _SHORT_LOOKUP.get(core)
    if meaning is None or target not in ("en", "ro", "ru"):
        return None
    word = _SHORT[meaning][{"en": 0, "ro": 1, "ru": 2}[target]]
    return word + (match.group(2) if match else "")
MAX_PIECE = 400  # characters per model call; longer text is split at sentences

_lock = threading.Lock()
_loaded: "OfflineTranslator | None" = None
_loaded_signature = None  # the files the loaded translator came from
_failed: tuple | None = None   # signature (size, mtime) of the model that failed to load
_downloading = False


def model_dir(directory: Path | None = None) -> Path:
    return Path(directory) if directory is not None else MODELS_DIR / FOLDER


def installed(directory: Path | None = None) -> bool:
    folder = model_dir(directory)
    return all((folder / name).is_file() for name in SHA256)


def supports(source: str, target: str) -> bool:
    return source in CODES and target in TARGETS and source != target


def source_language(text: str) -> str:
    """The language code of ``text`` for the model, or "" when it cannot be told."""
    value = str(text or "")
    letters = re.findall(r"[^\W\d_]", value)
    if len(letters) < 3:
        return ""
    cyrillic = sum(1 for char in letters if "\u0400" <= char <= "\u04ff")
    if cyrillic / len(letters) > 0.3:
        ukrainian = len(re.findall(r"[іїєґ]", value.casefold()))
        russian = len(re.findall(r"[ыэъё]", value.casefold()))
        return "uk" if ukrainian > russian else "ru"
    lowered = value.casefold()
    words = re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)?", lowered)
    scores = {code: sum(1 for word in words if word in vocabulary) for code, vocabulary in _WORDS.items()}
    for code, marks in _LETTERS.items():
        scores[code] += 2 * sum(lowered.count(mark) for mark in marks)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "en"


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
        out = [_short_answer(piece, target) for piece in pieces]
        todo = [index for index, done in enumerate(out) if done is None]
        if todo:
            batch = [self._tokens(pieces[index], source) for index in todo]
            # A translation is rarely 3× longer than its source: a cap stops invented continuations.
            longest = max(len(tokens) for tokens in batch)
            with self._run:
                results = self.translator.translate_batch(
                    batch, target_prefix=[[CODES[target]]] * len(batch), beam_size=2,
                    max_decoding_length=min(256, 3 * longest + 8), repetition_penalty=1.1, no_repeat_ngram_size=4)
            for index, result in zip(todo, results):
                tokens = [token for token in result.hypotheses[0] if token not in CODES.values()]
                ids = [self.tokenizer.token_to_id(token) for token in tokens]
                value = self.tokenizer.decode([i for i in ids if i is not None], skip_special_tokens=True).strip()
                out[index] = re.sub(r"^[-–—]\s+", "", value)  # subtitle dialogue dash
        joined = re.sub(r"\s+([.,!?;:…])", lambda match: match.group(1), " ".join(piece for piece in out if piece))
        if target == "ro":  # the model writes the old cedilla letters (ş ţ)
            joined = joined.translate(_RO_COMMA)
        return joined


def _signature(directory: Path | None = None) -> tuple | None:
    """Size and time of EVERY file the translator needs (audit 2 #30): repairing only the tokenizer or the
    configuration also counts as a change."""
    folder = model_dir(directory)
    parts = []
    for name in sorted(SHA256):
        try:
            stat = (folder / name).stat()
        except OSError:
            return None
        parts.append((name, stat.st_size, stat.st_mtime_ns))
    return tuple(parts)


def get(directory: Path | None = None) -> "OfflineTranslator | None":
    """The shared translator, loaded once (≈1 s); None when it is not installed or broken.

    A model that failed to load is tried again only after its files changed
    (a repair); a damaged model is checked and repaired in the background.
    """
    global _loaded, _failed, _loaded_signature
    signature = _signature(directory)
    if _loaded is not None:
        if signature == _loaded_signature or signature is None:
            return _loaded
        with _lock:  # the files were replaced (repair/update): load the new ones
            _loaded = None
    if not installed(directory):
        return None
    if _failed is not None and _failed == signature:
        return None
    with _lock:
        if _loaded is None:
            try:
                _loaded = OfflineTranslator(directory)
                _loaded_signature = signature
                _failed = None
            except Exception:
                _failed = signature
                broken = True
            else:
                broken = False
    if _loaded is None and broken:
        repair_in_background(directory)
    return _loaded


def repair_in_background(directory: Path | None = None) -> None:
    """A model that does not load: verify the files; damaged ones are deleted and downloaded again."""
    def work():
        if not verified(directory):
            for name in SHA256:
                try:
                    (model_dir(directory) / name).unlink(missing_ok=True)
                except OSError:
                    pass
            download_in_background(directory)

    if not os.environ.get("LUXAI_NO_DOWNLOADS"):
        threading.Thread(target=work, daemon=True, name="JarvisTranslatorRepair").start()


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
        folder = model_dir(directory)
        snapshot_download(REPO, revision=REVISION, local_dir=str(folder), allow_patterns=FILES)
        if not verified(directory):
            for name in SHA256:  # a damaged or swapped file is never loaded
                (folder / name).unlink(missing_ok=True)
            return False
    except Exception:
        return False
    finally:
        _downloading = False
    return installed(directory)


def verified(directory: Path | None = None) -> bool:
    import hashlib
    folder = model_dir(directory)
    for name, expected in SHA256.items():
        digest = hashlib.sha256()
        try:
            with (folder / name).open("rb") as file:
                for block in iter(lambda: file.read(1 << 20), b""):
                    digest.update(block)
        except OSError:
            return False
        if digest.hexdigest() != expected:
            return False
    return True


def main() -> int:
    """``python -m luxai.offline_translate`` — run by Update.bat: install the translator once."""
    if installed():
        print("Traducator offline: deja instalat.")
        return 0
    print("Descarc traducatorul offline (NLLB, ~640 MB, o singura data)...", flush=True)
    events = os.environ.get("LUXAI_UI_EVENTS")  # the setup window shows the bytes
    stop = threading.Event()
    if events:
        def watch():
            import json
            folder = model_dir()
            while not stop.wait(0.5):
                done = 0
                for item in folder.rglob("*") if folder.exists() else []:
                    try:
                        done += item.stat().st_size if item.is_file() else 0
                    except OSError:
                        pass
                try:
                    with open(events, "a", encoding="utf-8") as stream:
                        stream.write(json.dumps({"t": "bytes", "done": done, "total": 647_000_000}) + "\n")
                except OSError:
                    pass
        threading.Thread(target=watch, daemon=True).start()
    try:
        ready = ensure_downloaded()
    finally:
        stop.set()
    if ready:
        print("Traducator offline: instalat.")
        return 0
    print("Traducator offline: descarcarea a esuat (internet?). Se reincearca automat din aplicatie.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())


def download_in_background(directory: Path | None = None):
    if installed(directory) or _downloading or os.environ.get("LUXAI_NO_DOWNLOADS"):
        return
    threading.Thread(target=ensure_downloaded, args=(directory,), daemon=True,
                     name="JarvisTranslatorDownload").start()


def translate(text: str, source: str, target: str) -> str | None:
    """Offline translation, or None when it is not possible (yet): then the original is used."""
    if not supports(source, target):
        return None
    translator = get()
    if translator is None:
        download_in_background()  # not downloaded yet: ready for the next time
        return None
    try:
        return translator.translate(text, source, target) or None
    except Exception:
        return None
