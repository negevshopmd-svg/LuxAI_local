"""0.4.1b PC Control: Telegram menus, owner-only access, confirmation, reports."""
import json
import unittest
from unittest import mock

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from luxai import extensions_catalog as catalog
from luxai import extensions_runtime as runtime
from luxai import telegram_control as tg

TOKEN = "123456789:" + "A" * 35

ENTRIES = [
    {"id": "b1", "title": "Открыть блокнот", "category": "Система", "builtin": True, "enabled": True,
     "phrases": ["открой блокнот"]},
    {"id": "u1", "title": "Запустить Dota", "category": "dota", "builtin": False, "enabled": True,
     "phrases": ["запусти доту"], "ask_before_run": True},
    {"id": "u2", "title": "Выключить звук", "category": "dota", "builtin": False, "enabled": True,
     "phrases": ["выключи звук"]},
    {"id": "off", "title": "Старая", "category": "dota", "builtin": False, "enabled": False, "phrases": ["x"]},
    {"id": "agent", "title": "Агент", "category": "dota", "builtin": False, "enabled": True, "agent": True,
     "phrases": ["y"]},
]


class HelperTests(unittest.TestCase):
    def test_token_and_owner_validation(self):
        self.assertTrue(tg.valid_token(TOKEN))
        for bad in ("", "abc", "123:short", TOKEN + " x"):
            self.assertFalse(tg.valid_token(bad))
        self.assertTrue(tg.valid_owner("5519543372"))
        self.assertFalse(tg.valid_owner("@user"))

    def test_folders_skip_disabled_and_agent_commands(self):
        folders = tg.command_folders(ENTRIES, "ru")
        self.assertEqual([name for name, _ in folders], ["Команды по умолчанию", "dota"])
        self.assertEqual([entry["id"] for entry in dict(folders)["dota"]], ["u1", "u2"])

    def test_menus_use_short_callback_tokens(self):
        state = tg.MenuState()
        folders = tg.command_folders(ENTRIES, "ru")
        menu = tg.main_menu(folders, "ru", "inline", state)
        data = [row[0]["callback_data"] for row in menu["inline_keyboard"]]
        self.assertTrue(all(len(item.encode()) <= 64 for item in data))
        self.assertEqual(state.resolve(data[1]), ("f", "dota"))
        keyboard = tg.main_menu(folders, "ru", "keyboard", state)
        self.assertEqual(keyboard["keyboard"][1][0]["text"], "dota")

    def test_call_hides_token_in_errors(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"ok": False, "description": "Unauthorized " + TOKEN}).encode()
        opener = mock.Mock()
        opener.open.return_value = response
        with self.assertRaises(tg.TelegramError) as caught:
            tg.call(TOKEN, "getMe", opener=opener)
        self.assertNotIn(TOKEN, str(caught.exception))
        request = opener.open.call_args[0][0]
        self.assertTrue(request.full_url.startswith("https://api.telegram.org/bot"))

    def test_token_never_stored_in_state(self):
        state = catalog.normalize_state({"pc_control": {"enabled": True, "settings": {"token": TOKEN, "owner_id": "42x"}}})
        self.assertNotIn("token", state["pc_control"]["settings"])
        self.assertEqual(state["pc_control"]["settings"]["owner_id"], "")  # bad format dropped
        self.assertTrue(state["pc_control"]["enabled"])


class _Registry:
    def entries(self):
        return [dict(entry) for entry in ENTRIES]

    def match(self, text, source="voice"):
        return next((dict(e) for e in ENTRIES if text.casefold() in [p for p in e["phrases"]]), None)


class _Host:
    def __init__(self):
        self.cfg = {"ui_language": "ru"}
        self.tray_icon = None
        self.command_registry = _Registry()
        self.runs = []

    def run_command_entry(self, entry, origin=None):
        self.runs.append((entry["id"], origin))
        return True


class _Bot:
    running = True

    def __init__(self):
        self.sent = []
        self.me = {"username": "jarvis_bot"}

    def send(self, method, params):
        self.sent.append((method, params))

    def stop(self):
        self.running = False


def message(text, sender=111):
    return {"update_id": 1, "message": {"text": text, "from": {"id": sender}, "chat": {"id": sender}}}


def callback(data, sender=111):
    return {"update_id": 2, "callback_query": {"id": "q", "data": data, "from": {"id": sender},
                                               "message": {"message_id": 9, "chat": {"id": sender}}}}


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, **settings):
        host = _Host()
        engine = runtime.ExtensionsRuntime(host)
        state = catalog.normalize_state({"pc_control": {"enabled": True, "settings": settings}})
        with mock.patch.object(runtime.ExtensionsRuntime, "_token", return_value=""):
            engine.apply(state)
        bot = _Bot()
        engine._bot = bot

        def dispose():
            engine._bot = None
            engine.stop()
            engine.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        self.addCleanup(dispose)
        return engine, host, bot

    def texts(self, bot):
        return [params.get("text", "") for method, params in bot.sent if method in ("sendMessage", "editMessageText")]

    def test_without_owner_only_tells_the_id(self):
        engine, host, bot = self.make()
        engine._on_pc_update(message("Запустить Dota", sender=555))
        self.assertIn("555", self.texts(bot)[-1])
        self.assertEqual(host.runs, [])

    def test_strangers_get_nothing(self):
        engine, host, bot = self.make(owner_id="111")
        engine._on_pc_update(message("/start", sender=999))
        engine._on_pc_update(callback("c1", sender=999))
        self.assertEqual(self.texts(bot), [])
        self.assertEqual(host.runs, [])

    def test_owner_menu_folder_and_run(self):
        engine, host, bot = self.make(owner_id="111")
        engine._on_pc_update(message("/start"))
        menu = bot.sent[-1][1]["reply_markup"]["inline_keyboard"]
        dota = next(row[0]["callback_data"] for row in menu if "dota" in row[0]["text"])
        engine._on_pc_update(callback(dota))
        self.assertEqual(bot.sent[-1][0], "editMessageText")
        buttons = bot.sent[-1][1]["reply_markup"]["inline_keyboard"]
        mute = next(row[0]["callback_data"] for row in buttons if row[0]["text"] == "Выключить звук")
        engine._on_pc_update(callback(mute))
        self.assertEqual(host.runs[-1][0], "u2")
        self.assertEqual(host.runs[-1][1]["telegram_chat"], 111)
        self.assertFalse(host.runs[-1][1]["confirmed"])
        self.assertIn("Выключить звук", self.texts(bot)[-1])

    def test_ask_before_run_is_confirmed_in_telegram(self):
        engine, host, bot = self.make(owner_id="111")
        engine._on_pc_update(message("запусти доту"))
        self.assertEqual(host.runs, [])
        yes = bot.sent[-1][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        engine._on_pc_update(callback(yes))
        self.assertEqual(host.runs[-1][0], "u1")
        self.assertTrue(host.runs[-1][1]["confirmed"])

    def test_unknown_text_and_ignore_setting(self):
        engine, host, bot = self.make(owner_id="111")
        engine._on_pc_update(message("привет"))
        self.assertIn("не найдена", self.texts(bot)[-1])
        quiet, _, quiet_bot = self.make(owner_id="111", ignore_unknown=True)
        quiet._on_pc_update(message("привет"))
        self.assertEqual(quiet_bot.sent, [])

    def test_disabled_command_cannot_run_and_results_are_reported(self):
        engine, host, bot = self.make(owner_id="111", voice_replies=False)
        engine._run_remote(111, "off", confirmed=False)
        self.assertEqual(host.runs, [])
        self.assertIn("недоступна", self.texts(bot)[-1])
        engine._run_remote(111, "u2", confirmed=False)
        self.assertFalse(host.runs[-1][1]["speak"])
        engine.remote_command_finished(host.runs[-1][1], "Звук выключен.", ok=True)
        self.assertEqual(self.texts(bot)[-1], "✅ Выключить звук\nЗвук выключен.")

    def test_bot_not_started_without_token_or_when_disabled(self):
        engine, host, bot = self.make(owner_id="111")
        engine._bot = None
        with mock.patch.object(runtime.ExtensionsRuntime, "_token", return_value=""):
            engine._apply_pc_control()
        self.assertIsNone(engine._bot)
        self.assertEqual(engine.pc_state[0], "error")

    def test_store_secret_validates_format(self):
        engine, host, bot = self.make()
        with self.assertRaises(ValueError):
            engine.store_secret("pc_control", "token", "nope")
        with mock.patch("luxai.secure_keys.store_api_key") as store:
            engine.store_secret("pc_control", "token", TOKEN)
        store.assert_called_once_with(TOKEN, "telegram")


class MainWindowRemoteTests(unittest.TestCase):
    def test_remote_run_does_not_switch_page_and_reports_back(self):
        import main
        calls = []
        fake = mock.Mock()
        fake._closed = False
        fake._command_queue = []
        fake.show_page = mock.Mock()
        fake._dispatch_command = mock.Mock()
        entry = {"id": "u2", "title": "Выключить звук", "category": "dota", "action": "hotkey", "target": "",
                 "location": "desktop", "phrases": ["выключи звук"], "steps": [{"action": "volume_mute"}],
                 "enabled": True}
        with mock.patch.object(main, "checked_command", side_effect=lambda raw, builtin=False: dict(raw)):
            accepted = main.MainWindow.run_command_entry(fake, entry, origin={"telegram_chat": 1, "confirmed": True})
        self.assertTrue(accepted)
        fake.show_page.assert_not_called()
        group = fake._command_queue[0]
        self.assertTrue(group["remote_confirmed"])
        self.assertEqual(group["origin"]["telegram_chat"], 1)
        fake._command_queue = [dict(group, answers=["Готово."], routes=[])]
        fake.cfg = {"tts_enabled": True}
        fake.extensions_runtime = mock.Mock()
        fake.extensions_runtime.remote_command_finished.side_effect = lambda *a, **k: calls.append((a, k))
        with mock.patch.object(main, "QTimer"):
            main.MainWindow._finish_command_group(fake)
        self.assertEqual(calls[0][0][1], "Готово.")
        self.assertTrue(calls[0][1]["ok"])


if __name__ == "__main__":
    unittest.main()
