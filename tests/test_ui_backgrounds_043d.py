"""0.4.3d: no dark stripe behind scroll bars, no box behind the section icons of extension settings."""
from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication, QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from luxai.styles import build_styles


class BackgroundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def render(self, theme):
        card = QFrame()
        card.setObjectName("Card")
        card.setStyleSheet(build_styles(theme, "#f08a24"))
        card.resize(300, 300)
        layout = QVBoxLayout(card)
        icon = QLabel()
        icon.setObjectName("ExtSectionIcon")
        icon.setFixedSize(38, 38)
        layout.addWidget(icon)
        area = QScrollArea()
        area.setObjectName("ExtScroll")
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("ExtContent")
        content.setMinimumHeight(2000)
        area.setWidget(content)
        layout.addWidget(area)
        card.show()
        self.addCleanup(card.deleteLater)
        self.app.processEvents()
        return card, icon, area, card.grab().toImage()

    def test_scroll_bar_track_shows_the_panel(self):
        for theme in ("dark", "light"):
            card, _icon, area, image = self.render(theme)
            bar = area.verticalScrollBar()
            point = bar.mapTo(card, bar.rect().bottomLeft())
            self.assertEqual(image.pixelColor(point.x() + 1, point.y() - 3).name(),
                             image.pixelColor(point.x() - 20, point.y() - 3).name(), theme)

    def test_section_icon_has_no_box(self):
        for theme in ("dark", "light"):
            card, icon, _area, image = self.render(theme)
            edge = icon.mapTo(card, icon.rect().topLeft())
            outside = image.pixelColor(edge.x() + 50, edge.y() + 19).name()
            for x in (edge.x(), edge.x() + 1, edge.x() + 10):  # the old border and the old fill
                self.assertEqual(image.pixelColor(x, edge.y() + 19).name(), outside, theme)


if __name__ == "__main__":
    unittest.main()
