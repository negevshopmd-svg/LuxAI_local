"""A multilingual request preserves its Discord operation and exact recipient."""
import unittest

from luxai.discord_call_visual import detect_discord_call_request
from luxai.discord_navigation import detect_discord_open_dm
from luxai.discord_headphones_visual import discord_headphones_mode


CALLS = {
    "ro": (
        "Sună-l pe Hanzo în Discord", "Suna pe Hanzo in Discord",
        "Apelează-l pe Hanzo în Discord", "Apeleaza utilizatorul Hanzo pe Discord",
        "Sună prietenul meu Hanzo în Discord", "Poți să-l suni pe Hanzo în Discord?",
        "Te rog, sună-l pe Hanzo în Discord", "Dă-i un telefon lui Hanzo în Discord",
        "Inițiază un apel cu Hanzo în Discord", "Jarvis, sună în Discord utilizatorului Hanzo",
    ),
    "ru": (
        "Позвони Hanzo в Discord", "Позвони пользователю Hanzo в Discord",
        "Набери Hanzo в Discord", "Позвони другу Hanzo в Discord",
        "Позвони моему другу Hanzo в Discord", "Жарвис, позвони Hanzo в Discord",
        "Пожалуйста позвони Hanzo в Discord", "Можешь позвонить Hanzo в Discord?",
        "В Discord позвони Hanzo", "Позвони в Discord пользователю Hanzo",
    ),
    "en": (
        "Call Hanzo on Discord", "Call user Hanzo in Discord", "Ring Hanzo on Discord",
        "Phone Hanzo on Discord", "Call my friend Hanzo on Discord",
        "Please call Hanzo on Discord", "Could you call Hanzo in Discord?",
        "Start a voice call with Hanzo on Discord", "In Discord call Hanzo",
        "Jarvis, call contact Hanzo on Discord please",
    ),
}

CONTACTS = {
    "ro": (
        "Deschide conversația cu Hanzo în Discord", "Deschide conversatia cu Hanzo in Discord",
        "Deschide chatul cu Hanzo pe Discord", "Găsește utilizatorul Hanzo în Discord",
        "Gaseste utilizatorul Hanzo in Discord", "Caută utilizatorul Hanzo pe Discord",
        "Apasă pe utilizatorul Hanzo în Discord", "Selectează utilizatorul Hanzo în Discord",
        "Poți să deschizi conversația cu Hanzo în Discord?", "Jarvis, intră pe utilizatorul Hanzo în Discord",
    ),
    "ru": (
        "Открой пользователя Hanzo в Discord", "Найди пользователя Hanzo в Discord",
        "Выбери пользователя Hanzo в Discord", "Нажми на пользователя Hanzo в Discord",
        "Жми на пользователя Hanzo в Discord", "Открой чат с Hanzo в Discord",
        "Перейди на пользователя Hanzo в Discord", "Нажми в Discord на пользователя Hanzo",
        "Жарвис, открой пользователя Hanzo в Discord", "Можешь открыть пользователя Hanzo в Discord?",
    ),
    "en": (
        "Open user Hanzo in Discord", "Find user Hanzo on Discord", "Select user Hanzo in Discord",
        "Click on user Hanzo in Discord", "Open the chat with Hanzo on Discord",
        "Open the conversation with Hanzo in Discord", "Open direct messages with Hanzo in Discord",
        "Could you open user Hanzo in Discord?", "In Discord open contact Hanzo",
        "Jarvis, open the DM with Hanzo in Discord please",
    ),
}

HEADPHONES_OFF = {
    "ro": (
        "Oprește căștile în Discord", "Opreste castile in Discord", "Închide căștile în Discord",
        "Inchide castile in Discord", "Dezactivează căștile în Discord",
        "Dezactiveaza castile in Discord", "Pune căștile pe mute în Discord",
        "Poți să oprești căștile în Discord?", "Te rog, închide căștile în Discord",
        "Apasă pe căștile din Discord ca să le oprești",
    ),
    "ru": (
        "Выключи наушники в Discord", "Отключи наушники в Discord", "Заглуши наушники в Discord",
        "Замуть наушники в Discord", "Жарвис, выключи наушники в Discord",
        "Пожалуйста отключи наушники в Discord", "Можешь выключить наушники в Discord?",
        "Ты можешь отключить наушники в Discord?", "Выключи наушники в дискорде пожалуйста",
        "Нажми на наушники в Discord чтобы их выключить",
    ),
    "en": (
        "Deafen in Discord", "Mute headphones in Discord", "Turn off headphones in Discord",
        "Disable headphones in Discord", "Mute my Discord headset", "Please deafen in Discord",
        "Could you mute headphones in Discord?", "Can you turn off my Discord headphones?",
        "Jarvis, mute headphones on Discord", "Click the headphones in Discord to mute",
    ),
}

HEADPHONES_ON = {
    "ro": (
        "Pornește căștile în Discord", "Porneste castile in Discord", "Deschide căștile în Discord",
        "Deschide castile in Discord", "Activează căștile în Discord", "Activeaza castile in Discord",
        "Scoate căștile de pe mute în Discord", "Poți să pornești căștile în Discord?",
        "Te rog, deschide căștile în Discord", "Apasă pe căștile din Discord ca să le pornești",
    ),
    "ru": (
        "Включи наушники в Discord", "Разглуши наушники в Discord", "Размуть наушники в Discord",
        "Включить наушники в Discord", "Жарвис, включи наушники в Discord",
        "Пожалуйста включи наушники в Discord", "Можешь включить наушники в Discord?",
        "Ты можешь включить наушники в Discord?", "Включи наушники в дискорде пожалуйста",
        "Нажми на наушники в Discord чтобы их включить",
    ),
    "en": (
        "Undeafen in Discord", "Unmute headphones in Discord", "Turn on headphones in Discord",
        "Enable headphones in Discord", "Unmute my Discord headset", "Please undeafen in Discord",
        "Could you unmute headphones in Discord?", "Can you turn on my Discord headphones?",
        "Jarvis, unmute headphones on Discord", "Click the headphones in Discord to unmute",
    ),
}


class MultilingualDiscordContactTests(unittest.TestCase):
    def test_ten_call_formulations_per_language_preserve_exact_recipient(self):
        for language, phrases in CALLS.items():
            self.assertEqual(len(phrases), 10)
            for phrase in phrases:
                with self.subTest(language=language, phrase=phrase):
                    self.assertEqual(detect_discord_call_request(phrase), "Hanzo")
                    self.assertIsNone(detect_discord_open_dm(phrase), "Calling must not degrade into merely opening a DM")

    def test_ten_contact_formulations_per_language_preserve_exact_recipient(self):
        for language, phrases in CONTACTS.items():
            self.assertEqual(len(phrases), 10)
            for phrase in phrases:
                with self.subTest(language=language, phrase=phrase):
                    self.assertEqual(detect_discord_open_dm(phrase), "Hanzo")
                    self.assertIsNone(detect_discord_call_request(phrase), "Opening a DM cannot place a call")

    def test_ten_headphone_enable_and_disable_formulations_per_language(self):
        for expected, corpus in (("off", HEADPHONES_OFF), ("on", HEADPHONES_ON)):
            for language, phrases in corpus.items():
                self.assertEqual(len(phrases), 10)
                for phrase in phrases:
                    with self.subTest(language=language, phrase=phrase):
                        self.assertEqual(discord_headphones_mode(phrase), expected)

    def test_literal_messages_negations_questions_and_multiple_people_never_call_or_open_dm(self):
        for phrase in (
            "Nu suna pe Hanzo în Discord", "Do not call Hanzo on Discord", "Never call Hanzo on Discord",
            "Не надо звонить Hanzo в Discord", "Nu deschide utilizatorul Hanzo în Discord",
            "Don't open user Hanzo in Discord", "Не нажимай на пользователя Hanzo в Discord",
            "Cum pot suna pe Hanzo în Discord?", "How do I call Hanzo in Discord?",
            "Как позвонить Hanzo в Discord?", "How to open user Hanzo in Discord?",
            "Scrie-i lui Hanzo în Discord «sună-l pe Hanzo»",
            "Write Hanzo on Discord 'call Hanzo'", "Напиши Hanzo в Discord «позвони Hanzo»",
            "Call Hanzo and Alice on Discord", "Sună Hanzo și Alice în Discord",
            "Open user Hanzo in Discord and type hello", "Deschide utilizatorul Hanzo în Discord și scrie salut",
            "Call Hanzo on Discordant", "Open user Hanzo in NotDiscord",
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(detect_discord_call_request(phrase))
                self.assertIsNone(detect_discord_open_dm(phrase))
        for phrase in (
            "Nu opri căștile în Discord", "Nu scoți căștile de pe mute în Discord",
            "Explică-mi cum opresc căștile în Discord", "How to mute headphones in Discord?",
            "Scrie-i lui Hanzo în Discord «oprește căștile»", "Send Hanzo on Discord 'unmute headphones'",
            "Nu apăsa pe căștile în Discord", "Unmute microphone and headphones in Discord",
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(discord_headphones_mode(phrase))


if __name__ == "__main__":
    unittest.main()
