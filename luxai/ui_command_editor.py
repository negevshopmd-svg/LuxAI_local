"""Visual multi-action command editor, with a category-based Add Action dialog."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from luxai.action_catalog import CATALOG, CATEGORIES, describe_step, validate_step
from luxai.ui_i18n import get_ui_language, translate_widgets, tr
from luxai.ui_action_picker import ActionPicker, ActionOptionsDialog
from luxai.icons import icon, set_button_icon


class CommandEditor(QDialog):
    MAX_ACTIONS = 8

    def __init__(self, command=None, parent=None):
        super().__init__(parent)
        self.original = dict(command or {})
        self.setWindowTitle("Новая команда" if command is None else "Изменить команду")
        self.setWindowIcon(icon("jarvis"))
        self.setObjectName("CommandEditorDialog")
        self.resize(805, 660)
        self.setMinimumSize(680, 540)
        self.steps = []
        self._legacy = False

        previous = self.original.get("steps")
        if previous:
            self.steps = [validate_step(step) for step in previous]
        elif command:
            entry = {
                "action": self.original.get("action"),
                "target": self.original.get("target", ""),
                "location": self.original.get("location", "desktop"),
            }
            try:
                self.steps = [validate_step(entry)]
            except (ValueError, TypeError):
                self._legacy = True  # Keep previously saved verified Steam action.

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 19, 22, 19)
        root.setSpacing(13)
        header = QHBoxLayout()
        title = QLabel(self.windowTitle())
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addStretch()
        close = QPushButton()
        set_button_icon(close, "x")
        close.setToolTip("Закрыть")
        close.setAccessibleName("Закрыть")
        close.setFixedWidth(38)
        close.clicked.connect(self.reject)
        header.addWidget(close)
        root.addLayout(header)

        hint = QLabel(
            "Назовите команду, добавьте фразы и выберите действия. "
            "Jarvis выполнит их по порядку, без ожидания ИИ."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        name = QLabel("Название команды")
        root.addWidget(name)
        self.title_field = QLineEdit(self.original.get("title", ""))
        self.title_field.setPlaceholderText("Например: Открыть мой рабочий набор")
        root.addWidget(self.title_field)

        words = QLabel("Фразы  (несколько вариантов через запятую)")
        root.addWidget(words)
        self.phrase_field = QLineEdit(", ".join(self.original.get("phrases", [])))
        self.phrase_field.setPlaceholderText(
            "открой мой набор, включи рабочие программы"
        )
        root.addWidget(self.phrase_field)

        actions_bar = QHBoxLayout()
        title_actions = QLabel("Действия")
        title_actions.setStyleSheet("font-size:16px; font-weight:700;")
        actions_bar.addWidget(title_actions)
        actions_bar.addStretch()
        self.counter = QLabel("")
        self.counter.setObjectName("Muted")
        actions_bar.addWidget(self.counter)
        root.addLayout(actions_bar)

        content = QHBoxLayout()
        content.setSpacing(10)
        self.actions_list = QListWidget()
        self.actions_list.setObjectName("CommandActionsList")
        self.actions_list.setAlternatingRowColors(False)
        self.actions_list.setSpacing(5)
        self.actions_list.setToolTip("Выберите действие, чтобы изменить или переместить.")
        self.actions_list.currentRowChanged.connect(self._update_buttons)
        self.actions_list.itemDoubleClicked.connect(lambda _item: self.edit_action())
        content.addWidget(self.actions_list, 1)

        controls = QVBoxLayout()
        controls.setSpacing(9)
        self.add_button = QPushButton("Добавить действие")
        self.add_button.setObjectName("Primary")
        set_button_icon(self.add_button, "plus", role="white")
        self.add_button.clicked.connect(self.add_action)
        controls.addWidget(self.add_button)
        self.edit_button = QPushButton("Изменить")
        set_button_icon(self.edit_button, "pencil")
        self.edit_button.clicked.connect(self.edit_action)
        controls.addWidget(self.edit_button)
        self.up_button = QPushButton("Выше")
        set_button_icon(self.up_button, "arrow-up")
        self.up_button.clicked.connect(lambda: self.move_action(-1))
        controls.addWidget(self.up_button)
        self.down_button = QPushButton("Ниже")
        set_button_icon(self.down_button, "arrow-down")
        self.down_button.clicked.connect(lambda: self.move_action(1))
        controls.addWidget(self.down_button)
        self.delete_button = QPushButton("Удалить")
        set_button_icon(self.delete_button, "trash-2", role="danger")
        self.delete_button.clicked.connect(self.remove_action)
        controls.addWidget(self.delete_button)
        controls.addStretch()
        help_text = QLabel("Доступно до 8 действий в одной команде.")
        help_text.setWordWrap(True)
        help_text.setObjectName("Muted")
        controls.addWidget(help_text)
        content.addLayout(controls)
        root.addLayout(content, 1)

        info = QLabel(
            "Создание файлов, взаимодействие с клавиатурой и мышью требуют подтверждения. "
            "CMD и PowerShell не исполняются автоматически."
        )
        info.setObjectName("Muted")
        info.setWordWrap(True)
        root.addWidget(info)

        footer = QHBoxLayout()
        footer.addStretch()
        cancel = QPushButton("Отмена")
        set_button_icon(cancel, "x")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        save = QPushButton("Сохранить команду")
        save.setObjectName("Primary")
        set_button_icon(save, "save", role="white")
        save.clicked.connect(self._validate_accept)
        footer.addWidget(save)
        root.addLayout(footer)
        self.setStyleSheet("""
            QListWidget#CommandActionsList {
                border-radius:12px; padding:8px;
            }
            QListWidget#CommandActionsList::item {
                margin:2px; border-radius:8px; padding:12px;
            }
            QListWidget#CommandActionsList::item:selected {
                border:1px solid #4386ff;
            }
        """)
        self._refresh_steps()
        translate_widgets(self, get_ui_language())

    def _refresh_steps(self, selected=None):
        self.actions_list.clear()
        for i, step in enumerate(self.steps, 1):
            raw_title = CATALOG[step["action"]]["title"]
            description = tr(raw_title, get_ui_language())
            if step.get("target"):
                target = str(step["target"])
                description += ": " + (target[:45] + "..." if len(target) > 48 else target)
            item = QListWidgetItem(f"{i}.  {description}")
            name = dict(CATEGORIES).get(CATALOG[step["action"]]["category"], "list-checks")
            item.setIcon(icon(name, color="#3978f6", size=18))
            item.setData(Qt.ItemDataRole.UserRole + 60, name)
            item.setData(Qt.ItemDataRole.UserRole + 61, "accent")
            self.actions_list.addItem(item)
        if self._legacy:
            note = QListWidgetItem(
                "Старая сохранённая команда Steam: действие сохранено без изменений"
            )
            self.actions_list.addItem(note)
        if selected is not None and 0 <= selected < len(self.steps):
            self.actions_list.setCurrentRow(selected)
        elif self.steps:
            self.actions_list.setCurrentRow(len(self.steps)-1)
        self.counter.setText(f"{len(self.steps)} / {self.MAX_ACTIONS}")
        self.add_button.setEnabled(len(self.steps) < self.MAX_ACTIONS and not self._legacy)
        self._update_buttons()

    def _update_buttons(self, *_):
        idx = self.actions_list.currentRow()
        selected = 0 <= idx < len(self.steps)
        self.edit_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)
        self.up_button.setEnabled(selected and idx > 0)
        self.down_button.setEnabled(selected and idx < len(self.steps)-1)

    def add_action(self):
        if self._legacy or len(self.steps) >= self.MAX_ACTIONS:
            return
        picker = ActionPicker(self)
        if picker.exec() == QDialog.DialogCode.Accepted and picker.step:
            self.steps.append(picker.step)
            self._refresh_steps(len(self.steps) - 1)

    def edit_action(self):
        idx = self.actions_list.currentRow()
        if not (0 <= idx < len(self.steps)):
            return
        step = self.steps[idx]
        dialog = ActionOptionsDialog(step["action"], step, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.data:
            self.steps[idx] = dialog.data
            self._refresh_steps(idx)

    def move_action(self, offset):
        idx = self.actions_list.currentRow()
        dest = idx + offset
        if 0 <= idx < len(self.steps) and 0 <= dest < len(self.steps):
            self.steps[idx], self.steps[dest] = self.steps[dest], self.steps[idx]
            self._refresh_steps(dest)

    def remove_action(self):
        idx = self.actions_list.currentRow()
        if 0 <= idx < len(self.steps):
            self.steps.pop(idx)
            self._refresh_steps(min(idx, len(self.steps)-1))

    def get_data(self):
        if self._legacy and not self.steps:
            data = dict(self.original)
        else:
            first = self.steps[0] if self.steps else {"action": "", "target": "", "location": "desktop"}
            data = {
                "id": self.original.get("id"),
                "category": self.original.get("category", "Мои команды"),
                "action": first["action"],
                "target": first["target"],
                "location": first["location"],
                "steps": list(self.steps),
                "enabled": self.original.get("enabled", True),
                "learned": self.original.get("learned", False),
            }
        data.update({
            "title": self.title_field.text().strip(),
            "phrases": [
                phrase.strip()
                for phrase in self.phrase_field.text().split(",")
                if phrase.strip()
            ],
        })
        return data

    def _validate_accept(self):
        from uuid import uuid4
        from luxai.command_registry import checked_command
        payload = self.get_data()
        payload["id"] = payload.get("id") or "user_" + uuid4().hex[:16]
        try:
            checked_command(payload)
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, tr("Ошибка команды"), str(exc))
            return
        self.accept()
