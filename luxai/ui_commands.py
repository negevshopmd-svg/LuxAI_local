"""Luxify-inspired command library/editor for Jarvis.

Every saved command is a named allowed action, not a user-defined shell line.
The page exposes built-in defaults plus persistent user-created/learned phrases.
"""
from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QHeaderView, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from luxai.command_registry import APP_TARGETS, CommandRegistry
from luxai.file_actions import ALLOWED_LOCATIONS
from luxai.steam_games import GAMES
from luxai.ui_i18n import tr, get_ui_language, translate_widgets
from luxai.icons import icon, set_button_icon, set_item_icon
from luxai.action_catalog import CATALOG


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
    run_entry_requested = Signal(object)
    ai_requested = Signal(str, object)
    voice_create_requested = Signal()
    changed = Signal()

    def __init__(self, registry: CommandRegistry, parent=None):
        super().__init__(parent)
        self.registry = registry
        self._planner = None
        self._config = {}
        self.interface_language = get_ui_language()
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
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(False)
        self.tree.setIndentation(18)
        self.tree.setIconSize(QSize(18, 18))
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
        search_icon = self.search.addAction(icon("search", size=17), QLineEdit.ActionPosition.LeadingPosition)
        search_icon.setProperty("jarvisIcon", "search")
        search_icon.setProperty("jarvisIconRole", "muted")
        self.search.textChanged.connect(self._filter)
        side_col.addWidget(self.search)
        create_label = QLabel("Создать")
        create_label.setObjectName("Muted")
        side_col.addWidget(create_label)
        add = QPushButton("Новая команда")
        add.setObjectName("Primary")
        set_button_icon(add, "plus", role="white")
        add.clicked.connect(self.new_command)
        side_col.addWidget(add)
        add_voice = QPushButton("Создать голосом")
        set_button_icon(add_voice, "mic")
        add_voice.setToolTip("Jarvis спросит фразу и действие, затем сохранит команду.")
        add_voice.clicked.connect(lambda _checked=False: self.voice_create_requested.emit())
        side_col.addWidget(add_voice)
        tools_label = QLabel("Управление")
        tools_label.setObjectName("Muted")
        side_col.addWidget(tools_label)
        self.edit = QPushButton("Изменить выбранную")
        set_button_icon(self.edit, "pencil")
        self.edit.clicked.connect(self.edit_selected)
        side_col.addWidget(self.edit)
        self.toggle = QPushButton("Выключить команду")
        set_button_icon(self.toggle, "power")
        self.toggle.clicked.connect(self.toggle_selected)
        side_col.addWidget(self.toggle)
        self.remove = QPushButton("Удалить выбранную")
        set_button_icon(self.remove, "trash-2", role="danger")
        self.remove.clicked.connect(self.delete_selected)
        self.run_button = QPushButton("Выполнить сейчас")
        set_button_icon(self.run_button, "play", role="accent")
        self.run_button.clicked.connect(self.execute_selected)
        side_col.addWidget(self.run_button)
        side_col.addWidget(self.remove)
        side_col.addStretch()
        self.summary = QLabel("")
        self.summary.setObjectName("Muted")
        self.summary.setWordWrap(True)
        side_col.addWidget(self.summary)
        root.addWidget(side, 2)
        self.refresh()
        translate_widgets(self, self.interface_language)

    def refresh(self):
        self.tree.clear()
        records = self.registry.entries()
        categories = defaultdict(list)
        for entry in records:
            categories[(entry["category"], entry["builtin"])].append(entry)
        order = ["Приложения", "Windows", "Игры Steam", "Файлы",
                 "Мои команды", "Выученные команды"]
        builtins = [item for item in records if item["builtin"]]
        defaults_root = QTreeWidgetItem([tr("Команды по умолчанию", self.interface_language), ""])
        defaults_root.setFlags(defaults_root.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        set_item_icon(defaults_root, "folder", widget=self.tree, column=0, role="accent")
        self.tree.addTopLevelItem(defaults_root)
        category_names = order + sorted({name for name, _ in categories} - set(order))
        for category, builtin_group in ((name, flag) for flag in (True, False) for name in category_names):
            items = categories.get((category, builtin_group), [])
            if not items:
                continue
            is_default = items[0]["builtin"]
            header = QTreeWidgetItem([f"{tr(category, self.interface_language)}  ({len(items)})", ""])
            set_item_icon(header, {
                "Приложения": "app-window", "Windows": "monitor",
                "Игры Steam": "gamepad-2", "Файлы": "folder",
                "Мои команды": "list-checks", "Выученные команды": "sparkles",
            }.get(category, "folder"), widget=self.tree, column=0, role="muted")
            header.setFlags(header.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            if is_default:
                defaults_root.addChild(header)
            else:
                self.tree.addTopLevelItem(header)
            for entry in items:
                item = QTreeWidgetItem([
                    tr(entry["title"], self.interface_language) if entry["builtin"] else entry["title"], "",
                ])
                action_icon = CATALOG.get(entry["action"], {}).get("icon", "list-checks")
                set_item_icon(item, action_icon, widget=self.tree, column=0)
                state_text = {
                    "ru": ("Включена", "Выключена"), "en": ("Enabled", "Disabled"),
                    "ro": ("Activată", "Dezactivată"),
                }[self.interface_language][0 if entry["enabled"] else 1]
                set_item_icon(item, "circle-check" if entry["enabled"] else "circle-minus",
                              widget=self.tree, column=1,
                              role="success" if entry["enabled"] else "muted")
                item.setData(1, Qt.ItemDataRole.AccessibleTextRole, state_text)
                item.setToolTip(1, state_text)
                item.setData(0, Qt.ItemDataRole.UserRole, entry["id"])
                item.setToolTip(0, ", ".join(entry["phrases"]))
                header.addChild(item)
            header.setExpanded(not is_default)
        defaults_root.setText(0, f"{tr('Команды по умолчанию', self.interface_language)}  ({len(builtins)})")
        defaults_root.setExpanded(False)
        custom_count = len(self.registry.custom)
        summary_labels = {
            "ru": ("Готовые команды", "Мои/выученные"),
            "en": ("Built-in commands", "Custom/learned"),
            "ro": ("Comenzi predefinite", "Personale/învățate"),
        }
        built_in, custom = summary_labels.get(self.interface_language, summary_labels["ru"])
        self.summary.setText(
            f"{built_in}: {len(builtins)}\\n"
            f"{custom}: {custom_count}\\n"
            + tr("Изменения сохраняются между обновлениями.", self.interface_language)
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
            tr("Включить команду" if entry and not entry["enabled"] else "Выключить команду", self.interface_language)
        )

    def _filter(self, keyword):
        keyword = keyword.strip().casefold()
        for index in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(index)
            if root.childCount() and root.child(0).childCount():
                groups = [root.child(n) for n in range(root.childCount())]
            else:
                groups = [root]
            count = 0
            for group in groups:
                matches = 0
                for child_idx in range(group.childCount()):
                    item = group.child(child_idx)
                    shown = not keyword or keyword in item.text(0).casefold() or keyword in item.toolTip(0).casefold()
                    item.setHidden(not shown)
                    matches += int(shown)
                group.setHidden(matches == 0)
                count += matches
                if keyword and matches:
                    group.setExpanded(True)
            root.setHidden(count == 0)
            if keyword and count:
                root.setExpanded(True)

    def set_context(self, planner=None, config=None):
        self._planner = planner
        if config is not None:
            self._config = config

    def _configure_editor(self, dialog):
        dialog.set_context(self._planner, self._config)
        dialog.run_requested.connect(self.run_entry_requested.emit)
        dialog.ai_requested.connect(self.ai_requested.emit)
        return dialog

    def new_command(self):
        dialog = self._configure_editor(CommandEditor(parent=self))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.registry.save_custom(dialog.get_data())
                self.refresh()
                self.changed.emit()
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, tr("Ошибка", self.interface_language), str(exc))

    def edit_selected(self):
        selected = self._selected()
        if not selected or selected["builtin"]:
            return
        dialog = self._configure_editor(CommandEditor(selected, parent=self))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.registry.save_custom(dialog.get_data())
                self.refresh()
                self.changed.emit()
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, tr("Ошибка", self.interface_language), str(exc))

    def toggle_selected(self):
        entry = self._selected()
        if entry:
            try:
                self.registry.set_enabled(entry["id"], not entry["enabled"])
                self.refresh()
                self.changed.emit()
            except (ValueError, OSError) as exc:
                QMessageBox.warning(self, tr("Ошибка", self.interface_language), str(exc))

    def delete_selected(self):
        entry = self._selected()
        if not entry or entry["builtin"]:
            return
        answer = QMessageBox.question(
            self, tr("Удалить команду?", self.interface_language),
            tr("Удалить команду «{title}»?", self.interface_language).format(title=entry["title"]),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            try:
                self.registry.remove_custom(entry["id"])
                self.refresh()
                self.changed.emit()
            except (ValueError, OSError) as exc:
                QMessageBox.warning(self, tr("Ошибка", self.interface_language), str(exc))

    def execute_selected(self):
        entry = self._selected()
        if entry is not None and entry["enabled"]:
            self.run_requested.emit(dict(entry))
