"""Credential changes must update the live app without exposing secrets."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from luxai import secure_keys


class KeySourceTests(unittest.TestCase):
    def test_saved_key_source_matches_the_key_used_when_environment_also_exists(self):
        with tempfile.TemporaryDirectory() as folder:
            with (
                mock.patch.object(secure_keys, "SECRET_DIR", Path(folder) / "saved"),
                mock.patch.object(secure_keys, "LEGACY_SECRET_DIR", Path(folder) / "legacy"),
                mock.patch.object(secure_keys, "_win_crypt", side_effect=lambda data, encrypt: data[::-1]),
                mock.patch.dict(os.environ, {"OPENAI_API_KEY": "environment-example"}),
            ):
                secure_keys.store_api_key("ui-example", "openai")
                self.assertEqual(secure_keys.get_api_key("openai"), "ui-example")
                self.assertEqual(secure_keys.key_storage_status("openai"), "saved")
                secure_keys.clear_api_key("openai")
                self.assertEqual(secure_keys.get_api_key("openai"), "environment-example")
                self.assertEqual(secure_keys.key_storage_status("openai"), "environment")


class SettingsKeyDeletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def panel(self):
        from luxai.settings_panel import SettingsPanel
        changes = []
        with mock.patch("sounddevice.query_devices", return_value=[]):
            panel = SettingsPanel(
                {"microphone_enabled": False},
                lambda: changes.append(panel.collect()), lambda: None, lambda: None,
            )
        self.addCleanup(panel.close)
        return panel, changes

    def test_deleting_key_notifies_application_even_when_preferences_did_not_change(self):
        from PySide6.QtWidgets import QMessageBox
        panel, changes = self.panel()
        with (
            mock.patch("luxai.settings_panel.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes),
            mock.patch("luxai.settings_panel.clear_api_key") as clear,
        ):
            panel._clear_key()
        clear.assert_called_once_with(panel.online_provider.currentData())
        self.assertTrue(panel._autosave_timer.isActive())
        panel.flush_auto_save()
        self.assertEqual(len(changes), 1)
        self.assertNotIn("api_key", changes[0])
        panel.flush_auto_save()
        self.assertEqual(len(changes), 1)

    def test_cancelled_deletion_does_not_modify_storage_or_live_configuration(self):
        from PySide6.QtWidgets import QMessageBox
        panel, changes = self.panel()
        with (
            mock.patch("luxai.settings_panel.QMessageBox.question", return_value=QMessageBox.StandardButton.No),
            mock.patch("luxai.settings_panel.clear_api_key") as clear,
        ):
            panel._clear_key()
        clear.assert_not_called()
        panel.flush_auto_save()
        self.assertEqual(changes, [])


if __name__ == "__main__":
    unittest.main()
