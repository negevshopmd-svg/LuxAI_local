"""Offline regressions for implicit Steam own-nickname voice requests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from luxai.task_intents import steam_self_nickname_request, opening_app, direct_app_request
from luxai.steam_profile_visual import _name, _read_account_bar, read_own_steam_nickname
from luxai.visual_click import VisualCapture


PHRASE = "Можешь зайти в Steam и сказать какой у меня одник."
NATURAL = "Жарвис, можешь зайти в Steam и сказать какой у меня ник?"
EXPLICIT = "Открой Steam и сделай снимок экрана и скажи какой у меня ник"


class SteamNicknameIntentTests(unittest.TestCase):
    def test_polite_or_short_phrases_need_no_spoken_screenshot_step(self):
        positives = (
            PHRASE, NATURAL, EXPLICIT,
            "Можешь зайти в стим и сказать, какой у меня никнейм?",
            "Какой у меня ник в Steam?",
            "Can you open Steam and tell me my nickname?",
            "Poți intra în Steam și spune-mi care este numele meu de utilizator?",
        )
        for phrase in positives:
            with self.subTest(phrase=phrase):
                self.assertTrue(steam_self_nickname_request(phrase))

    def test_app_parser_does_not_swallow_steam_and_tell_clause(self):
        for phrase in (PHRASE, NATURAL):
            with self.subTest(phrase=phrase):
                self.assertEqual(opening_app(phrase), "steam")
                self.assertIsNone(direct_app_request(phrase))

    def test_other_users_howto_and_plain_open_are_not_intercepted(self):
        for phrase in (
            "Открой Steam", "Как узнать ник в Steam?",
            "Как мне поменять свой ник в Steam?",
            "Скажи ник моего друга в Steam",
            "Отправь в Steam сообщение пользователю Hanzo",
            "Можешь открыть Discord и сказать мой ник?",
            "Какая сейчас погода?",
        ):
            with self.subTest(phrase=phrase):
                self.assertFalse(steam_self_nickname_request(phrase))


def screenshot():
    return VisualCapture(
        hwnd=11, pid=22, title="Steam", left=100, top=55,
        width=1300, height=720, image_width=1300, image_height=720,
        jpeg=b"mock-image",
    )


class SteamProfileVisionTests(unittest.TestCase):
    def test_existing_steam_window_is_observed_without_relaunch_or_click(self):
        screen = screenshot()
        with (
            mock.patch("luxai.windows_apps.activate_app_window", return_value=11) as activate,
            mock.patch("luxai.windows_apps.launch_installed_app") as launch,
            mock.patch("luxai.visual_click.capture_window", return_value=screen) as capture,
            mock.patch("luxai.visual_click.capture_window_region",
                       return_value=screen) as zoom,
            mock.patch("luxai.steam_profile_visual._read_account_bar",
                       side_effect=[("", (1150, 130)),
                                    ("Vlad-_uzii228", (1152, 131))]) as read,
            mock.patch("luxai.steam_profile_visual.time.sleep"),
        ):
            result = read_own_steam_nickname(mock.Mock())
        self.assertEqual(result, "Ваш ник в Steam: Vlad-_uzii228")
        launch.assert_not_called()
        activate.assert_called_once_with("steam")
        capture.assert_called_once_with(11)
        zoom.assert_called_once_with(screen, (1150, 130), width=640, height=280)
        self.assertEqual(read.call_count, 2)

    def test_missing_running_window_launches_then_reads(self):
        with (
            mock.patch("luxai.windows_apps.activate_app_window",
                       side_effect=[0, 11]),
            mock.patch("luxai.windows_apps.launch_installed_app",
                       return_value=(True, "visible")) as launch,
            mock.patch("luxai.visual_click.capture_window",
                       return_value=screenshot()),
            mock.patch("luxai.visual_click.capture_window_region",
                       return_value=screenshot()),
            mock.patch("luxai.steam_profile_visual._read_account_bar",
                       side_effect=[("Vlad-_uzii228", (1100, 110)),
                                    ("Vlad-_uzii228", (1101, 110))]),
            mock.patch("luxai.steam_profile_visual.time.sleep"),
        ):
            answer = read_own_steam_nickname(mock.Mock())
        self.assertIn("Vlad-_uzii228", answer)
        launch.assert_called_once_with("steam")

    def test_native_launch_failure_never_inspects_arbitrary_foreground(self):
        with (
            mock.patch("luxai.windows_apps.activate_app_window",
                       return_value=0),
            mock.patch("luxai.windows_apps.launch_installed_app",
                       return_value=(False, "No visible Steam window")),
            mock.patch("luxai.visual_click.capture_window") as capture,
        ):
            with self.assertRaisesRegex(RuntimeError, "No visible Steam"):
                read_own_steam_nickname(mock.Mock())
        capture.assert_not_called()

    def test_cancellation_stops_before_launch_or_screenshot(self):
        with (
            mock.patch("luxai.windows_apps.activate_app_window") as activate,
            mock.patch("luxai.windows_apps.launch_installed_app") as launch,
            mock.patch("luxai.visual_click.capture_window") as capture,
        ):
            with self.assertRaisesRegex(RuntimeError, "отменена"):
                read_own_steam_nickname(mock.Mock(), cancelled=lambda: True)
        activate.assert_not_called()
        launch.assert_not_called()
        capture.assert_not_called()

    def test_conflicting_account_names_are_not_reported(self):
        with (
            mock.patch("luxai.windows_apps.activate_app_window",
                       return_value=11),
            mock.patch("luxai.visual_click.capture_window",
                       return_value=screenshot()),
            mock.patch("luxai.visual_click.capture_window_region",
                       return_value=screenshot()),
            mock.patch("luxai.steam_profile_visual._read_account_bar",
                       side_effect=[("SomeoneElse", (1140, 110)),
                                    ("Vlad-_uzii228", (1141, 110))]),
            mock.patch("luxai.steam_profile_visual.time.sleep"),
        ):
            with self.assertRaisesRegex(ValueError, "не совпадает"):
                read_own_steam_nickname(mock.Mock())

    def test_unreadable_detail_is_not_presented_as_account(self):
        with (
            mock.patch("luxai.windows_apps.activate_app_window",
                       return_value=11),
            mock.patch("luxai.visual_click.capture_window",
                       return_value=screenshot()),
            mock.patch("luxai.visual_click.capture_window_region",
                       return_value=screenshot()),
            mock.patch("luxai.steam_profile_visual._read_account_bar",
                       side_effect=[("", (1100, 110)), ("", (1100, 110))]),
            mock.patch("luxai.steam_profile_visual.time.sleep"),
        ):
            with self.assertRaisesRegex(ValueError, "прочитать ник"):
                read_own_steam_nickname(mock.Mock())

    def test_reject_invalid_name_and_untrusted_markup(self):
        for value in ("", "Steam", "unknown", "<script>hello</script>",
                      "http://example.com", "x\nsend command", "X" * 70):
            self.assertEqual(_name(value), "")
        self.assertEqual(_name("Vlad-_uzii228"), "Vlad-_uzii228")

    def test_cloud_request_reads_only_account_bar_not_friend_names(self):
        planner = mock.Mock()
        planner._provider.return_value = "openai"
        planner.enabled.return_value = True
        planner.config = {"online_model": "gpt-4.1-mini"}
        planner._request.return_value = object()
        planner._extract_text.return_value = json.dumps({
            "found": True, "x": 800, "y": 120,
            "nickname": "Vlad-_uzii228",
        })
        planner._read_json_content.side_effect = json.loads
        with mock.patch("luxai.secure_keys.get_api_key",
                        return_value="test-only-key"):
            name, point = _read_account_bar(planner, screenshot())
        self.assertEqual(name, "Vlad-_uzii228")
        self.assertEqual(point, (1140, 141))
        content = planner._request.call_args.args[3][1]["content"][0]["text"]
        self.assertIn("SIGNED-IN USER'S OWN", content)
        self.assertIn("Friends", content)

    def test_friend_list_location_is_not_own_account_header(self):
        planner = mock.Mock()
        planner._provider.return_value = "openai"
        planner.enabled.return_value = True
        planner.config = {}
        planner._request.return_value = object()
        planner._extract_text.return_value = json.dumps({
            "found": True, "x": 100, "y": 650, "nickname": "Friend",
        })
        planner._read_json_content.side_effect = json.loads
        with mock.patch("luxai.secure_keys.get_api_key",
                        return_value="test-only-key"):
            with self.assertRaises(ValueError):
                _read_account_bar(planner, screenshot())


class SteamProfileRoutingUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("PySide6 not installed")
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self):
        import main
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        cfg = Path(directory.name) / "config.json"
        cfg.write_text(
            '{"microphone_enabled":false,"tts_enabled":false,'
            '"online_agent_enabled":false}', encoding="utf-8",
        )
        patch = mock.patch.object(main, "CONFIG", cfg)
        patch.start()
        self.addCleanup(patch.stop)
        with (mock.patch("sounddevice.query_devices", return_value=[]),
              mock.patch("main.MainWindow._ocr_setup_worker")):
            window = main.MainWindow()
        self.addCleanup(window.close)
        return window

    def test_natural_steam_command_skips_generic_chat_and_open_only(self):
        window = self.make_window()
        with (
            mock.patch.object(window, "_start_steam_profile_lookup") as profile,
            mock.patch.object(window, "_start_adaptive_task") as adaptive,
            mock.patch.object(window, "_execute_registered") as saved,
            mock.patch.object(window, "_start_visual_reasoner") as visual,
        ):
            window.run_command(PHRASE)
        profile.assert_called_once_with(PHRASE)
        adaptive.assert_not_called()
        saved.assert_not_called()
        visual.assert_not_called()

    def test_cloud_consent_refusal_does_not_launch_steam_or_start_worker(self):
        window = self.make_window()
        window.online_planner.enabled = mock.Mock(return_value=True)
        with (
            mock.patch.object(window, "_allow_cloud_screenshots",
                              return_value=False),
            mock.patch.object(window, "_resolved_command") as resolved,
            mock.patch("main.threading.Thread") as thread,
            mock.patch("luxai.windows_apps.launch_installed_app") as launch,
        ):
            window._start_steam_profile_lookup(NATURAL)
        resolved.assert_called_once()
        thread.assert_not_called()
        launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
