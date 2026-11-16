"""PC Control: run saved Jarvis commands from the user's own Telegram bot.

Security model
- The bot token lives in Windows DPAPI storage (``secure_keys``, provider
  "telegram"), never in config.json or logs.
- Only the configured owner Telegram ID can run anything. Before an owner
  is set, the bot only tells a sender their own ID; it executes nothing.
- Only *saved, enabled* commands from the command editor can run; free text
  is matched against their phrases/titles, never sent to an AI agent.
- Updates queued before the bot started are skipped, so old messages never
  replay commands. Commands marked "ask before run" are confirmed with
  buttons in Telegram; risky (⚠) steps still ask on the PC as usual.
- Network traffic goes only to https://api.telegram.org (no redirects).
"""
from __future__ import annotations

import json
import queue
import re
import threading
import time
import urllib.error
import urllib.request

API = "https://api.telegram.org/bot{token}/{method}"
TOKEN_RE = re.compile(r"^\d{5,12}:[A-Za-z0-9_-]{30,60}$")
DEFAULT_FOLDER = {"ru": "Команды по умолчанию", "en": "Default commands", "ro": "Comenzi implicite"}

T = {
    "menu": ("Главное меню", "Main menu", "Meniul principal"),
    "refresh": ("🔄 Обновить", "🔄 Refresh", "🔄 Reîmprospătează"),
    "back": ("‹ Назад", "‹ Back", "‹ Înapoi"),
    "folder": ("Папка: {name}", "Folder: {name}", "Dosar: {name}"),
    "empty": ("Здесь пока нет команд.", "No commands here yet.", "Încă nu sunt comenzi aici."),
    "not_found": ("Команда не найдена. Выберите в меню:", "Command not found. Pick one from the menu:",
                  "Comanda nu a fost găsită. Alege din meniu:"),
    "your_id": ("Ваш Telegram ID: {id}\nВпишите его в Jarvis → Расширения → PC Control → «Telegram ID владельца» и сохраните.",
                "Your Telegram ID: {id}\nEnter it in Jarvis → Extensions → PC Control → “Owner Telegram ID” and save.",
                "ID-ul tău Telegram: {id}\nIntrodu-l în Jarvis → Extensii → PC Control → „ID Telegram proprietar” și salvează."),
    "confirm": ("Выполнить «{title}»?", "Run “{title}”?", "Rulez „{title}”?"),
    "yes": ("✅ Выполнить", "✅ Run", "✅ Rulează"),
    "no": ("✖ Отмена", "✖ Cancel", "✖ Anulează"),
    "cancelled": ("Отменено.", "Cancelled.", "Anulat."),
    "started": ("▶ Запускаю: {title}", "▶ Running: {title}", "▶ Rulez: {title}"),
    "done": ("✅ {title}", "✅ {title}", "✅ {title}"),
    "failed": ("⚠ {title}", "⚠ {title}", "⚠ {title}"),
    "gone": ("Команда недоступна: её изменили или выключили.", "Command unavailable: it was changed or disabled.",
             "Comandă indisponibilă: a fost modificată sau dezactivată."),
    "busy": ("Jarvis сейчас занят, попробуйте позже.", "Jarvis is busy, try again later.", "Jarvis e ocupat, încearcă mai târziu."),
}


def t(key, language, **values):
    value = dict(zip(("ru", "en", "ro"), T[key])).get(language, T[key][0])
    return value.format(**values) if values else value


def valid_token(token: str) -> bool:
    return bool(TOKEN_RE.fullmatch(str(token or "").strip()))


def valid_owner(owner: str) -> bool:
    return bool(re.fullmatch(r"\d{3,15}", str(owner or "").strip()))


# --- menus (pure) -------------------------------------------------------------

def command_folders(entries, language="ru"):
    """[(folder name, [entries])]: user folders first, then default commands."""
    folders: dict[str, list] = {}
    defaults = []
    for entry in entries:
        if not entry.get("enabled", True) or entry.get("agent"):
            continue
        if entry.get("builtin"):
            defaults.append(entry)
        else:
            folders.setdefault(entry.get("category") or "Мои команды", []).append(entry)
    result = [(name, items) for name, items in folders.items()]
    if defaults:
        result.insert(0, (DEFAULT_FOLDER.get(language, DEFAULT_FOLDER["ru"]), defaults))
    return result


class MenuState:
    """Short callback tokens (Telegram limits callback_data to 64 bytes)."""

    def __init__(self):
        self.tokens: dict[str, tuple] = {}
        self._counter = 0

    def token(self, kind, value):
        self._counter = (self._counter + 1) % 100000
        key = f"{kind}{self._counter}"
        self.tokens[key] = (kind, value)
        if len(self.tokens) > 2000:
            for old in list(self.tokens)[:1000]:
                self.tokens.pop(old, None)
        return key

    def resolve(self, data):
        return self.tokens.get(str(data or ""))


def main_menu(folders, language, mode, state: MenuState):
    if mode == "keyboard":
        rows = [[{"text": name}] for name, _ in folders] + [[{"text": t("refresh", language)}]]
        return {"keyboard": rows, "resize_keyboard": True, "is_persistent": True}
    rows = [[{"text": "📁 " + name, "callback_data": state.token("f", name)}] for name, _ in folders]
    rows.append([{"text": t("refresh", language), "callback_data": state.token("r", "")}])
    return {"inline_keyboard": rows}


def folder_menu(name, entries, language, mode, state: MenuState):
    if mode == "keyboard":
        rows = [[{"text": entry["title"]}] for entry in entries[:60]]
        rows.append([{"text": t("back", language)}])
        return {"keyboard": rows, "resize_keyboard": True, "is_persistent": True}
    rows = [[{"text": entry["title"], "callback_data": state.token("c", entry["id"])}] for entry in entries[:60]]
    rows.append([{"text": t("back", language), "callback_data": state.token("m", "")}])
    return {"inline_keyboard": rows}


def confirm_menu(identifier, language, state: MenuState):
    return {"inline_keyboard": [[{"text": t("yes", language), "callback_data": state.token("y", identifier)},
                                 {"text": t("no", language), "callback_data": state.token("n", identifier)}]]}


# --- HTTP ---------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Redirect blocked", headers, fp)


class TelegramError(RuntimeError):
    pass


def call(token, method, params=None, timeout=15, opener=None):
    """POST one Bot API method. Errors never include the token."""
    if not valid_token(token):
        raise TelegramError("Неверный формат токена.")
    request = urllib.request.Request(
        API.format(token=token, method=method),
        data=json.dumps(params or {}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "JarvisLocalAssistant/2.1"}, method="POST")
    opener = opener or urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            payload = json.loads(response.read(2_000_000).decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read(100_000).decode("utf-8"))
        except Exception:
            raise TelegramError(f"HTTP {error.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise TelegramError(f"Нет связи с Telegram ({type(error).__name__}).") from None
    if not payload.get("ok"):
        description = str(payload.get("description") or "unknown error")[:200]
        raise TelegramError(description.replace(token, "***"))
    return payload.get("result")


# --- bot thread -----------------------------------------------------------------

class TelegramBot:
    """Long-polls getUpdates in one thread and sends replies in another.

    ``on_update(update)`` and ``on_status(state, details)`` are called from
    worker threads: connect them to Qt signals only.
    """

    def __init__(self, token, on_update, on_status, *, caller=call):
        self.token = token
        self.on_update = on_update
        self.on_status = on_status
        self.call = caller
        self.outbox: queue.Queue = queue.Queue(maxsize=200)
        self._stop = threading.Event()
        self.me: dict = {}
        self._threads = []

    def start(self):
        for target, name in ((self._poll, "JarvisTelegramPoll"), (self._send_loop, "JarvisTelegramSend")):
            thread = threading.Thread(target=target, daemon=True, name=name)
            thread.start()
            self._threads.append(thread)

    def stop(self):
        self._stop.set()
        try:
            self.outbox.put_nowait(None)
        except queue.Full:
            pass

    @property
    def running(self):
        return not self._stop.is_set() and any(thread.is_alive() for thread in self._threads)

    def send(self, method, params):
        try:
            self.outbox.put_nowait((method, params))
        except queue.Full:
            pass

    def _send_loop(self):
        while not self._stop.is_set():
            item = self.outbox.get()
            if item is None:
                break
            method, params = item
            try:
                self.call(self.token, method, params, timeout=15)
            except TelegramError:
                pass

    def _poll(self):
        backoff = 2
        try:
            self.me = self.call(self.token, "getMe", timeout=15) or {}
            self.call(self.token, "deleteWebhook", {"drop_pending_updates": False}, timeout=15)
            # Skip everything sent while Jarvis was off: no replayed commands.
            pending = self.call(self.token, "getUpdates", {"timeout": 0, "offset": -1}, timeout=15) or []
            offset = (pending[-1]["update_id"] + 1) if pending else 0
        except TelegramError as error:
            self.on_status("error", {"message": str(error)})
            self._stop.set()
            return
        self.on_status("connected", {"name": self.me.get("first_name", ""), "username": self.me.get("username", "")})
        while not self._stop.is_set():
            try:
                updates = self.call(self.token, "getUpdates",
                                    {"timeout": 25, "offset": offset,
                                     "allowed_updates": ["message", "callback_query"]}, timeout=35) or []
                backoff = 2
            except TelegramError as error:
                if self._stop.is_set():
                    break
                message = str(error)
                if "conflict" in message.casefold():
                    # Another program (e.g. Luxify) polls the same bot.
                    message = ("Этот бот уже используется другой программой (например, PC Control в Luxify). "
                               "Выключите его там или создайте отдельного бота в @BotFather.")
                self.on_status("retrying", {"message": message})
                self._stop.wait(backoff)
                backoff = min(60, backoff * 2)
                continue
            for update in updates:
                offset = max(offset, int(update.get("update_id", 0)) + 1)
                if not self._stop.is_set():
                    self.on_update(update)
        self.on_status("stopped", {})
