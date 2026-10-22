"""Local help and explicit speech-to-action keyboard shortcuts for Jarvis.

This uses the exact same allowlisted actions and shortcuts shown in the
visual command editor. It does not send speech content to an LLM.
"""
from __future__ import annotations

import re

from luxai.fast_intents import strip_wake_name
from luxai.action_catalog import CATALOG, CATEGORIES, HOTKEYS

ENTER = re.compile(
    r"^\s*(?:нажми|нажать|нажмите|жми|press|apasă|apasa)\s+"
    r"(?:клавишу\s+|кнопку\s+)?(?:enter|энтер|ентер|ввод|return)\s*[.!?]*$",
    re.I,
)
HOTKEY = re.compile(
    r"^\s*(?:нажми|нажать|нажмите|жми|press|apasă|apasa)\s+"
    r"(?:комбинацию\s+|клавиши\s+|клавишу\s+)?"
    r"([a-zA-Zа-яА-Я+\s-]{3,30})\s*[.!?]*$",
    re.I,
)
CANONICAL = {
    "контрол": "ctrl",
    "контроль": "ctrl",
    "ctrl": "ctrl",
    "альт": "alt",
    "alt": "alt",
    "шифт": "shift",
    "shift": "shift",
    "таб": "tab",
    "tab": "tab",
    "эск": "esc",
    "esc": "esc",
    "вин": "win",
    "windows": "win",
    "win": "win",
    "эс": "s",
    "с": "s",
    "s": "s",
    "а": "a",
    "a": "a",
    "ф": "f",
    "f": "f",
    "з": "z",
    "z": "z",
    "ц": "c",
    "c": "c",
    "в": "v",
    "v": "v",
    "х": "x",
    "x": "x",
}
SAVE = re.compile(
    r"^\s*(?:сохрани|сохранить|сохрани\s+(?:документ|файл)|save(?:\s+document)?)\s*[.!?]*$",
    re.I,
)
HELP = re.compile(
    r"^\s*(?:какие\s+(?:у\s+тебя\s+)?(?:есть\s+)?(?:команды|действия|функции)"
    r"|что\s+ты\s+умеешь(?:\s+делать)?"
    r"|что\s+ты\s+можешь\s+(?:делать|выполнять)"
    r"|расскажи\s+(?:о\s+)?(?:командах|действиях|функциях)"
    r"|покажи\s+(?:все\s+)?(?:команды|действия|функции)"
    r"|help(?:\s+commands)?|list\s+(?:commands|actions)"
    r"|ce\s+(?:comenzi|funcții|functii)\s+(?:ai|știi|stii))\s*[.!?]*$",
    re.I,
)


def keyboard_action_plan(text: str) -> dict | None:
    phrase = strip_wake_name(text).strip()
    if ENTER.fullmatch(phrase):
        return {"action": "press_enter", "target": "", "reply": ""}
    if SAVE.fullmatch(phrase):
        return {"action": "save_document", "target": "", "reply": ""}
    match = HOTKEY.fullmatch(phrase)
    if not match:
        return None
    pieces = re.split(r"\s*\+\s*|\s+и\s+|\s+", match.group(1).casefold())
    combo = "+".join(CANONICAL.get(v, v) for v in pieces if v)
    if combo not in HOTKEYS:
        return None
    return {"action": "hotkey", "target": combo, "reply": ""}


def command_capabilities_reply(text: str) -> str | None:
    """Tell the user about REAL executable commands, not unsupported skills."""
    phrase = strip_wake_name(text).strip()
    if not HELP.fullmatch(phrase):
        return None
    categories = ", ".join(name for name, _ in CATEGORIES if name != "Все действия")
    available = [x for x in CATALOG.values() if x.get("available")]
    return (
        f"Я поддерживаю {len(available)} типов действий: {categories}. "
        "Можно открывать программы и сайты, документы с рабочего стола, "
        "управлять клавиатурой и мышью, регулировать громкость, читать экран "
        "и создавать собственные команды из нескольких шагов. "
        "Пример: «нажми Enter», «нажми Ctrl+S», «открой файл Отчёт.docx на рабочем столе». "
        "Скажите «создай новую команду», чтобы сохранить голосовую фразу; "
        "либо откройте «Команды → Новая команда → Действия», "
        "чтобы настроить больше шагов, включая паузы, звук и мышь."
    )
