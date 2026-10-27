"""Curated equivalent requests must select the same local tools in RU/RO/EN.

The corpus varies verb forms, object nouns, courtesy, diacritics, punctuation
and wake names; it is deliberately not one translated example per feature.
"""
import unicodedata
import unittest
from types import MethodType, SimpleNamespace
from unittest import mock

from luxai.agent import LocalAgent
from luxai.fast_intents import command_text
from luxai.intent_routing import is_operational_request, suspicious_completion_reply
from luxai.task_intents import direct_app_request, screenshot_request, system_volume_request
from luxai.voice_actions import parse_action_sequence
from luxai.voice_shortcuts import keyboard_action_plan
from luxai.voice_rules import recognition_options, is_stop_speech_command, is_hallucinated_outro


OPEN_DISCORD = {
    "ro": [
        "Deschide Discord", "Deschide aplicația Discord", "Deschide aplicatia Discord",
        "Jarvis, deschide Discord.", "Te rog să deschizi Discord", "Poți să deschizi Discord?",
        "Poti sa deschizi Discord?", "Poți te rog să deschizi Discord?",
        "Ai putea să pornești Discord?", "Aș dori să deschizi Discord",
        "Deschide-mi aplicația Discord", "Deschide fereastra aplicației Discord",
        "Pornește Discord, te rog frumos", "Îmi poți deschide Discord?", "Lansează Discord",
    ],
    "ru": [
        "Открой Discord", "Открыть Discord", "Открой приложение Discord",
        "Жарвис, открой Discord.", "Пожалуйста, открой Discord", "Ты можешь открыть Discord?",
        "Можешь открыть окно Discord?", "Не мог бы ты открыть Discord?",
        "Запусти Discord", "Запустить приложение Discord", "Включи Discord",
        "Зайди в Discord", "Открой мне окно Дискорда", "Открой Discord, пожалуйста", "Открывай Discord",
    ],
    "en": [
        "Open Discord", "Launch Discord", "Start Discord", "Run Discord",
        "Jarvis, open Discord.", "Please open Discord", "Can you open Discord?",
        "Could you please open Discord?", "Would you launch Discord?", "Will you start Discord?",
        "Open the Discord app", "Open the Discord window", "Open Discord for me",
        "Please open the application Discord", "Open Discord, please",
    ],
}

PRESS_Q = {
    "ro": [
        "Apasă Q", "Apasa Q", "Apasă tasta Q", "Apasa tasta Q", "Apasă pe Q",
        "Apasă pe tasta Q", "Apasa pe butonul Q", "Apasă litera Q", "Jarvis, apasă Q.",
        "Te rog, apasă tasta Q", "Poți să apeși tasta Q?", "Poti sa apesi pe Q?",
        "Poți te rog să apeși pe tasta Q?", "Ai putea să apeși Q?", "Apăsați tasta Q",
    ],
    "ru": [
        "Нажми Q", "Нажать Q", "Нажмите Q", "Жми Q", "Нажимай Q",
        "Нажми на Q", "Нажми клавишу Q", "Нажми на клавишу Q", "Нажми кнопку Q",
        "Нажми английскую Q", "Нажми букву Q", "Жарвис, нажми Q.",
        "Пожалуйста, нажми Q", "Можешь нажать Q?", "Нажми Q, пожалуйста",
    ],
    "en": [
        "Press Q", "Press the Q key", "Press key Q", "Press the key Q", "Hit Q",
        "Tap Q", "Jarvis, press Q.", "Please press Q", "Can you press Q?",
        "Could you please press Q?", "Would you press the key Q?", "Will you hit Q?",
        "Please tap the key Q", "Press Q, please", "Could you tap Q?",
    ],
}

VOLUME_FIFTY = {
    "ro": [
        "Setează volumul la 50", "Seteaza volumul la 50", "Pune volumul la 50%",
        "Schimbă volumul la 50 procente", "Reglează volumul la 50 de procente",
        "Setează volumul sistemului la 50", "Setează volumul Windows la 50%",
        "Jarvis, pune volumul la 50.", "Te rog setează volumul la 50",
        "Poți să setezi volumul la 50?", "Poti te rog sa setezi volumul la 50?",
        "Ai putea să reglezi volumul la 50?", "Aș dori să setezi volumul la 50",
        "Dă volumul la 50", "Setează volumul la 50, te rog",
    ],
    "ru": [
        "Поставь громкость на 50", "Установи громкость 50", "Сделай громкость 50%",
        "Измени громкость на 50 процентов", "Выставь громкость до 50",
        "Поставь звук на 50", "Установи громкость Windows на 50%",
        "Поставь громкость звука на 50", "Жарвис, поставь громкость на 50.",
        "Пожалуйста, поставь громкость на 50", "Можешь поставить громкость на 50?",
        "Ты можешь установить громкость на 50?", "Не мог бы ты сделать громкость 50?",
        "Поставь громкость на 50, пожалуйста", "Установи звук до 50 процентов",
    ],
    "en": [
        "Set volume to 50", "Set the volume to 50%", "Change volume to 50 percent",
        "Adjust volume to 50", "Put volume at 50", "Set system volume to 50%",
        "Set the system volume to 50", "Jarvis, set volume to 50.",
        "Please set volume to 50", "Can you set volume to 50?",
        "Could you please change volume to 50?", "Would you adjust the volume to 50?",
        "Will you put volume at 50?", "Set volume to 50, please", "Set volume to 50 per cent",
    ],
}

CAPTURE = {
    "ro": [
        "Fă o captură de ecran", "Fa o captura de ecran", "Fă-mi o captură de ecran",
        "Fă o captură a ecranului", "Salvează o captură de ecran", "Capturează o captură de ecran",
        "Fă un screenshot", "Fă un printscreen", "Fotografiază ecranul",
        "Fă o poză la ecran", "Jarvis, fă o captură de ecran.",
        "Te rog fă o captură de ecran", "Poți să faci o captură de ecran?",
        "Ai putea să faci un screenshot?", "Fă o captură de ecran, te rog",
    ],
    "ru": [
        "Сделай скриншот", "Сделать скриншот", "Сними экран", "Сними скрин",
        "Сохрани скриншот", "Сделай снимок экрана", "Сделай снимок активного окна",
        "Сделай мне скриншот", "Сохрани снимок текущего экрана",
        "Жарвис, сделай скриншот.", "Пожалуйста, сделай скриншот",
        "Можешь сделать скриншот?", "Ты можешь сделать снимок экрана?",
        "Не мог бы ты сделать скриншот?", "Сделай скриншот, пожалуйста",
    ],
    "en": [
        "Take a screenshot", "Make a screenshot", "Save a screenshot", "Capture screen",
        "Capture the screen", "Capture my screen", "Take a screen shot",
        "Take a screen capture", "Take a screenshot of my screen",
        "Take a screenshot of the current window", "Jarvis, take a screenshot.",
        "Please take a screenshot", "Could you please take a screenshot?",
        "Can you capture the screen?", "Take a screenshot, please",
    ],
}

SAVE = {
    "ro": [
        "Salvează", "Salveaza", "Salvează documentul", "Salvează fișierul",
        "Salveaza fisierul", "Jarvis, salvează.", "Te rog salvează documentul",
        "Poți să salvezi documentul?", "Poti sa salvezi fisierul?",
        "Poți te rog să salvezi?", "Ai putea să salvezi documentul?",
        "Aș dori să salvezi documentul", "Salvează, te rog", "Salvează fișierul, te rog frumos",
        "Îmi poți salva documentul?",
    ],
    "ru": [
        "Сохрани", "Сохранить", "Сохрани документ", "Сохрани файл", "Жарвис, сохрани.",
        "Пожалуйста, сохрани", "Можешь сохранить?", "Можешь сохранить документ?",
        "Ты можешь сохранить файл?", "Не мог бы ты сохранить?", "Не могла бы ты сохранить документ?",
        "Хочу чтобы ты сохрани документ", "Сохрани, пожалуйста", "Пожалуйста, сохрани файл.",
        "Жарвис, пожалуйста, сохрани документ",
    ],
    "en": [
        "Save", "Save document", "Save the document", "Save the file", "Save current document",
        "Jarvis, save.", "Please save", "Can you save the document?", "Could you please save the file?",
        "Would you save?", "Will you save the document?", "Save the current document",
        "Save, please", "Please save current file", "Jarvis, could you save the document?",
    ],
}


class MultilingualCommandParityTests(unittest.TestCase):
    def test_fifteen_open_variants_in_each_language_select_identical_native_app(self):
        for language, variants in OPEN_DISCORD.items():
            self.assertEqual(len(variants), 15)
            for phrase in variants:
                with self.subTest(language=language, phrase=phrase):
                    self.assertEqual(direct_app_request(phrase), "discord")

    def test_fifteen_key_variants_reach_the_same_validated_local_executor(self):
        for language, variants in PRESS_Q.items():
            self.assertEqual(len(variants), 15)
            agent = LocalAgent({"response_language": language})
            for phrase in variants:
                with self.subTest(language=language, phrase=phrase):
                    plan = parse_action_sequence(phrase)
                    self.assertIsNotNone(plan)
                    self.assertEqual(len(plan), 1)
                    self.assertEqual((plan[0]["action"], plan[0]["target"]), ("press_key", "q"))
                    with mock.patch("luxai.agent.execute_desktop_step", return_value="Verified key") as execute:
                        agent.execute_plan(phrase, plan[0], lambda _: False)
                    execute.assert_called_once_with(plan[0])
                    self.assertTrue(agent.last_execution_success)

    def test_fifteen_volume_variants_set_and_read_back_same_master_endpoint(self):
        for language, variants in VOLUME_FIFTY.items():
            self.assertEqual(len(variants), 15)
            agent = LocalAgent({"response_language": language})
            for phrase in variants:
                with self.subTest(language=language, phrase=phrase):
                    plan = system_volume_request(phrase)
                    self.assertEqual(plan, {"action": "set_system_volume", "target": "50"})
                    with mock.patch("luxai.agent.windows_volume", return_value=50) as volume:
                        agent.execute_plan(phrase, plan, lambda _: False)
                    volume.assert_called_once_with(50)
                    self.assertTrue(agent.last_execution_success)

    def test_fifteen_capture_variants_select_local_screenshot_without_cloud(self):
        for language, variants in CAPTURE.items():
            self.assertEqual(len(variants), 15)
            for phrase in variants:
                with self.subTest(language=language, phrase=phrase):
                    self.assertTrue(screenshot_request(phrase))

    def test_fifteen_save_variants_select_the_same_local_save_action(self):
        for language, variants in SAVE.items():
            self.assertEqual(len(variants), 15)
            for phrase in variants:
                with self.subTest(language=language, phrase=phrase):
                    plan = keyboard_action_plan(phrase)
                    self.assertIsNotNone(plan)
                    self.assertEqual((plan["action"], plan["target"]), ("save_document", ""))

    def test_compound_input_has_identical_order_and_no_partial_plan(self):
        commands = {
            "ru": "Пожалуйста, нажми Q, потом подожди 2 секунды, затем кликни",
            "ro": "Te rog, apasă tasta Q, apoi așteaptă 2 secunde, după aceea fă clic",
            "en": "Could you please press Q, then wait 2 seconds, after that click",
        }
        for phrase in commands.values():
            plan = parse_action_sequence(phrase)
            self.assertEqual([(x["action"], x["target"]) for x in plan],
                             [("press_key", "q"), ("wait_seconds", "2"), ("mouse_click", "")])
        for phrase in ("Apasă Q apoi fă ceva necunoscut", "Press Q then bypass security",
                       "Нажми Q потом сделай неизвестное"):
            self.assertIsNone(parse_action_sequence(phrase))

    def test_literal_typing_preserves_punctuation_and_words_that_sound_like_commands(self):
        body = "Salut! Nu închide Discord, te rog!"
        for prefix in ("Напечатай", "Type", "Scrie", "Te rog scrie"):
            plan = parse_action_sequence(prefix + " " + body)
            self.assertEqual(plan[0]["action"], "type_text")
            self.assertEqual(plan[0]["target"], body)
        for body in ("Hello, Jarvis!", "Salut, te rog!", "Vreau literele ş şi ţ."):
            self.assertEqual(parse_action_sequence("Scrie " + body)[0]["target"], body)

    def test_how_to_negation_messages_and_extra_tasks_do_not_execute_partial_native_actions(self):
        for phrase in (
            "Nu deschide Discord", "Nu apăsa Q", "Nu seta volumul la 50", "Cum deschid Discord?",
            "Cum pot apăsa Q?", "Cum se setează volumul la 50?", "Spune-mi despre volumul 50",
            "Don't open Discord", "Do not press Q", "Don't set volume to 50", "How do I set volume to 50?",
            "Не открывай Discord", "Не нажимай Q", "Не ставь громкость на 50", "Как поставить громкость на 50?",
            'Trimite lui Hanzo mesajul "setează volumul la 50"',
            'Tell Hanzo "press Q"', 'Скажи Hanzo "поставь громкость 50"',
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(direct_app_request(phrase))
                self.assertIsNone(parse_action_sequence(phrase))
                self.assertIsNone(system_volume_request(phrase))
        message = 'Напиши Hanzo "поставь громкость 50"'
        self.assertIsNone(system_volume_request(message))
        self.assertEqual(parse_action_sequence(message)[0]["action"], "type_text")
        self.assertEqual(parse_action_sequence(message)[0]["target"], 'Hanzo "поставь громкость 50"')
        for phrase in ("Deschide Discord și setează volumul la 50", "Open Discord and press Q",
                       "Открой Discord и нажми Q"):
            self.assertIsNone(direct_app_request(phrase))

    def test_unicode_keyboard_layout_variants_and_same_language_operational_detection(self):
        for phrase in ("Apasă tasta Q", "Apasă tasta Q".replace("ă", "a"),
                       unicodedata.normalize("NFD", "Apasă tasta Q"), "Apasă tasta Q".replace("ș", "ş")):
            self.assertEqual(parse_action_sequence(phrase)[0]["target"], "q")
        for phrase in ("Închide Discord", "Apasă pe tasta Q", "Scrie textul Salut", "Reglează volumul la 50",
                       "Derulează în jos", "Mută cursorul la 10,20", "Citește ecranul"):
            self.assertTrue(is_operational_request(phrase), phrase)
        for phrase in ("Am deschis Discord", "Am apăsat Q", "Am setat volumul", "Am șters fișierul"):
            self.assertTrue(suspicious_completion_reply(phrase), phrase)

    def test_asr_language_preferences_remain_explicit_and_romanian_has_command_vocabulary(self):
        for language in ("ru", "ro", "en", None):
            options = recognition_options(language, 3)
            self.assertEqual(options["language"], language)
            self.assertGreaterEqual(options["beam_size"], 3)
        romanian = recognition_options("ro", 1)
        self.assertGreaterEqual(romanian["beam_size"], 3)
        self.assertIn("War Thunder", romanian["initial_prompt"])
        self.assertIn("Închide", romanian["initial_prompt"])
        automatic = recognition_options(None, 1)
        self.assertGreaterEqual(automatic["beam_size"], 3)
        for vocabulary in ("Apasă", "нажми", "press", "War Thunder"):
            self.assertIn(vocabulary, automatic["initial_prompt"])
        for phrase in ("Oprește-te!", "Opreşte-te!", unicodedata.normalize("NFD", "Oprește-te!")):
            self.assertTrue(is_stop_speech_command(phrase))
        self.assertFalse(is_stop_speech_command("Oprește War Thunder"))
        self.assertTrue(is_hallucinated_outro("Mulţumesc   pentru vizionare!"))


class MultilingualDispatchParityTests(unittest.TestCase):
    """Exercise MainWindow's real routing with inert executor/UI adapters."""
    def window(self, phrase, language):
        import main
        registry = mock.Mock()
        registry.disabled_match.return_value = False
        registry.match.return_value = None
        group = {"parts": [phrase], "answers": [], "routes": [], "original_text": phrase}
        window = SimpleNamespace(
            cfg={"response_language": language, "tts_enabled": False},
            _processing=False, _closed=False, _active_text=None, _current_route="",
            _command_queue=[group], _pending_discord_message=None, _pending_agent_task=None,
            _adaptive_runtime=None, _adaptive_token=None,
            _last_visual_goal=None, _last_visual_goal_at=0.0, dictation_active=False,
            command_wizard=SimpleNamespace(active=False), command_registry=registry,
            online_planner=mock.Mock(), agent=mock.Mock(), mic_status=mock.Mock(),
            _run_direct_input=mock.Mock(), _start_adaptive_task=mock.Mock(),
            _start_native_plan=mock.Mock(),
            _start_visual_reasoner=mock.Mock(), _resolved_command=mock.Mock(),
            _execute_registered=mock.Mock(), confirm_action=mock.Mock(return_value=False),
            _error_message=lambda error: f"Routing error: {type(error).__name__}: {error}",
        )
        window._dispatch_command = MethodType(main.MainWindow._dispatch_command, window)
        return window

    def test_all_forty_five_key_variants_dispatch_native_input_without_cloud(self):
        for language, variants in PRESS_Q.items():
            for phrase in variants:
                with self.subTest(language=language, phrase=phrase):
                    window = self.window(phrase, language)
                    window._dispatch_command()
                    window._run_direct_input.assert_called_once_with(phrase, parse_action_sequence(phrase))
                    window._start_adaptive_task.assert_not_called()
                    window._start_visual_reasoner.assert_not_called()
                    window.agent.handle.assert_not_called()

    def test_all_open_and_capture_variants_dispatch_complete_task_not_chat(self):
        for corpus in (OPEN_DISCORD, CAPTURE):
            for language, variants in corpus.items():
                for phrase in variants:
                    with self.subTest(language=language, phrase=phrase):
                        window = self.window(phrase, language)
                        window._dispatch_command()
                        window._start_adaptive_task.assert_called_once_with(phrase)
                        window._run_direct_input.assert_not_called()
                        window.agent.handle.assert_not_called()

    def test_all_forty_five_volume_variants_dispatch_typed_master_volume_before_cloud(self):
        for language, variants in VOLUME_FIFTY.items():
            for phrase in variants:
                with self.subTest(language=language, phrase=phrase):
                    window = self.window(phrase, language)
                    window._dispatch_command()
                    window._start_native_plan.assert_called_once_with(
                        phrase, {"action": "set_system_volume", "target": "50"},
                    )
                    window._start_adaptive_task.assert_not_called()
                    window._run_direct_input.assert_not_called()
                    window.agent.handle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
