"""0.4.3o: the seven modules no test named before (shown in orange on the module map).

Each test checks what the user would notice if it broke, not only that the module imports.
"""
from __future__ import annotations

import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QIcon, QKeyEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import QApplication, QWidget


def app():
    return QApplication.instance() or QApplication([])


def key(widget, code, modifiers=Qt.KeyboardModifier.NoModifier):
    widget.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, code, modifiers))


def mouse(kind, x, y):
    point = QPointF(x, y)
    return QMouseEvent(kind, point, point, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)


# -- atomic_io: every settings / data file is written through it ------------------------------------------
class AtomicIoTests(unittest.TestCase):
    def setUp(self):
        from luxai import atomic_io
        self.io = atomic_io
        self.folder = Path(tempfile.mkdtemp())

    def leftovers(self):
        return [p.name for p in self.folder.rglob("*.tmp")]

    def test_writes_into_a_new_folder_and_leaves_no_temporary_file(self):
        target = self.folder / "deep" / "config.json"
        self.io.atomic_write_text(target, '{"language": "ro"} — ă î ș ț')
        self.assertEqual(target.read_text(encoding="utf-8"), '{"language": "ro"} — ă î ș ț')
        self.assertEqual(self.leftovers(), [])

    def test_a_briefly_locked_file_is_retried(self):
        """Antivirus or a reader holding the file for a moment must not lose the save."""
        target = self.folder / "data.json"
        target.write_text("old", encoding="utf-8")
        real = os.replace
        calls = []

        def busy_twice(source, destination):
            calls.append(1)
            if len(calls) <= 2:
                raise PermissionError("in use")
            return real(source, destination)

        with mock.patch.object(self.io.os, "replace", side_effect=busy_twice), \
                mock.patch.object(self.io.time, "sleep"):
            self.io.atomic_write_bytes(target, b"new")
        self.assertEqual(target.read_bytes(), b"new")
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.leftovers(), [])

    def test_a_file_that_stays_locked_keeps_the_old_content(self):
        target = self.folder / "data.json"
        target.write_text("old", encoding="utf-8")
        with mock.patch.object(self.io.os, "replace", side_effect=PermissionError("locked")), \
                mock.patch.object(self.io.time, "sleep"):
            with self.assertRaises(PermissionError):
                self.io.atomic_write_bytes(target, b"new", attempts=3)
        self.assertEqual(target.read_text(encoding="utf-8"), "old")   # never half-written
        self.assertEqual(self.leftovers(), [])                       # the temporary file is cleaned up

    def test_two_writers_never_share_a_temporary_name(self):
        target = self.folder / "data.json"
        names = []
        real = tempfile.mkstemp

        def spy(*args, **kwargs):
            result = real(*args, **kwargs)
            names.append(result[1])
            return result

        with mock.patch.object(self.io.tempfile, "mkstemp", side_effect=spy):
            self.io.atomic_write_text(target, "a")
            self.io.atomic_write_text(target, "b")
        self.assertEqual(len(set(names)), 2)
        self.assertTrue(all(Path(name).parent == self.folder for name in names))  # same folder: atomic rename


# -- voice_presets: which Piper voice is downloaded for each language ----------------------------------------
class VoicePresetTests(unittest.TestCase):
    def test_each_language_has_a_consistent_voice(self):
        from luxai import voice_presets as vp
        self.assertEqual(set(vp.VOICE_PRESETS), {"ru", "ro", "en"})
        for language, preset in vp.VOICE_PRESETS.items():
            with self.subTest(language=language):
                self.assertTrue(preset["id"].startswith(preset["language"] + "-"))
                parts = preset["directory"].split("/")
                self.assertEqual(parts[0], language)
                self.assertEqual(parts[1], preset["language"])
                self.assertIn(parts[2], preset["id"])
                self.assertIn(parts[3], preset["id"])
                self.assertTrue(preset["sha256"] is None or re.fullmatch(r"[0-9a-f]{64}", preset["sha256"]))
        self.assertTrue(vp.PIPER_REPOSITORY.startswith("https://") and vp.PIPER_REPOSITORY.endswith("/"))

    def test_the_voice_engine_uses_these_presets(self):
        from luxai import voice_presets as vp
        from luxai import voices
        self.assertIs(voices.VOICE_PRESETS, vp.VOICE_PRESETS)


# -- app_icons: the icons of the command library ------------------------------------------------------
class AppIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app()

    def setUp(self):
        from luxai import app_icons
        self.icons = app_icons
        app_icons._icons.clear()
        app_icons._paths.clear()
        self.addCleanup(app_icons._icons.clear)
        self.addCleanup(app_icons._paths.clear)

    def test_every_group_has_a_fallback_glyph(self):
        self.assertEqual(set(self.icons.SOURCES), set(self.icons.FALLBACK))
        self.assertTrue(set(self.icons.GROUP_KEYS.values()) <= set(self.icons.SOURCES))

    def test_a_tile_is_drawn_for_every_group_without_installed_programs(self):
        with mock.patch.object(self.icons, "program_path", return_value=None):
            for name in self.icons.SOURCES:
                for theme in ("dark", "light"):
                    with self.subTest(name=name, theme=theme):
                        tile = self.icons.tile_icon(name, theme)
                        self.assertFalse(tile.isNull())
                        self.assertFalse(tile.pixmap(QSize(26, 26)).toImage().isNull())

    def test_tiles_are_cached(self):
        with mock.patch.object(self.icons, "program_path", return_value=None):
            self.assertIs(self.icons.tile_icon("chrome", "dark"), self.icons.tile_icon("chrome", "dark"))
            self.assertIsNot(self.icons.tile_icon("chrome", "dark"), self.icons.tile_icon("chrome", "light"))

    def test_a_failing_program_lookup_does_not_break_the_library(self):
        with mock.patch("luxai.windows_apps.resolve_installed_app", side_effect=OSError("registry")):
            self.assertIsNone(self.icons.program_path("discord"))
        self.assertIsNone(self.icons.program_path("windows"))  # drawn, never looked up

    def test_padded_icon_keeps_the_box_size(self):
        source = QIcon(QPixmap(32, 32))
        padded = self.icons.padded_icon(source, inner=14, size=26)
        self.assertFalse(padded.isNull())
        self.assertEqual(padded.availableSizes()[0], QSize(52, 52))  # 26 px at ratio 2


# -- ui_convert_circle: the converter's radial menu, region picker and crop ----------------------------------
class RadialMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app()

    def menu(self, count=4):
        from luxai.ui_convert_circle import RadialMenu
        widget = RadialMenu([(f"id{i}", f"Item {i}", "") for i in range(count)], "Convert")
        self.addCleanup(widget.deleteLater)
        picked, cancelled = [], []
        widget.picked.connect(picked.append)
        widget.cancelled.connect(lambda: cancelled.append(1))
        return widget, picked, cancelled

    def test_sectors_follow_the_clock(self):
        widget, _, _ = self.menu(4)
        center = widget._center()
        middle = (widget.radius + widget.inner) / 2
        self.assertEqual(widget._sector_at(center), -1)                                       # the centre closes
        self.assertEqual(widget._sector_at(QPointF(center.x(), center.y() - middle)), 0)       # up
        self.assertEqual(widget._sector_at(QPointF(center.x() + middle, center.y())), 1)       # right
        self.assertEqual(widget._sector_at(QPointF(center.x(), center.y() + middle)), 2)       # down
        self.assertEqual(widget._sector_at(QPointF(center.x() - middle, center.y())), 3)       # left
        self.assertEqual(widget._sector_at(QPointF(center.x() + widget.radius + 20, center.y())), -1)

    def test_digits_and_enter_pick_once(self):
        widget, picked, _ = self.menu(4)
        key(widget, Qt.Key.Key_3)
        key(widget, Qt.Key.Key_1)  # already closed: nothing more
        self.assertEqual(picked, ["id2"])
        widget, picked, _ = self.menu(4)
        key(widget, Qt.Key.Key_Right)
        key(widget, Qt.Key.Key_Right)
        key(widget, Qt.Key.Key_Return)
        self.assertEqual(picked, ["id1"])

    def test_a_digit_beyond_the_items_does_nothing_and_escape_cancels(self):
        widget, picked, cancelled = self.menu(3)
        key(widget, Qt.Key.Key_9)
        self.assertEqual(picked, [])
        key(widget, Qt.Key.Key_Escape)
        self.assertEqual(cancelled, [1])

    def test_arrow_keys_on_an_empty_menu_do_not_crash(self):
        widget, picked, _ = self.menu(0)
        key(widget, Qt.Key.Key_Right)
        key(widget, Qt.Key.Key_Left)
        key(widget, Qt.Key.Key_Return)
        self.assertEqual(picked, [])

    def test_a_click_outside_the_ring_cancels(self):
        widget, picked, cancelled = self.menu(4)
        widget.mouseReleaseEvent(mouse(QEvent.Type.MouseButtonRelease, 1, 1))
        self.assertEqual((picked, cancelled), ([], [1]))

    def test_painting_does_not_fail(self):
        widget, _, _ = self.menu(8)
        widget.current = 2
        self.assertFalse(widget.grab().isNull())


class RegionAndCropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app()

    def selector(self):
        from luxai.ui_convert_circle import RegionSelector
        with mock.patch("luxai.ui_convert_circle.QGuiApplication.primaryScreen") as screen:
            screen.return_value.grabWindow.return_value = QPixmap(400, 300)
            screen.return_value.geometry.return_value = QRect(0, 0, 400, 300)
            widget = RegionSelector("Select")
        self.addCleanup(widget.deleteLater)
        selected, cancelled = [], []
        widget.selected.connect(selected.append)
        widget.cancelled.connect(lambda: cancelled.append(1))
        return widget, selected, cancelled

    def test_a_dragged_region_is_cut_from_the_snapshot(self):
        widget, selected, _ = self.selector()
        widget.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, 10, 20))
        widget.mouseMoveEvent(mouse(QEvent.Type.MouseMove, 110, 70))
        widget.mouseReleaseEvent(mouse(QEvent.Type.MouseButtonRelease, 110, 70))
        self.assertEqual(selected[0].size(), QSize(100, 50))

    def test_a_click_without_dragging_cancels(self):
        widget, selected, cancelled = self.selector()
        widget.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, 10, 20))
        widget.mouseReleaseEvent(mouse(QEvent.Type.MouseButtonRelease, 11, 21))
        self.assertEqual((selected, cancelled), ([], [1]))

    def test_the_crop_box_is_in_image_pixels(self):
        from luxai.ui_convert_circle import _CropCanvas
        canvas = _CropCanvas(QPixmap(200, 100))
        self.addCleanup(canvas.deleteLater)
        canvas.resize(400, 300)  # the picture is drawn twice as big, centred vertically (offset 50 px)
        canvas.rect_ = QRect(QPoint(0, 50), QPoint(199, 149))
        box = canvas.image_box()
        self.assertEqual(tuple(round(value) for value in box), (0, 0, 100, 50))
        canvas.rect_ = QRect(5, 5, 1, 1)
        self.assertIsNone(canvas.image_box())  # too small: nothing chosen


# -- ui_clipboard: the clipboard history window -------------------------------------------------------
class ClipboardWindowTests(unittest.TestCase):
    ITEMS = [
        {"id": 1, "kind": "text", "text": "Adresa: strada Florilor 5", "time": time.time() - 30, "app": "chrome.exe"},
        {"id": 2, "kind": "text", "text": "parola wifi de acasă", "time": time.time() - 7200, "pinned": True},
        {"id": 3, "kind": "image", "size": [640, 480], "time": time.time() - 3 * 86400},
    ]

    @classmethod
    def setUpClass(cls):
        app()

    def popup(self, items=None):
        from luxai.ui_clipboard import ClipboardPopup
        widget = ClipboardPopup(list(self.ITEMS if items is None else items), "ro")
        self.addCleanup(widget.deleteLater)
        events = {"picked": [], "pin": [], "removed": [], "ai": []}
        widget.picked.connect(lambda item_id, plain: events["picked"].append((item_id, plain)))
        widget.pin_toggled.connect(events["pin"].append)
        widget.removed.connect(events["removed"].append)
        widget.ai_requested.connect(lambda item_id, mode: events["ai"].append((item_id, mode)))
        return widget, events

    def test_times_and_previews(self):
        from luxai.ui_clipboard import ago, preview
        now = 1_000_000.0
        self.assertEqual(ago(now - 10, "ro", now), "acum")
        self.assertEqual(ago(now - 600, "ro", now), "acum 10 min")
        self.assertEqual(ago(now - 7200, "en", now), "2 h ago")
        self.assertEqual(ago(now - 3 * 86400, "ru", now), "3 дн назад")
        self.assertEqual(preview(self.ITEMS[2], "ro"), "Imagine 640×480")
        self.assertTrue(preview({"kind": "text", "text": "x" * 500, "truncated": True}, "ro").startswith("✂ "))

    def test_search_hides_what_does_not_match(self):
        widget, _ = self.popup()
        widget.search.setText("wifi")
        visible = [widget.list.item(i).data(Qt.ItemDataRole.UserRole)
                   for i in range(widget.list.count()) if not widget.list.item(i).isHidden()]
        self.assertEqual(visible, [2])
        widget.search.setText("nu există așa ceva")
        self.assertTrue(widget.empty.isVisibleTo(widget))
        self.assertEqual(widget.empty.text(), "Nu s-a găsit nimic.")

    def test_keys_paste_pin_and_delete_the_current_item(self):
        widget, events = self.popup()
        widget.list.setCurrentRow(1)
        widget.list.setFocus()
        key(widget, Qt.Key.Key_P, Qt.KeyboardModifier.ControlModifier)
        key(widget, Qt.Key.Key_Delete)
        self.assertEqual((events["pin"], events["removed"]), ([2], [2]))
        key(widget, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(events["picked"], [(2, True)])  # Shift+Enter: without formatting

    def test_pictures_have_no_text_actions(self):
        widget, events = self.popup()
        text_menu = [a.text() for a in widget._menu_actions(1).actions() if a.text()]
        picture_menu = [a.text() for a in widget._menu_actions(3).actions() if a.text()]
        self.assertIn("Tradu", text_menu)
        self.assertIn("Lipește fără formatare", text_menu)
        self.assertNotIn("Tradu", picture_menu)
        self.assertNotIn("Lipește fără formatare", picture_menu)
        next(a for a in widget._menu_actions(1).actions() if a.text() == "Tradu").trigger()
        self.assertEqual(events["ai"], [(1, "translate")])

    def test_an_empty_history_says_so(self):
        widget, _ = self.popup([])
        self.assertEqual(widget.empty.text(), "Istoricul e gol. Copiază ceva (Ctrl+C).")

    def test_unchanged_history_is_not_rebuilt(self):
        widget, _ = self.popup()
        widget.runtime_items = lambda: list(self.ITEMS)
        with mock.patch.object(widget, "_fill") as fill:
            widget._refresh_now()
        fill.assert_not_called()
        widget.runtime_items = lambda: list(self.ITEMS[:2])
        with mock.patch.object(widget, "_fill") as fill:
            widget._refresh_now()
        fill.assert_called_once()


# -- ui_command_fields: the phrase chips of the command editor -------------------------------------------
class PhraseChipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app()

    def chips(self, values=()):
        from luxai.ui_command_fields import PhraseChips
        widget = PhraseChips(values, placeholder="frază", add_text="+")
        self.addCleanup(widget.deleteLater)
        return widget

    def test_duplicates_and_blank_phrases_are_dropped(self):
        widget = self.chips(["pornește muzica", " pornește muzica ", "", "  ", "deschide chrome"])
        self.assertEqual(widget.values, ["pornește muzica", "deschide chrome"])

    def test_typed_phrases_are_added_comma_by_comma(self):
        widget = self.chips(["unu"])
        changes = []
        widget.changed.connect(lambda: changes.append(1))
        widget.input.setText("doi, trei ,unu")
        self.assertEqual(widget.get_values(), ["unu", "doi", "trei"])  # also before Enter (not lost on save)
        widget.commit()
        self.assertEqual(widget.values, ["unu", "doi", "trei"])
        self.assertEqual(widget.input.text(), "")
        self.assertTrue(changes)

    def test_removing_the_last_phrase_opens_the_input(self):
        widget = self.chips(["singura"])
        self.assertFalse(widget.input.isVisibleTo(widget))
        widget.remove("singura")
        self.assertEqual(widget.values, [])
        self.assertTrue(widget.input.isVisibleTo(widget))

    def test_chips_wrap_onto_more_lines_when_narrow(self):
        widget = self.chips([f"frază lungă numărul {i}" for i in range(8)])
        layout = widget.flow
        self.assertGreater(layout.heightForWidth(220), layout.heightForWidth(2000))
        self.assertEqual(layout.takeAt(999), None)
        self.assertIsNone(layout.itemAt(-1))


# -- ui_command_menu: the right-click menu of the command library ----------------------------------------
class CommandMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app()

    def test_actions_carry_their_icon_danger_and_callback(self):
        from luxai.ui_command_menu import CommandContextMenu
        menu = CommandContextMenu(config={"ui_theme": "light", "ui_accent": "#ff8800"})
        self.addCleanup(menu.deleteLater)
        calls = []
        run = menu.add_command("Rulează", "play", lambda: calls.append("run"))
        delete = menu.add_command("Șterge", "trash-2", lambda: calls.append("delete"), danger=True)
        off = menu.add_command("Exportă", "download", lambda: calls.append("export"), enabled=False)
        self.assertEqual(run.data(), {"icon": "play", "danger": False})
        self.assertEqual(delete.data(), {"icon": "trash-2", "danger": True})
        self.assertFalse(off.isEnabled())
        self.assertIn(delete, menu._danger_actions)
        self.assertNotIn(run, menu._danger_actions)
        delete.trigger()
        self.assertEqual(calls, ["delete"])
        self.assertEqual(menu.property("jarvisIconTheme"), "light")

    def test_the_red_rows_are_painted(self):
        from luxai.ui_command_menu import CommandContextMenu
        menu = CommandContextMenu()
        self.addCleanup(menu.deleteLater)
        menu.add_command("Rulează", "play", lambda: None)
        menu.add_command("Șterge", "trash-2", lambda: None, danger=True)
        menu.resize(menu.sizeHint())
        self.assertFalse(menu.grab().isNull())


if __name__ == "__main__":
    unittest.main()
