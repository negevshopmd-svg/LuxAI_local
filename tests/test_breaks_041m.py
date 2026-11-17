"""0.4.1m Breaks like Luxify: three timers, corner card, today stats, do-not-disturb."""
import unittest
from unittest import mock

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from luxai import extensions_catalog as catalog
from luxai import extensions_runtime as runtime


class _Host:
    def __init__(self):
        self.cfg = {"ui_language": "ru", "tts_enabled": True}
        self.tray_icon = None
        self.spoken = []
        self.saved = 0

    def _queue_speech(self, text, language):
        self.spoken.append(text)

    def save_extensions_meta(self):
        self.saved += 1


class BreaksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, **settings):
        engine = runtime.ExtensionsRuntime(_Host())
        engine.apply(catalog.normalize_state({"breaks": {"enabled": True, "settings": settings}}))
        patches = [mock.patch.object(runtime, "idle_seconds", return_value=0.0),
                   mock.patch("luxai.notifications.computer_locked", return_value=False),
                   mock.patch.object(runtime.ExtensionsRuntime, "_break_silence", return_value="")]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

        def dispose():
            engine._close_break_card()
            engine.stop()
            engine.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        self.addCleanup(dispose)
        return engine

    def advance(self, engine, seconds, step=5.0):
        for _ in range(int(seconds / step)):
            engine._last_tick -= step
            engine._tick_breaks()

    def test_eyes_card_after_twenty_active_minutes(self):
        engine = self.make()
        self.advance(engine, 19 * 60)
        self.assertIsNone(engine._break_card)
        self.advance(engine, 70)
        self.assertEqual(engine._break_card_kind, "eyes")
        engine._break_card.answered.emit("done")
        self.assertIsNone(engine._break_card)
        self.assertEqual(engine.break_stats(), (1, 0))
        self.assertEqual(engine.break_active["eyes"], 0.0)

    def test_later_and_skip(self):
        engine = self.make(stretch_on=False, water_on=False)
        engine.show_break_card("eyes")
        engine._break_card.answered.emit("later")
        self.assertEqual(engine.break_stats(), (0, 0))
        self.assertAlmostEqual(engine.break_active["eyes"], 20 * 60 - runtime.BREAK_SNOOZE)
        engine.show_break_card("eyes")
        engine._break_card.answered.emit("skip")
        self.assertEqual(engine.break_stats(), (0, 1))

    def test_try_now_never_counts(self):
        engine = self.make()
        engine.run_action("breaks", "try_water")
        self.assertEqual(engine._break_card_kind, "water")
        engine._break_card.answered.emit("done")
        self.assertEqual(engine.break_stats(), (0, 0))

    def test_away_lock_or_sleep_resets_counting(self):
        engine = self.make()
        self.advance(engine, 10 * 60)
        with mock.patch.object(runtime, "idle_seconds", return_value=6 * 60):
            engine._last_tick -= 5
            engine._tick_breaks()
        self.assertEqual(engine.break_active["eyes"], 0.0)
        self.advance(engine, 5 * 60)
        engine._last_tick -= 600  # the PC slept
        engine._tick_breaks()
        self.assertEqual(engine.break_active["eyes"], 0.0)

    def test_silence_delays_one_card_until_half_a_minute_after(self):
        engine = self.make()
        with mock.patch.object(runtime.ExtensionsRuntime, "_break_silence", return_value="fullscreen"):
            self.advance(engine, 21 * 60)
        self.assertIsNone(engine._break_card)
        self.assertEqual(engine._break_due, ["eyes"])
        self.advance(engine, 10)  # game ended — still waiting 30 s
        self.assertIsNone(engine._break_card)
        engine._break_resume_at = 0
        self.advance(engine, 5)
        self.assertEqual(engine._break_card_kind, "eyes")

    def test_voice_option(self):
        engine = self.make(voice=True)
        engine.show_break_card("stretch")
        self.assertEqual(engine.host.spoken[-1], runtime.break_message("stretch", "ru"))

    def test_page_matches_luxify(self):
        from luxai.ui_extension_settings import PluginSettingsView
        engine = self.make()
        state = catalog.normalize_state({"breaks": {"enabled": True}})
        view = PluginSettingsView(catalog.PLUGIN_BY_ID["breaks"], state["breaks"], "ru", engine)
        self.addCleanup(lambda: (view.detach(), view.deleteLater(),
                                 QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)))
        self.assertEqual(list(view.cards), ["basic", "today", "reminders", "how", "quiet"])
        self.assertIs(view.rows["eyes_every"], view.rows["eyes_on"])  # interval and switch in one row
        self.assertIs(view.rows["quiet_from"], view.rows["quiet_to"])
        self.assertEqual(view.today_label.text(), "Перерывов сделано: 0 · пропущено: 0")
        engine.show_break_card("eyes")
        engine._break_card.answered.emit("done")
        self.assertEqual(view.today_label.text(), "Перерывов сделано: 1 · пропущено: 0")
        view.fields["eyes_every"].setCurrentIndex(view.fields["eyes_every"].findData("30"))
        self.assertEqual(view.collect()["eyes_every"], "30")


if __name__ == "__main__":
    unittest.main()
