"""LuxAI settings window, inspired by the layout of the supplied Luxify screenshots.

Everything offered here is backed by a local configuration setting or real
feature. Cloud-only Luxify subscriptions and voice identities are not copied.
"""
from __future__ import annotations

from pathlib import Path
import webbrowser

from luxai.secure_keys import has_api_key, clear_api_key

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget, QMessageBox,
)

from luxai.voices import available_voices


class SettingsPanel(QWidget):
    SECTIONS = (
        ("Голосовой ввод", "Микрофон, распознавание и обращение"),
        ("Озвучка", "Голос ассистента и громкость"),
        ("Выполнение команд", "Подтверждения и управление"),
        ("Интерфейс", "Цвета, прозрачность и оформление"),
        ("ИИ-провайдер", "Локальная нейросеть и модель"),
        ("Синтез речи", "Движок речи и скорость"),
        ("Система", "Автозапуск и сворачивание"),
    )

    def __init__(self, config, on_save, on_pick_model, on_test_voice):
        super().__init__()
        self.cfg = dict(config)
        self.on_save = on_save
        self.on_pick_model = on_pick_model
        self.on_test_voice = on_test_voice
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
        description = QLabel("Настройки сохраняются на этом компьютере. Изменения применяются после сохранения.")
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

        save = QPushButton("Сохранить настройки")
        save.setObjectName("Primary")
        save.clicked.connect(self.on_save)
        self.body_layout.addWidget(save)
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
            button.clicked.connect(lambda checked=False, i=idx: self._jump(i))
            side.addWidget(button)
            self.section_buttons.append(button)
        side.addStretch()
        reset = QPushButton("Сбросить поиск")
        reset.clicked.connect(lambda: self.search.clear())
        side.addWidget(reset)
        root.addWidget(sidebar)

    def _section(self, title, subtitle):
        frame = QFrame()
        frame.setObjectName("SettingsCard")
        frame.setStyleSheet(
            "QFrame#SettingsCard {background:#1b2029; border:1px solid #303744; border-radius:15px;}"
            "QFrame#SettingsCard QLabel {background:transparent; border:0;}"
            "QFrame#SettingsCard QCheckBox {background:transparent; border:0;}"
        )
        col = QVBoxLayout(frame)
        col.setContentsMargins(18, 17, 18, 18)
        col.setSpacing(12)
        heading = QLabel(title)
        heading.setStyleSheet("font-size:18px; font-weight:700; color:#f4f6fb;")
        col.addWidget(heading)
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
            hint.setStyleSheet("font-size:11px; color:#a2a9b7;")
            labels.addWidget(hint)
        line.addLayout(labels, 3)
        if isinstance(control, QWidget):
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
    def _toggle(checked):
        checkbox = QCheckBox()
        checkbox.setChecked(bool(checked))
        return checkbox

    @staticmethod
    def _slider(value, bottom, top):
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(bottom, top)
        slider.setValue(max(bottom, min(top, int(value))))
        return slider

    def _build_voice_input(self):
        panel = self._section("Голосовой ввод", "Как Jarvis слышит вас: распознавание речи и микрофон.")
        self.recognition_engine = self._combo([("Whisper (локально)", "whisper")], "whisper")
        self._row(panel, "Распознавание речи", "Работает локально, без облака.", self.recognition_engine)
        self.recognition_quality = self._combo(
            [("Быстрее", 1), ("Сбалансированно", 2), ("Точнее", 4)],
            int(self.cfg.get("whisper_beam_size", 1)),
        )
        self._row(panel, "Повышенная точность", "Более точное распознавание может работать медленнее.", self.recognition_quality)
        self.language = self._combo(
            [("Авто", "auto"), ("Русский", "ru"), ("English", "en"), ("Română", "ro")],
            self.cfg.get("language", "ru"),
        )
        self._row(panel, "Язык распознавания", "Также задаёт язык ответов ассистента.", self.language)

        devices = [("По умолчанию", -1)]
        try:
            import sounddevice as sd
            for i, item in enumerate(sd.query_devices()):
                if item["max_input_channels"] > 0:
                    devices.append((f"{i}: {item['name']}", i))
        except Exception:
            pass
        self.mic_device = self._combo(devices, int(self.cfg.get("microphone_device", -1)))
        self._row(panel, "Микрофон", "Выберите устройство входа.", self.mic_device)

        self.mic = self._toggle(self.cfg.get("microphone_enabled", True))
        self._row(panel, "Автовключение микрофона", "Начать прослушивание после запуска приложения.", self.mic)
        self.prefix = self._toggle(self.cfg.get("prefix_enabled", False))
        self._row(panel, "Обращение (префикс)", "Реагировать только после имени Jarvis.", self.prefix)
        self.prefix_text = QLineEdit(self.cfg.get("wake_prefix", "джарвис, жарвис, jarvis"))
        self._row(panel, "Варианты обращения", "Несколько вариантов через запятую.", self.prefix_text)

    def _build_voice_output(self):
        panel = self._section("Озвучка", "Голос, которым звучат ответы Jarvis.")
        self.tts = self._toggle(self.cfg.get("tts_enabled", True))
        self._row(panel, "Голосовой ответ", "Озвучивать текст ответа.", self.tts)
        voices = [("Дмитрий — русский (по умолчанию)", "")]
        installed = available_voices()
        for voice in installed:
            if voice["ready"]:
                voices.append((voice["name"], voice["id"]))
        self.voice_id = self._combo(voices, self.cfg.get("voice_id", ""))
        self._row(panel, "Голос ассистента", "Список локально установленных моделей Piper.", self.voice_id)
        self.voice_volume = self._slider(self.cfg.get("voice_volume", 80), 0, 100)
        self._row(panel, "Громкость", "0–100%, применяется к озвучке.", self.voice_volume)
        preview = QPushButton("▶  Прослушать пример")
        preview.clicked.connect(self.on_test_voice)
        panel.addWidget(preview)

    def _build_commands(self):
        panel = self._section("Выполнение команд", "Подтверждения перед управлением приложениями и окнами.")
        self.confirm = self._toggle(self.cfg.get("confirm_desktop_actions", True))
        self._row(panel, "Подтверждать действия", "Запрашивать разрешение перед открытием программ и другими действиями.", self.confirm)
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
        panel = self._section("Интерфейс", "Вид окна и оформление.")
        self.theme = self._combo(
            [("Тёмное", "dark"), ("Светлое", "light")],
            self.cfg.get("ui_theme", "dark"),
        )
        self._row(panel, "Оформление", "Тёмное или светлое окно.", self.theme)
        self.accent = self._combo(
            [("Синий", "#3978f6"), ("Фиолетовый", "#873eff"), ("Зелёный", "#1bbf8b"), ("Розовый", "#ec4899")],
            self.cfg.get("ui_accent", "#3978f6"),
        )
        self._row(panel, "Цвет темы", "Акцент кнопок и навигации.", self.accent)
        self.transparency = self._slider(self.cfg.get("ui_transparency", 0), 0, 35)
        self._row(panel, "Прозрачность", "0–35% окна приложения.", self.transparency)
        self.animations = self._toggle(self.cfg.get("ui_animations", True))
        self._row(panel, "Анимации", "Отображение анимированного аватара.", self.animations)
        self.on_top = self._toggle(self.cfg.get("always_on_top", False))
        self._row(panel, "Поверх остальных окон", "Оставлять Jarvis видимым поверх приложений.", self.on_top)
        hint = QLabel("Язык интерфейса: Русский. Румынский и английский доступны для распознавания и ответов.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        panel.addWidget(hint)

    def _build_ai(self):
        panel = self._section(
            "ИИ-провайдер",
            "Два агента: облачный ИИ разбирает команды, локальный выполняет разрешённые действия.",
        )
        self.online_agent_enabled = self._toggle(self.cfg.get("online_agent_enabled", False))
        self._row(
            panel, "Облачный помощник",
            "Работает только с интернетом и вашим OpenAI API-ключом. Без связи остаётся локальный режим.",
            self.online_agent_enabled,
        )
        self.online_model = self._combo(
            [
                ("GPT-4.1 nano — быстро и экономно", "gpt-4.1-nano"),
                ("GPT-4o mini", "gpt-4o-mini"),
                ("GPT-4.1 mini", "gpt-4.1-mini"),
            ],
            self.cfg.get("online_model", "gpt-4.1-nano"),
        )
        self._row(panel, "Модель облачного агента", "Только разбор намерения и короткие ответы.", self.online_model)

        self.api_key_entry = QLineEdit()
        self.api_key_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_entry.setMaxLength(512)
        self.api_key_entry.setPlaceholderText(
            "Ключ сохранён в Windows" if has_api_key() else "Вставьте собственный OpenAI API-ключ"
        )
        self._row(
            panel, "OpenAI API-ключ",
            "После сохранения шифруется Windows DPAPI и не записывается в config.json.",
            self.api_key_entry,
        )
        self.online_timeout = QSpinBox()
        self.online_timeout.setRange(3, 10)
        self.online_timeout.setSuffix(" сек")
        self.online_timeout.setValue(int(self.cfg.get("online_timeout", 5)))
        self._row(panel, "Таймаут облака", "Если сеть не отвечает, продолжить локально.", self.online_timeout)
        key_buttons = QHBoxLayout()
        get_key = QPushButton("Открыть страницу API-ключей")
        get_key.clicked.connect(lambda: webbrowser.open("https://platform.openai.com/api-keys"))
        key_buttons.addWidget(get_key)
        clear = QPushButton("Удалить сохранённый ключ")
        clear.clicked.connect(self._clear_key)
        key_buttons.addWidget(clear)
        panel.addLayout(key_buttons)
        self.online_status = QLabel(
            "Когда облачный агент включён, ваша команда и до четырёх последних реплик "
            "отправляются в OpenAI. API оплачивается отдельно от ChatGPT, бесплатный "
            "доступ не гарантирован. Никогда не отправляйте ключ в чат или на GitHub."
        )
        self.online_status.setObjectName("Muted")
        self.online_status.setWordWrap(True)
        panel.addWidget(self.online_status)

        self.model_label = QLabel(
            Path(self.cfg.get("llm_model_path", "")).name or "Модель не выбрана"
        )
        self.model_label.setObjectName("Muted")
        self.model_label.setWordWrap(True)
        self._row(
            panel, "Локальная модель ИИ",
            "Отвечает без интернета, когда облако выключено или недоступно.",
            self.model_label,
        )
        choose = QPushButton("Выбрать локальную модель .gguf")
        choose.clicked.connect(self.on_pick_model)
        panel.addWidget(choose)

    def _clear_key(self):
        answer = QMessageBox.question(
            self, "OpenAI API", "Удалить сохранённый на этом компьютере API-ключ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            clear_api_key()
            self.api_key_entry.clear()
            self.api_key_entry.setPlaceholderText("Вставьте собственный OpenAI API-ключ")
            self.online_agent_enabled.setChecked(False)

    def refresh_key_status(self):
        self.api_key_entry.setPlaceholderText(
            "Ключ сохранён в Windows" if has_api_key()
            else "Вставьте собственный OpenAI API-ключ"
        )

    def _build_synthesis(self):
        panel = self._section("Синтез речи", "Локальный Piper или голос Windows (если установлен нужный язык).")
        self.voice_engine = self._combo(
            [("Piper — нейросеть (локально)", "piper"), ("Windows SAPI (локально)", "windows")],
            self.cfg.get("voice_engine", "piper"),
        )
        self._row(panel, "Провайдер синтеза", "Piper загружает русскую модель Дмитрий при первом запуске.", self.voice_engine)
        self.voice_speed = self._slider(round(float(self.cfg.get("voice_speed", 1.0)) * 100), 70, 140)
        self._row(panel, "Скорость речи", "70–140% обычной скорости.", self.voice_speed)
        self.speech_status = QLabel(
            "Голоса Luxify / Fish Audio и облачные модели требуют отдельного доступа. "
            "В этой версии используются только установленные локальные голоса."
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
        info = QLabel("Параметры сохраняются в config.json. Для смены микрофона перезапускается распознавание.")
        info.setObjectName("Muted")
        info.setWordWrap(True)
        panel.addWidget(info)

    def _jump(self, index):
        section = self.sections[index]
        self.scroll.verticalScrollBar().setValue(section.y())
        for i, button in enumerate(self.section_buttons):
            button.setProperty("selected", i == index)
            button.style().unpolish(button)
            button.style().polish(button)

    def _filter(self, text):
        query = text.strip().lower()
        for (name, _), section, button in zip(self.SECTIONS, self.sections, self.section_buttons):
            match = not query or query in name.lower()
            section.setVisible(match)
            button.setVisible(match)

    def collect(self):
        return {
            "microphone_enabled": self.mic.isChecked(),
            "prefix_enabled": self.prefix.isChecked(),
            "wake_prefix": self.prefix_text.text().strip() or "джарвис, жарвис, jarvis",
            "language": self.language.currentData(),
            "whisper_beam_size": self.recognition_quality.currentData(),
            "microphone_device": self.mic_device.currentData(),
            "tts_enabled": self.tts.isChecked(),
            "voice_id": self.voice_id.currentData(),
            "voice_volume": self.voice_volume.value(),
            "voice_engine": self.voice_engine.currentData(),
            "voice_speed": round(self.voice_speed.value() / 100, 2),
            "confirm_desktop_actions": self.confirm.isChecked(),
            "confirm_yes_words": self.confirm_yes.text().strip(),
            "confirm_no_words": self.confirm_no.text().strip(),
            "confirmation_timeout": self.confirm_timeout.value(),
            "command_chain_words": self.chain_words.text().strip(),
            "ui_theme": self.theme.currentData(),
            "ui_accent": self.accent.currentData(),
            "ui_transparency": self.transparency.value(),
            "ui_animations": self.animations.isChecked(),
            "always_on_top": self.on_top.isChecked(),
            "autostart_windows": self.autostart.isChecked(),
            "minimize_to_tray": self.tray_on_close.isChecked(),
            "online_agent_enabled": self.online_agent_enabled.isChecked(),
            "online_model": self.online_model.currentData(),
            "online_timeout": self.online_timeout.value(),
        }
