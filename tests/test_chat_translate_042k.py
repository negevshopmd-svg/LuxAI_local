"""0.4.2k: «переведи …» in the chat goes to the offline translator; Update.bat installs it."""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from luxai import chat_translate as ct  # noqa: E402
from luxai import offline_translate as ot  # noqa: E402


class ParseTests(unittest.TestCase):
    def test_phrasings(self):
        cases = {
            "переведи на английский: Я люблю кошек": ("Я люблю кошек", "en", "ru"),
            "Джарвис, переведи «Good morning» на русский": ("Good morning", "ru", "ru"),
            "переведи hello world": ("hello world", "", "ru"),
            "переведи на английский": ("", "en", "ru"),
            "translate to Romanian: I will be late": ("I will be late", "ro", "en"),
            "translate I am hungry into Russian": ("I am hungry", "ru", "en"),
            "tradu în engleză: Mâine plouă": ("Mâine plouă", "en", "ro"),
            "tradu textul acesta în rusă: Bună dimineața": ("Bună dimineața", "ru", "ro"),
            "как будет по-английски кошка": ("кошка", "en", "ru"),
            "как сказать спасибо по-румынски?": ("спасибо", "ro", "ru"),
            "how do you say thank you in Romanian?": ("thank you", "ro", "en"),
            "cum se spune mulțumesc în rusă?": ("mulțumesc", "ru", "ro"),
            "переведи на немецкий Добрый день": ("Добрый день", "de", "ru"),
        }
        for phrase, expected in cases.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(ct.parse_request(phrase), expected)

    def test_not_a_translation(self):
        for phrase in ("какая сегодня погода", "открой браузер", "hello there", ""):
            self.assertIsNone(ct.parse_request(phrase))

    def test_target_without_a_named_language(self):
        self.assertEqual(ct.choose_target("Hello, how are you?", "", "ru"), "ru")
        self.assertEqual(ct.choose_target("Привет, как дела?", "", "ru"), "en")
        self.assertEqual(ct.choose_target("Hello, how are you?", "", "en"), "ru")
        self.assertEqual(ct.choose_target("Hello", "de", "ru"), "de")


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from luxai.extensions_runtime import ExtensionsRuntime
        host = mock.Mock()
        host.cfg = {"language": "ru", "ui_language": "ru"}
        host.online_planner = None
        self.runtime = ExtensionsRuntime(host)

    def _answer(self, phrase, method="handle_text_request"):
        """Since 0.4.2r the translation runs on a worker and answers through chat_reply (audit #26)."""
        from PySide6.QtWidgets import QApplication
        from luxai.extensions_runtime import AsyncReply
        replies = []
        self.runtime.chat_reply.connect(lambda text, language: replies.append((text, language)))
        first = getattr(self.runtime, method)(phrase)
        self.assertIsInstance(first, AsyncReply)  # the window is not blocked
        import time as _time
        end = _time.time() + 5
        while not replies and _time.time() < end:
            QApplication.processEvents()
            _time.sleep(0.01)
        return replies[0]

    def test_translation_reply_and_voice(self):
        with mock.patch.object(ot, "installed", return_value=True), \
                mock.patch("luxai.translation.translate_offline", return_value="I love cats") as offline:
            self.assertEqual(self._answer("переведи на английский: Я люблю кошек"), ("I love cats", "en"))
        offline.assert_called_once_with("Я люблю кошек", "en", "ru")

    def test_pc_commands_are_left_alone(self):
        with mock.patch("luxai.translation.translate_offline") as offline:
            for phrase in ("переведи компьютер в спящий режим", "переведи деньги маме", "tradu-mi asta"):
                self.assertIsNone(self.runtime.handle_translate_request(phrase))
        offline.assert_not_called()

    def test_foreign_text_without_language_goes_to_jarvis_language(self):
        with mock.patch.object(ot, "installed", return_value=True), \
                mock.patch("luxai.translation.translate_offline", return_value="Привет") as offline:
            self.assertEqual(self._answer("переведи hello, how are you?", "handle_translate_request")[0], "Привет")
        self.assertEqual(offline.call_args[0][1], "ru")

    def test_asks_for_text_and_waits_for_download(self):
        self.assertIn("Что перевести", self.runtime.handle_translate_request("переведи на английский"))
        with mock.patch.object(ot, "installed", return_value=False), \
                mock.patch.object(ot, "download_in_background") as download:
            self.assertIn("скачивается", self.runtime.handle_translate_request("переведи на английский: кошка"))
        download.assert_called_once()


class UpdateTests(unittest.TestCase):
    def test_update_installs_the_translator(self):
        source = (ROOT / "Update.py").read_text(encoding="utf-8")
        self.assertIn('"-m", "luxai.offline_translate"', source)

    def test_download_is_pinned_and_checked(self):
        self.assertRegex(ot.REVISION, r"^[0-9a-f]{40}$")
        self.assertEqual(set(ot.SHA256), {"model.bin", "tokenizer.json", "config.json", "shared_vocabulary.txt",
                                          "special_tokens_map.json"})
        with mock.patch("huggingface_hub.snapshot_download") as download, \
                mock.patch.object(ot, "installed", side_effect=[False, False]), \
                mock.patch.object(ot, "verified", return_value=False), \
                mock.patch("pathlib.Path.unlink") as unlink:
            self.assertFalse(ot.ensure_downloaded(Path("nowhere")))
        self.assertEqual(download.call_args.kwargs["revision"], ot.REVISION)
        self.assertEqual(unlink.call_count, len(ot.SHA256))  # a damaged file is removed, never loaded

    def test_main_reports_installed(self):
        with mock.patch.object(ot, "installed", return_value=True):
            self.assertEqual(ot.main(), 0)


if __name__ == "__main__":
    unittest.main()
