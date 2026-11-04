"""Control phrases retain exact intent and held-key capture fails closed."""
import unittest
from unittest import mock

from luxai.listening_controls import (
    capture_allowed, mode_control, normalize_control_phrase, normalize_listen_hotkey,
)


class ListeningControls039gTests(unittest.TestCase):
    def test_default_controls_accept_punctuation_case_and_optional_wake_name(self):
        for phrase, expected in (
            ("Стоп!", "stop"), ("Jarvis, STOP.", "stop"),
            ("Джарвис, перейди в режим префикса!", "prefix"),
            ("перейди в тихий режим", "quiet"),
            ("выключи микрофон.", "microphone_off"),
            ("oprește", "stop"),
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(mode_control(phrase, {}), expected)
        self.assertEqual(normalize_control_phrase("OPREŞTE!"), "oprește")

    def test_controls_never_match_substrings_or_negations(self):
        for phrase in ("не выключи микрофон", "stop the game", "don't stop", "потом стоп",
                       "перейди в тихий режим и открой файл", "Jarvis please stop"):
            self.assertIsNone(mode_control(phrase, {}), phrase)

    def test_custom_phrases_wake_name_and_explicitly_disabled_defaults(self):
        config = {"wake_prefix": "Lux, помощник", "quiet_mode_phrases": "fără voce, be silent",
                  "command_stop_phrases": "", "microphone_off_phrases": ""}
        self.assertEqual(mode_control("Lux, fără voce!", config), "quiet")
        self.assertEqual(mode_control("Помощник, BE SILENT.", config), "quiet")
        self.assertIsNone(mode_control("stop", config))
        self.assertIsNone(mode_control("выключи микрофон", config))
        self.assertIsNone(mode_control("перейди в тихий режим", config))

    def test_duplicate_phrase_prioritizes_stopping_the_chain(self):
        self.assertEqual(mode_control("pause", {"command_stop_phrases": "pause",
                                                "quiet_mode_phrases": "pause"}), "stop")

    def test_hotkey_validation_canonicalizes_modifiers_and_supports_space(self):
        self.assertEqual(normalize_listen_hotkey("Shift + Control + SPACE"), "ctrl+shift+space")
        self.assertEqual(normalize_listen_hotkey("F8"), "f8")
        self.assertEqual(normalize_listen_hotkey("meta + z"), "win+z")
        for value in (None, "", "ctrl", "ctrl++space", "ctrl+ctrl+space", "f13", "ctrl+space+x", "enter"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_listen_hotkey(value)

    def test_always_mode_does_not_read_keys(self):
        reader = mock.Mock(side_effect=AssertionError("unnecessary keyboard access"))
        self.assertTrue(capture_allowed({}, key_reader=reader))
        self.assertTrue(capture_allowed({"listen_mode": "always"}, key_reader=reader))
        reader.assert_not_called()

    def test_hold_mode_requires_all_configured_keys(self):
        held = {0x11, 0x20}
        config = {"listen_mode": "hold"}
        self.assertTrue(capture_allowed(config, key_reader=held.__contains__))
        held.remove(0x20)
        self.assertFalse(capture_allowed(config, key_reader=held.__contains__))
        held = {0x12, 0x77}
        self.assertTrue(capture_allowed({"listen_mode": "hold", "listen_hotkey": "alt+f8"}, key_reader=held.__contains__))
        self.assertFalse(capture_allowed({"listen_mode": "hold", "listen_hotkey": "alt+f9"}, key_reader=held.__contains__))

    def test_right_windows_key_and_letter_can_hold_gate_open(self):
        self.assertTrue(capture_allowed({"listen_mode": "hold", "listen_hotkey": "win+a"},
                                        key_reader={0x5C, ord("A")}.__contains__))

    def test_invalid_or_unavailable_key_reader_closes_gate(self):
        self.assertFalse(capture_allowed({"listen_mode": "hold", "listen_hotkey": "ctrl+unknown"},
                                         key_reader=lambda code: True))
        self.assertFalse(capture_allowed({"listen_mode": "hold"}, key_reader=mock.Mock(side_effect=OSError("No keyboard"))))
        with mock.patch("luxai.listening_controls.sys.platform", "linux"):
            self.assertFalse(capture_allowed({"listen_mode": "hold"}))


if __name__ == "__main__":
    unittest.main()
