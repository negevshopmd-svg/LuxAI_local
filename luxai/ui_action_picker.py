"""Luxify-inspired action picker and configurable action detail dialogs.

This is real PySide6 UI, not a static mockup. Search, category selection,
disabled action explanations, keyboard double-click/Enter and Save work.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from luxai.action_catalog import CATALOG, CATEGORIES, HOTKEYS, validate_step
from luxai.command_registry import APP_TARGETS
from luxai.file_actions import ALLOWED_LOCATIONS
from luxai.steam_games import GAMES


APP_LABELS = {
    "telegram": "Telegram", "discord": "Discord", "steam": "Steam",
    "chrome": "Google Chrome", "firefox": "Mozilla Firefox",
    "edge": "Microsoft Edge", "spotify": "Spotify",
    "notepad": "Блокнот", "calculator": "Калькулятор",
    "explorer": "Проводник Windows",
}
LOCATION_LABELS = {
    "desktop": "Рабочий стол", "documents": "Документы", "downloads": "Загрузки",
}


class ActionOptionsDialog(QDialog):
    """Configure the target only after an explicitly selected palette action."""

    def __init__(self, action, step=None, parent=None):
        super().__init__(parent)
        self.action = action
        self.current_step = dict(step or {})
        self.data = None
        details = CATALOG[action]
        self.setWindowTitle("Настроить действие")
        self.setMinimumWidth(485)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(23, 22, 23, 22)
        layout.setSpacing(16)

        heading = QLabel(details["title"])
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)
        description = QLabel(details["description"])
        description.setWordWrap(True)
        description.setObjectName("Muted")
        layout.addWidget(description)
        form = QFormLayout()
        form.setVerticalSpacing(14)
        self.target = None
        self.location = None

        if action == "open_app":
            self.target = QComboBox()
            for app in APP_TARGETS:
                self.target.addItem(APP_LABELS.get(app, app), app)
            self._choose(self.target, self.current_step.get("target"))
            form.addRow("Приложение", self.target)
        elif action == "launch_game":
            self.target = QComboBox()
            for identifier, (_appid, game_name) in GAMES.items():
                self.target.addItem(game_name, identifier)
            self._choose(self.target, self.current_step.get("target"))
            form.addRow("Игра Steam", self.target)
        elif action == "hotkey":
            self.target = QComboBox()
            for shortcut in HOTKEYS:
                self.target.addItem(shortcut.upper(), shortcut)
            self._choose(self.target, self.current_step.get("target"))
            form.addRow("Сочетание", self.target)
        elif action in {"create_file", "create_folder", "list_files"}:
            if action != "list_files":
                self.target = QLineEdit(str(self.current_step.get("target", "")))
                self.target.setPlaceholderText(
                    "Новый файл.txt" if action == "create_file" else "Новая папка"
                )
                form.addRow("Название", self.target)
            self.location = QComboBox()
            for identifier in ALLOWED_LOCATIONS:
                self.location.addItem(LOCATION_LABELS[identifier], identifier)
            self._choose(self.location, self.current_step.get("location"))
            form.addRow("Папка", self.location)
        elif action in {"open_website", "search_web", "type_text", "speak_text"}:
            self.target = QLineEdit(str(self.current_step.get("target", "")))
            prompts = {
                "open_website": "https://example.com",
                "search_web": "Что найти в интернете",
                "type_text": "Текст для активного окна",
                "speak_text": "Текст, который произнесёт Jarvis",
            }
            self.target.setPlaceholderText(prompts[action])
            self.target.setMaxLength(400)
            form.addRow("Значение", self.target)
        elif action in {"wait_seconds", "mouse_scroll"}:
            self.target = QSpinBox()
            self.target.setRange(1, 30) if action == "wait_seconds" else self.target.setRange(-10, 10)
            self.target.setValue(int(self.current_step.get("target") or (1 if action == "wait_seconds" else 3)))
            self.target.setSuffix(" сек" if action == "wait_seconds" else " шага")
            form.addRow("Значение", self.target)
        elif action == "mouse_move":
            self.target = QLineEdit(str(self.current_step.get("target", "")))
            self.target.setPlaceholderText("Например: 600,350")
            form.addRow("Координаты X,Y", self.target)
        else:
            hint = QLabel("Действие не требует параметров.")
            hint.setObjectName("Muted")
            form.addRow("", hint)
        layout.addLayout(form)

        caution = QLabel(
            "Действие выполняется только из сохранённой команды; "
            "для взаимодействия с окнами и изменения системы Jarvis запросит подтверждение."
        )
        caution.setWordWrap(True)
        caution.setObjectName("Muted")
        layout.addWidget(caution)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = QPushButton("Добавить" if not step else "Применить")
        save.setObjectName("Primary")
        save.clicked.connect(self._accept)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    @staticmethod
    def _choose(combo, value):
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _accept(self):
        target = ""
        if isinstance(self.target, QComboBox):
            target = self.target.currentData()
        elif isinstance(self.target, QLineEdit):
            target = self.target.text().strip()
        elif isinstance(self.target, QSpinBox):
            target = str(self.target.value())
        raw = {
            "action": self.action,
            "target": target,
            "location": self.location.currentData() if self.location else "desktop",
        }
        try:
            self.data = validate_step(raw)
        except ValueError as exc:
            QMessageBox.warning(self, "Некорректное действие", str(exc))
            return
        self.accept()


class ActionPicker(QDialog):
    """Large category-based action palette matching the Luxify reference."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ActionPickerDialog")
        self.setWindowTitle("Добавить действие")
        self.setMinimumSize(750, 545)
        self.resize(800, 585)
        self.action = None
        self.step = None
        self._selected = None
        self._buttons = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(14)
        header = QHBoxLayout()
        plus_icon = QLabel("＋")
        plus_icon.setObjectName("ActionPickerIcon")
        plus_icon.setFixedSize(43, 43)
        plus_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        plus_icon.setStyleSheet(
            "background:#293a59; color:white; font-size:25px; "
            "border-radius:12px; font-weight:500;"
        )
        header.addWidget(plus_icon)
        heading = QVBoxLayout()
        title = QLabel("Добавить действие")
        title.setStyleSheet("font-size:19px; font-weight:700;")
        heading.addWidget(title)
        sub = QLabel("Что сделает команда. Двойной щелчок — добавить сразу.")
        sub.setObjectName("Muted")
        heading.addWidget(sub)
        header.addLayout(heading, 1)
        close = QPushButton("×")
        close.setObjectName("PickerClose")
        close.setFixedSize(32, 32)
        close.clicked.connect(self.reject)
        header.addWidget(close)
        root.addLayout(header)

        self.search = QLineEdit()
        self.search.setPlaceholderText("⌕   Поиск: «открыть», «клавиши», «громкость»…")
        self.search.setObjectName("ActionSearch")
        self.search.textChanged.connect(self._refresh_items)
        root.addWidget(self.search)

        main = QHBoxLayout()
        main.setSpacing(13)
        self.category_list = QListWidget()
        self.category_list.setObjectName("ActionCategories")
        self.category_list.setFixedWidth(185)
        for title, icon in CATEGORIES:
            item = QListWidgetItem(f"{icon}   {title}")
            item.setData(Qt.ItemDataRole.UserRole, title)
            self.category_list.addItem(item)
        self.category_list.currentRowChanged.connect(self._refresh_items)
        main.addWidget(self.category_list)

        self.action_scroll = QScrollArea()
        self.action_scroll.setObjectName("ActionScroll")
        self.action_scroll.setWidgetResizable(True)
        self.action_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.action_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.action_area = QWidget()
        self.action_area.setObjectName("PickerActionArea")
        self.action_layout = QVBoxLayout(self.action_area)
        self.action_layout.setContentsMargins(9, 4, 9, 4)
        self.action_layout.setSpacing(5)
        self.action_scroll.setWidget(self.action_area)
        main.addWidget(self.action_scroll, 1)
        root.addLayout(main, 1)

        buttons = QHBoxLayout()
        empty = QPushButton("＋  Пустое действие")
        empty.clicked.connect(self._add_empty)
        buttons.addWidget(empty)
        buttons.addStretch()
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.add_button = QPushButton("Добавить")
        self.add_button.setObjectName("Primary")
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self._add_selected)
        buttons.addWidget(self.add_button)
        root.addLayout(buttons)
        self.setStyleSheet("""
            QDialog#ActionPickerDialog {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #202f4e,stop:0.52 #1b2536,stop:1 #171b25);
                color: #f3f5fc;
            }
            QListWidget#ActionCategories {
                background: transparent;
                border: none;
                border-right:2px solid #394863;
                color:#cdd6e5;
                outline:none;
                padding:0 5px 0 0;
                font-size:13px;
            }
            QListWidget#ActionCategories::item {
                border-radius:9px;
                margin:2px 1px;
                padding:11px 8px;
            }
            QListWidget#ActionCategories::item:selected {background:#34445e; color:white;}
            QListWidget#ActionCategories::item:hover {background:#2a3950;}
            QScrollArea#ActionScroll, QWidget#PickerActionArea {
                background:transparent; border:none;
            }
            QLineEdit#ActionSearch {
                background:#282e3b; border:1px solid #3b465a;
                border-radius:11px; padding:12px; color:white;
            }
            QPushButton#PickerClose {background:transparent; border:0; font-size:20px;}
            QPushButton#PickerItem {
                background:transparent; border:none; text-align:left;
                padding:13px 12px; border-radius:9px; color:#f0f4ff;
            }
            QPushButton#PickerItem:hover {background:#303c51;}
            QPushButton#PickerItem[chosen="true"] {
                background:#2c466e; border:1px solid #4386ff;
            }
            QPushButton#PickerItem:disabled {color:#8995ab;}
        """)
        self.category_list.setCurrentRow(0)
        self._refresh_items()

    def _refresh_items(self, *_):
        from PySide6.QtWidgets import QLayoutItem
        while self.action_layout.count():
            item = self.action_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._buttons.clear()
        self._selected = None
        self.add_button.setEnabled(False)
        current = self.category_list.currentItem()
        chosen_cat = current.data(Qt.ItemDataRole.UserRole) if current else "Все действия"
        query = self.search.text().strip().casefold()

        found = {}
        for details in CATALOG.values():
            if chosen_cat != "Все действия" and details["category"] != chosen_cat:
                continue
            if query and query not in (
                details["title"] + " " + details["description"] + " "
                + details["category"]
            ).casefold():
                continue
            found.setdefault(details["category"], []).append(details)

        if not found:
            note = QLabel("Действия не найдены. Попробуйте другой запрос.")
            note.setObjectName("Muted")
            self.action_layout.addWidget(note)
        for category, entries in found.items():
            label = QLabel(category)
            label.setStyleSheet("color:#aebbd0; font-size:12px; font-weight:600; margin-top:5px;")
            self.action_layout.addWidget(label)
            for details in entries:
                action = details["id"]
                button = QPushButton(
                    ("◈   " if details["available"] else "⚠   ")
                    + details["title"] + ("   ·  Недоступно" if not details["available"] else "")
                    + "\n     " + details["description"]
                )
                button.setObjectName("PickerItem")
                button.setMinimumHeight(58)
                button.setProperty("chosen", False)
                button.setToolTip(details["description"])
                button.setEnabled(details["available"])
                if details["available"]:
                    button.clicked.connect(lambda _checked=False, a=action: self._choose_action(a))
                self.action_layout.addWidget(button)
                self._buttons[action] = button
        self.action_layout.addStretch(1)

    def _choose_action(self, action):
        if action not in CATALOG or not CATALOG[action]["available"]:
            return
        if self._selected == action:
            self._add_selected()
            return
        self._selected = action
        for key, button in self._buttons.items():
            button.setProperty("chosen", key == action)
            button.style().unpolish(button)
            button.style().polish(button)
        self.add_button.setEnabled(True)

    def _add_empty(self):
        self.step = validate_step({"action": "noop"})
        self.accept()

    def _add_selected(self):
        if self._selected is None:
            return
        configured = ActionOptionsDialog(self._selected, parent=self)
        if configured.exec() != QDialog.DialogCode.Accepted:
            return
        self.step = configured.data
        self.accept()
