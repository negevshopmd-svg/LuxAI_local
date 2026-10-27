"""The home avatar follows real audio activity and stays smooth across timer rates."""
import threading
import unittest
from unittest import mock

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from luxai.ui_home import OrbVisual


class AvatarAnimation038bTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_orb(self):
        orb = OrbVisual()
        orb.resize(440, 720)
        orb.show()
        self.app.processEvents()
        orb.set_animated(True)
        # Drive exact frame times below; do not race the real event loop timer.
        orb._timer.stop()
        self.addCleanup(orb.close)
        return orb

    def advance(self, orb, duration, steps):
        start = 100.0 if orb._last_frame is None else orb._last_frame
        orb._last_frame = start
        for frame in range(1, steps + 1):
            with mock.patch("luxai.ui_home.time.monotonic", return_value=start + duration * frame / steps):
                orb._advance()

    def test_frame_rate_does_not_change_motion_or_audio_attack(self):
        fast, slow = self.make_orb(), self.make_orb()
        for orb in (fast, slow):
            orb._last_frame = None
            orb.set_listening(True)
            orb.set_audio_level(0.8)
        self.advance(fast, 0.5, 30)
        self.advance(slow, 0.5, 10)
        self.assertAlmostEqual(fast._phase, slow._phase, places=10)
        self.assertAlmostEqual(fast._level, slow._level, places=10)
        self.assertAlmostEqual(fast._listen_mix, slow._listen_mix, places=10)
        self.assertGreater(fast._level, 0.75)
        self.assertLessEqual(fast._timer.interval(), 17)

    def test_mic_level_and_output_playback_produce_distinct_rendered_feedback(self):
        quiet, loud, speaking = (self.make_orb() for _ in range(3))
        playing = threading.Event()
        playing.set()
        speaking.set_playback_probe(playing.is_set)
        for orb in (quiet, loud, speaking):
            orb._last_frame = None
            orb.set_listening(True)
        loud.set_audio_level(1.0)
        # Assistant output may also reach the microphone. Playback wins.
        speaking.set_audio_level(1.0)
        for orb in (quiet, loud, speaking):
            self.advance(orb, 0.4, 24)
        quiet_image, loud_image, speaking_image = (orb.grab().toImage() for orb in (quiet, loud, speaking))
        self.assertNotEqual(quiet_image, loud_image)
        self.assertNotEqual(loud_image, speaking_image)
        self.assertGreater(loud._level, 0.99)
        self.assertEqual(speaking._level, 0.0)
        self.assertGreater(speaking._speak_mix, 0.9)
        playing.clear()
        speaking.set_listening(False)
        self.advance(speaking, 1.0, 60)
        self.assertFalse(speaking._speaking)
        self.assertLess(speaking._speak_mix, 0.04)
        self.assertEqual(speaking._audio_level, 0.0)

    def test_hidden_or_disabled_avatar_stops_and_resumes_without_polling_playback(self):
        orb = self.make_orb()
        probe = mock.Mock(return_value=True)
        orb.set_playback_probe(probe)
        orb.set_animated(False)
        probe.reset_mock()
        phase = orb._phase
        orb.set_listening(True)
        orb.set_audio_level(0.9)
        disabled_image = orb.grab().toImage()
        QTest.qWait(40)
        self.assertFalse(orb._timer.isActive())
        self.assertEqual(orb._phase, phase)
        self.assertEqual(disabled_image, orb.grab().toImage())
        probe.assert_not_called()
        orb.hide()
        orb.set_animated(True)
        QTest.qWait(30)
        probe.assert_not_called()
        self.assertFalse(orb._timer.isActive())
        orb.show()
        self.assertTrue(orb._timer.isActive())
        self.assertTrue(orb._speaking)
        probe.assert_called_once_with()
        QTest.qWait(50)
        self.assertGreater(orb._phase, phase)
        self.assertLess(orb._phase - phase, 0.2)
        orb.hide()
        probe.reset_mock()
        phase = orb._phase
        QTest.qWait(40)
        self.assertFalse(orb._timer.isActive())
        self.assertEqual(orb._phase, phase)
        probe.assert_not_called()

    def test_playback_ending_while_hidden_does_not_reappear_when_home_reopens(self):
        orb = self.make_orb()
        playing = threading.Event()
        playing.set()
        orb.set_playback_probe(playing.is_set)
        self.advance(orb, 0.4, 24)
        self.assertGreater(orb._speak_mix, 0.9)
        orb.hide()
        playing.clear()
        orb.show()
        self.assertFalse(orb._speaking)
        self.assertEqual(orb._speak_mix, 0.0)

    def test_theme_change_while_speaking_preserves_motion_and_changes_visible_colors(self):
        orb = self.make_orb()
        orb.set_speaking(True)
        self.advance(orb, 0.2, 12)
        phase = orb._phase
        orb.set_theme("dark", "#873eff", "#182d27")
        purple = orb.grab().toImage()
        orb.set_theme("light", "#1bbf8b", "#eef8e8")
        self.assertNotEqual(purple, orb.grab().toImage())
        self.assertEqual(orb._phase, phase)
        self.assertTrue(orb._speaking)
        self.assertEqual(orb._background, "#eef8e8")

    def test_invalid_audio_values_do_not_poison_animation(self):
        orb = self.make_orb()
        orb.set_listening(True)
        for value, expected in ((float("nan"), 0.0), (float("inf"), 0.0),
                                (None, 0.0), ("bad", 0.0), (-0.5, 0.0), (2.0, 1.0)):
            with self.subTest(value=value):
                orb.set_audio_level(value)
                self.assertEqual(orb._audio_level, expected)
        orb.set_listening(False)
        self.assertEqual(orb._audio_level, 0.0)


if __name__ == "__main__":
    unittest.main()
