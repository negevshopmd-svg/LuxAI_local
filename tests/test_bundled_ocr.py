"""Regression tests for automatically bundled Windows Tesseract OCR.

All network calls, installers, process invocations and disk paths are mocked.
No real OCR executable is downloaded or executed by these tests.
"""
from pathlib import Path
import hashlib
import importlib.util
import sys
import tempfile
import unittest
from unittest import mock

from luxai import ocr_setup
from luxai import screen


class BundledOCRTests(unittest.TestCase):
    def test_pinned_git_blob_hash_validates_exact_model_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "eng.traineddata"
            content = b"sample-ocr-model-binary"
            path.write_bytes(content)
            header = b"blob " + str(len(content)).encode("ascii") + b"\0"
            expected = hashlib.sha1(header + content).hexdigest()
            with mock.patch.dict(
                ocr_setup.MODEL_BLOBS,
                {"eng": (expected, len(content))},
            ):
                self.assertTrue(ocr_setup._model_is_verified(path, "eng"))
                path.write_bytes(content + b"corrupt")
                self.assertFalse(ocr_setup._model_is_verified(path, "eng"))

    def test_release_source_and_hash_are_pinned(self):
        self.assertIn("github.com/UB-Mannheim/tesseract/releases/download/", ocr_setup.INSTALLER_URL)
        self.assertEqual(ocr_setup.RELEASE, "5.4.0.20240606")
        self.assertEqual(
            ocr_setup.INSTALLER_SHA256,
            "c885fff6998e0608ba4bb8ab51436e1c6775c2bafc2559a19b423e18678b60c9",
        )
        self.assertEqual(set(ocr_setup.MODELS), {"rus", "eng"})
        self.assertTrue(all(
            x.startswith("https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/")
            for x in ocr_setup.MODELS.values()
        ))

    def test_bundled_ocr_is_found_before_stale_explicit_config(self):
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / "Tesseract-OCR" / "tesseract.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"MZ" + b"\0" * 15000)
            with mock.patch.object(ocr_setup, "WINDOWS_EXECUTABLE", executable), mock.patch(
                "luxai.ocr_setup.shutil.which", return_value=None
            ):
                self.assertEqual(
                    ocr_setup.find_tesseract("C:/old/missing/tesseract.exe"),
                    executable,
                )

    def test_checksum_mismatch_cannot_execute_installer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "ocr"
            target = root / "Tesseract-OCR"
            exe = target / "tesseract.exe"

            def corrupt_download(url, path, *, limit):
                path.write_bytes(b"MZ" + b"x" * 110000)
                return "0" * 64

            with mock.patch.object(ocr_setup, "OCR_ROOT", root), mock.patch.object(
                ocr_setup, "INSTALL_DIR", target
            ), mock.patch.object(
                ocr_setup, "WINDOWS_EXECUTABLE", exe
            ), mock.patch.object(
                ocr_setup.sys, "platform", "win32"
            ), mock.patch(
                "luxai.ocr_setup.struct.calcsize", return_value=8
            ), mock.patch(
                "luxai.ocr_setup._download_bounded", side_effect=corrupt_download
            ), mock.patch(
                "luxai.ocr_setup.subprocess.run"
            ) as running:
                with self.assertRaisesRegex(ocr_setup.OCRInstallError, "SHA-256"):
                    ocr_setup._install_binary()
                running.assert_not_called()
                self.assertFalse(exe.exists())

    def test_matching_checksum_installs_in_dedicated_data_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / ".luxai_data" / "ocr"
            target = root / "Tesseract-OCR"
            exe = target / "tesseract.exe"

            def valid_download(url, path, *, limit):
                path.write_bytes(b"MZ" + b"x" * 110000)
                return ocr_setup.INSTALLER_SHA256

            def simulate_installer(args, **kwargs):
                self.assertEqual(args[-1], "/D=" + str(target))
                self.assertEqual(args[1], "/S")
                self.assertEqual(kwargs["cwd"], str(root))
                exe.write_bytes(b"MZ" + b"x" * 15000)
                return mock.Mock(returncode=0)

            with mock.patch.object(ocr_setup, "OCR_ROOT", root), mock.patch.object(
                ocr_setup, "INSTALL_DIR", target
            ), mock.patch.object(
                ocr_setup, "WINDOWS_EXECUTABLE", exe
            ), mock.patch.object(
                ocr_setup.sys, "platform", "win32"
            ), mock.patch(
                "luxai.ocr_setup.struct.calcsize", return_value=8
            ), mock.patch(
                "luxai.ocr_setup._download_bounded", side_effect=valid_download
            ), mock.patch(
                "luxai.ocr_setup.subprocess.run", side_effect=simulate_installer
            ) as launched:
                self.assertEqual(ocr_setup._install_binary(), exe)
                launched.assert_called_once()
                self.assertTrue(exe.exists())

    def test_language_download_kept_only_after_success(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder) / "tessdata"

            def supply_model(url, target, *, limit):
                target.write_bytes(b"DATA" + b"x" * 120000)
                return "abc"

            with mock.patch.object(ocr_setup, "DATA_DIR", data), mock.patch(
                "luxai.ocr_setup._model_is_verified",
                side_effect=lambda path, lang: path.is_file() and path.stat().st_size >= 100000
            ), mock.patch(
                "luxai.ocr_setup._download_bounded", side_effect=supply_model
            ) as downloader:
                ocr_setup._install_languages()
                self.assertEqual(downloader.call_count, 2)
                self.assertTrue(ocr_setup.language_data_ready())
                ocr_setup._install_languages()
                self.assertEqual(downloader.call_count, 2)
            self.assertFalse(list(data.glob("*.partial")))

    def test_bundled_ocr_verified_offline_after_initial_install(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder) / "tessdata"
            data.mkdir()
            for name in ("rus", "eng"):
                (data / f"{name}.traineddata").write_bytes(b"DATA" + b"x" * 120000)
            exe = Path(folder) / "Tesseract-OCR" / "tesseract.exe"
            exe.parent.mkdir()
            exe.write_bytes(b"MZ" + b"x" * 15000)
            with mock.patch.object(ocr_setup, "DATA_DIR", data), mock.patch(
                "luxai.ocr_setup.language_data_ready", return_value=True
            ), mock.patch(
                "luxai.ocr_setup.find_tesseract", return_value=exe
            ), mock.patch(
                "luxai.ocr_setup.subprocess.run", return_value=mock.Mock(
                    returncode=0, stdout="List of available languages (2):\neng\nrus\n",
                    stderr="",
                )
            ) as process, mock.patch(
                "luxai.ocr_setup._download_bounded",
                side_effect=AssertionError("Network must NOT run after install"),
            ):
                self.assertEqual(
                    ocr_setup.ensure_tesseract(allow_download=False),
                    (exe, data),
                )
                cmd = process.call_args.args[0]
                self.assertIn("--tessdata-dir", cmd)
                self.assertIn(str(data), cmd)

    @unittest.skipUnless(
        importlib.util.find_spec("PIL") is not None,
        "Pillow is installed in the user's .venv, but not in minimal CI",
    )
    def test_first_ocr_includes_both_languages_without_manual_configuration(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as folder:
            image_path = Path(folder) / "shot.png"
            Image.new("RGB", (10, 10)).save(image_path)
            fake_exe = Path(folder) / "Tesseract-OCR" / "tesseract.exe"
            data = Path(folder) / "tessdata"
            with mock.patch("luxai.screen.ensure_tesseract", return_value=(fake_exe, data)), mock.patch(
                "luxai.screen.pytesseract.image_to_string",
                return_value="Привет! Hello!",
            ) as ocr:
                result = screen.read_screen_text(str(image_path))
            self.assertIn("Привет", result)
            self.assertEqual(ocr.call_args.kwargs["lang"], "rus+eng")
            self.assertIn("--tessdata-dir", ocr.call_args.kwargs["config"])
            self.assertIn(str(data), ocr.call_args.kwargs["config"])

    def test_win_installer_and_updater_schedule_ocr(self):
        root = Path(__file__).resolve().parents[1]
        install = (root / "install_windows.bat").read_text(encoding="utf-8")
        updater = (root / "Update.py").read_text(encoding="utf-8")
        self.assertIn("-m luxai.ocr_setup", install)
        self.assertIn('"luxai.ocr_setup"', updater)
        self.assertIn('".luxai_data"', updater)
        self.assertIn("OCR", updater)


if __name__ == "__main__":
    unittest.main()
