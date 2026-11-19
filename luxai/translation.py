"""Read aloud in Jarvis' language (0.4.1h): detect, split and translate text.

``text_language`` is tuned for paragraphs (not short commands): Cyrillic →
ru; Latin text is scored by common English / Romanian words; other Latin
languages (German, French…) return "other" and are translated too.
``split_chunks`` makes ≤ ~600-character pieces at sentence boundaries so the
first piece can be read while the rest is still being translated (the
speech engine also reads at most 700 characters per call).
"""
from __future__ import annotations

import re

_EN = set("""the a an and or of to in on for with is are was were be been it this that these those you your we
our they their he she his her i my me not no yes but if then than as at by from have has had do does did will
would can could should about there what which who when where how all any more most other some such only own
same so too very just also into over after before because while""".split())
_RO = set("""și si sau de la în in pe cu din pentru este sunt era au a fost fi nu da dar dacă daca că ca care
ce cum când cand unde mai foarte doar acest această aceasta acesta aceste acei lui ei el ea noi voi ele lor
meu mea tău tau său sau un o unei unui al ale prin după dupa până pana fără fara despre""".split())
_OTHER_HINTS = re.compile(r"[äöüßéèêëàçñøåœ]|\b(?:der|die|das|und|ist|nicht|le|la|les|est|une|des|el|los|las|que|del)\b",
                          re.IGNORECASE)


def text_language(text: str) -> str:
    """"ru", "en", "ro", "other" or "" (too little text to tell)."""
    value = str(text or "")
    letters = re.findall(r"[^\W\d_]", value)
    if len(letters) < 3:
        return ""
    cyrillic = sum(1 for char in letters if "Ѐ" <= char <= "ӿ")
    if cyrillic / len(letters) > 0.3:
        return "ru"
    words = re.findall(r"[a-zA-ZăâîșțşţĂÂÎȘȚŞŢ]+", value.casefold())
    if not words:
        return "other"
    english = sum(1 for word in words if word in _EN)
    romanian = sum(1 for word in words if word in _RO) + 2 * len(re.findall(r"[ăâîșțşţ]", value.casefold()))
    other = len(_OTHER_HINTS.findall(value))
    best = max(english, romanian)
    if other > best and other >= 2:
        return "other"
    if best == 0:
        return "other"
    return "en" if english >= romanian else "ro"


def needs_translation(text: str, target: str) -> bool:
    """True for text in another language — Ukrainian, German, Spanish… included."""
    from luxai.offline_translate import source_language
    source = source_language(text)
    return bool(source) and source != target


def split_chunks(text: str, limit: int = 450, first_limit: int = 180) -> list[str]:
    """Sentence-aligned pieces of at most ``limit`` characters.

    The FIRST piece is short (about one sentence, ``first_limit``), so the
    voice — and a translation, if any — starts almost at once.
    """
    pieces = _split(text, limit)
    if pieces and len(pieces[0]) > first_limit:
        head = _split(pieces[0], first_limit)
        pieces = [head[0]] + _split(" ".join(head[1:] + pieces[1:]), limit) if len(head) > 1 else pieces
    return pieces


def _split(text: str, limit: int) -> list[str]:
    value = " ".join(str(text or "").split())
    if not value:
        return []
    sentences = re.split(r"(?<=[.!?…])\s+", value)
    chunks, current = [], ""
    for sentence in sentences:
        while len(sentence) > limit:  # a very long sentence: cut at a word
            head = sentence[:limit].rsplit(" ", 1)[0] or sentence[:limit]
            if current:
                chunks.append(current)
                current = ""
            chunks.append(head)
            sentence = sentence[len(head):].lstrip()
        if current and len(current) + 1 + len(sentence) > limit:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks


def translate_offline(text: str, target: str, source: str = "") -> str | None:
    """Jarvis' only translator: offline NLLB on this PC, ≈0.5 s per sentence.

    ``source`` is the known spoken language (captions); otherwise it is guessed
    from the text. None = not possible (model still downloading, same language):
    callers then use the original text.
    """
    from luxai import offline_translate
    source = source if source in offline_translate.CODES else offline_translate.source_language(text)
    return offline_translate.translate(text, source, target)
