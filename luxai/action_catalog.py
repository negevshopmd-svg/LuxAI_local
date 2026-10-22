"""Action palette definitions and validated parameters for user-created macros.

Only these concrete actions may be executed. The palette also shows selected
Luxify reference actions that require additional integration; those are clearly
marked unavailable and cannot be stored or run.
"""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

CATEGORIES = [
    ("Все действия", "▦"),
    ("Запуск", "↗"),
    ("Клавиши", "⌨"),
    ("Мышь", "◉"),
    ("Программа", "◷"),
    ("Озвучка", "♬"),
    ("Звук", "♪"),
    ("Система", "▣"),
    ("Браузер", "◎"),
    ("Файлы", "▤"),
]

# id, category, title, short description, available
_ACTIONS = [
    ("open_app", "Запуск", "Запустить программу", "Открывает выбранное установленное приложение", True),
    ("launch_game", "Запуск", "Запустить игру Steam", "Dota 2, Counter-Strike 2, War Thunder", True),
    ("open_website", "Запуск", "Открыть сайт", "Открывает указанный HTTPS-сайт в браузере", True),
    ("run_cmd", "Запуск", "Выполнить команду CMD", "Системное действие — пока недоступно", False),
    ("run_powershell", "Запуск", "Выполнить команду PowerShell", "Системное действие — пока недоступно", False),
    ("type_text", "Клавиши", "Ввести текст", "Печатает указанный текст в активном окне", True),
    ("hotkey", "Клавиши", "Нажать клавишу или сочетание", "Выбираемое сочетание из безопасного списка", True),
    ("press_enter", "Клавиши", "Нажать Enter", "Отправляет Enter в активное окно", True),
    ("save_document", "Клавиши", "Сохранить (Ctrl+S)", "Отправляет Ctrl+S в активное окно", True),
    ("mouse_double_click", "Мышь", "Двойной клик", "Двойной щелчок левой кнопкой", True),
    ("mouse_click", "Мышь", "Левый клик", "Нажимает левую кнопку мыши", True),
    ("mouse_scroll", "Мышь", "Клик колесом / прокрутка", "Прокрутка колеса мыши", True),
    ("mouse_move", "Мышь", "Переместить курсор", "Перемещает курсор к координатам экрана", True),
    ("mouse_hold", "Мышь", "Зажать кнопку", "Требует отдельного безопасного режима", False),
    ("wait_seconds", "Программа", "Пауза в секундах", "Ждёт 1–30 секунд до следующего действия", True),
    ("wait_minutes", "Программа", "Пауза в минутах", "Длинное ожидание — пока недоступно", False),
    ("tray_minimize", "Программа", "Свернуть Jarvis в трей", "Требует отдельного управления окном", False),
    ("speak_text", "Озвучка", "Произнести текст", "Произносит указанный текст голосом Jarvis", True),
    ("speak_ready", "Озвучка", "Вас понял, сэр", "Готовая фраза подтверждения", True),
    ("speak_done", "Озвучка", "Всё готово, сэр", "Готовая фраза завершения", True),
    ("play_mp3", "Звук", "Воспроизвести MP3", "Работа со звуковыми файлами пока недоступна", False),
    ("play_wav", "Звук", "Воспроизвести WAV", "Работа со звуковыми файлами пока недоступна", False),
    ("volume_up", "Звук", "Увеличить громкость", "Повышает системную громкость", True),
    ("volume_down", "Звук", "Уменьшить громкость", "Понижает системную громкость", True),
    ("monitor_on", "Система", "Включить монитор", "Недоступно без отдельной реализации", False),
    ("monitor_off", "Система", "Выключить монитор", "Недоступно без отдельной реализации", False),
    ("lock_screen", "Система", "Заблокировать экран", "Блокирует текущую сессию Windows", True),
    ("sleep_pc", "Система", "Спящий режим", "Требует отдельного подтверждения и реализации", False),
    ("minimize_windows", "Система", "Свернуть все окна", "Сворачивает открытые окна Windows", True),
    ("search_web", "Браузер", "Найти в интернете", "Открывает результаты поиска по запросу", True),
    ("open_first_result", "Браузер", "Открыть первый результат", "Ненадёжное действие пока недоступно", False),
    ("create_file", "Файлы", "Создать файл", "Создаёт новый файл без перезаписи существующего", True),
    ("create_folder", "Файлы", "Создать папку", "Создаёт новую папку в выбранном месте", True),
    ("list_files", "Файлы", "Показать файлы", "Показывает имена файлов в выбранной папке", True),
    ("time", "Программа", "Сказать текущее время", "Называет текущее время", True),
]

CATALOG = {
    action: {
        "id": action, "category": category, "title": title,
        "description": description, "available": available,
    }
    for action, category, title, description, available in _ACTIONS
}

# Only common combinations; the user cannot inject shell or arbitrary key names.
HOTKEYS = {
    "ctrl+c": ("ctrl", "c"),
    "ctrl+v": ("ctrl", "v"),
    "ctrl+x": ("ctrl", "x"),
    "ctrl+a": ("ctrl", "a"),
    "ctrl+s": ("ctrl", "s"),
    "ctrl+z": ("ctrl", "z"),
    "ctrl+f": ("ctrl", "f"),
    "alt+tab": ("alt", "tab"),
    "ctrl+shift+esc": ("ctrl", "shift", "esc"),
    "win+d": ("win", "d"),
}

NO_TARGET = {
    "time", "minimize_windows", "press_enter", "save_document",
    "mouse_click", "mouse_double_click", "volume_up", "volume_down",
    "lock_screen", "list_files", "speak_ready", "speak_done",
}


def validate_website(value: str) -> str:
    """Validate user-supplied HTTPS web page before opening it in a browser."""
    if not isinstance(value, str) or not 1 <= len(value) <= 400:
        raise ValueError("Введите HTTPS-адрес сайта")
    try:
        parts = urlsplit(value.strip())
        hostname = parts.hostname or ""
    except ValueError:
        raise ValueError("Некорректный адрес сайта") from None
    if (
        parts.scheme != "https" or not hostname or parts.username or parts.password
        or parts.port not in (None, 443) or parts.fragment
    ):
        raise ValueError("Разрешены только обычные HTTPS-адреса")
    if hostname.casefold() in {"localhost", "localhost.localdomain"} or hostname.lower().endswith((".local", ".internal")):
        raise ValueError("Локальные адреса не разрешены")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        if "." not in hostname or not re.fullmatch(r"[A-Za-z0-9.-]+", hostname):
            raise ValueError("Некорректное доменное имя") from None
    else:
        raise ValueError("Используйте доменное имя, а не IP-адрес")
    return value.strip()


def validate_step(raw):
    """Validate and canonicalize one user-selected action, with no side effects."""
    if not isinstance(raw, dict):
        raise ValueError("Некорректное действие")
    action = raw.get("action")
    if action not in CATALOG or not CATALOG[action]["available"]:
        raise ValueError("Это действие недоступно")
    result = {"action": action, "target": "", "location": "desktop"}
    target = raw.get("target", "")
    from luxai.file_actions import ALLOWED_LOCATIONS, safe_name
    from luxai.steam_games import GAMES
    from luxai.command_registry import APP_TARGETS  # lazy, avoids import loop
    if action == "open_app":
        if target not in APP_TARGETS:
            raise ValueError("Выберите приложение из списка")
        result["target"] = target
    elif action == "launch_game":
        if target not in GAMES:
            raise ValueError("Выберите игру Steam из списка")
        result["target"] = target
    elif action in ("create_file", "create_folder"):
        result["target"] = safe_name(str(target or ""), is_folder=action == "create_folder")
        result["location"] = raw.get("location", "desktop")
    elif action == "list_files":
        result["location"] = raw.get("location", "desktop")
    elif action == "open_website":
        result["target"] = validate_website(target)
    elif action == "search_web":
        if not isinstance(target, str) or not target.strip() or len(target) > 150 or any(ord(ch) < 32 for ch in target):
            raise ValueError("Введите поисковый запрос (до 150 символов)")
        result["target"] = target.strip()
    elif action in ("type_text", "speak_text"):
        if not isinstance(target, str) or not target.strip() or len(target) > 350 or any(ord(ch) in (0, 127) for ch in target):
            raise ValueError("Введите текст длиной до 350 символов")
        result["target"] = target.strip()
    elif action == "hotkey":
        if target not in HOTKEYS:
            raise ValueError("Выберите разрешённое сочетание клавиш")
        result["target"] = target
    elif action == "wait_seconds":
        try:
            seconds = int(target)
        except (TypeError, ValueError):
            raise ValueError("Пауза должна быть числом от 1 до 30") from None
        if not 1 <= seconds <= 30:
            raise ValueError("Пауза должна быть от 1 до 30 секунд")
        result["target"] = str(seconds)
    elif action == "mouse_scroll":
        try:
            clicks = int(target)
        except (TypeError, ValueError):
            raise ValueError("Введите величину прокрутки от -10 до 10") from None
        if not -10 <= clicks <= 10 or clicks == 0:
            raise ValueError("Прокрутка должна быть от -10 до 10 (не 0)")
        result["target"] = str(clicks)
    elif action == "mouse_move":
        if not isinstance(target, str) or not re.fullmatch(r"\d{1,5},\s*\d{1,5}", target):
            raise ValueError("Координаты должны быть в формате X,Y")
        x, y = (int(part.strip()) for part in target.split(","))
        if x > 16000 or y > 16000:
            raise ValueError("Координаты выходят за допустимые пределы")
        result["target"] = f"{x},{y}"
    elif action in NO_TARGET:
        pass
    else:
        raise ValueError("Действие не реализовано")
    if result["location"] not in ALLOWED_LOCATIONS:
        raise ValueError("Выберите Desktop, Documents или Downloads")
    return result


def describe_step(step: dict) -> str:
    title = CATALOG[step["action"]]["title"]
    if step.get("target"):
        short = step["target"]
        if len(short) > 48:
            short = short[:45] + "..."
        return f"{title}: {short}"
    return title
