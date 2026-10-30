"""Local command library with Luxify-style folder tree and contextual actions.

Default edits and deletions are stored separately from the shipped presets.
Imports are validated and never executed.
"""
from __future__ import annotations

import json
import tempfile
import uuid
from collections import defaultdict
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QIcon
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QToolButton,
    QTreeWidgetItem, QVBoxLayout, QWidget,
    QHeaderView, QApplication,
)
from luxai.command_registry import CommandRegistry, checked_command
from luxai.ui_i18n import tr, get_ui_language, translate_widgets
from luxai.icons import icon, refresh_icons, set_button_icon, set_item_icon
from luxai.action_catalog import CATALOG
from luxai.ui_command_editor import CommandEditor
from luxai.ui_command_menu import CommandContextMenu
from luxai.command_transfer import export_payload, import_payload, is_agent_command
from luxai.ui_command_tree import CommandTreeWidget


GROUP_ROLE = int(Qt.ItemDataRole.UserRole) + 1
_ERROR_SOURCES = {
    "Command was deleted": "Команда была удалена.",
    "Unknown command": "Команда не найдена.",
    "Unknown group": "Папка не найдена.",
    "Group already exists": "Папка с таким названием уже существует.",
    "Invalid command list": "Некорректный список команд.",
    "Unsupported command export format or version": "Формат или версия файла команд не поддерживается.",
    "Invalid command export format": "Некорректный файл команд.",
    "Invalid command entry": "Некорректная команда в файле.",
    "Invalid group list": "Некорректные данные папок или коллекций.",
    "Invalid group": "Некорректные данные папок или коллекций.",
    "Duplicate group name": "Некорректные данные папок или коллекций.",
    "Invalid group selection": "Некорректные данные папок или коллекций.",
    "Invalid command scope": "Некорректная вкладка команд.",
    "Invalid group name": "Некорректное название папки.",
    "Command file exceeds the safe 4 MB import limit": "Файл команд превышает ограничение 4 МБ.",
    "Too many custom commands": "Слишком много пользовательских команд.",
}


class LibraryHoverButton(QToolButton):
    """Keep inactive index widgets blank even during a global icon refresh."""

    def setIcon(self, value):
        if self.property("libraryRevealed") is False:
            value = QIcon()
        super().setIcon(value)


class CommandsPage(QWidget):
    run_requested = Signal(object)
    run_entry_requested = Signal(object)
    ai_requested = Signal(str, object)
    voice_create_requested = Signal()
    changed = Signal()
    chat_requested = Signal()

    def __init__(self, registry: CommandRegistry, parent=None):
        super().__init__(parent)
        self.registry = registry
        self.interface_language = get_ui_language()
        self._planner = None
        self._config = {}
        self._last_hover = None
        self._menu_widgets = {}
        self._edit_widgets = {}
        self._agent_mode = False
        self._tree_mode = False
        self._view_states = {}
        self.setObjectName("CommandsPage")
        self.setStyleSheet("""
            QFrame#LibraryCard {background: #191c21; border: 1px solid #323943; border-radius: 15px;}
            QFrame#LibrarySidebar {background: #1b1e24; border: 1px solid #323943; border-radius: 15px;}
            QWidget#AgentCommandsEmpty, QWidget#AgentCommandsEmpty QLabel {background: transparent; border: none;}
            QLabel#LibraryTitle {font-size: 18px; font-weight: 700; color: #f4f6fa;}
            QLabel#LibraryMuted {font-size: 12px; color: #a4aebd;}
            QLabel#LibraryGroup {font-size: 12px; font-weight: 600; color: #b7bfcb;}
            QPushButton#LibraryPrimary {background: #397ef6; color: white; border: 0;
                                        border-radius: 10px; padding: 11px; font-weight: 600;}
            QPushButton#LibraryAction {background: #292f39; color: #e8edf5;
                                       border: 1px solid #3a4352; border-radius: 10px; padding: 9px;}
            QPushButton#LibraryTab {border-radius: 9px; padding: 10px; background: #272b33; color: #cbd1dc;}
            QPushButton#LibraryTab:checked {background: #397ef6; color: white;}
            QLineEdit#LibrarySearch {background: #242932; border: 1px solid #3b424e;
                                    border-radius: 10px; padding: 9px; color: #f8fafc;}
            QTreeWidget#CommandTree {background: transparent; border: none;
                                     outline: none; color: #edf2f8; font-size: 13px;}
            QTreeWidget#CommandTree::item {height: 36px; border-radius: 0; padding: 3px;}
            QTreeWidget#CommandTree::item:hover {background: #2b3443;}
            QTreeWidget#CommandTree::item:selected {background: #2f425e; color: #edf2f8;}
            QHeaderView::section {background: transparent; color: #a9b2c2;
                                  border: none; padding: 4px;}
            QToolButton#LibraryMore {background: transparent; border: 0;
                                     padding: 2px; color: #c9d6e8; font-size: 19px;}
        """)
        self._library_base_style = self.styleSheet()

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        center = QWidget()
        center_col = QVBoxLayout(center)
        center_col.setContentsMargins(0, 0, 0, 0)
        center_col.setSpacing(12)
        tabs = QHBoxLayout()
        tabs.setSpacing(8)
        self.my_tab = QPushButton(tr("Мои команды", self.interface_language))
        self.my_tab.setObjectName("LibraryTab")
        self.my_tab.setCheckable(True)
        self.my_tab.setChecked(True)
        set_button_icon(self.my_tab, "list-checks")
        self.my_tab.clicked.connect(lambda: self.set_agent_mode(False))
        tabs.addWidget(self.my_tab)
        self.agent_tab = QPushButton(tr("Команды агента", self.interface_language))
        self.agent_tab.setObjectName("LibraryTab")
        self.agent_tab.setCheckable(True)
        set_button_icon(self.agent_tab, "bot")
        self.agent_tab.clicked.connect(lambda: self.set_agent_mode(True))
        self.library_tabs = QButtonGroup(self)
        self.library_tabs.setExclusive(True)
        self.library_tabs.addButton(self.my_tab)
        self.library_tabs.addButton(self.agent_tab)
        tabs.addWidget(self.agent_tab)
        tabs.addStretch()
        center_col.addLayout(tabs)

        card = QFrame()
        card.setObjectName("LibraryCard")
        area = QVBoxLayout(card)
        area.setContentsMargins(17, 16, 15, 12)
        area.setSpacing(5)
        row = QHBoxLayout()
        heading = QLabel(tr("Ваши команды", self.interface_language))
        heading.setObjectName("LibraryTitle")
        self.library_heading = heading
        row.addWidget(heading)
        row.addStretch()
        self.expand_all = QPushButton("⌄")
        self.expand_all.setText("")
        set_button_icon(self.expand_all, "chevron-down", size=15)
        self.expand_all.setToolTip(tr("Развернуть все", self.interface_language))
        self.expand_all.setFixedSize(27, 27)
        self.expand_all.clicked.connect(self.tree_expand_all)
        row.addWidget(self.expand_all)
        self.collapse_all = QPushButton("⌃")
        self.collapse_all.setText("")
        set_button_icon(self.collapse_all, "chevron-up", size=15)
        self.collapse_all.setFixedSize(27, 27)
        self.collapse_all.setToolTip(tr("Свернуть все", self.interface_language))
        self.collapse_all.clicked.connect(self.tree_collapse_all)
        row.addWidget(self.collapse_all)
        area.addLayout(row)
        subtitle = QLabel(tr("Двойной щелчок по команде — открыть её.", self.interface_language))
        subtitle.setObjectName("LibraryMuted")
        subtitle.setWordWrap(True)
        self.library_subtitle = subtitle
        area.addWidget(subtitle)

        self.tree = CommandTreeWidget()
        self.tree.setObjectName("CommandTree")
        self.tree.setColumnCount(5)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(21)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setIconSize(QSize(20, 20))
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        # Long voice phrases must not steal the title and action controls' width.
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(1, 154)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.tree.header().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(2, 28)
        self.tree.setColumnWidth(3, 28)
        self.tree.setColumnWidth(4, 30)
        self.tree.viewport().setMouseTracking(True)
        self.tree.viewport().installEventFilter(self)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.itemClicked.connect(self._item_clicked)
        self.tree.itemDoubleClicked.connect(self.open_selected)
        area.addWidget(self.tree, 1)
        self.agent_empty = QWidget()
        self.agent_empty.setObjectName("AgentCommandsEmpty")
        empty = QVBoxLayout(self.agent_empty)
        empty.setContentsMargins(20, 30, 20, 30)
        empty.addStretch()
        self.agent_empty_icon = QLabel()
        self.agent_empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.addWidget(self.agent_empty_icon)
        self.agent_empty_title = QLabel()
        self.agent_empty_title.setObjectName("LibraryTitle")
        self.agent_empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.addWidget(self.agent_empty_title)
        self.agent_empty_description = QLabel()
        self.agent_empty_description.setObjectName("LibraryMuted")
        self.agent_empty_description.setWordWrap(True)
        self.agent_empty_description.setMaximumWidth(440)
        self.agent_empty_description.setMinimumHeight(80)
        self.agent_empty_description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.addWidget(self.agent_empty_description, 0, Qt.AlignmentFlag.AlignHCenter)
        self.open_chat_button = QPushButton(tr("Открыть Jarvis AI", self.interface_language))
        self.open_chat_button.setObjectName("LibraryAction")
        set_button_icon(self.open_chat_button, "bot")
        self.open_chat_button.clicked.connect(self.chat_requested.emit)
        empty.addSpacing(10)
        empty.addWidget(self.open_chat_button, 0, Qt.AlignmentFlag.AlignHCenter)
        empty.addStretch()
        self.agent_empty.hide()
        area.addWidget(self.agent_empty, 1)
        center_col.addWidget(card, 1)
        root.addWidget(center, 1)

        side = QFrame()
        side.setObjectName("LibrarySidebar")
        side.setFixedWidth(210)
        side_col = QVBoxLayout(side)
        side_col.setContentsMargins(11, 14, 11, 12)
        side_col.setSpacing(8)
        self.search = QLineEdit()
        self.search.setObjectName("LibrarySearch")
        self.search.setPlaceholderText(tr("Поиск команд", self.interface_language))
        search_icon = self.search.addAction(icon("search", size=17),
                                            QLineEdit.ActionPosition.LeadingPosition)
        search_icon.setProperty("jarvisIcon", "search")
        self.search.textChanged.connect(self._filter)
        side_col.addWidget(self.search)

        def caption(value):
            label = QLabel(tr(value, self.interface_language))
            label.setObjectName("LibraryGroup")
            return label

        def action(text, name, callback, primary=False):
            button = QPushButton(tr(text, self.interface_language))
            button.setObjectName("LibraryPrimary" if primary else "LibraryAction")
            set_button_icon(button, name, role="white" if primary else "muted")
            button.clicked.connect(callback)
            side_col.addWidget(button)
            return button

        side_col.addWidget(caption("Создать"))
        self.create_button = action("Новая команда", "plus", self.new_command, primary=True)
        self.folder_button = action("Новая папка", "folder-plus",
                                    lambda: self.create_group("folders"))
        self.collection_button = action("Новая коллекция", "folder",
                                        lambda: self.create_group("collections"))
        side_col.addSpacing(8)
        side_col.addWidget(caption("Файл"))
        self.import_button = action("Импорт из файла", "folder-open", self.import_commands)
        self.export_button = action("Экспорт в файл", "file-down", self.export_commands)
        side_col.addStretch()

        self.summary = QLabel()
        self.summary.setObjectName("LibraryMuted")
        self.summary.setWordWrap(True)
        side_col.addWidget(self.summary)
        self.save_info = QPushButton(tr("Сохранено автоматически", self.interface_language))
        self.save_info.setObjectName("LibraryAction")
        self.save_info.setEnabled(False)
        side_col.addWidget(self.save_info)
        root.addWidget(side)

        # Preserve compatibility for integrations, but put all per-command actions
        # in each command's hover/context menu rather than the right sidebar.
        self.edit = QPushButton(self)
        self.toggle = QPushButton(self)
        self.remove = QPushButton(self)
        self.run_button = QPushButton(self)
        for btn in (self.edit, self.toggle, self.remove, self.run_button):
            btn.hide()
        self.edit.clicked.connect(self.edit_selected)
        self.toggle.clicked.connect(self.toggle_selected)
        self.remove.clicked.connect(self.delete_selected)
        self.run_button.clicked.connect(self.execute_selected)

        self.refresh()
        self._apply_library_theme()

    def set_agent_mode(self, enabled):
        enabled = bool(enabled)
        if self._agent_mode == enabled:
            return
        old_menu = getattr(self, "_active_menu", None)
        if old_menu is not None:
            old_menu.close()
        self._agent_mode = enabled
        self.agent_tab.setChecked(enabled)
        self.my_tab.setChecked(not enabled)
        self.search.clear()
        self.refresh()

    def _visible_entries(self):
        return [entry for entry in self.registry.entries()
                if is_agent_command(entry) == self._agent_mode]

    def _show_error(self, error):
        source = _ERROR_SOURCES.get(str(error), str(error))
        QMessageBox.warning(self, tr("Ошибка", self.interface_language), tr(source, self.interface_language))

    def refresh(self):
        old_menu = getattr(self, "_active_menu", None)
        if old_menu is not None:
            old_menu.close()
        self._view_states[self._tree_mode] = {
            "selected": self._node_key(self.tree.currentItem()),
            "expanded": {self._node_key(item): item.isExpanded()
                         for item in self._iter_nodes() if item.data(0, GROUP_ROLE)},
        }
        state = self._view_states.get(self._agent_mode, {})
        previous_id = state.get("selected")
        expanded = state.get("expanded", {})
        self.tree.clear()
        self._menu_widgets.clear()
        self._edit_widgets.clear()
        self._last_hover = None
        entries = self._visible_entries()
        named_groups = self._group_names("folders") + self._group_names("collections")
        default_entries = ([] if self._agent_mode else
                           [entry for entry in entries if entry["builtin"] and entry["category"] not in named_groups])
        personal = [entry for entry in entries if entry not in default_entries]
        root = QTreeWidgetItem([tr("Команды по умолчанию", self.interface_language),
                                f"{len(default_entries)}", "", ""])
        self._set_group_data(root, "defaults", "Команды по умолчанию", default_entries)
        set_item_icon(root, "folder", widget=self.tree, column=0, role="muted")
        if not self._agent_mode:
            self.tree.addTopLevelItem(root)
        groups = defaultdict(list)
        for entry in default_entries:
            groups[self._default_group(entry)].append(entry)
        order = ["Управление Windows", "Управление Google Chrome",
                 "Управление YouTube", "Управление Telegram",
                 "Управление Spotify", "Управление Word",
                 "Управление Yandex Music", "Другие приложения", "Игры Steam"]
        for name in order + sorted(set(groups) - set(order)):
            if name not in groups:
                continue
            category = QTreeWidgetItem([tr(name, self.interface_language),
                                       f"{len(groups[name])}", "", ""])
            self._set_group_data(category, "default:" + name, name, groups[name])
            set_item_icon(category, {"Управление Windows": "monitor",
                                     "Управление Google Chrome": "app-window",
                                     "Управление YouTube": "globe",
                                     "Управление Telegram": "app-window",
                                     "Управление Spotify": "app-window",
                                     "Управление Word": "file-text",
                                     "Управление Yandex Music": "app-window",
                                     "Игры Steam": "gamepad-2"}.get(name, "folder"),
                          widget=self.tree, column=0, role="muted")
            root.addChild(category)
            for entry in groups[name]:
                self._add_entry(category, entry)
            category.setExpanded(expanded.get("default:" + name, False))
            self._attach_group_power(category, [item["id"] for item in groups[name]])
        root.setExpanded(expanded.get("defaults", True))
        if not self._agent_mode:
            self._attach_group_power(root, [item["id"] for item in default_entries])

        user_groups = defaultdict(list)
        for entry in personal:
            user_groups[entry["category"]].append(entry)
        for kind, names in (("folders", self._group_names("folders")),
                            ("collections", self._group_names("collections"))):
            for name in names:
                user_groups.setdefault(name, [])
        category_names = (["Команды агента", "Выученные команды", "Мои команды"]
                          if self._agent_mode else ["Мои команды", "Выученные команды"])
        category_names.extend(sorted(name for name in user_groups if name not in category_names))
        for name in category_names:
            items = user_groups.get(name, [])
            if not items and name not in self._group_names("folders") + self._group_names("collections"):
                continue
            kind = next((kind for kind in ("folders", "collections")
                         if name in self._group_names(kind)), None)
            label = tr(name, self.interface_language) if name in (
                "Мои команды", "Выученные команды", "Команды агента") else name
            category = QTreeWidgetItem([label, f"{len(items)}", "", ""])
            self._set_group_data(category, "user:" + name, name, items, kind)
            set_item_icon(category, "folder", widget=self.tree, column=0)
            self.tree.addTopLevelItem(category)
            for entry in items:
                self._add_entry(category, entry)
            category.setExpanded(expanded.get("user:" + name, bool(items)))
            self._attach_group_power(category, [item["id"] for item in items])
        self.summary.setText(
            tr("Всего команд: {count}", self.interface_language).format(count=len(entries)) + "\n"
            + (tr("Коллекций: {count}", self.interface_language).format(count=len(self._group_names("collections")))
               if self._agent_mode else f"{len(personal)} " + tr("мои / выученные", self.interface_language)) + "\n"
            + tr("Все изменения сохраняются автоматически.", self.interface_language))
        self.library_heading.setText(tr("Команды агента" if self._agent_mode else "Ваши команды", self.interface_language))
        self.library_subtitle.setText(tr(
            "Сохранённые действия агента. Проверьте шаги перед запуском."
            if self._agent_mode else "Двойной щелчок по команде — открыть её.", self.interface_language))
        self.agent_empty_title.setText(tr("Здесь пока пусто", self.interface_language))
        self.agent_empty_description.setText(tr(
            "Нажмите «Новая команда», чтобы собрать действия с AI, или откройте Jarvis AI.",
            self.interface_language))
        empty = self._agent_mode and not entries and not named_groups
        self.agent_empty.setVisible(empty)
        self.tree.setVisible(not empty)
        self._tree_mode = self._agent_mode
        self._filter(self.search.text())
        if previous_id:
            for item in self._iter_nodes():
                if self._node_key(item) == previous_id:
                    self.tree.setCurrentItem(item)
                    break
        self._selection_changed()

    def _group_names(self, kind):
        # Mocked registries in tests and older integrations may have no groups.
        value = (self.registry.groups_for(agent=self._agent_mode)
                 if hasattr(self.registry, "groups_for") else
                 getattr(self.registry, "agent_groups" if self._agent_mode else "groups", None))
        return list(value.get(kind, [])) if isinstance(value, dict) else []

    @staticmethod
    def _node_key(item):
        if item is None:
            return None
        group = item.data(0, GROUP_ROLE)
        return group["key"] if group else item.data(0, Qt.ItemDataRole.UserRole)

    def _set_group_data(self, item, key, name, members, kind=None):
        item.setData(0, GROUP_ROLE, {"key": key, "name": name, "kind": kind,
                                    "agent": self._agent_mode,
                                    "ids": [entry["id"] for entry in members]})
        item.setText(1, tr("{count} команд", self.interface_language).format(count=len(members)))
        item.setSizeHint(0, QSize(0, 38))

    def _iter_nodes(self):
        def visit(item):
            yield item
            for index in range(item.childCount()):
                yield from visit(item.child(index))
        for index in range(self.tree.topLevelItemCount()):
            yield from visit(self.tree.topLevelItem(index))

    @staticmethod
    def _default_group(entry):
        category = entry.get("category")
        if category in ("Windows", "Файлы"):
            return "Управление Windows"
        if category == "Приложения":
            return {
                "chrome": "Управление Google Chrome",
                "telegram": "Управление Telegram",
                "spotify": "Управление Spotify",
                "word": "Управление Word",
            }.get(entry.get("target"), "Другие приложения")
        return category or "Другие приложения"

    def _attach_group_power(self, item, identifiers):
        """Give folders the same right-hand power control as the reference UI."""
        self._attach_more(item)
        button = QToolButton(self.tree)
        button.setObjectName("LibraryGroupPower")
        members = [entry for entry in self.registry.entries() if entry["id"] in identifiers]
        enabled = bool(members) and all(entry["enabled"] for entry in members)
        set_button_icon(button, "power", size=19, role="success" if enabled else "muted")
        button.setFixedSize(27, 28)
        button.setToolTip(tr("Включить / отключить группу", self.interface_language))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setEnabled(bool(identifiers))
        button.setStyleSheet("QToolButton#LibraryGroupPower {border:0; background:transparent; padding:3px;}")
        button.clicked.connect(lambda _checked=False, ids=tuple(identifiers): self._toggle_group(ids))
        self.tree.setItemWidget(item, 4, button)

    def _toggle_group(self, identifiers):
        entries = {entry["id"]: entry for entry in self.registry.entries()}
        members = [entries[k] for k in identifiers if k in entries]
        if not members:
            return
        desired = not all(entry["enabled"] for entry in members)
        try:
            self.registry.set_group_enabled([entry["id"] for entry in members], desired)
            self.refresh()
            self.changed.emit()
        except (OSError, ValueError) as exc:
            self._show_error(exc)

    def _add_entry(self, category, entry):
        item = QTreeWidgetItem([tr(entry["title"], self.interface_language)
                                if entry["builtin"] and not entry.get("customized") else entry["title"],
                                ", ".join(entry.get("phrases", [])[:2]), "", ""])
        item.setData(0, Qt.ItemDataRole.UserRole, entry["id"])
        item.setToolTip(0, ", ".join(entry.get("phrases", [])))
        item.setToolTip(1, ", ".join(entry.get("phrases", [])))
        item.setSizeHint(0, QSize(0, 36))
        set_item_icon(item, CATALOG.get(entry["action"], {}).get("icon", "list-checks"),
                      widget=self.tree, column=0)
        set_item_icon(item, "power" if entry["enabled"] else "circle-minus",
                      widget=self.tree, column=4, role="success" if entry["enabled"] else "muted")
        category.addChild(item)
        pencil = LibraryHoverButton(self.tree)
        pencil.setObjectName("LibraryMore")
        set_button_icon(pencil, "pencil", size=15)
        pencil.setFixedSize(25, 28)
        pencil.setCursor(Qt.CursorShape.PointingHandCursor)
        pencil.setToolTip(tr("Открыть / изменить", self.interface_language))
        pencil.clicked.connect(lambda _checked=False, current=item: self._open_item(current))
        self.tree.setItemWidget(item, 2, pencil)
        self._show_hover_control(pencil, False)
        self._edit_widgets[entry["id"]] = pencil
        self._attach_more(item)

    def _attach_more(self, item):
        key = self._node_key(item)
        more = LibraryHoverButton(self.tree)
        more.setObjectName("LibraryMore")
        set_button_icon(more, "ellipsis", size=18)
        more.setFixedSize(25, 28)
        more.setCursor(Qt.CursorShape.PointingHandCursor)
        more.setToolTip(tr("Действия с командой", self.interface_language))
        more.clicked.connect(lambda _checked=False, current=item: self._popup_for(current))
        self.tree.setItemWidget(item, 3, more)
        self._show_hover_control(more, False)
        self._menu_widgets[key] = more

    @staticmethod
    def _show_hover_control(button, visible):
        # QTreeWidget may reshow its index widgets during layout. Clear the
        # inactive icon instead of hiding the widget, so only the current row
        # gets hover actions even after resize, expand or scrolling.
        button.setProperty("libraryRevealed", bool(visible))
        button.setEnabled(bool(visible))
        if visible:
            set_button_icon(button, button.property("jarvisIcon"),
                            size=int(button.property("jarvisIconSize") or 18))
        else:
            button.setIcon(QIcon())

    def _open_item(self, item):
        self.tree.setCurrentItem(item)
        self.open_selected()

    def _iter_leaves(self):
        return (item for item in self._iter_nodes() if item.data(0, Qt.ItemDataRole.UserRole))

    def _selected(self):
        item = self.tree.currentItem()
        if item is None:
            return None
        identifier = item.data(0, Qt.ItemDataRole.UserRole)
        return next((x for x in self.registry.entries() if x["id"] == identifier), None)

    def _item_clicked(self, item, column):
        if column == 4 and item.data(0, Qt.ItemDataRole.UserRole):
            # The green power icon at the far right is an actual toggle.
            self.tree.setCurrentItem(item)
            self.toggle_selected()

    def _selection_changed(self):
        entry = self._selected()
        self.edit.setEnabled(bool(entry))
        self.remove.setEnabled(bool(entry))
        self.toggle.setEnabled(bool(entry))
        self.run_button.setEnabled(bool(entry and entry["enabled"]))
        current = self.tree.currentItem()
        group = current.data(0, GROUP_ROLE) if current is not None else None
        hint = ("Экспорт выбранной команды" if entry else
                "Экспорт выбранной коллекции" if group and group.get("kind") == "collections" else
                "Экспорт выбранной папки" if group else "Экспорт всех команд этой вкладки")
        self.export_button.setToolTip(tr(hint, self.interface_language))
        selected_key = self._node_key(self.tree.currentItem())
        for controls in (self._menu_widgets, self._edit_widgets):
            for key, button in controls.items():
                self._show_hover_control(button, key in (selected_key, self._last_hover))

    def eventFilter(self, watched, event):
        if watched is self.tree.viewport():
            if event.type() == QEvent.Type.MouseMove:
                item = self.tree.itemAt(event.position().toPoint())
                identifier = self._node_key(item)
                if identifier != self._last_hover:
                    for buttons in (self._menu_widgets, self._edit_widgets):
                        old = buttons.get(self._last_hover)
                        if old and self._last_hover != self._node_key(self.tree.currentItem()):
                            self._show_hover_control(old, False)
                        button = buttons.get(identifier)
                        if button:
                            self._show_hover_control(button, True)
                    self._last_hover = identifier
            elif event.type() == QEvent.Type.Leave:
                # Entering a child edit/more button also generates a viewport
                # Leave; defer hiding so controls remain clickable on Windows.
                QTimer.singleShot(180, self._clear_hover_if_outside)
        return super().eventFilter(watched, event)

    def _clear_hover_if_outside(self):
        viewport = self.tree.viewport()
        if viewport.rect().contains(viewport.mapFromGlobal(QCursor.pos())):
            return
        for controls in (self._menu_widgets, self._edit_widgets):
            button = controls.get(self._last_hover)
            if button and self._last_hover != self._node_key(self.tree.currentItem()):
                self._show_hover_control(button, False)
        self._last_hover = None

    def show_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item and self._node_key(item):
            self._popup_for(item, self.tree.viewport().mapToGlobal(pos))

    def _popup_for(self, item, global_pos=None):
        if item is None or not self._node_key(item):
            return
        self.tree.setCurrentItem(item)
        menu = self.build_context_menu(item)
        if menu is None:
            return
        old_menu = getattr(self, "_active_menu", None)
        if old_menu is not None:
            old_menu.close()
        self._active_menu = menu
        button = self._menu_widgets.get(self._node_key(item))
        if global_pos is None and button is not None:
            global_pos = button.mapToGlobal(QPoint(0, button.height()))
        menu.popup(global_pos or self.cursor().pos())

    def build_context_menu(self, item):
        """Build an inspectable popover; every visible action has a real operation."""
        if item is None:
            return None
        self.tree.setCurrentItem(item)
        group = item.data(0, GROUP_ROLE)
        if group:
            return self._build_group_menu(item, group)
        entry = self._selected()
        if entry is None:
            return None
        menu = CommandContextMenu(self, config=self._config)
        add = lambda label, name, callback, **kw: menu.add_command(tr(label, self.interface_language), name, callback, **kw)
        add("Открыть", "pencil", self.open_selected)
        add("Добавить обязательную фразу", "message-square", lambda: self.add_phrase_selected(False))
        add("Добавить необязательную фразу", "plus", lambda: self.add_phrase_selected(True))
        menu.addSeparator()
        add("Включить" if not entry["enabled"] else "Отключить", "power", self.toggle_selected)
        add("Клонировать", "copy", self.duplicate_selected)
        add("Копировать", "clipboard", lambda: self._copy_records([entry], entry["title"]))
        add("Копировать как JSON", "file-text", lambda: self._copy_records([entry], entry["title"], as_json=True))
        folders = self._group_names("folders") + self._group_names("collections")
        if folders:
            move = CommandContextMenu(menu, config=self._config)
            move.setTitle(tr("Переместить в папку", self.interface_language))
            move.setIcon(icon("folder"))
            for name in dict.fromkeys(folders):
                move.add_command(name, "folder", lambda group=name: self.move_selected_to_group(group))
            menu.addMenu(move)
        menu.addSeparator()
        add("Удалить", "trash", self.delete_selected, danger=True)
        return menu

    def _group_entries(self, group):
        identifiers = set(group["ids"])
        return [entry for entry in self.registry.entries() if entry["id"] in identifiers]

    def _build_group_menu(self, item, group):
        records = self._group_entries(group)
        enabled = bool(records) and all(record["enabled"] for record in records)
        menu = CommandContextMenu(self, config=self._config)
        add = lambda label, name, callback, **kw: menu.add_command(tr(label, self.interface_language), name, callback, **kw)
        add("Открыть", "folder-open", lambda: item.setExpanded(True))
        add("Добавить обязательную фразу", "message-square", lambda: self._add_phrase(records, False, group=True), enabled=bool(records))
        add("Добавить необязательную фразу", "plus", lambda: self._add_phrase(records, True, group=True), enabled=bool(records))
        menu.addSeparator()
        add("Отключить" if enabled else "Включить", "power", lambda: self._toggle_group(group["ids"]), enabled=bool(records))
        add("Клонировать", "copy", lambda: self._duplicate_group(group), enabled=bool(records))
        add("Копировать", "clipboard", lambda: self._copy_records(records, group["name"]))
        add("Копировать как JSON", "file-text", lambda: self._copy_records(records, group["name"], as_json=True))
        if group.get("kind"):
            add("Переименовать", "pencil", lambda: self._rename_group(group))
        menu.addSeparator()
        add("Удалить", "trash", lambda: self._delete_group(group), danger=True,
            enabled=bool(records) or bool(group.get("kind")))
        return menu

    def _copy_records(self, records, label, *, as_json=False):
        # Copy only allowlisted, serializable command data, never an executable script.
        validated = [checked_command(record, builtin=record.get("builtin", False)) for record in records]
        payload = json.dumps({"version": 1, "commands": validated}, ensure_ascii=False, indent=2)
        mime = QMimeData()
        mime.setData("application/x-luxai-commands+json", payload.encode("utf-8"))
        mime.setText(payload if as_json else label)
        QApplication.clipboard().setMimeData(mime)

    def add_phrase_selected(self, optional=False):
        entry = self._selected()
        if entry:
            self._add_phrase([entry], optional)

    def _add_phrase(self, records, optional, *, group=False):
        heading = "Добавить необязательную фразу" if optional else "Добавить обязательную фразу"
        label = "Фраза"
        if group and not optional:
            label = "Префикс перед фразами всех команд папки"
        value, accepted = QInputDialog.getText(self, tr(heading, self.interface_language), tr(label, self.interface_language))
        value = value.strip()
        if not accepted or not value:
            return
        changed = []
        for record in records:
            data = dict(record)
            if optional:
                data["optional_words"] = list(dict.fromkeys(data.get("optional_words", []) + [value]))
            elif group:
                data["phrases"] = [value + " " + phrase for phrase in data.get("phrases", [])]
            else:
                data["phrases"] = list(dict.fromkeys(data.get("phrases", []) + [value]))
                data["voice_enabled"] = True
            changed.append(data)
        try:
            self.registry.save_commands(changed)
            self.refresh()
            self.changed.emit()
        except (OSError, ValueError) as exc:
            self._show_error(exc)

    def _rename_group(self, group):
        value, accepted = QInputDialog.getText(self, tr("Переименовать", self.interface_language),
                                              tr("Название", self.interface_language), text=group["name"])
        if accepted and value.strip():
            try:
                self.registry.rename_group(group["name"], value.strip(), group["kind"],
                                           agent=bool(group.get("agent")))
                self.refresh()
                self.changed.emit()
            except (OSError, ValueError) as exc:
                self._show_error(exc)

    def _delete_group(self, group):
        persistent = bool(group.get("kind"))
        message = ("Удалить папку «{title}»? Команды будут перемещены в «Мои команды»." if persistent
                   else "Удалить все команды из папки «{title}»?")
        answer = QMessageBox.question(self, tr("Удалить папку?", self.interface_language),
                                     tr(message, self.interface_language).format(title=group["name"]),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            if persistent:
                self.registry.remove_group(group["name"], group["kind"], agent=bool(group.get("agent")))
            else:
                self.registry.remove_commands(group["ids"])
            self.refresh()
            self.changed.emit()
        except (OSError, ValueError) as exc:
            self._show_error(exc)

    def _duplicate_group(self, group):
        existing = {entry["category"] for entry in self.registry.entries()}
        existing.update(self._group_names("folders") + self._group_names("collections"))
        base = group["name"][:45] + " — " + tr("копия", self.interface_language)
        name, index = base, 2
        while name in existing:
            name, index = f"{base} {index}", index + 1
        records = [self._clone_data(entry, category=name) for entry in self._group_entries(group)]
        if not records:
            return
        try:
            self.registry.add_group(name, "folders", agent=self._agent_mode)
            try:
                self.registry.save_commands(records)
            except (OSError, ValueError):
                self.registry.remove_group(name, "folders", agent=self._agent_mode)
                raise
            self.refresh()
            self.changed.emit()
        except (OSError, ValueError) as exc:
            self._show_error(exc)

    def open_selected(self, *_):
        entry = self._selected()
        if not entry:
            item = self.tree.currentItem()
            if item and item.data(0, GROUP_ROLE):
                item.setExpanded(not item.isExpanded())
            return
        self.edit_selected()

    def _clone_data(self, entry, *, category="Мои команды"):
        data = dict(entry)
        data.update(id="user_" + uuid.uuid4().hex[:16], builtin=False, learned=False,
                    agent=self._agent_mode,
                    category=category, enabled=False, hotkey="", schedule={}, event={})
        data.pop("customized", None)
        return data

    def duplicate_selected(self):
        entry = self._selected()
        if not entry:
            return
        data = self._clone_data(entry, category="Команды агента" if self._agent_mode else "Мои команды")
        suffix = " — " + tr("копия", self.interface_language)
        data["title"] = entry["title"][:100 - len(suffix)] + suffix
        try:
            saved = self.registry.save_command(data)
            self.refresh()
            for item in self._iter_leaves():
                if item.data(0, Qt.ItemDataRole.UserRole) == saved["id"]:
                    self.tree.setCurrentItem(item)
                    break
            self.changed.emit()
        except (OSError, ValueError) as exc:
            self._show_error(exc)

    def move_selected_to_group(self, group):
        entry = self._selected()
        if entry is None:
            return
        try:
            self.registry.save_command(dict(entry, category=group))
            self.refresh()
            self.changed.emit()
        except (OSError, ValueError) as exc:
            self._show_error(exc)

    def _filter(self, keyword):
        keyword = keyword.strip().casefold()
        def visit(item):
            own = keyword in item.text(0).casefold() or keyword in item.text(1).casefold() or keyword in item.toolTip(0).casefold()
            descendants = False
            for index in range(item.childCount()):
                descendants = visit(item.child(index)) or descendants
            shown = not keyword or own or descendants
            item.setHidden(not shown)
            if keyword and descendants:
                item.setExpanded(True)
            return shown
        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))

    def tree_expand_all(self):
        self.tree.expandAll()

    def tree_collapse_all(self):
        self.tree.collapseAll()

    def create_group(self, kind):
        heading = "Новая папка" if kind == "folders" else "Новая коллекция"
        name, ok = QInputDialog.getText(self, tr(heading, self.interface_language),
                                        tr("Название", self.interface_language))
        if ok and name.strip():
            try:
                self.registry.add_group(name, kind, agent=self._agent_mode)
                self.refresh()
                self.changed.emit()
            except (OSError, ValueError) as exc:
                self._show_error(exc)

    def import_commands(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Импорт из файла", self.interface_language),
                                               "", "JSON (*.json)")
        if not path:
            return
        try:
            file_path = Path(path)
            with file_path.open("rb") as source:
                content = source.read(4 * 1024 * 1024 + 1)
            if len(content) > 4 * 1024 * 1024:
                raise ValueError("Command file exceeds the safe 4 MB import limit")
            payload = json.loads(content.decode("utf-8-sig"))
            import_payload(self.registry, payload, agent=self._agent_mode)
            self.refresh()
            self.changed.emit()
        except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
            self._show_error(exc)

    def export_commands(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("Экспорт в файл", self.interface_language),
                                               "Jarvis_commands.json", "JSON (*.json)")
        if not path:
            return
        temporary = None
        try:
            file_path = Path(path)
            data = self._export_selection()
            content = json.dumps(data, ensure_ascii=False, indent=2)
            if len(content.encode("utf-8")) > 4 * 1024 * 1024:
                raise ValueError("Command file exceeds the safe 4 MB import limit")
            # An exclusive temporary file cannot overwrite an unrelated .tmp
            # next to the user's selected export, even if writing fails.
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=file_path.parent,
                                             prefix=".jarvis-export-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(content)
            temporary.replace(file_path)
        except (OSError, ValueError) as exc:
            self._show_error(exc)
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def _export_selection(self):
        item = self.tree.currentItem()
        group = item.data(0, GROUP_ROLE) if item is not None else None
        identifier = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        identifiers = (group["ids"] if group is not None else
                       [identifier] if identifier else [entry["id"] for entry in self._visible_entries()])
        return export_payload(self.registry, identifiers=identifiers, group=group,
                              agent=self._agent_mode, include_empty_groups=item is None)

    def set_context(self, planner=None, config=None):
        self._planner = planner
        if config is not None:
            self._config = config
        self._apply_library_theme()

    def _apply_library_theme(self):
        from luxai.styles import theme_colors
        theme = self._config.get("ui_theme", "dark")
        p = theme_colors(theme, self._config.get("ui_accent", "#3978f6"))
        self.tree.set_colors(p)
        self.agent_empty_icon.setPixmap(icon("bot", color=p["accent"], size=48).pixmap(48, 48))
        replacements = {
            "#191c21": p["surface"], "#1b1e24": p["surface"],
            "#323943": p["border"], "#f4f6fa": p["text"],
            "#a4aebd": p["muted"], "#b7bfcb": p["muted"],
            "#397ef6": p["accent"], "#292f39": p["control"],
            "#e8edf5": p["text"], "#3a4352": p["border"],
            "#272b33": p["control"], "#cbd1dc": p["text"],
            "#242932": p["field"], "#3b424e": p["border"],
            "#f8fafc": p["text"], "#edf2f8": p["text"],
            "#2b3443": p["hover"], "#2f425e": p["selection"],
            "#a9b2c2": p["muted"], "#c9d6e8": p["muted"],
        }
        stylesheet = self._library_base_style
        import re
        stylesheet = re.sub(r"#[0-9a-fA-F]{6}", lambda m: replacements.get(m[0], m[0]), stylesheet)
        self.setStyleSheet(stylesheet)
        self.setProperty("jarvisIconTheme", theme)
        self.setProperty("jarvisIconAccent", p["accent"])
        refresh_icons(self, theme, p["accent"])
        self._selection_changed()

    def _configure_editor(self, dialog):
        dialog.set_context(self._planner, self._config)
        dialog.run_requested.connect(self.run_entry_requested.emit)
        dialog.ai_requested.connect(self.ai_requested.emit)
        return dialog

    def new_command(self):
        dialog = self._configure_editor(CommandEditor(parent=self))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                data = dialog.get_data()
                data["agent"] = self._agent_mode
                data["learned"] = False
                selected = self.tree.currentItem()
                group = selected.data(0, GROUP_ROLE) if selected is not None else None
                data["category"] = (group["name"] if group and group.get("kind")
                                    else "Команды агента" if self._agent_mode else "Мои команды")
                self.registry.save_custom(data)
                self.refresh()
                self.changed.emit()
            except (OSError, ValueError) as exc:
                self._show_error(exc)

    def edit_selected(self):
        entry = self._selected()
        if not entry:
            return
        dialog = self._configure_editor(CommandEditor(entry, parent=self))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.registry.save_command(dialog.get_data())
                self.refresh()
                self.changed.emit()
            except (OSError, ValueError) as exc:
                self._show_error(exc)

    def toggle_selected(self):
        entry = self._selected()
        if not entry:
            return
        try:
            self.registry.set_enabled(entry["id"], not entry["enabled"])
            self.refresh()
            self.changed.emit()
        except (ValueError, OSError) as exc:
            self._show_error(exc)

    def delete_selected(self):
        entry = self._selected()
        if not entry:
            return
        answer = QMessageBox.question(
            self, tr("Удалить команду?", self.interface_language),
            tr("Удалить команду «{title}»?", self.interface_language).format(title=entry["title"]),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            try:
                self.registry.remove_command(entry["id"])
                self.refresh()
                self.changed.emit()
            except (ValueError, OSError) as exc:
                self._show_error(exc)

    def execute_selected(self):
        entry = self._selected()
        if entry is not None and entry["enabled"]:
            self.run_requested.emit(dict(entry))
