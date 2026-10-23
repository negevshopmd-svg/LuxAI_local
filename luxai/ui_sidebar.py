"""Navigation rail for Jarvis. The main window owns page selection."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from luxai.ui_i18n import tr, normalize_language
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)


class BrandMark(QWidget):
    """Vector logo, avoiding external image and icon dependencies."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(48, 48)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#244e91"))
        p.drawEllipse(1, 1, 46, 46)
        p.setBrush(QColor("#3f85f1"))
        p.drawEllipse(7, 7, 34, 34)
        p.setPen(QPen(QColor("#ffffff"), 5, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        # Abstract lightning-shaped J mark, matching the reference's look.
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPainterPath
        path = QPainterPath(QPointF(27, 15))
        path.lineTo(QPointF(19, 25))
        path.lineTo(QPointF(29, 25))
        path.lineTo(QPointF(23, 33))
        p.drawPath(path)


class NavigationSidebar(QFrame):
    page_selected = Signal(int)

    PAGES = [
        ("⌂", "Главная"),
        ("☷", "Команды"),
        ("▦", "Дополнения"),
        ("▣", "Jarvis AI"),
        ("☷", "Настройки"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(177)
        self._collapsed = False
        self._language = "ru"

        column = QVBoxLayout(self)
        column.setContentsMargins(14, 18, 14, 18)
        column.setSpacing(6)

        brand = QHBoxLayout()
        brand.setContentsMargins(3, 0, 0, 0)
        self.mark = BrandMark()
        brand.addWidget(self.mark)
        self.brand_text = QLabel("JARVIS")
        self.brand_text.setObjectName("SidebarBrand")
        self.brand_text.setStyleSheet("font-size:15px; font-weight:700; letter-spacing:1px;")
        brand.addWidget(self.brand_text)
        brand.addStretch()
        column.addLayout(brand)
        column.addSpacing(23)

        self.nav_buttons = []
        for idx, (glyph, label) in enumerate(self.PAGES):
            button = QPushButton(f"{glyph}    {label}")
            button.setObjectName("Nav")
            button.setProperty("active", idx == 0)
            button.setToolTip(label)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(45)
            button.clicked.connect(lambda checked=False, i=idx: self.page_selected.emit(i))
            column.addWidget(button)
            self.nav_buttons.append(button)
        column.addStretch()

        self.collapse = QPushButton("◁   Свернуть")
        self.collapse.setObjectName("Nav")
        self.collapse.setMinimumHeight(42)
        self.collapse.clicked.connect(self.toggle_collapsed)
        column.addWidget(self.collapse)

    def set_active(self, index):
        for i, button in enumerate(self.nav_buttons):
            button.setProperty("active", i == index)
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

    def toggle_collapsed(self):
        self._collapsed = not self._collapsed
        self.setFixedWidth(76 if self._collapsed else 177)
        self.brand_text.setVisible(not self._collapsed)
        self.set_language(self._language)

    def set_language(self, language):
        self._language = normalize_language(language)
        for (icon, title), button in zip(self.PAGES, self.nav_buttons):
            label = tr(title, self._language)
            button.setToolTip(label)
            button.setText(icon if self._collapsed else f"{icon}    {label}")
        self.collapse.setText("▷" if self._collapsed else f"◁   {tr('Свернуть', self._language)}")
