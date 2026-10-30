"""Real Qt paste keeps Explorer/image attachments out of the text draft."""
import ntpath
from pathlib import Path, PureWindowsPath
import tempfile
import unittest
from unittest import mock

from PySide6.QtCore import QEvent, QMimeData, Qt, QUrl
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from luxai.chat_attachments import load_attachment
from luxai import clipboard_attachments
from luxai.clipboard_attachments import (
    ClipboardAttachmentError, pasted_file_paths,
)
from luxai.ui_chat_composer import ChatPromptEdit
from luxai.ui_i18n import get_ui_language, set_ui_language


class Clipboard093cTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.addCleanup(set_ui_language, get_ui_language())
        set_ui_language("en")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.first = self.base / "fișier cu spații.txt"
        self.first.write_text("Personal file stays unchanged", encoding="utf-8")
        self.second = self.base / "second.bat"
        self.second.write_text("@echo Must not execute", encoding="utf-8")
        self.edit = ChatPromptEdit()
        self.edit.show()
        self.edit.setFocus()
        self.app.processEvents()
        self.addCleanup(self.close_edit)
        self.addCleanup(self.app.clipboard().clear)
        self.batches, self.errors = [], []
        self.edit.paths_pasted.connect(self.batches.append)
        self.edit.attachment_error.connect(self.errors.append)

    def close_edit(self):
        self.edit.close()
        self.edit.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def paste(self, mime):
        self.app.clipboard().setMimeData(mime)
        QTest.keyClick(self.edit, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()

    @staticmethod
    def image_mime():
        image = QImage(44, 32, QImage.Format.Format_ARGB32)
        image.fill(QColor("#d74c3f"))
        mime = QMimeData()
        mime.setImageData(image)
        return mime

    def test_explorer_urls_paste_files_without_inserting_their_locations(self):
        self.edit.setText("Please review these")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self.first)), QUrl.fromLocalFile(str(self.second))])
        with mock.patch("subprocess.Popen") as execute, mock.patch("urllib.request.urlopen") as network:
            self.paste(mime)
        self.assertEqual(self.batches, [[str(self.first), str(self.second)]])
        self.assertEqual(self.edit.text(), "Please review these")
        self.assertFalse(self.errors)
        execute.assert_not_called()
        network.assert_not_called()
        self.edit.release_pasted_files(self.batches[0])
        self.assertTrue(self.first.exists())
        self.assertTrue(self.second.exists())

    def test_image_only_paste_produces_local_png_snapshot_and_owned_cleanup(self):
        mime = self.image_mime()
        self.assertTrue(self.edit.canInsertFromMimeData(mime))
        self.paste(mime)
        self.assertEqual(len(self.batches), 1)
        path = Path(self.batches[0][0])
        self.assertTrue(path.is_file())
        self.assertTrue(path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
        attached = load_attachment(path)
        self.assertEqual(attached.kind, "image")
        decoded = QImage(str(path))
        self.assertEqual(decoded.size(), QImage(44, 32, QImage.Format.Format_RGB32).size())
        self.assertEqual(decoded.pixelColor(3, 4), QColor("#d74c3f"))
        self.assertEqual(self.edit.text(), "")
        self.edit.release_pasted_files([path, self.first])
        self.assertFalse(path.exists())
        self.assertTrue(self.first.exists())
        self.assertTrue(attached.content.startswith(b"\x89PNG"))
        self.assertTrue(attached.image_data_url.startswith("data:image/png;base64,"))

    def test_rejected_image_batch_cleanup_does_not_remove_an_earlier_pending_image(self):
        self.paste(self.image_mime())
        first = Path(self.batches[-1][0])
        self.paste(self.image_mime())
        second = Path(self.batches[-1][0])
        self.assertNotEqual(first, second)
        self.edit.release_pasted_files([second])
        self.assertTrue(first.exists())
        self.assertFalse(second.exists())
        self.edit.release_pasted_files([first])
        self.assertFalse(first.exists())

    def test_text_code_and_web_url_keep_native_text_paste(self):
        for value in ("Tell me about Python", "print('C:/data')\nvalue = 42", "https://example.com/photo.png"):
            with self.subTest(value=value):
                self.edit.clear()
                mime = QMimeData()
                mime.setText(value)
                self.paste(mime)
                self.assertEqual(self.edit.text(), value)
        self.assertFalse(self.batches)
        self.assertFalse(self.errors)

    def test_remote_url_mime_is_text_and_file_url_must_be_absolute(self):
        remote = QMimeData()
        remote.setUrls([QUrl("https://example.com/photo.png")])
        self.paste(remote)
        self.assertIn("https://example.com/photo.png", self.edit.text())
        self.assertFalse(self.batches)
        self.assertFalse(self.errors)
        self.edit.clear()
        relative = QMimeData()
        relative.setUrls([QUrl("file:relative.txt")])
        self.paste(relative)
        self.assertFalse(self.batches)
        self.assertEqual(self.edit.text(), "")
        self.assertEqual(len(self.errors), 1)

    def test_plain_local_paths_quoted_paths_and_file_urls_become_attachments(self):
        for text in (str(self.first), f'"{self.first}"\n"{self.second}"',
                     QUrl.fromLocalFile(str(self.first)).toString()):
            with self.subTest(text=text):
                mime = QMimeData()
                mime.setText(text)
                self.paste(mime)
                self.assertEqual(self.batches[-1][0], str(self.first))
                self.assertEqual(self.edit.text(), "")
        self.assertFalse(self.errors)

    def test_explicit_missing_url_reaches_reader_but_not_text_draft(self):
        missing = self.base / "already-removed.txt"
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(missing))])
        self.paste(mime)
        self.assertEqual(self.batches, [[str(missing)]])
        self.assertEqual(self.edit.text(), "")

    def test_mixed_remote_and_local_urls_are_rejected_as_one_batch(self):
        self.edit.setText("Keep my request")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self.first)), QUrl("https://example.com/other")])
        self.paste(mime)
        self.assertFalse(self.batches)
        self.assertEqual(len(self.errors), 1)
        self.assertIn("local files", self.errors[0])
        self.assertEqual(self.edit.text(), "Keep my request")

    def test_file_list_deduplicates_and_enforces_existing_attachment_count_limit(self):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self.first))] * 12)
        self.assertEqual(pasted_file_paths(mime), (str(self.first),))
        mime.setUrls([QUrl.fromLocalFile(str(self.base / f"{index}.txt")) for index in range(9)])
        self.paste(mime)
        self.assertFalse(self.batches)
        self.assertIn("8 files", self.errors[0])

    def test_native_windows_filename_format_and_invalid_relative_paths(self):
        mime = QMimeData()
        key = 'application/x-qt-windows-mime;value="FileNameW"'
        mime.setData(key, (str(self.first) + "\0").encode("utf-16-le"))
        self.assertEqual(pasted_file_paths(mime), (str(self.first),))
        mime.setData(key, "relative.txt\0".encode("utf-16-le"))
        with self.assertRaises(ClipboardAttachmentError):
            pasted_file_paths(mime)
        mime.setData(key, b"\xff")
        with self.assertRaises(ClipboardAttachmentError):
            pasted_file_paths(mime)

    def test_windows_slash_and_case_aliases_share_one_native_attachment_path(self):
        mime = QMimeData()
        aliases = ("C:/Users/Name/Documents/file.txt",
                   "C:\\Users\\Name\\Documents\\file.txt",
                   "c:/users/name/documents/file.txt")
        key = 'application/x-qt-windows-mime;value="FileNameW"'
        mime.setData(key, ("\0".join(aliases) + "\0").encode("utf-16-le"))
        # Exercise Windows lexical path semantics even on the Linux CI job.
        # PureWindowsPath never resolves a link or reads the filesystem.
        with (mock.patch.object(clipboard_attachments, "Path", PureWindowsPath),
              mock.patch.object(clipboard_attachments.os.path, "normcase", ntpath.normcase)):
            self.assertEqual(pasted_file_paths(mime),
                             ("C:\\Users\\Name\\Documents\\file.txt",))

    def test_image_limits_and_encoding_failure_report_error_without_any_path_paste(self):
        for patcher in (
            mock.patch("luxai.clipboard_attachments.MAX_IMAGE_PIXELS", 10),
            mock.patch("luxai.clipboard_attachments.MAX_FILE_BYTES", 10),
            mock.patch.object(QImage, "save", return_value=False),
        ):
            with patcher:
                self.paste(self.image_mime())
        self.assertFalse(self.batches)
        self.assertEqual(len(self.errors), 3)
        self.assertTrue(all("clipboard image" in value for value in self.errors))
        directory = self.edit._clipboard_images._directory
        if directory is not None:
            self.assertEqual(list(Path(directory.name).iterdir()), [])

    def test_prompt_grows_for_visual_lines_then_returns_to_compact_height(self):
        self.edit.resize(460, self.edit.height())
        self.edit.setText("One short line")
        self.app.processEvents()
        compact = self.edit.height()
        self.edit.setText("\n".join(["Another line"] * 6))
        self.app.processEvents()
        self.assertGreater(self.edit.height(), compact)
        self.assertLessEqual(self.edit.height(), 148)
        self.edit.setText("A long wrapped request with several words. " * 12)
        self.app.processEvents()
        self.assertGreater(self.edit.height(), compact)
        self.edit.clear()
        self.app.processEvents()
        self.assertEqual(self.edit.height(), compact)


if __name__ == "__main__":
    unittest.main()
