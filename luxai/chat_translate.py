"""«Переведи …» / «Tradu …» / «Translate …» in the chat (0.4.2k): the offline translator answers.

``parse_request`` finds the text and the wanted language in a typed or spoken
request. Without a named language the text is only taken when it is NOT in
Jarvis' language — «переведи компьютер в спящий режим» stays a PC command.
"""
from __future__ import annotations

import re

# code -> pattern for a language name in ru / en / ro (any case form)
LANGUAGE_PATTERNS = {
    "en": r"англ\w*|english|englez\w*",
    "ru": r"русск\w*|russian|rus[ăa]|ruse[șs]te|rusesc\w*",
    "ro": r"румын\w*|молдав\w*|romanian|rom[âa]n[ăa]|rom[âa]ne[șs]te|rom[âa]nesc\w*|moldovene\w*",
    "uk": r"украин\w*|ukrainian|ucrainean\w*",
    "de": r"немец\w*|german|german[ăa]|nem[țt]e[șs]te",
    "fr": r"француз\w*|french|francez\w*|fran[țt]uze[șs]te",
    "es": r"испан\w*|spanish|spaniol\w*",
    "it": r"итальян\w*|italian\w*|italien\w*",
    "pt": r"португал\w*|portuguese|portughez\w*",
    "pl": r"польск\w*|polish|polonez\w*",
}
_LANG = "|".join(f"(?P<{code}>{pattern})" for code, pattern in LANGUAGE_PATTERNS.items())
_LANG_GROUP = rf"(?:{_LANG})"
_TARGET = rf"(?:(?:на|в|to|into|în|in)\s+(?:limba\s+)?|по-?\s?)?{_LANG_GROUP}(?:\s+(?:язык|language))?"
_VERB = (r"(?P<verb>переведи(?:те)?|перевести|перевод|translate|translation|tradu(?:-mi|ceți|ceti|ce)?|"
         r"traducere)")
_LEAD = r"^(?:(?:джарвис|жарвис|jarvis)[,\s]+)?(?:(?:пожалуйста|please|te\s+rog|можешь|можете|can\s+you|po[țt]i)[,\s]+)*"
_GLUE = r"\s*(?:[:\-—–]\s*|\s)"
_FILLER = r"(?:(?:это|эту\s+фразу|этот\s+текст|текст|фразу|this(?:\s+text)?|the\s+text|textul(?:\s+acesta)?|asta|acest\s+text|fraza)\s+)?"
_SAY = (r"(?P<verb>как\s+(?:будет|сказать)|how\s+(?:do\s+(?:you|i)\s+)?say|"
        r"cum\s+se\s+(?:spune|zice))")


def _language(match) -> str:
    for code in LANGUAGE_PATTERNS:
        if match.groupdict().get(code):
            return code
    return ""


_LABEL = r"(?:это|эту\s+фразу|этот\s+текст|текст|фразу|this(?:\s+text)?|the\s+text|the\s+phrase|textul(?:\s+acesta)?|asta|fraza)"


def _clean(text: str) -> str:
    """Drop only an EXPLICIT label: «это: …», «textul — …», «this "…"».

    Audit 7 #1: the label used to be removed whenever the text merely started with it, so
    «thistle» became «tle», «This is a test» «is a test» and «textul nostru» «nostru».
    """
    value = str(text or "").strip()
    if re.fullmatch(rf"{_LABEL}\s*[.!?:]*", value, flags=re.I):
        return ""  # «tradu-mi asta» / «переведи это»: the label alone, nothing to translate yet
    value = re.sub(rf"^{_LABEL}(?:\s*[:\-—–]\s*|\s*(?=[«\"“„'`]))", "", value, flags=re.I)
    value = value.strip().strip("«»\"“”„'`").strip()
    return value


def _verb_language(match) -> str:
    verb = (match.group("verb") or "").casefold()
    if re.search(r"[а-я]", verb):
        return "ru"
    return "ro" if verb.startswith(("tradu", "cum")) else "en"


def parse_request(text: str):
    """(text, target code or "", language of the request word) or None when it is no translation request.

    ``text`` may be "" («переведи на английский» with nothing to translate).
    """
    value = " ".join(str(text or "").split())
    if not value:
        return None
    flags = re.IGNORECASE
    # «переведи на английский» alone
    match = re.match(rf"{_LEAD}{_VERB}\s+{_FILLER}{_TARGET}\s*[.?!:]*$", value, flags)
    if match:
        return "", _language(match), _verb_language(match)
    # «переведи на английский: текст» / «translate to English: text» / «tradu în engleză text»
    match = re.match(rf"{_LEAD}{_VERB}\s+{_FILLER}{_TARGET}{_GLUE}(?P<text>.+)$", value, flags)
    if match:
        return _clean(match.group("text")), _language(match), _verb_language(match)
    # «переведи текст на английский» / «translate text into English» / «tradu textul în engleză»
    match = re.match(rf"{_LEAD}{_VERB}{_GLUE}(?P<text>.+?)\s+{_TARGET}\s*[.?!]*$", value, flags)
    if match:
        return _clean(match.group("text")), _language(match), _verb_language(match)
    # «как будет по-английски кошка» / «how do you say cat in English» / «cum se spune pisică în engleză»
    match = re.match(rf"{_LEAD}{_SAY}\s+{_TARGET}{_GLUE}(?P<text>.+?)\s*\??$", value, flags)
    if match:
        return _clean(match.group("text")), _language(match), _verb_language(match)
    match = re.match(rf"{_LEAD}{_SAY}\s+(?P<text>.+?)\s+{_TARGET}\s*\??$", value, flags)
    if match:
        return _clean(match.group("text")), _language(match), _verb_language(match)
    # «переведи: текст» / «переведи "text"» / «translate hello world»: no language named
    match = re.match(rf"{_LEAD}{_VERB}{_GLUE}(?P<text>.+)$", value, flags)
    if match:
        return _clean(match.group("text")), "", _verb_language(match)
    return None


def choose_target(text: str, named: str, jarvis_language: str) -> str:
    """The named language, else Jarvis' language — or English when the text already is in it."""
    if named:
        return named
    from luxai.offline_translate import source_language
    source = source_language(text)
    if source == jarvis_language:
        return "en" if jarvis_language != "en" else "ru"
    return jarvis_language
