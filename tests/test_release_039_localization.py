"""Command and attachment UI labels translate while user content stays exact."""
from dataclasses import replace
from pathlib import Path
import re
import tempfile
import unittest

from PySide6.QtWidgets import QApplication, QAbstractButton, QComboBox, QLabel

from luxai.chat_attachments import load_attachment, propose_text_edit
from luxai.ui_attachments import AttachmentEditDialog, AttachmentPreviewDialog, AttachmentTray
from luxai.ui_command_editor import CommandEditor
from luxai.ui_i18n import get_ui_language, set_ui_language, translate_widgets


class Release039LocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.addCleanup(set_ui_language, get_ui_language())

    def test_new_editor_labels_options_and_feedback_follow_ui_language(self):
        for language, record, ready, weekday in (
            ("ru", "Записать", "Добавьте название", "Пн"),
            ("en", "Record", "Add a name", "Mon"),
            ("ro", "Înregistrează", "Adaugă un nume", "Lu"),
        ):
            with self.subTest(language=language):
                set_ui_language(language)
                dialog = CommandEditor()
                self.addCleanup(dialog.close)
                self.assertEqual(dialog.record_button.text(), record)
                self.assertEqual(dialog.readiness.text(), ready)
                self.assertEqual(dialog.weekday_buttons[0].text(), weekday)
                self.assertEqual([dialog.schedule_mode.itemData(i) for i in range(3)],
                                 ["daily", "once", "weekly"])
                self.assertEqual([dialog.event_type.itemData(i) for i in range(2)],
                                 ["app_started", "headphones_connected"])
                if language != "ru":
                    visible_copy = []
                    for widget in dialog.findChildren(QLabel) + dialog.findChildren(QAbstractButton):
                        visible_copy.extend((widget.text(), widget.toolTip()))
                    for combo in dialog.findChildren(QComboBox):
                        visible_copy.extend(combo.itemText(i) for i in range(combo.count()))
                    self.assertEqual([text for text in visible_copy if re.search(r"[А-Яа-яЁё]", text)], [])

    def test_user_command_title_phrase_and_tooltip_are_never_translated(self):
        command = {"id": "personal", "title": "Команды", "phrases": ["Настройки"],
                   "optional_words": ["пожалуйста"], "action": "open_app", "target": "notepad",
                   "steps": [{"action": "open_app", "target": "notepad", "location": "desktop"}]}
        set_ui_language("ru")
        dialog = CommandEditor(command)
        self.addCleanup(dialog.close)
        for language in ("en", "ro", "ru"):
            set_ui_language(language)
            translate_widgets(dialog, language)
            data = dialog.get_data()
            self.assertEqual(data["title"], "Команды")
            self.assertEqual(data["phrases"], ["Настройки"])
            chip = dialog.phrase_chips.findChild(QAbstractButton, "PhraseChip")
            self.assertEqual(chip.text(), "Настройки  ×")
            self.assertEqual(chip.toolTip(), "Настройки")

    def attachment(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "notes.txt"
        path.write_text("Настройки <b>exact user text</b> & Команды", encoding="utf-8")
        return replace(load_attachment(path), name="Команды")

    def test_attachment_tray_switches_captions_and_preserves_snapshot(self):
        item = self.attachment()
        tray = AttachmentTray()
        self.addCleanup(tray.close)
        tray.add_attachments((item,))
        for language, attach, remove, local in (
            ("ru", "Прикрепить", "Убрать", "локально"),
            ("en", "Attach", "Remove", "locally"),
            ("ro", "Atașează", "Elimină", "local"),
        ):
            with self.subTest(language=language):
                set_ui_language(language)
                translate_widgets(tray, language)
                tray.set_language(language)
                tray.set_delivery_mode(False)
                self.assertEqual(tray.add_button.text(), "+")
                self.assertEqual(tray.add_button.accessibleName(), attach)
                self.assertEqual(tray.remove_button.text(), "×")
                self.assertEqual(tray.remove_button.accessibleName(), remove)
                self.assertIn(local, tray.route_hint.text())
                self.assertEqual(tray.attachments(), (item,))
                self.assertTrue(tray.files.item(0).text().startswith("Команды"))
                self.assertTrue(tray.files.item(0).toolTip().startswith("Команды"))

    def test_preview_filename_and_review_content_keep_exact_user_text(self):
        item = self.attachment()
        original = item.path.read_bytes()
        proposed = "Главная <b>edited user text</b> & Настройки"
        proposal = propose_text_edit((item,), item.id, proposed)
        preview = AttachmentPreviewDialog(item)
        self.addCleanup(preview.close)
        for language, apply, new_text in (("ru", "Применить", "Новый текст"),
                                           ("en", "Apply", "New text"),
                                           ("ro", "Aplică", "Text nou")):
            with self.subTest(language=language):
                set_ui_language(language)
                translate_widgets(preview, language)
                self.assertEqual(preview.windowTitle(), "Команды")
                self.assertIn("Команды", [label.text() for label in preview.findChildren(QLabel)])
                review = AttachmentEditDialog(proposal)
                self.addCleanup(review.close)
                self.assertEqual(review.apply_button.text(), apply)
                self.assertEqual(review.tabs.tabText(2), new_text)
                self.assertEqual(review.original_view.toPlainText(), item.text)
                self.assertEqual(review.new_text.toPlainText(), proposed)
                self.assertEqual(item.path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
