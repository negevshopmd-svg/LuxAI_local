"""Compact appearance controls bound to the Settings combo-box models.

The models keep saved values and normal Qt signals stable. Their visible
presentations provide proper keyboard focus, names and live selection state.
"""
from __future__ import annotations

import re

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QBoxLayout, QButtonGroup, QColorDialog, QComboBox, QFrame, QHBoxLayout,
    QLabel, QLayout, QLineEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from luxai.icons import set_button_icon
from luxai.styles import theme_colors
from luxai.ui_i18n import tr


def color_value(value: str) -> str | None:
    """Accept only an opaque RGB setting, rather than arbitrary CSS."""
    text = str(value or "").strip()
    return text.lower() if re.fullmatch(r"#[0-9a-fA-F]{6}", text) else None


class SegmentedControl(QFrame):
    def __init__(self, model: QComboBox, parent=None):
        super().__init__(parent)
        self.setObjectName("PreferenceSegments")
        self.model = model
        model.setParent(self)
        model.hide()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = []
        for index in range(model.count()):
            button = QPushButton(model.itemText(index))
            button.setObjectName("PreferenceSegment")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(29)
            self.group.addButton(button, index)
            layout.addWidget(button)
            self.buttons.append(button)
        self.group.idClicked.connect(model.setCurrentIndex)
        model.currentIndexChanged.connect(self.sync)
        model.model().dataChanged.connect(self.sync)
        self.sync()

    def sync(self, *_):
        for index, button in enumerate(self.buttons):
            text = self.model.itemText(index)
            if button.text() != text:
                button.setText(text)
            button.setAccessibleName(text)
            selected = index == self.model.currentIndex()
            button.setChecked(selected)
            if button.property("selected") != selected:
                button.setProperty("selected", selected)
                button.style().unpolish(button)
                button.style().polish(button)


class ColorSwatch(QPushButton):
    def __init__(self, color, parent=None):
        super().__init__(parent)
        self.setObjectName("ColorSwatch")
        self.color = color
        self.setFixedSize(26, 30)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background:transparent; border:0; padding:0;")
        self._colors = theme_colors()

    def set_theme(self, theme, accent, background=None):
        self._colors = theme_colors(theme, accent, background)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = self.rect().center()
        if self.isChecked() or self.hasFocus():
            painter.setPen(QPen(QColor(self._colors["text"] if self.isChecked() else self._colors["accent"]), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, 12, 12)
        painter.setPen(QPen(QColor(self._colors["border"]), 1))
        painter.setBrush(QColor(self.color or self._colors["bg"]))
        painter.drawEllipse(center, 9, 9)
        if not self.color:
            painter.setPen(QPen(QColor(self._colors["muted"]), 1.1))
            painter.drawLine(center.x() - 5, center.y() + 5, center.x() + 5, center.y() - 5)


class ColorPalette(QWidget):
    """Color choices with a real custom picker; the combo retains cfg values."""
    def __init__(self, model: QComboBox, *, compact=False, parent=None):
        super().__init__(parent)
        self.setObjectName("ColorPalettePanel")
        self.setStyleSheet("QWidget#ColorPalettePanel {background:transparent;}")
        self.model = model
        model.setParent(self)
        model.hide()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3 if compact else 5)
        self.buttons = []
        for index in range(model.count()):
            color = str(model.itemData(index) or "")
            button = ColorSwatch(color)
            button.clicked.connect(lambda checked=False, i=index: self.select(i))
            self.buttons.append(button)
            row.addWidget(button)
        self.custom = QPushButton()
        self.custom.setObjectName("ColorPickerButton")
        self.custom.setFixedSize(30, 30)
        self.custom.setToolTip(tr("Другой цвет"))
        self.custom.setAccessibleName(tr("Другой цвет"))
        self.custom.setCursor(Qt.CursorShape.PointingHandCursor)
        set_button_icon(self.custom, "palette", size=17, role="muted")
        self.custom.clicked.connect(self.choose_color)
        row.addWidget(self.custom)
        model.currentIndexChanged.connect(self.sync)
        model.model().dataChanged.connect(self.sync)
        self.sync()

    def select(self, index):
        self.model.setCurrentIndex(index)
        # Clicking the selected checkable swatch toggles its button off, but
        # does not change the model or emit currentIndexChanged. Restore the
        # single selection even for that no-op click.
        self.sync()

    def sync(self, *_):
        for index, button in enumerate(self.buttons):
            selected = self.model.currentIndex() == index
            button.setChecked(selected)
            button.setAccessibleName(self.model.itemText(index))
            button.setToolTip(self.model.itemText(index))
            button.update()
        custom_selected = self.model.currentIndex() >= len(self.buttons)
        self.custom.setProperty("selected", custom_selected)
        self.custom.style().unpolish(self.custom)
        self.custom.style().polish(self.custom)

    def apply_color(self, value):
        value = color_value(value)
        if value is None:
            return False
        index = self.model.findData(value)
        if index < 0:
            self.model.addItem(tr("Свой цвет"), value)
            index = self.model.count() - 1
        self.model.setCurrentIndex(index)
        return True

    def choose_color(self):
        current = str(self.model.currentData() or "#0a0a0a")
        color = QColorDialog.getColor(QColor(current), self, tr("Выберите цвет"))
        if color.isValid():
            self.apply_color(color.name())


class BackgroundControl(QWidget):
    def __init__(self, model: QComboBox, parent=None):
        super().__init__(parent)
        self.setObjectName("BackgroundColorControl")
        self.setStyleSheet("QWidget#BackgroundColorControl {background:transparent;}")
        self.model = model
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.palette = ColorPalette(model, compact=True)
        row.addWidget(self.palette)
        self.hex = QLineEdit()
        self.hex.setObjectName("BackgroundHex")
        self.hex.setFixedWidth(98)
        self.hex.setMaxLength(7)
        self.hex.setPlaceholderText(tr("По теме"))
        self.hex.setAccessibleName(tr("Цвет фона"))
        self.hex.setToolTip(tr("Цвет в формате #RRGGBB"))
        row.addWidget(self.hex)
        model.currentIndexChanged.connect(self.sync)
        self.hex.editingFinished.connect(self.commit)
        self.sync()

    def sync(self, *_):
        self.hex.setText(str(self.model.currentData() or "").upper())
        was_invalid = self.hex.property("invalid")
        self.hex.setProperty("invalid", False)
        if was_invalid:
            self.hex.style().unpolish(self.hex)
            self.hex.style().polish(self.hex)

    def commit(self):
        value = self.hex.text().strip()
        if not value:
            self.model.setCurrentIndex(self.model.findData(""))
            self.sync()
            return True
        if self.palette.apply_color(value):
            self.sync()
            return True
        # Never save an invalid draft or silently replace the previous color.
        self.hex.setProperty("invalid", True)
        self.hex.style().unpolish(self.hex)
        self.hex.style().polish(self.hex)
        return False


class PreferenceRow(QFrame):
    """An appearance row that stacks naturally on narrow windows."""
    def __init__(self, title, hint, control, parent=None):
        super().__init__(parent)
        self.setObjectName("InterfaceRow")
        self.row = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.row.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.row.setContentsMargins(0, 11, 0, 11)
        self.row.setSpacing(12)
        labels = QWidget()
        self.labels = labels
        labels.setObjectName("PreferenceLabels")
        labels.setStyleSheet("QWidget#PreferenceLabels {background:transparent;}")
        labels.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        text = QVBoxLayout(labels)
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(4)
        name = QLabel(title)
        name.setObjectName("InterfaceRowTitle")
        name.setWordWrap(True)
        text.addWidget(name)
        if hint:
            subtitle = QLabel(hint)
            subtitle.setObjectName("InterfaceRowHint")
            subtitle.setWordWrap(True)
            text.addWidget(subtitle)
        self.row.addWidget(labels, 1)
        if not isinstance(control, QWidget):
            wrapper = QWidget()
            wrapper.setObjectName("PreferenceSliderWrapper")
            wrapper.setStyleSheet("QWidget#PreferenceSliderWrapper {background:transparent;}")
            wrapper.setLayout(control)
            control = wrapper
        self.control = control
        self.row.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        margins = self.row.contentsMargins()
        available = max(1, width - margins.left() - margins.right())
        control_size = self.control.sizeHint().expandedTo(self.control.minimumSizeHint())
        stacked = width < 540
        label_width = available if stacked else max(1, available - control_size.width() - self.row.spacing())
        label_height = self.labels.layout().heightForWidth(label_width)
        if label_height < 0:
            label_height = self.labels.sizeHint().height()
        body = (label_height + self.row.spacing() + control_size.height()
                if stacked else max(label_height, control_size.height()))
        return margins.top() + body + margins.bottom()

    def sizeHint(self):
        preferred = self.row.sizeHint()
        return QSize(preferred.width(), self.heightForWidth(preferred.width()))

    def minimumSizeHint(self):
        # A horizontal sum of label+control minima would prevent the narrow
        # width that the stacked layout is intended to support.
        width = max(self.control.minimumSizeHint().width(), self.labels.minimumSizeHint().width())
        return QSize(width, self.heightForWidth(width))

    def resizeEvent(self, event):
        direction = (QBoxLayout.Direction.TopToBottom if self.width() < 540
                     else QBoxLayout.Direction.LeftToRight)
        if self.row.direction() != direction:
            self.row.setDirection(direction)
            self.updateGeometry()
        height = self.heightForWidth(self.width())
        if self.minimumHeight() != height:
            self.setMinimumHeight(height)
            self.updateGeometry()
        super().resizeEvent(event)
