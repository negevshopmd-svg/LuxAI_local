"""0.4.1q: live captions like Luxify — segmenter, engine, bar, runtime, page."""
from __future__ import annotations

import tempfile
import unittest
from unittest import mock

import numpy as np
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QPushButton

from luxai import extensions_catalog as catalog
from luxai import live_captions as lc

RATE = lc.SAMPLE_RATE


def tone(seconds, level=0.2):
    t = np.arange(int(RATE * seconds)) / RATE
    return (level * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def quiet(seconds):
    return np.zeros(int(RATE * seconds), dtype=np.float32)


class SegmenterTests(unittest.TestCase):
    def test_phrase_ends_after_pause(self):
        seg = lc.PhraseSegmenter()
        seg.feed(quiet(2))
        self.assertFalse(seg.phrase_finished())
        self.assertLessEqual(seg.seconds, 0.31)  # only a short lead-in is kept
        seg.feed(tone(1.5))
        self.assertFalse(seg.phrase_finished())
        seg.feed(quiet(0.3))
        self.assertFalse(seg.phrase_finished())
        seg.feed(quiet(0.5))
        self.assertTrue(seg.phrase_finished())
        audio = seg.take()
        self.assertGreater(len(audio), RATE * 1.5)
        self.assertFalse(seg.phrase_finished())

    def test_long_speech_is_cut_at_five_seconds(self):
        seg = lc.PhraseSegmenter()
        seg.feed(tone(lc.MAX_PHRASE_SECONDS + 0.5))
        self.assertTrue(seg.phrase_finished())
        self.assertEqual(lc.MAX_PHRASE_SECONDS, 5.0)

    def test_continuous_speech_is_cut_between_words_and_rest_is_kept(self):
        seg = lc.PhraseSegmenter()
        seg.feed(tone(4.2))
        seg.feed(quiet(0.12))   # a short gap between two words (not a pause)
        seg.feed(tone(1.0))
        self.assertTrue(seg.phrase_finished())
        self.assertFalse(seg.paused)
        cut = seg.cut_point()
        gap_start, gap_end = int(RATE * 4.2), int(RATE * 4.32)
        self.assertTrue(gap_start <= cut <= gap_end + lc.FRAME, cut)
        total = len(seg.buffer)
        phrase = seg.take(cut)
        self.assertEqual(len(phrase) + len(seg.buffer), total)  # nothing is lost
        self.assertTrue(seg.heard_speech)  # the next phrase already started
        self.assertFalse(seg.phrase_finished())


class EngineTests(unittest.TestCase):
    def test_partial_then_final(self):
        partial, final = [], []
        engine = lc.CaptionEngine(lambda: object(), "ru", partial.append, final.append)
        with mock.patch.object(engine, "_transcribe", side_effect=["Привет", "Привет, мир"]):
            engine.feed(tone(1.0))
            engine.step(object())
            self.assertEqual(partial, ["Привет"])
            engine.feed(quiet(0.8))
            engine.step(object())
        self.assertEqual(final, ["Привет, мир"])
        self.assertEqual(partial[-1], "")

    def test_final_reuses_partial_that_covers_the_phrase(self):
        final = []
        engine = lc.CaptionEngine(lambda: object(), "ru", lambda _: None, final.append)
        with mock.patch.object(engine, "_transcribe", side_effect=["Привет, мир"]) as transcribe:
            engine.feed(tone(1.0))
            engine.feed(quiet(0.15))
            engine.step(object())        # partial over almost everything
            engine.feed(quiet(0.4))      # pause: phrase done, only silence was added
            engine.step(object())
        self.assertEqual(final, ["Привет, мир"])
        self.assertEqual(transcribe.call_count, 1)  # no second, slow pass

    def test_speed_setting_picks_a_fast_model(self):
        self.assertEqual(lc.QUALITY_MODELS, {"fast": "tiny", "balanced": "small"})
        plugin = catalog.PLUGIN_BY_ID["live_captions"]
        self.assertEqual(catalog.default_settings(plugin)["quality"], "balanced")

    def test_silence_never_reaches_whisper(self):
        engine = lc.CaptionEngine(lambda: object(), "ru", lambda _: None, lambda _: None)
        with mock.patch.object(engine, "_transcribe") as transcribe:
            engine.feed(quiet(3))
            engine.step(object())
        transcribe.assert_not_called()


class BarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_lines_translation_and_original_switch(self):
        bar = lc.CaptionBar()
        self.addCleanup(bar.deleteLater)
        bar.configure(lines=2)
        for text in ("one", "two", "three"):
            bar.add_final(text)
        bar.set_partial("four…")
        self.assertEqual([line for line, _ in bar.visible_lines()], ["three", "four…"])
        bar.set_translation("three", "три")
        self.assertIn("три", bar.text.text())
        self.assertIn("three", bar.text.text())
        bar.configure(show_original=False)
        self.assertNotIn(">three<", bar.text.text())
        bar.configure(lines=1)
        self.assertEqual(len(bar.visible_lines()), 1)
        self.assertNotIn("<script", bar.text.text())
        bar.set_partial("")
        bar.add_final("<script>x</script>")
        self.assertIn("&lt;script&gt;", bar.text.text())


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from luxai.extensions_runtime import ExtensionsRuntime
        self.host = mock.Mock()
        self.host.cfg = {"language": "ru", "extensions_meta": {}}
        self.host.online_planner.enabled.return_value = True
        self.runtime = ExtensionsRuntime(self.host)
        self.runtime.state = catalog.normalize_state({"live_captions": {"enabled": False, "settings": {}}})
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self.runtime.hide_captions()
        self.runtime.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_show_turns_plugin_on_and_starts_audio(self):
        with mock.patch.object(self.runtime, "_start_caption_audio") as start:
            answer = self.runtime.handle_text_request("Джарвис, покажи субтитры")
        self.assertEqual(answer, "Показал субтитры.")
        self.host.set_extension_enabled.assert_called_once_with("live_captions", True)
        start.assert_called_once()
        self.assertTrue(self.runtime.captions_visible)
        with mock.patch.object(self.runtime, "_stop_caption_audio"):
            self.assertEqual(self.runtime.handle_text_request("скрой субтитры"), "Скрыл субтитры.")
        self.assertFalse(self.runtime.captions_visible)
        self.assertIsNone(self.runtime.handle_text_request("покажи погоду"))

    def test_final_phrase_is_translated_into_program_language(self):
        self.runtime.state["live_captions"]["enabled"] = True
        self.runtime.state["live_captions"]["settings"]["translate"] = True
        with mock.patch.object(self.runtime, "_start_caption_audio"), \
                mock.patch("luxai.offline_translate.installed", return_value=True), \
                mock.patch("luxai.offline_translate.get", return_value=None), \
                mock.patch("luxai.translation.translate_offline", return_value="Привет всем") as offline:
            self.runtime.show_captions()
            self.runtime._on_cap_final("Hello everyone")
            import time
            end = time.time() + 5  # the translation worker answers through a Qt signal
            while time.time() < end and self.runtime._captions_bar.lines[-1][1] != "Привет всем":
                QApplication.processEvents()
                time.sleep(0.01)
        self.assertEqual(offline.call_args[0][:2], ("Hello everyone", "ru"))
        self.assertEqual(self.runtime._captions_bar.lines[-1], ("Hello everyone", "Привет всем"))

    def test_failed_translation_shows_the_original_not_dots_forever(self):
        self.runtime.state["live_captions"]["enabled"] = True
        self.runtime.state["live_captions"]["settings"]["translate"] = True
        with mock.patch.object(self.runtime, "_start_caption_audio"), \
                mock.patch("luxai.offline_translate.installed", return_value=True), \
                mock.patch("luxai.offline_translate.get", return_value=None), \
                mock.patch("luxai.translation.translate_offline", return_value=None):
            self.runtime.show_captions()
            self.runtime._on_cap_final("Hello everyone")
            import time
            end = time.time() + 5
            while time.time() < end and self.runtime._captions_bar.lines[-1][1] == lc.PENDING:
                QApplication.processEvents()
                time.sleep(0.01)
        self.assertEqual(self.runtime._captions_bar.lines[-1], ("Hello everyone", ""))
        self.assertIn("Hello everyone", self.runtime._captions_bar.text.text())

    def test_position_is_saved_and_reset(self):
        self.runtime._save_captions_position(100, 200)
        self.assertEqual(self.host.cfg["extensions_meta"]["captions_position"], [100, 200])
        self.runtime.reset_captions_position()
        self.assertNotIn("captions_position", self.host.cfg["extensions_meta"])

    def test_jarvis_voice_is_muted_in_the_feed(self):
        from luxai.voices import barge_in_ready
        fed = []
        self.runtime.state["live_captions"]["enabled"] = True
        with mock.patch("luxai.live_captions.CaptionEngine.start", lambda engine: engine), \
                mock.patch("luxai.live_captions.CaptionEngine.feed", lambda engine, chunk: fed.append(chunk)), \
                mock.patch("luxai.loopback_audio.LoopbackCapture.start", lambda capture: capture):
            self.runtime._start_caption_audio()
            capture = self.runtime._captions_capture
            barge_in_ready.set()
            try:
                capture.on_audio(tone(0.1))
            finally:
                barge_in_ready.clear()
            self.assertEqual(float(np.abs(fed[-1]).max()), 0.0)
            self.runtime._captions_capture = None
            self.runtime._captions_engine = None


class QualityTests(unittest.TestCase):
    def test_language_is_voted_then_kept(self):
        engine = lc.CaptionEngine(lambda: None, None, lambda _: None, lambda _: None)
        model = mock.Mock()
        model.detect_language.return_value = ("en", 0.97, [("en", 0.97), ("de", 0.01)])
        for _ in range(4):
            self.assertEqual(engine._spoken_language(model, tone(2.0)), "en")
        self.assertEqual(model.detect_language.call_count, 2)  # sure after two checks, then not on every pass
        engine._speech_since_detect = lc.REDETECT_SECONDS
        model.detect_language.return_value = ("ro", 0.9, [("ro", 0.9), ("it", 0.05)])
        engine._spoken_language(model, tone(2.0))  # re-checked after ~30 s: not sure any more…
        self.assertEqual(engine._spoken_language(model, tone(2.0)), "ro")  # …so the next pass switches
        fixed = lc.CaptionEngine(lambda: None, "ru", lambda _: None, lambda _: None)
        self.assertEqual(fixed._spoken_language(model, tone(2.0)), "ru")

    def test_one_wrong_first_guess_does_not_lock(self):
        engine = lc.CaptionEngine(lambda: None, None, lambda _: None, lambda _: None)
        model = mock.Mock()
        model.detect_language.return_value = ("ru", 0.45, [("ru", 0.45), ("ro", 0.40)])  # music intro
        engine._spoken_language(model, tone(2.0))
        model.detect_language.return_value = ("ro", 0.95, [("ro", 0.95), ("ru", 0.02)])
        engine._spoken_language(model, tone(2.0))
        self.assertEqual(engine._spoken_language(model, tone(2.0)), "ro")
        self.assertEqual(model.detect_language.call_count, 3)

    def test_untrustworthy_segments_are_dropped(self):
        good = mock.Mock(no_speech_prob=0.05, avg_logprob=-0.3, compression_ratio=1.4)
        silence = mock.Mock(no_speech_prob=0.9, avg_logprob=-0.9, compression_ratio=1.2)
        looped = mock.Mock(no_speech_prob=0.1, avg_logprob=-0.4, compression_ratio=3.1)
        unsure = mock.Mock(no_speech_prob=0.2, avg_logprob=-1.6, compression_ratio=1.3)
        self.assertEqual([lc.trustworthy(s) for s in (good, silence, looped, unsure)], [True, False, False, False])

    def test_doubled_final_line_is_not_repeated(self):
        finals = []
        engine = lc.CaptionEngine(lambda: object(), "en", lambda _: None, finals.append)
        with mock.patch.object(engine, "_transcribe", return_value="Hello there."):
            for _ in range(2):
                engine.feed(tone(1.0)); engine.feed(quiet(0.6))
                engine.step(object())
        self.assertEqual(finals, ["Hello there."])

    def test_auto_means_detect_not_the_voice_command_language(self):
        from luxai.extensions_runtime import ExtensionsRuntime
        QApplication.instance() or QApplication([])
        host = mock.Mock()
        host.cfg = {"language": "ru"}
        runtime = ExtensionsRuntime(host)
        runtime.state = catalog.normalize_state({"live_captions": {"enabled": True, "settings": {"language": "auto"}}})
        self.assertIsNone(runtime._caption_language())
        runtime.state["live_captions"]["settings"]["language"] = "ro"
        self.assertEqual(runtime._caption_language(), "ro")
        runtime.deleteLater()


class TranslateOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_only_the_translation_is_shown(self):
        bar = lc.CaptionBar()
        self.addCleanup(bar.deleteLater)
        bar.configure(show_original=False, lines=2)
        bar.add_final("Hello everyone", pending=True)
        self.assertNotIn("Hello everyone", bar.text.text())  # original never shown
        self.assertIn("…", bar.text.text())
        bar.set_translation("Hello everyone", "Всем привет")
        self.assertIn("Всем привет", bar.text.text())
        self.assertNotIn("Hello everyone", bar.text.text())
        self.assertFalse(catalog.default_settings(catalog.PLUGIN_BY_ID["live_captions"])["show_original"])


class AppListTests(unittest.TestCase):
    def test_open_programs_are_listed_even_when_silent(self):
        """A browser has no audio session until it plays: it must still be offered."""
        import sys
        if sys.platform != "win32":
            self.skipTest("Windows only")
        from luxai import loopback_audio as la

        class Proc:
            def __init__(self, pid, name, parent=None):
                self.pid, self._name, self._parent = pid, name, parent

            def name(self):
                return self._name

            def parent(self):
                return self._parent

        chrome_root = Proc(10, "chrome.exe")
        chrome_tab = Proc(11, "chrome.exe", chrome_root)
        discord = Proc(20, "Discord.exe")
        explorer = Proc(30, "explorer.exe")
        session = mock.Mock(Process=discord)
        processes = {11: chrome_tab, 20: discord, 30: explorer}
        with mock.patch("pycaw.pycaw.AudioUtilities.GetAllSessions", return_value=[session]),                 mock.patch.object(la, "_window_pids", return_value={11, 20, 30}),                 mock.patch("psutil.Process", side_effect=lambda pid: processes[pid]):
            apps = la.audio_apps()
        # Playing programs first, then the other open ones; Chrome by its top process.
        self.assertEqual(apps, [("Discord.exe", 20), ("chrome.exe", 10)])


class PageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_page_like_luxify(self):
        from luxai.extensions_runtime import ExtensionsRuntime
        from luxai.ui_extension_settings import PluginSettingsView
        host = mock.Mock()
        host.cfg = {"language": "ru"}
        host.online_planner.enabled.return_value = False
        runtime = ExtensionsRuntime(host)
        runtime.state = catalog.normalize_state({})
        plugin = catalog.PLUGIN_BY_ID["live_captions"]
        self.assertTrue(plugin.ready)
        with mock.patch("luxai.loopback_audio.audio_apps", return_value=[("Discord.exe", 5), ("steam.exe", 6)]):
            view = PluginSettingsView(plugin, runtime.state["live_captions"], "ru", runtime=runtime)
        self.addCleanup(view.deleteLater)
        self.assertEqual(list(view.cards), ["basic", "sound", "translate", "look", "key"])
        self.assertEqual(view.captions_button.text(), "Показать субтитры")
        self.assertIn("«Показать субтитры» включит", view.status_label.text())
        items = [view.source_combo.itemText(i) for i in range(view.source_combo.count())]
        self.assertEqual(items, ["Весь звук компьютера", "Только программа: Discord", "Только программа: steam"])
        view.source_combo.setCurrentIndex(1)
        self.assertEqual(view.collect()["source"], "Discord.exe")
        refresh = [button for button in view.findChildren(QPushButton) if button.toolTip().startswith("Обновить список программ")]
        self.assertEqual([button.objectName() for button in refresh], ["ExtIconButton"])  # never a black square
        self.assertIn("Перевод выключен", view.tr_label.text())
        with mock.patch("luxai.offline_translate.installed", return_value=False):
            view.fields["translate"].setChecked(True)
        self.assertIn("Переводчик скачивается", view.tr_label.text())
        with mock.patch("luxai.offline_translate.installed", return_value=True):
            view._render_translate_status(view.collect())
        self.assertIn("офлайн-переводчик", view.tr_label.text())
        self.assertTrue(view.rows["translate_to"].isEnabled())
        view.detach()


if __name__ == "__main__":
    unittest.main()
