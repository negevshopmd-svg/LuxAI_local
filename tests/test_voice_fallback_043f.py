"""0.4.3f: when Fish Audio refuses (key, credit) or is unreachable, the local voice speaks instead."""
from __future__ import annotations

import unittest
from unittest import mock

from luxai import fish_tts, voices


class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.manager = voices.VoiceManager()
        self.manager._fish_pause = None
        patcher = mock.patch.object(self.manager, "_load_config", return_value={"voice_engine": "fish", "language": "ru"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.key = "key-1"
        for target, value in ((self.manager, "_log"), (self.manager, "_windows_speak"), (self.manager, "_select_model")):
            patcher = mock.patch.object(target, value)
            self.mocks = getattr(self, "mocks", {})
            self.mocks[value] = patcher.start()
            self.addCleanup(patcher.stop)
        self.mocks["_select_model"].return_value = None   # no Piper file in the test: Windows voice is «local»
        self.mocks["_windows_speak"].return_value = True
        patcher = mock.patch("luxai.secure_keys.get_api_key", side_effect=lambda name: self.key)
        patcher.start()
        self.addCleanup(patcher.stop)
        while voices.take_voice_notice():
            pass
        voices._voice_notice_shown.clear()

    def speak(self):
        return self.manager._speak("Проверка.", "ru", voices._cancel_token())

    def test_rejected_key_falls_back_to_the_local_voice_and_says_why_once(self):
        with mock.patch.object(fish_tts, "synthesize", side_effect=fish_tts.FishTTSError("auth")) as fish:
            self.assertTrue(self.speak())
            self.assertTrue(self.speak())
        self.assertEqual(fish.call_count, 1)  # the refused key is not tried again
        self.assertEqual(self.mocks["_windows_speak"].call_count, 2)
        self.assertEqual(voices.take_voice_notice(), "fish_auth")
        self.assertEqual(voices.take_voice_notice(), "")

    def test_a_new_key_is_tried_at_once(self):
        with mock.patch.object(fish_tts, "synthesize", side_effect=fish_tts.FishTTSError("auth")) as fish:
            self.speak()
            self.key = "key-2"
            self.speak()
        self.assertEqual(fish.call_count, 2)

    def test_network_trouble_pauses_fish_only_for_a_while(self):
        with mock.patch.object(fish_tts, "synthesize", side_effect=fish_tts.FishTTSError("unavailable")):
            self.speak()
        fingerprint, until = self.manager._fish_pause
        self.assertIsNotNone(until)
        self.manager._fish_pause = (fingerprint, 0.0)  # the pause is over
        self.assertTrue(self.manager._fish_usable())

    def test_a_piece_already_partly_heard_is_not_repeated(self):
        def partial(*_args, on_chunk=None, **_kwargs):
            on_chunk(b"\0\0" * 100)
            raise fish_tts.FishTTSError("timeout")

        with mock.patch.object(voices, "_PCMStreamPlayer") as player, \
                mock.patch.object(fish_tts, "synthesize", side_effect=partial):
            player.return_value.received = 0

            def feed(chunk):
                player.return_value.received += len(chunk)
            player.return_value.feed.side_effect = feed
            self.assertFalse(self.speak())
        self.mocks["_windows_speak"].assert_not_called()

    def test_missing_key_uses_the_local_voice(self):
        self.key = ""
        self.assertTrue(self.speak())
        self.assertEqual(voices.take_voice_notice(), "fish_missing")

    def test_prefetch_does_not_spend_requests_on_a_refused_key(self):
        with mock.patch.object(fish_tts, "synthesize", side_effect=fish_tts.FishTTSError("auth")):
            self.speak()
        with mock.patch("luxai.voices.threading.Thread") as thread:
            self.manager.prefetch("Следующий кусок.", "ru")
        thread.assert_not_called()


if __name__ == "__main__":
    unittest.main()
