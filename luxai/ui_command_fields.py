"""Wrapping, editable phrase chips used by the command editor."""
from PySide6.QtCore import QPoint, QRect, QSize, Signal
from PySide6.QtWidgets import QHBoxLayout, QLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget


class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        from PySide6.QtCore import Qt
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        return QSize(0, 30 if self._items else 0)

    def _arrange(self, rect, measure):
        x, y, line = rect.x(), rect.y(), 0
        for item in self._items:
            if item.isEmpty():
                continue
            size = item.sizeHint()
            width = min(size.width(), max(0, rect.width()))
            if x > rect.x() and x + width > rect.right() + 1:
                x, y, line = rect.x(), y + line + self.spacing(), 0
            if not measure:
                item.setGeometry(QRect(QPoint(x, y), QSize(width, size.height())))
            x += width + self.spacing()
            line = max(line, size.height())
        return y + line - rect.y()


class PhraseChips(QWidget):
    changed = Signal()

    def __init__(self, values=(), placeholder="", add_text="+", parent=None):
        super().__init__(parent)
        self.setObjectName("EditorPlain")
        self.values = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
        self._editing = not self.values
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.chips = QWidget()
        self.chips.setObjectName("EditorPlain")
        self.flow = FlowLayout(self.chips)
        layout.addWidget(self.chips)
        self.input = QLineEdit(self.chips)
        self.input.setPlaceholderText(placeholder)
        self.input.setMinimumWidth(215)
        self.input.setMaxLength(1500)
        self.input.returnPressed.connect(self.commit)
        self.input.textChanged.connect(self.changed)
        self.add_button = QPushButton(add_text, self.chips)
        self.add_button.setAutoDefault(False)
        self.add_button.clicked.connect(self.begin_add)
        self.refresh()

    def get_values(self):
        pending = [value.strip() for value in self.input.text().split(",") if value.strip()]
        return list(dict.fromkeys(self.values + pending))

    def begin_add(self):
        if self._editing and self.input.text().strip():
            self.commit()
        else:
            self._editing = True
            self.input.show()
            self.flow.invalidate()
            self.input.setFocus()

    def commit(self):
        self.values = self.get_values()
        self.input.clear()
        self._editing = not self.values
        self.refresh()
        self.changed.emit()

    def remove(self, value):
        self.values.remove(value)
        if not self.values:
            self._editing = True
        self.refresh()
        self.changed.emit()

    def refresh(self):
        while self.flow.count():
            item = self.flow.takeAt(0)
            widget = item.widget()
            if widget not in (self.input, self.add_button):
                widget.hide()
                widget.deleteLater()
        for value in self.values:
            chip = QPushButton(value + "  ×")
            chip.setObjectName("PhraseChip")
            chip.setProperty("i18n_skip", True)
            chip.setAutoDefault(False)
            chip.setToolTip(value)
            chip.clicked.connect(lambda _checked=False, selected=value: self.remove(selected))
            self.flow.addWidget(chip)
        self.input.setVisible(self._editing)
        self.flow.addWidget(self.input)
        self.flow.addWidget(self.add_button)
        self.flow.invalidate()
        self.chips.updateGeometry()
