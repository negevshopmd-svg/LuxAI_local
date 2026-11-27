"""0.4.4b: video and call notes — recording to disk on a timeline, transcription as it goes, AI notes."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from luxai import extensions_catalog as catalog  # noqa: E402
from luxai import meeting_notes as mn  # noqa: E402

RATE = mn.RATE


def tone(seconds, level=0.3, frequency=220):
    t = np.arange(int(RATE * seconds)) / RATE
    return (level * np.sin(2 * np.pi * frequency * t)).astype(np.float32)


class TempCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)


class TrackTests(TempCase):
    def test_silence_without_packets_is_filled_so_the_tracks_stay_in_step(self):
        now = [0.0]
        writer = mn.TrackWriter(self.folder / "system.wav", 0.0, clock=lambda: now[0])
        now[0] = 1.0
        writer.write(tone(1.0))
        now[0] = 5.0  # four seconds with no packets (nothing played), then one more second
        writer.write(tone(1.0))
        writer.close()
        self.assertEqual(writer.samples, 5 * RATE)
        self.assertEqual(mn.available_samples(self.folder / "system.wav"), 5 * RATE)
        middle = mn.read_samples(self.folder / "system.wav", 2 * RATE, RATE)
        self.assertEqual(float(np.max(np.abs(middle))), 0.0)
        header = (self.folder / "system.wav").read_bytes()[:44]
        self.assertEqual(int.from_bytes(header[40:44], "little"), 5 * RATE * 2)  # the header is right at the end

    def test_a_pause_writes_nothing_and_does_not_count(self):
        now = [0.0]
        writer = mn.TrackWriter(self.folder / "mic.wav", 0.0, clock=lambda: now[0])
        now[0] = 1.0
        writer.write(tone(1.0))
        writer.pause()
        now[0] = 31.0
        writer.write(tone(1.0))  # ignored while paused
        writer.resume()
        now[0] = 32.0
        writer.write(tone(1.0))
        writer.close()
        self.assertEqual(writer.samples, 2 * RATE)

    def test_a_crash_still_leaves_readable_audio(self):
        writer = mn.TrackWriter(self.folder / "mic.wav", time.monotonic())
        writer.write(tone(0.5))
        # no close(): the header still says 0 bytes, the reader trusts the file size
        self.assertEqual(mn.available_samples(self.folder / "mic.wav"), RATE // 2)
        writer.close()

    def test_cut_in_the_quietest_moment(self):
        audio = tone(30.0)
        audio[int(24.0 * RATE):int(24.3 * RATE)] = 0.0  # a pause at 24 s
        cut = mn.cut_point(audio, final=False)
        self.assertTrue(24.0 * RATE <= cut <= 24.4 * RATE, cut / RATE)
        self.assertEqual(mn.cut_point(audio, final=True), len(audio))

    def test_silence_is_not_transcribed_but_continuous_sound_is(self):
        self.assertFalse(mn.voiced(np.zeros(RATE * 5, dtype=np.float32)))
        self.assertFalse(mn.voiced(np.full(RATE * 5, 0.002, dtype=np.float32)))  # a quiet mic hiss
        self.assertTrue(mn.voiced(tone(5.0)))  # speech without a single pause
        audio = np.zeros(RATE * 5, dtype=np.float32)
        audio[RATE:2 * RATE] = tone(1.0)
        self.assertTrue(mn.voiced(audio))


class FakeModel:
    def __init__(self, text="Hello there."):
        self.text, self.calls = text, []

    def transcribe(self, audio, **kwargs):
        self.calls.append((len(audio), kwargs))
        segment = SimpleNamespace(start=0.5, end=2.0, text=self.text, no_speech_prob=0.0, avg_logprob=-0.2,
                                  compression_ratio=1.2)
        return [segment], None


class TranscriberTests(TempCase):
    def write(self, name, audio):
        writer = mn.TrackWriter(self.folder / f"{name}.wav", 0.0, clock=lambda: len(audio) / RATE)
        writer.write(audio)
        writer.close()

    def test_pieces_as_it_goes_and_the_rest_at_the_end(self):
        self.write("system", tone(70.0))
        model = FakeModel()
        transcriber = mn.Transcriber(self.folder, ["system"], lambda: model, "en")
        while transcriber.step(final=False):
            pass
        self.assertEqual(len(model.calls), 2)  # two pieces of ≤30 s were ready while «recording»
        transcriber.finish()
        self.assertEqual(transcriber.done["system"], 70 * RATE)
        lines = mn.load_lines(self.folder)
        self.assertEqual(len(lines), len(model.calls))
        self.assertLess(lines[0].start, lines[1].start)  # times are from the start of the recording

    def test_invented_text_and_unsure_segments_are_dropped(self):
        self.write("system", tone(5.0))
        for text in ("Субтитры сделал DimaTorzok", "Thanks for watching!", "..."):
            folder_model = FakeModel(text)
            transcriber = mn.Transcriber(self.folder, ["system"], lambda: folder_model, None)
            transcriber.finish()
            self.assertEqual(transcriber.lines, [], text)

    def test_a_failing_model_does_not_stop_the_notes(self):
        self.write("system", tone(5.0))
        broken = mock.Mock()
        broken.transcribe.side_effect = RuntimeError("out of memory")
        transcriber = mn.Transcriber(self.folder, ["system"], lambda: broken, None)
        self.assertTrue(transcriber.finish())
        self.assertEqual(transcriber.errors, ["RuntimeError"])

    def test_long_segments_become_one_line_per_sentence(self):
        text = ("Как видите, после забастовки поезда снова ходят по расписанию. Многие пассажиры рассказали нам, "
                "что ждали больше двух часов. Компания пообещала вернуть деньги за все отменённые билеты.")
        lines = mn.sentence_lines(10.0, 22.0, "system", text)
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0].start, 10.0)
        self.assertAlmostEqual(lines[-1].end, 22.0)


class TranscriptTests(unittest.TestCase):
    def test_speakers_times_and_echo(self):
        lines = [mn.Line(5.0, 7.0, "system", "Let us start with the budget."),
                 mn.Line(5.5, 7.0, "mic", "let us start with the budget"),   # the speakers, heard by the mic
                 mn.Line(9.0, 10.0, "mic", "I agree, send it by Friday."),
                 mn.Line(3725.0, 3726.0, "system", "Bye.")]
        kept = mn.drop_echo(lines)
        self.assertEqual(len(kept), 3)
        text = mn.transcript_text(kept, "ro", True)
        self.assertIn("[00:00:05] Ceilalți: Let us start with the budget.", text)
        self.assertIn("[00:00:09] Eu: I agree, send it by Friday.", text)
        self.assertIn("[01:02:05] Ceilalți: Bye.", text)
        self.assertNotIn("Eu:", mn.transcript_text([lines[2]], "ro", False))


NOTES = {"summary": "We agreed on the budget.", "topics": ["Budget"], "decisions": ["Budget approved"],
         "tasks": [{"who": "Ana", "what": "Send the report", "when": "Friday"}], "questions": ["Who pays travel?"]}


class SummaryTests(unittest.TestCase):
    def test_json_in_fences_or_with_text_around_it(self):
        answer = "Here you go:\n```json\n" + json.dumps(NOTES) + "\n```"
        self.assertEqual(mn.parse_notes(answer)["tasks"][0]["who"], "Ana")
        self.assertIsNone(mn.parse_notes("I cannot help with that."))
        self.assertIsNone(mn.parse_notes('{"summary": "", "topics": []}'))
        hostile = mn.parse_notes('{"summary": "x", "topics": [{"a": 1}, "ok"], "tasks": ["Call Ana"], "decisions": 5}')
        self.assertEqual(hostile["topics"], ["ok"])
        self.assertEqual(hostile["tasks"], [{"who": "", "what": "Call Ana", "when": ""}])
        self.assertEqual(hostile["decisions"], [])

    def test_short_meeting_one_request(self):
        asked = []
        notes, error = mn.summarize("[00:00:01] Hi", "en", lambda text, task: asked.append(task) or json.dumps(NOTES))
        self.assertEqual((notes["summary"], error, len(asked)), (NOTES["summary"], "", 1))
        self.assertIn("English", asked[0])

    def test_long_meeting_in_parts_then_merged(self):
        transcript = "\n".join(f"[00:{i // 60:02d}:{i % 60:02d}] line number {i} " + "x" * 80 for i in range(200))
        asked = []

        def ask(text, task):
            asked.append(task)
            return json.dumps(NOTES)
        notes, _ = mn.summarize(transcript, "ru", ask)
        self.assertGreater(len(asked), 2)
        self.assertIn("Merge", asked[-1])
        self.assertTrue(all(len(piece) <= mn.SUMMARY_CHUNK for piece in mn.split_transcript(transcript)))
        self.assertEqual(notes["decisions"], NOTES["decisions"])

    def test_when_merging_fails_nothing_is_lost(self):
        transcript = "\n".join(f"[00:00:{i:02d}] " + "y" * 100 for i in range(120))
        pieces = len(mn.split_transcript(transcript))
        self.assertGreater(pieces, 1)
        answers = iter([json.dumps(dict(NOTES, decisions=[f"D{i}"])) for i in range(pieces)] + ["not json"])
        notes, _ = mn.summarize(transcript, "en", lambda text, task: next(answers))
        self.assertEqual(notes["decisions"], [f"D{i}" for i in range(pieces)])

    def test_no_ai_answer(self):
        self.assertEqual(mn.summarize("[00:00:01] Hi", "en", lambda *_: None), (None, "no_answer"))
        self.assertEqual(mn.summarize("  ", "en", lambda *_: "{}"), (None, "empty"))

    def test_markdown_in_three_languages(self):
        started = dt.datetime(2026, 11, 27, 18, 30)
        for language, word in (("ru", "Задачи"), ("en", "Tasks"), ("ro", "Sarcini")):
            text = mn.notes_markdown(NOTES, "[00:00:01] Hi", language=language, started=started, seconds=3725,
                                     sources=["system", "mic"], made_by="local AI")
            self.assertIn(f"## {word}", text)
            self.assertIn("- [ ] Send the report (Ana · Friday)", text)
            self.assertIn("01:02:05", text)
        plain = mn.notes_markdown(None, "[00:00:01] Hi", language="ro", started=started, seconds=1, sources=["mic"])
        self.assertIn("Nu e conectat niciun AI", plain)
        self.assertNotIn("## Transcriere", mn.notes_markdown(NOTES, "x", language="ro", started=started, seconds=1,
                                                             sources=["mic"], include_transcript=False))


class RuntimeTests(TempCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, **settings):
        from luxai import extensions_runtime as runtime
        host = SimpleNamespace(cfg={"ui_language": "ro"}, tray_icon=None, online_planner=None, agent=None,
                               _queue_speech=lambda *a: None)
        engine = runtime.ExtensionsRuntime(host)
        engine.meetings_dir = self.folder / "tmp"
        engine._meeting_recovered = True
        self.notices = []
        engine._notify = lambda message, **_k: self.notices.append(message)
        self.addCleanup(lambda: (engine.stop(), engine.deleteLater(),
                                 QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)))
        defaults = {"sources": "system", "ai_source": "none", "folder": str(self.folder / "notes"), "open_after": False}
        engine.apply(catalog.normalize_state({"meeting_notes": {"enabled": True, "settings": dict(defaults, **settings)}}))
        return engine

    def fake_capture(self):
        class Capture:
            def __init__(self, on_audio, **_kwargs):
                self.on_audio, self.mode = on_audio, "fake"

            def start(self):
                self.on_audio(tone(2.0))
                return self

            def stop(self):
                pass
        return mock.patch("luxai.loopback_audio.LoopbackCapture", Capture)

    def wait(self, engine):
        for _ in range(400):
            QCoreApplication.processEvents()
            if not engine._meeting_busy:
                return
            time.sleep(0.01)
        self.fail("the notes were not written")

    def test_record_stop_and_notes_with_the_ai(self):
        engine = self.make(ai_source="cloud")
        planner = mock.Mock()
        planner.enabled.return_value = True
        planner.rewrite_text.return_value = json.dumps(NOTES)
        engine.host.online_planner = planner
        with self.fake_capture(), mock.patch.object(engine, "_meeting_model", return_value=lambda: FakeModel("Hello team.")):
            self.assertIn("Înregistrez", engine.start_meeting())
            self.assertTrue(engine.meeting_recording)
            self.assertIn("deja", engine.start_meeting())
            self.assertIsNotNone(engine._meeting_pill)
            engine.stop_meeting()
            self.wait(engine)
        files = list((self.folder / "notes").glob("*.md"))
        self.assertEqual(len(files), 1)
        text = files[0].read_text(encoding="utf-8")
        self.assertIn("We agreed on the budget.", text)
        self.assertIn("Hello team.", text)
        self.assertEqual(list((self.folder / "tmp").glob("*")), [])  # the working folder and the audio are gone
        self.assertIn("Rezumatul e gata", self.notices[-1])

    def test_keep_audio_moves_it_next_to_the_notes(self):
        engine = self.make(keep_audio=True)
        with self.fake_capture(), mock.patch.object(engine, "_meeting_model", return_value=lambda: FakeModel("Hi.")):
            engine.start_meeting()
            engine.stop_meeting()
            self.wait(engine)
        self.assertEqual(len(list((self.folder / "notes").glob("*.wav"))), 1)
        self.assertIn("fără AI", self.notices[-1])

    def test_no_speech_no_file(self):
        engine = self.make()
        with self.fake_capture(), mock.patch.object(engine, "_meeting_model", return_value=lambda: FakeModel("...")):
            engine.start_meeting()
            engine.stop_meeting()
            self.wait(engine)
        self.assertFalse((self.folder / "notes").exists() and list((self.folder / "notes").glob("*")))
        self.assertIn("Nu a fost vorbire", self.notices[-1])

    def test_a_capture_that_cannot_start_leaves_nothing_behind(self):
        engine = self.make()
        with mock.patch("luxai.loopback_audio.LoopbackCapture", side_effect=OSError("no device")):
            reply = engine.start_meeting()
        self.assertIn("OSError", reply)
        self.assertFalse(engine.meeting_recording)
        self.assertEqual(list((self.folder / "tmp").glob("*")), [])

    def test_closing_jarvis_keeps_the_recording_for_the_next_start(self):
        engine = self.make()
        with self.fake_capture(), mock.patch.object(engine, "_meeting_model", return_value=lambda: FakeModel("Hi.")):
            engine.start_meeting()
            engine._meeting_on_exit()
        left = list((self.folder / "tmp").glob("*"))
        self.assertEqual(len(left), 1)
        engine._meeting_recovered = False
        with mock.patch.object(engine, "_meeting_model", return_value=lambda: FakeModel("Recovered words.")):
            engine._recover_meetings()
            self.wait(engine)
        files = list((self.folder / "notes").glob("*.md"))
        self.assertEqual(len(files), 1)
        self.assertIn("Recovered words.", files[0].read_text(encoding="utf-8"))
        self.assertEqual(list((self.folder / "tmp").glob("*")), [])

    def test_voice_and_shortcut(self):
        engine = self.make()
        with mock.patch.object(engine, "start_meeting", return_value="started") as start, \
                mock.patch.object(engine, "stop_meeting", return_value="stopped") as stop:
            self.assertEqual(engine.handle_meeting_request("Джарвис, начни конспект"), "started")
            self.assertEqual(engine.handle_meeting_request("oprește rezumatul"), "stopped")
            self.assertEqual(engine.handle_meeting_request("start notes"), "started")
            self.assertIsNone(engine.handle_meeting_request("what notes do I have"))
        self.assertEqual(start.call_count, 2)
        stop.assert_called_once()
        self.assertIn({"id": "meeting_notes.hotkey", "enabled": True, "hotkey": "ctrl+alt+n"}, engine.hotkey_entries())

    def test_turned_off_it_does_not_record(self):
        engine = self.make()
        engine.state["meeting_notes"]["enabled"] = False
        self.assertIn("Pornește", engine.start_meeting())

    def test_the_island_shows_the_recording_with_pause_and_stop(self):
        engine = self.make()
        engine.state["status_island"] = {"enabled": True, "settings": {}}
        with mock.patch("luxai.status_island.IslandProbe"):
            engine._apply_island()
        with self.fake_capture(), mock.patch.object(engine, "_meeting_model", return_value=lambda: FakeModel("Hi.")):
            engine.start_meeting()
            engine._tick_island()
            self.assertEqual(engine._island.main.kind, "meeting")
            engine._on_island_action("meeting:pause")
            self.assertTrue(engine._meeting["paused"])
            engine.stop_meeting()
            self.wait(engine)


class PillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_buttons_and_painting(self):
        from luxai.ui_meeting import MeetingPill
        pill = MeetingPill("ro")
        self.addCleanup(pill.deleteLater)
        clicks = []
        pill.pause_clicked.connect(lambda: clicks.append("pause"))
        pill.stop_clicked.connect(lambda: clicks.append("stop"))
        for name in ("pause", "stop"):
            point = pill._buttons()[name].center()
            pill.mouseReleaseEvent(SimpleNamespace(button=lambda: __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.MouseButton.LeftButton,
                                                   position=lambda p=point: p))
        self.assertEqual(clicks, ["pause", "stop"])
        pill.set_state("01:02:03", True, 0.1)
        self.assertFalse(pill.grab().isNull())


class CatalogTests(unittest.TestCase):
    def test_ready_and_three_languages(self):
        plugin = catalog.PLUGIN_BY_ID["meeting_notes"]
        self.assertTrue(plugin.ready)
        values = [plugin.title, plugin.description, catalog.BASIC_NOTE["meeting_notes"]]
        for setting in plugin.settings:
            values += [setting.label] + [label for _v, label in setting.options] + [x for x in (setting.hint,) if x]
        values += [label for _id, label in plugin.actions]
        for value in values:
            self.assertEqual(set(value), {"ru", "en", "ro"})
            self.assertTrue(all(value[lang].strip() for lang in value))

    def test_the_folder_default_is_the_real_documents_folder(self):
        from luxai.runtime_meeting import documents_dir
        self.assertTrue(documents_dir().is_dir())


if __name__ == "__main__":
    unittest.main()
