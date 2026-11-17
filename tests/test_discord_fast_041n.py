"""0.4.1n: fast Discord control with Discord's own shortcuts and a window map."""
from __future__ import annotations

import unittest
from unittest import mock

from luxai import discord_shortcuts as ds


class ShortcutIntentTests(unittest.TestCase):
    def check(self, phrase, expected, foreground=False):
        self.assertEqual(ds.detect_discord_shortcut(phrase, foreground=foreground), expected, phrase)

    def test_russian_romanian_english_commands(self):
        self.check("Жарвис, следующий сервер в дискорде", "next_server")
        self.check("прими звонок в дискорде", "answer_call")
        self.check("отклони звонок в discord", "decline_call")
        self.check("открой закреплённые в дискорде", "pins")
        self.check("открой личные сообщения в дискорде", "toggle_dms")
        self.check("следующий непрочитанный канал в дискорде", "next_unread")
        self.check("предыдущий канал в дискорде", "prev_channel")
        self.check("вернись в звонок в дискорде", "jump_call")
        self.check("открой быстрый переход в дискорде", "quick_switcher")
        self.check("deschide setările discord", "settings")
        self.check("răspunde la apel în discord", "answer_call")
        self.check("canalul următor în discord", "next_channel")
        self.check("next server in discord", "next_server")

    def test_other_workflows_keep_priority(self):
        # mic/headphones, messages and calls to a named person have verified flows
        self.check("выключи микрофон в дискорде", None)
        self.check("выключи наушники в дискорде", None)
        self.check("напиши Ханзу привет в дискорде", None)
        self.check("отправь гиф в дискорде", None)
        self.check("позвони Ханзу в дискорде", None)
        self.check("как перейти на следующий сервер в дискорде", None)
        self.check("не открывай настройки дискорда", None)
        self.check("открой дискорд", None)

    def test_without_the_word_discord_only_when_discord_is_active(self):
        self.check("следующий канал", None, foreground=False)
        self.check("следующий канал", "next_channel", foreground=True)
        self.check("прими звонок", "answer_call", foreground=True)
        # generic words still belong to Jarvis even while Discord is in front
        self.check("открой настройки", None, foreground=True)
        self.check("назад", None, foreground=True)

    def test_every_shortcut_has_valid_keys(self):
        from luxai.keys import vk_code
        for item in ds.SHORTCUTS:
            for key in item.keys:
                vk_code(key)
            self.assertEqual(len(item.done), 3)
        self.assertEqual(ds.shortcut_label(ds.BY_ID["jump_call"]), "Ctrl+Shift+Alt+V")
        self.assertIn("next_server=Ctrl+Alt+↓", ds.shortcuts_for_ai())
        self.assertNotIn("answer_call", ds.shortcuts_for_ai())

    def test_run_focuses_discord_then_presses(self):
        with (
            mock.patch("luxai.windows_control.running_pids", return_value=[5]),
            mock.patch("luxai.discord_window_state.find_discord_window", return_value=77),
            mock.patch.object(ds, "press_in_discord") as press,
        ):
            answer = ds.run_discord_shortcut("next_server", "ru")
        press.assert_called_once_with(77, "ctrl", "alt", "down")
        self.assertIn("Следующий сервер", answer)
        self.assertIn("Ctrl+Alt+↓", answer)

    def test_run_when_discord_is_closed(self):
        with (
            mock.patch("luxai.windows_control.running_pids", return_value=[]),
            mock.patch.object(ds, "press_in_discord") as press,
        ):
            self.assertIn("не запущен", ds.run_discord_shortcut("pins", "ru"))
        press.assert_not_called()


class QuickStatusTests(unittest.TestCase):
    def test_status_phrases(self):
        for phrase in ("проверь дискорд", "с кем я в звонке в дискорде", "какой микрофон в дискорде",
                       "verifică discord", "кто мне звонит в дискорде", "check discord"):
            self.assertTrue(ds.detect_discord_status_request(phrase), phrase)
        for phrase in ("выключи микрофон в дискорде", "позвони Ханзу в дискорде", "открой дискорд",
                       "проверь почту"):
            self.assertFalse(ds.detect_discord_status_request(phrase), phrase)

    def test_format(self):
        text = ds.format_discord_status({"mic": "muted", "headphones": "on", "in_call": True,
                                         "call_with": "Ханзу", "open_chat": "Ханзу", "profile": "Ханзу"}, "ru")
        self.assertIn("Микрофон: выключен", text)
        self.assertIn("наушники: включены", text)
        self.assertIn("в звонке: Ханзу", text)
        self.assertEqual(text.count("Ханзу"), 2)  # profile equal to chat is not repeated
        text = ds.format_discord_status({"mic": "unknown", "headphones": "deafened", "in_call": False,
                                         "open_chat": "empty", "incoming_call": "Octavian"}, "ro")
        self.assertIn("Microfon: nu se vede", text)
        self.assertIn("apel de la Octavian", text)
        self.assertIn("nu ești în apel", text)

    def test_one_screenshot_one_ai_look_with_the_map(self):
        planner = mock.Mock()
        planner._provider.return_value = "gemini"
        planner.enabled.return_value = True
        planner.config = {}
        planner._read_json_content.return_value = {"mic": "unmuted", "headphones": "on", "in_call": False}
        with (
            mock.patch("luxai.discord_screen_review._ensure_discord_visible", return_value=9),
            mock.patch("luxai.discord_screen_review.focus_discord"),
            mock.patch("luxai.visual_click.capture_window", return_value=mock.Mock()) as shot,
            mock.patch("luxai.visual_click.multimodal_messages",
                       return_value=[{"content": ""}, {"content": "x"}]) as messages,
            mock.patch("luxai.secure_keys.get_api_key", return_value="k"),
        ):
            answer = ds.discord_quick_status(planner, "ru")
        shot.assert_called_once_with(9)
        planner._request.assert_called_once()
        self.assertIn("BOTTOM-LEFT", messages.call_args.args[0])
        self.assertIn("Микрофон: включён", answer)


class VisualReasonerKnowsDiscordTests(unittest.TestCase):
    def test_map_in_prompts(self):
        import inspect
        from luxai import visual_reasoner, discord_mic_visual, discord_headphones_visual
        self.assertIn("discord_key", inspect.getsource(visual_reasoner))
        self.assertIn("DISCORD_LAYOUT", inspect.getsource(discord_mic_visual))
        self.assertIn("DISCORD_LAYOUT", inspect.getsource(discord_headphones_visual))
        self.assertIn("MICROPHONE", ds.DISCORD_LAYOUT)
        self.assertIn("TOP-RIGHT", ds.DISCORD_LAYOUT)


if __name__ == "__main__":
    unittest.main()
