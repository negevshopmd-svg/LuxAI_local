"""0.4.1c Timers and alarms: phrases, persistence, ringing, snooze and the page."""
import datetime as dt
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from luxai import extensions_catalog as catalog
from luxai import extensions_runtime as runtime
from luxai import timers

NOW = dt.datetime(2026, 11, 16, 21, 0)


class ParseTests(unittest.TestCase):
    def check(self, text, kind, seconds=0, at=None, label=""):
        request = timers.parse_request(text, NOW)
        self.assertIsNotNone(request, text)
        self.assertEqual(request.kind, kind, text)
        if seconds:
            self.assertEqual(request.seconds, seconds, text)
        if at:
            self.assertEqual(request.at, at, text)
        if label:
            self.assertEqual(request.label, label, text)

    def test_russian(self):
        self.check("поставь таймер на 10 минут", "timer", 600)
        self.check("таймер на полтора часа", "timer", 5400)
        self.check("Джарвис, засеки 30 секунд", "timer", 30)
        self.check("таймер на 1 час 20 минут", "timer", 4800)
        self.check("таймер на минуту", "timer", 60)
        self.check("поставь таймер на пять минут", "timer", 300)
        self.check("таймер полчаса", "timer", 1800)
        self.check("напомни через 20 минут выключить плиту", "timer", 1200, label="выключить плиту")
        self.check("разбуди в 7:30", "alarm", at=dt.datetime(2026, 11, 17, 7, 30))
        self.check("поставь будильник на 7 утра", "alarm", at=dt.datetime(2026, 11, 17, 7, 0))
        self.check("будильник на 22:15", "alarm", at=dt.datetime(2026, 11, 16, 22, 15))
        self.check("отмени таймер", "cancel")
        self.assertTrue(timers.parse_request("отмени все будильники", NOW).all)
        self.check("сколько осталось", "list")

    def test_romanian_and_english(self):
        self.check("pune un cronometru de 10 minute", "timer", 600)
        self.check("trezește-mă la 7:30", "alarm", at=dt.datetime(2026, 11, 17, 7, 30))
        self.check("anulează cronometrul", "cancel")
        self.check("set a timer for 5 minutes", "timer", 300)
        self.check("wake me up at 6 am", "alarm", at=dt.datetime(2026, 11, 17, 6, 0))
        self.check("alarm at 9:30 pm", "alarm", at=dt.datetime(2026, 11, 16, 21, 30))
        self.check("remind me in 15 minutes to call mom", "timer", 900, label="call mom")

    def test_other_requests_are_not_timers(self):
        for text in ("открой стим", "сколько времени", "какая погода", "нажми на W", "напиши привет", "10 минут назад"):
            self.assertIsNone(timers.parse_request(text, NOW), text)

    def test_formatting(self):
        self.assertEqual(timers.format_duration(4800), "1 час 20 минут")
        self.assertEqual(timers.format_duration(300), "5 минут")
        self.assertEqual(timers.format_duration(61, "en"), "1 minute 1 second")
        self.assertEqual(timers.format_countdown(3725), "1:02:05")
        self.assertEqual(timers.format_countdown(65), "01:05")


class StoreTests(unittest.TestCase):
    def test_persist_reload_and_due(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "timers.json"
            store = timers.TimerStore(path)
            first = store.add(timers.new_timer("timer", 100.0, "a", 60))
            store.add(timers.new_timer("alarm", 50.0))
            reloaded = timers.TimerStore(path)
            self.assertEqual([item.kind for item in reloaded.items], ["alarm", "timer"])
            self.assertEqual([item.kind for item in reloaded.due(now=60)], ["alarm"])
            self.assertTrue(reloaded.remove(first.id))
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(timers.TimerStore(path).items, [])


class _Host:
    def __init__(self):
        self.cfg = {"ui_language": "ru", "tts_enabled": True}
        self.tray_icon = None
        self.spoken = []

    def _queue_speech(self, text, language):
        self.spoken.append(text)


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, enabled=True, **settings):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        engine = runtime.ExtensionsRuntime(_Host())
        engine.timers_path = Path(folder.name) / "timers.json"
        state = catalog.normalize_state({"timers": {"enabled": enabled, "settings": {"sound": False, "popup": False, **settings}}})
        engine.apply(state)

        def dispose():
            engine.stop()
            engine.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        self.addCleanup(dispose)
        return engine

    def test_voice_flow(self):
        engine = self.make()
        self.assertEqual(engine.handle_timer_request("поставь таймер на 10 минут"), "Таймер на 10 минут запущен.")
        self.assertIn("Напомню через 20 минут: выключить плиту", engine.handle_timer_request("напомни через 20 минут выключить плиту"))
        self.assertIn("Будильник поставлен на", engine.handle_timer_request("разбуди в 7:30"))
        listing = engine.handle_timer_request("сколько осталось")
        self.assertIn("таймер на 10 минут: осталось", listing)
        self.assertIn("будильник на 07:30", listing)
        self.assertEqual(engine.handle_timer_request("отмени таймер"), "Отменил: таймер на 10 минут.")
        self.assertEqual(engine.handle_timer_request("отмени все"), None)  # no timer word: not ours
        self.assertEqual(engine.handle_timer_request("отмени все таймеры"), "Отменено: 1.")
        self.assertIsNone(engine.handle_timer_request("открой стим"))
        saved = json.loads(engine.timers_path.read_text(encoding="utf-8"))
        self.assertEqual([item["kind"] for item in saved], ["alarm"])

    def test_disabled_plugin_says_how_to_enable(self):
        engine = self.make(enabled=False)
        self.assertIn("Включите «Таймеры и будильники»", engine.handle_timer_request("таймер на 5 минут"))
        self.assertEqual(engine.active_timers(), [])

    def test_due_timer_rings_speaks_and_snoozes(self):
        engine = self.make(snooze=3)
        engine.handle_timer_request("таймер на 1 минуту")
        engine.timer_store.items[0].due = time.time() - 1
        engine._check_timers()
        self.assertEqual(engine.active_timers(), [])
        self.assertEqual(engine.host.spoken[-1], "Время вышло: таймер на 1 минуту.")
        ringing_timer = engine._ringing[0][0]
        engine.snooze(ringing_timer)
        self.assertEqual(len(engine.active_timers()), 1)
        self.assertAlmostEqual(engine.active_timers()[0].remaining(), 180, delta=2)
        self.assertEqual(engine._ringing, [])

    def test_popup_and_sound(self):
        engine = self.make(sound=True, popup=True)
        with mock.patch.object(runtime.threading, "Thread"):
            engine.ring(timers.new_timer("alarm", time.time(), ""))
        self.assertTrue(engine._ring_beeper.isActive())
        dialog = engine._ringing[0][1]
        self.assertIsNotNone(dialog)
        engine.stop_ringing()
        self.assertFalse(engine._ring_beeper.isActive())
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_settings_page_lists_and_cancels(self):
        from luxai.ui_extension_settings import PluginSettingsView
        engine = self.make()
        engine.handle_timer_request("таймер на 10 минут")
        state = catalog.normalize_state({"timers": {"enabled": True}})
        view = PluginSettingsView(catalog.PLUGIN_BY_ID["timers"], state["timers"], "ru", engine)
        self.addCleanup(lambda: (view.detach(), view.deleteLater(),
                                 QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)))
        self.assertEqual(list(view.cards)[:3], ["basic", "active", "signal"])
        self.assertEqual(len(view._countdowns), 1)
        self.assertRegex(view._countdowns[0][1].text(), r"^(09|10):\d\d$")
        view.timer_minutes.setValue(3)
        view._quick_timer()
        self.assertEqual(len(view._countdowns), 2)
        engine.cancel_timer(engine.active_timers()[0].id)
        self.assertEqual(len(view._countdowns), 1)


class MainHookTests(unittest.TestCase):
    def test_saved_command_wins_over_timer(self):
        import main
        fake = mock.Mock()
        fake.cfg = {"wake_prefix": "Jarvis"}
        fake.command_registry.match.return_value = {"id": "x"}
        self.assertTrue(main.MainWindow._saved_command_matches(fake, "таймер на 5 минут"))
        fake.command_registry.match.return_value = None
        self.assertFalse(main.MainWindow._saved_command_matches(fake, "таймер на 5 минут"))


if __name__ == "__main__":
    unittest.main()
