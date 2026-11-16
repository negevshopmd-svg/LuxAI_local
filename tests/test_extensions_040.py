"""0.4.0 Extensions: catalog, state validation, runtime helpers and page."""
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from luxai import extensions_catalog as catalog
from luxai import extensions_runtime as runtime
from luxai.ui_extension_settings import PluginSettingsView
from luxai.ui_extensions import ExtensionsPage
from luxai.ui_sidebar import NavigationSidebar


class CatalogTests(unittest.TestCase):
    def test_twenty_two_plugins_in_five_topics(self):
        self.assertEqual(len(catalog.PLUGINS), 22)
        counts = {identifier: 0 for identifier in catalog.CATEGORY_IDS}
        for plugin in catalog.PLUGINS:
            counts[plugin.category] += 1
        self.assertEqual(counts, {"voice": 5, "text": 4, "desktop": 4, "control": 5, "files": 4})

    def test_every_plugin_is_translated_and_has_an_icon(self):
        icons = Path(catalog.__file__).parent / "assets" / "icons" / "lucide"
        for plugin in catalog.PLUGINS:
            for language in catalog.LANGS:
                self.assertTrue(catalog.text(plugin.title, language))
                self.assertTrue(catalog.text(plugin.description, language))
                for setting in plugin.settings:
                    self.assertTrue(catalog.text(setting.label, language), setting.key)
            self.assertTrue((icons / f"{plugin.icon}.svg").is_file(), plugin.icon)
            self.assertRegex(plugin.color, r"^#[0-9a-f]{6}$")

    def test_defaults_are_valid(self):
        for plugin in catalog.PLUGINS:
            for setting in plugin.settings:
                self.assertEqual(catalog.validate_value(setting, setting.default), setting.default
                                 if setting.kind != "hotkey" else catalog.validate_value(setting, setting.default))

    def test_normalize_drops_bad_values_and_locks_unfinished_plugins(self):
        state = catalog.normalize_state({
            "breaks": {"enabled": True, "settings": {"interval": 5, "speak": "yes", "water": False}},
            "live_captions": {"enabled": True},
            "unknown": {"enabled": True},
            "clipboard_history": "broken",
            "screenshots": {"enabled": True, "settings": {"hotkey": "alt+f4"}},
        })
        self.assertTrue(state["breaks"]["enabled"])
        self.assertEqual(state["breaks"]["settings"]["interval"], 50)  # below minimum -> default
        self.assertTrue(state["breaks"]["settings"]["speak"] is False)
        self.assertFalse(state["breaks"]["settings"]["water"])
        self.assertFalse(state["live_captions"]["enabled"])  # not ready yet
        self.assertNotIn("unknown", state)
        self.assertFalse(state["clipboard_history"]["enabled"])
        self.assertEqual(state["screenshots"]["settings"]["hotkey"], "ctrl+alt+s")  # system combo rejected
        self.assertEqual(catalog.enabled_count(state), 2)
        json.dumps(state)  # stays serializable for config.json

    def test_search_and_snippets(self):
        breaks = catalog.PLUGIN_BY_ID["breaks"]
        self.assertTrue(catalog.matches(breaks, "перерыв", "ru"))
        self.assertTrue(catalog.matches(breaks, "Breaks", "ru"))
        self.assertFalse(catalog.matches(breaks, "telegram", "ru"))
        self.assertEqual(catalog.parse_snippets("a = b\\nc\nbad line\n x =  y "), [("a", "b\nc"), ("x", "y")])

    def test_hotkey_conflicts_between_enabled_plugins(self):
        state = catalog.normalize_state({
            "clipboard_history": {"enabled": True, "settings": {"hotkey": "ctrl+alt+x"}},
            "quick_inserts": {"enabled": True, "settings": {"hotkey": "ctrl+alt+x"}},
        })
        self.assertEqual(catalog.hotkey_conflicts(state), {"quick_inserts.hotkey": "clipboard_history.hotkey"})


class RuntimeHelperTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.base = Path(self.folder.name)
        self.addCleanup(self.folder.cleanup)

    def touch(self, name, days_old):
        path = self.base / name
        path.write_bytes(b"x")
        stamp = time.time() - days_old * 86400
        os.utime(path, (stamp, stamp))
        return path

    def test_cleanup_plan_respects_age_partial_files_and_installers(self):
        self.touch("photo.JPG", 3)
        self.touch("new.pdf", 0)
        self.touch("movie.mkv.crdownload", 9)
        self.touch("setup.exe", 40)
        self.touch("tool.msi", 2)
        self.touch("notes.unknownext", 9)
        (self.base / "Folder").mkdir()
        steps = runtime.plan_cleanup(self.base, min_age_days=1, installer_trash_days=30, language="ru")
        result = {step.source.name: (step.target.parent.name if step.target else "TRASH") for step in steps}
        self.assertEqual(result, {"photo.JPG": "Картинки", "setup.exe": "TRASH", "tool.msi": "Установщики"})

    def test_run_cleanup_moves_without_overwriting(self):
        self.touch("a.png", 5)
        (self.base / "Images").mkdir()
        (self.base / "Images" / "a.png").write_bytes(b"old")
        self.touch("b.exe", 99)
        trashed = []
        steps = runtime.plan_cleanup(self.base, min_age_days=0, installer_trash_days=10, language="en")
        moved, sent, errors = runtime.run_cleanup(steps, trash=trashed.append)
        self.assertEqual((moved, sent, errors), (1, 1, []))
        self.assertEqual((self.base / "Images" / "a.png").read_bytes(), b"old")
        self.assertTrue((self.base / "Images" / "a (1).png").is_file())
        self.assertEqual([Path(item).name for item in trashed], ["b.exe"])

    def test_convert_image_writes_copy(self):
        from PIL import Image
        source = self.base / "pic.png"
        Image.new("RGBA", (400, 200), (255, 0, 0, 128)).save(source)
        jpg = runtime.convert_image(source, "jpg", quality=70, max_side=100)
        self.assertEqual(jpg.name, "pic.jpg")
        with Image.open(jpg) as converted:
            self.assertEqual(converted.size, (100, 50))
        again = runtime.convert_image(source, "png")
        self.assertEqual(again.name, "pic_png.png")
        self.assertTrue(source.is_file())
        self.assertTrue(runtime.convert_image(source, "ico").is_file())
        self.assertTrue(runtime.convert_image(source, "pdf").is_file())

    def test_secret_heuristic(self):
        for value in ("12345", "sk-abcdefghijklmnop", "Xy7#pass!word", "aB3_dE5-fG7hJ9kL1mN2"):
            self.assertTrue(runtime.looks_secret(value), value)
        for value in ("hello world", "https://example.com/path", "Привет", "notes", "2024"):
            self.assertFalse(runtime.looks_secret(value), value)

    def test_snippet_placeholders(self):
        moment = dt.datetime(2026, 11, 16, 9, 5)
        self.assertEqual(runtime.expand_snippet("{дата} {time} {ora}", moment), "16.11.2026 09:05 09:05")


class _Host:
    def __init__(self):
        self.cfg = {"ui_language": "ru"}
        self.spoken = []
        self.tray_icon = None

    def _queue_speech(self, text, language):
        self.spoken.append((text, language))


class PageAndRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_page(self, state=None):
        host = _Host()
        engine = runtime.ExtensionsRuntime(host)
        page = ExtensionsPage(state, engine)
        page.resize(1000, 640)
        page.show()
        self.app.processEvents()
        self.addCleanup(self._dispose, page, engine)
        return page, engine, host

    def _dispose(self, page, engine):
        engine.stop()
        popup = getattr(engine, "_popup", None)
        for widget in (popup, page):
            if widget is not None:
                try:
                    widget.close()
                    widget.deleteLater()
                except RuntimeError:
                    pass
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_page_lists_all_plugins_and_counts(self):
        page, _, _ = self.make_page({"breaks": {"enabled": True}})
        self.assertEqual(len(page.cards), 22)
        self.assertEqual(page.counter.text(), "Включено: 1 из 22")
        self.assertEqual(page.topic_buttons["voice"].count.text(), "5")
        self.assertIn("22", page.plugins_tab.text())
        self.assertFalse(page.cards["live_captions"].switch.isEnabled())
        self.assertTrue(page.cards["breaks"].switch.isChecked())

    def test_toggle_search_filter_and_language(self):
        page, _, _ = self.make_page()
        emitted = []
        page.state_changed.connect(emitted.append)
        page.cards["clipboard_history"].switch.click()
        self.assertTrue(emitted[-1]["clipboard_history"]["enabled"])
        page.only_enabled.setChecked(True)
        self.app.processEvents()
        self.assertEqual(list(page.cards), ["clipboard_history"])
        page.only_enabled.setChecked(False)
        page.search.setText("скрин")
        self.assertEqual(list(page.cards), ["screenshots"])
        page.search.setText("")
        page.set_language("ro")
        self.assertEqual(page.counter.text(), "Activate: 1 din 22")
        page.set_view("list")
        self.assertEqual(page.cards["breaks"].objectName(), "ExtRow")

    def test_settings_view_validates_hotkeys(self):
        plugin = catalog.PLUGIN_BY_ID["media_keys"]
        state = catalog.normalize_state({})
        view = PluginSettingsView(plugin, state["media_keys"], "ru")
        self.addCleanup(lambda: (view.deleteLater(), QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)))
        view.fields["next"].set_value("ctrl+alt+p")  # duplicate of play_pause
        with self.assertRaises(ValueError):
            view.collect()
        self.assertFalse(view.save())
        view.fields["next"].set_value("ctrl+shift+n")
        self.assertEqual(view.collect()["next"], "ctrl+shift+n")

    def test_settings_open_inside_the_page_and_save(self):
        page, engine, _ = self.make_page()
        titles, states = [], []
        page.title_changed.connect(titles.append)
        page.state_changed.connect(states.append)
        view = page.open_settings("smart_dictation")
        self.assertIs(page.views.currentWidget(), view)
        self.assertEqual(titles[-1], "Умная диктовка")
        self.assertFalse(view.save_button.isEnabled())
        self.assertFalse(view.rows["silence_pause"].isEnabled())  # only for press-speak-press
        self.assertFalse(view.rows["hotkey"].isEnabled())  # right Ctrl x2 by default
        view.fields["mode"].set_value("toggle")
        view._refresh()
        self.assertTrue(view.rows["silence_pause"].isEnabled())
        view.enable_switch.setChecked(True)
        self.assertTrue(view.dirty and view.save_button.isEnabled())
        self.assertTrue(view.save())
        self.assertTrue(states[-1]["smart_dictation"]["enabled"])
        self.assertEqual(states[-1]["smart_dictation"]["settings"]["mode"], "toggle")
        self.assertFalse(view.dirty)
        view.reset_section("keys")
        self.assertEqual(view.draft()["mode"], "hold")
        self.assertTrue(view.dirty)
        with mock.patch("luxai.ui_extensions.QMessageBox.question",
                        return_value=__import__("PySide6.QtWidgets", fromlist=["QMessageBox"]).QMessageBox.StandardButton.Discard):
            self.assertTrue(page.go_back())
        self.assertIs(page.views.currentWidget(), page.list_view)
        self.assertEqual(titles[-1], "")
        self.assertEqual(page.state["smart_dictation"]["settings"]["mode"], "toggle")

    def test_dictation_test_box_receives_text_inside_jarvis(self):
        page, engine, _ = self.make_page({"smart_dictation": {"enabled": True}})
        view = page.open_settings("smart_dictation")
        self.assertTrue(view.test_box.isEnabled())
        view.test_box.setFocus()
        self.app.processEvents()
        with mock.patch.object(view.test_box, "hasFocus", return_value=True):
            engine.insert_dictation("Привет.", 0)
        self.assertEqual(view.test_box.toPlainText(), "Привет.")
        engine.dictation_done.emit("Привет.")
        self.assertEqual(view.last_label.text(), "Привет.")
        page.close_settings()
        self.assertIsNone(engine.test_sink)

    def test_runtime_clipboard_history_and_breaks(self):
        state = catalog.normalize_state({"clipboard_history": {"enabled": True, "settings": {"limit": 10}},
                                         "breaks": {"enabled": True, "settings": {"speak": True}}})
        _, engine, host = self.make_page(state)
        engine.apply(state)
        for index in range(15):
            engine.remember_clipboard(f"text {index}")
        engine.remember_clipboard("123456")  # one-time code is ignored
        self.assertEqual(len(engine.clipboard_items), 10)
        self.assertEqual(engine.clipboard_items[0]["text"], "text 14")
        engine._toggle_pin("text 5")
        engine.clear_clipboard()
        self.assertEqual([item["text"] for item in engine.clipboard_items], ["text 5"])
        popup = engine.open_clipboard_history()
        self.assertEqual(popup.list.count(), 1)
        message = engine.remind_break(force=True)
        self.assertTrue(message)
        self.assertEqual(host.spoken[-1][0], message)
        self.assertTrue(engine._break_timer.isActive())
        self.assertEqual({entry["id"] for entry in engine.hotkey_entries()}, {"clipboard_history.hotkey"})


class SidebarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_extensions_button_sits_after_addons_and_emits_page_five(self):
        sidebar = NavigationSidebar()
        self.addCleanup(sidebar.deleteLater)
        self.assertEqual(len(sidebar.nav_buttons), 6)
        layout = sidebar.layout()
        order = [layout.indexOf(button) for button in sidebar.nav_buttons]
        self.assertLess(order[2], order[5])
        self.assertLess(order[5], order[3])
        pages = []
        sidebar.page_selected.connect(pages.append)
        sidebar.nav_buttons[5].click()
        self.assertEqual(pages, [5])
        self.assertEqual(sidebar.nav_buttons[5].text(), "Расширения")
        sidebar.set_language("en")
        self.assertEqual(sidebar.nav_buttons[5].text(), "Extensions")


class MainWindowIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        from luxai import command_registry
        cls.app = QApplication.instance() or QApplication([])
        cls.folder = tempfile.TemporaryDirectory()
        cls.base = Path(cls.folder.name)
        cls.config = cls.base / "config.json"
        cls.config.write_text(json.dumps({
            "microphone_enabled": False, "tts_enabled": False, "online_agent_enabled": False,
            "ui_animations": False, "minimize_to_tray": False, "ui_language": "ru",
            "extensions": {"breaks": {"enabled": True, "settings": {"interval": 30}}},
        }), encoding="utf-8")
        cls.patches = [mock.patch.object(main, "CONFIG", cls.config),
                       mock.patch.object(command_registry, "REGISTRY_FILE", cls.base / "commands.json")]
        for patch in cls.patches:
            patch.start()
        with (mock.patch("sounddevice.query_devices", return_value=[]),
              mock.patch.object(main.MainWindow, "_ocr_setup_worker")):
            cls.window = main.MainWindow()
        cls.window.resize(1040, 640)
        cls.window.show()
        cls.app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.window._quitting = True
        cls.window.close()
        cls.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        for patch in reversed(cls.patches):
            patch.stop()
        cls.folder.cleanup()

    def test_page_five_is_extensions_and_state_persists(self):
        window = self.window
        self.assertEqual(window.pages.count(), 6)
        window.show_page(5)
        self.assertIs(window.pages.currentWidget(), window.extensions_page)
        self.assertIn("Расширения", window.header_title.text())
        self.assertTrue(window.extensions_page.cards["breaks"].switch.isChecked())
        window.extensions_page.cards["converter"].switch.click()
        saved = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertTrue(saved["extensions"]["converter"]["enabled"])
        self.assertEqual(saved["extensions"]["breaks"]["settings"]["interval"], 30)
        window.show_page(0)


if __name__ == "__main__":
    unittest.main()
