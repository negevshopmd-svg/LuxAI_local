"""Navigation rail for Jarvis. The main window owns page selection."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QFont, QPainter
from luxai.icons import icon, set_button_icon, theme_color
from luxai.ui_i18n import tr, normalize_language
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

VERSION_FILE = Path(__file__).resolve().parents[1] / "version.txt"


def application_version() -> str:
    """Read the installed version independently of the process directory."""
    try:
        value = VERSION_FILE.read_text(encoding="utf-8-sig").strip()
        return value if value and len(value) <= 32 and not any(c.isspace() for c in value) else "—"
    except (OSError, UnicodeError):
        return "—"


class BrandMark(QWidget):
    """The same scalable Jarvis mark used by the window and system tray."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(48, 48)
        self.setProperty("jarvisBrandMark", True)

    def paintEvent(self, event):
        painter = QPainter(self)
        icon("jarvis", color=theme_color("accent", self), size=48).paint(painter, self.rect())


class VersionLabel(QLabel):
    """Keep the release number readable with native Windows font metrics."""

    def __init__(self, text):
        super().__init__(text)
        self._fitting_font = False
        self._fit_font()

    def _set_font_size(self, pixels):
        font = QFont("Segoe UI")
        font.setPixelSize(pixels)
        font.setWeight(QFont.Weight.Normal)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0)
        if self.font() != font:
            self.setFont(font)
        # A local declaration wins over inherited native/stylesheet fonts.
        # Color still comes from the shared dark/light SidebarVersion rule.
        style = (
            f"font-family:'Segoe UI','Arial'; font-size:{pixels}px; "
            "font-weight:400; letter-spacing:0px; padding:0;"
        )
        if self.styleSheet() != style:
            self.setStyleSheet(style)

    def _fit_font(self):
        if self._fitting_font:
            return
        self._fitting_font = True
        try:
            # Qt's Windows style/font substitution can differ from Linux even
            # at the same logical DPI. Measure the effective font, rather than
            # assuming a stylesheet pixel size guarantees the string fits.
            for pixels in (10, 9, 8):
                self._set_font_size(pixels)
                if self.fontMetrics().horizontalAdvance(self.text()) <= self.contentsRect().width():
                    break
            self.setMinimumHeight(max(16, self.fontMetrics().height()))
        finally:
            self._fitting_font = False

    def event(self, event):
        result = super().event(event)
        if hasattr(self, "_fitting_font") and event.type() in (
            QEvent.Type.Resize, QEvent.Type.Show,
            QEvent.Type.FontChange, QEvent.Type.StyleChange,
        ):
            self._fit_font()
        return result


class NavigationSidebar(QFrame):
    page_selected = Signal(int)

    PAGES = [
        ("house", "Главная"),
        ("list-checks", "Команды"),
        ("blocks", "Дополнения"),
        ("bot", "Jarvis AI"),
        ("settings", "Настройки"),
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
        for idx, (icon_name, label) in enumerate(self.PAGES):
            button = QPushButton(label)
            button.setObjectName("Nav")
            button.setProperty("active", idx == 0)
            button.setProperty("collapsed", False)
            set_button_icon(button, icon_name, size=21)
            button.setToolTip(label)
            button.setAccessibleName(label)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(45)
            button.clicked.connect(lambda checked=False, i=idx: self.page_selected.emit(i))
            column.addWidget(button)
            self.nav_buttons.append(button)
        column.addStretch()

        self.collapse = QPushButton("Свернуть")
        self.collapse.setObjectName("Nav")
        set_button_icon(self.collapse, "panel-left-close", size=21, role="muted")
        self.collapse.setMinimumHeight(42)
        self.collapse.clicked.connect(self.toggle_collapsed)
        column.addWidget(self.collapse)

        version = application_version()
        self.version_label = VersionLabel(version)
        self.version_label.setObjectName("SidebarVersion")
        self.version_label.setTextFormat(Qt.TextFormat.PlainText)
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.version_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.version_label.setMinimumHeight(16)
        self.version_label.setToolTip(f"Jarvis {version}")
        self.version_label.setAccessibleName(f"Jarvis {version}")
        column.addWidget(self.version_label)

    def set_active(self, index):
        for i, button in enumerate(self.nav_buttons):
            button.setProperty("active", i == index)
            set_button_icon(button, self.PAGES[i][0], size=21)
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
        for (icon_name, title), button in zip(self.PAGES, self.nav_buttons):
            label = tr(title, self._language)
            button.setToolTip(label)
            button.setAccessibleName(label)
            button.setProperty("collapsed", self._collapsed)
            button.setText("" if self._collapsed else label)
            set_button_icon(button, icon_name, size=21)
            button.style().unpolish(button)
            button.style().polish(button)
        caption = ({"ru": "Развернуть", "en": "Expand", "ro": "Extinde"}[self._language]
                   if self._collapsed else tr("Свернуть", self._language))
        self.collapse.setText("" if self._collapsed else caption)
        self.collapse.setToolTip(caption)
        self.collapse.setAccessibleName(caption)
        self.collapse.setProperty("collapsed", self._collapsed)
        set_button_icon(self.collapse, "panel-left-open" if self._collapsed else "panel-left-close", size=21, role="muted")
        self.collapse.style().unpolish(self.collapse)
        self.collapse.style().polish(self.collapse)
