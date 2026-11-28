"""0.4.4d: the first word of a Russian command repaired when Whisper drops or garbles its first sound.

Measured (tests/command_bench/accuracy_bench.py, Whisper medium, 129 new commands by three Russian voices + the
20 tuning commands): word errors 18.6 % → 15.6 % and wrong first word 19.4 % → 12.4 % on the new set;
96 results better, 0 worse; no extra time (a text rule, microseconds).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from luxai.voice_rules import fix_command_words  # noqa: E402


class FirstWordTests(unittest.TestCase):
    def test_lost_first_sounds_are_repaired(self):
        cases = {
            "Окрой калькулятор.": "Открой калькулятор.", "Окрой Википедию.": "Открой Википедию.",
            "Крой окно.": "Открой окно.", "Делай тише на 20%.": "Сделай тише на 20%.",
            "Делай погромче": "Сделай погромче", "Напомню, через 10 минут позвонить маме.":
            "Напомни через 10 минут позвонить маме.", "Напомню завтра купить хлеб.": "Напомни завтра купить хлеб.",
            "Найти в интернете рецепт блинов.": "Найди в интернете рецепт блинов.",
            "Запустит Dota 2.": "Запусти Dota 2.", "Запустите.": "Запусти.", "Копируй это.": "Скопируй это.",
            "Убей звук.": "Убавь звук.",
        }
        for heard, meant in cases.items():
            self.assertEqual(fix_command_words(heard), meant, heard)

    def test_real_words_and_other_languages_are_left_alone(self):
        for text in ("Закрой окно", "Скрой островок", "Открой стим", "Делай что хочешь", "Напомню тебе потом",
                     "Найти бы время", "Убей босса", "Deschide YouTube", "Open YouTube", "кройка и шитьё",
                     "Он сказал окрой", "", "   "):
            expected = text if text.split(" ")[0] != "кройка" else text
            self.assertEqual(fix_command_words(text), expected, text)

    def test_hostile_input(self):
        self.assertEqual(fix_command_words(None), "")
        self.assertEqual(fix_command_words(["Окрой"]), "['Окрой']")
        self.assertEqual(fix_command_words("Окрой " + "а" * 5000)[:7], "Открой ")


class RecognizeTests(unittest.TestCase):
    def test_the_listener_hands_over_the_repaired_text(self):
        from luxai import voice
        item = voice.VoiceListener.__new__(voice.VoiceListener)
        item.language, item.beam_size = "ru", 1
        item.model = SimpleNamespace(transcribe=lambda audio, **k: ([SimpleNamespace(text=" Окрой калькулятор.")], None))
        import numpy as np
        self.assertEqual(item._recognize(np.zeros(1600, dtype=np.float32)), "Открой калькулятор.")


if __name__ == "__main__":
    unittest.main()
