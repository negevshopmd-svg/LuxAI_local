"""Selecting and reviewing attachments never writes or uploads in the background."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from PySide6.QtCore import QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from luxai.chat_attachments import load_attachment, propose_text_edit
from luxai.ui_attachments import AttachmentEditDialog, AttachmentTray
from luxai.ui_i18n import get_ui_language, set_ui_language


class AttachmentUI039Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.addCleanup(set_ui_language, get_ui_language())
        set_ui_language("en")
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.base = Path(folder.name)
        self.path = self.base / "Команды.txt"
        self.path.write_text("Original text\n", encoding="utf-8")
        self.item = load_attachment(self.path)

    def keep(self, widget):
        def close():
            widget.close()
            widget.deleteLater()
            self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.addCleanup(close)
        return widget

    def wait_loaded(self, tray):
        end = time.monotonic() + 5
        while tray.loading and time.monotonic() < end:
            QTest.qWait(10)
        self.assertFalse(tray.loading)

    def test_async_selection_loads_pinned_snapshot_and_remove_never_deletes_file(self):
        tray = self.keep(AttachmentTray())
        changes, errors, loading = [], [], []
        tray.changed.connect(lambda: changes.append(True))
        tray.error.connect(errors.append)
        tray.loading_changed.connect(loading.append)
        with (mock.patch("urllib.request.urlopen") as network,
              mock.patch("luxai.chat_attachments.extract_image_text") as ocr):
            self.assertTrue(tray.add_paths([self.path]))
            self.wait_loaded(tray)
        network.assert_not_called()
        ocr.assert_not_called()
        self.assertFalse(errors)
        self.assertEqual(loading, [True, False])
        self.assertTrue(changes)
        self.assertEqual(tray.attachments()[0].text, "Original text\n")
        # External changes do not silently replace the pinned snapshot.
        self.path.write_text("External change", encoding="utf-8")
        self.assertEqual(tray.attachments()[0].text, "Original text\n")
        tray.remove_selected()
        self.assertFalse(tray.attachments())
        self.assertEqual(self.path.read_text(), "External change")

    def test_invalid_load_preserves_pinned_files_and_reports_error(self):
        tray = self.keep(AttachmentTray())
        tray.add_attachments((self.item,))
        errors = []
        tray.error.connect(errors.append)
        tray.add_paths([self.base / "missing.txt"])
        self.wait_loaded(tray)
        self.assertTrue(errors)
        self.assertEqual(tray.attachments(), (self.item,))

    def test_route_hint_and_controls_follow_ru_ro_en_without_upload(self):
        tray = self.keep(AttachmentTray())
        for code, add_label, local_marker, cloud_marker in (
            ("en", "Attach", "locally", "cloud AI"),
            ("ro", "Atașează", "local", "AI cloud"),
            ("ru", "Прикрепить", "локально", "облачный AI"),
        ):
            with self.subTest(code=code):
                tray.set_language(code)
                tray.set_delivery_mode(False)
                self.assertEqual(tray.add_button.text(), "+")
                self.assertEqual(tray.add_button.accessibleName(), add_label)
                self.assertIn(local_marker, tray.route_hint.text())
                tray.set_delivery_mode(True)
                self.assertIn(cloud_marker, tray.route_hint.text())
        self.assertFalse(tray.attachments())

    def test_review_and_cancel_never_write_then_explicit_apply_saves_and_emits_refresh(self):
        proposal = propose_text_edit((self.item,), self.item.id, "Corrected text\n")
        rejected = self.keep(AttachmentEditDialog(proposal))
        self.assertIn("-Original text", rejected.diff_view.toPlainText())
        self.assertEqual(self.path.read_text(), "Original text\n")
        rejected.reject()
        self.assertEqual(self.path.read_text(), "Original text\n")
        dialog = self.keep(AttachmentEditDialog(proposal))
        refreshed = []
        dialog.applied.connect(refreshed.append)
        with mock.patch("luxai.chat_attachments.BACKUP_ROOT", self.base / "backups"):
            dialog.apply_changes()
        self.assertEqual(self.path.read_text(), "Corrected text\n")
        self.assertEqual(refreshed[0].text, "Corrected text\n")
        self.assertNotEqual(refreshed[0].sha256, self.item.sha256)
        self.assertTrue(list((self.base / "backups").glob("*.bak")))

    def test_stale_original_is_reported_without_overwriting(self):
        proposal = propose_text_edit((self.item,), self.item.id, "Corrected text\n")
        dialog = self.keep(AttachmentEditDialog(proposal))
        self.path.write_text("Another app changed this", encoding="utf-8")
        with mock.patch.object(dialog, "_show_error") as error:
            dialog.apply_changes()
        error.assert_called_once()
        self.assertEqual(self.path.read_text(), "Another app changed this")

    def test_user_can_refine_proposed_text_and_save_explicit_copy(self):
        proposal = propose_text_edit((self.item,), self.item.id, "Corrected text\n")
        dialog = self.keep(AttachmentEditDialog(proposal))
        dialog.new_text.setPlainText("My revised text\n")
        self.assertIn("+My revised text", dialog.diff_view.toPlainText())
        chosen = self.base / "edited-copy.txt"
        copied = []
        dialog.saved_copy.connect(copied.append)
        with mock.patch("luxai.ui_attachments.QFileDialog.getSaveFileName", return_value=(str(chosen), "")):
            dialog.save_copy()
        self.assertEqual(chosen.read_text(), "My revised text\n")
        self.assertEqual(self.path.read_text(), "Original text\n")
        self.assertEqual(copied, [str(chosen)])

    def test_replace_snapshot_keeps_one_chip_for_a_pinned_path(self):
        tray = self.keep(AttachmentTray())
        tray.add_attachments((self.item,))
        self.path.write_text("Updated original", encoding="utf-8")
        updated = load_attachment(self.path)
        tray.replace_attachment(updated)
        self.assertEqual(len(tray.attachments()), 1)
        self.assertEqual(tray.attachments()[0].text, "Updated original")


if __name__ == "__main__":
    unittest.main()
