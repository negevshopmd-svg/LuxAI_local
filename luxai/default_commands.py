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


# Discord without the cloud (0.4.2o): its account-bar buttons and its own shortcuts.
DISCORD_COMMANDS = [
    _built_in("Discord", 'Выключить микрофон', "discord_key", 'mic_off', ('выключи микрофон в дискорде', 'mute my discord microphone', 'oprește microfonul în discord')),
    _built_in("Discord", 'Включить микрофон', "discord_key", 'mic_on', ('включи микрофон в дискорде', 'unmute my discord microphone', 'pornește microfonul în discord')),
    _built_in("Discord", 'Выключить звук (наушники)', "discord_key", 'sound_off', ('выключи наушники в дискорде', 'deafen me in discord', 'oprește căștile în discord')),
    _built_in("Discord", 'Включить звук (наушники)', "discord_key", 'sound_on', ('включи наушники в дискорде', 'undeafen me in discord', 'pornește căștile în discord')),
    _built_in("Discord", 'Принять звонок', "discord_key", 'answer_call', ('прими звонок в дискорде', 'answer the discord call', 'răspunde la apel în discord')),
    _built_in("Discord", 'Отклонить звонок', "discord_key", 'decline_call', ('отклони звонок в дискорде', 'decline the discord call', 'respinge apelul în discord')),
    _built_in("Discord", 'Перейти к текущему звонку', "discord_key", 'jump_call', ('вернись в звонок в дискорде', 'back to the call in discord', 'înapoi la apel în discord')),
    _built_in("Discord", 'Следующий непрочитанный канал', "discord_key", 'next_unread', ('следующий непрочитанный в дискорде', 'next unread in discord', 'următorul necitit în discord')),
    _built_in("Discord", 'Предыдущий непрочитанный канал', "discord_key", 'prev_unread', ('предыдущий непрочитанный в дискорде', 'previous unread in discord', 'necititul anterior în discord')),
    _built_in("Discord", 'Следующий сервер', "discord_key", 'next_server', ('следующий сервер в дискорде', 'next server in discord', 'serverul următor în discord')),
    _built_in("Discord", 'Предыдущий сервер', "discord_key", 'prev_server', ('предыдущий сервер в дискорде', 'previous server in discord', 'serverul anterior în discord')),
    _built_in("Discord", 'Следующий канал', "discord_key", 'next_channel', ('следующий канал в дискорде', 'next channel in discord', 'canalul următor în discord')),
    _built_in("Discord", 'Предыдущий канал', "discord_key", 'prev_channel', ('предыдущий канал в дискорде', 'previous channel in discord', 'canalul anterior în discord')),
    _built_in("Discord", 'Отметить канал прочитанным', "discord_key", 'mark_read', ('отметь канал прочитанным в дискорде', 'mark the channel read in discord', 'marchează canalul citit în discord')),
    _built_in("Discord", 'Отметить сервер прочитанным', "discord_key", 'mark_server_read', ('отметь сервер прочитанным в дискорде', 'mark the server read in discord', 'marchează serverul citit în discord')),
    _built_in("Discord", 'Личные сообщения', "discord_key", 'toggle_dms', ('открой личные сообщения в дискорде', 'open direct messages in discord', 'deschide mesajele directe în discord')),
    _built_in("Discord", 'Назад', "discord_key", 'back', ('назад в дискорде', 'go back in discord', 'înapoi în discord')),
    _built_in("Discord", 'Вперёд', "discord_key", 'forward', ('вперёд в дискорде', 'go forward in discord', 'înainte în discord')),
    _built_in("Discord", 'Быстрый переход', "discord_key", 'quick_switcher', ('быстрый переход в дискорде', 'quick switcher in discord', 'comutare rapidă în discord')),
    _built_in("Discord", 'Поиск по сообщениям', "discord_key", 'search', ('открой поиск в дискорде', 'open search in discord', 'deschide căutarea în discord')),
    _built_in("Discord", 'Закреплённые сообщения', "discord_key", 'pins', ('закреплённые в дискорде', 'pinned messages in discord', 'mesajele fixate în discord')),
    _built_in("Discord", 'Входящие и упоминания', "discord_key", 'inbox', ('входящие в дискорде', 'inbox in discord', 'mențiunile în discord')),
    _built_in("Discord", 'Список участников', "discord_key", 'members', ('участники в дискорде', 'member list in discord', 'lista de membri în discord')),
    _built_in("Discord", 'Эмодзи', "discord_key", 'emoji', ('эмодзи в дискорде', 'emoji in discord', 'emoji în discord')),
    _built_in("Discord", 'GIF', "discord_key", 'gif', ('гиф в дискорде', 'gif in discord', 'gif în discord')),
    _built_in("Discord", 'Стикеры', "discord_key", 'stickers', ('стикеры в дискорде', 'stickers in discord', 'stickere în discord')),
    _built_in("Discord", 'Загрузить файл', "discord_key", 'upload', ('загрузи файл в дискорд', 'upload a file in discord', 'încarcă un fișier în discord')),
    _built_in("Discord", 'Звуковая панель', "discord_key", 'soundboard', ('звуковая панель в дискорде', 'soundboard in discord', 'soundboard în discord')),
    _built_in("Discord", 'Скопировать ссылку на канал', "discord_key", 'copy_link', ('скопируй ссылку в дискорде', 'copy the link in discord', 'copiază linkul în discord')),
    _built_in("Discord", 'Создать группу', "discord_key", 'create_group', ('создай группу в дискорде', 'create a group in discord', 'creează un grup în discord')),
    _built_in("Discord", 'Пролистать чат вверх', "discord_key", 'scroll_up', ('пролистай вверх в дискорде', 'scroll up in discord', 'derulează în sus în discord')),
    _built_in("Discord", 'Пролистать чат вниз', "discord_key", 'scroll_down', ('пролистай вниз в дискорде', 'scroll down in discord', 'derulează în jos în discord')),
    _built_in("Discord", 'Настройки Discord', "discord_key", 'settings', ('открой настройки дискорда', 'open discord settings', 'deschide setările discord')),
    _built_in("Discord", 'Горячие клавиши Discord', "discord_key", 'help', ('горячие клавиши дискорда', 'discord shortcuts', 'scurtăturile discord')),
]
BUILTINS.extend(DISCORD_COMMANDS)
