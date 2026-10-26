"""An asynchronous API result certifies only the connection actually tested."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class CloudCheckContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def window(self, provider="custom", model="tested-model"):
        import main
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        filename = Path(folder.name) / "config.json"
        filename.write_text(json.dumps({
            "microphone_enabled": False, "tts_enabled": False,
            "online_agent_enabled": True, "online_provider": provider,
            "online_model": model,
            "online_custom_url": "https://example.com/v1/chat/completions",
        }), encoding="utf-8")
        for patcher in (
            mock.patch.object(main, "CONFIG", filename),
            mock.patch.object(main, "get_api_key", return_value="fake-stored-key"),
            mock.patch("sounddevice.query_devices", return_value=[]),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        window = main.MainWindow()
        self.addCleanup(window.close)
        return window, filename

    def start_api_check(self, window):
        # Hold the network result until after a deliberate UI change.
        with mock.patch("main.threading.Thread"):
            window.test_online_api()
        self.assertTrue(window._api_test_running)

    def test_changed_model_cannot_be_certified_or_overwritten_by_old_success(self):
        window, _ = self.window()
        self.start_api_check(window)
        window.settings_panel.online_model.setText("untested-model")
        with mock.patch.object(window, "save_settings") as save:
            window._on_api_test_result("custom", True, "OK", "old-fallback")
        save.assert_not_called()
        self.assertEqual(window.settings_panel.online_model.text(), "untested-model")
        self.assertIsNone(window._cloud_verified_signature)
        self.assertFalse(window._api_test_running)
        self.assertIsNone(window._api_test_requested_key)

    def test_changed_custom_endpoint_cannot_be_certified(self):
        window, _ = self.window()
        self.start_api_check(window)
        window.settings_panel.custom_api_url.setText("https://other.example/v1/chat/completions")
        with mock.patch.object(window, "save_settings") as save:
            window._on_api_test_result("custom", True, "OK", "tested-model")
        save.assert_not_called()
        self.assertIsNone(window._cloud_verified_signature)

    def test_changed_key_blocks_fallback_before_it_mutates_model(self):
        window, _ = self.window()
        self.start_api_check(window)
        window.settings_panel.api_key_entry.setText("fake-new-key")
        with mock.patch.object(window, "save_settings") as save:
            window._on_api_test_result("custom", True, "OK", "old-fallback")
        save.assert_not_called()
        self.assertEqual(window.settings_panel.online_model.text(), "tested-model")
        self.assertEqual(window.settings_panel.api_key_entry.text(), "fake-new-key")

    def test_matching_success_saves_exact_verified_fallback_model(self):
        window, filename = self.window("gemini", "gemini-old-model")
        self.start_api_check(window)
        window._on_api_test_result("gemini", True, "OK", "gemini-2.5-flash")
        self.assertEqual(json.loads(filename.read_text(encoding="utf-8"))["online_model"],
                         "gemini-2.5-flash")
        self.assertEqual(window._cloud_verified_signature, window._cloud_signature())

    def test_successful_recheck_releases_old_cooldown_for_same_credentials(self):
        window, _ = self.window()
        window.online_planner._blocked_until = float("inf")
        window.online_planner.last_error = "Old HTTP 503"
        self.start_api_check(window)
        window._on_api_test_result("custom", True, "OK", "tested-model")
        self.assertEqual(window.online_planner._blocked_until, 0)
        self.assertEqual(window.online_planner.last_error, "")

    def test_deleting_saved_key_resets_cooldown_when_environment_key_takes_over(self):
        window, _ = self.window()
        window.online_planner._blocked_until = float("inf")
        window.online_planner._cache["previous-account"] = {"action": "reply", "reply": "old"}
        with mock.patch("main.get_api_key", return_value="fake-environment-key"):
            window.save_settings()
        self.assertEqual(window.online_planner._blocked_until, 0)
        self.assertFalse(window.online_planner._cache)

    def test_failed_stored_connection_check_clears_previous_green_status(self):
        window, _ = self.window()
        window._cloud_verified_signature = window._cloud_signature()
        self.start_api_check(window)
        window._on_api_test_result("custom", False, "HTTP 503", None)
        self.assertIsNone(window._cloud_verified_signature)
        self.assertTrue(window._cloud_probe_failed)
        self.assertIn("503", window.cloud_details.text())

    def test_failed_draft_key_check_does_not_invalidate_other_stored_connection(self):
        window, _ = self.window()
        verified = window._cloud_verified_signature = window._cloud_signature()
        window.settings_panel.api_key_entry.setText("fake-draft-key")
        self.start_api_check(window)
        window._on_api_test_result("custom", False, "HTTP 401", None)
        self.assertEqual(window._cloud_verified_signature, verified)
        self.assertFalse(window._cloud_probe_failed)

    def test_failed_config_write_keeps_previous_runtime_configuration(self):
        window, filename = self.window()
        original = dict(window.cfg)
        window.settings_panel.online_model.setText("new-model")
        with mock.patch("main.save_config", side_effect=OSError("disk full")):
            self.assertFalse(window.save_settings())
        self.assertEqual(window.cfg, original)
        self.assertEqual(window.online_planner.config, original)
        self.assertEqual(json.loads(filename.read_text(encoding="utf-8")), original)

    def test_health_check_persists_fallback_before_reporting_working(self):
        window, filename = self.window("gemini", "gemini-old-model")
        signature = window._cloud_signature()
        window._cloud_probe_running = True
        window._on_cloud_check_result("gemini", signature, True, "OK", "gemini-2.5-flash")
        self.assertEqual(json.loads(filename.read_text(encoding="utf-8"))["online_model"],
                         "gemini-2.5-flash")
        self.assertEqual(window.online_planner.config["online_model"], "gemini-2.5-flash")
        self.assertEqual(window._cloud_verified_signature, window._cloud_signature())

    def test_health_check_cannot_replace_new_settings_draft(self):
        window, _ = self.window("gemini", "gemini-old-model")
        signature = window._cloud_signature()
        window.settings_panel.online_model.setText("gemini-new-draft")
        window._on_cloud_check_result("gemini", signature, True, "OK", "gemini-2.5-flash")
        self.assertEqual(window.settings_panel.online_model.text(), "gemini-new-draft")
        self.assertEqual(window.cfg["online_model"], "gemini-old-model")
        self.assertIsNone(window._cloud_verified_signature)

    def test_api_success_applies_preferences_edited_during_network_request(self):
        window, filename = self.window()
        self.start_api_check(window)
        panel = window.settings_panel
        panel.theme.setCurrentIndex(panel.theme.findData("light"))
        self.assertTrue(panel._autosave_timer.isActive())
        with mock.patch.object(window, "apply_appearance") as appearance:
            window._on_api_test_result("custom", True, "OK", "tested-model")
        appearance.assert_called_once_with()
        self.assertEqual(json.loads(filename.read_text(encoding="utf-8"))["ui_theme"], "light")
        self.assertFalse(panel._autosave_timer.isActive())

    def test_health_fallback_applies_preferences_instead_of_swallowing_autosave(self):
        window, filename = self.window("gemini", "gemini-old-model")
        signature = window._cloud_signature()
        panel = window.settings_panel
        panel.theme.setCurrentIndex(panel.theme.findData("light"))
        self.assertTrue(panel._autosave_timer.isActive())
        with mock.patch.object(window, "apply_appearance") as appearance:
            window._on_cloud_check_result("gemini", signature, True, "OK", "gemini-2.5-flash")
        appearance.assert_called_once_with()
        saved = json.loads(filename.read_text(encoding="utf-8"))
        self.assertEqual(saved["ui_theme"], "light")
        self.assertEqual(saved["online_model"], "gemini-2.5-flash")
        self.assertFalse(panel._autosave_timer.isActive())

    def test_health_worker_forwards_the_model_that_really_generated(self):
        window, _ = self.window("gemini", "gemini-old-model")
        results = []
        window.cloud_check_result.disconnect()
        window.cloud_check_result.connect(lambda *args: results.append(args))
        with mock.patch("main.check_api_key_detailed", return_value=(True, "OK", "gemini-2.5-flash")):
            window._cloud_check_worker("gemini", "test-signature", dict(window.cfg), "fake-key")
        self.assertEqual(results, [("gemini", "test-signature", True, "OK", "gemini-2.5-flash")])


if __name__ == "__main__":
    unittest.main()
