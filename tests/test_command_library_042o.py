"""0.4.2o: app icons, a separate Discord group and Discord buttons without the cloud."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from luxai import discord_audio  # noqa: E402
from luxai.command_registry import CommandRegistry, checked_command, discord_targets  # noqa: E402
from luxai.default_commands import DISCORD_COMMANDS  # noqa: E402


class CountTests(unittest.TestCase):
    def test_plurals(self):
        from luxai.ui_commands import count_label
        self.assertEqual([count_label(n, "ru") for n in (1, 3, 5, 11, 21, 34)],
                         ["1 команда", "3 команды", "5 команд", "11 команд", "21 команда", "34 команды"])
        self.assertEqual([count_label(n, "ro") for n in (1, 7, 20)], ["1 comandă", "7 comenzi", "20 de comenzi"])
        self.assertEqual([count_label(n, "en") for n in (1, 2)], ["1 command", "2 commands"])


class DiscordCommandTests(unittest.TestCase):
    def test_every_discord_command_is_valid_and_offline(self):
        self.assertGreaterEqual(len(DISCORD_COMMANDS), 30)
        for entry in DISCORD_COMMANDS:
            checked = checked_command(entry, builtin=True)
            self.assertEqual(checked["action"], "discord_key")
            self.assertIn(checked["target"], discord_targets())
        targets = {entry["target"] for entry in DISCORD_COMMANDS}
        self.assertTrue({"mic_off", "mic_on", "sound_off", "sound_on", "answer_call"} <= targets)

    def test_unknown_discord_target_is_refused(self):
        bad = dict(DISCORD_COMMANDS[0], target="ctrl+alt+del")
        with self.assertRaises(ValueError):
            checked_command(bad, builtin=True)

    def test_phrases_match_the_command(self):
        registry = CommandRegistry(os.path.join(tempfile.mkdtemp(), "c.json"))
        self.assertEqual(registry.match("выключи микрофон в дискорде", "Jarvis")["target"], "mic_off")
        self.assertEqual(registry.match("включи наушники в дискорде", "Jarvis")["target"], "sound_on")


class AudioTests(unittest.TestCase):
    def setUp(self):
        patches = [mock.patch("luxai.windows_control.running_pids", return_value=[1]),
                   mock.patch("luxai.discord_window_state.find_discord_window", return_value=5)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_already_in_the_wanted_state(self):
        with mock.patch.object(discord_audio, "read_buttons", return_value={"mic": (object(), True)}), \
                mock.patch.object(discord_audio, "_toggle") as toggle:
            self.assertIn("Уже было так", discord_audio.set_discord_audio("mic", "off", "ru"))
        toggle.assert_not_called()

    def test_toggles_and_verifies(self):
        states = iter([{"mic": ("e", False)}, {"mic": ("e", True)}])
        with mock.patch.object(discord_audio, "read_buttons", side_effect=lambda *a, **k: next(states)), \
                mock.patch.object(discord_audio, "_toggle", return_value=True) as toggle, \
                mock.patch.object(discord_audio.time, "sleep"):
            self.assertEqual(discord_audio.set_discord_audio("mic", "off", "ru"), "Микрофон Discord выключен.")
        toggle.assert_called_once()

    def test_unreadable_state_returns_none(self):
        with mock.patch.object(discord_audio, "read_buttons", return_value={}):
            self.assertIsNone(discord_audio.set_discord_audio("deaf", "off", "ru"))

    def test_button_names_are_classified(self):
        self.assertEqual(discord_audio._classify("Mute"), "mic")
        self.assertEqual(discord_audio._classify("Deafen"), "deaf")
        self.assertEqual(discord_audio._classify("Откл. микрофон"), "mic")
        self.assertEqual(discord_audio._classify("Откл. звук"), "deaf")
        self.assertIsNone(discord_audio._classify("User Settings"))
        # The real names of the user's Russian Discord account bar (logs/discord_buttons.txt, 0.4.2q).
        self.assertEqual(discord_audio._classify("Заглушить"), "mic")
        self.assertEqual(discord_audio._classify("Откл. звук"), "deaf")
        self.assertIsNone(discord_audio._classify("Настройки ввода"))
        self.assertIsNone(discord_audio._classify("Настройки пользователя"))


class LibraryViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_discord_is_a_separate_group_with_icons(self):
        from luxai.icons import ICON_APP_ROLE
        from luxai.ui_commands import CommandsPage
        page = CommandsPage(CommandRegistry(os.path.join(tempfile.mkdtemp(), "c.json")))
        self.addCleanup(page.deleteLater)
        tops = [page.tree.topLevelItem(i) for i in range(page.tree.topLevelItemCount())]
        discord = next(item for item in tops if "Discord" in item.text(0))
        self.assertEqual(discord.data(0, ICON_APP_ROLE), "discord")
        self.assertEqual(discord.childCount(), len(DISCORD_COMMANDS) + 1)  # + «open Discord»
        defaults = tops[0]
        groups = [defaults.child(i) for i in range(defaults.childCount())]
        self.assertFalse(any("Discord" in group.text(0) for group in groups))
        self.assertEqual(groups[0].data(0, ICON_APP_ROLE), "windows")
        self.assertFalse(groups[0].icon(0).isNull())


class DevelopmentFileTests(unittest.TestCase):
    def test_git_files_stay_on_github(self):
        import Update
        for name in (".gitattributes", ".gitignore", "manifest.example.json"):
            self.assertTrue(Update.is_development_file(Path(name)), name)
        self.assertFalse(Update.is_development_file(Path("README_RU.txt")))
        self.assertFalse((ROOT / ".txt").exists())

    def test_readme_in_three_languages(self):
        version = (ROOT / "version.txt").read_text(encoding="utf-8").strip()
        for name in ("README_RO.txt", "README_RU.txt", "README_EN.txt"):
            self.assertIn(version, (ROOT / name).read_text(encoding="utf-8").splitlines()[0], name)


if __name__ == "__main__":
    unittest.main()
