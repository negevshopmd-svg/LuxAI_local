"""0.4.2r: fixes from the audit report of 2026-11-19 (numbers are the report's findings)."""
import ast
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from fractions import Fraction
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402


class SourceTests(unittest.TestCase):
    def test_no_control_characters_in_sources(self):
        """#10: a regex replacement «\\1» had become the invisible U+0001."""
        names = subprocess.run(["git", "ls-files", "*.py", "*.ps1", "*.bat"], cwd=ROOT, capture_output=True,
                               text=True).stdout.split()
        for name in names:
            data = (ROOT / name).read_bytes()
            bad = [byte for byte in data if byte < 32 and byte not in (9, 10, 13)]
            self.assertEqual(bad, [], name)

    def test_no_duplicate_dictionary_keys(self):
        """#43: one alias, one definition."""
        for name in ("luxai/websites.py", "luxai/screen_interact.py"):
            tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Dict, ast.Set)):
                    keys = [ast.literal_eval(key) for key in (node.keys if isinstance(node, ast.Dict) else node.elts)
                            if isinstance(key, ast.Constant)]
                    self.assertEqual(len(keys), len(set(keys)), name)


class TranslationTests(unittest.TestCase):
    def test_punctuation_is_kept(self):
        from luxai import offline_translate as ot
        fake = mock.Mock()
        result = mock.Mock()
        result.hypotheses = [["▁Salut", "▁!"]]
        fake.translate_batch.return_value = [result]
        translator = ot.OfflineTranslator.__new__(ot.OfflineTranslator)
        translator.translator = fake
        translator._run = __import__("threading").Lock()
        translator.tokenizer = mock.Mock()
        translator.tokenizer.encode.return_value.tokens = ["▁Hello"]
        translator.tokenizer.token_to_id.side_effect = lambda token: 1
        translator.tokenizer.decode.return_value = "Salut !"
        self.assertEqual(translator.translate("Hello there friend", "en", "ro"), "Salut!")

    def test_broken_model_is_retried_after_repair(self):
        from luxai import offline_translate as ot
        with tempfile.TemporaryDirectory() as folder:
            for name in ("model.bin", "tokenizer.json", "config.json"):
                Path(folder, name).write_text("x")
            with mock.patch.object(ot, "_loaded", None), mock.patch.object(ot, "_failed", None), \
                    mock.patch.object(ot, "OfflineTranslator", side_effect=RuntimeError("bad")) as load, \
                    mock.patch.object(ot, "repair_in_background") as repair:
                self.assertIsNone(ot.get(Path(folder)))
                self.assertIsNone(ot.get(Path(folder)))
                self.assertEqual(load.call_count, 1)  # the same broken files are not loaded again
                repair.assert_called_once()
                time.sleep(0.01)
                Path(folder, "model.bin").write_text("repaired")  # new files: a new try
                self.assertIsNone(ot.get(Path(folder)))
                self.assertEqual(load.call_count, 2)


class TimerTests(unittest.TestCase):
    NOW = dt.datetime(2026, 11, 19, 8, 0)

    def parse(self, text):
        from luxai.timers import parse_request
        return parse_request(text, self.NOW)

    def test_reminders_keep_their_message(self):
        request = self.parse("remind me in five minutes to call Ana")
        self.assertEqual((request.seconds, request.label), (300, "call Ana"))
        request = self.parse("remind me at 09:30 to call Ana")
        self.assertEqual((request.kind, request.label), ("alarm", "call Ana"))
        request = self.parse("remind me in 5 minutes to check oven for 2 minutes")
        self.assertEqual(request.seconds, 300)
        self.assertIn("for 2 minutes", request.label)

    def test_negative_and_general_questions(self):
        self.assertIsNone(self.parse("set a timer for -5 minutes"))
        self.assertIsNone(self.parse("help me understand how long is left in this video"))
        self.assertEqual(self.parse("сколько осталось").kind, "list")

    def test_non_finite_values_are_refused(self):
        from luxai.timers import TimerStore
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "timers.json")
            path.write_text('[{"id": "a", "kind": "timer", "due": NaN}, {"id": "b", "kind": "timer", "due": Infinity},'
                            ' {"id": "c", "kind": "timer", "due": 1e30}, {"id": "d", "kind": "timer", "due": 1900000000}]')
            self.assertEqual([item.id for item in TimerStore(path).items], ["d"])

    def test_failed_save_changes_nothing(self):
        from luxai.timers import TimerStore, new_timer
        with tempfile.TemporaryDirectory() as folder:
            store = TimerStore(Path(folder, "timers.json"))
            with mock.patch.object(store, "save", side_effect=PermissionError("locked")):
                with self.assertRaises(PermissionError):
                    store.add(new_timer("timer", time.time() + 60))
            self.assertEqual(store.items, [])

    def test_alarm_rings_before_it_is_removed(self):
        from luxai.extensions_runtime import ExtensionsRuntime
        from luxai.timers import new_timer
        QApplication.instance() or QApplication([])
        host = mock.Mock()
        host.cfg = {}
        runtime = ExtensionsRuntime(host)
        timer = new_timer("timer", time.time() - 1, "", 60)
        runtime.timer_store.items = [timer]
        order = []
        with mock.patch.object(runtime, "enabled", return_value=True), \
                mock.patch.object(runtime, "ring", side_effect=lambda t: order.append("ring")), \
                mock.patch.object(runtime.timer_store, "remove", side_effect=OSError("locked")):
            runtime._check_timers()
            self.assertEqual(order, ["ring"])  # rang although the file was locked (#9)
            runtime._check_timers()
            self.assertEqual(order, ["ring"])  # and never twice
        with mock.patch.object(runtime, "enabled", return_value=False), \
                mock.patch.object(runtime, "ring") as ring:
            runtime._check_timers()  # #19: nothing rings when the extension is off
        ring.assert_not_called()


class ConverterTests(unittest.TestCase):
    def test_video_keeps_timestamps(self):
        import av
        import numpy as np
        from luxai import converter
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder, "vfr.mkv")
            with av.open(str(source), "w") as out:
                stream = out.add_stream("libx264", rate=25)
                stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
                stream.codec_context.time_base = Fraction(1, 1000)
                for ms in (0, 40, 960, 1000):
                    frame = av.VideoFrame.from_ndarray(np.zeros((48, 64, 3), dtype=np.uint8), format="rgb24")
                    frame.pts, frame.time_base = ms, Fraction(1, 1000)
                    for packet in stream.encode(frame):
                        out.mux(packet)
                for packet in stream.encode(None):
                    out.mux(packet)
            result = converter.video_convert(source, mode="mp4", out_dir=Path(folder, "out"))
            with av.open(str(result)) as media:
                times = [round(frame.time, 2) for frame in media.decode(video=0)]
            self.assertEqual(times, [0.0, 0.04, 0.96, 1.0])

    def test_ico_from_a_wide_picture_and_unique_names(self):
        from PIL import Image
        from luxai import converter
        with tempfile.TemporaryDirectory() as folder:
            png = Path(folder, "wide.png")
            Image.new("RGBA", (100, 12), (255, 0, 0, 255)).save(png)
            self.assertTrue(converter.image_format(png, "ico", out_dir=Path(folder, "o")).stat().st_size > 0)
            first = converter.target_path(png, "png", out_dir=Path(folder, "same"))
            second = converter.target_path(png, "png", out_dir=Path(folder, "same"))
            self.assertNotEqual(first, second)  # #21: the first name is reserved on disk


class TelegramTests(unittest.TestCase):
    def test_a_failed_start_ends_both_threads(self):
        from luxai.telegram_control import TelegramBot, TelegramError
        statuses = []

        def caller(*_args, **_kwargs):
            raise TelegramError("no network")

        bot = TelegramBot("1:x", lambda update: None, lambda state, details: statuses.append(state), caller=caller)
        bot.start()
        for thread in bot._threads:
            thread.join(3)
        self.assertFalse(any(thread.is_alive() for thread in bot._threads))
        self.assertFalse(bot.running)
        self.assertIn("error", statuses)

    def test_non_json_answer_is_a_telegram_error(self):
        from luxai.telegram_control import TelegramError, call
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"<html>bad gateway</html>"
        opener = mock.Mock()
        opener.open.return_value = response
        with self.assertRaises(TelegramError):
            call("123456789:" + "A" * 35, "getMe", opener=opener)

    def test_undelivered_reply_is_reported(self):
        from luxai.telegram_control import TelegramBot
        statuses = []
        bot = TelegramBot("1:x", lambda update: None, lambda state, details: statuses.append(state))
        for _ in range(bot.outbox.maxsize):
            bot.outbox.put_nowait(("sendMessage", {}))
        self.assertFalse(bot.send("sendMessage", {}))
        self.assertEqual(statuses, ["undelivered"])


class UpdateTests(unittest.TestCase):
    def test_version_letters_after_z(self):
        from luxai.settings_updates import version_key
        self.assertGreater(version_key("0.4.2aa"), version_key("0.4.2z"))
        self.assertGreater(version_key("0.4.3"), version_key("0.4.2zz"))

    def test_bootstrap_hash_matches_git(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import fetch_updater
        data = b"print('hi')\n"
        expected = subprocess.run(["git", "hash-object", "--stdin"], input=data, capture_output=True,
                                  cwd=ROOT).stdout.decode().strip()
        self.assertEqual(fetch_updater.git_blob_sha(data), expected)

    def test_dropped_files_are_removed_only_when_unchanged(self):
        import hashlib
        import Update
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(Update, "ROOT", Path(folder)), \
                mock.patch.object(Update, "_report_console"):
            old = Path(folder, "luxai", "old.py")
            old.parent.mkdir()
            old.write_text("old")
            edited = Path(folder, "luxai", "edited.py")
            edited.write_text("mine")
            previous = {"luxai/old.py": hashlib.sha256(b"old").hexdigest(),
                        "luxai/edited.py": hashlib.sha256(b"original").hexdigest(),
                        "config.json": "x", "../outside.py": "x"}
            self.assertEqual(Update.remove_dropped_files(previous, {}), 1)
            self.assertFalse(old.exists())
            self.assertTrue(edited.exists())  # changed by the user: kept

    def test_rollback_message_tells_the_truth(self):
        source = (ROOT / "Update.py").read_text(encoding="utf-8")
        self.assertIn("Restaurarea NU este completă", source)
        self.assertIn("'(main|launch_windows)\\.py'", source)  # #5: the pythonw launcher is found too

    def test_admin_task_of_another_folder_is_not_ours(self):
        import Update
        xml = "<Task><Actions><Exec><WorkingDirectory>C:\\Other\\Jarvis</WorkingDirectory></Exec></Actions></Task>"
        with mock.patch.object(Update.subprocess, "run",
                               return_value=mock.Mock(returncode=0, stdout=xml.encode("utf-8"))):
            with mock.patch.object(Update, "ROOT", Path("C:/Users/me/LuxAI_Local")):
                self.assertFalse(Update.admin_task_is_ours())
            with mock.patch.object(Update, "ROOT", Path("C:/Other/Jarvis")):
                self.assertTrue(Update.admin_task_is_ours())

    def test_batch_launcher_checks_the_task_folder(self):
        launcher = (ROOT / "run_windows.bat").read_text(encoding="ascii")
        self.assertIn("<WorkingDirectory>%HERE%</WorkingDirectory>", launcher)
        self.assertIn('start "" "%JARVIS_EXE%"', launcher)
        updater = (ROOT / "Update.bat").read_text(encoding="ascii")
        self.assertIn("fetch_updater.py", updater)
        self.assertIn(".luxai_bootstrap.lock", updater)
        self.assertIn('(`call %LUXAI_PYTHON% -I "scripts\\fetch_updater.py"`)', updater)  # 0.4.2s


class LaunchTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows mutex")
    def test_one_jarvis_per_folder(self):
        code = ("import sys; sys.path.insert(0, r'%s'); import launch_windows as lw; "
                "lw.ROOT = lw.ROOT.parent / 'LuxAI_mutex_unittest'; print(lw.single_instance(wait=0.5))" % ROOT)
        import launch_windows as lw
        with mock.patch.object(lw, "ROOT", ROOT.parent / "LuxAI_mutex_unittest"):
            self.assertTrue(lw.single_instance(wait=0.5))
            second = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout.strip()
            self.assertEqual(second, "False")

    def test_config_that_is_not_an_object(self):
        import main
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "config.json")
            path.write_text("[]", encoding="utf-8")
            with mock.patch.object(main, "CONFIG", path):
                self.assertEqual(main.load_config(), {})
            self.assertTrue(list(Path(folder).glob("config.broken-*.json")))
            self.assertIn("list", main.CONFIG_PROBLEM)


class ScreenshotTests(unittest.TestCase):
    def test_window_shot_without_a_window_is_refused(self):
        from luxai import extensions_runtime as rt
        QApplication.instance() or QApplication([])
        host = mock.Mock()
        host.cfg = {}
        runtime = rt.ExtensionsRuntime(host)
        notices = []
        with mock.patch.object(rt, "_foreground_rect", return_value=None), \
                mock.patch.object(rt, "capture_png") as capture, \
                mock.patch.object(runtime, "_notify", side_effect=notices.append):
            self.assertIsNone(runtime.take_screenshot(window=True))
        capture.assert_not_called()  # #37: never a full-screen picture instead
        self.assertTrue(notices)


if __name__ == "__main__":
    unittest.main()
