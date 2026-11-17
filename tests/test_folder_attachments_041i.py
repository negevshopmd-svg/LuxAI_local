"""0.4.1i Folders can be attached to the AI chat (read-only snapshot)."""
import os
from pathlib import Path
import tempfile
import unittest

from luxai import chat_attachments as files


class FolderAttachmentTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / "project"
        (self.root / "src").mkdir(parents=True)
        (self.root / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
        (self.root / "README.md").write_text("# Проект\nОписание.\n", encoding="utf-8")
        (self.root / ".env").write_text("API_KEY=secret-value\n", encoding="utf-8")
        (self.root / "server.key").write_text("-----BEGIN PRIVATE KEY-----\n", encoding="utf-8")
        (self.root / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 100)
        (self.root / "node_modules" / "lib").mkdir(parents=True)
        (self.root / "node_modules" / "lib" / "index.js").write_text("module.exports = 1", encoding="utf-8")
        (self.root / "binary.txt").write_bytes(b"abc\x00def")

    def test_tree_and_text_files_are_included(self):
        attachment = files.load_attachments([self.root])[0]
        self.assertEqual(attachment.kind, "folder")
        self.assertEqual(attachment.name, "project/")
        self.assertFalse(attachment.editable)
        self.assertIn("src/", attachment.text)
        self.assertIn("--- src/app.py ---\nprint('hello')", attachment.text)
        self.assertIn("--- README.md ---\n# Проект", attachment.text)
        self.assertIn("photo.png (108 bytes, not read)", attachment.text)

    def test_secrets_heavy_folders_and_binaries_are_never_read(self):
        text = files.load_folder(self.root).text
        self.assertNotIn("secret-value", text)
        self.assertNotIn("PRIVATE KEY", text)
        self.assertIn(".env (not read: may contain secrets)", text)
        self.assertIn("node_modules/ (skipped)", text)
        self.assertNotIn("module.exports", text)
        self.assertNotIn("def", text.split("binary.txt")[-1][:20])

    def test_budget_and_mixing_with_files(self):
        big = self.root / "big"
        big.mkdir()
        for index in range(40):
            (big / f"part{index:02}.txt").write_text("слово " * 400, encoding="utf-8")
        attachment = files.load_folder(self.root, max_chars=5000)
        self.assertLessEqual(len(attachment.text), 5000)
        self.assertTrue(attachment.truncated)
        loaded = files.load_attachments([self.root, self.root / "README.md"])
        self.assertEqual([item.kind for item in loaded], ["folder", "text"])
        context = files.attachment_context(loaded)
        self.assertIn("type=folder", context)

    @unittest.skipUnless(os.name == "nt", "junctions are Windows-only")
    def test_junctions_are_not_followed(self):
        import subprocess
        outside = self.root.parent / "outside"
        outside.mkdir()
        (outside / "private.txt").write_text("outside data", encoding="utf-8")
        link = self.root / "link"
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
        if result.returncode:
            self.skipTest("could not create a junction")
        self.assertNotIn("outside data", files.load_folder(self.root).text)


if __name__ == "__main__":
    unittest.main()
