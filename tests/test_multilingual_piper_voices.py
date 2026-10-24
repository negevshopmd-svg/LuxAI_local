"""Offline tests for language-safe Piper voices and verified lazy downloads."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from luxai import voices


class PiperLanguageVoicesTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.patch_voices = mock.patch.object(voices, "VOICES_DIR", self.root)
        self.patch_voices.start()
        self.addCleanup(self.patch_voices.stop)
        patch_log = mock.patch.object(voices, "ERROR_LOG", self.root / "voice_error.log")
        patch_log.start()
        self.addCleanup(patch_log.stop)
        self.manager = voices.VoiceManager()
        self.manager.config = {}

    def create_voice(self, identifier, language):
        file = self.root / (identifier + ".onnx")
        file.write_bytes(b"x" * 101)
        file.with_suffix(".onnx.json").write_text(
            json.dumps({"language": {"code": language}}), encoding="utf-8"
        )
        return file

    def test_official_presets_for_three_languages(self):
        self.assertEqual(voices.VOICE_PRESETS["ru"]["id"], "ru_RU-dmitri-medium")
        self.assertEqual(voices.VOICE_PRESETS["ro"]["id"], "ro_RO-mihai-medium")
        self.assertEqual(voices.VOICE_PRESETS["en"]["id"], "en_US-lessac-medium")
        for lang in ("ru", "ro", "en"):
            self.assertTrue(voices.VOICE_PRESETS[lang]["directory"].startswith(lang + "/"))

    def test_selects_only_matching_language_and_never_other_installed_voice(self):
        russian = self.create_voice("ru_RU-dmitri-medium", "ru_RU")
        english = self.create_voice("en_US-lessac-medium", "en_US")
        self.manager.config["voice_id"] = "en_US-lessac-medium"
        with mock.patch.object(self.manager, "_download_voice", return_value=None) as download:
            self.assertEqual(self.manager._select_model("ru"), russian)
            self.assertEqual(self.manager._select_model("en"), english)
            self.assertIsNone(self.manager._select_model("ro"))
            download.assert_called_once_with("ro")

    def test_selected_english_preset_downloads_even_with_other_english_voice(self):
        self.create_voice("en_US-custom-medium", "en_US")
        self.manager.config["voice_id"] = "en_US-lessac-medium"
        with mock.patch.object(self.manager, "_download_voice", return_value=None) as download:
            self.assertIsNone(self.manager._select_model("en"))
            download.assert_called_once_with("en")

    def test_explicit_wrong_language_voice_is_not_used(self):
        russian = self.create_voice("ru_RU-dmitri-medium", "ru_RU")
        self.manager.config["voice_model_path"] = str(russian)
        with mock.patch.object(self.manager, "_download_voice", return_value=None) as dl:
            self.assertIsNone(self.manager._select_model("ro"))
            dl.assert_called_once_with("ro")

    def test_download_stream_validates_sha256_and_atomic_filename(self):
        data = b"validated local speech model"
        file = self.root / "ro_RO-mihai-medium.onnx"
        digest = hashlib.sha256(data).hexdigest()
        with mock.patch("luxai.voices.urllib.request.urlopen", return_value=io.BytesIO(data)) as request:
            voices.VoiceManager._download_file(
                "https://huggingface.co/rhasspy/piper-voices/resolve/main/ro/model.onnx",
                file, sha256=digest, minimum_size=5, maximum_size=1000
            )
            request.assert_called_once()
        self.assertEqual(file.read_bytes(), data)
        self.assertFalse((self.root / (file.name + ".download")).exists())

    def test_corrupt_download_is_not_installed(self):
        file = self.root / "ro_RO-mihai-medium.onnx"
        with mock.patch("luxai.voices.urllib.request.urlopen", return_value=io.BytesIO(b"broken")):
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                voices.VoiceManager._download_file(
                    "https://huggingface.co/example.onnx", file,
                    sha256="0" * 64, minimum_size=2, maximum_size=100
                )
        self.assertFalse(file.exists())
        self.assertFalse((self.root / (file.name + ".download")).exists())

    def test_download_new_voice_and_metadata_when_selected(self):
        binary = b"a" * 100
        metadata = json.dumps({"language": {"code": "ro_RO"}}).encode("utf-8") + b" " * 100
        sha = hashlib.sha256(binary).hexdigest()
        preset = {
            "id": "ro_RO-mihai-medium",
            "directory": "ro/ro_RO/mihai/medium",
            "language": "ro_RO",
            "sha256": sha,
        }
        def response(request, timeout=None):
            if request.full_url.endswith(".onnx.json"):
                return io.BytesIO(metadata)
            return io.BytesIO(binary)
        with (
            mock.patch.dict(voices.VOICE_PRESETS, {"ro": preset}),
            mock.patch.object(voices, "MIN_MODEL_BYTES", 80),
            mock.patch("luxai.voices.urllib.request.urlopen", side_effect=response) as download,
        ):
            result = self.manager._select_model("ro")
            self.assertEqual(result, self.root / "ro_RO-mihai-medium.onnx")
            def relevant_downloads():
                expected = ("ro_RO-mihai-medium.onnx",
                            "ro_RO-mihai-medium.onnx.json")
                return [
                    call.args[0].full_url
                    for call in download.call_args_list
                    if call.args and hasattr(call.args[0], "full_url")
                    and call.args[0].full_url.endswith(expected)
                ]
            # The patched urllib.request.urlopen is process-global; other
            # concurrent UI threads may use it during Windows CI. Count
            # only the two files belonging to this exact test voice.
            self.assertEqual(len(relevant_downloads()), 2)
            self.assertTrue(voices.VoiceManager._model_matches_language(result, "ro"))
            download.reset_mock()
            self.assertEqual(self.manager._select_model("ro"), result)
            self.assertEqual(relevant_downloads(), [])

    def test_missing_network_returns_none_and_no_partial_files(self):
        with mock.patch("luxai.voices.urllib.request.urlopen", side_effect=OSError("offline")):
            self.assertIsNone(self.manager._select_model("en"))
        self.assertFalse(list(self.root.glob("*.download")))
        self.assertFalse(list(self.root.glob("*.onnx")))


if __name__ == "__main__":
    unittest.main()
