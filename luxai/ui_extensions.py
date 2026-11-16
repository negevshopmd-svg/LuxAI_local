"""Extensions page (0.4.0): plugin tiles/list, topics, search and settings.

Presentation only. The page edits a normalized ``extensions`` state (see
``extensions_catalog.normalize_state``) and emits ``state_changed`` with a
copy; MainWindow persists it and hands it to ``ExtensionsRuntime``.
"""
from __future__ import annotations

import copy

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from luxai.extensions_catalog import (
    CATEGORIES, CONNECTIONS, PLUGINS, PLUGIN_BY_ID, Plugin, enabled_count, matches,
    normalize_state, text, ui, validate_value,
)
from luxai.icons import icon, set_button_icon
from luxai.ui_home import ToggleSwitch


class PluginIcon(QWidget):
    """Rounded colored tile with a white Lucide glyph."""

    def __init__(self, icon_name: str, color: str, size: int = 56, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.color = QColor(color)
        self.setFixedSize(size, size)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.color)
        radius = self.width() * 0.26
        painter.drawRoundedRect(self.rect(), radius, radius)
        glyph = int(self.width() * 0.5)
        offset = (self.width() - glyph) // 2
        icon(self.icon_name, color="#ffffff", size=glyph).paint(painter, offset, offset, glyph, glyph)


class StatusDot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(8, 8)
        self.color = QColor("#7c8696")

    def set_color(self, color: str):
        self.color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.color)
        painter.drawEllipse(self.rect())


class TopicButton(QPushButton):
    """Topic entry: title on the left, plugin count on the right."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ExtTopic")
        self.setMinimumHeight(38)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)
        self.title = QLabel()
        self.title.setObjectName("ExtTopicTitle")
        self.count = QLabel()
        self.count.setObjectName("ExtTopicCount")
        for label in (self.title, self.count):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            label.setProperty("i18n_skip", True)
        row.addWidget(self.title, 1)
        row.addWidget(self.count)

    def set_texts(self, title, count):
        self.title.setText(title)
        self.count.setText(str(count))
        self.setAccessibleName(f"{title} ({count})")


class PluginCard(QFrame):
    toggled = Signal(str, bool)
    configure = Signal(str)

    def __init__(self, plugin: Plugin, compact: bool = False, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.compact = compact
        self.setObjectName("ExtRow" if compact else "ExtCard")
        self.setProperty("i18n_skip", True)
        self.icon = PluginIcon(plugin.icon, plugin.color, 40 if compact else 56)
        self.switch = ToggleSwitch(False)
        self.switch.setAccessibleName(text(plugin.title, "ru"))
        self.switch.toggled.connect(lambda checked: self.toggled.emit(plugin.id, checked))
        self.title = QLabel()
        self.title.setObjectName("ExtTitle")
        self.badge = QLabel()
        self.badge.setObjectName("ExtBadge")
        self.description = QLabel()
        self.description.setObjectName("ExtDescription")
        self.description.setWordWrap(True)
        self.description.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.dot = StatusDot()
        self.status = QLabel()
        self.status.setObjectName("ExtStatus")
        self.button = QPushButton()
        self.button.setObjectName("ExtConfigure")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        set_button_icon(self.button, "sliders-horizontal", size=17)
        self.button.clicked.connect(lambda: self.configure.emit(plugin.id))
        for widget in (self.title, self.badge, self.description, self.status, self.button, self.switch):
            widget.setProperty("i18n_skip", True)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_row.addWidget(self.title)
        title_row.addWidget(self.badge)
        title_row.addStretch()
        status_row = QHBoxLayout()
        status_row.setSpacing(7)
        status_row.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.button)

        if compact:
            layout = QHBoxLayout(self)
            layout.setContentsMargins(14, 10, 14, 10)
            layout.setSpacing(14)
            layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignVCenter)
            middle = QVBoxLayout()
            middle.setSpacing(3)
            middle.addLayout(title_row)
            middle.addWidget(self.description)
            self.description.setMaximumHeight(36)
            layout.addLayout(middle, 1)
            right = QVBoxLayout()
            right.setSpacing(6)
            right.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignRight)
            right.addLayout(status_row)
            layout.addLayout(right)
        else:
            layout = QVBoxLayout(self)
            layout.setContentsMargins(16, 16, 16, 14)
            layout.setSpacing(8)
            top = QHBoxLayout()
            top.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
            top.addStretch()
            top.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignTop)
            layout.addLayout(top)
            layout.addSpacing(4)
            layout.addLayout(title_row)
            layout.addWidget(self.description, 1)
            layout.addLayout(status_row)
            self.setMinimumHeight(228)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def render(self, entry: dict, language: str, theme_args: tuple, error: str = ""):
        plugin = self.plugin
        self.title.setText(text(plugin.title, language))
        self.description.setText(text(plugin.description, language))
        self.description.setToolTip(text(plugin.description, language))
        self.badge.setText(ui("soon", language))
        self.badge.setVisible(not plugin.ready)
        self.button.setText(ui("configure", language))
        enabled = bool(entry.get("enabled"))
        self.switch.blockSignals(True)
        self.switch.setChecked(enabled)
        self.switch.blockSignals(False)
        self.switch.setEnabled(plugin.ready)
        self.switch.set_theme(*theme_args)
        tip = text(plugin.title, language) if plugin.ready else ui("soon_hint", language)
        self.switch.setToolTip(tip)
        self.switch.setAccessibleName(text(plugin.title, language))
        if error and enabled:
            status, color = error, "#e5a54b"
        elif not plugin.ready:
            status, color = ui("soon_status", language), "#7c8696"
        elif enabled:
            status, color = ui("on", language), "#32b87a"
        else:
            status, color = ui("off", language), "#7c8696"
        self.status.setText(status)
        self.status.setToolTip(status)
        self.dot.set_color(color)


class SettingsDialog(QDialog):
    """Form generated from a plugin's settings schema."""

    def __init__(self, plugin: Plugin, entry: dict, language: str, runtime=None, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.language = language
        self.runtime = runtime
        self.result_settings = None
        self.setObjectName("ExtSettingsDialog")
        self.setProperty("i18n_skip", True)
        self.setWindowTitle(ui("settings_of", language, name=text(plugin.title, language)))
        self.setMinimumWidth(520)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 18)
        outer.setSpacing(12)
        header = QHBoxLayout()
        header.setSpacing(14)
        header.addWidget(PluginIcon(plugin.icon, plugin.color, 48))
        titles = QVBoxLayout()
        name = QLabel(text(plugin.title, language))
        name.setObjectName("ExtTitle")
        titles.addWidget(name)
        about = QLabel(text(plugin.description, language))
        about.setObjectName("ExtDescription")
        about.setWordWrap(True)
        titles.addWidget(about)
        header.addLayout(titles, 1)
        outer.addLayout(header)
        if not plugin.ready:
            note = QLabel(ui("soon_hint", language))
            note.setObjectName("ExtNote")
            note.setWordWrap(True)
            outer.addWidget(note)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        self.fields = {}
        values = entry.get("settings", {})
        for setting in plugin.settings:
            widget = self._make_field(setting, values.get(setting.key, setting.default))
            self.fields[setting.key] = widget
            label = QLabel(text(setting.label, language))
            label.setWordWrap(True)
            if setting.hint:
                holder = QWidget()
                column = QVBoxLayout(holder)
                column.setContentsMargins(0, 0, 0, 0)
                column.setSpacing(3)
                column.addWidget(widget)
                hint = QLabel(text(setting.hint, language))
                hint.setObjectName("Muted")
                hint.setWordWrap(True)
                column.addWidget(hint)
                form.addRow(label, holder)
            else:
                form.addRow(label, widget)
        outer.addLayout(form)
        if plugin.actions and plugin.ready and runtime is not None:
            actions = QHBoxLayout()
            actions.setSpacing(8)
            for action_id, label in plugin.actions:
                button = QPushButton(text(label, language))
                button.clicked.connect(lambda checked=False, a=action_id: self._run_action(a))
                actions.addWidget(button)
            actions.addStretch()
            outer.addLayout(actions)
        self.error = QLabel()
        self.error.setObjectName("ExtError")
        self.error.setWordWrap(True)
        self.error.hide()
        outer.addWidget(self.error)
        buttons = QHBoxLayout()
        reset = QPushButton(ui("reset", language))
        reset.clicked.connect(self._reset)
        buttons.addWidget(reset)
        buttons.addStretch()
        cancel = QPushButton(ui("cancel", language))
        cancel.clicked.connect(self.reject)
        save = QPushButton(ui("save", language))
        save.setObjectName("Primary")
        save.setDefault(True)
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        outer.addLayout(buttons)
        for widget in self.findChildren(QWidget):
            widget.setProperty("i18n_skip", True)

    def _make_field(self, setting, value):
        language = self.language
        if setting.kind == "bool":
            widget = QCheckBox()
            widget.setChecked(bool(value))
        elif setting.kind == "choice":
            widget = QComboBox()
            for option, label in setting.options:
                widget.addItem(text(label, language), option)
            index = widget.findData(value)
            widget.setCurrentIndex(max(0, index))
        elif setting.kind == "int":
            widget = QSpinBox()
            widget.setRange(setting.minimum, setting.maximum)
            widget.setValue(int(value))
            if setting.suffix:
                widget.setSuffix(text(setting.suffix, language))
        elif setting.kind == "multiline":
            widget = QPlainTextEdit()
            widget.setPlainText(str(value))
            widget.setMinimumHeight(110)
        elif setting.kind == "folder":
            widget = QWidget()
            row = QHBoxLayout(widget)
            row.setContentsMargins(0, 0, 0, 0)
            line = QLineEdit(str(value))
            browse = QPushButton(ui("browse", language))

            def choose(line=line):
                chosen = QFileDialog.getExistingDirectory(self, text(setting.label, language), line.text())
                if chosen:
                    line.setText(chosen)

            browse.clicked.connect(choose)
            row.addWidget(line, 1)
            row.addWidget(browse)
            widget.line = line
        else:  # text, hotkey
            widget = QLineEdit(str(value))
            if setting.kind == "hotkey":
                widget.setPlaceholderText("Ctrl+Alt+…")
                widget.setText("+".join(part.capitalize() for part in str(value).split("+")) if value else "")
            widget.setMaxLength(setting.max_length)
        return widget

    def _raw_value(self, setting):
        widget = self.fields[setting.key]
        if setting.kind == "bool":
            return widget.isChecked()
        if setting.kind == "choice":
            return widget.currentData()
        if setting.kind == "int":
            return widget.value()
        if setting.kind == "multiline":
            return widget.toPlainText()
        if setting.kind == "folder":
            return widget.line.text()
        return widget.text()

    def collect(self) -> dict:
        values = {}
        problems = []
        for setting in self.plugin.settings:
            try:
                values[setting.key] = validate_value(setting, self._raw_value(setting))
            except ValueError as error:
                problems.append(f"{text(setting.label, self.language)}: {error}")
        hotkeys = [values[s.key] for s in self.plugin.settings if s.kind == "hotkey" and values.get(s.key)]
        if len(hotkeys) != len(set(hotkeys)):
            problems.append(ui("hotkey_error", self.language))
        if problems:
            raise ValueError("\n".join(problems))
        return values

    def _set_value(self, setting, value):
        widget = self.fields[setting.key]
        if setting.kind == "bool":
            widget.setChecked(bool(value))
        elif setting.kind == "choice":
            widget.setCurrentIndex(max(0, widget.findData(value)))
        elif setting.kind == "int":
            widget.setValue(int(value))
        elif setting.kind == "multiline":
            widget.setPlainText(str(value))
        elif setting.kind == "folder":
            widget.line.setText(str(value))
        else:
            widget.setText(str(value))

    def _reset(self):
        for setting in self.plugin.settings:
            self._set_value(setting, setting.default)

    def _show_error(self, message):
        self.error.setText(message)
        self.error.setVisible(bool(message))

    def _save(self):
        try:
            self.result_settings = self.collect()
        except ValueError as error:
            self._show_error(str(error))
            return
        self.accept()

    def _run_action(self, action_id):
        try:
            values = self.collect()
        except ValueError as error:
            self._show_error(str(error))
            return
        self._show_error("")
        self.runtime.run_action(self.plugin.id, action_id, parent=self, settings=values)


class ConnectionCard(QFrame):
    configure = Signal(str)

    def __init__(self, connection, parent=None):
        super().__init__(parent)
        self.connection = connection
        identifier, icon_name, _, users, _ = connection
        self.setObjectName("ExtRow")
        self.setProperty("i18n_skip", True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)
        layout.addWidget(PluginIcon(icon_name, PLUGIN_BY_ID[users[0]].color, 40))
        column = QVBoxLayout()
        self.name = QLabel()
        self.name.setObjectName("ExtTitle")
        self.used = QLabel()
        self.used.setObjectName("ExtDescription")
        column.addWidget(self.name)
        column.addWidget(self.used)
        layout.addLayout(column, 1)
        self.dot = StatusDot()
        self.status = QLabel()
        self.status.setObjectName("ExtStatus")
        layout.addWidget(self.dot)
        layout.addWidget(self.status)
        self.button = QPushButton()
        self.button.setObjectName("ExtConfigure")
        set_button_icon(self.button, "sliders-horizontal", size=17)
        self.button.clicked.connect(lambda: self.configure.emit(users[0]))
        layout.addWidget(self.button)
        for widget in self.findChildren(QWidget):
            widget.setProperty("i18n_skip", True)

    def render(self, state, language):
        identifier, _, title, users, field = self.connection
        self.name.setText(text(title, language))
        self.used.setText(ui("used_by", language, names=", ".join(text(PLUGIN_BY_ID[u].title, language) for u in users)))
        configured = bool(state.get(users[0], {}).get("settings", {}).get(field))
        self.status.setText(ui("connected" if configured else "not_connected", language))
        self.dot.set_color("#32b87a" if configured else "#7c8696")
        self.button.setText(ui("configure", language))


class ExtensionsPage(QWidget):
    state_changed = Signal(dict)

    def __init__(self, state=None, runtime=None, parent=None):
        super().__init__(parent)
        self.setObjectName("ExtensionsPage")
        self.runtime = runtime
        self.state = normalize_state(state)
        self.language = "ru"
        self.view = "tiles"
        self.theme_args = ("dark", "#3978f6", None)
        self.hotkey_errors: dict[str, str] = {}
        self.cards: dict[str, PluginCard] = {}
        self.sections: dict[str, tuple[QLabel, QWidget]] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.tab_group = QButtonGroup(self)
        self.plugins_tab = QPushButton()
        self.connections_tab = QPushButton()
        for index, (button, icon_name) in enumerate(((self.plugins_tab, "layers"), (self.connections_tab, "link"))):
            button.setObjectName("ExtTab")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(40)
            button.setProperty("i18n_skip", True)
            set_button_icon(button, icon_name, size=18)
            self.tab_group.addButton(button, index)
            top.addWidget(button)
        self.plugins_tab.setChecked(True)
        self.tab_group.idClicked.connect(self._switch_tab)
        top.addStretch()
        self.view_frame = QFrame()
        self.view_frame.setObjectName("PreferenceSegments")
        view_row = QHBoxLayout(self.view_frame)
        view_row.setContentsMargins(3, 3, 3, 3)
        view_row.setSpacing(2)
        self.view_group = QButtonGroup(self)
        self.tiles_button = QPushButton()
        self.list_button = QPushButton()
        for index, (button, icon_name) in enumerate(((self.tiles_button, "layout-grid"), (self.list_button, "list"))):
            button.setObjectName("PreferenceSegment")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(29)
            button.setProperty("i18n_skip", True)
            set_button_icon(button, icon_name, size=16)
            self.view_group.addButton(button, index)
            view_row.addWidget(button)
        self.tiles_button.setChecked(True)
        self.tiles_button.setProperty("selected", True)
        self.view_group.idClicked.connect(lambda index: self.set_view("tiles" if index == 0 else "list"))
        top.addWidget(self.view_frame)
        top.addSpacing(8)
        outer.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(16)
        self.stack = QStackedWidget()
        self.stack.setObjectName("ExtStack")
        body.addWidget(self.stack, 1)

        # Plugins list
        self.scroll = QScrollArea()
        self.scroll.setObjectName("ExtScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content.setObjectName("ExtContent")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 10, 10)
        self.content_layout.setSpacing(12)
        self.scroll.setWidget(self.content)
        self.scroll.verticalScrollBar().valueChanged.connect(self._sync_topic_from_scroll)
        self.scroll.viewport().installEventFilter(self)
        self.stack.addWidget(self.scroll)

        # Connections list
        connections = QWidget()
        connections.setObjectName("ExtContent")
        column = QVBoxLayout(connections)
        column.setContentsMargins(0, 0, 10, 0)
        column.setSpacing(10)
        self.connections_intro = QLabel()
        self.connections_intro.setObjectName("Muted")
        self.connections_intro.setWordWrap(True)
        self.connections_intro.setProperty("i18n_skip", True)
        column.addWidget(self.connections_intro)
        self.connection_cards = []
        for connection in CONNECTIONS:
            card = ConnectionCard(connection)
            card.configure.connect(self.open_settings)
            column.addWidget(card)
            self.connection_cards.append(card)
        column.addStretch()
        self.stack.addWidget(connections)

        # Right panel
        side = QFrame()
        side.setObjectName("ExtSide")
        side.setFixedWidth(240)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(12, 12, 12, 12)
        side_layout.setSpacing(4)
        self.search = QLineEdit()
        self.search.setObjectName("ExtSearch")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icon("search", color="#94a3b8"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(lambda: self.rebuild())
        self.search.setProperty("i18n_skip", True)
        side_layout.addWidget(self.search)
        side_layout.addSpacing(10)
        self.topics_label = QLabel()
        self.topics_label.setObjectName("SettingsGroupLabel")
        self.topics_label.setProperty("i18n_skip", True)
        side_layout.addWidget(self.topics_label)
        self.topic_buttons: dict[str, QPushButton] = {}
        for identifier, _ in CATEGORIES:
            button = TopicButton()
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setProperty("i18n_skip", True)
            button.clicked.connect(lambda checked=False, c=identifier: self.scroll_to(c))
            side_layout.addWidget(button)
            self.topic_buttons[identifier] = button
        side_layout.addStretch()
        self.only_enabled = QCheckBox()
        self.only_enabled.setProperty("i18n_skip", True)
        self.only_enabled.toggled.connect(lambda: self.rebuild())
        side_layout.addWidget(self.only_enabled)
        self.counter = QLabel()
        self.counter.setObjectName("ExtCounter")
        self.counter.setProperty("i18n_skip", True)
        side_layout.addWidget(self.counter)
        body.addWidget(side)
        outer.addLayout(body, 1)

        self._columns = 2
        self._active_topic = CATEGORIES[0][0]
        self.rebuild()

    # -- public API --
    def set_language(self, language: str):
        self.language = language if language in ("ru", "en", "ro") else "ru"
        self.rebuild()

    def set_theme(self, theme, accent="#3978f6", background=None):
        self.theme_args = (theme, accent, background)
        for card in self.cards.values():
            card.switch.set_theme(*self.theme_args)

    def set_hotkey_errors(self, errors: dict):
        mapped = {}
        for name, message in (errors or {}).items():
            mapped.setdefault(str(name).partition(".")[0], message)
        if mapped != self.hotkey_errors:
            self.hotkey_errors = mapped
            self._render_cards()

    def set_view(self, view: str):
        self.view = "list" if view == "list" else "tiles"
        for button, name in ((self.tiles_button, "tiles"), (self.list_button, "list")):
            selected = self.view == name
            button.setChecked(selected)
            button.setProperty("selected", selected)
            button.style().unpolish(button)
            button.style().polish(button)
        self.rebuild()

    def current_state(self) -> dict:
        return copy.deepcopy(self.state)

    # -- building --
    def _visible_plugins(self):
        query = self.search.text()
        only = self.only_enabled.isChecked()
        return [plugin for plugin in PLUGINS
                if matches(plugin, query, self.language)
                and (not only or self.state[plugin.id]["enabled"])]

    def rebuild(self):
        language = self.language
        self.plugins_tab.setText(f"{ui('plugins', language)}  {len(PLUGINS)}")
        self.connections_tab.setText(ui("connections", language))
        self.tiles_button.setText(ui("tiles", language))
        self.list_button.setText(ui("list", language))
        self.search.setPlaceholderText(ui("search", language))
        self.topics_label.setText(ui("topics", language))
        self.only_enabled.setText(ui("only_enabled", language))
        self.connections_intro.setText(ui("connections_intro", language))
        for button in (self.plugins_tab, self.connections_tab):
            selected = button.isChecked()
            button.setProperty("selected", selected)
            button.style().unpolish(button)
            button.style().polish(button)

        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.cards.clear()
        self.sections.clear()
        visible = self._visible_plugins()
        counts = {identifier: 0 for identifier, _ in CATEGORIES}
        for plugin in visible:
            counts[plugin.category] += 1
        for identifier, title in CATEGORIES:
            plugins = [plugin for plugin in visible if plugin.category == identifier]
            button = self.topic_buttons[identifier]
            button.set_texts(text(title, language), counts[identifier])
            button.setToolTip(f"{text(title, language)} ({counts[identifier]})")
            button.setEnabled(bool(plugins))
            if not plugins:
                continue
            heading = QLabel(f"{text(title, language)} ({len(plugins)})")
            heading.setObjectName("ExtSection")
            heading.setProperty("i18n_skip", True)
            self.content_layout.addWidget(heading)
            holder = QWidget()
            holder.setObjectName("ExtContent")
            grid = QGridLayout(holder)
            grid.setContentsMargins(0, 0, 0, 6)
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(12)
            columns = self._columns if self.view == "tiles" else 1
            for index, plugin in enumerate(plugins):
                card = PluginCard(plugin, compact=self.view == "list")
                card.toggled.connect(self._on_toggled)
                card.configure.connect(self.open_settings)
                grid.addWidget(card, index // columns, index % columns)
                self.cards[plugin.id] = card
            for column in range(columns):
                grid.setColumnStretch(column, 1)
            self.content_layout.addWidget(holder)
            self.sections[identifier] = (heading, holder)
        if not visible:
            empty = QLabel(ui("nothing", language))
            empty.setObjectName("Muted")
            empty.setProperty("i18n_skip", True)
            self.content_layout.addWidget(empty)
        self.content_layout.addStretch()
        self._render_cards()
        for card in self.connection_cards:
            card.render(self.state, language)
        self._update_topic_buttons()

    def _render_cards(self):
        for plugin_id, card in self.cards.items():
            card.render(self.state[plugin_id], self.language, self.theme_args, self.hotkey_errors.get(plugin_id, ""))
        self.counter.setText(ui("enabled_count", self.language, n=enabled_count(self.state), total=len(PLUGINS)))

    def _update_topic_buttons(self):
        for identifier, button in self.topic_buttons.items():
            active = identifier == self._active_topic
            if button.property("active") != active:
                button.setProperty("active", active)
                button.style().unpolish(button)
                button.style().polish(button)
                for label in (button.title, button.count):
                    label.setProperty("active", active)
                    label.style().unpolish(label)
                    label.style().polish(label)

    def eventFilter(self, watched, event):
        if watched is self.scroll.viewport() and event.type() == QEvent.Type.Resize:
            columns = 1 if self.scroll.viewport().width() < 600 else 2
            if columns != self._columns:
                self._columns = columns
                QTimer.singleShot(0, self, self.rebuild)
        return super().eventFilter(watched, event)

    # -- behaviour --
    def _switch_tab(self, index):
        self.stack.setCurrentIndex(index)
        self.view_frame.setVisible(index == 0)
        self.rebuild()

    def scroll_to(self, category: str):
        section = self.sections.get(category)
        if section is None:
            return
        self._active_topic = category
        self.scroll.verticalScrollBar().setValue(section[0].y())
        self._update_topic_buttons()

    def _sync_topic_from_scroll(self, value):
        current = None
        for identifier, (heading, _) in self.sections.items():
            if heading.y() <= value + 40:
                current = identifier
        bar = self.scroll.verticalScrollBar()
        if value >= bar.maximum() and self.sections:
            current = list(self.sections)[-1]
        if current and current != self._active_topic:
            self._active_topic = current
            self._update_topic_buttons()

    def _on_toggled(self, plugin_id, checked):
        plugin = PLUGIN_BY_ID[plugin_id]
        if not plugin.ready:
            checked = False
        self.state[plugin_id]["enabled"] = bool(checked)
        self._commit()
        if self.only_enabled.isChecked() and not checked:
            QTimer.singleShot(0, self, self.rebuild)

    def open_settings(self, plugin_id):
        plugin = PLUGIN_BY_ID[plugin_id]
        dialog = SettingsDialog(plugin, self.state[plugin_id], self.language, self.runtime, self.window())
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_settings is not None:
            self.state[plugin_id]["settings"] = dialog.result_settings
            self._commit()
        elif self.runtime is not None:
            # Actions in the dialog may have applied unsaved values; restore.
            self.runtime.apply(copy.deepcopy(self.state))
        return dialog

    def _commit(self):
        self.state = normalize_state(self.state)
        self._render_cards()
        for card in self.connection_cards:
            card.render(self.state, self.language)
        self.state_changed.emit(copy.deepcopy(self.state))


def show_error(parent, title, message):  # pragma: no cover - thin helper
    QMessageBox.warning(parent, title, message)
