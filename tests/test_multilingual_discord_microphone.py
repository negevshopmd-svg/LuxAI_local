"""Equivalent RU/RO/EN requests choose the same verified voice tools."""
import unittest

from luxai.voice_desktop import (
    discord_mic_visual_mode, wants_discord_mic_mute, wants_discord_mic_visual_click,
    is_dictation_start, is_dictation_stop, dictation_text, wants_screen_read,
)


MUTE = {
    "ro": (
        "Oprește microfonul în Discord", "Opreste microfonul in Discord",
        "Închide microfonul din Discord", "Inchide microfonul Discord",
        "Dezactivează microfonul în Discord", "Dezactiveaza microfonul in Discord",
        "Jarvis, poți să oprești microfonul în Discord?",
        "Te rog frumos, închide microfonul în Discord",
        "Pune microfonul pe mute în Discord", "Dă mute microfonului din Discord",
        "Apasă pe butonul microfonului în Discord ca să-l oprești",
        "Apasă pictograma microfonului în Discord pentru a-l dezactiva",
    ),
    "ru": (
        "Выключи микрофон в Discord", "Отключи микрофон в дискорде",
        "Закрой микрофон в Discord", "Заглуши микрофон в Discord",
        "Замуть микрофон в Discord", "Замьют микрофон в Discord",
        "Жарвис, пожалуйста, выключи микрофон Discord",
        "Можешь выключить микрофон в Discord?",
        "Выключу микрофон в Discord", "Нажми на микрофон в Discord чтобы его выключить",
        "Нажми кнопку микрофона Discord чтобы его отключить",
        "Кликни по значку микрофона в Discord чтобы его заглушить",
    ),
    "en": (
        "Mute microphone in Discord", "Mute my microphone in Discord",
        "Disable the microphone in Discord", "Turn off my Discord microphone",
        "Jarvis, mute my mic on Discord", "Please mute the Discord mic",
        "Could you mute my microphone in Discord?", "Can you disable my Discord microphone?",
        "Turn off the mic in Discord please", "Press the microphone button in Discord to mute",
        "Click the Discord microphone icon to disable it", "Tap my Discord microphone to turn off",
    ),
}

UNMUTE = {
    "ro": (
        "Pornește microfonul în Discord", "Porneste microfonul in Discord",
        "Deschide microfonul din Discord", "Activează microfonul în Discord",
        "Activeaza microfonul in Discord", "Jarvis, poți să pornești microfonul în Discord?",
        "Te rog, deschide microfonul Discord", "Poti activa microfonul in Discord?",
        "Scoate microfonul de pe mute în Discord", "Scoți microfonul din mute în Discord?",
        "Apasă pe butonul microfonului din Discord ca să-l pornești",
        "Apasă pictograma microfonului din Discord pentru a-l activa",
    ),
    "ru": (
        "Включи микрофон в Discord", "Размуть микрофон в Discord",
        "Размьют микрофон в Discord", "Включить микрофон в дискорде",
        "Жарвис, включи микрофон в Discord", "Пожалуйста включи микрофон Discord",
        "Можешь включить микрофон в Discord?", "Ты можешь включить микрофон в Discord?",
        "Включи мой микрофон в Discord пожалуйста",
        "Нажми на микрофон в Discord чтобы его включить",
        "Нажми кнопку микрофона в Discord чтобы его активировать",
        "Кликни по значку микрофона в Discord чтобы его размутить",
    ),
    "en": (
        "Unmute microphone in Discord", "Unmute my microphone in Discord",
        "Enable the microphone in Discord", "Turn on my Discord microphone",
        "Jarvis, unmute my mic on Discord", "Please unmute the Discord mic",
        "Could you unmute my microphone in Discord?", "Can you enable my Discord microphone?",
        "Turn on the mic in Discord please", "Press the microphone button in Discord to unmute",
        "Click the Discord microphone icon to enable it", "Tap my Discord microphone to turn on",
    ),
}

SCREEN = {
    "ro": (
        "Citește ecranul", "Citeste ecranul", "Citește textul de pe ecran",
        "Ce scrie pe ecran?", "Ce apare pe ecran?", "Ce vezi pe ecran?",
        "Spune-mi ce scrie pe ecran", "Analizează ecranul", "Privește ecranul",
        "Jarvis, poți să citești ce scrie pe ecran?",
    ),
    "ru": (
        "Прочитай экран", "Прочти текст на экране", "Посмотри на мой экран",
        "Что у меня на экране?", "Что видно на экране?", "Какой текст на экране?",
        "Покажи текст на экране", "Видишь мой экран?", "Жарвис, прочитай экран",
        "Можешь прочитать текст на экране?",
    ),
    "en": (
        "Read my screen", "Read the screen", "Read text on the screen",
        "Read the text from my screen", "What's on my screen?",
        "What is on the screen?", "Tell me what is on the screen",
        "Look at my screen", "Inspect the screen", "Could you analyze my screen?",
    ),
}

DICTATION = {
    "ro": (
        "Pornește dictarea", "Porneste dictarea", "Începe dictarea", "Incepe dictarea",
        "Activează dictarea", "Activeaza dictarea", "Începe modul de dictare",
        "Pornește scrierea vocală", "Scrie tot ce îți spun", "Te rog, pornește dictarea",
    ),
    "ru": (
        "Начни диктовку", "Включи диктовку", "Запусти диктовку", "Начни голосовую диктовку",
        "Я буду диктовать", "Я могу тебе диктовать", "Начни писать", "Записывай что я говорю",
        "Запиши всё что я диктую", "Жарвис, пожалуйста включи диктовку",
    ),
    "en": (
        "Start dictation", "Begin dictation", "Enable dictation", "Turn on dictation",
        "Start voice dictation", "Begin taking dictation", "Enable the dictation mode",
        "Start voice typing", "Could you start dictation?", "Jarvis, begin dictation please",
    ),
}


class MultilingualVoiceToolsTests(unittest.TestCase):
    def test_twelve_mute_and_unmute_formulations_per_language_use_verified_state(self):
        for expected, corpus in (("mute", MUTE), ("unmute", UNMUTE)):
            for language, phrases in corpus.items():
                self.assertEqual(len(phrases), 12)
                for phrase in phrases:
                    with self.subTest(language=language, phrase=phrase):
                        self.assertEqual(discord_mic_visual_mode(phrase), expected)
                        self.assertTrue(wants_discord_mic_visual_click(phrase))
                        self.assertFalse(wants_discord_mic_mute(phrase), "A state request cannot fall back to a blind toggle")

    def test_ten_equivalent_screen_reads_per_language(self):
        for language, phrases in SCREEN.items():
            self.assertEqual(len(phrases), 10)
            for phrase in phrases:
                with self.subTest(language=language, phrase=phrase):
                    self.assertTrue(wants_screen_read(phrase))

    def test_ten_equivalent_dictation_starts_per_language(self):
        for language, phrases in DICTATION.items():
            self.assertEqual(len(phrases), 10)
            for phrase in phrases:
                with self.subTest(language=language, phrase=phrase):
                    self.assertTrue(is_dictation_start(phrase))

    def test_dictation_stop_and_punctuation_preserve_language_and_literal_chunks(self):
        for phrase in (
            "Стоп", "Жарвис, останови диктовку", "Закончи диктовку", "Выключи диктовку",
            "Oprește dictarea", "Incheie dictarea", "Termină dictarea", "Dezactiveaza dictarea",
            "Stop dictation", "End dictation", "Finish dictation", "Stop voice typing",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(is_dictation_stop(phrase))
        for expected, phrases in (
            ("\n", ("новая строка", "linie nouă", "rand nou", "new line", "line break")),
            (".", ("точка", "punct", "period", "full stop")),
            (",", ("запятая", "virgulă", "virgula", "comma")),
            ("?", ("вопросительный знак", "semnul întrebării", "question mark")),
        ):
            for phrase in phrases:
                self.assertEqual(dictation_text(phrase), expected)
        self.assertEqual(dictation_text("Te rog, acesta este textul meu"), "Te rog, acesta este textul meu ")

    def test_explanations_prohibitions_and_messages_never_change_microphone_or_mode(self):
        for phrase in (
            "Nu opri microfonul în Discord", "Nu-mi închide microfonul în Discord",
            "Nu scoate microfonul de pe mute în Discord", "Nu apăsa pe microfon în Discord",
            "Nu vreau să oprești microfonul în Discord", "Cum pot opri microfonul în Discord?",
            "Poți să-mi explici cum se oprește microfonul în Discord?",
            "Не выключай микрофон в Discord", "Не надо включать микрофон Discord",
            "Не нажимай кнопку микрофона Discord", "Как выключить микрофон Discord?",
            "Don't mute my Discord microphone", "Do not press the Discord microphone button",
            "Never unmute my microphone in Discord", "How do I mute my Discord microphone?",
            "Scrie-i lui Hanzo în Discord «închide microfonul»",
            "Send Hanzo on Discord the message 'mute my microphone'",
            "Напиши Hanzo в Discord «выключи микрофон»",
            "Mute microphone in Discordant", "Mute microphone in NotDiscord",
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(discord_mic_visual_mode(phrase))
                self.assertFalse(wants_discord_mic_mute(phrase))
        for phrase in (
            "Nu începe dictarea", "Don't start dictation", "Не включай диктовку",
            "Cum pornesc dictarea?", "How to enable dictation?", "Как включить диктовку?",
            "Scrie-i lui Hanzo «pornește dictarea»", "Write 'start dictation'",
        ):
            with self.subTest(phrase=phrase):
                self.assertFalse(is_dictation_start(phrase))
        for phrase in (
            "Nu citi ecranul", "Don't read my screen", "Не читай экран",
            "How to read the screen?", "Cum pot citi ecranul?",
            "Scrie-i lui Hanzo «citește ecranul»", "Write 'read my screen'",
        ):
            with self.subTest(phrase=phrase):
                self.assertFalse(wants_screen_read(phrase))


if __name__ == "__main__":
    unittest.main()
