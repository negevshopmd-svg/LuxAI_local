"""ChatGPT-style expanding input: Enter sends, Shift+Enter starts a new line."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPlainTextEdit


class ChatPromptEdit(QPlainTextEdit):
    returnPressed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatMessageField")
        self.setPlaceholderText("Напишите сообщение или команду…")
        self.setTabChangesFocus(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumHeight(43)
        self.setMaximumHeight(148)
        self.textChanged.connect(self._resize_to_text)
        self._resize_to_text()

    def text(self):
        return self.toPlainText()

    def setText(self, text):
        self.setPlainText(str(text))

    def cursorPosition(self):
        """QLineEdit compatibility for existing settings/localization workflows."""
        return self.textCursor().position()

    def setCursorPosition(self, position):
        cursor = self.textCursor()
        cursor.setPosition(max(0, min(int(position), len(self.toPlainText()))))
        self.setTextCursor(cursor)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.returnPressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _resize_to_text(self):
        # Only grow the composer when lines of actual input require it.
        height = min(148, max(43, int(self.document().size().height()) + 20))
        if self.height() != height:
            self.setFixedHeight(height)
