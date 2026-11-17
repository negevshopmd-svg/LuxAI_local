"""Clipboard history window shown at the cursor.

Enter pastes the chosen item, Shift+Enter pastes it without formatting,
Delete removes it, Ctrl+P pins it. Right click or the sparkle button on a
text item offers the AI actions: translate, fix mistakes, shorten.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QToolButton, QVBoxLayout, QWidget,
)

WORDS = {
    "title": ("История буфера обмена", "Clipboard history", "Istoric clipboard"),
    "search": ("Поиск…", "Search…", "Caută…"),
    "empty": ("История пуста. Скопируйте что-нибудь (Ctrl+C).", "History is empty. Copy something (Ctrl+C).",
              "Istoricul e gol. Copiază ceva (Ctrl+C)."),
    "nothing": ("Ничего не найдено.", "Nothing found.", "Nu s-a găsit nimic."),
    "hint": ("Enter — вставить · Shift+Enter — без форматирования · Ctrl+P — закрепить · Del — удалить",
             "Enter — paste · Shift+Enter — plain · Ctrl+P — pin · Del — delete",
             "Enter — lipește · Shift+Enter — fără formatare · Ctrl+P — fixează · Del — șterge"),
    "paste": ("Вставить", "Paste", "Lipește"),
    "plain": ("Вставить без форматирования", "Paste without formatting", "Lipește fără formatare"),
    "pin": ("Закрепить", "Pin", "Fixează"),
    "unpin": ("Открепить", "Unpin", "Anulează fixarea"),
    "delete": ("Удалить", "Delete", "Șterge"),
    "translate": ("Перевести", "Translate", "Tradu"),
    "fix": ("Исправить ошибки", "Fix mistakes", "Corectează greșelile"),
    "short": ("Кратко", "Shorten", "Pe scurt"),
    "ai": ("Нейросеть", "AI", "AI"),
    "image": ("Картинка", "Picture", "Imagine"),
    "now": ("только что", "just now", "acum"),
    "min": ("{n} мин назад", "{n} min ago", "acum {n} min"),
    "hour": ("{n} ч назад", "{n} h ago", "acum {n} h"),
    "day": ("{n} дн назад", "{n} d ago", "acum {n} zile"),
}


def word(key: str, language: str) -> str:
    return WORDS[key][{"ru": 0, "en": 1, "ro": 2}.get(language, 0)]


def ago(stamp: float, language: str, now: float | None = None) -> str:
    seconds = max(0, (time.time() if now is None else now) - float(stamp or 0))
    if seconds < 60:
        return word("now", language)
    if seconds < 3600:
        return word("min", language).format(n=int(seconds // 60))
    if seconds < 86400:
        return word("hour", language).format(n=int(seconds // 3600))
    return word("day", language).format(n=int(seconds // 86400))


def preview(item: dict, language: str) -> str:
    if item["kind"] == "image":
        width, height = (item.get("size") or [0, 0])[:2]
        return word("image", language) + (f" {width}×{height}" if width else "")
    return " ".join(item.get("text", "").split())[:160]


class ElidedLabel(QLabel):
    """One line that ends with «…» when it does not fit (long links too)."""

    def __init__(self, full: str):
        super().__init__()
        self.full = full
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setMinimumWidth(80)
        self.setToolTip(full[:400])
        self.setText(full)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setText(self.fontMetrics().elidedText(self.full, Qt.TextElideMode.ElideRight, max(40, self.width())))

    def minimumSizeHint(self):
        return QSize(80, super().minimumSizeHint().height())

    def sizeHint(self):
        return QSize(200, super().sizeHint().height())


class ClipRow(QWidget):
    """One history line: thumbnail or text, app and time, sparkle button."""
    ai_clicked = Signal()

    def __init__(self, item: dict, language: str):
        super().__init__()
        self.setObjectName("ClipRow")
        line = QHBoxLayout(self)
        line.setContentsMargins(8, 6, 6, 6)
        line.setSpacing(10)
        if item["kind"] == "image" and item.get("thumb"):
            picture = QLabel()
            pixmap = QPixmap()
            pixmap.loadFromData(item["thumb"])
            picture.setPixmap(pixmap)
            picture.setFixedSize(QSize(96, 64))
            picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
            line.addWidget(picture)
        body = QVBoxLayout()
        body.setSpacing(4)
        body.setContentsMargins(0, 2, 0, 2)
        main = ElidedLabel(("📌 " if item.get("pinned") else "") + preview(item, language))
        body.addWidget(main)
        meta = QLabel(" · ".join(part for part in (str(item.get("app") or "").removesuffix(".exe"),
                                                    ago(item.get("time", 0), language)) if part))
        meta.setObjectName("Muted")
        meta.setStyleSheet("font-size:11px;")
        body.addWidget(meta)
        line.addLayout(body, 1)
        if item["kind"] == "text":
            star = QToolButton()
            star.setObjectName("ClipAI")
            star.setToolTip(word("ai", language))
            star.setAutoRaise(True)
            star.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            try:
                from luxai.icons import icon
                star.setIcon(icon("sparkles", color="#a78bfa"))
            except Exception:
                star.setText("✦")
            star.clicked.connect(self.ai_clicked.emit)
            line.addWidget(star)


class ClipboardPopup(QDialog):
    picked = Signal(int, bool)        # item id, plain (no formatting)
    pin_toggled = Signal(int)
    removed = Signal(int)
    ai_requested = Signal(int, str)   # item id, translate | fix | short

    def __init__(self, items: list[dict], language: str, parent=None):
        super().__init__(parent)
        self.language = language
        self.items = list(items)
        self.runtime_items = None
        self.setObjectName("ExtensionPicker")
        self.setWindowTitle(word("title", language))
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setProperty("i18n_skip", True)
        self.resize(440, 500)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        heading = QLabel(word("title", language))
        heading.setStyleSheet("font-size:15px;font-weight:700;")
        layout.addWidget(heading)
        self.search = QLineEdit()
        self.search.setPlaceholderText(word("search", language))
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.setProperty("i18n_skip", True)
        self.list.itemActivated.connect(lambda item: self._pick(item, False))
        self.list.itemDoubleClicked.connect(lambda item: self._pick(item, False))
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self.list, 1)
        self.empty = QLabel()
        self.empty.setObjectName("Muted")
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        hint = QLabel(word("hint", language))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size:11px;")
        layout.addWidget(hint)
        self._fill()
        self.search.setFocus()

    # -- content --
    def _fill(self):
        current = self._current_id()
        self.list.clear()
        for entry in self.items:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, entry["id"])
            item.setData(Qt.ItemDataRole.UserRole + 1, (entry.get("text") or "").casefold())
            row = ClipRow(entry, self.language)
            row.ai_clicked.connect(lambda item_id=entry["id"]: self._ai_menu(item_id))
            hint = row.sizeHint()
            item.setSizeHint(QSize(hint.width(), max(hint.height(), 78 if entry["kind"] == "image" else 58)))
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
        self._filter(self.search.text())
        if current is not None:
            for index in range(self.list.count()):
                if self.list.item(index).data(Qt.ItemDataRole.UserRole) == current:
                    self.list.setCurrentRow(index)

    def refresh_from_runtime(self):
        try:
            if self.runtime_items is not None:
                self.items = list(self.runtime_items())
                self._fill()
        except RuntimeError:
            pass

    def _current_id(self):
        item = self.list.currentItem() if hasattr(self, "list") else None
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    def _entry(self, item_id):
        return next((entry for entry in self.items if entry["id"] == item_id), None)

    def _filter(self, value):
        words = str(value or "").casefold().split()
        for row in range(self.list.count()):
            item = self.list.item(row)
            haystack = item.data(Qt.ItemDataRole.UserRole + 1) or ""
            item.setHidden(bool(words) and not all(part in haystack for part in words))
        visible = [row for row in range(self.list.count()) if not self.list.item(row).isHidden()]
        current = self.list.currentRow()
        if visible and current not in visible:
            self.list.setCurrentRow(visible[0])
        self.empty.setText(word("empty" if not self.items else "nothing", self.language))
        self.empty.setVisible(not visible)

    # -- actions --
    def _pick(self, item, plain: bool):
        if item is None or item.isHidden():
            return
        item_id = item.data(Qt.ItemDataRole.UserRole)
        self.close()
        self.picked.emit(item_id, plain)

    def _menu_actions(self, item_id):
        entry = self._entry(item_id)
        if entry is None:
            return None
        menu = QMenu(self)
        menu.addAction(word("paste", self.language), lambda: self._pick_id(item_id, False))
        if entry["kind"] == "text":
            menu.addAction(word("plain", self.language), lambda: self._pick_id(item_id, True))
        menu.addAction(word("unpin" if entry.get("pinned") else "pin", self.language),
                       lambda: self.pin_toggled.emit(item_id))
        if entry["kind"] == "text":
            menu.addSeparator()
            for mode in ("translate", "fix", "short"):
                menu.addAction(word(mode, self.language), lambda m=mode: self._ask_ai(item_id, m))
        menu.addSeparator()
        menu.addAction(word("delete", self.language), lambda: self.removed.emit(item_id))
        return menu

    def _pick_id(self, item_id, plain):
        self.close()
        self.picked.emit(item_id, plain)

    def _ask_ai(self, item_id, mode):
        self.close()
        self.ai_requested.emit(item_id, mode)

    def _context_menu(self, position):
        item = self.list.itemAt(position)
        if item is None:
            return
        self.list.setCurrentItem(item)
        menu = self._menu_actions(item.data(Qt.ItemDataRole.UserRole))
        if menu is not None:
            menu.exec(self.list.viewport().mapToGlobal(position))

    def _ai_menu(self, item_id):
        menu = QMenu(self)
        for mode in ("translate", "fix", "short"):
            menu.addAction(word(mode, self.language), lambda m=mode: self._ask_ai(item_id, m))
        menu.exec(QCursor.pos())

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._pick(self.list.currentItem(), bool(modifiers & Qt.KeyboardModifier.ShiftModifier))
            return
        if key == Qt.Key.Key_Escape:
            self.close()
            return
        if key == Qt.Key.Key_Delete and (self.list.hasFocus() or not self.search.text()):
            item_id = self._current_id()
            if item_id is not None:
                self.removed.emit(item_id)
            return
        if key == Qt.Key.Key_P and modifiers & Qt.KeyboardModifier.ControlModifier:
            item_id = self._current_id()
            if item_id is not None:
                self.pin_toggled.emit(item_id)
            return
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_PageDown, Qt.Key.Key_PageUp) and self.search.hasFocus():
            self.list.setFocus()
            self.list.keyPressEvent(event)
            return
        super().keyPressEvent(event)

    def show_at_cursor(self):
        position = QCursor.pos()
        screen = QGuiApplication.screenAt(position) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(area.left(), position.x() - 20), area.right() - self.width())
        y = min(max(area.top(), position.y() - 20), area.bottom() - self.height())
        self.move(QPoint(x, y))
        self.show()
        self.raise_()
        self.activateWindow()
