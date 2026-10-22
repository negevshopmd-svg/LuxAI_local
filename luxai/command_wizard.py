"""Multi-turn voice command creation without arbitrary command execution.

The speaker provides a trigger phrase, then a description of the action.
Known operations resolve locally. An optional online agent may classify
unfamiliar descriptions, but final action must still match our whitelist.
Nothing is saved until the user explicitly confirms.
"""
from __future__ import annotations

import re

from luxai.command_registry import APP_TARGETS, CommandRegistry, checked_command
from luxai.fast_intents import strip_wake_name, has_launch_verb
from luxai.file_actions import parse_file_intent
from luxai.steam_games import local_game_intent, GAMES
from luxai.voice_shortcuts import keyboard_action_plan
from luxai.voice_files import parse_open_user_file
from luxai.websites import website_plan
from luxai.action_catalog import CATALOG, validate_step


def is_create_command_request(text: str) -> bool:
    t = str(text or "").casefold()
    return bool(
        re.search(
            r"\b(?:создай|создать|сделай|добавь|запиши)\b.{0,35}\b(?:новую\s+)?команду\b"
            r"|\b(?:create|add)\s+(?:a\s+)?(?:new\s+)?(?:voice\s+)?command\b",
            t,
        )
    )


def _action_from_description(text: str) -> dict | None:
    """Narrow intent resolver, suitable for an untrusted voice utterance."""
    s = str(text or "").strip()
    t = s.casefold()
    keyboard = keyboard_action_plan(s)
    if keyboard is not None:
        return keyboard
    opened = parse_open_user_file(s)
    if opened is not None:
        return opened
    website = website_plan(s)
    if website is not None:
        return {
            "action": "open_website", "target": website["target"],
            "location": "desktop",
        }
    file_action = parse_file_intent(s)
    if file_action:
        return file_action
    game = local_game_intent(s)
    if game in GAMES:
        return {"action": "launch_game", "target": game, "location": "desktop"}
    if re.search(r"(?:который\s+час|сколько\s+времени|скажи\s+время|say\s+the\s+time)", t):
        return {"action": "time", "target": "", "location": "desktop"}
    if re.search(r"(?:сверни\s+все\s+окна|свернуть\s+все\s+окна|minimize\s+all\s+windows)", t):
        return {"action": "minimize_windows", "target": "", "location": "desktop"}
    if has_launch_verb(t):
        aliases = {
            "telegram": ("telegram", "телеграм", "телегу"),
            "discord": ("discord", "дискорд"),
            "steam": ("steam", "стим"),
            "chrome": ("chrome", "хром"),
            "firefox": ("firefox", "файрфокс"),
            "edge": ("edge", "эдж"),
            "spotify": ("spotify", "спотифай"),
            "notepad": ("notepad", "блокнот"),
            "calculator": ("calculator", "калькулятор"),
            "explorer": ("explorer", "проводник"),
        }
        for app, words in aliases.items():
            if any(word in t for word in words):
                return {"action": "open_app", "target": app, "location": "desktop"}
    return None


def _describe(plan):
    action, target = plan.get("action"), plan.get("target", "")
    location = plan.get("location", "desktop")
    if action == "open_app":
        return f"открыть {target}"
    if action == "launch_game":
        return f"запустить {GAMES[target][1]} через Steam"
    if action == "steam_verified":
        return f"запустить {target} через Steam"
    if action == "create_file":
        return f"создать файл «{target}» в папке {location}"
    if action == "create_folder":
        return f"создать папку «{target}» в папке {location}"
    if action == "list_files":
        return f"показать файлы в папке {location}"
    if action == "time":
        return "сказать время"
    if action == "minimize_windows":
        return "свернуть все окна"
    if action == "open_user_file":
        return f"открыть файл «{target}» ({location})"
    if action == "open_website":
        return f"открыть сайт «{target}» в браузере"
    if action == "hotkey":
        return f"нажать клавиши {target.upper()}"
    if action == "press_enter":
        return "нажать Enter"
    if action == "save_document":
        return "сохранить Ctrl+S"
    if action in CATALOG:
        return CATALOG[action]["title"]
    raise ValueError("Unsupported command plan")


def _allowed_plan(plan: dict) -> dict | None:
    if not isinstance(plan, dict):
        return None
    allowed_legacy = {
        "open_app", "launch_game", "steam_verified", "create_file", "create_folder",
        "list_files", "time", "minimize_windows",
    }
    action = plan.get("action")
    if action in {"open_user_file", "open_website", "hotkey", "press_enter",
                  "save_document"}:
        try:
            step = validate_step(plan)
        except (TypeError, ValueError):
            return None
        return {
            "action": step["action"], "target": step["target"],
            "location": step["location"], "steps": [step],
        }
    if action not in allowed_legacy:
        return None
    example = {
        "id": "voice_preview",
        "title": "Новая команда",
        "phrases": ["новая тестовая команда"],
        "action": plan["action"],
        "target": plan.get("target", ""),
        "appid": plan.get("appid"),
        "location": plan.get("location", "desktop"),
        "enabled": True,
    }
    try:
        checked_command(example)
    except (ValueError, TypeError):
        return None
    return plan


class CommandWizard:
    def __init__(self, registry: CommandRegistry, wake_prefix="Jarvis"):
        self.registry = registry
        self.wake_prefix = wake_prefix
        self.stage = ""
        self.phrase = ""
        self.description = ""
        self.plan = None

    @property
    def active(self):
        return bool(self.stage)

    def start(self):
        self.stage = "phrase"
        self.phrase = ""
        self.description = ""
        self.plan = None
        return "Создаём команду. Какую фразу мне запомнить? Скажите её."

    def cancel(self):
        self.stage = ""
        self.phrase = ""
        self.plan = None
        self.description = ""
        return "Создание команды отменено."

    def _confirm_prompt(self):
        return (
            f"Запомнить фразу «{self.phrase}» и действие: "
            f"{_describe(self.plan)}? Скажите «да» или «нет»."
        )

    def feed(self, speech):
        """Return (message, online_description_or_None, saved_or_None)."""
        spoken = strip_wake_name(speech, self.wake_prefix).strip()
        normalized = re.sub(r"[.!?,:;]+", "", spoken.casefold()).strip()
        if normalized in ("отмена", "отмени", "стоп", "cancel", "не надо"):
            return self.cancel(), None, None
        if not self.active:
            return "", None, None

        if self.stage == "phrase":
            if not spoken or len(spoken) > 120:
                return "Скажите короткую фразу длиной до 120 символов.", None, None
            if self.registry.match(spoken, self.wake_prefix):
                return "Эта фраза уже используется. Назовите другую фразу.", None, None
            self.phrase = spoken
            self.stage = "action"
            return (
                f"Запомнил фразу «{self.phrase}». Что нужно делать? "
                "Например: открыть Telegram или YouTube, открыть файл "
                "с рабочего стола, нажать Enter или Ctrl+S. "
                "Сложные цепочки с мышью и паузами можно создать "
                "в разделе Команды → Новая команда → Действия.",
                None, None,
            )
        if self.stage == "action":
            self.description = spoken
            plan = _allowed_plan(_action_from_description(spoken))
            if plan is not None:
                self.plan = plan
                self.stage = "confirm"
                return self._confirm_prompt(), None, None
            self.stage = "online"
            return "Уточняю действие через онлайн-агента…", spoken, None
        if self.stage == "online":
            return "Проверяю описание команды. Подождите или скажите «отмена».", None, None
        if self.stage == "confirm":
            if normalized in ("да", "ага", "подтверждаю", "верно", "сохрани", "сохранить", "yes"):
                try:
                    title = self.phrase[:95]
                    payload = {
                        "title": title, "phrases": [self.phrase],
                        "category": "Мои команды", "action": self.plan["action"],
                        "target": self.plan.get("target", ""),
                        "location": self.plan.get("location", "desktop"),
                        "steps": self.plan.get("steps", []),
                        "appid": self.plan.get("appid"),
                        "enabled": True,
                    }
                    saved = self.registry.save_custom(payload)
                except (OSError, ValueError) as exc:
                    self.stage = "action"
                    return f"Не удалось сохранить: {exc}. Опишите действие ещё раз.", None, None
                self.cancel()
                return (
                    f"Готово. Команда «{title}» добавлена в раздел «Команды». "
                    "Теперь скажите эту фразу, чтобы выполнить действие.",
                    None, saved,
                )
            if normalized in ("нет", "неправильно", "измени", "no"):
                self.stage = "action"
                return "Хорошо. Опишите действие по-другому.", None, None
            return "Скажите «да» для сохранения, «нет» для изменения или «отмена».", None, None
        return self.cancel(), None, None

    def accept_online_plan(self, plan):
        if self.stage != "online":
            return "", None
        verified = _allowed_plan(plan)
        if verified is None:
            self.stage = "action"
            return (
                "Не смог безопасно определить действие. "
                "Попробуйте сказать: открыть Telegram, открыть YouTube в браузере, "
                "нажать Enter, создать файл или запустить игру. "
                "Остальные действия доступны в визуальном редакторе.",
                None,
            )
        self.plan = verified
        self.stage = "confirm"
        return self._confirm_prompt(), verified
