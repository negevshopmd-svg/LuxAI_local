"""Settings checks report actual versions and defer installation until exit."""
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from luxai import settings_updates as updates
from luxai.ui_i18n import get_ui_language, set_ui_language


class VersionCheckTests(unittest.TestCase):
    def test_patch_labels_and_invalid_responses(self):
        self.assertEqual(updates.version_key("0.3.9.g"), updates.version_key("0.3.9g"))
        self.assertGreater(updates.version_key("0.3.9g"), updates.version_key("0.3.9.e"))
        self.assertGreater(updates.version_key("0.3.10"), updates.version_key("0.3.9z"))
        for value in ("", "banana", "0.3.9g\nmalicious", "1.2.3;echo x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                updates.version_key(value)

    def test_fetch_is_bounded_and_validates_before_display(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"0.3.9g\n"
        with mock.patch.object(updates.urllib.request, "urlopen", return_value=response) as fetch:
            self.assertEqual(updates.fetch_latest_version(), "0.3.9g")
        response.read.assert_called_once_with(257)
        self.assertEqual(fetch.call_args.kwargs["timeout"], 12)
        response.read.return_value = b"g" * 257
        with mock.patch.object(updates.urllib.request, "urlopen", return_value=response), self.assertRaises(ValueError):
            updates.fetch_latest_version()

    def test_windows_handoff_uses_argument_list_and_fixed_shell_command(self):
        with tempfile.TemporaryDirectory(prefix="LuxAI & test ") as temporary:
            root = Path(temporary)
            (root / "Update.bat").write_text("@echo off\n", encoding="utf-8")
            with mock.patch.object(updates, "ROOT", root), mock.patch.object(updates.sys, "platform", "win32"), \
                    mock.patch.object(updates.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, create=True), \
                    mock.patch.object(updates.subprocess, "CREATE_NO_WINDOW", 134217728, create=True), \
                    mock.patch.object(updates.subprocess, "Popen") as launch:
                updates.launch_updater_after_exit()
            command = launch.call_args.args[0]
            self.assertEqual(command[:3], [updates.sys.executable, "-I", "-c"])
            self.assertEqual(command[4], str(root))
            self.assertFalse(launch.call_args.kwargs["shell"])
            self.assertEqual(launch.call_args.kwargs["cwd"], str(root))
            self.assertIn('"/d", "/c", "Update.bat"', command[3])
            self.assertIn("WaitForSingleObject(handle, 60000)", command[3])
            self.assertNotIn(str(root), command[3])

    def test_non_windows_never_launches_bundled_installer(self):
        with mock.patch.object(updates.sys, "platform", "linux"), \
                mock.patch.object(updates.subprocess, "Popen") as launch, self.assertRaises(OSError):
            updates.launch_updater_after_exit()
        launch.assert_not_called()


class SettingsUpdatesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def panel(self, config=None):
        self.addCleanup(set_ui_language, get_ui_language())
        set_ui_language("ru")
        with mock.patch.object(updates, "application_version", return_value="0.3.9.e"):
            panel = updates.SettingsUpdates(config or {})
        self.addCleanup(panel.close)
        return panel

    def finish(self, panel):
        deadline = time.monotonic() + 2
        while panel.checking and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertFalse(panel.checking)

    def test_check_runs_off_ui_thread_and_prevents_duplicate_requests(self):
        panel = self.panel()
        started, release = threading.Event(), threading.Event()
        caller = []

        def fetch():
            caller.append(threading.get_ident())
            started.set()
            release.wait(1)
            return "0.3.9g"

        with mock.patch.object(updates, "fetch_latest_version", side_effect=fetch) as check:
            panel.start_check()
            self.assertTrue(started.wait(1))
            self.assertTrue(panel.checking)
            self.assertFalse(panel.check_button.isEnabled())
            panel.start_check()
            release.set()
            self.finish(panel)
        self.assertEqual(check.call_count, 1)
        self.assertNotEqual(caller, [threading.get_ident()])
        self.assertEqual(panel.latest_version, "0.3.9g")
        self.assertIn("0.3.9g", panel.status.text())
        self.assertIsNotNone(panel.last_checked)
        self.assertTrue(panel.check_button.isEnabled())

    def test_failure_is_not_reported_as_current_and_can_retry(self):
        panel = self.panel()
        with mock.patch.object(updates, "fetch_latest_version", side_effect=OSError("offline")):
            panel.start_check()
            self.finish(panel)
        self.assertIsNone(panel.latest_version)
        self.assertIn("Не удалось", panel.status.text())
        self.assertTrue(panel.install_button.isHidden())
        with mock.patch.object(updates, "fetch_latest_version", return_value="0.3.9.e"):
            panel.start_check()
            self.finish(panel)
        self.assertEqual(panel.status.text(), "У вас последняя версия")

    def test_installed_newer_version_is_distinguished(self):
        panel = self.panel()
        panel._on_check_finished("0.3.9a", "")
        self.assertEqual(panel.status.text(), "Установленная версия новее опубликованной")
        self.assertTrue(panel.install_button.isHidden())

    def test_automatic_check_is_optional_once_per_settings_instance(self):
        panel = self.panel()
        changed = []
        panel.preferences_changed.connect(lambda: changed.append(True))
        with mock.patch.object(updates, "fetch_latest_version", return_value="0.3.9g") as fetch:
            panel.show()
            self.app.processEvents()
            fetch.assert_not_called()
            panel.automatic.setChecked(True)
            self.app.processEvents()
            self.finish(panel)
            panel.hide()
            panel.show()
            self.app.processEvents()
            self.assertEqual(fetch.call_count, 1)
        self.assertEqual(changed, [True])
        self.assertEqual(panel.collect(), {"check_updates_automatically": True})

    def test_install_cancellation_does_not_launch_or_quit(self):
        panel = self.panel()
        panel._on_check_finished("0.3.9g", "")
        quits = []
        panel.quit_requested.connect(lambda: quits.append(True))
        with mock.patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.No), \
                mock.patch.object(updates, "launch_updater_after_exit") as launch:
            panel.request_install()
        launch.assert_not_called()
        self.assertEqual(quits, [])

    def test_install_handoff_requests_shutdown_only_after_successful_launch(self):
        panel = self.panel()
        panel._on_check_finished("0.3.9g", "")
        quits = []
        panel.quit_requested.connect(lambda: quits.append(True))
        with mock.patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Yes), \
                mock.patch.object(updates, "launch_updater_after_exit", side_effect=OSError("missing")):
            panel.request_install()
        self.assertEqual(quits, [])
        with mock.patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Yes), \
                mock.patch.object(updates, "launch_updater_after_exit") as launch:
            panel.request_install()
        launch.assert_called_once_with()
        self.assertEqual(quits, [True])


if __name__ == "__main__":
    unittest.main()
