"""Fast-response tests: no GGUF or online API should be used for these phrases."""
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault(
    "luxai.screen",
    types.SimpleNamespace(capture_screen=lambda: None, read_screen_text=lambda *a, **k: ""),
)

from luxai.agent import LocalAgent
from luxai.fast_intents import strip_wake_name, quick_reply, has_launch_verb


class FastIntentsTests(unittest.TestCase):
    def setUp(self):
        self.agent = LocalAgent({
            "language": "ru",
            "wake_prefix": "Jarvis, Джарвис, Жарвис",
        })

    def test_thanks_do_not_load_llm(self):
        phrases = [
            "Спасибо.", "Спасибо большое!", "Огромное спасибо",
            "Благодарю!", "Жарвис, спасибо.",
        ]
        with mock.patch.object(self.agent, "_load_llm") as load:
            for text in phrases:
                self.assertEqual(self.agent.handle_fast(text), "Пожалуйста.")
            load.assert_not_called()

    def test_greetings_work_with_or_without_wake_word(self):
        for spoken in ("Привет", "Жарвис, привет", "Jarvis! Привет.", "Джарвис: здравствуй"):
            self.assertEqual(self.agent.handle_fast(spoken), "Привет. Слушаю.")

    def test_yes_ack_without_active_confirmation(self):
        self.assertEqual(self.agent.handle_fast("Окей!"), "Хорошо.")

    def test_presence_check(self):
        self.assertEqual(self.agent.handle_fast("Жарвис, ты тут?"), "Да, я здесь. Слушаю.")

    def test_open_telegram_with_infinitive(self):
        phrases = [
            "Можешь открыть Telegram.",
            "Можешь открыть телеграм?",
            "Жарвис, можешь открыть телеграмм?",
            "Открой телегу.",
        ]
        with mock.patch.object(self.agent, "_open_application", return_value=True) as open_app:
            for phrase in phrases:
                response = self.agent.handle_fast(phrase, confirm_callback=lambda _: True)
                self.assertIn("Передал Windows запрос на запуск Telegram", response)
        self.assertEqual(open_app.call_count, len(phrases))

    def test_actions_still_require_confirmation(self):
        with mock.patch.object(self.agent, "_open_application") as open_app:
            response = self.agent.handle_fast("Можешь открыть телеграм?", lambda _: False)
            self.assertEqual(response, "Действие отменено.")
            open_app.assert_not_called()

    def test_no_shell_matching_for_unrelated_phrase(self):
        self.assertFalse(has_launch_verb("Telegram уже открыт"))
        self.assertIsNone(self.agent.handle_fast("Объясни мне, что такое телеграм"))

    def test_wake_strip_matches_whisper_variants(self):
        for name in ("жарвис", "джарвис", "jarvis", "Жервис"):
            self.assertEqual(strip_wake_name(f"{name}, спасибо!"), "спасибо!")

    def test_fast_conversation_ru_en_ro(self):
        cases = [
            ({"language": "ru"}, "Спасибо", "Пожалуйста."),
            ({"language": "en"}, "Thank you", "You're welcome."),
            ({"language": "ro"}, "Mulțumesc", "Cu plăcere."),
        ]
        for config, text, expected in cases:
            self.assertEqual(LocalAgent(config).handle_fast(text), expected)


if __name__ == "__main__":
    unittest.main()
