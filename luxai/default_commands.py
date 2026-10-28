"""Shipped, allowlisted default command definitions, separate from personal commands.

This module contains only declarative presets. User-created commands remain
in .luxai_data/commands.json and are never overwritten by an update.
"""
import re

def _built_in(category, title, action, target="", phrases=(), location="desktop"):
    return {
        "id": "built_" + re.sub(r"[^a-z0-9]+", "_", action + "_" + target + "_" + category.lower()).strip("_"),
        "category": category, "title": title, "action": action,
        "target": target, "location": location, "phrases": list(phrases),
        "enabled": True, "builtin": True, "learned": False,
    }


BUILTINS = [
    _built_in("Приложения", "Telegram", "open_app", "telegram", (
        "открой телеграм", "открой телеграмм", "открыть телеграм",
        "запусти телеграм", "открой telegram", "open telegram",
    )),
    _built_in("Приложения", "Discord", "open_app", "discord", (
        "открой дискорд", "запусти дискорд", "открой discord", "open discord",
    )),
    _built_in("Приложения", "Steam", "open_app", "steam", (
        "открой стим", "открой steam", "запусти стим", "open steam",
    )),
    _built_in("Приложения", "Google Chrome", "open_app", "chrome", (
        "открой хром", "открой google chrome", "open chrome", "запусти хром",
    )),
    _built_in("Приложения", "Mozilla Firefox", "open_app", "firefox", (
        "открой firefox", "открой файрфокс", "open firefox",
    )),
    _built_in("Приложения", "Microsoft Edge", "open_app", "edge", (
        "открой edge", "открой эдж", "open edge",
    )),
    _built_in("Приложения", "Spotify", "open_app", "spotify", (
        "открой spotify", "открой спотифай", "open spotify",
    )),
    _built_in("Приложения", "Microsoft Word", "open_app", "word", (
        "открой word", "открой ворд", "открой microsoft word",
        "запусти word", "запусти ворд",
    )),
    _built_in("Windows", "Блокнот", "open_app", "notepad", (
        "открой блокнот", "запусти блокнот", "open notepad",
    )),
    _built_in("Windows", "Калькулятор", "open_app", "calculator", (
        "открой калькулятор", "запусти калькулятор", "open calculator",
    )),
    _built_in("Windows", "Проводник", "open_app", "explorer", (
        "открой проводник", "запусти проводник", "open file explorer",
    )),
    _built_in("Windows", "Свернуть окна", "minimize_windows", phrases=(
        "сверни все окна", "свернуть все окна", "minimize all windows",
    )),
    _built_in("Windows", "Время", "time", phrases=(
        "сколько время", "сколько времени", "который час",
        "what time is it", "cât e ceasul",
    )),
    _built_in("Игры Steam", "Dota 2", "launch_game", "dota2", (
        "открой доту", "запусти доту", "открой дота 2", "запусти dota 2",
        "открой dota", "launch dota 2",
    )),
    _built_in("Игры Steam", "Counter-Strike 2", "launch_game", "cs2", (
        "открой кс", "открой кс 2", "запусти кс", "открой cs",
        "запусти counter strike", "launch cs2",
    )),
    _built_in("Игры Steam", "War Thunder", "launch_game", "warthunder", (
        "открой вар тандер", "открой вар тандер", "запусти вар тандер",
        "открой war thunder", "запусти war thunder", "открой вартандер",
        "запусти вартандер", "launch war thunder",
    )),
    _built_in("Игры Steam", "Undertale", "launch_game", "undertale", (
        "открой undertale", "запусти undertale", "открой андертейл",
        "запусти андертейл", "открой андертэйл",
        "запусти андертэйл", "открой андертале",
        "запусти андертале", "launch undertale",
    )),
    _built_in("Файлы", "Создать файл на рабочем столе", "create_file", "Новый файл.txt", (
        "создай файл на рабочем столе", "создай файл",
        "создать файл на рабочем столе", "create a file on desktop",
    )),
    _built_in("Файлы", "Создать папку на рабочем столе", "create_folder", "Новая папка", (
        "создай папку на рабочем столе", "создай папку",
        "создать папку на рабочем столе", "create folder on desktop",
    )),
    _built_in("Файлы", "Показать файлы на рабочем столе", "list_files", phrases=(
        "покажи файлы на рабочем столе", "какие файлы на рабочем столе",
        "list desktop files",
    )),
]

