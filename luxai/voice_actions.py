"""Conservative local parsing of Russian/English/Romanian mouse and keyboard tasks."""
from __future__ import annotations

import re
from luxai.fast_intents import strip_wake_name
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
    "й": "q", "ц": "w", "у": "e", "к": "r", "е": "t", "н": "y",
    "г": "u", "ш": "i", "щ": "o", "з": "p",
    "ф": "a", "ы": "s", "в": "d", "а": "f", "п": "g",
    "р": "h", "о": "j", "л": "k", "д": "l",
    "я": "z", "ч": "x", "с": "c", "м": "v", "и": "b",
    "т": "n", "ь": "m",
}
KEY_START = re.compile(r"^(?:нажми|нажать|нажмите|жми|press|apasă|apasa)\s+", re.I)
MOUSE_CLICK = re.compile(r"^(?:нажми|нажать|кликни|кликнуть|щелкни|щелкнуть|сделай|выполни|click|apasă|apasa)\s+(.+)$", re.I)
CHAIN_SPLIT = re.compile(r"\s*(?:[,;]\s*(?=(?:потом|затем|после этого|нажми|нажать|кликни|подожди|перемести|прокрути|введи)\b)|\b(?:а затем|и затем|затем|потом|после этого|then|and then)\b)\s*", re.I)


def parse_action(text: str) -> dict | None:
    original = strip_wake_name(text).strip().strip(" .!?")
    phrase = original.casefold()
    phrase = re.sub(r"^(?:пожалуйста|please|te rog)\s+", "", phrase)
    original = re.sub(r"^(?:пожалуйста|please|te rog)\s+", "", original, flags=re.I)
    if not phrase:
        return None
    key = KEY_START.match(phrase)
    if key:
        words = key.group(0)
        rest = phrase[len(words):].strip()
        rest = re.sub(r"^(?:(?:на|клавишу|клавиши|кнопку|комбинацию|английскую|английский|букву|key|the)\s+)+", "", rest)
        parts = [x.strip() for x in re.split(r"\s*\+\s*|\s+и\s+|\s+", rest) if x.strip()]
        mapped = [KEY_WORDS.get(x, x) for x in parts]
        if len(mapped) == 1 and mapped[0] in SINGLE_KEYS:
            return validate_step({"action": "press_key", "target": mapped[0]})
        joined = "+".join(mapped)
        if joined in HOTKEYS:
            return validate_step({"action": "hotkey", "target": joined})
    if re.fullmatch(r"(?:кликни|кликнуть|щелкни|щелкнуть|click|сделай клик|нажми мышкой|нажать мышкой|левый клик|левая кнопка мыши)", phrase):
        return validate_step({"action": "mouse_click"})
    if re.fullmatch(r"(?:правый клик|кликни правой кнопкой(?: мыши)?|нажми правую кнопку мыши|right click|click right)", phrase):
        return validate_step({"action": "mouse_right_click"})
    if re.fullmatch(r"(?:двойной клик|двойной щелчок|сделай двойной клик|double click)", phrase):
        return validate_step({"action": "mouse_double_click"})
    if re.fullmatch(r"(?:средний клик|кликни колёсиком|нажми колёсико|middle click)", phrase):
        return validate_step({"action": "mouse_middle_click"})
    coord = re.fullmatch(r"(?:перемести|передвинь|поставь|move)(?:\s+(?:мышь|курсор|mouse|cursor))?\s+(?:на|в|to)?\s*(\d{1,5})\s*[,;]\s*(\d{1,5})", phrase)
    if coord:
        try:
            return validate_step({"action": "mouse_move", "target": f"{coord[1]},{coord[2]}"})
        except ValueError:
            return None
    scroll = re.fullmatch(r"(?:прокрути|прокрутить|листай|scroll)\s+(вверх|вниз|up|down)(?:\s+(?:на|by))?\s*(\d{1,2})?", phrase)
    if scroll:
        count = int(scroll[2] or 3) * (1 if scroll[1] in ("вверх", "up") else -1)
        if 1 <= abs(count) <= 10:
            return validate_step({"action": "mouse_scroll", "target": str(count)})
    pause = re.fullmatch(r"(?:подожди|жди|пауза|wait)\s+(\d{1,2})\s*(?:секунд[уы]?|сек|seconds?|s)", phrase)
    if pause and 1 <= int(pause[1]) <= 30:
        return validate_step({"action": "wait_seconds", "target": pause[1]})
    typing = re.fullmatch(r"(?:напечатай|введи|напиши|type|write)\s+(?:текст\s+)?(.{1,350})", original, re.I)
    if typing:
        return validate_step({"action": "type_text", "target": typing[1]})
    return None


def parse_action_sequence(text: str) -> list[dict] | None:
    value = strip_wake_name(text).strip()
    parts = [part.strip(" ,;.") for part in CHAIN_SPLIT.split(value) if part.strip(" ,;.")]
    if not 1 <= len(parts) <= 8:
        return None
    steps = [parse_action(part) for part in parts]
    return steps if all(step is not None for step in steps) else None
