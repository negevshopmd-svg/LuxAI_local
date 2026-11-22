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
import socket
import re
import threading
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


class TelegramNotSent(TelegramError):
    """The request certainly never reached Telegram (refused connection, unknown host): safe to retry.

    Audit 7 #25: any other lost connection may have delivered the message before the answer was lost,
    so it is not sent again.
    """


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
        reason = getattr(error, "reason", None) if isinstance(error, urllib.error.URLError) else error
        if isinstance(reason, (ConnectionRefusedError, socket.gaierror)):
            raise TelegramNotSent(f"Нет связи с Telegram ({type(reason).__name__}).") from None
        raise TelegramError(f"Нет связи с Telegram ({type(error).__name__}).") from None
    except (ValueError, UnicodeDecodeError):
        raise TelegramError("Telegram ответил не в формате JSON.") from None
    if not isinstance(payload, dict):
        raise TelegramError("Неожиданный ответ Telegram.")  # audit #23: a list / null / number root
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
        self._send_lock = threading.Lock()  # audit 7 #24: «stopped?» and «queue it» are one step
        self.me: dict = {}
        self._threads = []
        self.undelivered = 0  # replies that could not be sent (queue full or Telegram error)

    def start(self):
        for target, name in ((self._poll, "JarvisTelegramPoll"), (self._send_loop, "JarvisTelegramSend")):
            thread = threading.Thread(target=target, daemon=True, name=name)
            thread.start()
            self._threads.append(thread)

    def stop(self, wait: float = 0.0):
        """Every way out (user, error, crash) ends BOTH threads (audit #22)."""
        with self._send_lock:
            self._stop.set()
        while True:  # make room for the wake-up item even when the queue is full
            try:
                self.outbox.put_nowait(None)
                break
            except queue.Full:
                try:
                    self.outbox.get_nowait()
                except queue.Empty:
                    pass
        if wait:
            for thread in self._threads:
                if thread is not threading.current_thread():
                    thread.join(wait)

    @property
    def running(self):
        """True only while the POLLER lives — a lone send thread is not a running bot (audit #23)."""
        poll = self._threads[0] if self._threads else None
        return not self._stop.is_set() and poll is not None and poll.is_alive()

    def send(self, method, params) -> bool:
        with self._send_lock:
            if self._stop.is_set():
                # audit 7 #24: a reply queued after stop() would never be sent — say so instead
                self._undelivered(method, "bot stopped")
                return False
            try:
                self.outbox.put_nowait((method, params))
                return True
            except queue.Full:
                pass
        self._undelivered(method, "queue full")
        return False

    def _undelivered(self, method, reason):
        # Never silent (audit #24): the status line shows it, and the command is not resent automatically,
        # because the action itself was already done.
        self.undelivered += 1
        try:
            self.on_status("undelivered", {"message": f"{method}: {reason}"[:200], "count": self.undelivered})
        except Exception:
            pass

    def _send_loop(self):
        while not self._stop.is_set():
            item = self.outbox.get()
            if item is None:
                break
            method, params = item
            for attempt in (1, 2):
                try:
                    self.call(self.token, method, params, timeout=15)
                    break
                except TelegramNotSent as error:
                    # The request never left: one retry cannot duplicate the message.
                    if attempt == 1 and not self._stop.wait(2):
                        continue
                    self._undelivered(method, str(error))
                    break
                except TelegramError as error:
                    # A lost answer may follow a delivered message (audit 7 #25): report, never resend.
                    reason = str(error)
                    if "связи" in reason:
                        reason += " — может быть, уже доставлено / maybe delivered"
                    self._undelivered(method, reason)
                    break
                except Exception as error:
                    self._undelivered(method, type(error).__name__)
                    break

    def _poll(self):
        try:
            self._poll_loop()
        except Exception as error:  # anything unexpected still ends in a known state
            try:
                self.on_status("error", {"message": f"{type(error).__name__}: {str(error)[:160]}"})
            except Exception:
                pass
        finally:
            self.stop()  # the send thread never stays behind (audit #22)

    def _poll_loop(self):
        backoff = 2
        try:
            self.me = self.call(self.token, "getMe", timeout=15) or {}
            self.call(self.token, "deleteWebhook", {"drop_pending_updates": False}, timeout=15)
            # Skip everything sent while Jarvis was off: no replayed commands.
            pending = self.call(self.token, "getUpdates", {"timeout": 0, "offset": -1}, timeout=15) or []
            offset = (pending[-1]["update_id"] + 1) if pending else 0
        except TelegramError as error:
            self.on_status("error", {"message": str(error)})
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
            if not isinstance(updates, list):
                updates = []
            for update in updates:
                if not isinstance(update, dict):
                    continue
                try:
                    offset = max(offset, int(update.get("update_id", 0)) + 1)
                except (TypeError, ValueError):
                    continue
                if not self._stop.is_set():
                    self.on_update(update)
        self.on_status("stopped", {})
