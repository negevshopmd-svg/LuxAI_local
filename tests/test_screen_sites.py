"""Website opening and safe screen-button inspection regression tests."""
from __future__ import annotations

import time
import unittest
from unittest import mock

from luxai.online_agent import OnlinePlanner
from luxai.websites import website_plan, normalize_public_website, open_website
from luxai.screen_interact import (
    VisibleButton, ScreenInspection, button_choice, classify_button,
    is_screen_inspection_request, select_unique_button, click_inspected_button,
)


class WebsiteTests(unittest.TestCase):
    def test_russian_youtube_and_common_websites(self):
        samples = {
            "Открой YouTube в браузере": "https://www.youtube.com/",
            "Жарвис, открой ютуб в браузере": "https://www.youtube.com/",
            "Открой, пожалуйста, Ютуб": "https://www.youtube.com/",
            "Открой сайт Википедия": "https://ru.wikipedia.org/",
            "Открой google.com": "https://www.google.com/",
            "Открой https://example.org": "https://example.org/",
            "Open youtube in browser": "https://www.youtube.com/",
            "Deschide YouTube în browser": "https://www.youtube.com/",
            "Открой Github": "https://github.com/",
        }
        for spoken, expected in samples.items():
            with self.subTest(spoken=spoken):
                self.assertEqual(website_plan(spoken), {
                    "action": "open_site", "target": expected, "reply": "",
                })

    def test_do_not_confuse_installed_app_with_website(self):
        self.assertIsNone(website_plan("Открой Discord"))
        self.assertIsNone(website_plan("Открой Visual Studio Code"))
        self.assertIsNone(website_plan("Привет"))
        self.assertIsNone(website_plan("Открой браузер"))

    def test_public_https_validation_rejects_unsafe_urls(self):
        for target in (
            "javascript:alert(1)", "file:///C:/Users/user/test.txt",
            "http://example.org", "https://localhost",
            "https://192.168.1.1", "https://internal.local",
            "https://example.org:8080/", "https://user:pass@example.org",
            "https://example.org/?q=evil", "https://example.org/#fragment",
            "https://example.org/../../malware",
            "https://example.org:wrong/",
        ):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    normalize_public_website(target)

    def test_cloud_can_propose_safe_site_not_shell(self):
        parsed = OnlinePlanner._validate({
            "action": "open_site", "target": "YouTube", "reply": "",
        })
        self.assertEqual(parsed["target"], "https://www.youtube.com/")
        self.assertIsNone(OnlinePlanner._validate({
            "action": "open_site", "target": "file:///secret", "reply": "",
        }))

    def test_browser_launch_result_is_truthful(self):
        with mock.patch("luxai.websites.webbrowser.open", return_value=True) as browser:
            success, message = open_website("youtube")
        self.assertTrue(success)
        self.assertIn("Отправил браузеру", message)
        self.assertIn("Проверьте, загрузилась", message)
        browser.assert_called_once_with("https://www.youtube.com/", new=2)
        with mock.patch("luxai.websites.webbrowser.open", return_value=False):
            self.assertFalse(open_website("youtube")[0])

    def test_cloud_timeout_is_at_least_35_seconds(self):
        planner = OnlinePlanner({
            "online_provider": "gemini",
            "online_agent_enabled": True,
            "online_timeout": 5,  # preserved from an old config.json
        })
        response = {"choices": [{"message": {"content": '{"action":"reply","target":"","reply":"Привет"}'}}]}
        with mock.patch.object(planner, "enabled", return_value=True), mock.patch(
            "luxai.online_agent.get_api_key", return_value="fake-test-key"
        ), mock.patch.object(planner, "_request", return_value=response) as call:
            self.assertEqual(planner.plan("Привет")["reply"], "Привет")
        self.assertGreater(call.call_args.args[4], 30)

    def test_cloud_timeout_can_be_extended_to_120(self):
        planner = OnlinePlanner({
            "online_provider": "gemini",
            "online_agent_enabled": True,
            "online_timeout": 120,
        })
        response = {"choices": [{"message": {"content": '{"action":"reply","target":"","reply":"Привет"}'}}]}
        with mock.patch.object(planner, "enabled", return_value=True), mock.patch(
            "luxai.online_agent.get_api_key", return_value="fake-test-key"
        ), mock.patch.object(planner, "_request", return_value=response) as call:
            planner.plan("Привет")
        self.assertEqual(call.call_args.args[4], 120)


class ScreenButtonTests(unittest.TestCase):
    @staticmethod
    def _snapshot(buttons):
        return ScreenInspection(
            hwnd=142, pid=8765, title="Some Desktop Program",
            buttons=tuple(buttons), captured=time.monotonic(),
        )

    def test_voice_yes_no_are_explicit_only(self):
        self.assertEqual(button_choice("Жарвис, нажми да"), "yes")
        self.assertEqual(button_choice("Нажми на кнопку Нет."), "no")
        self.assertEqual(button_choice("click yes"), "yes")
        self.assertIsNone(button_choice("Он говорил да вчера"))
        self.assertIsNone(button_choice("В ответе было слово нет"))
        self.assertTrue(is_screen_inspection_request("Покажи кнопки на экране"))
        self.assertTrue(is_screen_inspection_request("Жарвис, найди кнопку да"))
        self.assertFalse(is_screen_inspection_request("Привет"))

    def test_localized_yes_no_labels(self):
        for label in ("Да", "Yes", "&Yes", "Accept", "Confirm"):
            self.assertEqual(classify_button(label), "yes")
        for label in ("Нет", "No", "Отмена", "Cancel", "Nu"):
            self.assertEqual(classify_button(label), "no")

    def test_exactly_one_accessible_button_required(self):
        snap = self._snapshot([
            VisibleButton("Да", (10, 10, 60, 40)),
            VisibleButton("Нет", (70, 10, 120, 40)),
        ])
        self.assertEqual(select_unique_button(snap, "yes").center, (35, 25))
        with self.assertRaises(ValueError):
            select_unique_button(snap, "other")
        duplicate = self._snapshot([
            VisibleButton("Да", (10, 10, 60, 40)),
            VisibleButton("Yes", (200, 20, 260, 60)),
        ])
        with self.assertRaisesRegex(ValueError, "несколько"):
            select_unique_button(duplicate, "yes")
        with self.assertRaisesRegex(ValueError, "нет доступной"):
            select_unique_button(self._snapshot(()), "yes")

    def test_stale_snapshot_cannot_click(self):
        stale = ScreenInspection(
            hwnd=142, pid=8765, title="Some Desktop Program",
            buttons=(VisibleButton("Да", (10, 10, 60, 40)),),
            captured=time.monotonic() - 150,
        )
        with mock.patch("luxai.screen_interact._valid_external_window") as ui:
            result = click_inspected_button(stale, "yes", confirm=lambda _: True)
        self.assertIn("устарел", result)
        ui.assert_not_called()

    def test_confirmation_prevents_any_mouse_action(self):
        snap = self._snapshot([VisibleButton("Да", (10, 10, 60, 40))])
        with mock.patch("luxai.screen_interact._valid_external_window",
                        return_value=(8765, "Some Desktop Program")):
            result = click_inspected_button(snap, "yes", confirm=lambda _: False)
        self.assertIn("отменено", result)

    def test_positive_mouse_click_after_same_window_revalidation(self):
        import ctypes
        import sys
        import types

        snap = self._snapshot([VisibleButton("Да", (10, 10, 60, 40))])
        user32 = types.SimpleNamespace(
            SetForegroundWindow=mock.Mock(return_value=True),
            WindowFromPoint=mock.Mock(return_value=142),
        )
        fake_mouse = types.SimpleNamespace(
            moveTo=mock.Mock(), click=mock.Mock()
        )
        with mock.patch.object(ctypes, "windll",
                               types.SimpleNamespace(user32=user32), create=True), mock.patch(
            "luxai.screen_interact._valid_external_window",
            return_value=(8765, "Some Desktop Program")
        ), mock.patch(
            "luxai.screen_interact._foreground_hwnd", return_value=142
        ), mock.patch(
            "luxai.screen_interact._window_pid", return_value=8765
        ), mock.patch(
            "luxai.screen_interact.inspect_screen_buttons",
            return_value=snap
        ), mock.patch(
            "luxai.screen_interact.time.sleep"
        ), mock.patch.dict(sys.modules, {"pyautogui": fake_mouse}):
            result = click_inspected_button(
                snap, "yes", confirm=lambda _: True,
            )
        self.assertIn("Нажал кнопку", result)
        fake_mouse.moveTo.assert_called_once_with(35, 25, duration=0.12)
        fake_mouse.click.assert_called_once_with(35, 25)

    def test_covered_button_in_another_process_never_clicked(self):
        import ctypes
        import sys
        import types

        snap = self._snapshot([VisibleButton("Да", (10, 10, 60, 40))])
        user32 = types.SimpleNamespace(
            SetForegroundWindow=mock.Mock(return_value=True),
            WindowFromPoint=mock.Mock(return_value=143),
        )
        fake_mouse = types.SimpleNamespace(moveTo=mock.Mock(), click=mock.Mock())
        with mock.patch.object(
            ctypes, "windll",
            types.SimpleNamespace(user32=user32), create=True,
        ), mock.patch(
            "luxai.screen_interact._valid_external_window",
            return_value=(8765, "Some Desktop Program")
        ), mock.patch(
            "luxai.screen_interact._foreground_hwnd",
            return_value=142
        ), mock.patch(
            "luxai.screen_interact._window_pid",
            return_value=9999  # Jarvis or another window overlays the target
        ), mock.patch(
            "luxai.screen_interact.inspect_screen_buttons",
            return_value=snap
        ), mock.patch(
            "luxai.screen_interact.time.sleep"
        ), mock.patch.dict(sys.modules, {"pyautogui": fake_mouse}):
            result = click_inspected_button(
                snap, "yes", confirm=lambda _: True,
            )
        self.assertIn("закрыта другим окном", result)
        fake_mouse.moveTo.assert_not_called()
        fake_mouse.click.assert_not_called()

    def test_button_moved_after_confirmation_prevents_click(self):
        import ctypes
        import sys
        import types

        snap = self._snapshot([VisibleButton("Да", (10, 10, 60, 40))])
        moved = self._snapshot([VisibleButton("Да", (300, 300, 360, 340))])
        fake_mouse = types.SimpleNamespace(click=mock.Mock())
        with mock.patch.object(
            ctypes, "windll",
            types.SimpleNamespace(user32=types.SimpleNamespace(
                SetForegroundWindow=mock.Mock(return_value=True),
                WindowFromPoint=mock.Mock(return_value=142),
            )),
            create=True,
        ), mock.patch(
            "luxai.screen_interact._valid_external_window",
            return_value=(8765, "Some Desktop Program")
        ), mock.patch(
            "luxai.screen_interact._foreground_hwnd", return_value=142
        ), mock.patch(
            "luxai.screen_interact.inspect_screen_buttons",
            return_value=moved
        ), mock.patch(
            "luxai.screen_interact.time.sleep"
        ), mock.patch.dict(sys.modules, {"pyautogui": fake_mouse}):
            result = click_inspected_button(
                snap, "yes", confirm=lambda _: True,
            )
        self.assertIn("сместилась", result)
        fake_mouse.click.assert_not_called()

    def test_changed_window_rejected_before_click(self):
        snap = self._snapshot([VisibleButton("Да", (10, 10, 60, 40))])
        with mock.patch("luxai.screen_interact._valid_external_window",
                        return_value=(8766, "Different Desktop Program")):
            result = click_inspected_button(snap, "yes", confirm=lambda _: True)
        self.assertIn("изменилось", result)


if __name__ == "__main__":
    unittest.main()
