"""Optional speech credentials and settings stay separate from chat credentials."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from luxai import secure_keys
from luxai.api_providers import PROVIDERS
from luxai.fish_tts import DEFAULT_FISH_VOICE


class FishSecretTests(unittest.TestCase):
    def test_fish_environment_key_does_not_add_a_chat_provider(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            mock.patch.object(secure_keys, "SECRET_DIR", Path(folder) / "current"),
            mock.patch.object(secure_keys, "LEGACY_SECRET_DIR", Path(folder) / "legacy"),
            mock.patch.dict(os.environ, {"FISH_API_KEY": "fish-environment-key"}),
        ):
            self.assertEqual(secure_keys.get_api_key("fish"), "fish-environment-key")
            self.assertEqual(secure_keys.key_storage_status("fish"), "environment")
        self.assertNotIn("fish", PROVIDERS)
        for provider in ("../fish", "Fish", "unknown"):
            with self.assertRaises(ValueError):
                secure_keys.get_api_key(provider)

    def test_saved_fish_key_is_independent_of_chat_and_overrides_environment(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            mock.patch.object(secure_keys, "SECRET_DIR", Path(folder) / "current"),
            mock.patch.object(secure_keys, "LEGACY_SECRET_DIR", Path(folder) / "legacy"),
            mock.patch.object(secure_keys, "_win_crypt", side_effect=lambda data, encrypt: data[::-1]),
            mock.patch.dict(os.environ, {"FISH_API_KEY": "fish-from-environment"}),
        ):
            secure_keys.store_api_key("chat-sample-key", "openai")
            secure_keys.store_api_key("fish-sample-key", "fish")
            self.assertEqual(secure_keys.get_api_key("fish"), "fish-sample-key")
            self.assertEqual(secure_keys.key_storage_status("fish"), "saved")
            self.assertNotIn(b"fish-sample-key", secure_keys._secret_file("fish").read_bytes())
            secure_keys.clear_api_key("fish")
            self.assertEqual(secure_keys.get_api_key("fish"), "fish-from-environment")
            self.assertEqual(secure_keys.get_api_key("openai"), "chat-sample-key")

    @unittest.skipUnless(sys.platform == "win32", "Native Windows DPAPI")
    def test_native_windows_fish_dpapi_roundtrip_and_chat_isolation(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            mock.patch.object(secure_keys, "SECRET_DIR", Path(folder) / "current"),
            mock.patch.object(secure_keys, "LEGACY_SECRET_DIR", Path(folder) / "legacy"),
            mock.patch.dict(os.environ, {"FISH_API_KEY": ""}),
        ):
            secure_keys.store_api_key("local-chat-test-key", "openai")
            secure_keys.store_api_key("local-fish-test-key", "fish")
            data = secure_keys._secret_file("fish").read_bytes()
            self.assertNotIn(b"local-fish-test-key", data)
            self.assertEqual(secure_keys.get_api_key("fish"), "local-fish-test-key")
            self.assertEqual(secure_keys.key_storage_status("fish"), "saved")
            secure_keys.clear_api_key("fish")
            self.assertEqual(secure_keys.get_api_key("fish"), "")
            self.assertEqual(secure_keys.get_api_key("openai"), "local-chat-test-key")


class FishSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def panel(self, values=None):
        from luxai.settings_panel import SettingsPanel
        from luxai.ui_i18n import get_ui_language, set_ui_language
        self.addCleanup(set_ui_language, get_ui_language())
        set_ui_language("ru")
        saved = []
        with (
            mock.patch("sounddevice.query_devices", return_value=[]),
            mock.patch("luxai.settings_panel.key_storage_status", return_value="missing"),
        ):
            panel = SettingsPanel(
                {"microphone_enabled": False, "tts_enabled": False, **(values or {})},
                lambda: saved.append(panel.collect()), lambda: None, lambda: None,
            )
        self.addCleanup(panel.close)
        return panel, saved

    def test_default_stays_piper_and_fish_controls_are_conditional(self):
        panel, saved = self.panel()
        self.assertEqual(panel.voice_engine.currentData(), "piper")
        self.assertTrue(panel.fish_controls.isHidden())
        self.assertTrue(panel.voice_id.isEnabled())
        self.assertEqual(panel.collect()["fish_voice_id"], DEFAULT_FISH_VOICE)
        self.assertFalse(panel._autosave_timer.isActive())
        panel.flush_auto_save()
        self.assertEqual(saved, [])
        panel.voice_engine.setCurrentIndex(panel.voice_engine.findData("fish"))
        self.assertFalse(panel.fish_controls.isHidden())
        self.assertFalse(panel.voice_id.isEnabled())
        panel.flush_auto_save()
        self.assertEqual(saved[-1]["voice_engine"], "fish")

    def test_secret_draft_is_not_collected_or_committed_while_typing(self):
        from PySide6.QtWidgets import QLineEdit
        panel, saved = self.panel({"voice_engine": "fish"})
        panel.fish_api_key.setText("fish-example-draft")
        self.assertEqual(panel.fish_api_key.echoMode(), QLineEdit.EchoMode.Password)
        self.assertFalse(panel._autosave_timer.isActive())
        self.assertEqual(panel.fish_key_ready_for_save(), "")
        panel.weather_city.setText("Orhei")
        panel.flush_auto_save()
        self.assertNotIn("fish-example-draft", json.dumps(saved))
        self.assertEqual(panel.fish_key_ready_for_save(), "")
        panel.fish_api_key.editingFinished.emit()
        self.assertTrue(panel._autosave_timer.isActive())
        self.assertEqual(panel.fish_key_ready_for_save(), "fish-example-draft")
        self.assertNotIn("fish_api_key", panel.collect())

    def test_voice_link_commits_only_when_finished_and_invalid_draft_keeps_last_voice(self):
        previous = "a" * 32
        panel, saved = self.panel({"voice_engine": "fish", "fish_voice_id": previous})
        panel.fish_voice_id.setText("https://fish.audio/ru/m/" + DEFAULT_FISH_VOICE + "/")
        self.assertEqual(panel.collect()["fish_voice_id"], previous)
        self.assertFalse(panel._autosave_timer.isActive())
        panel.fish_voice_id.editingFinished.emit()
        panel.flush_auto_save()
        self.assertEqual(saved[-1]["fish_voice_id"], DEFAULT_FISH_VOICE)
        self.assertEqual(panel.fish_voice_id.text(), DEFAULT_FISH_VOICE)
        panel.fish_voice_id.setText("https://example.com/not-a-fish-voice")
        panel.fish_voice_id.editingFinished.emit()
        self.assertTrue(panel._fish_voice_invalid)
        self.assertFalse(panel.prepare_fish_preview())
        panel.weather_city.setText("Cahul")
        panel.flush_auto_save()
        self.assertEqual(saved[-1]["fish_voice_id"], DEFAULT_FISH_VOICE)
        self.assertEqual(saved[-1]["weather_city"], "Cahul")
        panel.fish_jarvis_voice.click()
        self.assertFalse(panel._fish_voice_invalid)
        self.assertEqual(panel.fish_voice_id.text(), DEFAULT_FISH_VOICE)

    def test_invalid_stored_voice_does_not_break_settings(self):
        panel, _ = self.panel({"fish_voice_id": "invalid"})
        self.assertEqual(panel.collect()["fish_voice_id"], DEFAULT_FISH_VOICE)

    def test_translation_keeps_secret_and_voice_drafts_and_shows_truthful_status(self):
        from luxai.ui_i18n import set_ui_language
        panel, _ = self.panel({"voice_engine": "fish"})
        panel.fish_api_key.setText("unfinished-fish-key")
        panel.fish_voice_id.setText("invalid")
        panel.fish_voice_id.editingFinished.emit()
        for language, word in (("ro", "Introdu"), ("en", "Enter"), ("ru", "Введите")):
            set_ui_language(language)
            with mock.patch("luxai.settings_panel.key_storage_status", return_value="saved"):
                panel.retranslate(language)
            self.assertIn(word, panel.fish_voice_status.text())
            self.assertEqual(panel.fish_api_key.text(), "unfinished-fish-key")
            self.assertEqual(panel.fish_voice_id.text(), "invalid")
            self.assertEqual(panel.fish_key_ready_for_save(), "")
        self.assertIn("при озвучке", panel.fish_key_status.text())

    def test_key_and_library_buttons_open_fish_pages_only(self):
        panel, _ = self.panel({"voice_engine": "fish"})
        with mock.patch("luxai.settings_panel.webbrowser.open") as open_page:
            panel.fish_keys_button.click()
            panel.fish_library_button.click()
        self.assertEqual(open_page.call_args_list, [
            mock.call("https://fish.audio/app/api-keys/"),
            mock.call("https://fish.audio/discovery/"),
        ])


class FishSettingsIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import main
        from luxai.ui_i18n import get_ui_language, set_ui_language
        self.addCleanup(set_ui_language, get_ui_language())
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.config = Path(folder.name) / "config.json"
        self.config.write_text(json.dumps({
            "microphone_enabled": False, "tts_enabled": False,
            "online_agent_enabled": False, "ui_animations": False,
            "minimize_to_tray": False, "ui_language": "ru", "language": "auto",
            "voice_engine": "fish", "response_language": "ru",
        }), encoding="utf-8")
        patcher = mock.patch.object(main, "CONFIG", self.config)
        patcher.start()
        self.addCleanup(patcher.stop)
        with (
            mock.patch("sounddevice.query_devices", return_value=[]),
            mock.patch.object(main.MainWindow, "_ocr_setup_worker"),
        ):
            self.window = main.MainWindow()
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window._quitting = True
        self.window.close()

    def test_saved_fish_key_never_enters_config_and_does_not_change_chat_provider(self):
        import main
        window, panel = self.window, self.window.settings_panel
        provider = panel.online_provider.currentData()
        panel.fish_api_key.setText("fish-local-ui-key")
        panel.fish_api_key.editingFinished.emit()
        with (
            mock.patch.object(main, "store_api_key") as store,
            mock.patch.object(main, "get_api_key", side_effect=lambda name="openai": "fish-local-ui-key" if name == "fish" else ""),
            mock.patch("luxai.settings_panel.key_storage_status", return_value="saved"),
        ):
            self.assertTrue(window.save_settings())
        store.assert_called_once_with("fish-local-ui-key", "fish")
        saved = self.config.read_text(encoding="utf-8")
        self.assertNotIn("fish-local-ui-key", saved)
        self.assertNotIn("fish_api_key", json.loads(saved))
        self.assertEqual(panel.online_provider.currentData(), provider)
        self.assertEqual(panel.fish_api_key.text(), "")

    def test_failed_secret_save_retains_draft_and_does_not_commit_settings_or_preview(self):
        import main
        panel = self.window.settings_panel
        before = self.config.read_bytes()
        panel.fish_api_key.setText("fish-unsaved-key")
        with (
            mock.patch.object(main, "store_api_key", side_effect=OSError("Windows crypto unavailable")),
            mock.patch.object(self.window, "_queue_speech") as queue_speech,
        ):
            self.window.preview_voice()
        self.assertEqual(panel.fish_api_key.text(), "fish-unsaved-key")
        self.assertEqual(self.config.read_bytes(), before)
        self.assertIn("Не удалось", panel.fish_key_status.text())
        self.assertNotIn("fish-unsaved-key", panel.fish_key_status.text())
        queue_speech.assert_not_called()
        # Stop cleanup from retrying the deliberately failing pending draft.
        panel.fish_api_key.clear()
        panel.mark_auto_saved()

    def test_preview_uses_current_fish_settings_and_response_language(self):
        import main
        panel = self.window.settings_panel
        other_voice = "b" * 32
        panel.fish_voice_id.setText("https://fish.audio/m/" + other_voice)
        with (
            mock.patch.object(main, "get_api_key", side_effect=lambda name="openai": "fish-env-key" if name == "fish" else ""),
            mock.patch.object(self.window, "_queue_speech") as queue_speech,
        ):
            self.window.preview_voice()
        self.assertEqual(self.window.cfg["fish_voice_id"], other_voice)
        self.assertEqual(json.loads(self.config.read_text(encoding="utf-8"))["fish_voice_id"], other_voice)
        queue_speech.assert_called_once_with("Здравствуйте. Я Джарвис, ваш голосовой помощник.", "ru")
        self.assertEqual(self.window.cfg["language"], "auto")

    def test_missing_key_or_invalid_voice_does_not_queue_network_speech(self):
        import main
        panel = self.window.settings_panel
        with (
            mock.patch.object(main, "get_api_key", return_value=""),
            mock.patch.object(self.window, "_queue_speech") as queue_speech,
        ):
            self.window.preview_voice()
            self.assertIn("API-ключ Fish Audio", panel.fish_key_status.text())
            panel.fish_voice_id.setText("broken-voice")
            self.window.preview_voice()
        queue_speech.assert_not_called()
        self.assertTrue(panel._fish_voice_invalid)


if __name__ == "__main__":
    unittest.main()
