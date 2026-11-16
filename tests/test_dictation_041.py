"""0.4.1 Smart dictation: punctuation, voice trigger, double tap and runtime flow."""
import unittest
from unittest import mock

import numpy as np
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from luxai import dictation
from luxai import extensions_catalog as catalog
from luxai import extensions_runtime as runtime


class PunctuationTests(unittest.TestCase):
    def test_spoken_marks_in_three_languages(self):
        p = dictation.apply_spoken_punctuation
        self.assertEqual(p("привет запятая как дела вопросительный знак"), "Привет, как дела?")
        self.assertEqual(p("Привет, запятая, как дела. Точка."), "Привет, как дела.")
        self.assertEqual(p("salut virgulă ce faci semnul întrebării"), "Salut, ce faci?")
        self.assertEqual(p("hello comma world full stop new paragraph bye"), "Hello, world.\n\nBye")
        self.assertEqual(p("он сказал тире да"), "Он сказал — да")

    def test_real_whisper_output_does_not_double_marks(self):
        p = dictation.apply_spoken_punctuation
        raw = ("Привет, запитая, как у тебя дела? Вопросительный знак, новая строка, "
               "я купил хлеб, молоко, удали последнее слово, сыр.")
        self.assertEqual(p(raw), "Привет, как у тебя дела?\nЯ купил хлеб сыр.")
        self.assertEqual(p("How are you doing today question mark?"), "How are you doing today?")

    def test_ordinary_text_and_idioms_stay(self):
        p = dictation.apply_spoken_punctuation
        self.assertEqual(p("просто текст без знаков"), "просто текст без знаков")
        self.assertEqual(p("с моей точки зрения это верно точка"), "С моей точки зрения это верно.")

    def test_delete_last_word_and_quotes(self):
        p = dictation.apply_spoken_punctuation
        self.assertEqual(p("я купил хлеб молоко удали последнее слово сыр точка"), "Я купил хлеб сыр.")
        self.assertEqual(p("он сказал кавычки привет кавычки точка"), "Он сказал «привет».")
        self.assertEqual(p("buy milk delete last word bread period"), "Buy bread.")

    def test_voice_request(self):
        phrases = "напиши, write, scrie"
        self.assertEqual(dictation.voice_dictation_request("Джарвис, напиши привет как дела", phrases), "привет как дела")
        self.assertEqual(dictation.voice_dictation_request("Jarvis scrie", phrases), "")
        self.assertEqual(dictation.voice_dictation_request("write: hello", phrases), "hello")
        self.assertIsNone(dictation.voice_dictation_request("открой стим", phrases))
        self.assertIsNone(dictation.voice_dictation_request("напишите отчёт", phrases))  # whole word only

    def test_double_tap(self):
        tap = dictation.DoubleTapDetector()
        events = [tap.update(*step) for step in [(True, 0), (False, .1), (True, .2), (True, .5), (False, .9)]]
        self.assertEqual(events, ["", "", "double", "", "release"])
        slow = dictation.DoubleTapDetector()
        self.assertEqual([slow.update(*step) for step in [(True, 0), (False, .1), (True, .9), (False, 1)]], ["", "", "", ""])

    def test_type_text_presses_enter_between_lines(self):
        typed, keys = [], []
        dictation.type_text("Строка один\nдва", typer=typed.append, enter=lambda: keys.append("enter"))
        self.assertEqual(typed, ["Строка один", "два"])
        self.assertEqual(keys, ["enter"])

    def test_resample(self):
        audio = np.ones(48000, dtype=np.float32)
        self.assertEqual(len(dictation.resample(audio, 48000)), 16000)


class _Recorder:
    def __init__(self, cfg):
        self.full = False
        self.voiced_once = True
        self.started = False

    def start(self):
        self.started = True

    def silent_for(self):
        return 0.0

    def stop(self):
        return np.zeros(16000, dtype=np.float32)


class _Model:
    def transcribe(self, audio, **options):
        segment = mock.Mock()
        segment.text = " привет запятая мир точка"
        return [segment], None


class _Host:
    def __init__(self):
        self.cfg = {"ui_language": "ru", "language": "ru"}
        self.tray_icon = None

    def dictation_model(self):
        return _Model()


class RuntimeDictationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, **settings):
        state = catalog.normalize_state({"smart_dictation": {"enabled": True, "settings": {"sound": False, **settings}}})
        engine = runtime.ExtensionsRuntime(_Host())
        engine.apply(state)

        def dispose():
            engine.stop()
            if engine._overlay is not None:
                engine._overlay.deleteLater()
            engine.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        self.addCleanup(dispose)
        return engine

    def test_plugin_is_ready_and_uses_right_ctrl_by_default(self):
        plugin = catalog.PLUGIN_BY_ID["smart_dictation"]
        self.assertTrue(plugin.ready)
        engine = self.make()
        self.assertEqual(engine.hotkey_entries(), [])  # double tap is polled, not registered
        custom = self.make(trigger="hotkey")
        self.assertEqual([entry["id"] for entry in custom.hotkey_entries()], ["smart_dictation.hotkey"])

    def test_full_flow_closes_listener_gate_and_types_result(self):
        engine = self.make(mode="toggle")
        inserted = []
        engine.insert_dictation = lambda text, target: inserted.append((text, target))
        with mock.patch.object(dictation, "Recorder", _Recorder), \
                mock.patch.object(runtime, "_foreground_window", return_value=4242):
            self.assertTrue(engine.start_dictation())
        self.assertTrue(dictation.DICTATION_ACTIVE.is_set())
        self.assertTrue(engine.dictating)
        engine.toggle_dictation()  # second press stops in toggle mode
        for _ in range(200):
            self.app.processEvents()
            if inserted:
                break
            QCoreApplication.processEvents()
            import time
            time.sleep(0.01)
        self.assertEqual(inserted, [("Привет, мир.", 4242)])
        self.assertFalse(dictation.DICTATION_ACTIVE.is_set())
        self.assertEqual(engine.last_dictation, "Привет, мир.")

    def test_cancel_clears_gate(self):
        engine = self.make()
        with mock.patch.object(dictation, "Recorder", _Recorder):
            engine.start_dictation(target=1)
        engine.cancel_dictation()
        self.assertFalse(engine.dictating)
        self.assertFalse(dictation.DICTATION_ACTIVE.is_set())

    def test_voice_trigger(self):
        engine = self.make(voice_trigger=True)
        inserted = []
        engine.insert_dictation = lambda text, target: inserted.append((text, target))
        self.assertTrue(engine.handle_voice_request("Джарвис, напиши привет запятая мир", 7))
        self.assertEqual(inserted, [("Привет, мир", 7)])
        self.assertFalse(engine.handle_voice_request("открой стим", 7))
        with mock.patch.object(dictation, "Recorder", _Recorder):
            self.assertTrue(engine.handle_voice_request("напиши", 7))
        self.assertEqual(engine._dictation_source, "voice")
        self.assertEqual(engine._dictation_target, 7)
        disabled = self.make(voice_trigger=False)
        self.assertFalse(disabled.handle_voice_request("напиши привет", 7))

    def test_ai_polish_is_optional(self):
        planner = mock.Mock()
        planner.polish_dictation.return_value = "Полировано."
        self.assertEqual(runtime.ExtensionsRuntime.finish_text("текст", {"ai_cleanup": True}, planner), "Полировано.")
        planner.polish_dictation.return_value = None
        self.assertEqual(runtime.ExtensionsRuntime.finish_text("текст", {"ai_cleanup": True}, planner), "текст")
        self.assertEqual(runtime.ExtensionsRuntime.finish_text("текст", {"ai_cleanup": False}, planner), "текст")


if __name__ == "__main__":
    unittest.main()
