"""Real attachment reads, bounded previews and confirmed atomic edits."""
import base64
from dataclasses import FrozenInstanceError
import io
import importlib.util
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zipfile

from PIL import Image

from luxai import chat_attachments as files


class ChatAttachmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def put(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def docx(self):
        xml = (b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
               b'<w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
               b'<w:r><w:rPr><w:b/></w:rPr><w:t>Heading</w:t></w:r></w:p>'
               b'<w:p><w:r><w:t>Old body</w:t></w:r></w:p></w:body></w:document>')
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
            archive.writestr("word/document.xml", xml)
            archive.writestr("word/media/preserved.bin", b"unrelated embedded data")
        return self.put("document.docx", output.getvalue())

    def test_snapshot_is_immutable_and_confirmed_edit_preserves_bom_crlf_and_backup(self):
        original = b"\xef\xbb\xbfOld\r\nBody\r\n"
        path = self.put("note.md", original)
        attachment = files.load_attachment(path)
        self.assertEqual(attachment.text, "Old\nBody\n")
        with self.assertRaises(FrozenInstanceError):
            attachment.text = "changed"
        proposal = files.propose_text_edit((attachment,), attachment.id, "New\nBody\n")
        self.assertIn("-Old", proposal.diff)
        self.assertIn("+New", proposal.diff)
        self.assertEqual(path.read_bytes(), original)
        with self.assertRaisesRegex(files.AttachmentError, "Preview and confirm"):
            files.apply_text_edit(proposal, backup_root=self.root / "backups")
        result = files.apply_text_edit(proposal, confirmed=True, backup_root=self.root / "backups")
        self.assertEqual(path.read_bytes(), b"\xef\xbb\xbfNew\r\nBody\r\n")
        self.assertEqual(result.backup_path.read_bytes(), original)

    def test_windows1251_and_utf16_big_endian_preserve_original_encoding(self):
        for name, data, expected in (
            ("russian.txt", "Привет\r\n".encode("cp1251"), "Пока\r\n".encode("cp1251")),
            ("unicode.txt", b"\xfe\xff" + "Привет\r\n".encode("utf-16-be"),
             b"\xfe\xff" + "Пока\r\n".encode("utf-16-be")),
        ):
            with self.subTest(name=name):
                path = self.put(name, data)
                attachment = files.load_attachment(path)
                proposal = files.propose_text_edit([attachment], attachment.id, "Пока\n")
                files.apply_text_edit(proposal, confirmed=True, backup_root=self.root / "backups")
                self.assertEqual(path.read_bytes(), expected)

    def test_unrepresentable_edit_is_utf8_export_only(self):
        path = self.put("legacy.txt", "Привет".encode("cp1251"))
        attachment = files.load_attachment(path)
        proposal = files.propose_text_edit([attachment], attachment.id, "Привет 😀")
        self.assertTrue(proposal.export_only)
        with self.assertRaises(files.AttachmentError):
            files.apply_text_edit(proposal, confirmed=True, backup_root=self.root / "backups")
        destination = self.root / "unicode-copy.txt"
        files.save_text_copy(proposal, destination)
        self.assertEqual(destination.read_text(encoding="utf-8"), "Привет 😀")
        self.assertEqual(path.read_bytes(), "Привет".encode("cp1251"))

    def test_file_limits_and_total_budget_are_checked_before_extraction(self):
        huge = self.root / "huge.txt"
        with huge.open("wb") as output:
            output.truncate(files.MAX_FILE_BYTES + 1)
        with self.assertRaisesRegex(files.AttachmentError, "10 MB"):
            files.load_attachment(huge)
        paths = []
        for number in range(3):
            path = self.root / f"medium{number}.txt"
            with path.open("wb") as output:
                output.truncate(8 * 1024 * 1024)
            paths.append(path)
        with mock.patch.object(files, "load_attachment") as extract:
            with self.assertRaisesRegex(files.AttachmentError, "20 MB"):
                files.load_attachments(paths)
            extract.assert_not_called()
        with self.assertRaisesRegex(files.AttachmentError, "8 attachments"):
            files.load_attachments([self.root / "missing"] * 9)

    def test_duplicate_files_are_one_attachment_and_source_code_is_never_executed(self):
        path = self.put("example.py", b"raise RuntimeError('must never execute')\n")
        selected = files.load_attachments([path, path])
        self.assertEqual(len(selected), 1)
        self.assertIn("must never execute", selected[0].text)

    def test_unknown_binary_and_binary_disguised_as_text_return_precise_errors(self):
        unknown = self.put("program.exe", b"MZ\x00dangerous")
        with self.assertRaisesRegex(files.AttachmentError, "Unsupported file type .exe"):
            files.load_attachment(unknown)
        disguised = self.put("binary.txt", b"hello\x00world")
        with self.assertRaisesRegex(files.AttachmentError, "binary data"):
            files.load_attachment(disguised)
        self.assertEqual(unknown.read_bytes(), b"MZ\x00dangerous")

    def test_long_or_mixed_newline_text_is_read_only_and_context_stays_bounded(self):
        for name, content in (("long.txt", b"x" * (files.MAX_EXTRACTED_CHARS + 20)),
                              ("mixed.txt", b"first\r\nsecond\n")):
            attachment = files.load_attachment(self.put(name, content))
            self.assertFalse(attachment.editable)
            with self.assertRaises(files.AttachmentError):
                files.propose_text_edit([attachment], attachment.id, "replacement")
        attachment = files.load_attachment(self.put("context.txt", b"hello " * 100))
        context = files.attachment_context([attachment], max_chars=240)
        self.assertLessEqual(len(context), 240)
        self.assertIn("Context truncated", context)
        self.assertNotIn(str(self.root), context)
        self.assertEqual(files.attachment_context([attachment], max_chars=0), "")

    def test_only_selected_attachment_id_can_be_edited(self):
        attachment = files.load_attachment(self.put("selected.txt", b"selected"))
        unrelated = self.put("unrelated.txt", b"personal")
        with self.assertRaisesRegex(files.AttachmentError, "not one of the selected"):
            files.propose_text_edit([attachment], str(unrelated), "overwrite")
        self.assertEqual(unrelated.read_bytes(), b"personal")

    def test_invalid_unicode_and_hidden_binary_edits_are_rejected_before_preview(self):
        path = self.put("selected.txt", b"text")
        attachment = files.load_attachment(path)
        for replacement in ("hidden\x00binary", "invalid\ud800Unicode", "Line one\vLine two"):
            with self.subTest(text=repr(replacement)), self.assertRaises(files.AttachmentError):
                files.propose_text_edit([attachment], attachment.id, replacement)
            self.assertEqual(path.read_bytes(), b"text")

    def test_external_changes_prevent_apply_even_after_a_valid_preview(self):
        path = self.put("selected.txt", b"old")
        attachment = files.load_attachment(path)
        proposal = files.propose_text_edit([attachment], attachment.id, "new")
        path.write_bytes(b"external personal change")
        with self.assertRaisesRegex(files.AttachmentError, "changed outside"):
            files.apply_text_edit(proposal, confirmed=True, backup_root=self.root / "backups")
        self.assertEqual(path.read_bytes(), b"external personal change")
        self.assertFalse((self.root / "backups").exists())

    def test_symlink_selection_or_replacement_never_reads_or_changes_other_files(self):
        target = self.put("target.txt", b"personal")
        link = self.root / "linked.txt"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("Symlinks are unavailable for this Windows account.")
        with self.assertRaisesRegex(files.AttachmentError, "Linked"):
            files.load_attachment(link)
        chosen = self.put("selected.txt", b"selected")
        attachment = files.load_attachment(chosen)
        proposal = files.propose_text_edit([attachment], attachment.id, "new")
        chosen.unlink()
        chosen.symlink_to(target)
        with self.assertRaisesRegex(files.AttachmentError, "Linked"):
            files.apply_text_edit(proposal, confirmed=True, backup_root=self.root / "backups")
        self.assertEqual(target.read_bytes(), b"personal")

    def test_windows_reparse_ancestor_is_rejected_before_file_read(self):
        path = self.put("reparse-folder/selected.txt", b"personal")
        real_lstat = Path.lstat

        def inspect(candidate):
            if candidate == path.parent:
                return SimpleNamespace(st_mode=0o040755, st_file_attributes=0x400)
            return real_lstat(candidate)

        with mock.patch.object(Path, "lstat", autospec=True, side_effect=inspect):
            with mock.patch.object(files.os, "open") as read:
                with self.assertRaisesRegex(files.AttachmentError, "Linked"):
                    files.load_attachment(path)
                read.assert_not_called()

    def test_backup_parent_link_does_not_create_directories_outside_destination(self):
        external = self.root / "external"
        external.mkdir()
        link = self.root / "backup-link"
        try:
            link.symlink_to(external, target_is_directory=True)
        except OSError:
            self.skipTest("Symlinks are unavailable for this Windows account.")
        path = self.put("selected.txt", b"selected")
        attachment = files.load_attachment(path)
        proposal = files.propose_text_edit([attachment], attachment.id, "new")
        with self.assertRaisesRegex(files.AttachmentError, "Linked"):
            files.apply_text_edit(proposal, confirmed=True, backup_root=link / "must-not-create")
        self.assertFalse((external / "must-not-create").exists())
        self.assertEqual(path.read_bytes(), b"selected")

    def test_failed_atomic_replace_retains_original_and_recovery_backup(self):
        path = self.put("selected.txt", b"old")
        attachment = files.load_attachment(path)
        proposal = files.propose_text_edit([attachment], attachment.id, "new")
        with mock.patch.object(files.os, "replace", side_effect=PermissionError("locked")):
            with self.assertRaises(files.AttachmentError):
                files.apply_text_edit(proposal, confirmed=True, backup_root=self.root / "backups")
        self.assertEqual(path.read_bytes(), b"old")
        self.assertEqual(next((self.root / "backups").iterdir()).read_bytes(), b"old")
        self.assertEqual(list(self.root.glob(".luxai-edit-*")), [])

    def test_save_copy_requires_new_explicit_supported_destination(self):
        path = self.put("selected.json", b'{"old":true}')
        attachment = files.load_attachment(path)
        proposal = files.propose_text_edit([attachment], attachment.id, '{"new":true}')
        with self.assertRaisesRegex(files.AttachmentError, "already exists"):
            files.save_text_copy(proposal, path)
        with self.assertRaisesRegex(files.AttachmentError, "Choose .txt"):
            files.save_text_copy(proposal, self.root / "copy.exe")
        destination = self.root / "copy.json"
        files.save_text_copy(proposal, destination)
        self.assertEqual(destination.read_bytes(), b'{"new":true}')
        self.assertEqual(path.read_bytes(), b'{"old":true}')

    def test_image_loading_validates_downsamples_and_never_runs_ocr(self):
        path = self.root / "image.png"
        Image.new("RGBA", (2000, 1000), (20, 50, 80, 150)).save(path)
        with mock.patch.object(files, "extract_image_text", side_effect=AssertionError("OCR on add")):
            attachment = files.load_attachment(path)
        self.assertEqual(attachment.kind, "image")
        self.assertEqual(attachment.text, "")
        prepared = base64.b64decode(attachment.image_data_url.partition(",")[2])
        with Image.open(io.BytesIO(prepared)) as image:
            self.assertEqual(image.size, (1600, 800))
            self.assertEqual(image.format, "PNG")
        invalid = self.put("invalid.jpg", b"not an image")
        with self.assertRaisesRegex(files.AttachmentError, "decode this image"):
            files.load_attachment(invalid)

    def test_local_ocr_is_explicit_offline_and_uses_safe_process_arguments(self):
        path = self.root / "image.png"
        Image.new("RGB", (20, 20), "white").save(path)
        attachment = files.load_attachment(path)
        completed = mock.Mock(returncode=0, stdout="local recognized text")
        with mock.patch("luxai.ocr_setup.ensure_tesseract", return_value=(Path("tesseract"), Path("models"))) as setup:
            with mock.patch.object(files.subprocess, "run", return_value=completed) as run:
                self.assertEqual(files.extract_image_text(attachment), "local recognized text")
        setup.assert_called_once_with(allow_download=False)
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertIn("rus+eng", run.call_args.args[0])

    def test_docx_same_paragraph_edit_preserves_other_package_parts(self):
        path = self.docx()
        original = path.read_bytes()
        attachment = files.load_attachment(path)
        self.assertEqual(attachment.text, "Heading\nOld body")
        proposal = files.propose_text_edit([attachment], attachment.id, "Heading\nNew body")
        self.assertFalse(proposal.export_only)
        result = files.apply_text_edit(proposal, confirmed=True, backup_root=self.root / "backups")
        self.assertEqual(result.backup_path.read_bytes(), original)
        self.assertEqual(files.load_attachment(path).text, "Heading\nNew body")
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(archive.read("word/media/preserved.bin"), b"unrelated embedded data")
            self.assertIn(b"Heading1", archive.read("word/document.xml"))

    def test_docx_manual_breaks_round_trip_as_text_lines_and_stay_breaks_in_docx(self):
        output = io.BytesIO()
        with zipfile.ZipFile(self.docx()) as original, zipfile.ZipFile(output, "w") as target:
            for info in original.infolist():
                data = original.read(info.filename)
                if info.filename == "word/document.xml":
                    data = data.replace(b"<w:t>Old body</w:t>",
                                        b"<w:t>Old</w:t><w:br/><w:t>body</w:t>")
                target.writestr(info, data)
        original = output.getvalue()
        path = self.put("line-breaks.docx", original)
        attachment = files.load_attachment(path)
        self.assertEqual(attachment.text, "Heading\nOld\vbody")
        proposal = files.propose_text_edit([attachment], attachment.id, "Heading\nNew\vbody")
        self.assertFalse(proposal.export_only)

        destination = self.root / "line-breaks.txt"
        files.save_text_copy(proposal, destination)
        self.assertEqual(destination.read_bytes(), b"Heading\nNew\nbody")
        self.assertEqual(files.load_attachment(destination).text, "Heading\nNew\nbody")
        self.assertEqual(path.read_bytes(), original)

        result = files.apply_text_edit(proposal, confirmed=True, backup_root=self.root / "backups")
        self.assertEqual(files.load_attachment(path).text, "Heading\nNew\vbody")
        self.assertEqual(result.backup_path.read_bytes(), original)

    def test_docx_structural_change_is_explicit_text_export_and_preserves_original(self):
        path = self.docx()
        original = path.read_bytes()
        attachment = files.load_attachment(path)
        proposal = files.propose_text_edit([attachment], attachment.id, "One paragraph instead of two")
        self.assertTrue(proposal.export_only)
        with self.assertRaises(files.AttachmentError):
            files.apply_text_edit(proposal, confirmed=True, backup_root=self.root / "backups")
        destination = self.root / "edited.txt"
        files.save_text_copy(proposal, destination)
        self.assertEqual(destination.read_text(encoding="utf-8"), "One paragraph instead of two")
        self.assertEqual(path.read_bytes(), original)

    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "pypdf dependency not installed")
    def test_pdf_edit_is_reviewed_plain_text_export_and_original_is_unchanged(self):
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        output = io.BytesIO()
        writer.write(output)
        path = self.put("input.pdf", output.getvalue())
        original = path.read_bytes()
        attachment = files.load_attachment(path)
        self.assertEqual(attachment.kind, "pdf")
        proposal = files.propose_text_edit([attachment], attachment.id, "Proposed text document")
        self.assertTrue(proposal.export_only)
        with self.assertRaisesRegex(files.AttachmentError, "text copy"):
            files.apply_text_edit(proposal, confirmed=True, backup_root=self.root / "backups")
        result = files.save_text_copy(proposal, self.root / "reviewed.txt")
        self.assertEqual(result.path.read_text(encoding="utf-8"), "Proposed text document")
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
