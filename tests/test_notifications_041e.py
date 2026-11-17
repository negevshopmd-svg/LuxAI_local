"""0.4.1e Notification reader: toast parsing, filters, silence rules, voice, page."""
from pathlib import Path
import sqlite3
from contextlib import closing
import tempfile
import unittest
from unittest import mock

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from luxai import extensions_catalog as catalog
from luxai import extensions_runtime as runtime
from luxai import notifications as n


def toast(*lines):
    texts = "".join(f"<text>{line}</text>" for line in lines)
    return f'<toast><visual><binding template="ToastGeneric">{texts}</binding></visual></toast>'.encode()


class FakeDB:
    def __init__(self, folder):
        self.path = Path(folder) / "wpndatabase.db"
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE NotificationHandler (RecordId INTEGER PRIMARY KEY, PrimaryId TEXT)")
            db.execute("CREATE TABLE Notification ([Order] INTEGER PRIMARY KEY, Id INTEGER, HandlerId INTEGER, "
                       "Type TEXT, Payload BLOB, PayloadType TEXT)")
            db.executemany("INSERT INTO NotificationHandler VALUES (?, ?)",
                           [(1, "TelegramDesktop.TelegramDesktop!App"), (2, "Microsoft.Chrome"), (3, r"C:\x\pythonw.exe")])
        self.order = 0
        self.add(1, "Старое", "не читать")

    def add(self, handler, *lines, kind="toast"):
        self.order += 1
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO Notification VALUES (?, ?, ?, ?, ?, 'xml')",
                       (self.order, self.order, handler, kind, toast(*lines)))


class HelperTests(unittest.TestCase):
    def test_parse_and_compose(self):
        texts = n.toast_texts(toast("Мама", "Купи хлеба https://t.me/x", "и молоко"))
        self.assertEqual(texts, ["Мама", "Купи хлеба https://t.me/x", "и молоко"])
        self.assertEqual(n.compose("Telegram", texts, mode="sender"), "Telegram: Мама")
        self.assertEqual(n.compose("Telegram", texts), "Telegram: Мама — Купи хлеба ссылка")
        self.assertEqual(n.compose("Telegram", texts, mode="full", say_app=False), "Мама — Купи хлеба ссылка и молоко")
        self.assertEqual(n.compose("Bank", ["Bank", "Ваш код 482913"]), "Bank: пришёл код")
        self.assertEqual(n.compose("Bank", ["Bank", "Ваш код 482913"], skip_codes=False), "Bank: Ваш код 482913")
        long = n.compose("App", ["A", "слово " * 100], limit=50)
        self.assertLessEqual(len(long), 60)
        self.assertTrue(long.endswith("…"))

    def test_app_names_rules_and_hours(self):
        self.assertEqual(n.app_name("TelegramDesktop.TelegramDesktop.Store!App"), "Telegram")
        self.assertEqual(n.app_name("com.squirrel.Discord.Discord"), "Discord")
        self.assertTrue(n.is_ignored_app(r"C:\venv\pythonw.exe"))
        self.assertEqual(n.app_name("OpenAI.Codex_2p2nqsd0c76g0!App"), "Codex")
        self.assertEqual(n.app_name("{9909CFDC-8EB7-46A7-2EFA-F726394C2F3B}"), "")
        self.assertTrue(n.is_ignored_app("Microsoft.ScreenSketch_8wekyb3d8bbwe!App"))
        self.assertTrue(n.app_allowed("Telegram", {}))
        self.assertTrue(n.app_allowed("Chrome", {}))  # every non-system app is read by default
        rules = n.parse_rules("Chrome=1\nTelegram=0")
        self.assertTrue(n.app_allowed("Chrome", rules))
        self.assertFalse(n.app_allowed("Telegram", rules))
        self.assertEqual(n.parse_rules(n.format_rules(rules)), rules)
        self.assertTrue(n.in_quiet_hours(23, 23, 8) and n.in_quiet_hours(3, 23, 8))
        self.assertFalse(n.in_quiet_hours(12, 23, 8))
        self.assertEqual(n.group_message("Telegram", ["Мама", "Папа", "Мама"], 3), "Telegram: 3 новых сообщения — Мама, Папа")

    def test_voice_requests(self):
        cases = {"что пришло": "missed", "Джарвис, прочитай последнее сообщение": "last", "не читай уведомления": "off",
                 "читай уведомления": "on", "не беспокой": "dnd", "ce a venit": "missed", "do not disturb": "dnd"}
        for phrase, expected in cases.items():
            self.assertEqual(n.parse_voice_request(phrase), expected, phrase)
        for phrase in ("что пришло в голову", "открой телеграм", "не беспокойся о нём завтра утром пожалуйста дорогой"):
            self.assertIsNone(n.parse_voice_request(phrase), phrase)

    def test_watcher_reads_only_new_toasts(self):
        with tempfile.TemporaryDirectory() as folder:
            db = FakeDB(folder)
            watcher = n.NotificationWatcher(db.path)
            self.assertTrue(watcher.prime())
            self.assertEqual(watcher.poll(), [])
            db.add(1, "Мама", "Привет")
            db.add(3, "Jarvis", "своё уведомление")
            db.add(2, "tile", kind="tile")
            items = watcher.poll()
            self.assertEqual([(item["app"], item["texts"]) for item in items], [("Telegram", ["Мама", "Привет"])])
            self.assertEqual(watcher.poll(), [])


class _Host:
    def __init__(self):
        self.cfg = {"ui_language": "ru", "tts_enabled": True}
        self.tray_icon = None
        self.spoken = []
        self.updates = []

    def _queue_speech(self, text, language):
        self.spoken.append(text)

    def update_extension_setting(self, plugin, key, value):
        self.updates.append((plugin, key, value))


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, **settings):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        db = FakeDB(folder.name)
        engine = runtime.ExtensionsRuntime(_Host())
        engine.notifications_db = db.path
        with mock.patch.object(n, "microphone_in_use_by_other_app", return_value=False):
            engine.apply(catalog.normalize_state({"notification_reader": {"enabled": True, "settings": settings}}))

        def dispose():
            engine.stop()
            engine.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        self.addCleanup(dispose)
        return engine, db

    def poll(self, engine, *, silent=""):
        with mock.patch.object(runtime.ExtensionsRuntime, "_silence_reason", return_value=silent):
            engine._poll_notifications()

    def test_reads_new_messengers_and_groups(self):
        engine, db = self.make(app_rules="Chrome=0")
        db.add(1, "Мама", "Купи хлеба")
        self.poll(engine)
        self.assertEqual(engine.host.spoken, ["Telegram: Мама — Купи хлеба"])
        db.add(1, "Мама", "А")
        db.add(1, "Папа", "Б")
        db.add(2, "Chrome", "реклама")
        self.poll(engine)
        self.assertEqual(engine.host.spoken[-1], "Telegram: 2 новых сообщения — Мама, Папа")
        self.assertEqual(len(engine.host.spoken), 2)  # Chrome was switched off
        self.assertEqual(engine.seen_notification_apps, {"Telegram", "Chrome"})

    def test_silence_keeps_missed_for_what_came_in(self):
        engine, db = self.make()
        db.add(1, "Мама", "Купи хлеба")
        self.poll(engine, silent="call")
        self.assertEqual(engine.host.spoken, [])
        self.assertEqual(engine.handle_text_request("что пришло"), "Telegram: Мама — Купи хлеба")
        self.assertEqual(engine.handle_text_request("что пришло"), "Новых уведомлений нет.")
        self.assertEqual(engine.handle_text_request("прочитай последнее сообщение"), "Telegram: Мама — Купи хлеба")

    def test_read_now_off_dnd_and_voice_toggles(self):
        engine, db = self.make(read_now=False)
        db.add(1, "Мама", "Привет")
        self.poll(engine)
        self.assertEqual(engine.host.spoken, [])
        self.assertEqual(len(engine.missed_notifications), 1)
        self.assertIn("буду читать", engine.handle_text_request("читай уведомления"))
        self.assertEqual(engine.host.updates[-1], ("notification_reader", "read_now", True))
        self.assertIn("час", engine.handle_text_request("не беспокой"))
        with mock.patch.object(n, "computer_locked", return_value=False):
            self.assertEqual(engine._silence_reason(), "dnd")

    def test_app_rules_and_dictation_wait(self):
        from luxai.dictation import DICTATION_ACTIVE
        engine, db = self.make(app_rules="Chrome=1\nTelegram=0")
        db.add(1, "Мама", "Привет")
        db.add(2, "Chrome", "Загрузка завершена")
        DICTATION_ACTIVE.set()
        try:
            self.poll(engine)
            self.assertEqual(engine.host.spoken, [])
        finally:
            DICTATION_ACTIVE.clear()
        self.poll(engine)
        self.assertEqual(engine.host.spoken, ["Chrome: Загрузка завершена"])

    def test_disabled_plugin_and_repeat_key(self):
        engine, db = self.make(repeat_hotkey="ctrl+alt+n")
        self.assertEqual([e["id"] for e in engine.hotkey_entries()], ["notification_reader.repeat_hotkey"])
        db.add(1, "Мама", "Привет")
        self.poll(engine)
        engine._on_hotkey("notification_reader.repeat_hotkey")
        self.assertEqual(engine.host.spoken[-1], "Telegram: Мама — Привет")
        off = runtime.ExtensionsRuntime(_Host())
        self.addCleanup(off.deleteLater)
        off.apply(catalog.normalize_state({}))
        self.assertIn("выключена", off.handle_text_request("что пришло"))


class PageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_luxify_like_page_with_apps(self):
        from luxai.ui_extension_settings import PluginSettingsView
        engine = runtime.ExtensionsRuntime(_Host())
        engine.seen_notification_apps = {"Telegram", "Chrome"}
        state = catalog.normalize_state({"notification_reader": {"enabled": True}})
        view = PluginSettingsView(catalog.PLUGIN_BY_ID["notification_reader"], state["notification_reader"], "ru", engine)
        self.addCleanup(lambda: (view.detach(), view.deleteLater(), engine.deleteLater(),
                                 QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)))
        self.app.processEvents()
        self.assertEqual(list(view.cards), ["basic", "apps", "what", "quiet", "voice"])
        self.assertNotIn("app_rules", view.rows)  # edited by the apps card only
        self.assertFalse(view.rows["quiet_from"].isEnabled())
        switches = view.apps_holder
        self.assertEqual(switches.count(), 2)
        chrome_row = switches.itemAt(0).widget()
        from luxai.ui_home import ToggleSwitch
        chrome = chrome_row.findChild(ToggleSwitch)
        self.assertTrue(chrome.isChecked())  # read by default
        chrome.setChecked(False)
        self.assertEqual(n.parse_rules(view.collect()["app_rules"]), {"Chrome": False})
        self.assertTrue(view.dirty)


if __name__ == "__main__":
    unittest.main()
