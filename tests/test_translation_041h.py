"""0.4.1h Read aloud and notifications speak foreign text in Jarvis' language."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from luxai import extensions_catalog as catalog
from luxai import extensions_runtime as runtime
from luxai import translation


class DetectionTests(unittest.TestCase):
    def test_languages(self):
        self.assertEqual(translation.text_language("The quick brown fox jumps over the lazy dog."), "en")
        self.assertEqual(translation.text_language("Buna ziua, aceasta este o propozitie in limba romana."), "ro")
        self.assertEqual(translation.text_language("Привет, как у тебя дела?"), "ru")
        self.assertEqual(translation.text_language("Der Mond ist aufgegangen, die goldnen Sternlein prangen."), "other")
        self.assertEqual(translation.text_language("OK"), "")
        self.assertTrue(translation.needs_translation("Hello, how are you today?", "ru"))
        self.assertFalse(translation.needs_translation("Привет, как дела?", "ru"))
        self.assertFalse(translation.needs_translation("OK", "ru"))

    def test_chunks_and_thinking(self):
        chunks = translation.split_chunks("One sentence here. " * 120, limit=600)
        self.assertTrue(all(len(chunk) <= 600 for chunk in chunks))
        self.assertGreater(len(chunks), 3)
        self.assertEqual(translation.split_chunks("   "), [])
        self.assertEqual(translation.strip_thinking("<think>\nhmm</think>\nДа"), "Да")


class _Planner:
    def __init__(self, result=lambda text, target: f"[{target}] {text}"):
        self.result = result
        self.calls = []

    def translate_text(self, text, target):
        self.calls.append((text, target))
        return self.result(text, target)


class _Host:
    def __init__(self, planner=None):
        self.cfg = {"ui_language": "ru", "language": "ru", "tts_enabled": True, "local_llm_fallback_enabled": False}
        self.tray_icon = None
        self.spoken = []
        self.online_planner = planner

    def _queue_speech(self, text, language):
        self.spoken.append((text, language))

    def stop_speaking(self):
        pass


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, planner=None, **extensions):
        engine = runtime.ExtensionsRuntime(_Host(planner))
        engine.apply(catalog.normalize_state(extensions))

        def dispose():
            engine.stop()
            engine.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        self.addCleanup(dispose)
        return engine

    def pump(self):
        for _ in range(5):
            self.app.processEvents()

    def test_read_aloud_translates_each_piece_then_reads(self):
        planner = _Planner()
        engine = self.make(planner, read_aloud={"enabled": True})
        text = "This is an English sentence about the weather. " * 30
        engine.read_text(text, wait=True)
        self.pump()
        self.assertGreater(len(planner.calls), 1)  # translated piece by piece
        self.assertTrue(all(target == "ru" for _, target in planner.calls))
        self.assertTrue(all(spoken.startswith("[ru] ") and language == "ru" for spoken, language in engine.host.spoken))
        self.assertEqual(len(engine.host.spoken), len(planner.calls))

    def test_same_language_or_switched_off_is_read_as_is(self):
        planner = _Planner()
        engine = self.make(planner, read_aloud={"enabled": True})
        engine.read_text("Привет, это русский текст для чтения.", wait=True)
        self.pump()
        self.assertEqual(planner.calls, [])
        self.assertEqual(engine.host.spoken, [("Привет, это русский текст для чтения.", "ru")])
        off = self.make(planner, read_aloud={"enabled": True, "settings": {"translate": False}})
        off.read_text("Hello, this is English text.", wait=True)
        self.pump()
        self.assertEqual(planner.calls, [])
        self.assertEqual(off.host.spoken[0][0], "Hello, this is English text.")

    def test_reading_language_setting_and_failure_fallback(self):
        planner = _Planner(lambda text, target: None)
        engine = self.make(planner, read_aloud={"enabled": True, "settings": {"translate_to": "ro"}})
        notices = []
        engine.notice.connect(notices.append)
        engine.read_text("Hello, this is English text that cannot be translated now.", wait=True)
        self.pump()
        self.assertEqual(planner.calls[0][1], "ro")
        self.assertEqual(engine.host.spoken[0], ("Hello, this is English text that cannot be translated now.", "en"))
        self.assertIn("Перевод недоступен", notices[-1])

    def test_second_press_stops_the_rest(self):
        planner = _Planner()
        engine = self.make(planner, read_aloud={"enabled": True})
        stopped = []

        def translate(text, target):
            if len(planner.calls) == 1:
                engine._reading = True
                with mock.patch("luxai.selection.copy_selected_text"):
                    engine.read_selection()  # second press while reading
                stopped.append(True)
            return f"[{target}] {text}"

        planner.result = translate
        engine.read_text("English sentence number one is here. " * 40, wait=True)
        self.pump()
        self.assertTrue(stopped)
        self.assertEqual(engine.host.spoken, [])

    def test_foreign_notification_is_translated_keeping_the_app_name(self):
        planner = _Planner(lambda text, target: "Мама — Купи хлеба")
        engine = self.make(planner, notification_reader={"enabled": True})
        engine.seen_notification_apps.add("Telegram")
        with mock.patch.object(runtime.ExtensionsRuntime, "_silence_reason", return_value=""):
            engine._translate_notification("Telegram: Mom — Please buy some bread", wait=True)
            self.pump()
        self.assertEqual(planner.calls, [("Mom — Please buy some bread", "ru")])
        self.assertEqual(engine.host.spoken, [("Telegram: Мама — Купи хлеба", "ru")])
        self.assertEqual(engine.notification_memory[-1], "Telegram: Мама — Купи хлеба")

    def test_notification_in_jarvis_language_skips_translation(self):
        planner = _Planner()
        engine = self.make(planner, notification_reader={"enabled": True})
        engine.seen_notification_apps.add("Telegram")
        self.assertFalse(engine._notification_foreign("Telegram: Мама — Купи хлеба"))
        self.assertTrue(engine._notification_foreign("Telegram: Mom — Please buy some bread today"))

    def test_failed_notification_translation_reads_the_original(self):
        planner = _Planner(lambda text, target: None)
        engine = self.make(planner, notification_reader={"enabled": True})
        engine.seen_notification_apps.add("Telegram")
        with mock.patch.object(runtime.ExtensionsRuntime, "_silence_reason", return_value=""):
            engine._translate_notification("Telegram: Mom — Please buy some bread", wait=True)
            self.pump()
        self.assertEqual(engine.host.spoken, [("Telegram: Mom — Please buy some bread", "en")])


if __name__ == "__main__":
    unittest.main()
