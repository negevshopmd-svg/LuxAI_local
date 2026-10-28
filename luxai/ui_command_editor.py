"""A complete command draft: phrases, triggers, ordered actions and a live check."""
from __future__ import annotations

from PySide6.QtCore import QDate, QSize, Qt, QTime, QTimer, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QBoxLayout, QCheckBox, QComboBox, QDateEdit, QDialog, QFormLayout, QFrame, QHBoxLayout,
    QInputDialog, QKeySequenceEdit, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QScrollArea, QSizeGrip, QSizePolicy, QTimeEdit, QToolButton,
    QVBoxLayout, QWidget,
)

from luxai.action_catalog import CATALOG, validate_step
from luxai.command_registry import APP_TARGETS, checked_command
from luxai.ui_i18n import get_ui_language, translate_widgets, tr
from luxai.ui_action_picker import ActionPicker, ActionOptionsDialog, APP_LABELS
from luxai.ui_command_fields import PhraseChips
from luxai.ui_home import ToggleSwitch
from luxai.icons import icon, refresh_icons, set_button_icon, set_label_icon
from luxai.styles import theme_colors


def _label(text, name=None):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    if name:
        label.setObjectName(name)
    return label


def _card(parent=None):
    frame = QFrame(parent)
    frame.setObjectName("CommandCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 17, 18, 17)
    layout.setSpacing(12)
    return frame, layout


def _heading(text, tooltip=""):
    row = QHBoxLayout()
    row.setSpacing(7)
    row.addWidget(_label(text, "EditorSectionTitle"))
    if tooltip:
        info = QToolButton()
        set_button_icon(info, "info", size=15, role="muted")
        info.setObjectName("EditorIconButton")
        info.setToolTip(tooltip)
        info.setAccessibleName(text)
        row.addWidget(info)
    row.addStretch()
    return row


class CommandEditor(QDialog):
    MAX_ACTIONS = 8
    run_requested = Signal(object)
    ai_requested = Signal(str, object)

    def __init__(self, command=None, parent=None):
        super().__init__(parent)
        self.original = dict(command or {})
        self.steps = []
        self._legacy = False
        self._recorder = None
        self._ai_pending = False
        self._context_config = {}
        self._ai_prompt = ""
        self._drag_offset = None
        self.setWindowTitle("Новая команда" if command is None else "Изменить команду")
        self.setWindowIcon(icon("jarvis"))
        self.setObjectName("CommandEditorDialog")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.resize(1060, 720)
        self.setMinimumSize(760, 560)
        previous = self.original.get("steps")
        if previous:
            self.steps = [validate_step(step) for step in previous]
        elif command:
            try:
                self.steps = [validate_step({
                    "action": self.original.get("action"), "target": self.original.get("target", ""),
                    "location": self.original.get("location", "desktop"),
                })]
            except (ValueError, TypeError):
                self._legacy = True

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(15)
        header = QHBoxLayout()
        back = QPushButton()
        set_button_icon(back, "chevron-left")
        back.setFixedSize(32, 32)
        back.setToolTip("Назад")
        back.clicked.connect(self.reject)
        header.addWidget(back)
        breadcrumb = _label("Jarvis  /  " + tr("Команды") + "  /  " + tr(self.windowTitle()), "Muted")
        header.addWidget(breadcrumb, 1)
        close = QPushButton()
        close.setObjectName("EditorIconButton")
        set_button_icon(close, "x")
        close.setFixedSize(32, 32)
        close.setToolTip("Закрыть")
        close.setAccessibleName("Закрыть")
        close.clicked.connect(self.reject)
        header.addWidget(close)
        root.addLayout(header)
        root.addWidget(_label(self.windowTitle(), "PageTitle"))

        body = QHBoxLayout()
        body.setSpacing(16)
        self.main_scroll = QScrollArea()
        self.main_scroll.setObjectName("CommandEditorScroll")
        self.main_scroll.setWidgetResizable(True)
        self.main_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.main_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("CommandEditorBody")
        main = QVBoxLayout(content)
        main.setContentsMargins(0, 0, 4, 0)
        main.setSpacing(14)
        self.main_scroll.setWidget(content)
        body.addWidget(self.main_scroll, 1)

        details, form = _card()
        form.addWidget(_label("Название команды", "EditorSectionTitle"))
        self.title_field = QLineEdit(self.original.get("title", ""))
        self.title_field.setMaxLength(100)
        self.title_field.setPlaceholderText("Например: Начать рабочий день")
        form.addWidget(self.title_field)
        self.phrases_toggle = self._expander("Фразы", form, True)
        self.phrases_panel = QWidget()
        self._phrase_rows = []
        self.phrases_panel.setObjectName("EditorPlain")
        phrases = QVBoxLayout(self.phrases_panel)
        phrases.setContentsMargins(0, 0, 0, 0)
        phrases.setSpacing(10)
        self.phrase_chips = PhraseChips(self.original.get("phrases", []), "Введите фразу…", "+ Фраза")
        self.phrase_field = self.phrase_chips.input
        phrases.addLayout(self._phrase_row("Что сказать", "Любая из этих фраз запускает команду. Можно добавить несколько вариантов.", self.phrase_chips))
        self.optional_chips = PhraseChips(self.original.get("optional_words", []), "Например: пожалуйста", "+ Слово")
        self.optional_words = self.optional_chips.input
        phrases.addLayout(self._phrase_row("Можно добавить", "Необязательные слова в начале или конце фразы, например «пожалуйста».", self.optional_chips))
        form.addWidget(self.phrases_panel)
        self.phrases_toggle.toggled.connect(self.phrases_panel.setVisible)

        form.addLayout(_heading("Запуск", "Голос, горячие клавиши, расписание и события работают, пока Jarvis запущен."))
        self.voice_enabled = ToggleSwitch(self.original.get("voice_enabled", True))
        self.voice_enabled.setAccessibleName("Голосом")
        voice_row = QHBoxLayout()
        voice_row.addWidget(self.voice_enabled)
        voice_row.addWidget(_label("Голосом"))
        voice_row.addStretch()
        form.addLayout(voice_row)
        triggers = QHBoxLayout()
        self._trigger_row = triggers
        triggers.setSpacing(7)
        self.hotkey_toggle = self._trigger_button("+ Клавиша", "keyboard", bool(self.original.get("hotkey")))
        self.schedule_toggle = self._trigger_button("+ По расписанию", "clock", bool(self.original.get("schedule")))
        self.event_toggle = self._trigger_button("+ По событию", "bell", bool(self.original.get("event")))
        for button in (self.hotkey_toggle, self.schedule_toggle, self.event_toggle):
            triggers.addWidget(button, 1)
        form.addLayout(triggers)
        self.hotkey_panel = QWidget()
        self.hotkey_panel.setObjectName("EditorPlain")
        keys = QHBoxLayout(self.hotkey_panel)
        self._hotkey_row = keys
        keys.setContentsMargins(0, 0, 0, 0)
        keys.addWidget(_label("Сочетание клавиш"))
        self.hotkey = QKeySequenceEdit(QKeySequence(self.original.get("hotkey", "")))
        self.hotkey.setMaximumSequenceLength(1)
        keys.addWidget(self.hotkey, 1)
        form.addWidget(self.hotkey_panel)
        self.hotkey_panel.setVisible(self.hotkey_toggle.isChecked())
        self.hotkey_toggle.toggled.connect(self.hotkey_panel.setVisible)
        self.schedule_panel = self._build_schedule()
        form.addWidget(self.schedule_panel)
        self.schedule_panel.setVisible(self.schedule_toggle.isChecked())
        self.schedule_toggle.toggled.connect(self.schedule_panel.setVisible)
        self.event_panel = self._build_event()
        form.addWidget(self.event_panel)
        self.event_panel.setVisible(self.event_toggle.isChecked())
        self.event_toggle.toggled.connect(self.event_panel.setVisible)
        main.addWidget(details)

        action_card, actions = _card()
        action_header = _heading("Действия")
        self.counter = _label("", "Muted")
        action_header.addWidget(self.counter)
        actions.addLayout(action_header)
        toolbar = QHBoxLayout()
        self._action_toolbar = toolbar
        toolbar.setSpacing(8)
        self.add_button = QPushButton("Действие")
        self.add_button.setObjectName("Primary")
        set_button_icon(self.add_button, "plus", role="white")
        self.add_button.clicked.connect(self.add_action)
        self.record_button = QPushButton("Записать")
        set_button_icon(self.record_button, "circle", role="danger")
        self.record_button.clicked.connect(self.toggle_recording)
        self.ai_button = QPushButton("С ИИ")
        set_button_icon(self.ai_button, "sparkles", role="accent")
        self.ai_button.clicked.connect(self.request_ai)
        for button in (self.add_button, self.record_button, self.ai_button):
            toolbar.addWidget(button)
        toolbar.addStretch()
        actions.addLayout(toolbar)
        self.record_game_keys = QCheckBox("Записывать игровые клавиши (буквы и цифры)")
        self.record_game_keys.setChecked(False)
        self.record_game_keys.setToolTip("Записывает буквы и цифры только в Dota 2, Counter-Strike 2, War Thunder и Undertale.")
        actions.addWidget(self.record_game_keys)
        self.actions_list = QListWidget()
        self.actions_list.setObjectName("CommandActionsList")
        self.actions_list.setSpacing(5)
        self.actions_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.actions_list.currentRowChanged.connect(self._update_buttons)
        self.actions_list.itemDoubleClicked.connect(lambda _item: self.edit_action())
        actions.addWidget(self.actions_list)
        self.empty_hint = _label("Добавьте действие, запишите шаги или опишите задачу ИИ.", "Muted")
        actions.addWidget(self.empty_hint)
        self.action_feedback = _label("", "Muted")
        self.action_feedback.hide()
        actions.addWidget(self.action_feedback)
        main.addWidget(action_card)

        advanced_card, advanced = _card()
        self.advanced_toggle = self._expander("Дополнительно", advanced, False)
        self.advanced_panel = QWidget()
        self.advanced_panel.setObjectName("EditorPlain")
        advanced_options = QVBoxLayout(self.advanced_panel)
        advanced_options.setContentsMargins(0, 0, 0, 0)
        self.ask_before_run = ToggleSwitch(self.original.get("ask_before_run", False))
        self.ask_before_run.setAccessibleName("Спрашивать перед выполнением")
        self.ask_before_run.setToolTip("Дополнительное подтверждение всей команды. Подтверждения опасных действий сохраняются.")
        self.allow_chaining = ToggleSwitch(self.original.get("allow_chaining", True))
        self.allow_chaining.setAccessibleName("Связка с другими командами")
        self.allow_chaining.setToolTip("Разрешить выполнять эту команду в цепочке с другими командами.")
        for text, switch in (("Спрашивать перед выполнением", self.ask_before_run),
                             ("Связка с другими командами", self.allow_chaining)):
            row = QHBoxLayout()
            row.addWidget(_label(text), 1)
            row.addWidget(switch)
            advanced_options.addLayout(row)
        self.advanced_panel.hide()
        self.advanced_toggle.toggled.connect(self.advanced_panel.setVisible)
        advanced.addWidget(self.advanced_panel)
        main.addWidget(advanced_card)
        main.addStretch()

        self.sidebar, side = _card()
        self.sidebar.setFixedWidth(220)
        side.addLayout(_heading("Проверка команды"))
        side.addWidget(_label("Проверьте фразу перед сохранением.", "Muted"))
        self.test_phrase = QLineEdit()
        self.test_phrase.setPlaceholderText("Что вы скажете Jarvis?")
        side.addWidget(self.test_phrase)
        self.match_feedback = _label("Введите фразу для проверки.", "Muted")
        side.addWidget(self.match_feedback)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        side.addWidget(separator)
        self.readiness = _label("", "EditorSectionTitle")
        side.addWidget(self.readiness)
        self.phrase_count = _label("", "Muted")
        self.action_count = _label("", "Muted")
        side.addWidget(self.phrase_count)
        side.addWidget(self.action_count)
        self.trigger_summary = _label("", "Muted")
        side.addWidget(self.trigger_summary)
        self.run_button = QPushButton("Выполнить сейчас")
        set_button_icon(self.run_button, "play", role="accent")
        self.run_button.clicked.connect(self.run_draft)
        side.addWidget(self.run_button)
        side.addStretch()
        side.addWidget(_label("Проверка фразы не выполняет действия.", "Muted"))
        body.addWidget(self.sidebar)
        root.addLayout(body, 1)

        footer = QHBoxLayout()
        self.footer_status = _label("", "Muted")
        footer.addWidget(self.footer_status, 1)
        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.clicked.connect(self.reject)
        footer.addWidget(self.cancel_button)
        self.save_button = QPushButton("Сохранить команду")
        self.save_button.setObjectName("Primary")
        set_button_icon(self.save_button, "save", role="white")
        self.save_button.clicked.connect(self._validate_accept)
        footer.addWidget(self.save_button)
        footer.addWidget(QSizeGrip(self), 0, Qt.AlignmentFlag.AlignBottom)
        root.addLayout(footer)

        # Retain the old public controls for integrations; action rows now own
        # visible edit/move/remove buttons instead of a separate vertical rail.
        self.edit_button, self.up_button, self.down_button, self.delete_button = (QPushButton(self) for _ in range(4))
        for button in (self.edit_button, self.up_button, self.down_button, self.delete_button):
            button.hide()
        self.edit_button.clicked.connect(self.edit_action)
        self.up_button.clicked.connect(lambda: self.move_action(-1))
        self.down_button.clicked.connect(lambda: self.move_action(1))
        self.delete_button.clicked.connect(self.remove_action)
        self.record_timer = QTimer(self)
        self.record_timer.setInterval(100)
        self.record_timer.timeout.connect(self._check_recording)
        for field in (self.title_field, self.test_phrase):
            field.textChanged.connect(self._update_readiness)
        for chips in (self.phrase_chips, self.optional_chips):
            chips.changed.connect(self._update_readiness)
        for button in (self.voice_enabled, self.hotkey_toggle, self.schedule_toggle, self.event_toggle,
                       self.ask_before_run, self.allow_chaining, *self.weekday_buttons):
            button.toggled.connect(self._update_readiness)
        self.hotkey.keySequenceChanged.connect(self._update_readiness)
        self.schedule_mode.currentIndexChanged.connect(self._update_schedule_visibility)
        self.schedule_time.timeChanged.connect(self._update_readiness)
        self.schedule_date.dateChanged.connect(self._update_readiness)
        self.event_type.currentIndexChanged.connect(self._update_event_visibility)
        self.event_app.currentIndexChanged.connect(self._update_readiness)
        self._refresh_steps()
        self._update_schedule_visibility()
        self._update_event_visibility()
        ancestor = parent
        while ancestor is not None:
            config = getattr(ancestor, "cfg", None)
            if isinstance(config, dict):
                self._context_config = config
                break
            ancestor = ancestor.parentWidget()
        self.set_context(config=self._context_config)
        translate_widgets(self, get_ui_language())
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        self._sync_responsive_layout()

    def _phrase_row(self, text, tooltip, chips):
        row = QHBoxLayout()
        row.setSpacing(10)
        heading = QWidget()
        heading.setObjectName("EditorPlain")
        heading.setFixedWidth(122)
        layout = _heading(text, tooltip)
        layout.setContentsMargins(0, 7, 0, 0)
        heading.setLayout(layout)
        row.addWidget(heading, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(chips, 1)
        self._phrase_rows.append(row)
        return row

    def _sync_responsive_layout(self):
        if not hasattr(self, "sidebar"):
            return
        compact = self.width() <= 900
        if getattr(self, "_responsive_compact", None) == compact:
            return
        self._responsive_compact = compact
        direction = (QBoxLayout.Direction.TopToBottom if compact
                     else QBoxLayout.Direction.LeftToRight)
        for layout in (*self._phrase_rows, self._trigger_row,
                       self._hotkey_row, self._action_toolbar):
            layout.setDirection(direction)
        self.sidebar.setFixedWidth(190 if compact else 220)
        self.main_scroll.widget().layout().invalidate()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_responsive_layout()

    @staticmethod
    def _expander(text, layout, checked):
        button = QToolButton()
        button.setText(text)
        button.setObjectName("EditorExpander")
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        button.setCheckable(True)
        button.setChecked(checked)
        button.toggled.connect(lambda state: button.setArrowType(Qt.ArrowType.DownArrow if state else Qt.ArrowType.RightArrow))
        layout.addWidget(button)
        return button

    @staticmethod
    def _trigger_button(text, mark, checked):
        button = QPushButton(text)
        button.setObjectName("TriggerButton")
        button.setCheckable(True)
        button.setChecked(checked)
        set_button_icon(button, mark, size=16, role="muted")
        return button

    def _build_schedule(self):
        settings = self.original.get("schedule") or {}
        panel = QWidget()
        panel.setObjectName("EditorPlain")
        form = QFormLayout(panel)
        form.setContentsMargins(0, 3, 0, 0)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.schedule_mode = QComboBox()
        for label, mode in (("Ежедневно", "daily"), ("Один раз", "once"), ("По дням недели", "weekly")):
            self.schedule_mode.addItem(label, mode)
        self.schedule_mode.setCurrentIndex(max(0, self.schedule_mode.findData(settings.get("mode", "daily"))))
        form.addRow("Повтор", self.schedule_mode)
        self.schedule_time = QTimeEdit(QTime.fromString(settings.get("time", "09:00"), "HH:mm"))
        self.schedule_time.setDisplayFormat("HH:mm")
        form.addRow("Время", self.schedule_time)
        self.schedule_date = QDateEdit(QDate.fromString(settings.get("date", ""), Qt.DateFormat.ISODate))
        if not self.schedule_date.date().isValid() or not settings.get("date"):
            self.schedule_date.setDate(QDate.currentDate())
        self.schedule_date.setCalendarPopup(True)
        self.schedule_date.setDisplayFormat("yyyy-MM-dd")
        form.addRow("Дата", self.schedule_date)
        self.weekdays = QWidget()
        self.weekdays.setObjectName("EditorPlain")
        days = QHBoxLayout(self.weekdays)
        days.setContentsMargins(0, 0, 0, 0)
        days.setSpacing(4)
        self.weekday_buttons = []
        for day, label in enumerate(("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")):
            check = QCheckBox(label)
            check.setChecked(day in settings.get("weekdays", [0, 1, 2, 3, 4]))
            days.addWidget(check)
            self.weekday_buttons.append(check)
        form.addRow("Дни", self.weekdays)
        return panel

    def _build_event(self):
        settings = self.original.get("event") or {}
        panel = QWidget()
        panel.setObjectName("EditorPlain")
        row = QVBoxLayout(panel)
        row.setContentsMargins(0, 3, 0, 0)
        self.event_type = QComboBox()
        self.event_type.addItem("При запуске приложения", "app_started")
        self.event_type.addItem("При подключении наушников", "headphones_connected")
        self.event_type.setCurrentIndex(max(0, self.event_type.findData(settings.get("type"))))
        row.addWidget(self.event_type)
        self.event_app = QComboBox()
        for app in sorted(APP_TARGETS):
            self.event_app.addItem(APP_LABELS.get(app, app.title()), app)
        self.event_app.setCurrentIndex(max(0, self.event_app.findData(settings.get("app", "telegram"))))
        row.addWidget(self.event_app)
        return panel

    def _update_schedule_visibility(self, *_):
        form = self.schedule_panel.layout()
        once = self.schedule_mode.currentData() == "once"
        weekly = self.schedule_mode.currentData() == "weekly"
        self.schedule_date.setVisible(once)
        form.labelForField(self.schedule_date).setVisible(once)
        self.weekdays.setVisible(weekly)
        form.labelForField(self.weekdays).setVisible(weekly)
        self._update_readiness()

    def _update_event_visibility(self, *_):
        self.event_app.setVisible(self.event_type.currentData() == "app_started")
        self._update_readiness()

    def set_context(self, planner=None, config=None):
        if config is not None:
            self._context_config = config
        self._planner = planner
        cfg = self._context_config
        self.set_theme(cfg.get("ui_theme", "dark"), cfg.get("ui_accent", "#3978f6"), cfg.get("ui_background"))

    def set_theme(self, theme="dark", accent="#3978f6", background=None):
        p = theme_colors(theme, accent, background)
        self.setStyleSheet(f"""
QDialog#CommandEditorDialog {{ background: {p['bg']}; border: 1px solid {p['border']}; border-radius: 14px; }}
QWidget#EditorPlain, QWidget#CommandEditorBody, QScrollArea#CommandEditorScroll {{ background: transparent; border: none; }}
QFrame#CommandCard {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 12px; }}
QPushButton#Primary:disabled {{ background: {p["control"]}; color: {p["muted"]}; border: 1px solid {p["border"]}; }}
QLabel#EditorSectionTitle {{ font-size: 13px; font-weight: 600; }}
QLabel#Muted {{ color: {p['muted']}; font-size: 12px; }}
QToolButton#EditorExpander {{ border: none; background: transparent; padding: 2px 0; font-size: 13px; font-weight: 600; }}
QPushButton#EditorIconButton, QToolButton#EditorIconButton {{ border: none; background: transparent; padding: 4px; }}
QPushButton#PhraseChip {{ background: {p['selection']}; color: {p['text']}; border: 1px solid {p['border']}; padding: 5px 9px; border-radius: 9px; font-size: 12px; text-align: left; }}
QPushButton#TriggerButton {{ padding: 7px 5px; font-size: 11px; border-radius: 8px; }}
QPushButton#TriggerButton:checked {{ background: {p['selection']}; border-color: {p['accent']}; }}
QListWidget#CommandActionsList {{ background: transparent; border: none; padding: 0; }}
QListWidget#CommandActionsList::item {{ padding: 0; margin: 0; border: none; background: transparent; }}
QFrame#CommandActionRow {{ border: 1px solid {p['border']}; border-radius: 9px; background: {p['field']}; }}
QPushButton#ActionRowButton {{ padding: 3px; border: none; background: transparent; }}
QLabel#ActionNumber {{ color: {p['muted']}; font-size: 12px; }}
""")
        refresh_icons(self, theme, p["accent"])
        for switch in (self.voice_enabled, self.ask_before_run, self.allow_chaining):
            switch.set_theme(theme, p["accent"], background)

    def _refresh_steps(self, selected=None):
        self.actions_list.clear()
        for index, step in enumerate(self.steps):
            details = CATALOG[step["action"]]
            row = QFrame()
            row.setObjectName("CommandActionRow")
            layout = QHBoxLayout(row)
            layout.setContentsMargins(9, 8, 7, 8)
            layout.setSpacing(7)
            number = _label(str(index + 1), "ActionNumber")
            number.setFixedWidth(16)
            layout.addWidget(number)
            mark = QLabel()
            set_label_icon(mark, details["icon"], size=20, role="accent")
            layout.addWidget(mark)
            text = QVBoxLayout()
            text.setSpacing(3)
            title = _label(tr(details["title"]), "EditorSectionTitle")
            title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            text.addWidget(title)
            target = str(step.get("target", ""))
            description = _label(target[:72] + ("…" if len(target) > 72 else "") if target else tr(details["description"]), "Muted")
            description.setToolTip(target)
            description.setProperty("i18n_skip", bool(target))
            description.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            text.addWidget(description)
            layout.addLayout(text, 1)
            for mark_name, tooltip, callback, enabled in (
                ("arrow-up", "Выше", lambda: self.move_action(-1), index > 0),
                ("arrow-down", "Ниже", lambda: self.move_action(1), index < len(self.steps) - 1),
                ("pencil", "Изменить", self.edit_action, True),
                ("trash-2", "Удалить", self.remove_action, True),
            ):
                button = QPushButton()
                button.setObjectName("ActionRowButton")
                button.setFixedSize(25, 28)
                button.setToolTip(tr(tooltip))
                button.setAccessibleName(tr(tooltip))
                set_button_icon(button, mark_name, size=15, role="danger" if mark_name == "trash-2" else "muted")
                button.setEnabled(enabled)
                button.clicked.connect(lambda _checked=False, idx=index, action=callback: self._row_action(idx, action))
                layout.addWidget(button)
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 78))
            self.actions_list.addItem(item)
            self.actions_list.setItemWidget(item, row)
        if self._legacy:
            self.actions_list.addItem(tr("Старая сохранённая команда Steam: действие сохранено без изменений"))
        count = len(self.steps)
        self.actions_list.setFixedHeight(min(350, max(85, count * 88 + 8)))
        if selected is not None and 0 <= selected < count:
            self.actions_list.setCurrentRow(selected)
        elif count:
            self.actions_list.setCurrentRow(count - 1)
        self.empty_hint.setVisible(not count and not self._legacy)
        self.empty_hint.setMinimumHeight(55)
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.actions_list.setVisible(bool(count or self._legacy))
        self.counter.setText(f"{count or int(self._legacy)} / {self.MAX_ACTIONS}")
        self.add_button.setEnabled(count < self.MAX_ACTIONS and not self._legacy)
        self.record_button.setEnabled(count < self.MAX_ACTIONS and not self._legacy)
        self.ai_button.setEnabled(count < self.MAX_ACTIONS and not self._legacy and not self._ai_pending)
        self._update_buttons()
        self._update_readiness()

    def _row_action(self, index, callback):
        self.actions_list.setCurrentRow(index)
        callback()

    def _update_buttons(self, *_):
        index = self.actions_list.currentRow()
        selected = 0 <= index < len(self.steps)
        if not hasattr(self, "edit_button"):
            return
        self.edit_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)
        self.up_button.setEnabled(selected and index > 0)
        self.down_button.setEnabled(selected and index < len(self.steps) - 1)

    def add_action(self):
        if self._legacy or len(self.steps) >= self.MAX_ACTIONS:
            return
        picker = ActionPicker(self)
        if picker.exec() == QDialog.DialogCode.Accepted and picker.step:
            self.steps.append(validate_step(picker.step))
            self._refresh_steps(len(self.steps) - 1)

    def edit_action(self):
        index = self.actions_list.currentRow()
        if not 0 <= index < len(self.steps):
            return
        step = self.steps[index]
        dialog = ActionOptionsDialog(step["action"], step, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.data:
            self.steps[index] = validate_step(dialog.data)
            self._refresh_steps(index)

    def move_action(self, offset):
        index = self.actions_list.currentRow()
        dest = index + offset
        if 0 <= index < len(self.steps) and 0 <= dest < len(self.steps):
            self.steps[index], self.steps[dest] = self.steps[dest], self.steps[index]
            self._refresh_steps(dest)

    def remove_action(self):
        index = self.actions_list.currentRow()
        if 0 <= index < len(self.steps):
            self.steps.pop(index)
            self._refresh_steps(min(index, len(self.steps) - 1))

    def toggle_recording(self):
        if self._recorder is not None:
            self._finish_recording()
            return
        try:
            from luxai.command_recording import ActionRecorder
            recorder = ActionRecorder(max_actions=self.MAX_ACTIONS - len(self.steps),
                                      record_game_keys=self.record_game_keys.isChecked())
            started = recorder.start()
            if started is False or recorder.error:
                raise RuntimeError(recorder.error)
            self._recorder = recorder
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            self._feedback(str(exc))
            return
        self.record_button.setText(tr("Остановить запись"))
        set_button_icon(self.record_button, "square-stop", role="danger")
        self._feedback(tr("Запись: выполните действия в другом приложении. Esc или кнопка записи остановит запись."))
        self.record_timer.start()
        self.record_game_keys.setEnabled(False)
        self._update_readiness()

    def _check_recording(self):
        if self._recorder is not None and not self._recorder.active:
            self._finish_recording()

    def _finish_recording(self, append=True):
        recorder, self._recorder = self._recorder, None
        self.record_timer.stop()
        if recorder is None:
            return
        try:
            steps = [validate_step(step) for step in recorder.stop()]
            if append:
                self.steps.extend(steps[:self.MAX_ACTIONS - len(self.steps)])
                self._refresh_steps()
                self._feedback(recorder.error or tr("Запись завершена. Проверьте действия перед сохранением."))
        except (ValueError, TypeError, RuntimeError, OSError) as exc:
            self._feedback(str(exc))
        self.record_button.setText(tr("Записать"))
        self.record_game_keys.setEnabled(True)
        set_button_icon(self.record_button, "circle", role="danger")

    def request_ai(self):
        if self._legacy or self._ai_pending or len(self.steps) >= self.MAX_ACTIONS:
            return
        prompt, accepted = QInputDialog.getMultiLineText(self, tr("Действия с ИИ"), tr("Опишите, что должна сделать команда:"))
        if not accepted or not prompt.strip():
            return
        self._ai_prompt = prompt.strip()
        self._ai_pending = True
        self.ai_button.setEnabled(False)
        self._feedback(tr("ИИ подбирает действия…"))
        self.ai_requested.emit(self._ai_prompt, self)

    def apply_ai_result(self, plan=None, error=""):
        self._ai_pending = False
        if error:
            self._feedback(str(error))
            self._refresh_steps()
            return
        try:
            from luxai.macro_planner import validate_generated_macro
            validated = validate_generated_macro(plan, self._ai_prompt)
            if not validated:
                raise ValueError(tr("ИИ не предложил допустимых действий. Уточните задачу."))
            steps = [validate_step(step) for step in validated.get("steps", [])]
            if not steps or len(self.steps) + len(steps) > self.MAX_ACTIONS:
                raise ValueError(tr("В команде может быть не более 8 действий."))
            self.steps.extend(steps)
            self._feedback(tr("Действия добавлены. Проверьте их перед сохранением."))
        except (ValueError, TypeError, KeyError) as exc:
            self._feedback(str(exc))
        self._refresh_steps()

    def _feedback(self, message):
        self.action_feedback.setText(tr(message))
        self.action_feedback.setVisible(bool(message))

    def get_data(self):
        data = dict(self.original)
        if not (self._legacy and not self.steps):
            first = self.steps[0] if self.steps else {"action": "", "target": "", "location": "desktop"}
            data.update({"action": first["action"], "target": first["target"], "location": first["location"],
                         "steps": [dict(step) for step in self.steps]})
        data.update({
            "id": self.original.get("id"), "category": self.original.get("category", "Мои команды"),
            "title": self.title_field.text().strip(), "phrases": self.phrase_chips.get_values(),
            "optional_words": self.optional_chips.get_values(), "voice_enabled": self.voice_enabled.isChecked(),
            "hotkey": self.hotkey.keySequence().toString(QKeySequence.SequenceFormat.PortableText) if self.hotkey_toggle.isChecked() else "",
            "schedule": {}, "event": {}, "ask_before_run": self.ask_before_run.isChecked(),
            "allow_chaining": self.allow_chaining.isChecked(), "enabled": self.original.get("enabled", True),
            "learned": self.original.get("learned", False),
        })
        if self.schedule_toggle.isChecked():
            mode = self.schedule_mode.currentData()
            data["schedule"] = {"mode": mode, "time": self.schedule_time.time().toString("HH:mm")}
            if mode == "once":
                data["schedule"]["date"] = self.schedule_date.date().toString(Qt.DateFormat.ISODate)
            elif mode == "weekly":
                data["schedule"]["weekdays"] = [index for index, button in enumerate(self.weekday_buttons) if button.isChecked()]
        if self.event_toggle.isChecked():
            data["event"] = {"type": self.event_type.currentData()}
            if data["event"]["type"] == "app_started":
                data["event"]["app"] = self.event_app.currentData()
        return data

    def _validated_data(self):
        payload = self.get_data()
        payload["id"] = payload.get("id") or "user_preview"
        return checked_command(payload)

    def _update_readiness(self, *_):
        if not hasattr(self, "save_button"):
            return
        data = self.get_data()
        action_count = len(self.steps) or int(self._legacy)
        self.phrase_count.setText(tr("Фразы: {count}").format(count=len(data["phrases"])))
        self.action_count.setText(tr("Действия: {count}").format(count=action_count))
        ready = False
        try:
            self._validated_data()
            ready = True
        except (ValueError, TypeError):
            pass
        message = "Готово к запуску" if ready else "Добавьте название" if not data["title"] else "Добавьте действие" if not action_count else "Добавьте фразу" if data["voice_enabled"] and not data["phrases"] else "Проверьте настройки запуска"
        self.readiness.setText(tr(message))
        self.footer_status.setText(tr("Изменения ещё не сохранены."))
        self.save_button.setEnabled(ready and self._recorder is None)
        self.run_button.setEnabled(ready and self._recorder is None)
        triggers = []
        for enabled, name in ((data["voice_enabled"], "Голосом"), (data["hotkey"], "Сочетание клавиш"),
                              (data["schedule"], "По расписанию"), (data["event"], "По событию")):
            if enabled:
                triggers.append(tr(name))
        self.trigger_summary.setText(" · ".join(triggers))
        text = self.test_phrase.text().strip()
        if not text:
            self.match_feedback.setText(tr("Введите фразу для проверки."))
        elif not data["voice_enabled"]:
            self.match_feedback.setText(tr("Голосовой запуск выключен."))
        else:
            from luxai.command_registry import phrase_matches
            matched = phrase_matches(data, text, prefix=self._context_config.get("wake_prefix", "Jarvis"))
            self.match_feedback.setText(tr("Фраза подходит") if matched else tr("Фраза не подходит"))

    def run_draft(self):
        try:
            payload = self._validated_data()
        except (ValueError, TypeError) as exc:
            self._feedback(str(exc))
            return
        self.run_requested.emit(payload)

    def _validate_accept(self):
        try:
            self._validated_data()
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, tr("Ошибка команды"), tr(str(exc)))
            return
        self._finish_recording()
        self.accept()

    def done(self, result):
        self._finish_recording(append=False)
        super().done(result)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 100:
            handle = self.windowHandle()
            if handle is None or not handle.startSystemMove():
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event):
        self._finish_recording(append=False)
        super().closeEvent(event)
