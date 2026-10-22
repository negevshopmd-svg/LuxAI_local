"""Regression tests: quota-independent weather, voice typing and screen OCR."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import types
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from luxai.weather_service import (
    is_weather_question, parse_weather_request, get_weather_report,
)
from luxai.voice_desktop import (
    is_dictation_start, is_dictation_stop, dictation_text, wants_screen_read,
    wants_discord_mic_mute, read_screen_locally, toggle_discord_microphone,
)


class WeatherTests(unittest.TestCase):
    def test_russian_speech_weather_variants(self):
        for phrase in (
            "Какая погода завтра будет в Кишневе?",
            "Скорая погода завтра будет в Кишневе.",
            "Какая погода завтра в Кишинёве",
            "Погода завтра",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(is_weather_question(phrase))
                plan = parse_weather_request(phrase)
                self.assertEqual(plan["city"], "Кишинёв")
                self.assertEqual(plan["days"], 1)

    def test_weather_is_real_api_data_without_gemini_key(self):
        today = datetime.now(ZoneInfo("Europe/Chisinau")).date()
        dates = [(today + timedelta(days=k)).isoformat() for k in range(3)]
        payload = {
            "timezone": "Europe/Chisinau",
            "daily": {
                "time": dates,
                "weather_code": [0, 63, 3],
                "temperature_2m_min": [2.1, 4.5, 5.5],
                "temperature_2m_max": [13.0, 17.3, 18],
                "precipitation_probability_max": [0, 75, 20],
                "wind_speed_10m_max": [10, 24, 12],
            },
        }
        with mock.patch("luxai.weather_service._get_json", return_value=payload) as request:
            answer = get_weather_report("Какая погода завтра в Кишневе?")
            self.assertEqual(request.call_count, 1)  # known city needs no geocoding request
            self.assertIn(dates[1], answer)
            self.assertIn("от 4 до 17", answer)
            self.assertIn("75%", answer)
            self.assertIn("дождь", answer)
            self.assertIn("Open-Meteo", answer)
            self.assertNotIn("Gemini", answer)

    def test_unknown_city_uses_geocoding_then_forecast(self):
        day = datetime.now(ZoneInfo("Europe/Paris")).date()
        result = {
            "timezone": "Europe/Paris",
            "daily": {
                "time": [(day + timedelta(days=x)).isoformat() for x in range(3)],
                "weather_code": [2, 3, 2],
                "temperature_2m_min": [1, 2, 3],
                "temperature_2m_max": [11, 12, 13],
                "precipitation_probability_max": [10, 20, 30],
            },
        }
        with mock.patch(
            "luxai.weather_service._get_json",
            side_effect=[
                {"results": [{"latitude": 48.86, "longitude": 2.35, "name": "Paris"}]},
                result,
            ],
        ) as call:
            response = get_weather_report("Погода завтра в Paris?")
        self.assertEqual(call.call_count, 2)
        self.assertIn("Paris", response)
        self.assertIn("20%", response)

    def test_missing_data_is_not_invented(self):
        with mock.patch("luxai.weather_service._get_json", return_value={"daily": {"time": []}}):
            with self.assertRaises(ValueError):
                get_weather_report("погода завтра в Кишинёве")

    def test_nothing_looks_like_weather_when_it_isnt(self):
        self.assertFalse(is_weather_question("Здравствуй Jarvis"))
        self.assertIsNone(parse_weather_request("Открой Firefox"))


class VoiceToolsTests(unittest.TestCase):
    def test_dictation_start_and_explicit_stop(self):
        self.assertTrue(is_dictation_start(
            "Теперь я тебе могу диктовать, ты будешь писать, пока не скажу стоп."
        ))
        self.assertTrue(is_dictation_start("Жарвис, включи диктовку"))
        self.assertTrue(is_dictation_stop("Стоп."))
        self.assertTrue(is_dictation_stop("Жарвис, останови диктовку."))
        self.assertFalse(is_dictation_stop("Он сказал слово стоп в этом предложении"))

    def test_dictation_converts_punctuation(self):
        self.assertEqual(dictation_text("точка"), ".")
        self.assertEqual(dictation_text("Новая строка"), "\n")
        self.assertEqual(dictation_text("Привет, как дела?"), "Привет, как дела? ")

    def test_screen_recognition_from_spoken_command(self):
        for phrase in (
            "Прочитай что написано на экране.",
            "Жарвис, посмотри на мой экран.",
            "Что у меня на экране?",
        ):
            self.assertTrue(wants_screen_read(phrase))
        self.assertFalse(wants_screen_read("Экран компьютера хороший."))

    def test_local_ocr_does_not_call_cloud(self):
        with mock.patch("luxai.screen.capture_screen", return_value="some.png"), mock.patch(
            "luxai.screen.read_screen_text", return_value="Привет! Это на экране."
        ):
            response = read_screen_locally()
        self.assertIn("Привет", response)
        self.assertIn("экране", response)

    def test_missing_tesseract_is_explained(self):
        with mock.patch("luxai.screen.capture_screen", return_value="some.png"), mock.patch(
            "luxai.screen.read_screen_text", side_effect=FileNotFoundError("tesseract missing")
        ):
            response = read_screen_locally()
        self.assertIn("Tesseract", response)

    def test_discord_microphone_command_and_truthful_toggle(self):
        self.assertTrue(wants_discord_mic_mute("Выключи микрофон в дискорде."))
        self.assertTrue(wants_discord_mic_mute("Жарвис, отключи микрофон Discord"))
        self.assertFalse(wants_discord_mic_mute("Открой Discord"))
        with mock.patch("sys.platform", "win32"), mock.patch(
            "luxai.windows_control.running_pids", return_value={42}
        ), mock.patch.dict("sys.modules", {
            "pyautogui": types.SimpleNamespace(hotkey=mock.Mock())
        }):
            prompts = []
            refusal = toggle_discord_microphone(lambda p: prompts.append(p) or False)
            self.assertIn("отменено", refusal)
            self.assertIn("Если он уже выключен", prompts[0])
            response = toggle_discord_microphone(lambda _: True)
            self.assertIn("переключатель", response)
            self.assertNotIn("микрофон выключен", response)


if __name__ == "__main__":
    unittest.main()
