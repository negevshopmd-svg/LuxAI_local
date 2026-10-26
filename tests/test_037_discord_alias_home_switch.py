"""0.3.7: strict ASR alias calling and reliable home control switches."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from luxai.discord_contact_vision import exact_voice_transliteration
from luxai.discord_navigation import open_discord_contact
from luxai.discord_call_visual import call_discord_user
from luxai.visual_click import VisualCapture


def shot():
    return VisualCapture(
        hwnd=22, pid=44, title="Discord", left=0, top=0,
        width=1522, height=990, image_width=1522, image_height=990,
        jpeg=b"mock",
    )


class StrictDiscordAliasTests(unittest.TestCase):
    def test_russian_asr_hanzo_equals_exact_latin_nickname(self):
        self.assertTrue(exact_voice_transliteration("Ханзо", "Hanzo"))
        self.assertTrue(exact_voice_transliteration("ханзо", "Khanzo"))
        self.assertTrue(exact_voice_transliteration("Hanzo", "Ханзо"))
        self.assertTrue(exact_voice_transliteration("@ХАНЗО", "@hanzo"))
        self.assertTrue(exact_voice_transliteration("Алекс", "Aleks"))

    def test_never_match_lookalikes_partial_or_unrelated_users(self):
        for heard, visible in (
            ("Ханзо", "Hanzo123"), ("Ханзо", "Hanz0"),
            ("Ханзо", "Handzo"), ("Ханзо", "HanzoX"),
            ("Ханзо", "GhostOX"), ("Аня", "Anya"),
            ("Hanzo", "Hanzo"), ("Ханзо", "Ханзо"),
            ("Ха", "Ha"), ("Пользователь Ханзо", "Hanzo"),
            ("Ханзо", "Hanzo from Friends"), ("Ханзо", "Hanzo\nmessage"),
            ("Позвони Ханзо", "Hanzo"), ("Ханзо", "Hanzó"),
        ):
            with self.subTest(heard=heard, visible=visible):
                self.assertFalse(exact_voice_transliteration(heard, visible))

    def test_alias_is_not_applied_to_existing_strict_discord_identity_check(self):
        from luxai.discord_contact_vision import same_discord_name
        self.assertFalse(same_discord_name("Ханзо", "Hanzo"))


class DiscordNavigationAliasTests(unittest.TestCase):
    def test_verified_visible_name_only_available_after_dm_header_check(self):
        from luxai.discord_contact_vision import VisibleContact
        identity = []
        screen = shot()
        with (
            mock.patch("luxai.discord_navigation._ensure_discord_visible", return_value=22),
            mock.patch("luxai.discord_navigation.focus_discord"),
            mock.patch("luxai.visual_click.capture_window", return_value=screen),
            mock.patch("luxai.discord_navigation.locate_visible_contact",
                       return_value=VisibleContact("Hanzo", (600, 300))),
            mock.patch("luxai.discord_navigation._chat_header_ok",
                       return_value=screen) as header,
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.discord_navigation.time.sleep"),
        ):
            result = open_discord_contact(
                mock.Mock(), "Ханзо",
                confirm_candidate=exact_voice_transliteration,
                verified_identity=identity.append,
            )
        self.assertEqual(identity, ["Hanzo"])
        header.assert_called_once_with(mock.ANY, 22, "Hanzo")
        click.assert_called_once()
        self.assertIn("Hanzo", result)

    def test_header_mismatch_does_not_authorize_identity(self):
        from luxai.discord_contact_vision import VisibleContact
        identity = []
        with (
            mock.patch("luxai.discord_navigation._ensure_discord_visible", return_value=22),
            mock.patch("luxai.discord_navigation.focus_discord"),
            mock.patch("luxai.visual_click.capture_window", return_value=shot()),
            mock.patch("luxai.discord_navigation.locate_visible_contact",
                       side_effect=[
                           VisibleContact("Hanzo", (600, 300)), None,
                       ]),
            mock.patch("luxai.discord_navigation._chat_header_ok",
                       side_effect=ValueError("Wrong DM")),
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.discord_navigation.time.sleep"),
        ):
            with self.assertRaises(ValueError):
                open_discord_contact(
                    mock.Mock(), "Ханзо",
                    confirm_candidate=exact_voice_transliteration,
                    verified_identity=identity.append,
                )
        self.assertEqual(identity, [])
        click.assert_called_once()

    def test_unrelated_account_never_clicked_even_if_visually_found(self):
        from luxai.discord_contact_vision import VisibleContact
        with (
            mock.patch("luxai.discord_navigation._ensure_discord_visible", return_value=22),
            mock.patch("luxai.discord_navigation.focus_discord"),
            mock.patch("luxai.visual_click.capture_window", return_value=shot()),
            mock.patch("luxai.discord_navigation.locate_visible_contact",
                       return_value=VisibleContact("Hanzo_2", (600, 300))),
            mock.patch("luxai.visual_click.click_visual_target") as click,
        ):
            with self.assertRaisesRegex(ValueError, "другой никнейм"):
                open_discord_contact(
                    mock.Mock(), "Ханзо",
                    confirm_candidate=exact_voice_transliteration,
                )
        click.assert_not_called()

    def test_call_uses_verified_latin_identity_in_all_subsequent_screen_checks(self):
        captured = shot()
        def navigate(_planner, _username, *, verified_identity=None, **kwargs):
            self.assertTrue(kwargs["confirm_candidate"]("Ханзо", "Hanzo"))
            verified_identity("Hanzo")
            return "Discord: открыт и проверен чат Hanzo"
        with (
            mock.patch("luxai.discord_navigation.open_discord_contact",
                       side_effect=navigate) as open_dm,
            mock.patch("luxai.discord_screen_review._ensure_discord_visible",
                       return_value=22),
            mock.patch("luxai.discord_research.focus_discord"),
            mock.patch("luxai.discord_navigation._chat_header_ok",
                       return_value=captured) as header,
            mock.patch("luxai.discord_call_visual._observe_call_state",
                       side_effect=["idle", "idle", "ringing"]) as state,
            mock.patch("luxai.discord_call_visual._locate_voice_call_button",
                       return_value=(1100, 50)),
            mock.patch("luxai.visual_click.click_visual_target") as click,
            mock.patch("luxai.visual_click.capture_window", return_value=captured),
            mock.patch("luxai.discord_call_visual.time.sleep"),
        ):
            result = call_discord_user(mock.Mock(), "Ханзо")
        self.assertIn("«Hanzo»", result)
        self.assertEqual(header.call_count, 2)
        self.assertEqual([c.args[2] for c in header.call_args_list],
                         ["Hanzo", "Hanzo"])
        self.assertEqual([c.args[2] for c in state.call_args_list],
                         ["Hanzo", "Hanzo", "Hanzo"])
        self.assertEqual(open_dm.call_count, 1)
        click.assert_called_once()

    def test_call_stops_on_unverified_name_and_never_reaches_phone(self):
        with (
            mock.patch("luxai.discord_navigation.open_discord_contact",
                       side_effect=ValueError("Другой никнейм")) as navigate,
            mock.patch("luxai.discord_call_visual._locate_voice_call_button") as phone,
            mock.patch("luxai.visual_click.click_visual_target") as click,
        ):
            with self.assertRaisesRegex(ValueError, "никнейм"):
                call_discord_user(mock.Mock(), "Ханзо")
        navigate.assert_called_once()
        phone.assert_not_called()
        click.assert_not_called()


class HomeToggleClickTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            raise unittest.SkipTest("Qt unavailable")
        cls.app = QApplication.instance() or QApplication([])

    def test_entire_visible_pill_is_clickable_on_first_press(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from luxai.ui_home import ToggleSwitch
        switch = ToggleSwitch(False)
        switch.show()
        self.addCleanup(switch.close)
        changed = []
        switch.toggled.connect(changed.append)
        for point in (QPoint(47, 14), QPoint(7, 14), QPoint(27, 14)):
            before = switch.isChecked()
            QTest.mouseClick(switch, Qt.MouseButton.LeftButton, pos=point)
            self.assertNotEqual(switch.isChecked(), before, point)
        self.assertEqual(len(changed), 3)

    def test_disabled_switch_does_not_accept_click(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from luxai.ui_home import ToggleSwitch
        switch = ToggleSwitch(False)
        switch.show()
        self.addCleanup(switch.close)
        switch.setEnabled(False)
        QTest.mouseClick(switch, Qt.MouseButton.LeftButton, pos=QPoint(47, 14))
        self.assertFalse(switch.isChecked())

    def make_window(self):
        import main
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = Path(tmp.name) / "config.json"
        cfg.write_text(
            '{"microphone_enabled":false,"tts_enabled":false,'
            '"online_agent_enabled":false}', encoding="utf-8",
        )
        patch = mock.patch.object(main, "CONFIG", cfg)
        patch.start()
        self.addCleanup(patch.stop)
        with (mock.patch("sounddevice.query_devices", return_value=[]),
              mock.patch("main.MainWindow._ocr_setup_worker")):
            win = main.MainWindow()
        self.addCleanup(win.close)
        win.show()
        return win

    def test_all_home_control_switches_toggle_at_right_edge_and_save_state(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        window = self.make_window()
        for attribute, config_key, invert in (
            ("home_prefix", "prefix_enabled", False),
            ("home_quiet", "tts_enabled", True),
            ("home_avatar", "ui_animations", False),
            ("home_top", "always_on_top", False),
        ):
            with self.subTest(switch=attribute):
                switch = getattr(window, attribute)
                previous = switch.isChecked()
                QTest.mouseClick(
                    switch, Qt.MouseButton.LeftButton, pos=QPoint(47, 14),
                )
                self.assertEqual(switch.isChecked(), not previous)
                self.assertEqual(
                    window.cfg.get(config_key), previous if invert else not previous,
                )


if __name__ == "__main__":
    unittest.main()
