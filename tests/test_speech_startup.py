"""Startup prepares speech before the first reply without playing a greeting."""
import queue
import unittest
from types import SimpleNamespace
from unittest import mock


class SpeechStartupTests(unittest.TestCase):
    def worker(self, enabled=True):
        tasks = queue.Queue()
        tasks.put(("First reply", "ru", 0))
        tasks.put(None)
        return SimpleNamespace(
            cfg={"tts_enabled": enabled, "response_language": "ru"},
            _speech_queue=tasks, _speech_generation=0, _closed=False,
            tts_played=mock.Mock(),
        )

    def test_first_reply_uses_voice_prepared_before_playback(self):
        import main
        worker = self.worker()
        calls = []
        with (
            mock.patch.object(main, "warm_up_voice", side_effect=lambda cfg: calls.append(("prepare", cfg))),
            mock.patch.object(main, "speak", side_effect=lambda *a, **k: calls.append(("reply", a[0])) or True),
        ):
            main.MainWindow._speech_loop(worker)
        self.assertEqual(calls, [("prepare", worker.cfg), ("reply", "First reply")])
        worker.tts_played.emit.assert_called_once_with(True, 0)

    def test_quiet_startup_never_loads_or_downloads_voice(self):
        import main
        worker = self.worker(False)
        worker._speech_queue = queue.Queue()
        worker._speech_queue.put(None)
        with mock.patch.object(main, "warm_up_voice") as prepare, mock.patch.object(main, "speak") as speak:
            main.MainWindow._speech_loop(worker)
        prepare.assert_not_called()
        speak.assert_not_called()

    def test_stop_during_preparation_does_not_play_stale_reply(self):
        import main
        worker = self.worker()
        def prepare(_):
            worker._speech_generation += 1
        with mock.patch.object(main, "warm_up_voice", side_effect=prepare), mock.patch.object(main, "speak") as speak:
            main.MainWindow._speech_loop(worker)
        speak.assert_not_called()
        worker.tts_played.emit.assert_not_called()

    def test_failed_preparation_keeps_normal_playback_fallback(self):
        import main
        worker = self.worker()
        with (
            mock.patch.object(main, "warm_up_voice", side_effect=RuntimeError("Unavailable voice")),
            mock.patch.object(main, "speak", return_value=True) as speak,
        ):
            main.MainWindow._speech_loop(worker)
        speak.assert_called_once_with("First reply", enabled=True, language="ru")


if __name__ == "__main__":
    unittest.main()
