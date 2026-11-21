"""0.4.3: the browser extension is offered when captions start, installed with a guide, and detected."""
from __future__ import annotations

import json
import unittest
import urllib.request
from unittest import mock

from PySide6.QtWidgets import QApplication

from luxai import extensions_catalog as catalog
from luxai import film_captions as fc
from luxai import ui_browser_extension as ube

ORIGIN = "chrome-extension://" + "b" * 32


class HelloTests(unittest.TestCase):
    def test_hello_reaches_jarvis_with_the_extension_id(self):
        hellos = []
        bridge = fc.BridgeServer(lambda _r: None, port=47397, on_hello=hellos.append, token="k" * 48)
        self.assertTrue(bridge.start())
        self.addCleanup(bridge.stop)
        request = urllib.request.Request("http://127.0.0.1:47397/v1/hello", method="POST",
                                         data=json.dumps({"version": "1.0.0", "browser": "chrome"}).encode(),
                                         headers={"Content-Type": "application/json", "Origin": ORIGIN,
                                                  "X-Jarvis-Token": "k" * 48})
        with urllib.request.urlopen(request, timeout=3) as response:
            self.assertEqual(response.status, 200)
        self.assertEqual(hellos, [{"version": "1.0.0", "browser": "chrome", "extension": "b" * 32}])

    def test_hello_is_cleaned(self):
        self.assertEqual(fc.parse_hello(b'{"version": "1.0<script>", "browser": "x"}'),
                         {"version": "1.0", "browser": "chrome"})
        self.assertEqual(fc.parse_hello(b"garbage"), {"version": "", "browser": "chrome"})


class OfferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def runtime(self, meta=None):
        from luxai.extensions_runtime import ExtensionsRuntime
        host = mock.Mock()
        host.cfg = {"language": "ro", "extensions_meta": dict(meta or {})}
        runtime = ExtensionsRuntime(host)
        self.addCleanup(runtime.deleteLater)
        runtime.state = catalog.normalize_state({"live_captions": {"enabled": True, "settings": {}}})
        runtime.captions_visible = True
        return runtime

    def offer(self, runtime, answer=None):
        shown = []

        def exec_(box):
            shown.append(box.text())
            roles = {"yes": box.ButtonRole.AcceptRole, "never": box.ButtonRole.DestructiveRole}
            for button in box.buttons():
                if answer and box.buttonRole(button) == roles[answer]:
                    box.clickedButton = lambda b=button: b
            return 0
        with mock.patch.object(ube, "find_browser", return_value=("chrome", "chrome.exe")), \
                mock.patch("luxai.extensions_runtime.QMessageBox.exec", exec_), \
                mock.patch.object(runtime, "open_browser_extension") as install:
            runtime._offer_browser_extension()
        return shown, install

    def test_asks_once_when_the_extension_is_missing(self):
        runtime = self.runtime()
        shown, install = self.offer(runtime, answer="yes")
        self.assertEqual(len(shown), 1)
        install.assert_called_once()
        shown, _ = self.offer(runtime)
        self.assertEqual(shown, [])  # once per session

    def test_never_asks_when_installed_or_refused_or_no_chrome(self):
        installed = self.runtime({"browser_extension_seen": {"version": "1.0.0", "browser": "chrome"}})
        self.assertEqual(self.offer(installed)[0], [])
        refused = self.runtime({"browser_extension_never": True})
        self.assertEqual(self.offer(refused)[0], [])
        runtime = self.runtime()
        with mock.patch.object(ube, "find_browser", return_value=None):
            runtime._offer_browser_extension()
        self.assertFalse(runtime._extension_offered)

    def test_dont_ask_again_is_saved(self):
        runtime = self.runtime()
        self.offer(runtime, answer="never")
        self.assertTrue(runtime.host.cfg["extensions_meta"]["browser_extension_never"])

    def test_hello_or_a_report_marks_it_installed_and_turns_the_guide_green(self):
        runtime = self.runtime()
        dialog = ube.ExtensionInstallDialog("ro")
        self.addCleanup(dialog.deleteLater)
        runtime._extension_dialog = dialog
        runtime._on_extension_hello({"version": "1.0.0", "browser": "chrome"})
        self.assertTrue(runtime.extension_installed())
        self.assertTrue(dialog.done_already)
        self.assertIn("Chrome", dialog.status.text())
        fresh = self.runtime()
        fresh._on_film_report({"tab": 1, "page": "", "time": 1.0, "paused": True, "rate": 1.0, "duration": 0.0,
                               "media": []})
        self.assertTrue(fresh.extension_installed())


class GuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_guide_opens_chrome_with_the_address_on_the_clipboard(self):
        """Chrome ignores chrome:// on its command line (checked): the address is pasted by the user."""
        dialog = ube.ExtensionInstallDialog("en")
        self.addCleanup(dialog.deleteLater)
        with mock.patch.object(ube, "find_browser", return_value=("chrome", "C:/chrome.exe")), \
                mock.patch.object(ube.subprocess, "Popen") as popen:
            self.assertEqual(dialog.start(), "chrome")
        self.assertEqual(popen.call_args[0][0], ["C:/chrome.exe", "--new-window"])
        self.assertEqual(QApplication.clipboard().text(), "chrome://extensions")
        dialog.copy_button.click()
        self.assertEqual(QApplication.clipboard().text(), str(ube.FOLDER))

    def test_store_page_once_published(self):
        with mock.patch.object(ube, "STORE_ID", "abcdefghijklmnopabcdefghijklmnop"), \
                mock.patch.object(ube, "find_browser", return_value=("chrome", "C:/chrome.exe")), \
                mock.patch.object(ube.subprocess, "Popen") as popen:
            ube.open_extensions_page()
        self.assertIn("chromewebstore.google.com/detail/abcdefghijklmnopabcdefghijklmnop", popen.call_args[0][0][1])


if __name__ == "__main__":
    unittest.main()
