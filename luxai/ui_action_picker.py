"""Luxify-style configurable action picker with readable, non-overlapping rows.

The window is a frameless, dark PySide6 dialog (no bright Windows title bar).
Each action is a separate two-line widget, never a multi-line QPushButton.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget, QSizePolicy,
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
    "desktop": "Рабочий стол", "documents": "Документы",
    "downloads": "Загрузки",
}
CATEGORY_ICONS = {
    "Запуск": "↗", "Клавиши": "⌨", "Мышь": "◉", "Программа": "◷",
    "Озвучка": "♬", "Звук": "♪", "Система": "▣", "Браузер": "◎",
    "Файлы": "▤",
}

PICKER_CSS = """
QDialog#ActionPickerDialog {
    background: #192231;
    color: #f3f5fc;
    border: 1px solid #3b4960;
}
QWidget#PickerActionArea, QScrollArea#ActionScroll,
QWidget#PickerBody {
    background: transparent;
    border: none;
}
QLabel { color: #eaf0fa; background: transparent; }
QLabel#PickerSubtitle, QLabel#ActionHint { color: #aab8cd; }
QLabel#PickerGroup { color: #aebbd0; font-size: 12px; font-weight: 700; }
QLabel#TileTitle { color: #f4f7ff; font-size: 14px; font-weight: 600; }
QLabel#TileDescription { color: #aebbcf; font-size: 12px; }
QLabel#TileIcon {
    background: #28354b; border-radius: 10px;
    color: #dbe9ff; font-size: 19px;
}
QFrame#ActionTile {
    background: transparent; border: 1px solid transparent;
    border-radius: 12px;
}
QFrame#ActionTile:hover { background: #29364c; }
QFrame#ActionTile[chosen="true"] {
    background: #2a4163; border: 1px solid #448aff;
}
QFrame#ActionTile:disabled { background: transparent; }
QLabel#TileTitle:disabled, QLabel#TileDescription:disabled {
    color: #8794a8;
}
QListWidget#ActionCategories {
    background: transparent; border: none; color: #cbd5e4;
    outline: none; font-size: 13px;
}
QListWidget#ActionCategories::item {
    border-radius: 10px; padding: 10px 8px; margin: 2px;
}
QListWidget#ActionCategories::item:selected {
    background: #344966; color: white;
}
QListWidget#ActionCategories::item:hover { background: #293850; }
QLineEdit#ActionSearch {
    background: #252e3f; color: #f3f5fb;
    border: 1px solid #3b4960;
    border-radius: 10px; padding: 10px;
}
QPushButton#PickerClose {
    background: transparent; border: none;
    font-size: 22px; color: #d9e4f8;
}
QPushButton#PickerClose:hover { background: #384760; }
QPushButton#Primary {
    background: #397af0; border: none; color: white;
    border-radius: 10px; padding: 10px 24px;
}
QPushButton#Primary:disabled { background: #354461; color: #8c9db8; }
QPushButton#PickerCancel {
    background: #303b4e; color: #f1f5fd;
    border: 1px solid #41506b; border-radius: 10px; padding: 10px 21px;
}
"""


class ActionTile(QFrame):
    """Stable-height selectable row; labels are independent, wrapped widgets."""
    clicked = Signal(str)
    activated = Signal(str)

    def __init__(self, details, parent=None):
        super().__init__(parent)
        self.action_id = details["id"]
        self.setObjectName("ActionTile")
        self.setProperty("chosen", False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumHeight(72)
        self.setToolTip(details["description"])
        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 9, 11, 9)
        outer.setSpacing(12)

        icon = QLabel(CATEGORY_ICONS.get(details["category"], "◈"))
        icon.setObjectName("TileIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(35, 35)
        outer.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)

        text = QVBoxLayout()
        text.setSpacing(3)
        title = QLabel(details["title"])
        title.setObjectName("TileTitle")
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        text.addWidget(title)
        subtitle = QLabel(details["description"])
        subtitle.setObjectName("TileDescription")
        subtitle.setWordWrap(True)
        subtitle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        text.addWidget(subtitle)
        outer.addLayout(text, 1)
        self.setEnabled(details["available"])
        self.setAccessibleName(details["title"])

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.clicked.emit(self.action_id)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.activated.emit(self.action_id)
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit(self.action_id)
            event.accept()
            return
        super().keyPressEvent(event)


class ActionOptionsDialog(QDialog):
    def __init__(self, action, step=None, parent=None):
        super().__init__(parent)
        self.action = action
        self.current_step = dict(step or {})
        self.data = None
        details = CATALOG[action]
        self.setWindowTitle("Настроить действие")
        self.setMinimumWidth(500)
        self.resize(550, 320)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(23, 20, 23, 20)
        layout.setSpacing(14)

        heading = QLabel(details["title"])
        heading.setStyleSheet("font-size:18px; font-weight:700;")
        layout.addWidget(heading)
        subtitle = QLabel(details["description"])
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        form = QFormLayout()
        form.setVerticalSpacing(12)
        self.target = None
        self.location = None
        self.app_choice = None
        self.percent = None
        self.browse = None

        if action == "open_app":
            self.target = QComboBox()
            for app in APP_TARGETS:
                self.target.addItem(APP_LABELS.get(app, app), app)
            self._choose(self.target, self.current_step.get("target"))
            form.addRow("Приложение", self.target)
        elif action == "launch_game":
            self.target = QComboBox()
            for identifier, (_, title) in GAMES.items():
                self.target.addItem(title, identifier)
            self._choose(self.target, self.current_step.get("target"))
            form.addRow("Игра Steam", self.target)
        elif action == "hotkey":
            self.target = QComboBox()
            for shortcut in HOTKEYS:
                self.target.addItem(shortcut.upper(), shortcut)
            self._choose(self.target, self.current_step.get("target"))
            form.addRow("Сочетание", self.target)
        elif action == "app_volume":
            self.app_choice = QComboBox()
            for app in APP_TARGETS:
                self.app_choice.addItem(APP_LABELS.get(app, app), app)
            value = str(self.current_step.get("target", ""))
            app, _, percent = value.partition(":")
            self._choose(self.app_choice, app)
            form.addRow("Приложение", self.app_choice)
            self.percent = QSpinBox()
            self.percent.setRange(0, 100)
            self.percent.setSuffix(" %")
            self.percent.setValue(int(percent) if percent.isdigit() else 80)
            form.addRow("Громкость", self.percent)
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
        elif action in {
            "open_website", "search_web", "open_first_result", "type_text",
            "speak_text", "voice_female", "voice_male", "run_cmd", "run_powershell",
        }:
            self.target = QLineEdit(str(self.current_step.get("target", "")))
            prompts = {
                "open_website": "https://example.com",
                "search_web": "Что найти в интернете",
                "open_first_result": "Что искать и открыть",
                "type_text": "Текст для активного окна",
                "speak_text": "Текст для Jarvis",
                "voice_female": "Текст женским голосом",
                "voice_male": "Текст мужским голосом",
                "run_cmd": "Команда CMD — вводить только вручную",
                "run_powershell": "PowerShell — вводить только вручную",
            }
            self.target.setPlaceholderText(prompts[action])
            self.target.setMaxLength(500)
            form.addRow("Значение", self.target)
        elif action in {"play_mp3", "play_wav", "run_file"}:
            self.target = QLineEdit(str(self.current_step.get("target", "")))
            self.target.setReadOnly(True)
            self.target.setPlaceholderText("Выберите файл или программу…")
            row = QHBoxLayout()
            row.addWidget(self.target, 1)
            self.browse = QPushButton("Обзор…")
            self.browse.clicked.connect(self._browse_audio)
            row.addWidget(self.browse)
            form.addRow("Аудиофайл", row)
        elif action in {
            "wait_seconds", "wait_minutes", "mouse_scroll", "mouse_hold",
            "mouse_right_hold",
        }:
            self.target = QSpinBox()
            bounds = {
                "wait_seconds": (1, 30, 2),
                "wait_minutes": (1, 10, 1),
                "mouse_scroll": (-10, 10, 3),
                "mouse_hold": (1, 5, 2),
                "mouse_right_hold": (1, 5, 2),
            }
            mn, mx, default = bounds[action]
            self.target.setRange(mn, mx)
            self.target.setValue(int(self.current_step.get("target") or default))
            self.target.setSuffix(
                " мин" if action == "wait_minutes" else (
                    " шага" if action == "mouse_scroll" else " сек"
                )
            )
            form.addRow("Значение", self.target)
        elif action == "mouse_move":
            self.target = QLineEdit(str(self.current_step.get("target", "")))
            self.target.setPlaceholderText("Например: 600,350")
            form.addRow("Координаты X,Y", self.target)
        else:
            form.addRow("", QLabel("Действие не требует параметров."))
        layout.addLayout(form)

        if action in {"run_cmd", "run_powershell", "sleep_pc", "monitor_off"}:
            warning = QLabel(
                "Внимание! Это действие может изменить работу Windows. "
                "Jarvis покажет содержимое и всегда спросит разрешение "
                "перед выполнением. ИИ не сможет вставлять команды CMD сюда."
            )
            warning.setWordWrap(True)
            warning.setStyleSheet("color:#f5c16b; font-weight:600;")
            layout.addWidget(warning)

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

    def _browse_audio(self):
        ext = "MP3 (*.mp3)" if self.action == "play_mp3" else "WAV (*.wav)"
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите аудиофайл", "", ext,
        )
        if path:
            self.target.setText(path)

    @staticmethod
    def _choose(combo, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _accept(self):
        target = ""
        if isinstance(self.target, QComboBox):
            target = self.target.currentData()
        elif isinstance(self.target, QLineEdit):
            target = self.target.text().strip()
        elif isinstance(self.target, QSpinBox):
            target = str(self.target.value())
        if self.action == "app_volume":
            target = f"{self.app_choice.currentData()}:{self.percent.value()}"
        try:
            self.data = validate_step({
                "action": self.action, "target": target,
                "location": self.location.currentData() if self.location else "desktop",
            })
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(self, "Некорректное действие", str(exc))
            return
        self.accept()


class ActionPicker(QDialog):
    """Responsive category/search picker with separate two-line action cards."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ActionPickerDialog")
        # Hide the native Windows titlebar (which can use a bright accent color).
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("Добавить действие")
        self.setMinimumSize(730, 530)
        self.resize(820, 610)
        self.step = None
        self.action = None
        self._selected = None
        self._buttons = {}
        self._drag_position = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(13)
        header = QHBoxLayout()
        icon = QLabel("＋")
        icon.setFixedSize(46, 46)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            "background:#293e61;color:white;font-size:23px;"
            "border-radius:11px;"
        )
        header.addWidget(icon)
        heading = QVBoxLayout()
        heading.setSpacing(3)
        title = QLabel("Добавить действие")
        title.setStyleSheet("font-size:20px;font-weight:700;")
        heading.addWidget(title)
        sub = QLabel("Что сделает команда. Двойной щелчок — добавить сразу.")
        sub.setObjectName("PickerSubtitle")
        sub.setWordWrap(True)
        heading.addWidget(sub)
        header.addLayout(heading, 1)
        close = QPushButton("×")
        close.setFixedSize(34, 34)
        close.setObjectName("PickerClose")
        close.clicked.connect(self.reject)
        header.addWidget(close)
        root.addLayout(header)

        self.search = QLineEdit()
        self.search.setObjectName("ActionSearch")
        self.search.setPlaceholderText(
            "⌕   Поиск: «открыть», «клавиши», «громкость»…"
        )
        self.search.textChanged.connect(self._refresh_items)
        root.addWidget(self.search)

        body = QHBoxLayout()
        body.setSpacing(11)
        self.category_list = QListWidget()
        self.category_list.setObjectName("ActionCategories")
        self.category_list.setFixedWidth(190)
        self.category_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        for name, icon_name in CATEGORIES:
            entry = QListWidgetItem(f"{icon_name}   {name}")
            entry.setData(Qt.ItemDataRole.UserRole, name)
            entry.setSizeHint(QSize(170, 43))
            self.category_list.addItem(entry)
        self.category_list.currentRowChanged.connect(self._refresh_items)
        body.addWidget(self.category_list)

        self.action_scroll = QScrollArea()
        self.action_scroll.setObjectName("ActionScroll")
        self.action_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.action_scroll.setWidgetResizable(True)
        self.action_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.action_area = QWidget()
        self.action_area.setObjectName("PickerActionArea")
        self.action_layout = QVBoxLayout(self.action_area)
        self.action_layout.setContentsMargins(4, 3, 8, 5)
        self.action_layout.setSpacing(6)
        self.action_scroll.setWidget(self.action_area)
        body.addWidget(self.action_scroll, 1)
        root.addLayout(body, 1)

        footer = QHBoxLayout()
        empty = QPushButton("＋  Пустое действие")
        empty.clicked.connect(self._add_empty)
        footer.addWidget(empty)
        footer.addStretch()
        cancel = QPushButton("Отмена")
        cancel.setObjectName("PickerCancel")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        self.add_button = QPushButton("Добавить")
        self.add_button.setObjectName("Primary")
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self._add_selected)
        footer.addWidget(self.add_button)
        root.addLayout(footer)
        self.setStyleSheet(PICKER_CSS)
        self.category_list.setCurrentRow(0)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 85:
            self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_position is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_position)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_position = None
        super().mouseReleaseEvent(event)

    def _refresh_items(self, *_):
        while self.action_layout.count():
            item = self.action_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._buttons.clear()
        self._selected = None
        self.add_button.setEnabled(False)
        current = self.category_list.currentItem()
        chosen = (
            current.data(Qt.ItemDataRole.UserRole)
            if current is not None else "Все действия"
        )
        query = self.search.text().strip().casefold()
        matches = {}
        for details in CATALOG.values():
            if chosen != "Все действия" and details["category"] != chosen:
                continue
            searchable = (
                details["title"] + " " + details["description"] + " "
                + details["category"]
            ).casefold()
            if query and query not in searchable:
                continue
            matches.setdefault(details["category"], []).append(details)

        for group, actions in matches.items():
            heading = QLabel(group)
            heading.setObjectName("PickerGroup")
            heading.setContentsMargins(4, 8, 0, 2)
            self.action_layout.addWidget(heading)
            for details in actions:
                tile = ActionTile(details, self.action_area)
                tile.clicked.connect(self._choose_action)
                tile.activated.connect(self._activate_action)
                self.action_layout.addWidget(tile)
                self._buttons[details["id"]] = tile

        if not matches:
            note = QLabel("Действия не найдены. Попробуйте другой запрос.")
            note.setObjectName("PickerSubtitle")
            note.setWordWrap(True)
            self.action_layout.addWidget(note)
        self.action_layout.addStretch(1)
        self.action_scroll.verticalScrollBar().setValue(0)

    def _activate_action(self, action):
        self._choose_action(action)
        self._add_selected()

    def _choose_action(self, action):
        if action not in self._buttons or not CATALOG[action]["available"]:
            return
        self._selected = action
        for key, tile in self._buttons.items():
            tile.setProperty("chosen", key == action)
            tile.style().unpolish(tile)
            tile.style().polish(tile)
        self.add_button.setEnabled(True)

    def _add_empty(self):
        self.step = validate_step({"action": "noop"})
        self.accept()

    def _add_selected(self):
        if not self._selected:
            return
        editor = ActionOptionsDialog(self._selected, parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted and editor.data is not None:
            self.step = editor.data
            self.accept()
