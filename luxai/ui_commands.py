"""Local command library with Luxify-style folder tree and contextual actions.

Default commands remain read-only. Imports are validated and never executed.
"""
from __future__ import annotations

import json
import uuid
from collections import defaultdict
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMenu, QMessageBox, QPushButton, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    QHeaderView, QApplication,
)
from luxai.command_registry import CommandRegistry, MAX_USER_COMMANDS, checked_command
from luxai.ui_i18n import tr, get_ui_language, translate_widgets
from luxai.icons import icon, set_button_icon, set_item_icon
from luxai.action_catalog import CATALOG
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
        self.interface_language = get_ui_language()
        self._planner = None
        self._config = {}
        self._last_hover = None
        self._menu_widgets = {}
        self.setObjectName("CommandsPage")
        self.setStyleSheet("""
            QFrame#LibraryCard {background: #191c21; border: 1px solid #323943; border-radius: 15px;}
            QFrame#LibrarySidebar {background: #1b1e24; border: 1px solid #323943; border-radius: 15px;}
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
            QTreeWidget#CommandTree::item {height: 36px; border-radius: 7px; padding: 3px;}
            QTreeWidget#CommandTree::item:hover {background: #2b3443;}
            QTreeWidget#CommandTree::item:selected {background: #2f425e; color: white;}
            QHeaderView::section {background: transparent; color: #a9b2c2;
                                  border: none; padding: 4px;}
            QToolButton#LibraryMore {background: transparent; border: 0;
                                     padding: 2px; color: #c9d6e8; font-size: 19px;}
        """)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        center = QWidget()
        center_col = QVBoxLayout(center)
        center_col.setContentsMargins(0, 0, 0, 0)
        center_col.setSpacing(12)
        tabs = QHBoxLayout()
        tabs.setSpacing(8)
        self.my_tab = QPushButton("▣  " + tr("Мои команды", self.interface_language))
        self.my_tab.setObjectName("LibraryTab")
        self.my_tab.setCheckable(True)
        self.my_tab.setChecked(True)
        tabs.addWidget(self.my_tab)
        self.agent_tab = QPushButton("✧  " + tr("Команды агента", self.interface_language))
        self.agent_tab.setObjectName("LibraryTab")
        self.agent_tab.setToolTip(tr("Команды агента пока не настроены.", self.interface_language))
        self.agent_tab.clicked.connect(self._agent_tab_unavailable)
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
        row.addWidget(heading)
        row.addStretch()
        self.expand_all = QPushButton("⌄")
        self.expand_all.setToolTip(tr("Развернуть все", self.interface_language))
        self.expand_all.setFixedSize(27, 27)
        self.expand_all.clicked.connect(self.tree_expand_all)
        row.addWidget(self.expand_all)
        self.collapse_all = QPushButton("⌃")
        self.collapse_all.setFixedSize(27, 27)
        self.collapse_all.setToolTip(tr("Свернуть все", self.interface_language))
        self.collapse_all.clicked.connect(self.tree_collapse_all)
        row.addWidget(self.collapse_all)
        area.addLayout(row)
        subtitle = QLabel(tr("Двойной щелчок по команде — открыть её.", self.interface_language))
        subtitle.setObjectName("LibraryMuted")
        area.addWidget(subtitle)

        self.tree = QTreeWidget()
        self.tree.setObjectName("CommandTree")
        self.tree.setColumnCount(4)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(21)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setIconSize(QSize(20, 20))
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(2, 30)
        self.tree.setColumnWidth(3, 28)
        self.tree.viewport().setMouseTracking(True)
        self.tree.viewport().installEventFilter(self)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(self.open_selected)
        area.addWidget(self.tree, 1)
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
        self.create_button = action("+  Новая команда", "plus", self.new_command, primary=True)
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

    def _agent_tab_unavailable(self):
        self.agent_tab.setChecked(False)
        self.my_tab.setChecked(True)

    def refresh(self):
        previous = self._selected()
        previous_id = previous["id"] if previous else None
        self.tree.clear()
        self._menu_widgets.clear()
        self._last_hover = None
        entries = self.registry.entries()
        default_entries = [entry for entry in entries if entry["builtin"]]
        personal = [entry for entry in entries if not entry["builtin"]]
        root = QTreeWidgetItem([tr("Команды по умолчанию", self.interface_language),
                                f"{len(default_entries)}", "", ""])
        root.setFlags(root.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        set_item_icon(root, "folder", widget=self.tree, column=0, role="muted")
        self.tree.addTopLevelItem(root)
        groups = defaultdict(list)
        for entry in default_entries:
            groups[entry["category"]].append(entry)
        order = ["Windows", "Приложения", "Игры Steam", "Файлы"]
        for name in order + sorted(set(groups) - set(order)):
            if name not in groups:
                continue
            category = QTreeWidgetItem([tr(name, self.interface_language),
                                       f"{len(groups[name])}", "", ""])
            category.setFlags(category.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            set_item_icon(category, {"Windows": "monitor", "Приложения": "app-window",
                                     "Игры Steam": "gamepad-2", "Файлы": "folder"}.get(name, "folder"),
                          widget=self.tree, column=0, role="muted")
            root.addChild(category)
            for entry in groups[name]:
                self._add_entry(category, entry)
            category.setExpanded(False)
        root.setExpanded(True)

        user_groups = defaultdict(list)
        for entry in personal:
            user_groups[entry["category"]].append(entry)
        for kind, names in (("folders", getattr(self.registry, "groups", {}).get("folders", [])),
                            ("collections", getattr(self.registry, "groups", {}).get("collections", []))):
            for name in names:
                user_groups.setdefault(name, [])
        category_names = ["Мои команды", "Выученные команды"]
        category_names.extend(sorted(name for name in user_groups if name not in category_names))
        for name in category_names:
            items = user_groups.get(name, [])
            if not items and name not in getattr(self.registry, "groups", {}).get("folders", []) + getattr(self.registry, "groups", {}).get("collections", []):
                continue
            category = QTreeWidgetItem([tr(name, self.interface_language), f"{len(items)}", "", ""])
            category.setFlags(category.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            set_item_icon(category, "folder", widget=self.tree, column=0)
            self.tree.addTopLevelItem(category)
            for entry in items:
                self._add_entry(category, entry)
            category.setExpanded(bool(items))
        self.summary.setText(
            f"{len(entries)} " + tr("команды", self.interface_language) + "\n"
            f"{len(personal)} " + tr("мои / выученные", self.interface_language) + "\n"
            + tr("Все изменения сохраняются автоматически.", self.interface_language))
        self._filter(self.search.text())
        if previous_id:
            for item in self._iter_leaves():
                if item.data(0, Qt.ItemDataRole.UserRole) == previous_id:
                    self.tree.setCurrentItem(item)
                    break
        self._selection_changed()

    def _add_entry(self, category, entry):
        item = QTreeWidgetItem([tr(entry["title"], self.interface_language)
                                if entry["builtin"] else entry["title"],
                                ", ".join(entry.get("phrases", [])[:2]), "", ""])
        item.setData(0, Qt.ItemDataRole.UserRole, entry["id"])
        item.setToolTip(0, ", ".join(entry.get("phrases", [])))
        item.setToolTip(1, ", ".join(entry.get("phrases", [])))
        item.setSizeHint(0, QSize(0, 36))
        set_item_icon(item, CATALOG.get(entry["action"], {}).get("icon", "list-checks"),
                      widget=self.tree, column=0)
        set_item_icon(item, "power" if entry["enabled"] else "circle-minus",
                      widget=self.tree, column=2, role="success" if entry["enabled"] else "muted")
        category.addChild(item)
        more = QToolButton(self.tree)
        more.setObjectName("LibraryMore")
        more.setText("⋯")
        more.setFixedSize(25, 28)
        more.setCursor(Qt.CursorShape.PointingHandCursor)
        more.setToolTip(tr("Действия с командой", self.interface_language))
        more.clicked.connect(lambda _checked=False, current=item: self._popup_for(current))
        self.tree.setItemWidget(item, 3, more)
        more.hide()
        self._menu_widgets[entry["id"]] = more

    def _iter_leaves(self):
        def visit(item):
            if item.data(0, Qt.ItemDataRole.UserRole):
                yield item
            for index in range(item.childCount()):
                yield from visit(item.child(index))
        for index in range(self.tree.topLevelItemCount()):
            yield from visit(self.tree.topLevelItem(index))

    def _selected(self):
        item = self.tree.currentItem()
        if item is None:
            return None
        identifier = item.data(0, Qt.ItemDataRole.UserRole)
        return next((x for x in self.registry.entries() if x["id"] == identifier), None)

    def _selection_changed(self):
        entry = self._selected()
        self.edit.setEnabled(bool(entry and not entry["builtin"]))
        self.remove.setEnabled(bool(entry and not entry["builtin"]))
        self.toggle.setEnabled(bool(entry))
        self.run_button.setEnabled(bool(entry and entry["enabled"]))

    def eventFilter(self, watched, event):
        if watched is self.tree.viewport():
            if event.type() == QEvent.Type.MouseMove:
                item = self.tree.itemAt(event.position().toPoint())
                identifier = item.data(0, Qt.ItemDataRole.UserRole) if item else None
                if identifier != self._last_hover:
                    old = self._menu_widgets.get(self._last_hover)
                    if old:
                        old.hide()
                    button = self._menu_widgets.get(identifier)
                    if button:
                        button.show()
                    self._last_hover = identifier
            elif event.type() == QEvent.Type.Leave:
                old = self._menu_widgets.get(self._last_hover)
                if old and not old.underMouse():
                    old.hide()
                    self._last_hover = None
        return super().eventFilter(watched, event)

    def show_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item and item.data(0, Qt.ItemDataRole.UserRole):
            self._popup_for(item, self.tree.viewport().mapToGlobal(pos))

    def _popup_for(self, item, global_pos=None):
        if item is None or not item.data(0, Qt.ItemDataRole.UserRole):
            return
        self.tree.setCurrentItem(item)
        entry = self._selected()
        if entry is None:
            return
        menu = QMenu(self)
        menu.addAction(tr("Открыть", self.interface_language),
                       self.open_selected)
        menu.addAction(tr("Выполнить сейчас", self.interface_language),
                       self.execute_selected).setEnabled(entry["enabled"])
        menu.addSeparator()
        menu.addAction(tr("Создать копию", self.interface_language),
                       self.duplicate_selected)
        menu.addAction(tr("Копировать название", self.interface_language),
                       lambda: QApplication.clipboard().setText(entry["title"]))
        menu.addAction(tr("Копировать как JSON", self.interface_language),
                       lambda: QApplication.clipboard().setText(json.dumps(entry, ensure_ascii=False, indent=2)))
        menu.addSeparator()
        menu.addAction(tr("Включить" if not entry["enabled"] else "Отключить",
                          self.interface_language), self.toggle_selected)
        if not entry["builtin"]:
            menu.addAction(tr("Изменить", self.interface_language), self.edit_selected)
            menu.addAction(tr("Удалить", self.interface_language), self.delete_selected)
        button = self._menu_widgets.get(entry["id"])
        if global_pos is None and button is not None:
            global_pos = button.mapToGlobal(QPoint(0, button.height()))
        menu.exec(global_pos or self.cursor().pos())

    def open_selected(self, *_):
        entry = self._selected()
        if not entry:
            return
        if entry["builtin"]:
            # Do not silently rewrite shipped presets. Open an editable copy.
            self.duplicate_selected()
        else:
            self.edit_selected()

    def duplicate_selected(self):
        entry = self._selected()
        if not entry:
            return
        copy = dict(entry)
        copy.pop("id", None)
        copy["builtin"] = False
        copy["learned"] = False
        copy["category"] = "Мои команды"
        copy["title"] = entry["title"] + " — копия"
        copy["enabled"] = False  # Avoid duplicate hotkey/voice triggers until reviewed.
        copy["hotkey"] = ""
        if copy.get("phrases"):
            copy["phrases"] = []  # Ask user to choose an unambiguous wake phrase.
        copy["voice_enabled"] = False
        dialog = self._configure_editor(CommandEditor(copy, parent=self))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                data = dialog.get_data()
                data.pop("id", None)
                self.registry.save_custom(data)
                self.refresh()
                self.changed.emit()
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, tr("Ошибка", self.interface_language), str(exc))

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
                self.registry.add_group(name, kind)
                self.refresh()
                self.changed.emit()
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, tr("Ошибка", self.interface_language), str(exc))

    def import_commands(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Импорт из файла", self.interface_language),
                                               "", "JSON (*.json)")
        if not path:
            return
        try:
            file_path = Path(path)
            if file_path.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("Command file exceeds the safe 4 MB import limit")
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Invalid command export format")
            records = payload.get("commands")
            if not isinstance(records, list) or len(records) > MAX_USER_COMMANDS:
                raise ValueError("Invalid command list")
            if len(self.registry.custom) + len(records) > MAX_USER_COMMANDS:
                raise ValueError("Too many custom commands")
            items = []
            for record in records:
                raw = dict(record)
                raw["id"] = "user_" + uuid.uuid4().hex[:16]
                raw["builtin"] = False
                raw["enabled"] = False  # Import never auto-enables potentially dangerous triggers.
                raw["hotkey"] = ""
                items.append(checked_command(raw))
            previous = list(self.registry.custom)
            try:
                self.registry.custom = previous + items
                self.registry._persist()
            except OSError:
                self.registry.custom = previous
                raise
            self.refresh()
            self.changed.emit()
        except (OSError, ValueError, TypeError, KeyError) as exc:
            QMessageBox.warning(self, tr("Ошибка", self.interface_language), str(exc))

    def export_commands(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("Экспорт в файл", self.interface_language),
                                               "Jarvis_commands.json", "JSON (*.json)")
        if not path:
            return
        try:
            file_path = Path(path)
            data = {"version": 1, "commands": self.registry.custom}
            temporary = file_path.with_suffix(file_path.suffix + ".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(file_path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr("Ошибка", self.interface_language), str(exc))

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
        entry = self._selected()
        if not entry or entry["builtin"]:
            return
        dialog = self._configure_editor(CommandEditor(entry, parent=self))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.registry.save_custom(dialog.get_data())
                self.refresh()
                self.changed.emit()
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, tr("Ошибка", self.interface_language), str(exc))

    def toggle_selected(self):
        entry = self._selected()
        if not entry:
            return
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
