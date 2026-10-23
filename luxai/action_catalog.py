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
    ("run_file", "Запуск", "Запустить файл или программу", "Открывает файл, вручную выбранный на вашем компьютере", True),
    ("open_user_file", "Файлы", "Открыть файл по имени", "Ищет на рабочем столе, в Документах или Загрузках и открывает через Windows", True),
    ("open_website", "Запуск", "Открыть сайт", "Открывает указанный HTTPS-сайт в браузере", True),
    ("run_cmd", "Запуск", "Выполнить команду CMD", "Только сохранённый пользователем скрипт; подтверждение при каждом запуске", True),
    ("run_powershell", "Запуск", "Выполнить команду PowerShell", "Только сохранённая вручную команда; обязательное подтверждение", True),
    ("type_text", "Клавиши", "Ввести текст", "Печатает указанный текст в активном окне", True),
    ("hotkey", "Клавиши", "Нажать клавишу или сочетание", "Выбираемое сочетание из безопасного списка", True),
    ("press_key", "Клавиши", "Нажать одну клавишу", "Буквы, цифры и стандартные клавиши", True),
    ("key_sequence", "Клавиши", "Последовательность клавиш", "По очереди нажимает 2–24 буквы или цифры, например Q,W,E,R,D", True),
    ("press_enter", "Клавиши", "Нажать Enter", "Отправляет Enter в активное окно", True),
    ("save_document", "Клавиши", "Сохранить (Ctrl+S)", "Отправляет Ctrl+S в активное окно", True),
    ("mouse_double_click", "Мышь", "Двойной клик", "Двойной щелчок левой кнопкой", True),
    ("mouse_right_click", "Мышь", "Правый клик", "Щелчок правой кнопкой мыши", True),
    ("mouse_click", "Мышь", "Левый клик", "Нажимает левую кнопку мыши", True),
    ("visual_click", "Мышь", "Найти объект на экране и нажать", "Снимок окна, облачное зрение и 1–3 клика после подтверждения", True),
    ("close_window", "Программа", "Закрыть активное окно", "Закрывает только окно другой программы после подтверждения", True),
    ("display_info", "Система", "Размеры экранов", "Реальные координаты и размеры виртуального рабочего стола", True),
    ("empty_recycle_bin", "Файлы", "Очистить корзину Windows", "Безвозвратно удалить файлы из корзины только после явного подтверждения", True),
    ("mouse_scroll", "Мышь", "Клик колесом / прокрутка", "Прокрутка колеса мыши", True),
    ("mouse_move", "Мышь", "Переместить курсор", "Перемещает курсор к координатам экрана", True),
    ("mouse_hold", "Мышь", "Зажать левую кнопку", "Удерживает кнопку 1–5 секунд и отпускает автоматически", True),
    ("noop", "Программа", "Пустое действие", "Не выполняет никаких действий — разделитель шагов", True),
    ("wait_seconds", "Программа", "Пауза в секундах", "Ждёт 1–30 секунд до следующего действия", True),
    ("wait_minutes", "Программа", "Пауза в минутах", "Ждёт 1–10 минут без блокировки окна", True),
    ("tray_minimize", "Программа", "Свернуть Jarvis в трей", "Скрывает окно Jarvis в системный трей", True),
    ("speak_text", "Озвучка", "Произнести текст", "Произносит указанный текст голосом Jarvis", True),
    ("speak_ready", "Озвучка", "Вас понял, сэр", "Готовая фраза подтверждения", True),
    ("speak_done", "Озвучка", "Всё готово, сэр", "Готовая фраза завершения", True),
    ("play_mp3", "Звук", "Воспроизвести MP3", "Воспроизводит выбранный MP3 через Windows Media Control", True),
    ("play_wav", "Звук", "Воспроизвести WAV", "Воспроизводит выбранный WAV через Windows", True),
    ("volume_up", "Звук", "Увеличить громкость", "Повышает системную громкость", True),
    ("volume_down", "Звук", "Уменьшить громкость", "Понижает системную громкость", True),
    ("app_volume", "Звук", "Громкость приложения", "Устанавливает громкость выбранного приложения, если оно запущено", True),
    ("voice_female", "Звук", "Произнести женским голосом", "Использует доступный женский голос Windows SAPI", True),
    ("voice_male", "Звук", "Произнести мужским голосом", "Использует настроенный голос Jarvis", True),
    ("mouse_middle_click", "Мышь", "Клик колёсиком", "Нажимает среднюю кнопку мыши", True),
    ("mouse_right_hold", "Мышь", "Зажать правую кнопку", "Удерживает правую кнопку 1–5 секунд", True),
    ("monitor_on", "Система", "Включить монитор", "Посылает Windows запрос включения монитора", True),
    ("monitor_off", "Система", "Выключить монитор", "Гасит дисплей, не выключая компьютер", True),
    ("lock_screen", "Система", "Заблокировать экран", "Блокирует текущую сессию Windows", True),
    ("sleep_pc", "Система", "Спящий режим", "Отправляет Windows в сон после подтверждения", True),
    ("minimize_windows", "Система", "Свернуть все окна", "Сворачивает открытые окна Windows", True),
    ("search_web", "Браузер", "Найти в интернете", "Открывает результаты поиска по запросу", True),
    ("open_first_result", "Браузер", "Открыть первый результат поиска", "Открывает первый найденный результат через поисковик", True),
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

SINGLE_KEYS = set("abcdefghijklmnopqrstuvwxyz0123456789") | {"enter", "space", "tab", "esc", "backspace", "delete", "insert", "home", "end", "up", "down", "left", "right", "pageup", "pagedown"} | {f"f{i}" for i in range(1, 13)}
HOTKEYS.update({f"ctrl+{key}": ("ctrl", key) for key in "abcdefghijklmnopqrstuvwxyz"})

NO_TARGET = {
    "time", "minimize_windows", "press_enter", "save_document",
    "mouse_click", "mouse_right_click", "mouse_double_click", "volume_up", "volume_down",
    "lock_screen", "list_files", "speak_ready", "speak_done", "noop",
    "mouse_middle_click", "monitor_on", "monitor_off", "sleep_pc", "tray_minimize",
    "display_info", "empty_recycle_bin", "close_window",
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
    elif action == "open_user_file":
        # Explicit basename only. The actual file must be resolved only
        # when the command runs, so user-created shortcuts survive renames.
        value = str(target or "").strip().strip("'\"«»“”")
        if (
            not 1 <= len(value) <= 180 or value in (".", "..")
            or ".." in value
            or any(ord(c) < 32 or c in '\\/:*?"<>|' for c in value)
        ):
            raise ValueError("Укажите только имя файла без пути, например Отчёт.docx")
        result["target"] = value
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
    elif action in ("run_cmd", "run_powershell"):
        # Only a user-created macro may carry these steps; cloud schemas reject
        # them. Execution also shows the FULL command for approval every time.
        if not isinstance(target, str) or not 1 <= len(target.strip()) <= 500:
            raise ValueError("Введите команду длиной до 500 символов")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in target):
            raise ValueError("Только одна строка команды без управляющих символов")
        result["target"] = target.strip()
    elif action in ("play_mp3", "play_wav", "run_file"):
        from pathlib import Path
        if not isinstance(target, str) or len(target) > 350 or not Path(target).is_absolute():
            raise ValueError("Выберите локальный аудиофайл через «Обзор»")
        if action != "run_file" and Path(target).suffix.casefold() != (".mp3" if action == "play_mp3" else ".wav"):
            raise ValueError("Неверный формат звукового файла")
        if not Path(target).is_file():
            raise ValueError("Звуковой файл не найден")
        result["target"] = str(Path(target).resolve())
    elif action in ("voice_female", "voice_male"):
        if not isinstance(target, str) or not 1 <= len(target.strip()) <= 350:
            raise ValueError("Введите текст озвучки (до 350 символов)")
        result["target"] = target.strip()
    elif action == "app_volume":
        from luxai.command_registry import APP_TARGETS
        match = re.fullmatch(r"([a-z]+):(100|[0-9]{1,2})", str(target))
        if not match or match.group(1) not in APP_TARGETS:
            raise ValueError("Выберите приложение и громкость от 0 до 100%")
        result["target"] = f"{match.group(1)}:{int(match.group(2))}"
    elif action in ("mouse_hold", "mouse_right_hold"):
        try:
            duration = int(target)
        except (TypeError, ValueError):
            raise ValueError("Длительность удержания должна быть от 1 до 5 секунд") from None
        if not 1 <= duration <= 5:
            raise ValueError("Удержание ограничено 5 секундами")
        result["target"] = str(duration)
    elif action == "wait_minutes":
        try:
            minutes = int(target)
        except (TypeError, ValueError):
            raise ValueError("Пауза должна быть от 1 до 10 минут") from None
        if not 1 <= minutes <= 10:
            raise ValueError("Пауза должна быть от 1 до 10 минут")
        result["target"] = str(minutes)
    elif action == "open_first_result":
        if not isinstance(target, str) or not 1 <= len(target.strip()) <= 150:
            raise ValueError("Введите поисковую фразу")
        if any(ord(ch) < 32 for ch in target):
            raise ValueError("Неверный поисковый запрос")
        result["target"] = target.strip()
    elif action == "key_sequence":
        if not isinstance(target, str):
            raise ValueError("Укажите последовательность из 2–24 английских букв или цифр")
        raw = target.strip().casefold()
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
            raise ValueError("Управляющие символы запрещены")
        if re.fullmatch(r"[a-z0-9]{2,24}", raw):
            keys = list(raw)
        else:
            keys = [item.strip() for item in re.split(r"[,\s]+", raw) if item.strip()]
        if not 2 <= len(keys) <= 24 or any(not re.fullmatch(r"[a-z0-9]", key) for key in keys):
            raise ValueError("Допустимы только 2–24 последовательных букв или цифр")
        result["target"] = ",".join(keys)
    elif action == "press_key":
        if target not in SINGLE_KEYS:
            raise ValueError("Неизвестная клавиша")
        result["target"] = target
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
    elif action == "visual_click":
        from luxai.visual_click import parse_click_target
        label, count = parse_click_target(target)
        result["target"] = label + "||" + str(count)
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
    if step["action"] == "key_sequence":
        return title + ": " + " → ".join(step["target"].upper().split(","))
    if step.get("target"):
        short = step["target"]
        if len(short) > 48:
            short = short[:45] + "..."
        return f"{title}: {short}"
    return title
