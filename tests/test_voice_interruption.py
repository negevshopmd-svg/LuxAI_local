"""Speech endpoint and interruption tests."""
import sys
import types
import unittest
from unittest import mock

from luxai.voice_rules import is_hallucinated_outro, is_stop_speech_command, speech_pause_seconds
from luxai import voices


class SpeechRuleTests(unittest.TestCase):
    def test_outros_are_not_commands(self):
        for phrase in ("Спасибо за внимание!", "Спасибо за просмотр.",
                       "Thanks for watching!", "Mulțumesc pentru vizionare."):
            self.assertTrue(is_hallucinated_outro(phrase), phrase)
        self.assertFalse(is_hallucinated_outro("Открой Telegram"))

    def test_spoken_stop_across_languages(self):
        for phrase in ("Стоп!", "Stop.", "Замолчи", "oprește-te", "taci"):
            self.assertTrue(is_stop_speech_command(phrase), phrase)
        self.assertFalse(is_stop_speech_command("Пожалуйста, останови игру"))

    def test_configurable_speech_pause(self):
        self.assertEqual(speech_pause_seconds(None), 2.3)
        self.assertEqual(speech_pause_seconds(3.4), 3.4)
        self.assertEqual(speech_pause_seconds("99"), 2.3)

    def test_stop_requests_sounddevice_stop(self):
        audio = types.SimpleNamespace(stop=mock.Mock())
        token = voices._cancel_token()
        with mock.patch.dict(sys.modules, {"sounddevice": audio}):
            voices.stop_speaking()
        self.assertTrue(voices._was_cancelled(token))
        audio.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
