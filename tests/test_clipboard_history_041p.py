"""0.4.1p: clipboard history like Luxify — storage, privacy, popup, AI, voice."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QCoreApplication, QEvent, QMimeData, Qt
from PySide6.QtGui import QImage, QKeyEvent
from PySide6.QtWidgets import QApplication

from luxai import clipboard_store as store
from luxai import extensions_catalog as catalog


class StoreTests(unittest.TestCase):
    def test_dedupe_pins_trim_and_age(self):
        history = store.ClipboardHistory()
        for index in range(8):
            history.add_text(f"t{index}", now=1000 + index)
        history.add_text("t2", now=2000)  # copied again: moves to the top, no duplicate
        self.assertEqual([item["text"] for item in history.items][:2], ["t2", "t7"])
        self.assertEqual(len(history.items), 8)
        pinned = next(item for item in history.items if item["text"] == "t0")
        history.toggle_pin(pinned["id"])
        history.trim(3)
        self.assertEqual([item["text"] for item in history.ordered()], ["t0", "t2", "t7", "t6"])
        history.prune(1, now=1000 + 86400 + 10)  # one day: only t2 (time 2000) and the pin survive
        self.assertEqual([item["text"] for item in history.ordered()], ["t0", "t2"])
        self.assertEqual(history.previous_text(), "t0")
        history.clear()
        self.assertEqual([item["text"] for item in history.items], ["t0"])
        history.clear_all()
        self.assertEqual(history.items, [])

    def test_images_dedupe_by_content(self):
        history = store.ClipboardHistory()
        history.add_image(b"png-1", thumb=b"t", size=(10, 20))
        history.add_image(b"png-1", thumb=b"t", size=(10, 20))
        history.add_image(b"png-2")
        self.assertEqual(len(history.items), 2)
        self.assertIsNone(history.add_image(b""))

    def test_roundtrip_bytes_keeps_images_and_pins(self):
        history = store.ClipboardHistory()
        history.add_text("hello", html="<b>hello</b>", app="notepad.exe")
        item = history.add_image(b"\x89PNG data", thumb=b"thumb")
        history.toggle_pin(item["id"])
        again = store.ClipboardHistory()
        again.load_bytes(history.to_bytes())
        self.assertEqual(again.items[0]["png"], b"\x89PNG data")
        self.assertTrue(again.items[0]["pinned"])
        self.assertEqual(again.items[1]["html"], "<b>hello</b>")

    @unittest.skipUnless(sys.platform == "win32", "DPAPI is Windows only")
    def test_file_on_disk_is_encrypted(self):
        history = store.ClipboardHistory()
        history.add_text("very private text")
        path = Path(tempfile.mkdtemp()) / "clip.bin"
        self.assertTrue(history.save(path))
        raw = path.read_bytes()
        self.assertTrue(raw.startswith(store.FILE_MAGIC))
        self.assertNotIn(b"very private", raw)
        again = store.ClipboardHistory()
        self.assertTrue(again.load(path))
        self.assertEqual(again.items[0]["text"], "very private text")

    def test_privacy_rules(self):
        self.assertTrue(store.marked_private({'application/x-qt-windows-mime;value="ExcludeClipboardContentFromMonitorProcessing"': b""}))
        self.assertTrue(store.marked_private({'application/x-qt-windows-mime;value="CanIncludeInClipboardHistory"': b"\0\0\0\0"}))
        self.assertFalse(store.marked_private({'application/x-qt-windows-mime;value="CanIncludeInClipboardHistory"': b"\1\0\0\0"}))
        self.assertTrue(store.marked_private({"Clipboard Viewer Ignore": b""}))
        self.assertFalse(store.marked_private({"text/plain": b"x"}))
        names = store.parse_names(catalog.default_settings(catalog.PLUGIN_BY_ID["clipboard_history"])["exclude_apps"])
        for exe in ("KeePass.exe", "KeePassXC.exe", "1Password.exe", "Bitwarden.exe", "ProtonPass.exe", "pwsafe.exe"):
            self.assertTrue(store.excluded_app(exe, names), exe)
        for exe in ("notepad.exe", "chrome.exe", ""):
            self.assertFalse(store.excluded_app(exe, names), exe)

    def test_suppress_window(self):
        store._suppress_until = 0.0
        with mock.patch.object(store.time, "monotonic", return_value=100.0):
            store.suppress(2)
        with mock.patch.object(store.time, "monotonic", return_value=101.0):
            self.assertTrue(store.suppressed())
        with mock.patch.object(store.time, "monotonic", return_value=103.0):
            self.assertFalse(store.suppressed())

    def test_catalog_like_luxify(self):
        plugin = catalog.PLUGIN_BY_ID["clipboard_history"]
        defaults = catalog.default_settings(plugin)
        self.assertEqual(defaults["hotkey"], "alt+win+v")
        self.assertEqual(defaults["keep"], "100")
        self.assertTrue(defaults["persist"] and defaults["images"])
        self.assertEqual([section.id for section in catalog.sections_for(plugin)], ["key", "storage", "exclude", "ai"])
        tags = next(item for item in plugin.settings if item.key == "exclude_apps")
        self.assertEqual(catalog.validate_value(tags, "KeePass, keepass\nMy App "), "KeePass\nMy App")


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from luxai.extensions_runtime import ExtensionsRuntime
        store._suppress_until = 0.0
        folder = Path(tempfile.mkdtemp())
        patcher = mock.patch("luxai.clipboard_store.history_file", return_value=folder / "clip.bin")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.host = mock.Mock()
        self.host.cfg = {"language": "ru", "tts_enabled": False}
        self.host.online_planner.enabled.return_value = True
        self.runtime = ExtensionsRuntime(self.host)
        self.state = catalog.normalize_state({"clipboard_history": {"enabled": True, "settings": {"persist": False}}})
        self.runtime.state = self.state
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        popup = getattr(self.runtime, "_popup", None)
        if popup is not None:
            try:
                popup.close()
            except RuntimeError:
                pass
        self.runtime.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_password_manager_and_private_copies_are_skipped(self):
        data = QMimeData()
        data.setText("hunter2 password")
        with mock.patch.object(QApplication.clipboard(), "mimeData", return_value=data), \
                mock.patch("luxai.clipboard_store.clipboard_owner_app", return_value="KeePassXC.exe"):
            self.runtime._on_clipboard()
        self.assertEqual(self.runtime.clip_history.items, [])
        data.setData('application/x-qt-windows-mime;value="ExcludeClipboardContentFromMonitorProcessing"', b"")
        with mock.patch.object(QApplication.clipboard(), "mimeData", return_value=data), \
                mock.patch("luxai.clipboard_store.clipboard_owner_app", return_value="notepad.exe"):
            self.runtime._on_clipboard()
        self.assertEqual(self.runtime.clip_history.items, [])

    def test_text_with_html_and_images_are_kept(self):
        data = QMimeData()
        data.setText("hello world")
        data.setHtml("<b>hello</b> world")
        with mock.patch.object(QApplication.clipboard(), "mimeData", return_value=data), \
                mock.patch("luxai.clipboard_store.clipboard_owner_app", return_value="WINWORD.EXE"):
            self.runtime._on_clipboard()
        item = self.runtime.clip_history.items[0]
        self.assertEqual((item["text"], item["app"]), ("hello world", "WINWORD.EXE"))
        self.assertIn("<b>hello</b>", item["html"])
        image = QImage(40, 30, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.red)
        self.runtime._remember_image(image, "SnippingTool.exe")
        picture = self.runtime.clip_history.items[0]
        self.assertEqual(picture["kind"], "image")
        self.assertEqual(picture["size"], [40, 30])
        self.assertTrue(picture["thumb"].startswith(b"\x89PNG"))

    def test_jarvis_own_temporary_copies_are_skipped(self):
        store.suppress(2)
        data = QMimeData()
        data.setText("selection copied for read aloud")
        with mock.patch.object(QApplication.clipboard(), "mimeData", return_value=data):
            self.runtime._on_clipboard()
        self.assertEqual(self.runtime.clip_history.items, [])
        store._suppress_until = 0.0

    def test_popup_enter_shift_enter_and_formatting(self):
        self.runtime.clip_history.add_text("plain one", html="<i>plain one</i>")
        self.runtime.clip_history.add_text("second")
        with mock.patch("luxai.extensions_runtime._foreground_window", return_value=0):
            popup = self.runtime.open_clipboard_history()
        self.assertEqual(popup.list.count(), 2)
        popup.list.setCurrentRow(1)
        captured = []
        with mock.patch.object(QApplication.clipboard(), "setMimeData", side_effect=captured.append):
            popup.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier))
        self.assertEqual(captured[0].text(), "plain one")
        self.assertFalse(captured[0].hasHtml())  # Shift+Enter: without formatting
        self.assertEqual(self.runtime.clip_history.items[0]["text"], "plain one")  # used item moves up
        with mock.patch("luxai.extensions_runtime._foreground_window", return_value=0):
            popup = self.runtime.open_clipboard_history()
        popup.list.setCurrentRow(0)
        captured.clear()
        with mock.patch.object(QApplication.clipboard(), "setMimeData", side_effect=captured.append):
            popup.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier))
        self.assertTrue(captured[0].hasHtml())

    def test_popup_search_pin_delete(self):
        for value in ("apple pie", "banana", "cherry"):
            self.runtime.clip_history.add_text(value)
        with mock.patch("luxai.extensions_runtime._foreground_window", return_value=0):
            popup = self.runtime.open_clipboard_history()
        popup.search.setText("ban")
        visible = [popup.list.item(i) for i in range(popup.list.count()) if not popup.list.item(i).isHidden()]
        self.assertEqual(len(visible), 1)
        popup.search.clear()
        popup.list.setCurrentRow(2)  # apple pie
        popup.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_P, Qt.KeyboardModifier.ControlModifier))
        self.assertEqual(self.runtime.clip_history.ordered()[0]["text"], "apple pie")
        self.assertEqual(popup.list.count(), 3)  # refreshed live
        popup.list.setFocus()
        popup.list.setCurrentRow(1)
        popup.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier))
        self.assertEqual(len(self.runtime.clip_history.items), 2)

    def test_ai_actions_put_result_on_clipboard_and_top(self):
        item = self.runtime.clip_history.add_text("helo wrld")
        self.host.online_planner.transform_text.return_value = "hello world"

        class Inline:
            def __init__(self, target, **kwargs):
                self.target = target

            def start(self):
                self.target()

        with mock.patch("luxai.extensions_runtime.threading.Thread", Inline), \
                mock.patch.object(QApplication.clipboard(), "setText") as put:
            self.runtime._clip_ai(item["id"], "fix")
        self.host.online_planner.transform_text.assert_called_once_with("helo wrld", "fix")
        put.assert_called_once_with("hello world")
        self.assertEqual(self.runtime.clip_history.items[0]["text"], "hello world")

    def test_voice_paste_previous(self):
        self.runtime.clip_history.add_text("first copy")
        self.runtime.clip_history.add_text("current copy")
        with mock.patch.object(self.runtime, "_paste_clip") as paste, \
                mock.patch("luxai.extensions_runtime._foreground_window", return_value=55), \
                mock.patch("luxai.screen_interact._window_pid", return_value=1):
            answer = self.runtime.handle_text_request("Джарвис, вставь предыдущее")
        self.assertEqual(answer, "Вставил предыдущее.")
        first = next(entry for entry in self.runtime.clip_history.items if entry["text"] == "first copy")
        paste.assert_called_once_with(first["id"], False, 55)
        self.assertIsNone(self.runtime.handle_clipboard_request("вставь картинку"))


class SettingsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_page_sections_tags_and_count(self):
        from luxai.ui_extension_settings import PluginSettingsView, TagsField
        from luxai.extensions_runtime import ExtensionsRuntime
        host = mock.Mock()
        host.cfg = {"language": "ru"}
        host.online_planner.enabled.return_value = False
        runtime = ExtensionsRuntime(host)
        runtime.state = catalog.normalize_state({})
        runtime.clip_history.add_text("x")
        plugin = catalog.PLUGIN_BY_ID["clipboard_history"]
        view = PluginSettingsView(plugin, runtime.state["clipboard_history"], "ru", runtime=runtime)
        self.addCleanup(view.deleteLater)
        self.assertEqual(list(view.cards), ["basic", "key", "storage", "exclude", "ai"])
        self.assertEqual(view.nav["storage"].text(), "Хранение")
        tags = view.fields["exclude_apps"]
        self.assertIsInstance(tags, TagsField)
        self.assertIn("KeePassXC", tags.names)
        tags.input.setText("MyVault")
        tags._add()
        self.assertTrue(view.save_button.isEnabled())
        self.assertIn("MyVault", view.collect()["exclude_apps"])
        self.assertIn("Записей: 1", view.clip_row.hint_label.text())
        runtime.clear_clipboard_all()
        self.assertEqual(view.clip_row.hint_label.text(), "История пуста.")
        view.detach()


if __name__ == "__main__":
    unittest.main()
