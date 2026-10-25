"""Small dark screen-inspection panel showing what Jarvis can click.

Uses a local screenshot and Windows UI Automation button list. The screenshot
is never uploaded to Gemini or any network service.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout, QWidget,
)

from luxai.screen_interact import ScreenInspection, classify_button
from luxai.ui_i18n import get_ui_language, translate_widgets, tr
from luxai.icons import icon, set_button_icon


class ScreenAssistDialog(QDialog):
    click_requested = Signal(str)
    refresh_requested = Signal()

    def __init__(self, snapshot: ScreenInspection, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Jarvis | Просмотр экрана")
        self.setWindowIcon(icon("jarvis"))
        self.setObjectName("ScreenAssistDialog")
        self.setModal(False)
        self.resize(960, 690)
        self.setMinimumSize(690, 460)
        self.setStyleSheet(
            "QListWidget{border-radius:9px;padding:8px;}"
            "QPushButton{padding:10px;font-weight:600;}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(10)
        title = QLabel("Экран и кнопки Windows")
        title.setStyleSheet("font-size:18px;font-weight:bold;")
        outer.addWidget(title)
        self.details = QLabel()
        self.details.setWordWrap(True)
        outer.addWidget(self.details)

        main = QHBoxLayout()
        self.preview = QLabel("Снимок экрана недоступен.")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(360, 225)
        self.preview.setObjectName("ScreenPreview")
        self.preview.setStyleSheet(
            "border:1px solid #6d7c96;border-radius:9px;"
        )
        main.addWidget(self.preview, 3)
        side = QVBoxLayout()
        buttons_title = QLabel("Найденные кнопки Да / Нет")
        side.addWidget(buttons_title)
        self.button_list = QListWidget()
        side.addWidget(self.button_list, 1)
        main.addLayout(side, 2)
        outer.addLayout(main, 1)

        hint = QLabel(
            "Для голосового нажатия скажите «Жарвис, нажми да» или «нажми нет». "
            "Нажимается только одна точно найденная кнопка после подтверждения. "
            "Защищённые окна и непонятные кнопки не нажимаются."
        )
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        hint.setStyleSheet("font-size:12px;")
        outer.addWidget(hint)

        actions = QHBoxLayout()
        self.yes_button = QPushButton("Нажать Да")
        set_button_icon(self.yes_button, "check-circle-2", role="success")
        self.yes_button.clicked.connect(lambda: self.click_requested.emit("yes"))
        actions.addWidget(self.yes_button)
        self.no_button = QPushButton("Нажать Нет")
        set_button_icon(self.no_button, "x-circle")
        self.no_button.clicked.connect(lambda: self.click_requested.emit("no"))
        actions.addWidget(self.no_button)
        self.refresh_button = QPushButton("Обновить снимок")
        set_button_icon(self.refresh_button, "refresh-cw")
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        actions.addWidget(self.refresh_button)
        close = QPushButton("Закрыть")
        set_button_icon(close, "x")
        close.clicked.connect(self.close)
        actions.addWidget(close)
        outer.addLayout(actions)
        self.set_snapshot(snapshot)
        translate_widgets(self, get_ui_language())

    def set_snapshot(self, snapshot: ScreenInspection):
        self.snapshot = snapshot
        caption = {"en": "Inspected window: ", "ro": "Fereastra verificată: ", "ru": "Проверяемое окно: "}[get_ui_language()]
        self.details.setText(caption + snapshot.title)
        image = QPixmap()
        if snapshot.screenshot and image.loadFromData(snapshot.screenshot, "PNG"):
            self.preview.setPixmap(
                image.scaled(
                    690, 420,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self.preview.setText("Снимок экрана недоступен.")
        self.button_list.clear()
        for item in snapshot.buttons:
            kind = classify_button(item.label)
            if kind in ("yes", "no"):
                row = QListWidgetItem(f"{item.label}  —  ({item.center[0]}, {item.center[1]})")
                name = "check-circle-2" if kind == "yes" else "x-circle"
                row.setIcon(icon(name, color="#3978f6", size=18))
                row.setData(Qt.ItemDataRole.UserRole + 60, name)
                row.setData(Qt.ItemDataRole.UserRole + 61, "success" if kind == "yes" else "default")
                self.button_list.addItem(row)
        yes_count = sum(
            1 for b in snapshot.buttons if classify_button(b.label) == "yes"
        )
        no_count = sum(
            1 for b in snapshot.buttons if classify_button(b.label) == "no"
        )
        self.yes_button.setEnabled(yes_count == 1)
        self.no_button.setEnabled(no_count == 1)
        if not self.button_list.count():
            self.button_list.addItem(
                "Кнопки через UI Automation не обнаружены."
            )
