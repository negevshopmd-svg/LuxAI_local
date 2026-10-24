"""Regress the actual reported Windows voice intent and visual action failures.

All tests are offline. They never touch Discord contacts, a live browser or
the user's microphone.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

from luxai.discord_navigation import detect_discord_open_dm, open_discord_contact
from luxai.discord_contact_vision import VisibleContact
from luxai.research_notepad import (
    detect_research_notepad, validate_research_topic,
    _research_three_facts, write_researched_facts_to_notepad,
)
from luxai.voice_desktop import wants_discord_mic_mute
from luxai.macro_planner import needs_live_macro_planning, validate_generated_macro

DISCORD = "Нажми в Дискорд на пользователя Старый Бог"
MUTE = "Выключу микрофон в дискорде."
MARS = (
    "Жарвис, найди в интернете три факта про Марс, открой Блокнот, "
    "напиши эти три факта, потом выдели весь текст и скопируй его."
)


class RealSpeechRegressionTests(unittest.TestCase):
    def test_direct_discord_contact_routed_without_generic_chatbot(self):
        self.assertEqual(detect_discord_open_dm(DISCORD), "Старый Бог")
        self.assertTrue(needs_live_macro_planning(DISCORD))
        self.assertIsNone(detect_discord_open_dm(
            "Нажми в Дискорд на пользователя Старый Бог и отправь сообщение"
        ))
        self.assertIsNone(detect_discord_open_dm(
            "Открой Discord потом найди пользователя Старый Бог и сделай снимок экрана"
        ))
        accepted = validate_generated_macro({
            "steps": [{"action": "discord_open_dm", "target": "Старый Бог"}]
        }, DISCORD)
        self.assertEqual(accepted["steps"][0]["target"], "Старый Бог")
        self.assertIsNone(validate_generated_macro({
            "steps": [{"action": "open_app", "target": "discord"}]
        }, DISCORD))

    def test_misheard_discord_mute_remains_local(self):
        for phrase in (
            MUTE, "Жарвис выключи микрофон в Discord",
            "Отключу микрофон в дискорде",
        ):
            from luxai.voice_desktop import discord_mic_visual_mode
            self.assertEqual(discord_mic_visual_mode(phrase), "mute", phrase)
            self.assertFalse(wants_discord_mic_mute(phrase))
        self.assertFalse(wants_discord_mic_mute(
            "Сделай снимок и нажми на кнопку микрофона в дискорде"
        ))

    def test_notepad_three_facts_full_request_not_generic_search(self):
        self.assertEqual(detect_research_notepad(MARS), "Марс")
        self.assertTrue(needs_live_macro_planning(MARS))
        complete = validate_generated_macro({
            "steps": [{"action": "research_notepad_facts", "target": "Марс"}],
        }, MARS)
        self.assertEqual(complete["steps"][0]["action"], "research_notepad_facts")
        self.assertIsNone(validate_generated_macro({
            "steps": [{"action": "search_web", "target": "Марс"}]
        }, MARS))
        self.assertIsNone(detect_research_notepad("Найди в интернете факты про Марс"))
        with self.assertRaises(ValueError):
            validate_research_topic("../hidden")

    def test_one_session_screenshot_consent_and_denial(self):
        import main
        fake = types.SimpleNamespace(confirm_action=mock.Mock(return_value=True))
        self.assertTrue(main.MainWindow._allow_cloud_screenshots(fake))
        self.assertTrue(main.MainWindow._allow_cloud_screenshots(fake))
        fake.confirm_action.assert_called_once()
        other = types.SimpleNamespace(confirm_action=mock.Mock(return_value=False))
        self.assertFalse(main.MainWindow._allow_cloud_screenshots(other))
        self.assertFalse(getattr(other, "_visual_upload_consent_session", False))

    def test_native_mute_precedes_learned_open_discord_shortcut(self):
        try:
            from PySide6.QtWidgets import QApplication
            import main
            import tempfile
        except ImportError:
            self.skipTest("Qt unavailable")
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as td:
            file = Path(td) / "config.json"
            file.write_text(
                '{"microphone_enabled":false,"tts_enabled":false,'
                '"online_agent_enabled":false}', encoding="utf-8",
            )
            config_patch = mock.patch.object(main, "CONFIG", file)
            config_patch.start()
            self.addCleanup(config_patch.stop)
            with mock.patch("sounddevice.query_devices", return_value=[]):
                window = main.MainWindow()
            try:
                window.command_registry.match = mock.Mock(return_value={
                    "action": "open_app", "target": "discord", "steps": [],
                })
                with (
                    mock.patch.object(window, "_start_discord_mic_visual") as visual,
                    mock.patch.object(window, "_execute_registered") as registered,
                    mock.patch.object(main, "toggle_discord_microphone") as shortcut,
                ):
                    window.run_command(MUTE)
                visual.assert_called_once_with(MUTE)
                registered.assert_not_called()
                shortcut.assert_not_called()
            finally:
                window.close()


class ExecutorRoutingRegressionTests(unittest.TestCase):
    def test_mouse_display_step_uses_catalog_executor_not_agent(self):
        import main
        step = {"action": "display_info", "target": "", "location": "desktop"}
        fake = types.SimpleNamespace(
            _closed=False, _processing=True,
            _macro_context={
                "text": "show resolution then move and right click",
                "steps": [step], "index": 0, "messages": [],
            },
            _macro_worker=mock.Mock(),
        )
        with mock.patch("main.threading.Thread") as thread:
            main.MainWindow._next_macro_step(fake)
        self.assertEqual(fake._macro_context["index"], 1)
        self.assertEqual(
            thread.call_args.kwargs["target"], fake._macro_worker,
        )
        self.assertEqual(thread.call_args.kwargs["args"], (step, 1))
        thread.return_value.start.assert_called_once()

    def test_facts_and_contact_utterances_bypass_cloud_macro_generator(self):
        import main
        for phrase, action in (
            (MARS, "research_notepad_facts"),
            (DISCORD, "discord_open_dm"),
        ):
            with self.subTest(phrase=phrase):
                fake = types.SimpleNamespace(
                    _closed=False,
                    online_planner=mock.Mock(),
                    direct_macro_ready=types.SimpleNamespace(emit=mock.Mock()),
                )
                main.MainWindow._direct_macro_worker(fake, phrase)
                fake.online_planner.plan_macro.assert_not_called()
                sent = fake.direct_macro_ready.emit.call_args.args
                self.assertEqual(sent[1]["steps"][0]["action"], action)
                self.assertEqual(sent[2], "")


class DiscordNavigationTests(unittest.TestCase):
    def test_quick_switcher_may_close_without_opening_chat_retry_verified(self):
        pyauto = types.SimpleNamespace(hotkey=mock.Mock())
        planner = mock.Mock()
        capture = mock.Mock(hwnd=42)
        with (
            mock.patch.dict(sys.modules, {"pyautogui": pyauto}),
            mock.patch("luxai.discord_navigation._ensure_discord_visible",
                       return_value=42),
            mock.patch("luxai.discord_navigation.focus_discord"),
            mock.patch("luxai.discord_search_guard.verified_discord_search",
                       return_value=capture) as search,
            mock.patch("luxai.visual_click.capture_window", return_value=capture) as shot,
            mock.patch("luxai.desktop_actions._type_unicode_windows") as write,
            mock.patch("luxai.discord_navigation.locate_visible_contact",
                       side_effect=[
                           None, VisibleContact("Старый Бог", (220, 150)),
                           VisibleContact("Старый Бог", (120, 400)),
                       ]) as locate,
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.discord_navigation._chat_header_ok",
                       side_effect=[ValueError("not opened"), capture]) as verify,
            mock.patch("luxai.discord_navigation.time.sleep"),
        ):
            result = open_discord_contact(planner, "Старый Бог")
        self.assertIn("открыт и проверен", result)
        self.assertEqual(click.call_count, 2)
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(locate.call_count, 3)
        self.assertGreaterEqual(shot.call_count, 2)
        search.assert_called_once()
        self.assertEqual(search.call_args.args[:3],
                         (planner, 42, "@Старый Бог"))
        write.assert_not_called()

    def test_declined_mismatching_contact_is_never_clicked(self):
        pyauto = types.SimpleNamespace(hotkey=mock.Mock())
        with (
            mock.patch.dict(sys.modules, {"pyautogui": pyauto}),
            mock.patch("luxai.discord_navigation._ensure_discord_visible",
                       return_value=42),
            mock.patch("luxai.discord_navigation.focus_discord"),
            mock.patch("luxai.visual_click.capture_window"),
            mock.patch("luxai.discord_navigation.locate_visible_contact",
                       return_value=VisibleContact("OtherName", (220, 200))),
            mock.patch("luxai.visual_click.click_visual_target") as click,
        ):
            with self.assertRaisesRegex(ValueError, "не подтверждён"):
                open_discord_contact(
                    mock.Mock(), "Старый Бог",
                    confirm_candidate=lambda spoken, shown: False,
                )
        click.assert_not_called()


class FactsWorkflowTests(unittest.TestCase):
    def test_three_sentences_are_sourced_not_made_up(self):
        sample = {"query": {"pages": [{
            "title": "Марс (планета)",
            "extract": (
                "Марс является четвёртой планетой от Солнца. "
                "Его называют красной планетой из-за цвета поверхности. "
                "У Марса есть два небольших спутника. "
                "Четвёртое предложение здесь не должно появиться."
            ),
        }]}}
        response = mock.MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.read.return_value = json.dumps(
            sample, ensure_ascii=False
        ).encode("utf-8")
        with mock.patch(
            "luxai.research_notepad.urllib.request.urlopen",
            return_value=response,
        ):
            facts, source = _research_three_facts("Марс")
        self.assertEqual(len(facts.splitlines()), 3)
        self.assertIn("четвёртой", facts)
        self.assertNotIn("Четвёртое предложение", facts)
        self.assertIn("wikipedia", source)
        self.assertLessEqual(len(facts.encode("utf-16-le")) // 2, 350)

    def test_failed_source_has_no_fabricated_facts(self):
        response = mock.MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.read.return_value = (
            b'{"query":{"pages":[]}}'
        )
        with mock.patch("luxai.research_notepad.urllib.request.urlopen",
                        return_value=response):
            with self.assertRaises(ValueError):
                _research_three_facts("Марс")

    def test_focus_and_copy_only_after_verified_notepad(self):
        pyauto = types.SimpleNamespace(hotkey=mock.Mock())
        with (
            mock.patch.dict(sys.modules, {"pyautogui": pyauto}),
            mock.patch("luxai.research_notepad._research_three_facts",
                       return_value=("1. Fact A\n2. Fact B\n3. Fact C", "source")),
            mock.patch("luxai.windows_apps.launch_installed_app",
                       return_value=(True, "opened")),
            mock.patch("luxai.research_notepad._focus_notepad_window",
                       return_value=55) as focus,
            mock.patch("luxai.desktop_actions._type_unicode_windows") as typing,
            mock.patch("luxai.screen_interact._foreground_hwnd",
                       return_value=55),
            mock.patch("luxai.research_notepad.time.sleep"),
        ):
            answer = write_researched_facts_to_notepad("Марс")
        self.assertEqual(focus.call_count, 2)
        typing.assert_called_once()
        self.assertEqual(
            [x.args for x in pyauto.hotkey.call_args_list],
            [("ctrl", "n"), ("ctrl", "a"), ("ctrl", "c")],
        )
        self.assertIn("скопированы", answer)


if __name__ == "__main__":
    unittest.main()
