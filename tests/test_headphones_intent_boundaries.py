"""Headphone enable requests must never become the opposite operation."""
import unittest

from luxai.discord_headphones_visual import discord_headphones_mode


class HeadphonesIntentBoundaryTests(unittest.TestCase):
    def test_enable_words_do_not_match_disable_substrings(self):
        for phrase in (
            "Undeafen in Discord", "Unmute headphones in Discord",
            "Please turn on headphones in Discord", "Включи наушники в Discord",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(discord_headphones_mode(phrase), "on")

    def test_disable_and_explicit_toggle_requests_still_work(self):
        for phrase in (
            "Deafen in Discord", "Mute headphones in Discord",
            "Turn off headphones in Discord", "Выключи наушники в дискорде",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(discord_headphones_mode(phrase), "off")
        self.assertEqual(discord_headphones_mode("Click headphones in Discord"), "toggle")

    def test_prohibitions_and_instructions_are_not_direct_actions(self):
        for phrase in (
            "Don't mute headphones in Discord", "Do not undeafen in Discord",
            "Never click headphones in Discord", "How do I unmute headphones in Discord?",
            "How to deafen in Discord?", "Не выключай наушники в Discord",
            "Не надо включать наушники в Discord", "Как выключить наушники в Discord?",
            "Unmute headphones in Discordant", "Unmute microphone in Discord",
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(discord_headphones_mode(phrase))


if __name__ == "__main__":
    unittest.main()
