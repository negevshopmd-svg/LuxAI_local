"""0.4.3n: the notification reader says (once) why it keeps notifications instead of reading them.

Reported: «the message reading plugin does not work». On the user's PC Discord held the microphone (a voice
channel), so «Silent during calls» kept every notification for «what came in» — without a word.
"""
from __future__ import annotations

import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication

from luxai import notifications as n


class ProgramNameTests(unittest.TestCase):
    def test_registry_key_names_become_program_names(self):
        self.assertEqual(n._program_name(r"C:#Users#x#AppData#Local#Discord#app-1.0.9269#Discord.exe"), "Discord")
        self.assertEqual(n._program_name("Microsoft.SkypeApp_kzf8qxf38zg5c"), "Microsoft.SkypeApp")

    def test_in_use_follows_the_named_program(self):
        with mock.patch.object(n, "call_app", return_value="Discord"):
            self.assertTrue(n.microphone_in_use_by_other_app())
        with mock.patch.object(n, "call_app", return_value=""):
            self.assertFalse(n.microphone_in_use_by_other_app())


class HeldNoticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def runtime(self):
        from luxai import extensions_catalog as catalog
        from luxai.extensions_runtime import ExtensionsRuntime
        host = mock.Mock(spec=["cfg", "_queue_speech", "save_extensions_meta"])
        host.cfg = {"language": "ro", "tts_enabled": True, "extensions_meta": {}}
        runtime = ExtensionsRuntime(host)
        self.addCleanup(runtime.deleteLater)
        runtime.state = catalog.normalize_state({"notification_reader": {"enabled": True, "settings": {}}})
        notices = []
        runtime.notice.connect(notices.append)
        return runtime, notices

    def test_a_call_is_told_once_with_the_program(self):
        runtime, notices = self.runtime()
        with mock.patch.object(runtime, "_silence_reason", return_value="call"), \
                mock.patch.object(n, "call_app", return_value="Discord"):
            for text in ("Telegram: Mama — salut", "Telegram: Tata — ce faci", "WhatsApp: Ana — vin"):
                runtime._accept_notification(text)
        self.assertEqual(len(notices), 1)
        self.assertIn("Discord", notices[0])
        self.assertTrue(any(phrase in notices[0] for phrase in ("ce a venit", "что пришло", "what came in")))
        self.assertEqual(len(runtime.missed_notifications), 3)       # kept, not lost
        runtime.host._queue_speech.assert_not_called()

    def test_after_the_call_it_reads_and_a_new_call_is_told_again(self):
        runtime, notices = self.runtime()
        with mock.patch.object(runtime, "_silence_reason", return_value="call"), \
                mock.patch.object(n, "call_app", return_value="Discord"):
            runtime._accept_notification("Telegram: Mama — salut")
        with mock.patch.object(runtime, "_silence_reason", return_value=""):
            runtime._accept_notification("Telegram: Tata — ce faci")
        runtime.host._queue_speech.assert_called_once()
        with mock.patch.object(runtime, "_silence_reason", return_value="call"), \
                mock.patch.object(n, "call_app", return_value="Discord"):
            runtime._accept_notification("Telegram: Ana — vin")
        self.assertEqual(len(notices), 2)

    def test_expected_silences_are_not_announced(self):
        runtime, notices = self.runtime()
        for reason in ("quiet_mode", "locked", "quiet_hours", "dnd"):
            with mock.patch.object(runtime, "_silence_reason", return_value=reason):
                runtime._accept_notification("Telegram: Mama — salut")
        self.assertEqual(notices, [])


if __name__ == "__main__":
    unittest.main()
