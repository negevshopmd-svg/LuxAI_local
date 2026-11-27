"""The Text helper window at the cursor (0.4.3u).

Page 1 — the actions: 1 fix · 2 improve · 3 shorten · 4 translate · 5 reply, or a request of your own.
Page 2 — «working…». Page 3 — the result, editable: Ctrl+Enter (or the button) puts it in place of the
selection, «Copy» only copies it, «Back» tries another action. Esc closes at any time.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

WORDS = {
    "title": ("Помощник текста", "Text helper", "Asistent de text"),
    "fix": ("Исправить ошибки", "Fix mistakes", "Corectează greșelile"),
    "improve": ("Улучшить стиль", "Improve style", "Îmbunătățește stilul"),
    "shorten": ("Сократить", "Shorten", "Scurtează"),
    "translate": ("Перевести", "Translate", "Tradu"),
    "reply": ("Ответить на сообщение", "Reply to the message", "Răspunde la mesaj"),
    "custom": ("Своя команда… (например «сделай вежливее»)", "Your own request… (e.g. “make it more polite”)",
               "Cererea ta… (de ex. „fă-l mai politicos”)"),
    "hint_menu": ("1–5 — действие · Enter — по умолчанию · Esc — закрыть",
                  "1–5 — action · Enter — default · Esc — close",
                  "1–5 — acțiune · Enter — implicită · Esc — închide"),
    "working": ("Нейросеть работает…", "The AI is working…", "AI lucrează…"),
    "translating": ("Перевожу…", "Translating…", "Traduc…"),
    "replace": ("Заменить", "Replace", "Înlocuiește"),
    "copy": ("Копировать", "Copy", "Copiază"),
    "back": ("Назад", "Back", "Înapoi"),
    "hint_result": ("Ctrl+Enter — заменить выделенное · текст можно поправить · Esc — закрыть",
                    "Ctrl+Enter — replace the selection · you can edit the text · Esc — close",
                    "Ctrl+Enter — înlocuiește selecția · poți edita textul · Esc — închide"),
    "offline": ("офлайн-переводчик", "offline translator", "traducător offline"),
    "cloud": ("облачный ИИ", "cloud AI", "AI în cloud"),
    "local": ("локальная модель", "local model", "model local"),
    "done_by": ("Готово · {who}", "Done · {who}", "Gata · {who}"),
    "default": ("по умолчанию", "default", "implicit"),
}


def word(key: str, language: str) -> str:
    return WORDS[key][{"ru": 0, "en": 1, "ro": 2}.get(language, 0)]


def preview(text: str, limit: int = 140) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[:limit - 1].rstrip() + "…"


class TextHelperPopup(QDialog):
    action_chosen = Signal(str, str)     # action, own request ("" unless action == "custom")
    replace_requested = Signal(str)
    copy_requested = Signal(str)

    ORDER = ("fix", "improve", "shorten", "translate", "reply")

    def __init__(self, selected: str, language: str, default_action: str = "fix", parent=None):
        super().__init__(parent)
        self.language = language
        self.default_action = default_action if default_action in self.ORDER else "fix"
        self.setObjectName("ExtensionPicker")
        self.setWindowTitle(word("title", language))
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setProperty("i18n_skip", True)
        self.resize(440, 380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        heading = QLabel(word("title", language))
        heading.setStyleSheet("font-size:15px;font-weight:700;")
        layout.addWidget(heading)
        self.excerpt = QLabel(preview(selected))
        self.excerpt.setObjectName("Muted")
        self.excerpt.setWordWrap(True)
        layout.addWidget(self.excerpt)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        self.pages.addWidget(self._menu_page())
        self.pages.addWidget(self._busy_page())
        self.pages.addWidget(self._result_page())
        self.hint = QLabel(word("hint_menu", language))
        self.hint.setObjectName("Muted")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("font-size:11px;")
        layout.addWidget(self.hint)
        replace = QShortcut(QKeySequence("Ctrl+Return"), self)
        replace.activated.connect(self._replace)
        replace_enter = QShortcut(QKeySequence("Ctrl+Enter"), self)
        replace_enter.activated.connect(self._replace)

    # -- pages --
    def _menu_page(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 4, 0, 0)
        column.setSpacing(6)
        self.buttons = {}
        for number, action in enumerate(self.ORDER, start=1):
            label = f"{number}   {word(action, self.language)}"
            if action == self.default_action:
                label += f"   · {word('default', self.language)}"
            button = QPushButton(label)
            button.setStyleSheet("text-align:left; padding:8px 12px;")
            button.setAutoDefault(False)  # Enter is handled in keyPressEvent, never by QDialog
            button.clicked.connect(lambda checked=False, a=action: self.choose(a))
            column.addWidget(button)
            self.buttons[action] = button
        self.custom = QLineEdit()
        self.custom.setPlaceholderText(word("custom", self.language))
        self.custom.setMaxLength(300)
        self.custom.returnPressed.connect(self._custom)
        column.addWidget(self.custom)
        column.addStretch()
        return page

    def _busy_page(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        self.busy = QLabel()
        self.busy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.busy.setStyleSheet("font-size:14px;")
        column.addStretch()
        column.addWidget(self.busy)
        column.addStretch()
        return page

    def _result_page(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 4, 0, 0)
        self.result = QPlainTextEdit()
        self.result.setProperty("i18n_skip", True)
        column.addWidget(self.result, 1)
        self.source = QLabel()
        self.source.setObjectName("Muted")
        self.source.setStyleSheet("font-size:11px;")
        column.addWidget(self.source)
        row = QHBoxLayout()
        self.back_button = QPushButton(word("back", self.language))
        self.back_button.clicked.connect(self.show_menu)
        self.copy_button = QPushButton(word("copy", self.language))
        self.copy_button.clicked.connect(lambda: self._finish(self.copy_requested))
        self.replace_button = QPushButton(word("replace", self.language) + "   Ctrl+Enter")
        self.replace_button.setObjectName("Primary")
        self.replace_button.clicked.connect(self._replace)
        row.addWidget(self.back_button)
        row.addStretch()
        row.addWidget(self.copy_button)
        row.addWidget(self.replace_button)
        column.addLayout(row)
        return page

    # -- states --
    def show_menu(self):
        self.pages.setCurrentIndex(0)
        self.hint.setText(word("hint_menu", self.language))
        self.buttons[self.default_action].setFocus()

    def show_busy(self, action: str):
        self.busy.setText(word("translating" if action == "translate" else "working", self.language))
        self.pages.setCurrentIndex(1)
        self.hint.setText("Esc")

    def show_result(self, text: str, who: str):
        self.result.setPlainText(text)
        self.source.setText(word("done_by", self.language).format(who=word(who, self.language))
                            if who in ("offline", "cloud", "local") else "")
        self.pages.setCurrentIndex(2)
        self.hint.setText(word("hint_result", self.language))
        self.replace_button.setFocus()

    def show_error(self, message: str):
        self.show_menu()
        self.hint.setText(message)

    # -- input --
    def choose(self, action: str, instruction: str = ""):
        self.action_chosen.emit(action, instruction)

    def _custom(self):
        request = " ".join(self.custom.text().split())
        # QLineEdit passes Enter on to the window after returnPressed: the window must not ALSO run the
        # default action for the same key press.
        self._enter_taken = True
        if request:
            self.choose("custom", request)

    def _replace(self):
        if self.pages.currentIndex() == 2:
            self._finish(self.replace_requested)

    def _finish(self, signal):
        value = self.result.toPlainText()
        if not value.strip():
            return
        self.close()
        signal.emit(value)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._replace()
            return
        if self.pages.currentIndex() == 0 and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (
                getattr(self, "_enter_taken", False) or self.focusWidget() is self.custom):
            self._enter_taken = False
            return  # the own-request field handled this Enter; QDialog must not click a button too
        if self.pages.currentIndex() == 0 and self.focusWidget() is not self.custom:
            if Qt.Key.Key_1 <= key <= Qt.Key.Key_5:
                self.choose(self.ORDER[key - Qt.Key.Key_1])
                return
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if getattr(self, "_enter_taken", False):
                    self._enter_taken = False
                    return  # Enter of the own-request field: never also «press» a menu button
                focused = next((action for action, button in self.buttons.items() if button.hasFocus()),
                               self.default_action)
                self.choose(focused)
                return
        super().keyPressEvent(event)

    def show_at_cursor(self):
        position = QCursor.pos()
        screen = QGuiApplication.screenAt(position) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(area.left(), position.x() - 20), area.right() - self.width())
        y = min(max(area.top(), position.y() + 16), area.bottom() - self.height())
        self.move(QPoint(x, y))
        self.show()
        self.raise_()
        self.activateWindow()
        self.show_menu()
