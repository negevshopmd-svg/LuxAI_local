"""Real bounded PDF/DOCX extraction and structure-preserving Word edits."""
import importlib.util
import io
import stat
import struct
import subprocess
import unittest
from unittest import mock
import zipfile
from xml.etree import ElementTree

from luxai import attachment_documents as documents


W = documents.WORD_NAMESPACE
WORD_XMLNS = W[1:-1]
HAS_PYPDF = importlib.util.find_spec("pypdf") is not None


def docx(body, *, extra=(), declaration="", encoding="utf-8", compression=zipfile.ZIP_STORED):
    xml = (f'<?xml version="1.0"?><w:document xmlns:w="{WORD_XMLNS}" '
           'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
           'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
           f'mc:Ignorable="w14"><w:body>{body}</w:body></w:document>')
    if declaration:
        xml = xml.replace("?><", "?>" + declaration + "<", 1)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr("word/document.xml", xml.encode(encoding))
        for name, data in extra:
            archive.writestr(name, data)
    return output.getvalue()


def paragraph(text):
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def pdf(text="Attached document", *, pages=1, encrypted=False, stream_bytes=None):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

    writer = PdfWriter()
    for index in range(pages):
        page = writer.add_blank_page(width=200, height=200)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)}),
        })
        stream = DecodedStreamObject()
        stream.set_data(stream_bytes if stream_bytes is not None else
                        f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream.flate_encode())
    if encrypted:
        writer.encrypt("private-password")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class WordAttachmentTests(unittest.TestCase):
    def test_extracts_paragraphs_empty_lines_tabs_breaks_and_table_cells_in_order(self):
        data = docx('<w:p><w:pPr><w:tabs><w:tab w:val="left" w:pos="720"/></w:tabs></w:pPr>'
                    '<w:r><w:t>Hello</w:t><w:tab/><w:t>World</w:t><w:br/><w:t>line</w:t></w:r></w:p>'
                    '<w:p/><w:tbl><w:tr><w:tc>' + paragraph("Left") + '</w:tc><w:tc>' +
                    paragraph("Right") + '</w:tc></w:tr></w:tbl><w:p/>')
        text, warnings = documents.extract_docx(data)
        self.assertEqual(text, "Hello\tWorld\vline\n\nLeft\nRight\n")
        self.assertIn("main-body", warnings[0])

    def test_text_context_bound_is_explicit(self):
        text, warnings = documents.extract_docx(docx(paragraph("abcdefghijklmnop")), max_chars=7)
        self.assertEqual(text, "abcdefg")
        self.assertTrue(any("truncated" in item for item in warnings))

    def test_rewrite_keeps_properties_empty_paragraphs_tables_and_package_entries(self):
        original = docx('<w:p w:rsidR="123"><w:pPr><w:jc w:val="center"/></w:pPr>'
                        '<w:r><w:rPr><w:b/></w:rPr><w:t>Old</w:t></w:r>'
                        '<w:r><w:rPr><w:i/></w:rPr><w:t> title</w:t></w:r></w:p><w:p/>'
                        '<w:tbl><w:tr><w:tc>' + paragraph("Cell") + '</w:tc></w:tr></w:tbl>'
                        '<w:sectPr><w:pgSz w:w="11906"/></w:sectPr>',
                        extra=(("word/styles.xml", b"unrelated styles"),
                               ("word/embeddings/never-executed.bin", b"unrelated embedded bytes")))
        self.assertTrue(documents.docx_editable(original))
        edited = documents.rewrite_docx(original, "New \ttitle\vline\n\nUpdated cell")
        self.assertEqual(documents.extract_docx(edited)[0], "New \ttitle\vline\n\nUpdated cell")
        with zipfile.ZipFile(io.BytesIO(original)) as before, zipfile.ZipFile(io.BytesIO(edited)) as after:
            self.assertEqual(before.namelist(), after.namelist())
            for name in before.namelist():
                if name != "word/document.xml":
                    self.assertEqual(before.read(name), after.read(name))
            xml = after.read("word/document.xml")
        root = ElementTree.fromstring(xml)
        paragraphs = list(root.find(W + "body").iter(W + "p"))
        self.assertEqual(len(paragraphs), 3)
        self.assertEqual(paragraphs[0].get(W + "rsidR"), "123")
        self.assertIsNotNone(paragraphs[0].find(W + "pPr/" + W + "jc"))
        self.assertIsNotNone(paragraphs[0].find(W + "r/" + W + "rPr/" + W + "b"))
        self.assertIsNotNone(root.find(W + "body/" + W + "sectPr"))
        self.assertEqual(len(list(root.iter(W + "tc"))), 1)
        self.assertIn(b'xmlns:w14="', xml)
        self.assertEqual(root.get("{http://schemas.openxmlformats.org/markup-compatibility/2006}Ignorable"), "w14")
        unchanged_first = documents.rewrite_docx(original, "Old title\n\nUpdated cell")
        with zipfile.ZipFile(io.BytesIO(unchanged_first)) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
        first = root.find(W + "body/" + W + "p")
        self.assertEqual(len(first.findall(W + "r")), 2)
        self.assertIsNotNone(first.findall(W + "r")[1].find(W + "rPr/" + W + "i"))

    def test_structural_and_complex_edits_fail_without_modifying_original_bytes(self):
        original = docx(paragraph("First") + paragraph("Second"))
        with self.assertRaisesRegex(ValueError, "paragraph count"):
            documents.rewrite_docx(original, "One paragraph")
        self.assertEqual(documents.extract_docx(original)[0], "First\nSecond")
        linked = docx('<w:p><w:hyperlink w:anchor="bookmark"><w:r><w:t>Link</w:t></w:r></w:hyperlink></w:p>')
        self.assertFalse(documents.docx_editable(linked))
        with self.assertRaisesRegex(ValueError, "TXT copy"):
            documents.rewrite_docx(linked, "Changed link")
        with self.assertRaisesRegex(ValueError, "control characters"):
            documents.rewrite_docx(original, "Bad\x00value\nSecond")

    def test_utf16_xml_entities_are_rejected_before_expansion(self):
        declaration = '<!DOCTYPE document [<!ENTITY secret "expanded">]>'
        for encoding in ("utf-8", "utf-16", "utf-16-le"):
            with self.subTest(encoding=encoding), self.assertRaisesRegex(ValueError, "entity declarations|encoding"):
                documents.extract_docx(docx(paragraph("&secret;"), declaration=declaration, encoding=encoding))
        nested = "<w:sdt>" * 200 + paragraph("Deep") + "</w:sdt>" * 200
        with self.assertRaisesRegex(ValueError, "nesting limit"):
            documents.extract_docx(docx(nested))

    def test_traversal_links_and_case_aliases_are_rejected(self):
        for name in ("../outside.txt", "/outside.txt", "word/../../outside.txt", "C:/outside.txt",
                     "word\\outside.txt", "WORD/DOCUMENT.XML"):
            archive_bytes = docx(paragraph("Safe"), extra=((name, b"payload"),))
            if name == "word\\outside.txt":
                # Windows ZipInfo normalizes backslashes on ZIP creation too.
                # Put the unsafe name into both local and central ZIP headers.
                archive_bytes = archive_bytes.replace(b"word/outside.txt", b"word\\outside.txt")
                self.assertIn(b"word\\outside.txt", archive_bytes)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "unsafe entry"):
                documents.extract_docx(archive_bytes)
        link = zipfile.ZipInfo("word/link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaisesRegex(ValueError, "unsafe entry"):
            documents.extract_docx(docx(paragraph("Safe"), extra=((link, b"outside"),)))

    def test_archive_size_and_ratio_limits_precede_xml_decompression(self):
        data = bytearray(docx(paragraph("Safe")))
        central = data.index(b"PK\x01\x02")
        struct.pack_into("<I", data, central + 24, documents.MAX_DOCX_EXPANDED_BYTES + 1)
        with mock.patch.object(zipfile.ZipFile, "open", side_effect=AssertionError("must reject before decompression")):
            with self.assertRaisesRegex(ValueError, "expansion limit"):
                documents.extract_docx(bytes(data))
        high_ratio = docx(paragraph("x" * 200_000), compression=zipfile.ZIP_DEFLATED)
        with self.assertRaisesRegex(ValueError, "compression ratio"):
            documents.extract_docx(high_ratio)

    def test_damaged_or_non_docx_archives_fail_precisely(self):
        with self.assertRaisesRegex(ValueError, "damaged"):
            documents.extract_docx(b"not a ZIP")
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("personal.txt", "Not a Word document")
        with self.assertRaisesRegex(ValueError, "not a DOCX"):
            documents.extract_docx(archive.getvalue())

    def test_edit_rejects_corrupt_unread_package_entry_with_export_fallback(self):
        original = docx(paragraph("Readable main document"),
                        extra=(("word/styles.xml", b"UNIQUE_STYLE_PAYLOAD"),))
        damaged = bytearray(original)
        damaged[damaged.index(b"UNIQUE_STYLE_PAYLOAD")] ^= 1
        damaged = bytes(damaged)
        self.assertEqual(documents.extract_docx(damaged)[0], "Readable main document")
        with self.assertRaisesRegex(ValueError, "damaged.*TXT copy"):
            documents.rewrite_docx(damaged, "Reviewed replacement")


@unittest.skipUnless(HAS_PYPDF, "pypdf is optional until the PDF dependency is installed")
class PDFAttachmentTests(unittest.TestCase):
    def test_real_pdf_text_extraction_and_explicit_context_bound(self):
        text, warnings = documents.extract_pdf(pdf("Attached document"))
        self.assertEqual(text, "Attached document")
        self.assertEqual(warnings, ())
        text, warnings = documents.extract_pdf(pdf("Attachment context limit"), max_chars=10)
        self.assertEqual(text, "Attachment")
        self.assertTrue(any("truncated" in item for item in warnings))

    def test_encrypted_page_limit_and_stream_expansion_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Password-protected"):
            documents.extract_pdf(pdf(encrypted=True))
        with self.assertRaisesRegex(ValueError, "100-page"):
            documents.extract_pdf(pdf(pages=101))
        bomb = pdf(stream_bytes=b" " * (9 * 1024 * 1024))
        with self.assertRaisesRegex(ValueError, "safely|limits"):
            documents.extract_pdf(bomb)
        aggregate_bomb = pdf(pages=40, stream_bytes=b" " * (1024 * 1024))
        with self.assertRaisesRegex(ValueError, "decoded-stream budget"):
            documents.extract_pdf(aggregate_bomb)

    def test_malformed_pdf_failure_and_timeout_are_precise(self):
        with self.assertRaisesRegex(ValueError, "valid PDF"):
            documents.extract_pdf(b"not a PDF")
        with self.assertRaisesRegex(ValueError, "could not be read safely"):
            documents.extract_pdf(b"%PDF-1.7\ntruncated")
        with mock.patch.object(documents.subprocess, "run", side_effect=subprocess.TimeoutExpired("reader", 30)):
            with self.assertRaisesRegex(ValueError, "30-second"):
                documents.extract_pdf(pdf())


if __name__ == "__main__":
    unittest.main()
