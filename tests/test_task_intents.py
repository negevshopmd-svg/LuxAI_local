"""Task classification never opens apps, captures images, or performs power calls."""
import unittest
from unittest import mock

from luxai.task_intents import (
    direct_action_request, direct_app_request, is_task_cancel,
    needs_adaptive_task, opening_app, screenshot_request, system_request,
)


class AppIntentTests(unittest.TestCase):
    def test_native_open_handles_politeness_wake_names_and_languages(self):
        cases = {
            "Жарвис, пожалуйста, открой окно Дискорда.": "discord",
            "Ты можешь открыть приложение Discord?": "discord",
            "зайди в Discord": "discord",
            "Открой мне окно Discord": "discord",
            "Could you please open the Discord app?": "discord",
            "Jarvis, open Visual Studio Code, please.": "vscode",
            "Te rog, deschide aplicația Calculator.": "calculator",
            "Poți să deschizi Blender?": "blender",
            "Deschide-mi aplicația Blender": "blender",
            "Open Discord for me": "discord",
            "Open Research and Development Studio": "research and development studio",
            "Open Black and White": "black and white",
            "Open My Start Tools": "my start tools",
        }
        for phrase, expected in cases.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(direct_app_request(phrase), expected)
                self.assertEqual(opening_app(phrase), expected)

    def test_initial_app_can_be_opened_without_discarding_remaining_goal(self):
        for phrase in (
            "Открой Discord и нажми на кнопку настроек",
            "Открой Steam, потом найди библиотеку",
            "Open Research and Development Studio and click Settings",
            "Open My Start Tools, then take a screenshot",
            "Deschide Calculator și apasă pe butonul 7",
            "Открой Blender и измени размер окна",
            "Open Discord, but don't send a message",
            "Deschide Blender și schimbă dimensiunea ferestrei",
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(direct_app_request(phrase))
                self.assertIsNotNone(opening_app(phrase))
        self.assertEqual(opening_app("Open Black and White and click Settings"), "black and white")

    def test_app_named_by_a_click_or_explanation_is_not_a_launch(self):
        for phrase in (
            "Нажми на кнопку в Discord", "Click the Settings button in Steam",
            "How do I open Discord?", "Как открыть Блокнот?",
            "Не открывай Discord", "Don't open Steam", "Nu deschide Discord",
            "Tell me about Blender", "Я использую Discord",
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(direct_app_request(phrase))
                self.assertIsNone(opening_app(phrase))

    def test_file_system_object_and_shell_requests_do_not_become_app_names(self):
        for phrase in (
            "Открой файл Отчет.docx", "Open folder Downloads", "Открой настройки Windows",
            "Open https://example.com", "Open C:\\Windows\\System32\\cmd.exe",
            "Run cmd /c dir", "Открой командную строку", "Open Windows Terminal",
            "Открой корзину", "Включи темную тему", "Включи микрофон",
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(direct_app_request(phrase))
                self.assertIsNone(opening_app(phrase))

    def test_classification_does_not_resolve_or_launch_installed_apps(self):
        with mock.patch("luxai.windows_apps.launch_installed_app", side_effect=AssertionError("No execution")), mock.patch(
            "luxai.windows_apps.resolve_installed_app", side_effect=AssertionError("No disk lookup"),
        ):
            self.assertEqual(direct_app_request("Open Blender"), "blender")


class CaptureIntentTests(unittest.TestCase):
    def test_pure_capture_does_not_require_cloud_or_visual_interpretation(self):
        for phrase in (
            "Сделай скриншот", "Жарвис сделай снимок экрана",
            "Сними экран", "Сделай снимок активного окна",
            "Please take a screenshot", "Capture the screen",
            "Take a screenshot of the current window",
            "Fă o captură de ecran", "Te rog fă un screenshot",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(screenshot_request(phrase))

    def test_capture_does_not_consume_multi_step_or_capability_questions(self):
        for phrase in (
            "Сделай снимок экрана и нажми кнопку", "Take a screenshot then click Settings",
            "Открой Discord и сделай скриншот", "Take a screenshot, find the contact",
            "Ты умеешь делать скриншоты?", "What is a screenshot?", "Read the screen",
        ):
            with self.subTest(phrase=phrase):
                self.assertFalse(screenshot_request(phrase))


class SystemIntentTests(unittest.TestCase):
    def test_explicit_power_intents_are_typed_and_bounded_to_system_target(self):
        cases = {
            "Жарвис, выключи компьютер": "shutdown",
            "Could you shut down my PC?": "shutdown",
            "Oprește calculatorul": "shutdown",
            "Перезагрузи Windows": "restart",
            "Restart the computer": "restart",
            "Repornește calculatorul": "restart",
            "Переведи ноутбук в спящий режим": "sleep",
            "Put my computer to sleep": "sleep",
            "Pune calculatorul în repaus": "sleep",
            "Заблокируй экран": "lock",
            "Lock my screen": "lock",
            "Blochează ecranul": "lock",
            "Отмени выключение компьютера": "cancel_shutdown",
            "Cancel shutdown": "cancel_shutdown",
            "Anulează oprirea calculatorului": "cancel_shutdown",
        }
        for phrase, expected in cases.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(system_request(phrase), {"action": expected})

    def test_questions_negation_and_app_restarts_never_become_power_actions(self):
        for phrase in (
            "Как выключить компьютер?", "How do I restart Windows?",
            "Cum pot opri calculatorul?", "Не выключай компьютер",
            "Restart Discord", "Перезапусти микрофон", "Выключи музыку",
            "Turn off the monitor", "Выключи компьютер потом открой Discord",
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(system_request(phrase))

    def test_dark_theme_and_actual_night_light_are_distinct_from_ambiguous_night_mode(self):
        for phrase, enabled in (
            ("Включи темную тему", True), ("Отключи тёмную тему", False),
            ("Включи светлую тему", False), ("Set dark theme", True),
            ("Turn off dark mode", False), ("Activează tema întunecată", True),
            ("Setează tema deschisă", False),
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(system_request(phrase), {"action": "set_dark_theme", "enabled": enabled})
        for phrase in ("Включи ночной свет", "Turn off night light", "Deschide lumina de noapte"):
            with self.subTest(phrase=phrase):
                self.assertEqual(system_request(phrase), {"action": "open_night_light_settings"})
        for phrase in ("Включи ночной режим", "Night mode", "Regim de noapte", "Activează modul de noapte"):
            with self.subTest(phrase=phrase):
                self.assertEqual(system_request(phrase), {"action": "clarify_night_mode"})

    def test_theme_queries_and_recycle_bin_do_not_change_state(self):
        for phrase in ("Какая сейчас тема Windows?", "What is the current theme?", "Ce temă este activă?"):
            with self.subTest(phrase=phrase):
                self.assertEqual(system_request(phrase), {"action": "get_theme"})
        for phrase in ("Открой корзину Windows", "Open the Recycle Bin", "Deschide coșul de reciclare"):
            with self.subTest(phrase=phrase):
                self.assertEqual(direct_action_request(phrase), {"action": "open_recycle_bin"})
        self.assertIsNone(direct_action_request("Открой корзину и очисти её"))


class AdaptiveTaskTests(unittest.TestCase):
    def test_tasks_include_novel_desktop_goals_research_and_explicit_shell(self):
        for phrase in (
            "Открой Discord", "Открой Blender и измени размер окна",
            "Найди в интернете как поменять тему Windows",
            "Как включить ночной свет в Windows?", "How do I fix my Windows microphone?",
            "Cum schimb tema Windows?", "Выполни в cmd команду dir",
            "Run a command in PowerShell", "Проверь настройки приложения",
            "Нажми кнопку в этом окне", "Сделай скриншот",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(needs_adaptive_task(phrase))

    def test_ordinary_talk_does_not_become_an_operational_task(self):
        for phrase in (
            "Привет", "Как дела?", "Спасибо", "Hi Jarvis", "Salut",
            "Расскажи шутку", "Tell me a story", "What is love?", "Как сварить борщ?",
        ):
            with self.subTest(phrase=phrase):
                self.assertFalse(needs_adaptive_task(phrase))

    def test_task_cancellation_does_not_steal_tts_stop_or_shutdown_cancel(self):
        for phrase in ("Отмени задание", "Останови текущую задачу", "Cancel this task", "Stop the operation", "Anulează sarcina"):
            with self.subTest(phrase=phrase):
                self.assertTrue(is_task_cancel(phrase))
                self.assertFalse(needs_adaptive_task(phrase))
        for phrase in ("Stop", "Стоп", "Останови музыку", "Cancel shutdown", "Открой Cancel Task Manager"):
            with self.subTest(phrase=phrase):
                self.assertFalse(is_task_cancel(phrase))


if __name__ == "__main__":
    unittest.main()
