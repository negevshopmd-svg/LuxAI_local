"""In-page plugin settings (Luxify-style), shown inside the Extensions page.

Layout: section cards on the left (basic on/off first, then the plugin's
sections, then actions or a live "Проверка" area), and a right panel with
"How it works", section navigation, "Reset all" and "Save". Edits stay a
draft until Save; the page emits ``saved`` with (enabled, settings).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from luxai.extensions_catalog import (
    BASIC_ACTIONS, BASIC_KEYS, BASIC_LAST, BASIC_NOTE, BASIC_TEXT, HIDDEN_SETTINGS, VOICE_HELP, ENABLED_IF, L, Plugin, how_it_works, sections_for, text, ui, validate_value,
)
from luxai.icons import set_button_icon, set_label_icon
from luxai.ui_home import ToggleSwitch

W = {
    "basic": L("Основные", "Basic", "De bază"),
    "basic_sub": L("Включение и как это работает.", "Turning it on and how it works.", "Pornire și cum funcționează."),
    "how": L("Как это работает", "How it works", "Cum funcționează"),
    "reset_all": L("Сбросить всё", "Reset all", "Resetează tot"),
    "assign": L("Назначить", "Assign", "Atribuie"),
    "press_keys": L("Нажмите сочетание клавиш…  Esc — отмена, Backspace — очистить.",
                    "Press a key combination…  Esc — cancel, Backspace — clear.",
                    "Apasă combinația…  Esc — anulare, Backspace — golește."),
    "actions": L("Действия", "Actions", "Acțiuni"),
    "actions_sub": L("Запустить модуль вручную.", "Run the module manually.", "Rulează modulul manual."),
    "check": L("Проверка", "Check", "Verificare"),
    "check_sub": L("Попробуйте диктовку здесь, не выходя из настроек.", "Try dictation here without leaving settings.",
                   "Încearcă dictarea aici, fără să ieși din setări."),
    "check_row": L("Проверить диктовку", "Test dictation", "Testează dictarea"),
    "check_off": L("Диктовка выключена. Включите её и нажмите «Сохранить» — тогда проверка заработает.",
                   "Dictation is off. Turn it on and press Save — then the test works.",
                   "Dictarea e oprită. Pornește-o și apasă Salvează — apoi testul funcționează."),
    "check_on": L("Щёлкните в поле, нажмите клавишу диктовки и скажите фразу.",
                  "Click the field, press the dictation key and say a phrase.",
                  "Fă clic în câmp, apasă tasta de dictare și spune o frază."),
    "check_placeholder": L("Щёлкните сюда, нажмите клавишу диктовки и скажите фразу",
                           "Click here, press the dictation key and say a phrase",
                           "Fă clic aici, apasă tasta de dictare și spune o frază"),
    "clear": L("Очистить", "Clear", "Golește"),
    "last": L("Последняя диктовка", "Last dictation", "Ultima dictare"),
    "last_hint": L("Хранится только пока программа запущена, на диск не пишется.",
                   "Kept only while the app runs; never written to disk.",
                   "Se păstrează doar cât rulează aplicația; nu se scrie pe disc."),
    "copy": L("Копировать", "Copy", "Copiază"),
    "nothing": L("Пока ничего не продиктовано.", "Nothing dictated yet.", "Nimic dictat încă."),
    "enabled": L("Включена.", "On.", "Activată."),
    "disabled": L("Выключена.", "Off.", "Dezactivată."),
    "soon": L("В разработке.", "In development.", "În dezvoltare."),
    "secret_saved": L("•••••••• сохранён — введите новый, чтобы заменить", "•••••••• saved — type a new one to replace",
                       "•••••••• salvat — scrie unul nou ca să-l înlocuiești"),
    "secret_empty": L("Вставьте токен", "Paste the token", "Lipește tokenul"),
    "pc_connected": L("Подключено", "Connected", "Conectat"),
    "pc_checked": L("Токен рабочий", "Token works", "Tokenul funcționează"),
    "pc_connecting": L("Подключаюсь…", "Connecting…", "Mă conectez…"),
    "pc_checking": L("Проверяю…", "Checking…", "Verific…"),
    "pc_retrying": L("Нет связи, повторяю…", "No connection, retrying…", "Fără conexiune, reîncerc…"),
    "pc_error": L("Ошибка", "Error", "Eroare"),
    "pc_stopped": L("Остановлен", "Stopped", "Oprit"),
    "pc_bot": L("Бот: {name} (@{username})", "Bot: {name} (@{username})", "Bot: {name} (@{username})"),
    "pc_main_menu": L("Главное меню", "Main menu", "Meniul principal"),
    "pc_refresh": L("Обновить", "Refresh", "Reîmprospătează"),
    "active": L("Активные", "Active", "Active"),
    "active_sub": L("Таймеры и будильники, которые сейчас идут.", "Timers and alarms that are running now.",
                    "Cronometrele și alarmele care rulează acum."),
    "no_timers": L("Сейчас ничего не запущено.", "Nothing is running right now.", "Nimic nu rulează acum."),
    "add_timer": L("Таймер", "Timer", "Cronometru"),
    "add_timer_hint": L("Запустить на столько минут.", "Start for this many minutes.", "Pornește pentru atâtea minute."),
    "start": L("Запустить", "Start", "Pornește"),
    "add_alarm": L("Будильник", "Alarm", "Alarmă"),
    "add_alarm_hint": L("Ближайшее такое время: сегодня или завтра.", "The next such time: today or tomorrow.",
                        "Următoarea astfel de oră: azi sau mâine."),
    "set": L("Поставить", "Set", "Setează"),
    "timers_off": L("Включите модуль и сохраните — тогда таймеры заработают.",
                    "Turn the module on and save — then timers work.",
                    "Pornește modulul și salvează — apoi cronometrele funcționează."),
    "video_card": L("Компонент для видео", "Video component", "Componenta video"),
    "video_sub": L("FFmpeg: звук, видео, GIF и WebP.", "FFmpeg: audio, video, GIF and WebP.", "FFmpeg: sunet, video, GIF și WebP."),
    "video_ready": L("Встроен ({version}) — ничего скачивать не нужно.", "Built in ({version}) — nothing to download.",
                     "Inclus ({version}) — nu trebuie descărcat nimic."),
    "video_missing": L("Не найден. Запустите Update.bat — он восстановит компонент.", "Not found. Run Update.bat to restore it.",
                       "Nu a fost găsit. Rulează Update.bat ca să-l restaurezi."),
    "apps": L("Программы", "Apps", "Aplicații"),
    "apps_sub": L("Чьи уведомления читать. Список пополняется сам, когда программа присылает уведомление.",
                  "Whose notifications to read. The list grows by itself when an app sends a notification.",
                  "Ale cui notificări le citesc. Lista se completează singură când o aplicație trimite o notificare."),
    "apps_empty": L("Пока ни одна программа не присылала уведомлений. Включите плагин — список пополнится сам. "
                    "По умолчанию читаются все программы, кроме системных — лишние можно выключить.",
                    "No app has sent a notification yet. Turn the plugin on — the list fills by itself. "
                    "Every app except system ones is read by default — switch off what you don't need.",
                    "Nicio aplicație n-a trimis încă notificări. Pornește pluginul — lista se completează singură. "
                    "Implicit se citesc toate aplicațiile, în afară de cele de sistem — oprește ce nu-ți trebuie."),
    "apps_refresh": L("Обновить список", "Refresh the list", "Reîmprospătează lista"),
    "example": L("Пример", "Example", "Exemplu"),
    "unsaved": L("Есть несохранённые изменения.", "There are unsaved changes.", "Există modificări nesalvate."),
}


def w(key, language):
    return text(W[key], language)


class KeyCaptureDialog(QDialog):
    """Read one shortcut from a key press (Qt events, no global hooks)."""

    def __init__(self, language, parent=None):
        super().__init__(parent)
        self.result_value = None
        self.setWindowTitle(w("assign", language))
        self.setProperty("i18n_skip", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        label = QLabel(w("press_keys", language))
        label.setWordWrap(True)
        layout.addWidget(label)
        self.preview = QLabel("…")
        self.preview.setObjectName("ExtKeyChip")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.preview)
        self.resize(360, 130)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.reject()
            return
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self.result_value = ""
            self.accept()
            return
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift, Qt.Key.Key_Meta, Qt.Key.Key_AltGr):
            return
        modifiers = event.modifiers()
        parts = []
        for flag, name in ((Qt.KeyboardModifier.ControlModifier, "ctrl"), (Qt.KeyboardModifier.AltModifier, "alt"),
                           (Qt.KeyboardModifier.ShiftModifier, "shift"), (Qt.KeyboardModifier.MetaModifier, "win")):
            if modifiers & flag:
                parts.append(name)
        name = QKeySequence(key).toString().casefold()
        if not name:
            return
        parts.append(name)
        self.result_value = "+".join(parts)
        self.preview.setText("+".join(part.capitalize() for part in parts))
        QTimer.singleShot(150, self.accept)


class Segmented(QFrame):
    changed = Signal()

    def __init__(self, options, language, parent=None):
        super().__init__(parent)
        self.setObjectName("PreferenceSegments")
        row = QHBoxLayout(self)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)
        self.group = QButtonGroup(self)
        self.values = []
        for index, (value, label) in enumerate(options):
            button = QPushButton(text(label, language))
            button.setObjectName("PreferenceSegment")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(30)
            button.setProperty("i18n_skip", True)
            self.group.addButton(button, index)
            row.addWidget(button)
            self.values.append(value)
        self.group.idClicked.connect(lambda _: (self._sync(), self.changed.emit()))

    def value(self):
        index = self.group.checkedId()
        return self.values[index] if index >= 0 else self.values[0]

    def set_value(self, value):
        index = self.values.index(value) if value in self.values else 0
        self.group.button(index).setChecked(True)
        self._sync()

    def _sync(self):
        for index, button in enumerate(self.group.buttons()):
            selected = button.isChecked()
            if button.property("selected") != selected:
                button.setProperty("selected", selected)
                button.style().unpolish(button)
                button.style().polish(button)


class SliderField(QWidget):
    changed = Signal()

    def __init__(self, setting, language, parent=None):
        super().__init__(parent)
        self.suffix = text(setting.suffix, language) if setting.suffix else ""
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(setting.minimum, setting.maximum)
        self.slider.setMinimumWidth(170)
        self.pill = QLabel()
        self.pill.setObjectName("SettingsSliderValue")
        self.pill.setMinimumWidth(52)
        self.pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.slider, 1)
        row.addWidget(self.pill)
        self.slider.valueChanged.connect(self._update)

    def _update(self, value):
        self.pill.setText(f"{value}{self.suffix}")
        self.changed.emit()

    def value(self):
        return self.slider.value()

    def set_value(self, value):
        self.slider.setValue(int(value))
        self.pill.setText(f"{int(value)}{self.suffix}")


class HotkeyField(QWidget):
    changed = Signal()

    def __init__(self, language, parent=None):
        super().__init__(parent)
        self.language = language
        self._value = ""
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.chip = QLabel()
        self.chip.setObjectName("ExtKeyChip")
        self.assign = QPushButton(w("assign", language))
        self.assign.setObjectName("ExtConfigure")
        self.assign.setCursor(Qt.CursorShape.PointingHandCursor)
        self.assign.clicked.connect(self._capture)
        row.addStretch()
        row.addWidget(self.chip)
        row.addWidget(self.assign)

    def _capture(self):
        dialog = KeyCaptureDialog(self.language, self.window())
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_value is not None:
            self.set_value(dialog.result_value)
            self.changed.emit()

    def value(self):
        return self._value

    def set_value(self, value):
        self._value = str(value or "")
        self.chip.setText("+".join(part.capitalize() for part in self._value.split("+")) if self._value else "—")


class SecretField(QWidget):
    """Password-style field with an eye toggle. Empty = keep the saved secret."""
    changed = Signal()

    def __init__(self, setting, language, saved: bool, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.line = QLineEdit()
        self.line.setEchoMode(QLineEdit.EchoMode.Password)
        self.line.setMaxLength(setting.max_length)
        self.line.setMinimumWidth(280)
        self.line.textChanged.connect(self.changed.emit)
        from luxai.icons import icon
        self.eye = self.line.addAction(icon("eye", color="#94a3b8"), QLineEdit.ActionPosition.TrailingPosition)
        self.eye.triggered.connect(self._toggle)
        row.addWidget(self.line)
        self.set_saved(saved, language)

    def _toggle(self):
        hidden = self.line.echoMode() == QLineEdit.EchoMode.Password
        self.line.setEchoMode(QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)

    def set_saved(self, saved: bool, language: str):
        self.line.setPlaceholderText(w("secret_saved" if saved else "secret_empty", language))

    def value(self):
        return self.line.text().strip()

    def set_value(self, value):
        self.line.setText(str(value or ""))


class FolderField(QWidget):
    changed = Signal()

    def __init__(self, setting, language, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.line = QLineEdit()
        self.line.textChanged.connect(self.changed.emit)
        browse = QPushButton(ui("browse", language))
        browse.clicked.connect(lambda: self._choose(text(setting.label, language)))
        row.addWidget(self.line, 1)
        row.addWidget(browse)

    def _choose(self, title):
        chosen = QFileDialog.getExistingDirectory(self, title, self.line.text())
        if chosen:
            self.line.setText(chosen)

    def value(self):
        return self.line.text()

    def set_value(self, value):
        self.line.setText(str(value))


def _row(title, hint, control, *, wide=False):
    """A label/hint column with the control on the right (or below)."""
    row = QFrame()
    row.setObjectName("ExtSettingRow")
    layout = QVBoxLayout(row) if wide else QHBoxLayout(row)
    layout.setContentsMargins(0, 12, 0, 12)
    layout.setSpacing(14 if not wide else 8)
    texts = QVBoxLayout()
    texts.setSpacing(3)
    label = QLabel(title)
    label.setObjectName("ExtRowTitle")
    label.setWordWrap(True)
    texts.addWidget(label)
    hint_label = None
    if hint:
        hint_label = QLabel(hint)
        hint_label.setObjectName("ExtRowHint")
        hint_label.setWordWrap(True)
        texts.addWidget(hint_label)
    if wide:
        layout.addLayout(texts)
        layout.addWidget(control)
    else:
        layout.addLayout(texts, 1)
        layout.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
    row.title_label = label
    row.hint_label = hint_label
    return row


class SectionCard(QFrame):
    reset_requested = Signal(str)

    def __init__(self, section_id, icon_name, title, subtitle, *, resettable=True, parent=None):
        super().__init__(parent)
        self.section_id = section_id
        self.setObjectName("ExtCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 8)
        layout.setSpacing(0)
        head = QHBoxLayout()
        head.setSpacing(14)
        mark = QLabel()
        mark.setObjectName("ExtSectionIcon")
        mark.setFixedSize(38, 38)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setProperty("jarvisIconBoxSize", 38)
        set_label_icon(mark, icon_name, size=19)
        head.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
        column = QVBoxLayout()
        column.setSpacing(2)
        heading = QLabel(title)
        heading.setObjectName("ExtTitle")
        column.addWidget(heading)
        sub = QLabel(subtitle)
        sub.setObjectName("ExtRowHint")
        sub.setWordWrap(True)
        column.addWidget(sub)
        head.addLayout(column, 1)
        if resettable:
            reset = QPushButton()
            reset.setObjectName("ExtIconButton")
            reset.setFixedSize(32, 32)
            reset.setCursor(Qt.CursorShape.PointingHandCursor)
            set_button_icon(reset, "rotate-ccw", size=17, role="muted")
            reset.clicked.connect(lambda: self.reset_requested.emit(section_id))
            head.addWidget(reset, 0, Qt.AlignmentFlag.AlignTop)
            self.reset_button = reset
        layout.addLayout(head)
        layout.addSpacing(8)
        self.rows = layout

    def add_row(self, row):
        self.rows.addWidget(row)


class PluginSettingsView(QWidget):
    saved = Signal(str, bool, dict)
    closed = Signal()

    def __init__(self, plugin: Plugin, entry: dict, language: str, runtime=None, theme_args=None, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.language = language
        self.runtime = runtime
        self.theme_args = theme_args or ("dark", "#3978f6", None)
        self.saved_enabled = bool(entry.get("enabled"))
        self.saved_settings = dict(entry.get("settings", {}))
        self.fields: dict[str, QWidget] = {}
        self.rows: dict[str, QFrame] = {}
        self.cards: dict[str, SectionCard] = {}
        self.setObjectName("ExtSettingsView")
        self.setProperty("i18n_skip", True)

        body = QHBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("ExtScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("ExtContent")
        self.column = QVBoxLayout(content)
        self.column.setContentsMargins(0, 0, 10, 10)
        self.column.setSpacing(14)
        self.scroll.setWidget(content)
        self.scroll.verticalScrollBar().valueChanged.connect(self._sync_nav)
        body.addWidget(self.scroll, 1)

        if plugin.id not in BASIC_LAST:
            self._build_basic()
        has_status_row = False
        if plugin.id == "timers":
            self._build_timers_card()
        if plugin.id == "notification_reader":
            self._build_apps_card()
        for key in HIDDEN_SETTINGS.get(plugin.id, ()):
            field = QPlainTextEdit()
            field.hide()
            field.textChanged.connect(self._refresh)
            self.fields[key] = field
        for section in sections_for(plugin):
            card = SectionCard(section.id, section.icon, text(section.title, language), text(section.subtitle, language))
            card.reset_requested.connect(self.reset_section)
            if section.groups:
                self._add_switch_grid(card, section)
            if self.plugin.id in VOICE_HELP and section.id == "voice":
                help_note = QLabel(text(VOICE_HELP[self.plugin.id], language))
                help_note.setObjectName("ExtNote")
                help_note.setWordWrap(True)
                card.add_row(help_note)
            for key in (() if section.groups else section.keys):
                if key == "@status":
                    self._add_status_row(card)
                    has_status_row = True
                    continue
                setting = next(item for item in plugin.settings if item.key == key)
                self._add_setting(card, setting)
            self.cards[section.id] = card
            self.column.addWidget(card)
            if plugin.id == "converter" and section.id == "sectors":
                self._build_video_card()
        if plugin.id == "smart_dictation":
            self._build_dictation_check()
        elif (plugin.actions and plugin.ready and runtime is not None and not has_status_row
              and plugin.id not in BASIC_ACTIONS):
            self._build_actions()
        if plugin.id in BASIC_LAST:
            self._build_basic()
        self.column.addStretch()

        # Right panel
        side = QFrame()
        side.setObjectName("ExtSide")
        side.setFixedWidth(240)
        panel = QVBoxLayout(side)
        panel.setContentsMargins(12, 12, 12, 12)
        panel.setSpacing(4)
        how = QFrame()
        how.setObjectName("ExtHowBox")
        how_layout = QVBoxLayout(how)
        how_layout.setContentsMargins(12, 10, 12, 12)
        how_layout.setSpacing(8)
        caption = QLabel(w("how", language))
        caption.setObjectName("ExtRowHint")
        how_layout.addWidget(caption)
        self.how_chip = QLabel()
        self.how_chip.setObjectName("ExtKeyChip")
        chip_row = QHBoxLayout()
        chip_row.addWidget(self.how_chip)
        chip_row.addStretch()
        how_layout.addLayout(chip_row)
        self.how_text = QLabel()
        self.how_text.setWordWrap(True)
        self.how_text.setObjectName("ExtHowText")
        how_layout.addWidget(self.how_text)
        if plugin.id == "pc_control":
            caption.hide()
            self.how_chip.hide()
            self.how_text.hide()
            self._build_bot_preview(how_layout)
        how.setSizePolicy(how.sizePolicy().horizontalPolicy(), how.sizePolicy().Policy.Minimum)
        panel.addWidget(how)
        panel.addSpacing(8)
        nav_area = QScrollArea()
        nav_area.setObjectName("ExtScroll")
        nav_area.setWidgetResizable(True)
        nav_area.setFrameShape(QFrame.Shape.NoFrame)
        nav_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        nav_holder = QWidget()
        nav_holder.setObjectName("ExtContent")
        nav_layout = QVBoxLayout(nav_holder)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(4)
        nav_area.setWidget(nav_holder)
        self.nav: dict[str, QPushButton] = {}
        for card_id, card in self.cards.items():
            button = QPushButton(card.findChild(QLabel, "ExtTitle").text())
            button.setObjectName("ExtNav")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            icon_name = {"basic": "bell" if plugin.id == "notification_reader" else "power", "check": "mic",
                         "actions": "play", "active": "hourglass", "video": "download", "apps": "list-checks"}.get(card_id) or next(
                (s.icon for s in sections_for(plugin) if s.id == card_id), "sliders-horizontal")
            set_button_icon(button, icon_name, size=17)
            button.clicked.connect(lambda checked=False, c=card_id: self.scroll_to(c))
            nav_layout.addWidget(button)
            self.nav[card_id] = button
        nav_layout.addStretch()
        panel.addWidget(nav_area, 1)
        self.message = QLabel()
        self.message.setObjectName("ExtRowHint")
        self.message.setWordWrap(True)
        panel.addWidget(self.message)
        self.reset_all_button = QPushButton(w("reset_all", language))
        set_button_icon(self.reset_all_button, "rotate-ccw", size=16)
        self.reset_all_button.clicked.connect(self.reset_all)
        panel.addWidget(self.reset_all_button)
        self.save_button = QPushButton(ui("save", language))
        self.save_button.setObjectName("Primary")
        self.save_button.setMinimumHeight(40)
        self.save_button.clicked.connect(self.save)
        panel.addWidget(self.save_button)
        body.addWidget(side)

        for key, value in self.saved_settings.items():
            if key in self.fields:
                self._set_value(key, value)
        self.enable_switch.setChecked(self.saved_enabled)
        if hasattr(self, "apps_holder"):
            self._render_apps()
        self._active_nav = ""
        self._set_active_nav(next(iter(self.cards)))
        self._refresh()
        for widget in self.findChildren(QWidget):
            widget.setProperty("i18n_skip", True)

    # -- building --
    def _build_basic(self):
        language = self.language
        card = SectionCard("basic", "bell" if self.plugin.id == "notification_reader" else "power",
                           w("basic", language), w("basic_sub", language), resettable=False)
        title, hint = BASIC_TEXT.get(self.plugin.id, (self.plugin.title, self.plugin.description))
        self.enable_switch = ToggleSwitch(False)
        self.enable_switch.set_theme(*self.theme_args)
        self.enable_switch.setEnabled(self.plugin.ready)
        self.enable_switch.toggled.connect(self._refresh)
        card.add_row(_row(text(title, language), text(hint, language), self.enable_switch))
        status = QWidget()
        status.setObjectName("ExtContent")
        status_row = QHBoxLayout(status)
        status_row.setContentsMargins(0, 10, 0, 10)
        from luxai.ui_extensions import StatusDot
        self.status_dot = StatusDot()
        self.status_label = QLabel()
        self.status_label.setObjectName("ExtStatus")
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_label, 1)
        separator = QFrame()
        separator.setObjectName("ExtSettingRow")
        separator_layout = QVBoxLayout(separator)
        separator_layout.setContentsMargins(0, 0, 0, 0)
        separator_layout.addWidget(status)
        card.add_row(separator)
        if self.plugin.id in BASIC_NOTE:
            note = QLabel(text(BASIC_NOTE[self.plugin.id], language))
            note.setObjectName("ExtNote")
            note.setWordWrap(True)
            card.add_row(note)
        for key in BASIC_KEYS.get(self.plugin.id, ()):
            setting = next(item for item in self.plugin.settings if item.key == key)
            self._add_setting(card, setting)
        for action_id in BASIC_ACTIONS.get(self.plugin.id, ()):
            label = next(text(item[1], language) for item in self.plugin.actions if item[0] == action_id)
            button = QPushButton(label)
            button.setObjectName("Primary")
            set_button_icon(button, "play", size=16, role="white")
            button.setEnabled(self.runtime is not None)
            button.clicked.connect(lambda checked=False, a=action_id: self._run_action(a))
            sample = ""
            if self.plugin.id == "notification_reader" and self.runtime is not None:
                sample = "«" + self.runtime.NOTIFICATION_SAMPLE.get(language, "") + "»"
            card.add_row(_row(w("example", language), sample, button))
        if not self.plugin.ready:
            note = QLabel(ui("soon_hint", language))
            note.setObjectName("ExtNote")
            note.setWordWrap(True)
            card.add_row(note)
        self.cards["basic"] = card
        self.column.addWidget(card)

    def _add_setting(self, card, setting):
        language = self.language
        kind = setting.kind
        wide = False
        if kind == "bool":
            field = ToggleSwitch(False)
            field.set_theme(*self.theme_args)
            field.toggled.connect(self._refresh)
        elif kind == "choice":
            short = len(setting.options) <= 3 and sum(len(text(label, language)) for _, label in setting.options) <= 48
            if short:
                field = Segmented(setting.options, language)
                field.changed.connect(self._refresh)
            else:
                field = QComboBox()
                field.setMinimumWidth(260)
                for value, label in setting.options:
                    field.addItem(text(label, language), value)
                field.currentIndexChanged.connect(self._refresh)
        elif kind == "int":
            if setting.maximum - setting.minimum <= 120:
                field = SliderField(setting, language)
                field.changed.connect(self._refresh)
            else:
                field = QSpinBox()
                field.setRange(setting.minimum, setting.maximum)
                if setting.suffix:
                    field.setSuffix(text(setting.suffix, language))
                field.setMinimumWidth(140)
                field.valueChanged.connect(self._refresh)
        elif kind == "hotkey":
            field = HotkeyField(language)
            field.changed.connect(self._refresh)
        elif kind == "secret":
            saved = bool(self.runtime is not None and self.runtime.has_secret(self.plugin.id, setting.key))
            field = SecretField(setting, language, saved)
            field.changed.connect(self._refresh)
        elif kind == "folder":
            field = FolderField(setting, language)
            field.changed.connect(self._refresh)
            wide = True
        elif kind == "multiline":
            field = QPlainTextEdit()
            field.setMinimumHeight(110)
            field.textChanged.connect(self._refresh)
            wide = True
        else:
            field = QLineEdit()
            field.setMaxLength(setting.max_length)
            field.setMinimumWidth(260)
            field.textChanged.connect(self._refresh)
        hint = text(setting.hint, language) if setting.hint else ""
        row = _row(text(setting.label, language), hint, field, wide=wide)
        card.add_row(row)
        self.fields[setting.key] = field
        self.rows[setting.key] = row

    def _add_status_row(self, card):
        """Connection state with the plugin's action buttons (PC Control)."""
        from luxai.ui_extensions import StatusDot
        holder = QFrame()
        holder.setObjectName("ExtSettingRow")
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 12, 0, 12)
        row.setSpacing(10)
        column = QVBoxLayout()
        column.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(7)
        self.pc_dot = StatusDot()
        self.pc_label = QLabel()
        self.pc_label.setObjectName("ExtRowTitle")
        top.addWidget(self.pc_dot)
        top.addWidget(self.pc_label, 1)
        column.addLayout(top)
        self.pc_detail = QLabel()
        self.pc_detail.setObjectName("ExtRowHint")
        self.pc_detail.setWordWrap(True)
        column.addWidget(self.pc_detail)
        row.addLayout(column, 1)
        for action_id, label in self.plugin.actions:
            button = QPushButton(text(label, self.language))
            button.setObjectName("ExtConfigure")
            set_button_icon(button, "refresh-cw" if action_id == "check" else "external-link", size=16)
            button.setEnabled(self.runtime is not None)
            button.clicked.connect(lambda checked=False, a=action_id: self._run_action(a))
            row.addWidget(button)
        card.add_row(holder)
        if self.runtime is not None:
            self.runtime.pc_status_changed.connect(self._show_pc_status)
            self._show_pc_status(*self.runtime.pc_state)
        else:
            self._show_pc_status("stopped", {})

    def _show_pc_status(self, state, details):
        try:
            language = self.language
            colors = {"connected": "#32b87a", "checked": "#32b87a", "error": "#e26675",
                      "retrying": "#e5a54b", "connecting": "#6f9df5", "checking": "#6f9df5"}
            self.pc_dot.set_color(colors.get(state, "#7c8696"))
            self.pc_label.setText(w("pc_" + state, language) if ("pc_" + state) in W else state)
            if details.get("username"):
                detail = w("pc_bot", language).format(name=details.get("name", ""), username=details["username"])
            else:
                detail = str(details.get("message", ""))
            self.pc_detail.setText(detail)
            self.pc_detail.setVisible(bool(detail))
            self._refresh_bot_preview()
        except RuntimeError:
            pass

    def _build_bot_preview(self, layout):
        head = QHBoxLayout()
        head.setSpacing(8)
        avatar = QLabel()
        avatar.setFixedSize(26, 26)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet("background:#21a366;border-radius:13px;")
        from luxai.icons import icon
        avatar.setPixmap(icon("send", color="#ffffff", size=14).pixmap(14, 14))
        head.addWidget(avatar)
        self.preview_name = QLabel()
        self.preview_name.setObjectName("ExtRowTitle")
        head.addWidget(self.preview_name, 1)
        layout.addLayout(head)
        self.preview_menu = QVBoxLayout()
        self.preview_menu.setSpacing(5)
        layout.addLayout(self.preview_menu)
        self._refresh_bot_preview()

    def _refresh_bot_preview(self):
        if not hasattr(self, "preview_menu"):
            return
        name, folders = self.runtime.pc_menu_preview() if self.runtime is not None else ("Jarvis", [])
        self.preview_name.setText(name)
        while self.preview_menu.count():
            item = self.preview_menu.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        chips = [("ExtKeyChip", w("pc_main_menu", self.language))]
        chips += [("ExtPreviewButton", folder) for folder in folders[:6]]
        chips.append(("ExtPreviewButton", "⟳ " + w("pc_refresh", self.language)))
        for name_, label_text in chips:
            label = QLabel(label_text)
            label.setObjectName(name_)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter if name_ != "ExtKeyChip" else Qt.AlignmentFlag.AlignLeft)
            label.setProperty("i18n_skip", True)
            if name_ == "ExtKeyChip":
                self.preview_menu.addWidget(label, 0, Qt.AlignmentFlag.AlignLeft)
            else:
                self.preview_menu.addWidget(label)

    def _build_timers_card(self):
        from PySide6.QtCore import QTime
        from PySide6.QtWidgets import QTimeEdit
        language = self.language
        card = SectionCard("active", "hourglass", w("active", language), w("active_sub", language), resettable=False)
        self.timer_rows = QVBoxLayout()
        self.timer_rows.setContentsMargins(0, 0, 0, 0)
        self.timer_rows.setSpacing(0)
        holder = QWidget()
        holder.setObjectName("ExtContent")
        holder.setLayout(self.timer_rows)
        card.add_row(holder)
        self.timer_minutes = QSpinBox()
        self.timer_minutes.setRange(1, 1440)
        self.timer_minutes.setValue(10)
        self.timer_minutes.setSuffix(text(L(" мин", " min", " min"), language))
        start = QPushButton(w("start", language))
        start.setObjectName("ExtConfigure")
        start.clicked.connect(self._quick_timer)
        quick = QWidget()
        quick.setObjectName("ExtContent")
        quick_row = QHBoxLayout(quick)
        quick_row.setContentsMargins(0, 0, 0, 0)
        quick_row.addWidget(self.timer_minutes)
        quick_row.addWidget(start)
        self.timer_add_row = _row(w("add_timer", language), w("add_timer_hint", language), quick)
        card.add_row(self.timer_add_row)
        self.alarm_time = QTimeEdit(QTime(7, 0))
        self.alarm_time.setDisplayFormat("HH:mm")
        set_alarm = QPushButton(w("set", language))
        set_alarm.setObjectName("ExtConfigure")
        set_alarm.clicked.connect(self._quick_alarm)
        alarm = QWidget()
        alarm.setObjectName("ExtContent")
        alarm_row = QHBoxLayout(alarm)
        alarm_row.setContentsMargins(0, 0, 0, 0)
        alarm_row.addWidget(self.alarm_time)
        alarm_row.addWidget(set_alarm)
        self.alarm_add_row = _row(w("add_alarm", language), w("add_alarm_hint", language), alarm)
        card.add_row(self.alarm_add_row)
        self.cards["active"] = card
        self.column.addWidget(card)
        self._countdowns = []
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._tick_countdowns)
        self._countdown_timer.start()
        if self.runtime is not None:
            self.runtime.timers_changed.connect(self._render_timers)
        self._render_timers()

    def _render_timers(self):
        try:
            rows = self.timer_rows
        except RuntimeError:
            return
        while rows.count():
            item = rows.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._countdowns = []
        timers = self.runtime.active_timers() if self.runtime is not None else []
        if not timers:
            empty = QLabel(w("no_timers", self.language))
            empty.setObjectName("ExtRowHint")
            empty.setContentsMargins(0, 10, 0, 10)
            rows.addWidget(empty)
            return
        import datetime as _dt
        for timer in timers:
            countdown = QLabel()
            countdown.setObjectName("ExtKeyChip")
            cancel = QPushButton()
            cancel.setObjectName("ExtIconButton")
            cancel.setFixedSize(30, 30)
            set_button_icon(cancel, "x", size=16, role="muted")
            cancel.clicked.connect(lambda checked=False, i=timer.id: self.runtime.cancel_timer(i))
            control = QWidget()
            control.setObjectName("ExtContent")
            control_row = QHBoxLayout(control)
            control_row.setContentsMargins(0, 0, 0, 0)
            control_row.addWidget(countdown)
            control_row.addWidget(cancel)
            hint = "" if timer.kind == "timer" else _dt.datetime.fromtimestamp(timer.due).strftime("%d.%m %H:%M")
            row = _row(self.runtime._describe(timer), hint, control)
            rows.addWidget(row)
            self._countdowns.append((timer, countdown))
        self._tick_countdowns()

    def _tick_countdowns(self):
        from luxai.timers import format_countdown
        try:
            for timer, label in self._countdowns:
                label.setText(format_countdown(timer.remaining()))
        except RuntimeError:
            pass

    def _quick_timer(self):
        if self.runtime is None or not self.saved_enabled:
            self.message.setText(w("timers_off", self.language))
            return
        self.message.setText(self.runtime.add_timer("timer", seconds=self.timer_minutes.value() * 60))

    def _quick_alarm(self):
        import datetime as _dt
        if self.runtime is None or not self.saved_enabled:
            self.message.setText(w("timers_off", self.language))
            return
        now = _dt.datetime.now()
        value = self.alarm_time.time()
        at = now.replace(hour=value.hour(), minute=value.minute(), second=0, microsecond=0)
        if at <= now:
            at += _dt.timedelta(days=1)
        self.message.setText(self.runtime.add_timer("alarm", at=at))

    def _add_switch_grid(self, card, section):
        """Group titles with a two-column grid of compact switches (Luxify sectors)."""
        from PySide6.QtWidgets import QGridLayout
        holder = QWidget()
        holder.setObjectName("ExtContent")
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 6, 0, 10)
        column.setSpacing(4)
        for title, keys in section.groups:
            heading = QLabel(text(title, self.language))
            heading.setObjectName("ExtGroupLabel")
            column.addWidget(heading)
            grid = QGridLayout()
            grid.setHorizontalSpacing(28)
            grid.setVerticalSpacing(2)
            for index, key in enumerate(keys):
                setting = next(item for item in self.plugin.settings if item.key == key)
                cell = QWidget()
                cell.setObjectName("ExtContent")
                row = QHBoxLayout(cell)
                row.setContentsMargins(0, 0, 0, 0)
                label = QLabel(text(setting.label, self.language))
                label.setObjectName("ExtGridLabel")
                switch = ToggleSwitch(False)
                switch.set_theme(*self.theme_args)
                switch.toggled.connect(self._refresh)
                row.addWidget(label, 1)
                row.addWidget(switch)
                grid.addWidget(cell, index // 2, index % 2)
                self.fields[key] = switch
                self.rows[key] = cell
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            column.addLayout(grid)
            column.addSpacing(6)
        card.add_row(holder)

    def _build_video_card(self):
        from luxai.converter import ffmpeg_version
        language = self.language
        card = SectionCard("video", "download", w("video_card", language), w("video_sub", language), resettable=False)
        version = ffmpeg_version()
        from luxai.ui_extensions import StatusDot
        holder = QFrame()
        holder.setObjectName("ExtSettingRow")
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 12, 0, 12)
        dot = StatusDot()
        dot.set_color("#32b87a" if version else "#e26675")
        label = QLabel(w("video_ready", language).format(version=version) if version else w("video_missing", language))
        label.setObjectName("ExtRowHint")
        label.setWordWrap(True)
        row.addWidget(dot)
        row.addWidget(label, 1)
        card.add_row(holder)
        self.cards["video"] = card
        self.column.addWidget(card)

    def _build_apps_card(self):
        language = self.language
        card = SectionCard("apps", "list-checks", w("apps", language), w("apps_sub", language))
        card.reset_requested.connect(lambda _id: self._set_rules({}))
        self.apps_holder = QVBoxLayout()
        self.apps_holder.setContentsMargins(0, 0, 0, 0)
        self.apps_holder.setSpacing(0)
        holder = QWidget()
        holder.setObjectName("ExtContent")
        holder.setLayout(self.apps_holder)
        card.add_row(holder)
        refresh = QPushButton(w("apps_refresh", language))
        set_button_icon(refresh, "refresh-cw", size=16)
        refresh.clicked.connect(self._render_apps)
        row = QHBoxLayout()
        row.setContentsMargins(0, 10, 0, 10)
        row.addWidget(refresh)
        row.addStretch()
        wrapper = QWidget()
        wrapper.setObjectName("ExtContent")
        wrapper.setLayout(row)
        card.add_row(wrapper)
        self.cards["apps"] = card
        self.column.addWidget(card)
        if self.runtime is not None:
            self.runtime.notification_apps_changed.connect(self._render_apps)

    def _rules(self):
        from luxai.notifications import parse_rules
        return parse_rules(self._raw("app_rules")) if "app_rules" in self.fields else {}

    def _set_rules(self, rules):
        from luxai.notifications import format_rules
        self._set_value("app_rules", format_rules(rules))
        self._render_apps()
        self._refresh()

    def _render_apps(self):
        from luxai.notifications import app_allowed
        try:
            layout = self.apps_holder
        except RuntimeError:
            return
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        rules = self._rules()
        apps = sorted(set(rules) | set(getattr(self.runtime, "seen_notification_apps", set()) or set()), key=str.casefold)
        if not apps:
            note = QLabel(w("apps_empty", self.language))
            note.setObjectName("ExtNote")
            note.setWordWrap(True)
            layout.addWidget(note)
            return
        for app in apps:
            switch = ToggleSwitch(app_allowed(app, rules))
            switch.set_theme(*self.theme_args)

            def toggled(checked, app=app):
                current = self._rules()
                current[app] = bool(checked)
                from luxai.notifications import format_rules
                self._set_value("app_rules", format_rules(current))
                self._refresh()

            switch.toggled.connect(toggled)
            layout.addWidget(_row(app, "", switch))

    def _build_actions(self):
        language = self.language
        card = SectionCard("actions", "play", w("actions", language), w("actions_sub", language), resettable=False)
        holder = QWidget()
        holder.setObjectName("ExtContent")
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 12, 0, 12)
        row.setSpacing(8)
        for action_id, label in self.plugin.actions:
            button = QPushButton(text(label, language))
            button.clicked.connect(lambda checked=False, a=action_id: self._run_action(a))
            row.addWidget(button)
        row.addStretch()
        card.add_row(holder)
        self.cards["actions"] = card
        self.column.addWidget(card)

    def _build_dictation_check(self):
        language = self.language
        card = SectionCard("check", "mic", w("check", language), w("check_sub", language), resettable=False)
        clear = QPushButton(w("clear", language))
        clear.setObjectName("ExtConfigure")
        self.check_row = _row(w("check_row", language), w("check_off", language), clear)
        card.add_row(self.check_row)
        self.test_box = QPlainTextEdit()
        self.test_box.setObjectName("ExtTestBox")
        self.test_box.setPlaceholderText(w("check_placeholder", language))
        self.test_box.setFixedHeight(96)
        clear.clicked.connect(self.test_box.clear)
        card.add_row(self.test_box)
        copy_button = QPushButton(w("copy", language))
        copy_button.setObjectName("ExtConfigure")
        set_button_icon(copy_button, "copy", size=16)
        copy_button.clicked.connect(self._copy_last)
        last_row = _row(w("last", language), w("last_hint", language), copy_button)
        card.add_row(last_row)
        self.last_label = QLabel()
        self.last_label.setObjectName("ExtRowHint")
        self.last_label.setWordWrap(True)
        self.last_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card.add_row(self.last_label)
        self.cards["check"] = card
        self.column.addWidget(card)
        if self.runtime is not None:
            self.runtime.test_sink = self._test_sink
            if hasattr(self.runtime, "dictation_done"):
                self.runtime.dictation_done.connect(self._show_last)
        self._show_last(getattr(self.runtime, "last_dictation", "") if self.runtime is not None else "")

    def _test_sink(self, value):
        """Dictation lands in the test box when it has focus inside Jarvis."""
        try:
            if self.isVisible() and self.test_box.hasFocus():
                self.test_box.insertPlainText(value)
                return True
        except RuntimeError:
            pass
        return False

    def _show_last(self, value):
        try:
            self.last_label.setText(value or w("nothing", self.language))
        except RuntimeError:
            pass

    def _copy_last(self):
        if self.runtime is not None:
            self.runtime.copy_last_dictation()

    # -- values --
    def _raw(self, key):
        field = self.fields[key]
        if isinstance(field, (ToggleSwitch,)):
            return field.isChecked()
        if isinstance(field, (Segmented, SliderField, HotkeyField, FolderField, SecretField)):
            return field.value()
        if isinstance(field, QComboBox):
            return field.currentData()
        if isinstance(field, QSpinBox):
            return field.value()
        if isinstance(field, QPlainTextEdit):
            return field.toPlainText()
        return field.text()

    def _set_value(self, key, value):
        field = self.fields[key]
        setting = next(item for item in self.plugin.settings if item.key == key)
        field.blockSignals(True)
        try:
            if isinstance(field, ToggleSwitch):
                field.setChecked(bool(value))
            elif isinstance(field, (Segmented, SliderField, HotkeyField, FolderField, SecretField)):
                field.set_value(value)
            elif isinstance(field, QComboBox):
                field.setCurrentIndex(max(0, field.findData(value)))
            elif isinstance(field, QSpinBox):
                field.setValue(int(value))
            elif isinstance(field, QPlainTextEdit):
                field.setPlainText(str(value))
            else:
                field.setText(str(value))
        finally:
            field.blockSignals(False)
        if setting.kind == "hotkey" and isinstance(field, HotkeyField):
            field.set_value(value)

    def _plain_settings(self):
        return [setting for setting in self.plugin.settings if setting.kind != "secret"]

    def _secret_settings(self):
        return [setting for setting in self.plugin.settings if setting.kind == "secret"]

    def draft(self) -> dict:
        return {setting.key: self._raw(setting.key) for setting in self._plain_settings()}

    def collect(self) -> dict:
        values, problems = {}, []
        for setting in self._plain_settings():
            try:
                values[setting.key] = validate_value(setting, self._raw(setting.key))
            except ValueError as error:
                problems.append(f"{text(setting.label, self.language)}: {error}")
        hotkeys = [values[s.key] for s in self.plugin.settings if s.kind == "hotkey" and values.get(s.key)]
        if len(hotkeys) != len(set(hotkeys)):
            problems.append(ui("hotkey_error", self.language))
        if problems:
            raise ValueError("\n".join(problems))
        return values

    @property
    def dirty(self) -> bool:
        if self.enable_switch.isChecked() != self.saved_enabled:
            return True
        if any(self._raw(setting.key) for setting in self._secret_settings()):
            return True
        return self.draft() != {key: self.saved_settings.get(key) for key in self.draft()}

    def _refresh(self, *_):
        draft = self.draft()
        for key, (other, allowed) in ENABLED_IF.get(self.plugin.id, {}).items():
            active = draft.get(other) in allowed
            row = self.rows.get(key)
            if row is not None:
                row.setEnabled(active)
        enabled = self.enable_switch.isChecked()
        if not self.plugin.ready:
            label, color = w("soon", self.language), "#7c8696"
        elif enabled:
            label, color = w("enabled", self.language), "#32b87a"
        else:
            label, color = w("disabled", self.language), "#7c8696"
        self.status_label.setText(label)
        self.status_dot.set_color(color)
        chip, body = how_it_works(self.plugin, draft, self.language)
        self.how_chip.setText(chip)
        self.how_chip.setVisible(bool(chip))
        self.how_text.setText(body)
        if hasattr(self, "check_row") and self.check_row.hint_label is not None:
            live = self.saved_enabled and self.plugin.ready
            self.check_row.hint_label.setText(w("check_on" if live else "check_off", self.language))
            self.test_box.setEnabled(live)
        dirty = self.dirty
        self.save_button.setEnabled(dirty)
        self.message.setText(w("unsaved", self.language) if dirty else "")
        self.message.setStyleSheet("")

    # -- actions --
    def reset_section(self, section_id):
        section = next((s for s in sections_for(self.plugin) if s.id == section_id), None)
        if section is None:
            return
        for key in section.keys:
            setting = next((item for item in self.plugin.settings if item.key == key), None)
            if setting is not None and setting.kind != "secret":
                self._set_value(key, setting.default)
        self._refresh()

    def reset_all(self):
        for setting in self._plain_settings():
            self._set_value(setting.key, setting.default)
        self._refresh()

    def save(self):
        try:
            values = self.collect()
        except ValueError as error:
            self.message.setText(str(error))
            self.message.setStyleSheet("color:#e26675;")
            return False
        for setting in self._secret_settings():
            secret = self._raw(setting.key)
            if not secret:
                continue
            try:
                self.runtime.store_secret(self.plugin.id, setting.key, secret)
            except Exception as error:
                self.message.setText(f"{text(setting.label, self.language)}: {error}")
                self.message.setStyleSheet("color:#e26675;")
                return False
            self.fields[setting.key].set_value("")
            self.fields[setting.key].set_saved(True, self.language)
        self.saved_enabled = self.enable_switch.isChecked() and self.plugin.ready
        self.saved_settings = dict(values)
        self.saved.emit(self.plugin.id, self.saved_enabled, values)
        self._refresh()
        return True

    def _run_action(self, action_id):
        try:
            values = self.collect()
        except ValueError as error:
            self.message.setText(str(error))
            return
        if (self.plugin.id, action_id) == ("pc_control", "check"):
            self.runtime.check_pc_connection(self._raw("token"))
            return
        self.runtime.run_action(self.plugin.id, action_id, parent=self.window(), settings=values)

    def scroll_to(self, card_id):
        card = self.cards.get(card_id)
        if card is not None:
            self.scroll.verticalScrollBar().setValue(card.y())
            self._set_active_nav(card_id)

    def _sync_nav(self, value):
        current = None
        for card_id, card in self.cards.items():
            if card.y() <= value + 40:
                current = card_id
        bar = self.scroll.verticalScrollBar()
        if value >= bar.maximum() and self.cards:
            current = list(self.cards)[-1]
        if current:
            self._set_active_nav(current)

    def _set_active_nav(self, card_id):
        self._active_nav = card_id
        for key, button in self.nav.items():
            active = key == card_id
            if button.property("active") != active:
                button.setProperty("active", active)
                button.style().unpolish(button)
                button.style().polish(button)

    def detach(self):
        if self.runtime is not None and hasattr(self, "apps_holder"):
            try:
                self.runtime.notification_apps_changed.disconnect(self._render_apps)
            except (RuntimeError, TypeError):
                pass
        if hasattr(self, "_countdown_timer"):
            self._countdown_timer.stop()
            if self.runtime is not None:
                try:
                    self.runtime.timers_changed.disconnect(self._render_timers)
                except (RuntimeError, TypeError):
                    pass
        if self.runtime is not None and hasattr(self, "pc_label"):
            try:
                self.runtime.pc_status_changed.disconnect(self._show_pc_status)
            except (RuntimeError, TypeError):
                pass
        if self.runtime is not None and getattr(self.runtime, "test_sink", None) == self._test_sink:
            self.runtime.test_sink = None
        if self.runtime is not None and hasattr(self.runtime, "dictation_done") and hasattr(self, "last_label"):
            try:
                self.runtime.dictation_done.disconnect(self._show_last)
            except (RuntimeError, TypeError):
                pass
