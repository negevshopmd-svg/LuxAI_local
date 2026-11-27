"""0.4.3v: the Action circle plugin — radial menu at the cursor: commands, window, media, search."""
from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from luxai import action_circle as ac  # noqa: E402
from luxai import extensions_catalog as catalog  # noqa: E402

ENTRIES = [
    {"id": "user_1", "title": "Open Telegram", "phrases": ["open telegram"], "enabled": True, "builtin": False},
    {"id": "user_2", "title": "Night mode", "phrases": ["night mode"], "enabled": True, "builtin": False},
    {"id": "user_3", "title": "Off one", "phrases": ["off"], "enabled": False, "builtin": False},
    {"id": "user_4", "title": "Agent task", "phrases": ["agent"], "enabled": True, "builtin": False, "agent": True},
    {"id": "built_1", "title": "Steam", "phrases": ["open steam"], "enabled": True, "builtin": True},
]


class SlotTests(unittest.TestCase):
    def test_defaults_fill_ten_items(self):
        settings = catalog.normalize_state({})["quick_circle"]["settings"]
        items = ac.slots(settings, ENTRIES, "en")
        self.assertEqual(len(items), 10)
        self.assertEqual([slot for slot, _, _ in items[:2]], ["cmd:user_1", "cmd:user_2"])  # personal ones, enabled
        self.assertEqual(items[2][0], "search_selection")
        self.assertNotIn("cmd:user_3", [slot for slot, _, _ in items])
        self.assertNotIn("cmd:user_4", [slot for slot, _, _ in items])

    def test_named_commands_in_their_order_and_the_rest_trimmed(self):
        settings = {"items": 4, "commands": "night mode\nSTEAM\nmissing", "show_search": True,
                    "show_window": True, "show_media": True}
        items = ac.slots(settings, ENTRIES, "ro")
        self.assertEqual([slot for slot, _, _ in items], ["cmd:user_2", "cmd:built_1", "search_selection", "win_minimize"])
        self.assertEqual(items[2][1], "Caută selecția")

    def test_groups_can_be_turned_off(self):
        items = ac.slots({"items": 12, "commands": "", "show_search": False, "show_window": False,
                          "show_media": True}, [], "ru")
        self.assertEqual([slot for slot, _, _ in items], list(ac.MEDIA_ACTIONS))
        self.assertEqual(ac.slots({"items": 12, "show_search": False, "show_window": False, "show_media": False},
                                  [], "ru"), [])

    def test_hostile_item_count(self):
        for value in ("x", None, -5, 99):
            self.assertLessEqual(len(ac.slots({"items": value}, ENTRIES, "ru")), 12)

    def test_search_url_is_encoded(self):
        self.assertEqual(ac.search_url("a&b c", "duckduckgo"), "https://duckduckgo.com/?q=a%26b+c")
        self.assertTrue(ac.search_url("x", "unknown").startswith("https://www.google.com/search?q="))
        self.assertLessEqual(len(ac.search_url("y" * 5000)), 400)

    def test_every_label_has_three_languages_and_an_icon(self):
        for key, values in ac.LABELS.items():
            self.assertEqual(len(values), 3, key)
            self.assertTrue(all(values), key)
        for action in ac.WINDOW_ACTIONS + ac.MEDIA_ACTIONS + ac.SEARCH_ACTIONS:
            self.assertTrue((ROOT / "luxai" / "assets" / "icons" / "lucide" / f"{ac.ICONS[action]}.svg").is_file(), action)

    def test_the_plugin_is_ready_and_its_texts_are_trilingual(self):
        plugin = catalog.PLUGIN_BY_ID["quick_circle"]
        self.assertTrue(plugin.ready)
        values = [plugin.title, plugin.description, catalog.BASIC_NOTE["quick_circle"]]
        for setting in plugin.settings:
            values += [setting.label] + ([setting.hint] if setting.hint else []) + [label for _v, label in setting.options]
        for value in values:
            for language in ("ru", "en", "ro"):
                self.assertTrue(str(value.get(language) or "").strip(), value)


class _Host:
    def __init__(self):
        self.cfg = {"language": "ru", "ui_language": "ru", "ui_theme": "dark"}
        self.tray_icon = None
        self.online_planner = None
        self.command_registry = mock.Mock()
        self.command_registry.entries.return_value = ENTRIES
        self.ran = []

    def run_command_entry(self, entry, *, triggered=False, origin=None):
        self.ran.append((entry["id"], triggered))
        return True

    def _queue_speech(self, *args):
        pass

    def stop_speaking(self):
        pass


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, **settings):
        from luxai import extensions_runtime as runtime
        engine = runtime.ExtensionsRuntime(_Host())
        engine.apply(catalog.normalize_state({"quick_circle": {"enabled": True, "settings": settings}}))

        def dispose():
            engine.stop()
            engine.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        self.addCleanup(dispose)
        return engine

    def test_the_hotkey_is_registered(self):
        engine = self.make()
        self.assertIn({"id": "quick_circle.hotkey", "enabled": True, "hotkey": "ctrl+alt+c"}, engine.hotkey_entries())

    def test_the_circle_opens_with_its_slots(self):
        engine = self.make()
        with mock.patch("luxai.screen_interact._foreground_hwnd", return_value=0):
            menu = engine.open_action_circle()
        self.addCleanup(menu.close)
        self.assertEqual(len(menu.items), 10)
        self.assertEqual(menu.title, "Круг действий")

    def test_an_empty_circle_is_explained(self):
        engine = self.make(show_search=False, show_window=False, show_media=False, commands="nothing like this")
        notes = []
        with mock.patch.object(engine, "_notify", side_effect=notes.append), \
                mock.patch("luxai.screen_interact._foreground_hwnd", return_value=0):
            self.assertIsNone(engine.open_action_circle())
        self.assertTrue(notes)

    def test_a_command_runs_on_the_window_it_was_meant_for(self):
        engine = self.make()
        with mock.patch("luxai.extensions_runtime._set_foreground", return_value=True) as front, \
                mock.patch.object(ac, "window_alive", return_value=True), \
                mock.patch.object(ac, "is_own_window", return_value=False):
            engine._circle_pick("cmd:user_2", 777)
        front.assert_called_once_with(777)
        self.assertEqual(engine.host.ran, [("user_2", True)])

    def test_a_removed_command_is_said(self):
        engine = self.make()
        notes = []
        with mock.patch.object(engine, "_notify", side_effect=notes.append):
            engine._circle_pick("cmd:user_404", 0)
        self.assertEqual(engine.host.ran, [])
        self.assertTrue(notes)

    def test_media_slots_press_their_keys(self):
        engine = self.make()
        with mock.patch("luxai.extensions_runtime.press_virtual_key") as press:
            engine._circle_pick("media_next", 0)
        press.assert_called_once_with(0xB0)

    def test_search_reads_the_selection_and_opens_the_browser(self):
        engine = self.make(search_engine="bing")
        opened = []
        with mock.patch("luxai.extensions_runtime._set_foreground", return_value=True), \
                mock.patch.object(ac, "window_alive", return_value=True), \
                mock.patch.object(ac, "is_own_window", return_value=False), \
                mock.patch.object(engine, "_capture_selection", side_effect=lambda hwnd, deliver: deliver("café prices")), \
                mock.patch("PySide6.QtGui.QDesktopServices.openUrl",
                           side_effect=lambda url: opened.append(bytes(url.toEncoded()).decode())):
            engine._circle_pick("search_selection", 55)
            deadline = time.monotonic() + 2
            while not opened and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.01)
        self.assertEqual(opened, ["https://www.bing.com/search?q=caf%C3%A9+prices"])


@unittest.skipUnless(sys.platform == "win32", "Win32 windows")
class RealWindowTests(unittest.TestCase):
    """The window actions on a real Notepad window (started and closed by the test)."""

    def setUp(self):
        import ctypes
        from ctypes import wintypes
        self.user32 = ac._user32()  # declared types: 64-bit window handles
        enum_windows = ctypes.windll.user32.EnumWindows
        self.process = subprocess.Popen(["notepad.exe"])
        self.addCleanup(self.process.kill)
        self.hwnd = 0
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def visit(hwnd, _):
            owner = wintypes.DWORD()
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == self.process.pid and self.user32.IsWindowVisible(hwnd):
                found.append(hwnd)
            return True

        deadline = time.monotonic() + 10
        while not found and time.monotonic() < deadline:
            time.sleep(0.1)
            enum_windows(visit, 0)
        if not found:
            self.skipTest("Notepad did not open")
        self.hwnd = found[0]

    def test_maximize_topmost_minimize_close(self):
        self.assertEqual(ac.window_action("win_maximize", self.hwnd), "")
        time.sleep(0.3)
        self.assertTrue(self.user32.IsZoomed(self.hwnd))
        self.assertEqual(ac.window_action("win_maximize", self.hwnd), "")  # a second press restores
        time.sleep(0.3)
        self.assertFalse(self.user32.IsZoomed(self.hwnd))
        self.assertEqual(ac.window_action("win_topmost", self.hwnd), "topmost_on")
        self.assertTrue(ac.is_topmost(self.hwnd))
        self.assertEqual(ac.window_action("win_topmost", self.hwnd), "topmost_off")
        self.assertFalse(ac.is_topmost(self.hwnd))
        self.assertEqual(ac.window_action("win_minimize", self.hwnd), "")
        time.sleep(0.3)
        self.assertTrue(self.user32.IsIconic(self.hwnd))
        self.assertEqual(ac.window_action("win_close", self.hwnd), "")
        self.process.wait(10)  # an unchanged Notepad closes without asking
        self.assertEqual(ac.window_action("win_close", self.hwnd), "no_window")

    def test_jarvis_never_closes_its_own_window(self):
        with mock.patch.object(ac, "is_own_window", return_value=True):
            self.assertEqual(ac.window_action("win_close", self.hwnd), "own_window")
        self.assertTrue(self.user32.IsWindow(self.hwnd))


if __name__ == "__main__":
    unittest.main()
