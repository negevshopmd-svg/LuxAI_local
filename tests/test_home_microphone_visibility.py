"""Header microphone toggle is visible only on the Home page."""
from __future__ import annotations

import os
from types import SimpleNamespace
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QPushButton, QStackedWidget, QWidget,
)

from luxai.ui_window_chrome import WindowHeader
from main import MainWindow


class HeaderMicrophoneVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_button_only_on_home_and_navigation_preserves_toggle_state(self):
        owner = QMainWindow()
        self.addCleanup(owner.close)
        title = QLabel("Jarvis")
        microphone = QPushButton()
        microphone.setCheckable(True)
        microphone.setChecked(True)
        header = WindowHeader(owner, title, microphone, owner)

        pages = QStackedWidget()
        homes = [QWidget() for _ in range(5)]
        for page in homes:
            pages.addWidget(page)

        sections = []
        fake = SimpleNamespace(
            pages=pages,
            home_page=homes[0],
            header_title=title,
            window_header=header,
            sidebar=SimpleNamespace(set_active=sections.append),
            _update_home_backdrop=lambda: None,
        )

        for index in (0, 1, 2, 3, 4, 0):
            with self.subTest(page=index):
                MainWindow.show_page(fake, index)
                self.assertEqual(microphone.isHidden(), index != 0)
                self.assertTrue(microphone.isChecked())
                self.assertTrue(microphone.isCheckable())
        self.assertEqual(sections, [0, 1, 2, 3, 4, 0])

    def test_disabled_microphone_stays_disabled_when_reentering_home(self):
        owner = QMainWindow()
        self.addCleanup(owner.close)
        button = QPushButton()
        button.setCheckable(True)
        button.setChecked(False)
        header = WindowHeader(owner, QLabel("Jarvis"), button, owner)
        header.set_microphone_visible(False)
        self.assertTrue(button.isHidden())
        header.set_microphone_visible(True)
        self.assertFalse(button.isHidden())
        self.assertFalse(button.isChecked())


if __name__ == "__main__":
    unittest.main()
