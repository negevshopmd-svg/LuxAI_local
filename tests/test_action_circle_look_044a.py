"""0.4.4a: the action circle's new look — round buttons in group colours, a hub with the full name, a short
opening zoom, labels in up to two lines."""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont, QFontMetricsF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from luxai import action_circle as ac  # noqa: E402


class LookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def menu(self, items=None, **kwargs):
        from luxai.ui_convert_circle import RadialMenu
        items = items if items is not None else ac.slots({"items": 10}, [], "ro")
        widget = RadialMenu(items, "Cerc", **kwargs)
        self.addCleanup(widget.deleteLater)
        return widget

    def test_groups_have_their_colours_and_commands_the_theme_colour(self):
        widget = self.menu(tint=ac.tint, accent="#3978f6")
        colours = {widget.items[i][0]: widget._color(i).name() for i in range(len(widget.items))}
        self.assertEqual(colours["search_selection"], "#2dd4bf")
        self.assertEqual(colours["win_close"], "#f87171")
        self.assertEqual(colours["media_play_pause"], "#f472b6")
        command = self.menu([("cmd:x", "X", "zap")], tint=ac.tint, accent="#3978f6")
        self.assertEqual(command._color(0).name(), "#3978f6")

    def test_a_broken_tint_falls_back_to_the_theme_colour(self):
        widget = self.menu([("a", "A", "")], tint=lambda _id: 1 / 0, accent="#123456")
        self.assertEqual(widget._color(0).name(), "#123456")
        widget = self.menu([("a", "A", "")], tint=lambda _id: "not a colour", accent="#123456")
        self.assertEqual(widget._color(0).name(), "#123456")

    def test_commands_get_the_icon_of_what_they_do(self):
        self.assertEqual(ac.command_icon({"action": "open_website"}), "globe")
        self.assertEqual(ac.command_icon({"action": "launch_game"}), "gamepad-2")
        self.assertEqual(ac.command_icon({"action": "something new"}), "zap")
        items = ac.slots({"items": 4}, [{"id": "u1", "title": "YouTube", "enabled": True, "action": "open_website"}], "en")
        self.assertEqual(items[0], ("cmd:u1", "YouTube", "globe"))

    def test_the_pointed_button_grows_smoothly(self):
        widget = self.menu()
        widget.current = 2
        for _ in range(3):
            widget._animate()
        self.assertTrue(0.5 < widget._hover[2] < 1.0)
        for _ in range(30):
            widget._animate()
        self.assertEqual(widget._hover[2], 1.0)
        widget.current = -1
        for _ in range(30):
            widget._animate()
        self.assertEqual(widget._hover, [0.0] * len(widget.items))

    def test_labels_take_at_most_two_lines(self):
        from luxai.ui_convert_circle import label_lines
        font = QFont()
        font.setPixelSize(11)
        metrics = QFontMetricsF(font)
        lines = label_lines("Închide fereastra activă acum imediat", metrics, 70)
        self.assertLessEqual(len(lines), 2)
        self.assertTrue(lines[-1].endswith("…"))
        self.assertEqual(label_lines("Discord", metrics, 200), ["Discord"])
        self.assertEqual(label_lines("", metrics, 70), [])

    def test_painting_while_opening_and_when_open_in_both_themes(self):
        for theme in ("dark", "light"):
            widget = self.menu(theme=theme, tint=ac.tint)
            widget.current = 3
            self.assertFalse(widget.grab().isNull())  # opening
            widget._opened = time.monotonic() - 5
            self.assertFalse(widget.grab().isNull())  # open

    def test_every_group_icon_exists(self):
        from luxai.icons import ASSET_DIR
        for name in ac.ICONS.values():
            self.assertTrue((ASSET_DIR / "lucide" / f"{name}.svg").is_file(), name)


if __name__ == "__main__":
    unittest.main()
