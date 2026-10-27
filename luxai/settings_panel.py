"""LuxAI settings window, inspired by the layout of the supplied Luxify screenshots.

Everything offered here is backed by a local configuration setting or real
feature. Cloud-only Luxify subscriptions and voice identities are not copied.
"""
from __future__ import annotations

from pathlib import Path
import webbrowser

from luxai.secure_keys import has_api_key, clear_api_key
from luxai.api_providers import PROVIDERS

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QProgressBar, QScrollArea, QSlider, QSizePolicy, QSpinBox, QVBoxLayout, QWidget, QMessageBox,
)

from luxai.voices import available_voices
from luxai.voice_presets import VOICE_PRESETS
from luxai.ui_i18n import LANGUAGES, get_ui_language, tr, translate_widgets
from luxai.icons import icon, set_button_icon, set_label_icon, theme_color
from luxai.ui_home import ToggleSwitch
from luxai.ui_preferences import (
    BackgroundControl, ColorPalette, ColorSwatch, PreferenceRow,
    SegmentedControl, color_value,
)


class SettingsPanel(QWidget):
    SECTION_ICONS = ("mic", "volume-2", "list-checks", "palette", "bot", "audio-lines", "monitor")
    SECTIONS = (
        ("Голосовой ввод", "Микрофон, распознавание и обращение"),
        ("Озвучка", "Голос ассистента и громкость"),
        ("Выполнение команд", "Подтверждения и управление"),
        ("Интерфейс", "Цвета, прозрачность и оформление"),
        ("ИИ-провайдер", "Локальная нейросеть и модель"),
        ("Синтез речи", "Движок речи и скорость"),
        ("Система", "Автозапуск и сворачивание"),
    )

    def __init__(self, config, on_save, on_pick_model, on_test_voice, on_test_online=None, on_install_local_ai=None):
        super().__init__()
        self.cfg = dict(config)
        self.on_save = on_save
        self.on_pick_model = on_pick_model
        self.on_test_voice = on_test_voice
        self.on_test_online = on_test_online
        self.on_install_local_ai = on_install_local_ai
        self.sections = []
        self.section_buttons = []

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self.scroll, 1)

        body = QWidget()
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setSpacing(14)
        self.body_layout.setContentsMargins(0, 2, 8, 10)
        self.scroll.setWidget(body)

        heading = QLabel("Настройки")
        heading.setObjectName("PageTitle")
        self.body_layout.addWidget(heading)
        description = QLabel("Изменения автоматически сохраняются на этом компьютере и применяются без кнопки сохранения.")
        description.setWordWrap(True)
        description.setObjectName("Muted")
        self.body_layout.addWidget(description)

        self._build_voice_input()
        self._build_voice_output()
        self._build_commands()
        self._build_interface()
        self._build_ai()
        self._build_synthesis()
        self._build_system()

        # Every actual settings control is monitored and saved automatically.
        # No explicit Save button is needed.
        self.body_layout.addStretch()

        sidebar = QFrame()
        sidebar.setObjectName("SettingsSidebar")
        sidebar.setFixedWidth(198)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(10, 10, 10, 10)
        side.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск настроек")
        self.search.textChanged.connect(self._filter)
        side.addWidget(self.search)
        label = QLabel("РАЗДЕЛЫ")
        label.setObjectName("Muted")
        side.addWidget(label)
        for idx, (title, _subtitle) in enumerate(self.SECTIONS):
            button = QPushButton(title)
            button.setObjectName("SettingsNav")
            button.setProperty("selected", idx == 0)
            set_button_icon(button, self.SECTION_ICONS[idx], role="accent" if idx == 0 else "default")
            button.clicked.connect(lambda checked=False, i=idx: self._jump(i))
            side.addWidget(button)
            self.section_buttons.append(button)
        side.addStretch()
        reset = QPushButton("Сбросить поиск")
        set_button_icon(reset, "search-x")
        reset.clicked.connect(lambda: self.search.clear())
        side.addWidget(reset)
        root.addWidget(sidebar)
        self.set_theme(self.theme.currentData(), self.accent.currentData(), self.background.currentData())
        translate_widgets(self, get_ui_language())
        self._setup_autosave()
        self._section_sync_timer = QTimer(self)
        self._section_sync_timer.setSingleShot(True)
        self._section_sync_timer.timeout.connect(self._sync_current_section)
        self.scroll.verticalScrollBar().valueChanged.connect(self._sync_current_section)
        self.scroll.verticalScrollBar().rangeChanged.connect(self._queue_section_sync)
        self.scroll.viewport().installEventFilter(self)
        body.installEventFilter(self)
        self._queue_section_sync()
        self._engine_status_timer = QTimer(self)
        self._engine_status_timer.setInterval(2000)
        self._engine_status_timer.timeout.connect(self._refresh_auto_engine_status)
        self._refresh_auto_engine_status(force=True)

    def _setup_autosave(self):
        """Debounce actual user settings edits, not diagnostics or search.

        The watcher is attached *after* widget construction/translation so
        default initialization cannot overwrite an existing config.json.
        """
        self._autosave_busy = False
        self._autosave_force = False
        self._api_key_commit_ready = False
        self._autosave_snapshot = self.collect()
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(550)
        self._autosave_timer.timeout.connect(self.flush_auto_save)

        controls = (
            "mic", "prefix", "prefix_text", "recognition_quality",
            "whisper_model", "language", "mic_device", "mic_sensitivity",
            "speech_pause", "tts", "voice_id", "response_language",
            "voice_volume", "voice_engine", "voice_speed", "confirm",
            "confirm_yes", "confirm_no", "confirm_timeout", "chain_words",
            "ui_language", "theme", "accent", "background", "transparency",
            "animations", "on_top", "autostart", "tray_on_close",
            "weather_city", "local_llm_fallback", "model_select",
            "online_agent_enabled", "online_provider", "online_model",
            "custom_api_url", "online_timeout",
        )
        for name in controls:
            widget = getattr(self, name)
            if isinstance(widget, QCheckBox):
                widget.toggled.connect(self._queue_auto_save)
            elif isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._queue_auto_save)
            elif isinstance(widget, (QSlider, QSpinBox)):
                widget.valueChanged.connect(self._queue_auto_save)
            elif isinstance(widget, QLineEdit):
                widget.textChanged.connect(self._queue_auto_save)
        # A secret must not be written after every keystroke.
        # Save it only after editing finishes or a separate key test succeeds.
        self.api_key_entry.textChanged.connect(self._on_api_key_draft_changed)
        self.api_key_entry.editingFinished.connect(self._queue_api_key_save)

    def _queue_auto_save(self, *_):
        if not self._autosave_busy:
            self._autosave_timer.start()

    def _on_api_key_draft_changed(self, *_):
        # A pending secret is not ready to save while the user is typing.
        self._api_key_commit_ready = False

    def _queue_api_key_save(self):
        if self.api_key_entry.text().strip():
            self._api_key_commit_ready = True
            self._autosave_force = True
            self._queue_auto_save()

    def api_key_ready_for_save(self):
        """Only submit a finished secret, never the middle of a pasted/typed key."""
        return self.api_key_entry.text().strip() if self._api_key_commit_ready else ""

    def mark_auto_saved(self):
        """Also called when a Home control / explicit API test saved config."""
        if not hasattr(self, "_autosave_timer"):
            return
        self._autosave_snapshot = self.collect()
        self._autosave_force = False
        self._autosave_timer.stop()

    def flush_auto_save(self):
        """Persist pending edits before navigation and window close."""
        if not hasattr(self, "_autosave_timer") or self._autosave_busy:
            return
        self._autosave_timer.stop()
        current = self.collect()
        if current == self._autosave_snapshot and not self._autosave_force:
            return
        self._autosave_busy = True
        try:
            if self.on_save() is not False:
                self.mark_auto_saved()
        finally:
            self._autosave_busy = False

    def _section(self, title, subtitle):
        frame = QFrame()
        frame.setObjectName("SettingsCard")
        col = QVBoxLayout(frame)
        col.setContentsMargins(18, 17, 18, 18)
        col.setSpacing(12)
        heading = QLabel(title)
        heading.setStyleSheet("font-size:18px; font-weight:700;")
        heading_row = QHBoxLayout()
        heading_row.setSpacing(10)
        heading_icon = QLabel()
        set_label_icon(heading_icon, self.SECTION_ICONS[len(self.sections)], size=21, role="accent")
        heading_row.addWidget(heading_icon)
        heading_row.addWidget(heading)
        heading_row.addStretch()
        col.addLayout(heading_row)
        hint = QLabel(subtitle)
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        col.addWidget(hint)
        self.body_layout.addWidget(frame)
        self.sections.append(frame)
        return col

    @staticmethod
    def _row(layout, title, subtitle, control):
        line = QHBoxLayout()
        line.setSpacing(12)
        labels = QVBoxLayout()
        labels.setSpacing(3)
        name = QLabel(title)
        name.setStyleSheet("font-weight:600;")
        labels.addWidget(name)
        if subtitle:
            hint = QLabel(subtitle)
            hint.setObjectName("Muted")
            hint.setWordWrap(True)
            hint.setStyleSheet("font-size:11px;")
            labels.addWidget(hint)
        line.addLayout(labels, 3)
        if isinstance(control, ToggleSwitch):
            line.addWidget(control, 0, Qt.AlignmentFlag.AlignRight)
        elif isinstance(control, QWidget):
            control.setMinimumWidth(150)
            line.addWidget(control, 2)
        else:
            line.addLayout(control, 2)
        layout.addLayout(line)

    @staticmethod
    def _combo(items, selected):
        widget = QComboBox()
        for title, value in items:
            widget.addItem(title, value)
        idx = widget.findData(selected)
        widget.setCurrentIndex(max(0, idx))
        return widget

    @staticmethod
    def _status_row(layout, label, name, *, role="muted"):
        """Keep status text selectable and accessible beside its SVG icon."""
        row = QHBoxLayout()
        row.setSpacing(8)
        indicator = QLabel()
        set_label_icon(indicator, name, size=17, role=role)
        row.addWidget(indicator, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(label, 1)
        layout.addLayout(row)
        return indicator

    @staticmethod
    def _combo_icon(combo, index, name, *, role="default"):
        # Shared icon refresh recolors these items without changing userData.
        combo.setItemData(index, name, Qt.ItemDataRole.UserRole + 60)
        combo.setItemData(index, role, Qt.ItemDataRole.UserRole + 61)
        combo.setItemIcon(index, icon(name, color=theme_color(role, combo), size=18))

    @staticmethod
    def _toggle(checked):
        return ToggleSwitch(bool(checked))

    @staticmethod
    def _slider(value, bottom, top):
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(bottom, top)
        slider.setValue(max(bottom, min(top, int(value))))
        return slider

    @staticmethod
    def _slider_value_control(slider, formatter=lambda value: f"{value}%"):
        """Keep the current value beside its slider, including during editing."""
        value = QLabel(formatter(slider.value()))
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        value.setMinimumWidth(52)
        value.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        value.setObjectName("SettingsSliderValue")
        value.setTextFormat(Qt.TextFormat.PlainText)
        slider.valueChanged.connect(lambda number: value.setText(formatter(number)))
        row = QHBoxLayout()
        row.setSpacing(9)
        row.addWidget(slider, 1)
        row.addWidget(value)
        return row, value

    def _build_voice_input(self):
        panel = self._section("Голосовой ввод", "Как Jarvis слышит вас: распознавание речи и микрофон.")
        self.recognition_engine = self._combo([("Whisper (локально)", "whisper")], "whisper")
        self._row(panel, "Распознавание речи", "Работает локально, без облака.", self.recognition_engine)
        self.recognition_quality = self._combo(
            [("Быстрее", 1), ("Сбалансированно", 2), ("Точнее", 4)],
            int(self.cfg.get("whisper_beam_size", 1)),
        )
        self._row(panel, "Повышенная точность", "Более точное распознавание может работать медленнее.", self.recognition_quality)
        self.whisper_model = self._combo(
            [("Small — standard (about 500 MB)", "small"),
             ("Medium — more accurate Romanian (about 1.5 GB, slower)", "medium"),
             ("Large-v3-turbo — advanced (requires a powerful PC)", "large-v3-turbo")],
            self.cfg.get("whisper_model", "small"),
        )
        self._row(panel, "Модель распознавания",
                  "Для румынского языка рекомендуется Medium, если хватает памяти. Модель загружается при первом использовании.",
                  self.whisper_model)
        self.language = self._combo(
            [("Авто", "auto"), ("Русский", "ru"), ("English", "en"), ("Română", "ro")],
            self.cfg.get("language", "ru"),
        )
        self._row(panel, "Язык распознавания", "Также задаёт язык ответов ассистента.", self.language)

        self.mic_device = QComboBox()
        self._microphone_metadata = {}
        self.refresh_microphone_devices(initial=True)
        self._row(panel, "Микрофон", "Выберите устройство входа.", self.mic_device)
        self.mic_sensitivity = self._slider(round(float(self.cfg.get("microphone_sensitivity", 1.0)) * 100), 50, 300)
        sensitivity_control, self.mic_sensitivity_value = self._slider_value_control(self.mic_sensitivity)
        self._row(panel, "Чувствительность микрофона",
                  "100% — обычная; увеличьте для тихого микрофона. Это не меняет громкость Windows.",
                  sensitivity_control)
        self.speech_pause = self._slider(
            round(float(self.cfg.get("speech_pause_seconds", 2.3)) * 10), 12, 40,
        )
        pause_control, self.speech_pause_value = self._slider_value_control(
            self.speech_pause, lambda value: f"{value / 10:.1f} s",
        )
        self._row(
            panel, "Пауза перед распознаванием",
            "Jarvis дождётся этой паузы после вашей речи (1,2–4,0 с). "
            "Если обрывает фразы, увеличьте до 3 секунд.",
            pause_control,
        )
        self.audio_level = QProgressBar()
        self.audio_level.setRange(0, 100)
        self.audio_level.setValue(0)
        self.audio_level.setFormat("%p%")
        self.audio_level.setAccessibleName(tr("Уровень микрофона"))
        self._row(panel, "Уровень микрофона", "Говорите: шкала должна двигаться.", self.audio_level)
        self.audio_status = QLabel(tr("Микрофон выключен"))
        self.audio_status.setWordWrap(True)
        self.audio_status_icon = self._status_row(panel, self.audio_status, "mic-off")
        self.audio_feedback = QLabel("")
        self.audio_feedback.setWordWrap(True)
        panel.addWidget(self.audio_feedback)
        self.refresh_mics = QPushButton("Обновить устройства")
        set_button_icon(self.refresh_mics, "refresh-cw")
        self.refresh_mics.clicked.connect(lambda: self.refresh_microphone_devices())
        self.test_microphone = QPushButton("Проверить микрофон")
        set_button_icon(self.test_microphone, "stethoscope")
        self.restart_microphone = QPushButton("Перезапустить микрофон")
        set_button_icon(self.restart_microphone, "rotate-cw")
        self.export_diagnostics = QPushButton("Сохранить диагностику")
        set_button_icon(self.export_diagnostics, "download")
        for pair in ((self.refresh_mics, self.test_microphone), (self.restart_microphone, self.export_diagnostics)):
            controls = QHBoxLayout()
            for button in pair:
                controls.addWidget(button)
            panel.addLayout(controls)
        headset_hint = QLabel("Для беспроводной гарнитуры выберите вход Headset / Hands-Free. Разрешите доступ к микрофону для настольных приложений в Windows.")
        headset_hint.setWordWrap(True)
        headset_hint.setObjectName("Muted")
        panel.addWidget(headset_hint)

        self.mic = self._toggle(self.cfg.get("microphone_enabled", True))
        self._row(panel, "Автовключение микрофона", "Начать прослушивание после запуска приложения.", self.mic)
        self.prefix = self._toggle(self.cfg.get("prefix_enabled", False))
        self._row(panel, "Обращение (префикс)", "Реагировать только после имени Jarvis.", self.prefix)
        self.prefix_text = QLineEdit(self.cfg.get("wake_prefix", "джарвис, жарвис, jarvis"))
        self._row(panel, "Варианты обращения", "Несколько вариантов через запятую.", self.prefix_text)

    def refresh_microphone_devices(self, initial=False):
        """Display each Windows microphone once; retain exact recording IDs."""
        from luxai.audio_devices import microphone_display_entries, microphone_display_name

        if initial:
            selected = self.cfg.get("microphone_device", -1)
            name = self.cfg.get("microphone_name", "")
            host = self.cfg.get("microphone_hostapi", "")
        else:
            selected = self.mic_device.currentData()
            info = self._selected_microphone_metadata()
            name, host = info.get("name", ""), info.get("hostapi", "")
        try:
            selected = int(selected) if selected is not None else -1
        except (TypeError, ValueError):
            selected = -1
        name, host = str(name or "").strip(), str(host or "").strip()

        # Rebuilding a QComboBox emits selection signals. A device scan must not
        # automatically change the microphone or restart recognition.
        was_blocked = self.mic_device.blockSignals(True)
        error = ""
        try:
            self.mic_device.clear()
            self.mic_device.addItem(tr("По умолчанию"), -1)
            self._combo_icon(self.mic_device, 0, "mic")
            self.mic_device.setItemData(
                0, {"name": "", "hostapi": ""}, Qt.ItemDataRole.UserRole + 1
            )
            self._microphone_metadata = {-1: {"name": "", "hostapi": ""}}
            raw_devices = []
            entries = []
            try:
                import sounddevice as sd
                hosts = sd.query_hostapis()
                raw_devices = list(sd.query_devices())
                entries = microphone_display_entries(raw_devices, hosts)
            except Exception as exc:
                error = type(exc).__name__

            labels_seen = {}
            for index, driver_name, host_name in entries:
                friendly = microphone_display_name(driver_name)
                # Identically named physical microphones remain selectable.
                count = labels_seen.get(friendly.casefold(), 0) + 1
                labels_seen[friendly.casefold()] = count
                display = friendly if count == 1 else f"{friendly} ({count})"
                self._microphone_metadata[index] = {
                    "name": driver_name, "hostapi": host_name,
                }
                self.mic_device.addItem(display, index)
                position = self.mic_device.count() - 1
                self._combo_icon(self.mic_device, position, "mic")
                self.mic_device.setItemData(
                    position, self._microphone_metadata[index],
                    Qt.ItemDataRole.UserRole + 1,
                )

            # Migrate old MME/DirectSound selections to the single WASAPI entry,
            # only when the recording device can be identified unambiguously.
            if name:
                matches = [i for i, meta in self._microphone_metadata.items()
                           if i != -1 and meta["name"].casefold() == name.casefold()]
                same_host = [i for i in matches
                             if self._microphone_metadata[i]["hostapi"].casefold() == host.casefold()]
                if host and same_host:
                    # PortAudio indices can move after reconnecting a headset.
                    # A same-named input on another API must not win just
                    # because it now occupies the saved numeric index.
                    matches = same_host
                if not matches and host.casefold() in {"mme", "windows mme"} and len(name) >= 20:
                    # PortAudio MME may truncate long Windows device names.
                    matches = [
                        i for i, meta in self._microphone_metadata.items()
                        if i != -1 and meta["name"].casefold().startswith(name.casefold())
                    ]
                if len(matches) == 1:
                    selected = matches[0]
                elif selected not in matches:
                    selected = None
            elif selected != -1 and selected not in self._microphone_metadata:
                # Legacy saved configs may contain only the old numeric index.
                # Do not substitute an unrelated device after indices change.
                matches = []
                if 0 <= selected < len(raw_devices):
                    old_name = str(raw_devices[selected].get("name", "")).casefold()
                    matches = [
                        i for i, meta in self._microphone_metadata.items()
                        if i != -1 and meta["name"].casefold() == old_name
                    ]
                selected = matches[0] if len(matches) == 1 else None

            position = self.mic_device.findData(selected)
            if position < 0:
                # Keep the original offline selection instead of choosing a
                # different live microphone without the user's approval.
                unavailable_index = (
                    self.cfg.get("microphone_device", -1)
                    if selected is None else selected
                )
                position = self.mic_device.count()
                self.mic_device.addItem(
                    tr("Недоступен") + ": " + (microphone_display_name(name) or str(unavailable_index)),
                    unavailable_index,
                )
                self._combo_icon(self.mic_device, position, "mic-off", role="muted")
                self.mic_device.setItemData(
                    position, {"name": name, "hostapi": host},
                    Qt.ItemDataRole.UserRole + 1,
                )
            self.mic_device.setCurrentIndex(position)
        finally:
            self.mic_device.blockSignals(was_blocked)
        if hasattr(self, "audio_status"):
            self.audio_status.setText(
                tr("Устройства обновлены.") + (f" ({error})" if error else "")
            )

    def _selected_microphone_metadata(self):
        return self.mic_device.itemData(self.mic_device.currentIndex(), Qt.ItemDataRole.UserRole + 1) or {}

    def _build_voice_output(self):
        panel = self._section("Озвучка", "Голос, которым звучат ответы Jarvis.")
        self.tts = self._toggle(self.cfg.get("tts_enabled", True))
        self._row(panel, "Голосовой ответ", "Озвучивать текст ответа.", self.tts)
        installed = {voice["id"]: voice for voice in available_voices() if voice["ready"]}
        voices = [("Автоматически — по языку ответа", "")]
        labels = {
            "ru": "Dmitri — Русский",
            "ro": "Mihai — Румынский",
            "en": "Lessac — Английский",
        }
        for lang, preset in VOICE_PRESETS.items():
            voice_id = preset["id"]
            voices.append((labels[lang], voice_id))
        preset_ids = {item["id"] for item in VOICE_PRESETS.values()}
        for voice in installed.values():
            if voice["id"] not in preset_ids:
                voices.append((voice["name"], voice["id"]))
        self.voice_id = self._combo(voices, self.cfg.get("voice_id", ""))
        self.refresh_voice_status()
        self.response_language = self._combo(
            [("Автоматически — как язык распознавания", "auto"),
             ("Русский", "ru"), ("English", "en"), ("Română", "ro")],
            self.cfg.get("response_language", "auto"),
        )
        self._row(
            panel, "Язык ответов Jarvis",
            "Определяет язык текста и озвучивания. "
            "Не меняет язык микрофона или интерфейса.",
            self.response_language,
        )
        def voice_changed(_index):
            selected = self.voice_id.currentData()
            for language, preset in VOICE_PRESETS.items():
                if preset["id"] == selected:
                    position = self.response_language.findData(language)
                    if position >= 0:
                        self.response_language.setCurrentIndex(position)
                    break
        self.voice_id.currentIndexChanged.connect(voice_changed)
        self._row(
            panel, "Голос ассистента",
            "Голоса со значком загрузки загрузятся при первом использовании. "
            "Голос выбирается по языку ответа, а не по языку интерфейса.",
            self.voice_id,
        )
        self.voice_volume = self._slider(self.cfg.get("voice_volume", 80), 0, 100)
        volume_control, self.voice_volume_value = self._slider_value_control(self.voice_volume)
        self._row(panel, "Громкость", "0–100%, применяется к озвучке.", volume_control)
        preview = QPushButton("Прослушать пример")
        set_button_icon(preview, "play")
        preview.clicked.connect(self.on_test_voice)
        panel.addWidget(preview)

    def refresh_voice_status(self):
        """Refresh installed/download icon without resetting the user's choice."""
        installed = {voice["id"] for voice in available_voices() if voice["ready"]}
        known = {preset["id"] for preset in VOICE_PRESETS.values()}
        for index in range(self.voice_id.count()):
            voice_id = self.voice_id.itemData(index)
            if not voice_id:
                self._combo_icon(self.voice_id, index, "audio-lines")
                continue
            if voice_id not in known and voice_id not in installed:
                continue
            ready = voice_id in installed
            self._combo_icon(self.voice_id, index, "check-circle-2" if ready else "download",
                             role="success" if ready else "muted")

    def _build_commands(self):
        panel = self._section(
            "Выполнение команд",
            "Обычные голосовые действия выполняются сразу. "
            "Сон, выключение, скрипты и опасные действия требуют разрешения.",
        )
        # confirm_desktop_actions was enabled by default in older versions.
        # It must not silently re-enable repetitive dialogs on upgrade.
        self.confirm = self._toggle(self.cfg.get("confirm_all_actions", False))
        self._row(
            panel, "Подтверждать также обычные действия",
            "Необязательная настройка: спрашивать разрешение даже "
            "для открытия приложений, сайтов и документов. "
            "Опасные действия всегда требуют подтверждения.",
            self.confirm,
        )
        self.confirm_yes = QLineEdit(self.cfg.get("confirm_yes_words", "да, ага, конечно, подтверждаю, давай"))
        self._row(panel, "Слова «да»", "Варианты голосового подтверждения через запятую.", self.confirm_yes)
        self.confirm_no = QLineEdit(self.cfg.get("confirm_no_words", "нет, отмена, отмени, не надо"))
        self._row(panel, "Слова «нет»", "Варианты голосового отказа через запятую.", self.confirm_no)
        self.confirm_timeout = QSpinBox()
        self.confirm_timeout.setRange(5, 180)
        self.confirm_timeout.setSuffix(" сек")
        self.confirm_timeout.setValue(int(self.cfg.get("confirmation_timeout", 30)))
        self._row(panel, "Автоотмена подтверждения", "Отмена, если нет ответа в течение заданного времени.", self.confirm_timeout)
        self.chain_words = QLineEdit(self.cfg.get("command_chain_words", "и затем, потом"))
        self._row(panel, "Связка команд", "Разделите две простые команды одним из этих выражений.", self.chain_words)

    def _build_interface(self):
        panel = self._section("Интерфейс", "Цвет темы, фон, прозрачность и язык. Изменения видны сразу.")
        panel.setSpacing(0)
        self.interface_reset = QPushButton()
        self.interface_reset.setObjectName("InterfaceReset")
        self.interface_reset.setFixedSize(30, 30)
        self.interface_reset.setToolTip(tr("Сбросить оформление"))
        self.interface_reset.setAccessibleName(tr("Сбросить оформление"))
        set_button_icon(self.interface_reset, "rotate-cw", size=17, role="muted")
        self.interface_reset.clicked.connect(self._reset_interface)
        panel.itemAt(0).layout().addWidget(self.interface_reset)
        self.theme = self._combo(
            [("Тёмное", "dark"), ("Светлое", "light")],
            self.cfg.get("ui_theme", "dark"),
        )
        self.theme_control = SegmentedControl(self.theme)
        panel.addWidget(PreferenceRow("Оформление", "Тёмное или светлое окно.", self.theme_control))
        self.accent = self._combo(
            [("Синий", "#3978f6"), ("Фиолетовый", "#873eff"), ("Пурпурный", "#b400ff"),
             ("Розовый", "#ec4899"), ("Зелёный", "#1bbf8b"), ("Оранжевый", "#f97316"),
             ("Красный", "#ff245a"), ("Белый", "#f5f5f5")],
            self.cfg.get("ui_accent", "#3978f6"),
        )
        initial_accent = color_value(self.cfg.get("ui_accent", ""))
        if initial_accent:
            index = self.accent.findData(initial_accent)
            if index < 0:
                self.accent.addItem(tr("Свой цвет"), initial_accent)
                index = self.accent.count() - 1
            self.accent.setCurrentIndex(index)
        self.accent_control = ColorPalette(self.accent)
        panel.addWidget(PreferenceRow("Цвет темы", "Акцент кнопок и навигации.", self.accent_control))
        initial_background = color_value(self.cfg.get("ui_background", "")) or ""
        self.background = self._combo(
            [("По теме", ""), ("#0A0A0A", "#0a0a0a"), ("#101B2C", "#101b2c"),
             ("#1C1329", "#1c1329"), ("#0E1E18", "#0e1e18")], initial_background,
        )
        if initial_background and self.background.findData(initial_background) < 0:
            self.background.addItem(tr("Свой цвет"), initial_background)
            self.background.setCurrentIndex(self.background.count() - 1)
        self.background_control = BackgroundControl(self.background)
        panel.addWidget(PreferenceRow("Цвет фона", "Подложка окна под содержимым.", self.background_control))
        self.transparency = self._slider(self.cfg.get("ui_transparency", 0), 0, 35)
        transparency_control, self.transparency_value = self._slider_value_control(self.transparency)
        self.transparency.setMinimumWidth(180)
        panel.addWidget(PreferenceRow("Прозрачность", "0–35% окна приложения.", transparency_control))
        self.animations = self._toggle(self.cfg.get("ui_animations", True))
        panel.addWidget(PreferenceRow("Анимации", "Отображение анимированного аватара.", self.animations))
        self.on_top = self._toggle(self.cfg.get("always_on_top", False))
        panel.addWidget(PreferenceRow("Поверх остальных окон", "Оставлять Jarvis видимым поверх приложений.", self.on_top))
        self.ui_language = self._combo(
            LANGUAGES, self.cfg.get("ui_language", "ru")
        )
        self.ui_language.setObjectName("UiLanguageCombo")
        self.ui_language_control = SegmentedControl(self.ui_language)
        panel.addWidget(PreferenceRow(
            "Язык интерфейса",
            "Меняет только интерфейс. Язык распознавания и озвучивания настраивается отдельно.",
            self.ui_language_control,
        ))

    def _reset_interface(self):
        for combo, value in ((self.theme, "dark"), (self.accent, "#3978f6"), (self.background, "")):
            combo.setCurrentIndex(combo.findData(value))
        self.transparency.setValue(0)
        self.animations.setChecked(True)
        self.on_top.setChecked(False)

    def set_theme(self, theme, accent, background=None):
        for control in self.findChildren(ToggleSwitch) + self.findChildren(ColorSwatch):
            control.set_theme(theme, accent, background)

    def _build_ai(self):
        panel = self._section(
            "ИИ-провайдер",
            "Онлайн-ИИ разбирает сложные команды, локальный агент проверяет и выполняет действия.",
        )
        self.online_agent_enabled = self._toggle(self.cfg.get("online_agent_enabled", False))
        self._row(
            panel, "Облачный помощник",
            "Работает только при подключении к интернету и с вашим ключом выбранного сервиса.",
            self.online_agent_enabled,
        )
        provider_name = self.cfg.get("online_provider", "openai")
        if provider_name not in PROVIDERS:
            provider_name = "openai"
        self.online_provider = self._combo(
            [(settings["label"], name) for name, settings in PROVIDERS.items()],
            provider_name,
        )
        self._row(
            panel, "Поставщик AI API",
            "OrcaRouter и OpenRouter — разные сервисы. Ключ должен принадлежать выбранному провайдеру.",
            self.online_provider,
        )

        saved_model = self.cfg.get("online_model", "")
        default_model = PROVIDERS[provider_name]["model"]
        # A model from another provider, or the AI Studio "Antigravity" agent
        # name, must not be used as a Gemini chat completion model.
        if provider_name == "gemini" and not str(saved_model).strip().startswith("gemini-"):
            saved_model = ""
        elif provider_name != "openai" and saved_model in {
            "gpt-4.1-nano", "gpt-4.1-mini", "gpt-4o-mini",
        }:
            saved_model = ""
        self.online_model = QLineEdit(saved_model or default_model)
        self.online_model.setMaxLength(140)
        self.online_model.setPlaceholderText("Введите ID модели")
        self._row(
            panel, "Модель API",
            "У разных сервисов разные названия моделей. При смене сервиса будет подставлен пример.",
            self.online_model,
        )
        self.gemini_hint = QLabel(
            "Gemini: «Antigravity» — агент AI Studio, а не модель chat API. "
            "Нажмите «Проверить ключ»: Jarvis подберёт доступную модель из вашего проекта."
        )
        self.gemini_hint.setObjectName("Muted")
        self.gemini_hint.setWordWrap(True)
        self.gemini_hint.setVisible(provider_name == "gemini")
        panel.addWidget(self.gemini_hint)
        # Avoid showing an old OrcaRouter URL in Google Gemini settings.
        # It is only relevant when the custom provider is selected.
        self._saved_custom_endpoint = self.cfg.get("online_custom_url", "")
        self.custom_api_url = QLineEdit(
            self._saved_custom_endpoint if provider_name == "custom" else ""
        )
        self.custom_api_url.setMaxLength(500)
        self.custom_api_url.setPlaceholderText("https://provider.example/v1/chat/completions")
        self._row(
            panel, "Другой HTTPS endpoint",
            "Только для пункта «Другой API». Ключ будет отправлен указанному вами серверу.",
            self.custom_api_url,
        )
        self.custom_api_url.setEnabled(provider_name == "custom")

        self.api_key_entry = QLineEdit()
        self.api_key_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_entry.setMaxLength(2048)
        self.api_key_entry.setToolTip("Ключ скрыт. Не делитесь им с другими.")
        self.api_key_controls = QWidget()
        self.api_key_controls_layout = QHBoxLayout(self.api_key_controls)
        self.api_key_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.api_key_controls_layout.setSpacing(7)
        self.api_key_controls_layout.addWidget(self.api_key_entry, 1)
        self.api_test_button = QPushButton("Проверить ключ")
        set_button_icon(self.api_test_button, "key-round")
        self.api_test_button.setMinimumWidth(130)
        self.api_test_button.setToolTip(
            "Проверить введённый или сохранённый ключ. Тест использует небольшую часть квоты API."
        )
        if self.on_test_online:
            self.api_test_button.clicked.connect(self.on_test_online)
        else:
            self.api_test_button.setEnabled(False)
        self.api_key_controls_layout.addWidget(self.api_test_button)
        self._row(
            panel, "API-ключ выбранного сервиса",
            "Успешная проверка автоматически сохраняет ключ и модель. Запрос может расходовать квоту.",
            self.api_key_controls,
        )
        self.key_status = QLabel("")
        self.key_status.setObjectName("Muted")
        self.key_status.setWordWrap(True)
        self.key_status_icon = self._status_row(panel, self.key_status, "key-round")

        self.online_timeout = QSpinBox()
        self.online_timeout.setRange(35, 120)
        self.online_timeout.setSuffix(" сек")
        # Migrate legacy 3–10 second timeouts: old defaults made Gemini time
        # out long before it could plan commands. Default is now 60 seconds.
        legacy_timeout = int(self.cfg.get("online_timeout", 60))
        self.online_timeout.setValue(60 if legacy_timeout < 35 else min(legacy_timeout, 120))
        self._row(
            panel, "Время ответа облачного ИИ",
            "Gemini может думать от 35 до 120 секунд. По умолчанию 60 сек. "
            "При HTTP 429 лимит аккаунта не исчезнет от увеличения времени.",
            self.online_timeout,
        )

        buttons = QHBoxLayout()
        self.provider_keys_button = QPushButton("Получить ключ")
        set_button_icon(self.provider_keys_button, "external-link")
        self.provider_keys_button.clicked.connect(self._open_provider_keys)
        buttons.addWidget(self.provider_keys_button)
        delete_button = QPushButton("Удалить ключ")
        set_button_icon(delete_button, "trash-2", role="danger")
        delete_button.clicked.connect(self._clear_key)
        buttons.addWidget(delete_button)
        panel.addLayout(buttons)

        self.online_status = QLabel(
            "У каждого поставщика собственный ключ и лимиты. Некоторые сервисы "
            "предоставляют бесплатные квоты, но это зависит от аккаунта. При включении "
            "онлайн-ИИ команда и до четырёх предыдущих реплик отправляются выбранному "
            "сервису. Никогда не публикуйте ключи в чате или на GitHub."
        )
        self.online_status.setObjectName("Muted")
        self.online_status.setWordWrap(True)
        panel.addWidget(self.online_status)

        self.online_provider.currentIndexChanged.connect(self._on_provider_changed)
        self.api_key_entry.textChanged.connect(self._on_key_text_changed)
        self.refresh_key_status()
        self._refresh_provider_keys_button()

        self.local_llm_fallback = self._toggle(
            self.cfg.get("local_llm_fallback_enabled", True)
        )
        self._row(
            panel, "Резервный локальный ИИ",
            "Если облачный API недоступен, запускать тяжёлую GGUF-модель. "
            "Выключите для максимальной скорости: быстрые команды работают и без неё.",
            self.local_llm_fallback,
        )
        from luxai.local_models import available_models, resolve_model_path, format_model
        self.model_select = QComboBox()
        self.model_select.setObjectName("LocalGGUFCombo")
        self.model_select.setMinimumWidth(320)
        self._refresh_local_models()
        self.model_select.currentIndexChanged.connect(self._selected_local_model)
        self._row(
            panel, "Модели в папке models",
            "Все файлы .gguf в папке LuxAI_Local/models. Недостаточно просто выбрать файл: "
            "для чата также требуется llama-cpp-python.",
            self.model_select,
        )
        self.model_label = QLabel(
            Path(self.model_select.currentData() or "").name or "Модель не выбрана"
        )
        self.model_label.setObjectName("Muted")
        self.model_label.setWordWrap(True)
        self.model_health = QLabel("")
        self.model_health.setObjectName("Muted")
        self.model_health.setWordWrap(True)
        self.model_health_icon = self._status_row(panel, self.model_health, "circle-alert")
        self._selected_local_model()
        self._row(
            panel, "Локальная модель ИИ",
            "Продолжает работать без интернета, даже если онлайн API недоступен.",
            self.model_label,
        )
        choose = QPushButton("Выбрать локальную модель .gguf")
        set_button_icon(choose, "folder-open")
        choose.clicked.connect(self.on_pick_model)
        panel.addWidget(choose)
        refresh = QPushButton("Обновить список моделей")
        set_button_icon(refresh, "refresh-cw")
        refresh.clicked.connect(self.refresh_local_models)
        panel.addWidget(refresh)
        self.local_engine_status = QLabel()
        self.local_engine_status.setObjectName("Muted")
        self.local_engine_status.setWordWrap(True)
        panel.addWidget(self.local_engine_status)

    def _refresh_local_models(self):
        from luxai.local_models import available_models, resolve_model_path, format_model
        selected = (self.model_select.currentData() or self.cfg.get("llm_model_path", ""))
        self.model_select.blockSignals(True)
        self.model_select.clear()
        self.model_select.addItem(tr("— Модель не выбрана —"), "")
        self.model_select.setItemData(0, "— Модель не выбрана —", Qt.ItemDataRole.UserRole + 18)
        self._combo_icon(self.model_select, 0, "bot", role="muted")
        found = available_models()
        for item in found:
            self.model_select.addItem(format_model(item), item["path"])
            self._combo_icon(self.model_select, self.model_select.count() - 1,
                             "bot" if item["valid"] else "circle-alert")
            if not item["valid"]:
                index = self.model_select.count() - 1
                self.model_select.model().item(index).setEnabled(False)
        resolved = resolve_model_path(str(selected))
        if resolved is not None:
            index = self.model_select.findData(str(resolved))
            if index >= 0:
                self.model_select.setCurrentIndex(index)
        else:
            # External model paths remain supported, including previously
            # configured paths outside models/ on this computer.
            path = Path(str(selected))
            if path.is_file():
                self.model_select.addItem(path.name + " (" + tr("внешняя модель") + ")", str(path.resolve()))
                self._combo_icon(self.model_select, self.model_select.count() - 1, "bot")
                self.model_select.setCurrentIndex(self.model_select.count() - 1)
        self.model_select.blockSignals(False)
        return len(found)

    def _selected_local_model(self, *_):
        current = self.model_select.currentData() or ""
        if hasattr(self, "model_label"):
            self.model_label.setText(
                Path(current).name or tr("Модель не выбрана")
            )
        if hasattr(self, "model_health"):
            from luxai.local_models import model_status
            ready, status = model_status(str(current))
            self.model_health.setText(tr(status))
            set_label_icon(self.model_health_icon, "check-circle-2" if ready else "circle-alert",
                           size=17, role="success" if ready else "muted")

    def refresh_local_models(self):
        """Rescan files after user copies a model or chooses one externally."""
        count = self._refresh_local_models()
        self._selected_local_model()
        self._refresh_auto_engine_status(force=True)
        return count

    def _refresh_auto_engine_status(self, *, force=False):
        if not force and not self.isVisible():
            return
        from luxai.local_ai_setup import setup_status
        state = setup_status()
        message = {
            "installing": "Движок локального ИИ подготавливается…",
            "ready": "Движок локального ИИ готов.",
            "unavailable": "Движок локального ИИ пока недоступен. Подключитесь к интернету и повторите Update.bat.",
        }.get(state, "Движок локального ИИ подготавливается автоматически при запуске и обновлении.")
        self.local_engine_status.setText(tr(message))
        if state != getattr(self, "_engine_status_state", None):
            self._engine_status_state = state
            self._selected_local_model()

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "_engine_status_timer"):
            self._engine_status_timer.start()
            self._refresh_auto_engine_status(force=True)

    def hideEvent(self, event):
        if hasattr(self, "_engine_status_timer"):
            self._engine_status_timer.stop()
        super().hideEvent(event)

    def _on_provider_changed(self, *_):
        provider = self.online_provider.currentData()
        self.online_model.setText(PROVIDERS[provider]["model"])
        self.gemini_hint.setVisible(provider == "gemini")
        if self.custom_api_url.isEnabled():
            self._saved_custom_endpoint = self.custom_api_url.text().strip()
        if provider == "custom":
            self.custom_api_url.setText(self._saved_custom_endpoint)
            self.custom_api_url.setEnabled(True)
        else:
            self.custom_api_url.setText("")
            self.custom_api_url.setEnabled(False)
        # Never accidentally send an unsaved key to a different provider.
        self.api_key_entry.clear()
        self.refresh_key_status()
        self._refresh_provider_keys_button()

    def _on_key_text_changed(self, text):
        if text.strip():
            self._key_status_mode = "draft"
            set_label_icon(self.key_status_icon, "key-round", size=17, role="accent")
            if text.strip().startswith("sk-orca-") and self.online_provider.currentData() != "orcarouter":
                self.key_status.setText(
                    tr("Похоже, это ключ OrcaRouter. Выберите «OrcaRouter (orcarouter.ai)» "
                    "в списке провайдеров, иначе проверка может вернуть 401.")
                )
            else:
                self.key_status.setText(
                    tr("Ключ сохраняется после завершения ввода. Нажмите «Проверить ключ» для проверки.")
                )
        else:
            self.refresh_key_status()

    def set_test_busy(self, busy):
        self.api_test_button.setEnabled(not busy)
        self.api_test_button.setText(tr("Проверка…" if busy else "Проверить ключ"))
        set_button_icon(self.api_test_button, "refresh-cw" if busy else "key-round")
        if busy:
            self._key_status_mode = "busy"
            set_label_icon(self.key_status_icon, "refresh-cw", size=17, role="accent")
            self.key_status.setText(tr("Проверка ключа и выбранной модели через API…"))

    def show_test_result(self, message, valid):
        self.set_test_busy(False)
        self._key_status_mode = "test"
        self.key_status.setText(message)
        set_label_icon(self.key_status_icon, "check-circle-2" if valid else "x-circle",
                       size=17, role="success" if valid else "danger")

    def _refresh_provider_keys_button(self):
        provider = self.online_provider.currentData()
        self.provider_keys_button.setEnabled(bool(PROVIDERS[provider]["api_keys"]))

    def _open_provider_keys(self):
        provider = self.online_provider.currentData()
        url = PROVIDERS[provider]["api_keys"]
        if url:
            webbrowser.open(url)

    def _clear_key(self):
        provider = self.online_provider.currentData()
        name = PROVIDERS[provider]["label"]
        answer = QMessageBox.question(
            self, tr("API-ключ"),
            {"ru": f"Удалить локально сохранённый ключ для {name}?",
             "en": f"Delete the locally stored API key for {name}?",
             "ro": f"Ștergi cheia API salvată local pentru {name}?"}[get_ui_language()],
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            clear_api_key(provider)
            self.api_key_entry.clear()
            self.refresh_key_status()
            # Credentials are deliberately absent from collect(), but deleting
            # one still changes the live cloud configuration. Notify the main
            # window so a previous successful health check cannot stay green.
            self._autosave_force = True
            self._queue_auto_save()

    def refresh_key_status(self, *, update_status=True):
        provider = self.online_provider.currentData()
        name = PROVIDERS[provider]["label"]
        stored = has_api_key(provider)
        language = get_ui_language()
        placeholders = {
            "ru": (f"Ключ {name} уже сохранён", f"Введите свой ключ {name}"),
            "en": (f"{name} key already saved", f"Enter your {name} key"),
            "ro": (f"Cheia {name} este salvată", f"Introdu cheia {name}"),
        }
        statuses = {
            "ru": (f"Ключ {name} найден на этом компьютере.", f"Ключ {name} пока не установлен."),
            "en": (f"{name} key found on this computer.", f"{name} key not configured yet."),
            "ro": (f"Cheia {name} a fost găsită pe calculator.", f"Cheia {name} nu este configurată."),
        }
        self.api_key_entry.setPlaceholderText(placeholders[language][0 if stored else 1])
        if not update_status:
            return
        self._key_status_mode = "storage"
        self.key_status.setText(statuses[language][0 if stored else 1])
        set_label_icon(self.key_status_icon, "check-circle-2" if stored else "key-round",
                       size=17, role="success" if stored else "muted")

    def _build_synthesis(self):
        panel = self._section("Синтез речи", "Локальный Piper или голос Windows (если установлен нужный язык).")
        self.voice_engine = self._combo(
            [("Piper", "piper"), ("Windows", "windows")],
            self.cfg.get("voice_engine", "piper"),
        )
        self._row(panel, "Провайдер синтеза", "Выбранный голос Piper загружается при первом использовании.", self.voice_engine)
        self.voice_speed = self._slider(round(float(self.cfg.get("voice_speed", 1.0)) * 100), 70, 140)
        speed_control, self.voice_speed_value = self._slider_value_control(self.voice_speed)
        self._row(panel, "Скорость речи", "70–140% обычной скорости.", speed_control)
        self.speech_status = QLabel(
            "Для голоса Windows нужен установленный языковой пакет. "
            "Piper работает локально после загрузки голоса."
        )
        self.speech_status.setObjectName("Muted")
        self.speech_status.setWordWrap(True)
        panel.addWidget(self.speech_status)

    def _build_system(self):
        panel = self._section("Система", "Запуск вместе с Windows и работа в фоновом режиме.")
        self.autostart = self._toggle(self.cfg.get("autostart_windows", False))
        self._row(panel, "Автозапуск программы", "Запускать Jarvis при входе в Windows.", self.autostart)
        self.tray_on_close = self._toggle(self.cfg.get("minimize_to_tray", False))
        self._row(panel, "Сворачивать в трей при закрытии", "Не завершать Jarvis при закрытии главного окна.", self.tray_on_close)
        self.weather_city = QLineEdit(self.cfg.get("weather_city", "Кишинёв"))
        self.weather_city.setPlaceholderText("Кишинёв")
        self._row(
            panel, "Город для прогноза погоды",
            "Open-Meteo работает без ключа Gemini. Этот город по умолчанию.",
            self.weather_city,
        )
        info = QLabel("Изменения автоматически сохраняются в config.json. При смене микрофона распознавание перезапускается.")
        info.setObjectName("Muted")
        info.setWordWrap(True)
        panel.addWidget(info)

    def retranslate(self, language):
        translate_widgets(self, language)
        self.ui_language_control.sync()
        self.refresh_key_status(update_status=False)
        mode = getattr(self, "_key_status_mode", "storage")
        if mode == "busy":
            self.set_test_busy(True)
        elif mode == "test":
            pass
        elif self.api_key_entry.text().strip():
            self._on_key_text_changed(self.api_key_entry.text())
        else:
            self.refresh_key_status()
        self._selected_local_model()
        self._refresh_auto_engine_status(force=True)
        self._queue_section_sync()

    def _jump(self, index):
        section = self.sections[index]
        if section.isHidden():
            return
        self.scroll.verticalScrollBar().setValue(section.y())
        self._sync_current_section()

    def _select_section(self, index):
        for i, button in enumerate(self.section_buttons):
            if bool(button.property("selected")) == (i == index):
                continue
            button.setProperty("selected", i == index)
            set_button_icon(button, self.SECTION_ICONS[i], role="accent" if i == index else "default")
            button.style().unpolish(button)
            button.style().polish(button)

    def _queue_section_sync(self, *_):
        if hasattr(self, "_section_sync_timer"):
            self._section_sync_timer.start(0)

    def _sync_current_section(self, *_):
        """Follow the section at the viewport's top, including the page end."""
        if not self.isVisible():
            return
        visible = [(i, section) for i, section in enumerate(self.sections)
                   if not section.isHidden()]
        if not visible:
            self._select_section(-1)
            return
        scrollbar = self.scroll.verticalScrollBar()
        if scrollbar.maximum() > 0 and scrollbar.value() >= scrollbar.maximum():
            selected = visible[-1][0]
        else:
            marker = scrollbar.value() + 16
            selected = visible[0][0]
            for index, section in visible:
                if section.y() <= marker:
                    selected = index
                else:
                    break
        self._select_section(selected)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.LayoutRequest, QEvent.Type.Show):
            self._queue_section_sync()
        return super().eventFilter(watched, event)

    def _filter(self, text):
        query = text.strip().casefold()
        for (_name, _), section, button in zip(self.SECTIONS, self.sections, self.section_buttons):
            match = not query or query in button.text().casefold()
            section.setVisible(match)
            button.setVisible(match)
        # Hidden sections are already known before Qt lays out the remaining
        # ones. Clear/select immediately, then resync their new geometry.
        # On Windows, layout events can restart the zero-delay timer after
        # an event-loop pass, leaving a stale hidden selection meanwhile.
        self._sync_current_section()
        self._queue_section_sync()

    def collect(self):
        return {
            "microphone_enabled": self.mic.isChecked(),
            "prefix_enabled": self.prefix.isChecked(),
            "wake_prefix": self.prefix_text.text().strip() or "джарвис, жарвис, jarvis",
            "language": self.language.currentData(),
            "whisper_beam_size": self.recognition_quality.currentData(),
            "whisper_model": self.whisper_model.currentData(),
            "microphone_device": self.mic_device.currentData(),
            "microphone_name": self._selected_microphone_metadata().get("name", ""),
            "microphone_hostapi": self._selected_microphone_metadata().get("hostapi", ""),
            "microphone_sensitivity": self.mic_sensitivity.value() / 100.0,
            "speech_pause_seconds": self.speech_pause.value() / 10.0,
            "tts_enabled": self.tts.isChecked(),
            "voice_id": self.voice_id.currentData(),
            "response_language": self.response_language.currentData(),
            "voice_volume": self.voice_volume.value(),
            "voice_engine": self.voice_engine.currentData(),
            "voice_speed": round(self.voice_speed.value() / 100, 2),
            "confirm_desktop_actions": False,
            "confirm_all_actions": self.confirm.isChecked(),
            "confirm_yes_words": self.confirm_yes.text().strip(),
            "confirm_no_words": self.confirm_no.text().strip(),
            "confirmation_timeout": self.confirm_timeout.value(),
            "command_chain_words": self.chain_words.text().strip(),
            "ui_language": self.ui_language.currentData(),
            "ui_theme": self.theme.currentData(),
            "ui_accent": self.accent.currentData(),
            "ui_background": self.background.currentData() or "",
            "ui_transparency": self.transparency.value(),
            "ui_animations": self.animations.isChecked(),
            "always_on_top": self.on_top.isChecked(),
            "autostart_windows": self.autostart.isChecked(),
            "minimize_to_tray": self.tray_on_close.isChecked(),
            "weather_city": self.weather_city.text().strip()[:70] or "Кишинёв",
            "tesseract_path": self.cfg.get("tesseract_path", ""),
            "local_llm_fallback_enabled": self.local_llm_fallback.isChecked(),
            "llm_model_path": self.model_select.currentData() or "",
            "online_agent_enabled": self.online_agent_enabled.isChecked(),
            "online_provider": self.online_provider.currentData(),
            "online_model": self.online_model.text().strip(),
            "online_custom_url": (
                self.custom_api_url.text().strip()
                if self.online_provider.currentData() == "custom"
                else self._saved_custom_endpoint
            ),
            "online_timeout": self.online_timeout.value(),
        }
