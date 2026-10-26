"""Cloud credential durability, UI truthfulness and Romanian subprocess Unicode."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from luxai import secure_keys
from luxai.cloud_status import cloud_status_text
from luxai.gguf_backend import IsolatedGGUF


class KeyPersistenceTests(unittest.TestCase):
    def test_key_is_still_available_on_next_read_after_ui_clears_field(self):
        with tempfile.TemporaryDirectory() as home:
            folder = Path(home)
            with (
                mock.patch.object(secure_keys, "SECRET_DIR", folder / "appdata"),
                mock.patch.object(secure_keys, "LEGACY_SECRET_DIR", folder / "old"),
                mock.patch.object(secure_keys, "_win_crypt",
                                  side_effect=lambda data, encrypt: data[::-1]),
                mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}),
            ):
                secure_keys.store_api_key("fake-local-only-key", "openai")
                self.assertTrue((folder / "appdata" / "openai_key.dpapi").exists())
                self.assertEqual(secure_keys.get_api_key("openai"), "fake-local-only-key")
                self.assertEqual(secure_keys.key_storage_status("openai"), "saved")
                self.assertEqual(secure_keys.get_api_key("openai"), "fake-local-only-key")

    def test_failed_encryption_verification_preserves_old_key(self):
        with tempfile.TemporaryDirectory() as home:
            folder = Path(home)
            with (
                mock.patch.object(secure_keys, "SECRET_DIR", folder / "appdata"),
                mock.patch.object(secure_keys, "LEGACY_SECRET_DIR", folder / "old"),
                mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}),
            ):
                with mock.patch.object(secure_keys, "_win_crypt",
                                       side_effect=lambda data, encrypt: data[::-1]):
                    secure_keys.store_api_key("previous-key", "openai")
                def broken(data, encrypt):
                    return data[::-1] if encrypt else b"WRONG"
                with mock.patch.object(secure_keys, "_win_crypt", side_effect=broken):
                    with self.assertRaisesRegex(OSError, "could not be recovered"):
                        secure_keys.store_api_key("new-secret", "openai")
                with mock.patch.object(secure_keys, "_win_crypt",
                                       side_effect=lambda data, encrypt: data[::-1]):
                    self.assertEqual(secure_keys.get_api_key("openai"), "previous-key")
                self.assertFalse((folder / "appdata" / "openai_key.dpapi.tmp").exists())

    def test_unreadable_windows_account_key_not_falsely_reported_saved(self):
        with tempfile.TemporaryDirectory() as home:
            folder = Path(home)
            with (
                mock.patch.object(secure_keys, "SECRET_DIR", folder / "appdata"),
                mock.patch.object(secure_keys, "LEGACY_SECRET_DIR", folder / "old"),
                mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}),
                mock.patch.object(secure_keys, "_win_crypt",
                                  side_effect=RuntimeError("Different Windows account")),
            ):
                (folder / "appdata").mkdir()
                (folder / "appdata" / "openai_key.dpapi").write_bytes(b"bad dpapi")
                self.assertEqual(secure_keys.key_storage_status("openai"), "unreadable")
                self.assertEqual(secure_keys.get_api_key("openai"), "")


class HealthStatusTests(unittest.TestCase):
    def test_only_real_success_is_green(self):
        for state in ("missing", "offline", "disabled", "checking", "unchecked"):
            with self.subTest(state=state):
                title, detail, color = cloud_status_text(state, "Gemini", "ro")
                self.assertNotEqual(color, "#3dbb77")
        title, detail, color = cloud_status_text("online", "Gemini", "ro")
        self.assertEqual(color, "#3dbb77")
        self.assertIn("funcționează", title)
        self.assertIn("Gemini", detail)

    def test_translation_of_cloud_verification(self):
        title, detail, color = cloud_status_text("online", "OpenRouter", "en")
        self.assertIn("works", title)
        title, detail, color = cloud_status_text("offline", "OpenRouter", "ru")
        self.assertIn("недоступен", title)

    def test_failure_names_selected_provider_and_preserves_literal_diagnostic(self):
        title, detail, _ = cloud_status_text("offline", "Gemini", "ro", "HTTP 503 {retry}")
        self.assertEqual(detail, "Gemini: HTTP 503 {retry}")


class GGUFUTF8Tests(unittest.TestCase):
    def test_romanian_diacritics_survive_real_worker_stdin_and_stdout(self):
        # Test a real subprocess, but stub native llama_cpp to avoid a model
        # download. This reproduces the Windows cp1252/charmap data path.
        with tempfile.TemporaryDirectory() as temporary:
            module = Path(temporary) / "llama_cpp.py"
            module.write_text(
                "class Llama:\n"
                "    def __init__(self, **kwargs): pass\n"
                "    def create_chat_completion(self, *, messages, **kwargs):\n"
                "        return {'choices': [{'message': {'content': messages[-1]['content']}}]}\n",
                encoding="utf-8",
            )
            path = os.pathsep.join(filter(None, [temporary, os.environ.get("PYTHONPATH", "")]))
            with mock.patch.dict(os.environ, {
                "PYTHONPATH": path, "PYTHONIOENCODING": "cp1252",
            }):
                words = "Vă mulțumesc, șase țări, înger, Ярвис"
                response = IsolatedGGUF("example.gguf").create_chat_completion(
                    messages=[{"role": "user", "content": words}]
                )
                self.assertEqual(response["choices"][0]["message"]["content"], words)


if __name__ == "__main__":
    unittest.main()
