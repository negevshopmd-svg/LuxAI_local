"""Conservative local parsing of Russian/English/Romanian mouse and keyboard tasks."""
from __future__ import annotations

import re
from luxai.fast_intents import command_text, strip_wake_name
from luxai.action_catalog import HOTKEYS, SINGLE_KEYS, validate_step

KEY_WORDS = {
    "энтер": "enter", "ентер": "enter", "ввод": "enter",
    "пробел": "space", "спейс": "space", "пропуск": "space",
    "эскейп": "esc", "эск": "esc", "escape": "esc",
    "таб": "tab", "табуляция": "tab",
    "делит": "delete", "удаление": "delete",
    "бэкспейс": "backspace", "бекспейс": "backspace",
    "вверх": "up", "вниз": "down", "влево": "left", "вправо": "right",
    "контрол": "ctrl", "контроль": "ctrl", "контролл": "ctrl",
    "шифт": "shift", "альт": "alt", "вин": "win",
    "ку": "q", "кью": "q", "английскую ку": "q",
    "control": "ctrl", "spatiu": "space", "spațiu": "space",
    "spațiul": "space", "spatiul": "space", "retur": "enter",
    "sus": "up", "jos": "down", "stânga": "left", "stanga": "left",
    "dreapta": "right", "эс": "s",
    "й": "q", "ц": "w", "у": "e", "к": "r", "е": "t", "н": "y",
    "г": "u", "ш": "i", "щ": "o", "з": "p",
    "ф": "a", "ы": "s", "в": "d", "а": "f", "п": "g",
    "р": "h", "о": "j", "л": "k", "д": "l",
    "я": "z", "ч": "x", "с": "c", "м": "v", "и": "b",
    "т": "n", "ь": "m",
}
_PRESS = r"(?:нажми|нажимай|нажать|нажмите|жми|press|hit|tap|apasă|apasa|apeși|apesi|apăsați|apasati)"
KEY_START = re.compile(r"^" + _PRESS + r"\s+", re.I)
MOUSE_CLICK = re.compile(r"^(?:нажми|нажать|кликни|кликнуть|щелкни|щелкнуть|сделай|выполни|click|apasă|apasa)\s+(.+)$", re.I)
CHAIN_SPLIT = re.compile(r"\s*(?:[,;]\s*(?=(?:потом|затем|после этого|нажми|нажать|кликни|подожди|перемести|прокрути|введи|apasă|apasa|apeși|apesi|așteaptă|asteapta|mută|muta|derulează|deruleaza|scrie|press|click|wait|move|type)\b)|\b(?:а затем|и затем|и потом|затем|потом|после этого|and then|then|after that|și apoi|si apoi|apoi|după aceea|dupa aceea|după asta|dupa asta)\b)\s*", re.I)


def parse_action(text: str) -> dict | None:
    original = command_text(text, trim_trailing_politeness=False, normalize_unicode=False)
    phrase = command_text(text).strip(" .!?").casefold()
    if not phrase:
        return None
    # A spoken compact sequence is NOT text dictation. Actually press each
    # key (useful for hotkeys in games and apps such as Q,W,E,R,D).
    sequence = re.fullmatch(
        _PRESS + r"(?:\s+pe)?"
        r"(?:\s+(?:по\s+очереди|последовательно|клавиши|кнопки|"
        r"keys|the\s+keys|tastele|literele|pe\s+rând|pe\s+rand))*"
        r"\s+([a-z0-9]{2,24}|[a-z0-9](?:\s+[a-z0-9]){1,23})",
        phrase, flags=re.I,
    )
    if sequence and sequence.group(1) not in SINGLE_KEYS | {"ctrl", "shift", "alt", "win"}:
        try:
            return validate_step({"action": "key_sequence", "target": sequence.group(1)})
        except ValueError:
            return None
    key = KEY_START.match(phrase)
    if key:
        words = key.group(0)
        rest = phrase[len(words):].strip()
        rest = re.sub(r"^(?:(?:на|клавишу|клавиши|кнопку|комбинацию|английскую|английский|букву|key|keys|the|pe|tasta|tastele|butonul|combinația|combinatia|săgeata|sageata|litera)\s+)+", "", rest)
        # English commonly puts the noun after the key: "the Q key".
        # The remaining key/hotkey must still pass the allowlist below.
        rest = re.sub(r"\s+keys?$", "", rest)
        parts = [x.strip() for x in re.split(r"\s*\+\s*|\s+(?:и|and|și|si)\s+|\s+", rest) if x.strip()]
        mapped = [KEY_WORDS.get(x, x) for x in parts]
        if len(mapped) == 1 and mapped[0] == "enter":
            return validate_step({"action": "press_enter"})
        if len(mapped) == 1 and mapped[0] in SINGLE_KEYS:
            return validate_step({"action": "press_key", "target": mapped[0]})
        joined = "+".join(mapped)
        if joined in HOTKEYS:
            return validate_step({"action": "hotkey", "target": joined})
    if re.fullmatch(r"(?:кликни|кликнуть|щелкни|щелкнуть|click|left click|click left|сделай клик|нажми мышкой|нажать мышкой|левый клик|левая кнопка мыши|(?:fă|fa|dă|da)\s+(?:un\s+)?clic(?:\s+(?:cu\s+)?(?:butonul\s+)?(?:stânga|stanga))?|clic(?:\s+(?:stânga|stanga))?|apasă\s+(?:pe\s+)?butonul\s+(?:stâng|stang)(?:\s+al\s+mouse-ului)?)", phrase):
        return validate_step({"action": "mouse_click"})
    if re.fullmatch(r"(?:правый клик|кликни правой кнопкой(?: мыши)?|нажми правую кнопку мыши|right click|click right|(?:fă|fa|dă|da)\s+(?:un\s+)?clic\s+(?:cu\s+)?(?:butonul\s+)?dreapta|clic\s+dreapta|apasă\s+(?:pe\s+)?butonul\s+drept(?:\s+al\s+mouse-ului)?)", phrase):
        return validate_step({"action": "mouse_right_click"})
    if re.fullmatch(r"(?:двойной клик|двойной щелчок|сделай двойной клик|double click|(?:fă|fa|dă|da)\s+(?:un\s+)?dublu\s+clic|dublu\s+clic)", phrase):
        return validate_step({"action": "mouse_double_click"})
    if re.fullmatch(r"(?:средний клик|кликни колёсиком|нажми колёсико|middle click)", phrase):
        return validate_step({"action": "mouse_middle_click"})
    coord = re.fullmatch(r"(?:перемести|передвинь|поставь|move|mută|muta|muți|muti|deplasează|deplaseaza)(?:\s+(?:мышь|курсор|(?:the\s+)?mouse|(?:the\s+)?cursor|mouse-ul|cursorul))?\s+(?:на|в|to|la)?\s*(\d{1,5})\s*[,;]\s*(\d{1,5})", phrase)
    if coord:
        try:
            return validate_step({"action": "mouse_move", "target": f"{coord[1]},{coord[2]}"})
        except ValueError:
            return None
    scroll = re.fullmatch(r"(?:прокрути|прокрутить|листай|scroll|derulează|deruleaza|derulezi)\s+(?:în\s+|in\s+)?(вверх|вниз|up|down|sus|jos)(?:\s+(?:на|by|cu))?\s*(\d{1,2})?(?:\s+(?:pași|pasi))?", phrase)
    if scroll:
        count = int(scroll[2] or 3) * (1 if scroll[1] in ("вверх", "up", "sus") else -1)
        if 1 <= abs(count) <= 10:
            return validate_step({"action": "mouse_scroll", "target": str(count)})
    pause = re.fullmatch(r"(?:подожди|жди|пауза|wait|așteaptă|asteapta|aștepți|astepti|pauză|pauza)\s+(\d{1,2})\s*(?:секунд[уы]?|сек|seconds?|secunde?|s)", phrase)
    if pause and 1 <= int(pause[1]) <= 30:
        return validate_step({"action": "wait_seconds", "target": pause[1]})
    typing = re.fullmatch(r"(?:напечатай|введи|напиши|type|write|scrie|scrii|tastează|tasteaza|introdu)\s+(?:(?:текст|(?:the\s+)?text|textul)\s+)?(.{1,350})", original, re.I)
    if typing:
        return validate_step({"action": "type_text", "target": typing[1]})
    return None


def parse_action_sequence(text: str) -> list[dict] | None:
    value = command_text(text, trim_trailing_politeness=False, normalize_unicode=False)
    parts = [part.strip(" ,;") for part in CHAIN_SPLIT.split(value) if part.strip(" ,;")]
    if not 1 <= len(parts) <= 8:
        return None
    steps = [parse_action(part) for part in parts]
    return steps if all(step is not None for step in steps) else None
