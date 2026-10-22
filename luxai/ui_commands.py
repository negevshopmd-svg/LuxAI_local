"""Luxify-inspired command library/editor for Jarvis.

Every saved command is a named allowed action, not a user-defined shell line.
The page exposes built-in defaults plus persistent user-created/learned phrases.
"""
from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from luxai.command_registry import APP_TARGETS, CommandRegistry
from luxai.file_actions import ALLOWED_LOCATIONS
from luxai.steam_games import GAMES


ACTION_CHOICES = [
    ("Открыть приложение", "open_app"),
    ("Запустить игру Steam", "launch_game"),
    ("Создать файл", "create_file"),
    ("Создать папку", "create_folder"),
    ("Показать список файлов", "list_files"),
    ("Сказать текущее время", "time"),
    ("Свернуть все окна", "minimize_windows"),
]

LOCATION_CHOICES = [
    ("Рабочий стол", "desktop"),
    ("Документы", "documents"),
    ("Загрузки", "downloads"),
]

APP_NAMES = {
    "telegram": "Telegram", "discord": "Discord", "steam": "Steam",
    "chrome": "Google Chrome", "firefox": "Firefox", "edge": "Microsoft Edge",
    "spotify": "Spotify", "notepad": "Блокнот",
    "calculator": "Калькулятор", "explorer": "Проводник",
}


from luxai.ui_command_editor import CommandEditor


class CommandsPage(QWidget):
    run_requested = Signal(object)
    voice_create_requested = Signal()
    changed = Signal()

    def __init__(self, registry: CommandRegistry, parent=None):
        super().__init__(parent)
        self.registry = registry
        self.setObjectName("CommandsPage")

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 2, 0, 0)
        root.setSpacing(16)
        left = QFrame()
        left.setObjectName("SettingsCard")
        left_col = QVBoxLayout(left)
        left_col.setContentsMargins(18, 16, 18, 16)
        heading = QLabel("Ваши команды")
        heading.setObjectName("PageTitle")
        left_col.addWidget(heading)
        hint = QLabel(
            "Готовые команды выполняются мгновенно. "
            "Двойной щелчок запускает выбранную команду."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        left_col.addWidget(hint)
        self.tree = QTreeWidget()
        self.tree.setObjectName("CommandTree")
        self.tree.setHeaderLabels(["Название команды", "Состояние"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(False)
        self.tree.setIndentation(18)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(lambda *_: self.execute_selected())
        left_col.addWidget(self.tree, 1)
        root.addWidget(left, 5)

        side = QFrame()
        side.setObjectName("SettingsSidebar")
        side.setMinimumWidth(215)
        side.setMaximumWidth(245)
        side_col = QVBoxLayout(side)
        side_col.setContentsMargins(12, 14, 12, 14)
        side_col.setSpacing(9)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск команд")
        self.search.textChanged.connect(self._filter)
        side_col.addWidget(self.search)
        add = QPushButton("＋  Новая команда")
        add.setObjectName("Primary")
        add.clicked.connect(self.new_command)
        side_col.addWidget(add)
        add_voice = QPushButton("🎙  Создать голосом")
        add_voice.setToolTip("Jarvis спросит фразу и действие, затем сохранит команду.")
        add_voice.clicked.connect(lambda _checked=False: self.voice_create_requested.emit())
        side_col.addWidget(add_voice)
        self.edit = QPushButton("Изменить выбранную")
        self.edit.clicked.connect(self.edit_selected)
        side_col.addWidget(self.edit)
        self.toggle = QPushButton("Выключить команду")
        self.toggle.clicked.connect(self.toggle_selected)
        side_col.addWidget(self.toggle)
        self.remove = QPushButton("Удалить выбранную")
        self.remove.clicked.connect(self.delete_selected)
        side_col.addWidget(self.remove)
        self.run_button = QPushButton("▶  Выполнить сейчас")
        self.run_button.clicked.connect(self.execute_selected)
        side_col.addWidget(self.run_button)
        side_col.addStretch()
        self.summary = QLabel("")
        self.summary.setObjectName("Muted")
        self.summary.setWordWrap(True)
        side_col.addWidget(self.summary)
        root.addWidget(side, 2)
        self.refresh()

    def refresh(self):
        self.tree.clear()
        categories = defaultdict(list)
        records = self.registry.entries()
        for entry in records:
            categories[entry["category"]].append(entry)
        ordering = [
            "Приложения", "Windows", "Игры Steam", "Файлы",
            "Мои команды", "Выученные команды",
        ]
        for category in ordering + sorted(set(categories) - set(ordering)):
            group_items = categories.get(category)
            if not group_items:
                continue
            header = QTreeWidgetItem([f"{category}  ({len(group_items)})", ""])
            header.setFlags(header.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tree.addTopLevelItem(header)
            for entry in group_items:
                item = QTreeWidgetItem([
                    entry["title"], "●" if entry["enabled"] else "○",
                ])
                item.setData(0, Qt.ItemDataRole.UserRole, entry["id"])
                item.setToolTip(0, ", ".join(entry["phrases"]))
                header.addChild(item)
            header.setExpanded(True)
        custom_count = len(self.registry.custom)
        self.summary.setText(
            f"Готовые команды: {len(records) - custom_count}\n"
            f"Мои/выученные: {custom_count}\n"
            "Изменения сохраняются между обновлениями."
        )
        self._filter(self.search.text())
        self._selection_changed()

    def _selected(self):
        current = self.tree.currentItem()
        if current is None:
            return None
        cmd_id = current.data(0, Qt.ItemDataRole.UserRole)
        return next((cmd for cmd in self.registry.entries() if cmd["id"] == cmd_id), None)

    def _selection_changed(self):
        entry = self._selected()
        is_custom = entry is not None and not entry["builtin"]
        self.edit.setEnabled(is_custom)
        self.remove.setEnabled(is_custom)
        self.toggle.setEnabled(entry is not None)
        self.run_button.setEnabled(bool(entry and entry["enabled"]))
        self.toggle.setText(
            "Включить команду" if entry and not entry["enabled"] else "Выключить команду"
        )

    def _filter(self, keyword):
        keyword = keyword.strip().casefold()
        for index in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(index)
            visible = 0
            for child_idx in range(group.childCount()):
                item = group.child(child_idx)
                label = item.text(0).casefold()
                phrases = item.toolTip(0).casefold()
                show = not keyword or keyword in label or keyword in phrases
                item.setHidden(not show)
                visible += int(show)
            group.setHidden(visible == 0)

    def new_command(self):
        dialog = CommandEditor(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.registry.save_custom(dialog.get_data())
                self.refresh()
                self.changed.emit()
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Ошибка", str(exc))

    def edit_selected(self):
        selected = self._selected()
        if not selected or selected["builtin"]:
            return
        dialog = CommandEditor(selected, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.registry.save_custom(dialog.get_data())
                self.refresh()
                self.changed.emit()
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Ошибка", str(exc))

    def toggle_selected(self):
        entry = self._selected()
        if entry:
            try:
                self.registry.set_enabled(entry["id"], not entry["enabled"])
                self.refresh()
                self.changed.emit()
            except (ValueError, OSError) as exc:
                QMessageBox.warning(self, "Ошибка", str(exc))

    def delete_selected(self):
        entry = self._selected()
        if not entry or entry["builtin"]:
            return
        answer = QMessageBox.question(
            self, "Удалить команду?",
            f"Удалить команду «{entry['title']}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            try:
                self.registry.remove_custom(entry["id"])
                self.refresh()
                self.changed.emit()
            except (ValueError, OSError) as exc:
                QMessageBox.warning(self, "Ошибка", str(exc))

    def execute_selected(self):
        entry = self._selected()
        if entry is not None and entry["enabled"]:
            self.run_requested.emit(dict(entry))
