"""0.4.3p: the sixth audit report (0.4.3o, 2026-11-21)."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest import mock

import numpy as np
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]


class InstalledFilesTests(unittest.TestCase):
    """#1: «already up to date» also checks that the installed files are there and intact."""

    def setUp(self):
        import Update
        self.Update = Update
        self.root = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(Update, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.root / "luxai").mkdir()
        self.good = b"print('ok')\n"
        (self.root / "luxai" / "a.py").write_bytes(self.good)
        (self.root / "main.py").write_bytes(self.good)
        digest = hashlib.sha256(self.good).hexdigest()
        self.recorded = {"luxai/a.py": digest, "main.py": digest}

    def test_intact_installation_is_not_reinstalled(self):
        self.assertEqual(self.Update.damaged_installed_files(self.recorded), [])

    def test_missing_and_changed_files_are_found(self):
        (self.root / "luxai" / "a.py").unlink()
        (self.root / "main.py").write_bytes(b"damaged")
        self.assertEqual(sorted(self.Update.damaged_installed_files(self.recorded)), ["luxai/a.py", "main.py"])

    def test_paths_outside_the_program_or_bad_digests_are_ignored(self):
        self.assertEqual(self.Update.damaged_installed_files({"../outside.py": "0" * 64, "main.py": "nope"}), [])

    def test_the_update_reinstalls_when_files_are_damaged(self):
        source = (ROOT / "Update.py").read_text(encoding="utf-8")
        self.assertIn("damaged = damaged_installed_files(_previous_file_hashes())", source)
        self.assertIn('current_sha = ""', source.split("damaged = damaged_installed_files")[1][:400])


class ReminderTests(unittest.TestCase):
    now = dt.datetime(2026, 11, 21, 7, 0)

    def parse(self, text):
        from luxai.timers import parse_request
        return parse_request(text, self.now)

    def test_the_time_in_the_message_is_not_the_reminder_time(self):
        """#2"""
        request = self.parse("remind me at 6 pm to check the 19:45 departure")
        self.assertEqual((request.at.hour, request.at.minute, request.label), (18, 0, "check the 19:45 departure"))
        request = self.parse("remind me at 08:00 to check the 19:45 departure")
        self.assertEqual((request.at.hour, request.label), (8, "check the 19:45 departure"))
        request = self.parse("напомни в 9 проверить поезд в 19:45")
        self.assertEqual((request.at.hour, request.label), (9, "проверить поезд в 19:45"))
        request = self.parse("remind me to check the departure at 19:45")
        self.assertEqual((request.at.hour, request.at.minute, request.label), (19, 45, "check the departure"))

    def test_a_half_after_the_unit_counts(self):
        """#12"""
        from luxai.timers import parse_duration
        for text in ("pune un cronometru pentru 2 ore și jumătate", "pune un cronometru pentru 2 ore si jumatate",
                     "set a timer for 2 and a half hours", "таймер на два с половиной часа", "таймер на 2 часа и половина"):
            self.assertEqual(parse_duration(text), 9000, text)
        self.assertEqual(parse_duration("o jumătate de oră"), 1800)
        self.assertEqual(self.parse("amintește-mi peste 2 ore și jumătate să sun").seconds, 9000)


class AtomicWriteTests(unittest.TestCase):
    def test_zero_attempts_still_writes(self):
        """#13"""
        from luxai.atomic_io import atomic_write_bytes
        target = Path(tempfile.mkdtemp()) / "data.json"
        target.write_bytes(b"old")
        atomic_write_bytes(target, b"new", attempts=0)
        self.assertEqual(target.read_bytes(), b"new")


class ConverterTests(unittest.TestCase):
    def test_a_failed_png_compression_leaves_no_broken_file(self):
        """#10"""
        from PIL import Image
        from luxai import converter
        folder = Path(tempfile.mkdtemp())
        source = folder / "small.png"
        Image.new("RGB", (40, 30), (200, 10, 10)).save(source)
        real_save = Image.Image.save

        def broken(self, fp, *args, **kwargs):
            if str(fp).endswith("_compressed.png"):
                Path(fp).write_bytes(b"\x89PNG broken!")
                raise OSError("disk full")
            return real_save(self, fp, *args, **kwargs)

        with mock.patch.object(Image.Image, "save", broken):
            with self.assertRaises(OSError):
                converter.image_compress(source)
        self.assertEqual([p.name for p in folder.iterdir()], ["small.png"])


class RepeatTests(unittest.TestCase):
    def test_a_repetition_in_one_pass_stays_two_lines(self):
        """#8"""
        from luxai import film_captions as fc
        timeline = fc.CueTimeline()
        timeline.add([fc.Cue(10.3, 11.2, "Yes.", pass_id=4)], 10, 12)
        timeline.add([fc.Cue(10.6, 11.4, "Yes!", pass_id=4)], 10, 12)
        self.assertEqual([c.text for c in timeline.cues], ["Yes.", "Yes!"])

    def test_the_same_line_from_another_pass_is_still_replaced(self):
        from luxai import film_captions as fc
        timeline = fc.CueTimeline()
        timeline.add([fc.Cue(10.3, 11.2, "Yes.", pass_id=4)], 10, 12)
        timeline.add([fc.Cue(10.35, 11.25, "Yes.", pass_id=5)], 10, 12)
        self.assertEqual(len(timeline.cues), 1)


class NotificationCallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_a_second_call_is_explained_again(self):
        """#9: the call ended while nothing arrived; the next call is told again."""
        from luxai import extensions_catalog as catalog
        from luxai import notifications as n
        from luxai.extensions_runtime import ExtensionsRuntime
        host = mock.Mock(spec=["cfg", "_queue_speech", "save_extensions_meta"])
        host.cfg = {"language": "ro", "tts_enabled": True, "extensions_meta": {}}
        runtime = ExtensionsRuntime(host)
        self.addCleanup(runtime.deleteLater)
        runtime.state = catalog.normalize_state({"notification_reader": {"enabled": True, "settings": {}}})
        notices = []
        runtime.notice.connect(notices.append)
        with mock.patch.object(n, "call_app", return_value="Discord"):
            with mock.patch.object(runtime, "_silence_reason", return_value="call"):
                runtime._accept_notification("Telegram: Mama — salut")
            with mock.patch.object(runtime, "_silence_reason", return_value=""):
                runtime._flush_notifications()  # an empty poll after the call ended
            with mock.patch.object(runtime, "_silence_reason", return_value="call"):
                runtime._accept_notification("Telegram: Tata — ce faci")
        self.assertEqual(len(notices), 2)


@unittest.skipUnless(shutil.which("node"), "Node.js runs the extension's page hook")
class DashAudioTests(unittest.TestCase):
    def test_dash_aac_fragments_reach_jarvis(self):
        """#3: MP4 fragments that start with styp / sidx before moof are captured (0 packets before)."""
        import av
        from luxai import film_captions as fc
        folder = Path(tempfile.mkdtemp())
        here = os.getcwd()
        os.chdir(folder)  # FFmpeg's DASH muxer writes the segments next to the current folder
        self.addCleanup(os.chdir, here)
        with av.open(str(folder / "audio.mpd"), "w", format="dash", options={
                "seg_duration": "2", "use_template": "1", "use_timeline": "0", "single_file": "0",
                "init_seg_name": "init.mp4", "media_seg_name": "seg-$Number$.m4s"}) as out:
            stream = out.add_stream("aac", rate=48000)
            stream.layout = "mono"
            pts = 0
            for _ in range(48000 * 6 // 1024):
                tone = (np.sin(2 * np.pi * 440 * (np.arange(1024) + pts) / 48000) * 8000).astype(np.int16)
                frame = av.AudioFrame.from_ndarray(tone.reshape(1, -1), format="s16", layout="mono")
                frame.sample_rate, frame.pts, frame.time_base = 48000, pts, Fraction(1, 48000)
                pts += 1024
                for packet in stream.encode(frame):
                    out.mux(packet)
            for packet in stream.encode(None):
                out.mux(packet)
        segments = sorted(folder.glob("seg-*.m4s"), key=lambda f: int(f.stem.split("-")[1]))
        self.assertEqual(segments[0].read_bytes()[4:8], b"styp")  # the arrangement of the report
        result = subprocess.run(["node", str(ROOT / "tests" / "js" / "hook_harness.js"), 'audio/mp4; codecs="mp4a.40.2"',
                                 str(folder / "init.mp4"), *map(str, segments)],
                                capture_output=True, text=True, timeout=60, check=True)
        packets = json.loads(result.stdout)
        self.assertEqual(len(packets), len(segments))
        assembly = fc.BufferAssembly()
        whole = None
        for packet in packets:
            whole, need = assembly.feed("p", {
                "kind": packet["kind"], "track": packet["track"], "offset": packet["offset"], "epoch": packet["epoch"],
                "full": packet["full"], "header": base64.b64decode(packet["header"]),
                "pieces": [(n, start, base64.b64decode(data)) for n, start, data in packet["pieces"]]})
            self.assertFalse(need)
        seconds = sum(len(audio) for _begin, audio in fc.decode_browser_audio("mp4", 0.0, whole[3])) / 16000
        self.assertGreater(seconds, 5.5)


class ExtensionCodeTests(unittest.TestCase):
    def test_extension_contract(self):
        content = (ROOT / "browser_extension" / "content.js").read_text(encoding="utf-8")
        background = (ROOT / "browser_extension" / "background.js").read_text(encoding="utf-8")
        page = (ROOT / "browser_extension" / "youtube_audio.js").read_text(encoding="utf-8")
        manifest = json.loads((ROOT / "browser_extension" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "1.11.0")
        # #4: a «ready» answer belongs to one hold
        self.assertIn("holdId: opening?.video === video ? opening.id : 0", content)
        self.assertIn("forThisHold && answer?.openingReady", content)
        self.assertIn("document.openingHold = state.hold_id", background)
        # #5: resumed once the new source can play; the user's own action cancels it
        self.assertIn('event.type === "canplay"', content)
        self.assertIn("resumeWhenReady = null; // the user acts", content)
        # #6: «never pause» releases a running hold
        self.assertIn("|| !canPreroll", content)
        # #7: refused packet ≠ Jarvis away; queued audio only for an active, visible tab
        self.assertIn("return { rejected: true }", background)
        self.assertIn("value.active && value.visible", background)
        # #11: closing one document keeps another frame's state
        self.assertIn("value.includes(slot.state?.doc)", background)
        # #3 / #14
        self.assertIn('const BEFORE_MOOF = ["styp", "sidx", "emsg", "prft", "free", "skip"]', page)
        self.assertIn("chunk.sentParts = chunk.parts.length", page)


if __name__ == "__main__":
    unittest.main()
