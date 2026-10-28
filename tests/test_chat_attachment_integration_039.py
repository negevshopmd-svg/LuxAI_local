"""The real chat composer isolates attachment work from desktop execution."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from PySide6.QtCore import QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import main
from luxai.attachment_chat import AttachmentReply
from luxai.chat_attachments import load_attachment, propose_text_edit
from luxai.ui_i18n import get_ui_language, set_ui_language


class ChatAttachmentIntegration039Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.addCleanup(set_ui_language, get_ui_language())
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.base = Path(folder.name)
        self.config = self.base / "config.json"
        self.config.write_text(json.dumps({
            "microphone_enabled": False, "tts_enabled": False,
            "online_agent_enabled": False, "response_language": "en",
            "ui_language": "en", "minimize_to_tray": False,
        }), encoding="utf-8")
        for target, value in (("main.CONFIG", self.config),
                              ("luxai.command_registry.REGISTRY_FILE", self.base / "commands.json")):
            patcher = mock.patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        with (mock.patch("sounddevice.query_devices", return_value=[]),
              mock.patch.object(main.MainWindow, "_ocr_setup_worker"),
              mock.patch.object(main.MainWindow, "_start_cloud_check")):
            self.window = main.MainWindow()
        def close():
            for dialog in tuple(self.window._attachment_dialogs):
                dialog.reject()
            self.window.close()
            self.window.deleteLater()
            self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.addCleanup(close)
        self.path = self.base / "report&draft.txt"
        self.path.write_text("Original attachment\n", encoding="utf-8")
        self.item = load_attachment(self.path)
        self.window.attachment_tray.add_attachments((self.item,))

    def wait_done(self):
        end = time.monotonic() + 5
        while (self.window._processing or self.window._command_queue) and time.monotonic() < end:
            QTest.qWait(10)
        self.assertFalse(self.window._processing)
        self.assertFalse(self.window._command_queue)

    def test_send_uses_fake_provider_worker_and_never_desktop_executor(self):
        self.window.cfg.update({"online_agent_enabled": True, "online_provider": "openai"})
        self.window.online_planner.update_config(self.window.cfg)
        self.window.command.setText("Correct the attached document.")
        response = {"choices": [{"message": {"content": json.dumps({
            "reply": "Suggested <b>plain text</b>.",
            "edits": [{"attachment_id": self.item.id, "content": "Corrected attachment\n"}],
        })}}]}
        with (mock.patch.object(self.window, "apply_settings", return_value=True),
              mock.patch("luxai.online_agent.get_api_key", return_value="fixture-key"),
              mock.patch("luxai.attachment_chat.get_api_key", return_value="fixture-key"),
              mock.patch.object(main.OnlinePlanner, "_request", return_value=response) as request,
              mock.patch.object(self.window, "run_command") as desktop_route,
              mock.patch.object(self.window, "_execute_registered") as execute):
            self.window.submit_command()
            self.wait_done()
        request.assert_called_once()
        desktop_route.assert_not_called()
        execute.assert_not_called()
        self.assertEqual(self.window.attachment_edit_layout.count(), 1)
        self.assertEqual(self.path.read_text(), "Original attachment\n")
        self.assertIn("Suggested <b>plain text</b>.", self.window.log.toPlainText())
        self.assertIn("report&amp;draft.txt", self.window.log.toHtml())
        self.assertIn("&lt;b&gt;plain text&lt;/b&gt;", self.window.log.toHtml())
        self.assertEqual(self.window.attachment_tray.attachments(), (self.item,))

    def test_proposal_button_opens_review_and_only_apply_updates_original_and_tray(self):
        proposal = propose_text_edit((self.item,), self.item.id, "Corrected attachment\n")
        self.window._attachment_active = (23, "Correct this file.")
        self.window._command_queue = [{"parts": [], "answers": [], "routes": [],
                                       "original_text": "Correct this file."}]
        self.window._on_attachment_reply(23, AttachmentReply("Review this change.", (proposal,), "cloud"), "")
        self.window.attachment_edit_layout.itemAt(0).widget().click()
        self.assertEqual(len(self.window._attachment_dialogs), 1)
        dialog = self.window._attachment_dialogs[0]
        self.assertEqual(self.path.read_text(), "Original attachment\n")
        with mock.patch("luxai.chat_attachments.BACKUP_ROOT", self.base / "backups"):
            dialog.apply_changes()
        self.assertEqual(self.path.read_text(), "Corrected attachment\n")
        self.assertEqual(self.window.attachment_tray.attachments()[0].text, "Corrected attachment\n")
        self.assertIn("saved", self.window.log.toPlainText().casefold())

    def test_queued_send_captures_provider_mode_and_snapshot_before_later_settings_changes(self):
        self.window._processing = True
        self.window.cfg.update({"online_provider": "openai", "online_model": "old-model"})
        self.window.command.setText("Read this file.")
        with (mock.patch.object(self.window, "apply_settings", return_value=True),
              mock.patch.object(self.window.online_planner, "enabled", return_value=True)):
            self.window.submit_command()
        queued = self.window._command_queue[0]
        self.assertEqual(queued["attachment_config"]["online_model"], "old-model")
        self.path.write_text("External content must not be uploaded", encoding="utf-8")
        self.window.cfg.update({"online_provider": "custom", "online_model": "new-model"})
        self.window._processing = False
        with mock.patch.object(self.window, "_start_attachment_chat") as start:
            self.window._dispatch_command()
        start.assert_called_once()
        self.assertEqual(start.call_args.kwargs["config"]["online_provider"], "openai")
        self.assertTrue(start.call_args.kwargs["allow_cloud"])
        self.assertEqual(start.call_args.args[1][0].text, "Original attachment\n")

    def test_cancel_and_stale_result_do_not_add_reply_or_edits(self):
        self.window._attachment_active = (5, "Read this file.")
        self.window._attachment_token = 5
        self.window._processing = True
        self.window._command_queue = [{"parts": [], "answers": [], "routes": [],
                                       "original_text": "Read this file."}]
        self.window.run_command("cancel task")
        self.assertIsNone(self.window._attachment_active)
        before = self.window.log.toPlainText()
        proposal = propose_text_edit((self.item,), self.item.id, "Never applied\n")
        self.window._on_attachment_reply(5, AttachmentReply("Stale reply", (proposal,)), "")
        self.assertEqual(self.window.log.toPlainText(), before)
        self.assertEqual(self.window.attachment_edit_layout.count(), 0)
        self.assertEqual(self.path.read_text(), "Original attachment\n")

    def test_closed_window_ignores_late_reply(self):
        self.window._attachment_active = (6, "Read this file.")
        self.window._closed = True
        before = self.window.log.toPlainText()
        self.window._on_attachment_reply(6, AttachmentReply("Late reply"), "")
        self.assertEqual(self.window.log.toPlainText(), before)
        self.assertEqual(self.window.attachment_edit_layout.count(), 0)


if __name__ == "__main__":
    unittest.main()
