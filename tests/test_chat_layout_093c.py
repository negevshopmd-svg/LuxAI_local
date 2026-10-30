"""Bounded chat previews and real clipboard-to-snapshot integration."""
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from PySide6.QtCore import QEvent, QMimeData, QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStackedWidget, QVBoxLayout, QWidget

import main
from luxai.chat_attachments import load_attachment, load_attachments
from luxai.icons import refresh_icons
from luxai.styles import build_styles
from luxai.ui_attachments import AttachmentChip
from luxai.ui_i18n import get_ui_language, set_ui_language


class ChatPageHost(QWidget):
    """Use the production chat builder without unrelated startup/device work."""
    build_chat = main.MainWindow.build_chat
    _paste_chat_attachments = main.MainWindow._paste_chat_attachments
    _finish_pasted_attachment_load = main.MainWindow._finish_pasted_attachment_load
    _attachment_loading_changed = main.MainWindow._attachment_loading_changed
    _refresh_attachment_route = main.MainWindow._refresh_attachment_route

    def __init__(self):
        super().__init__()
        self.pages = QStackedWidget()
        self.online_planner = mock.Mock()
        self.online_planner.enabled.return_value = False
        self.messages = []
        self._attachment_dialogs = []
        self._pick_chat_attachments = mock.Mock()
        self.submit_command = mock.Mock()
        self.run_command = mock.Mock()
        outer = QVBoxLayout(self)
        outer.addWidget(self.pages)
        self.build_chat()

    def append_message(self, *message):
        self.messages.append(message)


class ChatLayout093cTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.addCleanup(set_ui_language, get_ui_language())
        self.addCleanup(self.app.setStyleSheet, self.app.styleSheet())
        set_ui_language("en")
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.base = Path(folder.name)
        self.host = ChatPageHost()
        self.host.resize(760, 600)
        self.addCleanup(self.close_host)

    def close_host(self):
        for dialog in self.host.attachment_tray._dialogs[:]:
            dialog.close()
        self.host.close()
        self.host.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def show(self, theme="dark"):
        self.app.setStyleSheet(build_styles(theme, "#873eff"))
        self.host.show()
        self.app.processEvents()

    def wait_loaded(self):
        end = time.monotonic() + 5
        while self.host.attachment_tray.loading and time.monotonic() < end:
            QTest.qWait(10)
        self.assertFalse(self.host.attachment_tray.loading)
        self.app.processEvents()

    def text_files(self, count):
        result = []
        for index in range(count):
            path = self.base / f"report-{index}-with-a-long-file-name.txt"
            path.write_text(f"Original {index}", encoding="utf-8")
            result.append(load_attachment(path))
        return tuple(result)

    def test_toolbar_stays_at_edges_and_empty_composer_is_compact(self):
        for theme in ("dark", "light"):
            with self.subTest(theme=theme):
                self.show(theme)
                refresh_icons(self.host, theme, "#873eff")
                composer = self.host.chat_composer
                plus = self.host.attachment_tray.add_button
                send = self.host.send
                self.assertLessEqual(composer.height(), 112)
                self.assertLessEqual(plus.mapTo(composer, QPoint()).x(), 20)
                right_gap = composer.width() - send.mapTo(composer, QPoint()).x() - send.width()
                self.assertLessEqual(right_gap, 20)
                self.assertEqual(plus.width(), 34)
                self.assertTrue(plus.icon().isNull())
                self.assertFalse(self.host.attachment_tray.files.isVisible())

    def test_eight_attachments_use_one_bounded_row_and_each_x_unpins_its_file(self):
        self.show()
        tray = self.host.attachment_tray
        files = self.text_files(8)
        tray.add_attachments(files[:1])
        self.app.processEvents()
        single_height = self.host.chat_composer.height()
        tray.add_attachments(files[1:])
        self.app.processEvents()
        self.assertEqual(self.host.chat_composer.height(), single_height)
        self.assertLessEqual(single_height, 240)
        self.assertGreater(tray.files.horizontalScrollBar().maximum(), 0)
        self.assertEqual(tray.files.verticalScrollBar().maximum(), 0)
        cards = [tray.files.itemWidget(tray.files.item(i)) for i in range(8)]
        self.assertTrue(all(isinstance(card, AttachmentChip) for card in cards))
        self.assertTrue(all(card.width() <= 132 and card.height() <= 106 for card in cards))
        self.assertGreater(tray.route_hint.width(), 80)
        QTest.mouseClick(cards[0], Qt.MouseButton.LeftButton)
        self.assertEqual(len(tray._dialogs), 1)
        tray._dialogs[0].close()
        QTest.mouseClick(cards[0].remove_button, Qt.MouseButton.LeftButton)
        self.assertEqual([item.id for item in tray.attachments()], [item.id for item in files[1:]])
        self.assertEqual(files[0].path.read_text(), "Original 0")

    def test_image_paste_loads_snapshot_before_temporary_png_cleanup(self):
        self.show()
        image = QImage(72, 40, QImage.Format.Format_ARGB32)
        image.fill(QColor("#617fdb"))
        source = QMimeData()
        source.setImageData(image)
        paths = []
        self.host.command.paths_pasted.connect(lambda batch: paths.extend(batch))
        with (mock.patch("urllib.request.urlopen") as network,
              mock.patch("luxai.chat_attachments.extract_image_text") as ocr):
            self.host.command.insertFromMimeData(source)
            self.wait_loaded()
        self.assertEqual(len(paths), 1)
        self.assertFalse(Path(paths[0]).exists())
        attached = self.host.attachment_tray.attachments()
        self.assertEqual(len(attached), 1)
        self.assertEqual(attached[0].kind, "image")
        self.assertTrue(attached[0].image_data_url.startswith("data:image/png;base64,"))
        self.assertEqual(self.host.command.text(), "")
        self.assertFalse(self.host.messages)
        network.assert_not_called()
        ocr.assert_not_called()

    def test_rejected_second_paste_does_not_remove_first_inflight_image(self):
        self.show()
        gate = threading.Event()
        self.addCleanup(gate.set)
        original_loader = load_attachments

        def wait_and_load(paths):
            gate.wait(5)
            return original_loader(paths)

        paths = []
        self.host.command.paths_pasted.connect(lambda batch: paths.append(batch[0]))
        image = QImage(30, 20, QImage.Format.Format_ARGB32)
        image.fill(QColor("#4282d9"))
        source = QMimeData()
        source.setImageData(image)
        with mock.patch("luxai.ui_attachments.load_attachments", side_effect=wait_and_load):
            self.host.command.insertFromMimeData(source)
            self.host.command.insertFromMimeData(source)
            self.assertEqual(len(paths), 2)
            self.assertTrue(Path(paths[0]).exists())
            self.assertFalse(Path(paths[1]).exists())
            gate.set()
            self.wait_loaded()
        self.assertFalse(Path(paths[0]).exists())
        self.assertEqual(len(self.host.attachment_tray.attachments()), 1)
        self.assertFalse(self.host.messages)


if __name__ == "__main__":
    unittest.main()
