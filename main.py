import re
import sys, os, json, html, urllib.request
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFontDatabase, QFont, QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QLineEdit, QTextEdit, QFileDialog, QMessageBox,
    QComboBox, QStackedWidget, QFrame, QSlider, QSizePolicy, QSystemTrayIcon, QMenu, QStyle
)

from luxai.agent import LocalAgent
from luxai.voice import VoiceListener, speak
from luxai.screen import capture_screen, read_screen_text
from luxai.settings_panel import SettingsPanel

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "config.json"

STYLE = """
QWidget { background:#101319; color:#e9edf5; font-family:'Fuzzy Bubbles','Segoe UI'; font-size:13px; }
QMainWindow { background:#101319; }
QFrame#Sidebar { background:#151a23; border-right:1px solid #252c39; }
QFrame#Card { background:#1b2029; border:1px solid #303744; border-radius:15px; }
QLabel#PageTitle { font-size:23px; font-weight:700; color:#f4f6fb; }
QLabel#Muted { color:#a2a9b7; }
QPushButton { background:#252c38; color:#e9edf5; border:1px solid #363f4e; border-radius:9px; padding:9px 13px; }
QPushButton:hover { background:#30394a; border-color:#4d7fff; }
QPushButton#Primary { background:#3978f6; border:0; color:white; font-weight:600; }
QPushButton#Primary:hover { background:#4d88ff; }
QPushButton#Nav { text-align:left; padding:12px 14px; background:transparent; border:0; border-radius:9px; color:#b7bfcc; }
QPushButton#Nav:hover { background:#222936; color:white; }
QPushButton#Nav[active="true"] { background:#252d3a; color:white; border-left:3px solid #4b83ff; }
QLineEdit, QTextEdit, QComboBox { background:#131820; border:1px solid #343c4a; border-radius:9px; padding:10px; selection-background-color:#3978f6; }
QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border-color:#4b83ff; }
QCheckBox { spacing:10px; color:#cbd2dd; }
QCheckBox::indicator { width:17px; height:17px; }
QCheckBox::indicator:unchecked { background:#252c38; border:1px solid #4a5362; border-radius:8px; }
QCheckBox::indicator:checked { background:#3978f6; border:1px solid #3978f6; border-radius:8px; }
QSlider::groove:horizontal { height:5px; background:#343c4a; border-radius:2px; }
QSlider::sub-page:horizontal { background:#3978f6; border-radius:2px; }
QSlider::handle:horizontal { background:white; width:15px; margin:-5px 0; border-radius:7px; }
QScrollBar:vertical { background:#151a23; width:9px; margin:2px; }
QScrollBar::handle:vertical { background:#3a4352; min-height:25px; border-radius:4px; }
"""

def load_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_config(cfg):
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

def card():
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(13)
    return frame, layout

class VoiceWorker(QThread):
    transcript = Signal(str)
    status = Signal(str)
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.listener = None
    def run(self):
        try:
            self.listener = VoiceListener(
                model_path=self.cfg.get("whisper_model_path") or self.cfg.get("whisper_model") or "small",
                prefix_enabled=self.cfg.get("prefix_enabled", False),
                prefix=self.cfg.get("wake_prefix", "Jarvis"),
                language=self.cfg.get("language", "auto"),
                microphone_device=self.cfg.get("microphone_device", -1),
                beam_size=self.cfg.get("whisper_beam_size", 1),
            )
            self.status.emit("Microfon activ — ascultare locală")
            for text in self.listener.listen():
                if self.isInterruptionRequested():
                    break
                if text:
                    self.transcript.emit(text)
        except Exception as e:
            self.status.emit(f"Microfon/Whisper: {e}")
        finally:
            if self.listener:
                self.listener.stop()
            self.status.emit("Microfon oprit")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Jarvis")
        self.resize(1120, 720)
        self.setMinimumSize(900, 600)
        self.cfg = load_config()
        self.agent = LocalAgent(self.cfg)
        self.worker = None
        self.history = []
        self.nav_buttons = []
        self.pending_confirmation_dialog = None
        self.pending_confirmation_result = None
        self._quitting = False
        self.tray_icon = None

        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(176)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 18, 12, 14)
        side.setSpacing(8)

        brand = QHBoxLayout()
        logo = QLabel("◉")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedSize(42, 42)
        logo.setStyleSheet("background:#2f70e8;color:white;border-radius:21px;font-size:25px;font-weight:700;")
        brand_name = QLabel("NEXORA")
        brand_name.setStyleSheet("font-size:17px;font-weight:800;letter-spacing:1px;")
        brand.addWidget(logo)
        brand.addWidget(brand_name)
        brand.addStretch()
        side.addLayout(brand)
        side.addSpacing(24)

        for label, page in [("⌂   Acasă", 0), ("☷   Comenzi", 1), ("▦   Instrumente", 2), ("▣   Jarvis", 3), ("☷   Setări", 4)]:
            btn = QPushButton(label)
            btn.setObjectName("Nav")
            btn.setProperty("active", page == 0)
            btn.clicked.connect(lambda checked=False, p=page: self.show_page(p))
            side.addWidget(btn)
            self.nav_buttons.append(btn)
        side.addStretch()
        collapse = QPushButton("◁   Свернуть")
        collapse.setObjectName("Nav")
        collapse.clicked.connect(lambda: sidebar.setFixedWidth(72 if sidebar.width() > 100 else 176))
        side.addWidget(collapse)
        outer.addWidget(sidebar)

        content = QWidget()
        content.setStyleSheet("background:#101319;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 18)
        content_layout.setSpacing(14)
        header = QHBoxLayout()
        self.header_title = QLabel("Jarvis   |   Acasă")
        self.header_title.setStyleSheet("font-size:17px;font-weight:650;")
        header.addWidget(self.header_title)
        header.addStretch()
        self.mic_status = QLabel("●  Локальный режим")
        self.mic_status.setStyleSheet("color:#8ea2c2;padding-right:8px;")
        header.addWidget(self.mic_status)
        content_layout.addLayout(header)

        self.pages = QStackedWidget()
        content_layout.addWidget(self.pages, 1)
        outer.addWidget(content, 1)

        self.build_home()
        self.build_commands()
        self.build_addons()
        self.build_chat()
        self.build_settings()
        self._setup_tray()
        self.apply_appearance()
        self.show_page(0)

        if self.cfg.get("microphone_enabled", True):
            self.start_listener()

    def build_home(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(16)
        top = QHBoxLayout()
        intro = QVBoxLayout()
        title = QLabel("Bine ai venit în Jarvis!")
        title.setStyleSheet("font-size:23px;font-weight:700;")
        subtitle = QLabel("Asistentul tău local este gata de lucru.")
        subtitle.setObjectName("Muted")
        intro.addWidget(title)
        intro.addWidget(subtitle)
        top.addLayout(intro, 1)
        self.avatar = QLabel(" ")
        self.avatar.setFixedSize(150, 150)
        self.avatar.setStyleSheet("background:qradialgradient(cx:0.8,cy:0.5,radius:1,stop:0 #4788ff,stop:0.38 #3569c4,stop:0.68 #203454,stop:1 #101319);border-radius:75px;")
        top.addWidget(self.avatar)
        layout.addLayout(top)

        row = QHBoxLayout()
        history_frame, history_layout = card()
        history_title = QLabel("История команд")
        history_title.setStyleSheet("font-size:17px;font-weight:700;")
        history_layout.addWidget(history_title)
        self.home_history = QTextEdit()
        self.home_history.setReadOnly(True)
        self.home_history.setPlaceholderText("Bine ai venit în Jarvis!\nÎncă nu există comenzi.")
        self.home_history.setMinimumHeight(190)
        history_layout.addWidget(self.home_history)
        row.addWidget(history_frame, 3)

        control_frame, control_layout = card()
        control_title = QLabel("Панель управления")
        control_title.setStyleSheet("font-size:17px;font-weight:700;")
        control_layout.addWidget(control_title)
        self.home_prefix = QCheckBox("Режим префикса")
        self.home_prefix.setChecked(self.cfg.get("prefix_enabled", False))
        self.home_prefix.toggled.connect(self.sync_prefix)
        control_layout.addWidget(self.home_prefix)
        self.home_quiet = QCheckBox("Тихий режим (без ответа vocal)")
        self.home_quiet.setChecked(not self.cfg.get("tts_enabled", True))
        self.home_quiet.toggled.connect(self.sync_quiet)
        control_layout.addWidget(self.home_quiet)
        self.home_avatar = QCheckBox("Анимация аватара")
        self.home_avatar.setChecked(True)
        self.home_avatar.toggled.connect(lambda on: self.avatar.setVisible(on))
        control_layout.addWidget(self.home_avatar)
        self.home_top = QCheckBox("Окно поверх остальных")
        self.home_top.setChecked(False)
        self.home_top.toggled.connect(self.set_always_on_top)
        control_layout.addWidget(self.home_top)
        volume_row = QHBoxLayout()
        volume_row.addWidget(QLabel("Громкость"))
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(80)
        volume_row.addWidget(self.volume, 1)
        self.volume_label = QLabel("80%")
        self.volume.valueChanged.connect(lambda v: self.volume_label.setText(f"{v}%"))
        volume_row.addWidget(self.volume_label)
        control_layout.addLayout(volume_row)
        row.addWidget(control_frame, 2)
        layout.addLayout(row, 1)

        quick = QHBoxLayout()
        for text, page_num in [("Открыть Jarvis", 3), ("Настройки", 4), ("Дополнения", 2)]:
            b = QPushButton(text)
            b.clicked.connect(lambda checked=False, p=page_num: self.show_page(p))
            quick.addWidget(b)
        layout.addLayout(quick)
        self.pages.addWidget(page)

    def build_commands(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("Команды")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        desc = QLabel("История распознанных и введённых команд.")
        desc.setObjectName("Muted")
        layout.addWidget(desc)
        frame, box = card()
        self.command_history = QTextEdit()
        self.command_history.setReadOnly(True)
        self.command_history.setPlaceholderText("Здесь появятся выполненные команды и ответы.")
        box.addWidget(self.command_history)
        layout.addWidget(frame, 1)
        self.pages.addWidget(page)

    def build_addons(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("Дополнения")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        desc = QLabel("Инструменты, доступные локально на этом компьютере.")
        desc.setObjectName("Muted")
        layout.addWidget(desc)
        for name, description, action in [
            ("Снимок экрана", "Сохранить снимок текущего экрана на этом компьютере.", self.screen_action),
            ("Распознавание текста (OCR)", "Сделать снимок и извлечь из него видимый текст.", self.ocr_action),
            ("Выбрать локальную AI-модель", "Указать путь к файлу модели .gguf на компьютере.", self.pick_model),
        ]:
            frame, box = card()
            row = QHBoxLayout()
            col = QVBoxLayout()
            heading = QLabel(name)
            heading.setStyleSheet("font-size:16px;font-weight:650;")
            detail = QLabel(description)
            detail.setObjectName("Muted")
            detail.setWordWrap(True)
            col.addWidget(heading)
            col.addWidget(detail)
            row.addLayout(col, 1)
            button = QPushButton("Запустить")
            button.setObjectName("Primary")
            button.clicked.connect(action)
            row.addWidget(button)
            box.addLayout(row)
            layout.addWidget(frame)
        layout.addStretch()
        self.pages.addWidget(page)

    def build_chat(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("Jarvis")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        subtitle = QLabel("Общение с локальным помощником. Ваши модели и настройки остаются на компьютере.")
        subtitle.setObjectName("Muted")
        layout.addWidget(subtitle)
        frame, box = card()
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Jarvis появится здесь после первого сообщения.")
        box.addWidget(self.log, 1)
        row = QHBoxLayout()
        self.command = QLineEdit()
        self.command.setPlaceholderText("Напишите сообщение или команду…")
        self.command.returnPressed.connect(self.submit_command)
        row.addWidget(self.command, 1)
        self.send = QPushButton("Отправить")
        self.send.setObjectName("Primary")
        self.send.clicked.connect(self.submit_command)
        row.addWidget(self.send)
        box.addLayout(row)
        layout.addWidget(frame, 1)
        self.pages.addWidget(page)

    def build_settings(self):
        self.settings_panel = SettingsPanel(
            self.cfg,
            on_save=self.apply_settings,
            on_pick_model=self.pick_model,
            on_test_voice=self.preview_voice,
        )
        self.mic = self.settings_panel.mic
        self.prefix = self.settings_panel.prefix
        self.tts = self.settings_panel.tts
        self.prefix_text = self.settings_panel.prefix_text
        self.language = self.settings_panel.language
        self.model_label = self.settings_panel.model_label
        self.pages.addWidget(self.settings_panel)

    def show_page(self, index):
        self.pages.setCurrentIndex(index)
        titles = ["Главная", "Команды", "Дополнения", "Jarvis", "Настройки"]
        self.header_title.setText("Jarvis   |   " + titles[index])
        for i, button in enumerate(self.nav_buttons):
            button.setProperty("active", i == index)
            button.style().unpolish(button)
            button.style().polish(button)

    def save_settings(self, *_):
        if not hasattr(self, "settings_panel"):
            return
        self.cfg.update(self.settings_panel.collect())
        save_config(self.cfg)
        if self.agent:
            self.agent.update_config(self.cfg)

    def apply_settings(self, *_):
        """Save settings and apply them to running services where supported."""
        old = dict(self.cfg)
        self.save_settings()
        self.apply_appearance()
        if old.get("autostart_windows", False) != self.cfg.get("autostart_windows", False):
            self._set_autostart(self.cfg.get("autostart_windows", False))
        if hasattr(self, "home_prefix"):
            self.home_prefix.blockSignals(True)
            self.home_prefix.setChecked(self.cfg.get("prefix_enabled", False))
            self.home_prefix.blockSignals(False)
        if hasattr(self, "home_quiet"):
            self.home_quiet.blockSignals(True)
            self.home_quiet.setChecked(not self.cfg.get("tts_enabled", True))
            self.home_quiet.blockSignals(False)
        if hasattr(self, "home_top"):
            self.home_top.blockSignals(True)
            self.home_top.setChecked(self.cfg.get("always_on_top", False))
            self.home_top.blockSignals(False)
        if hasattr(self, "home_avatar"):
            self.home_avatar.blockSignals(True)
            self.home_avatar.setChecked(self.cfg.get("ui_animations", True))
            self.home_avatar.blockSignals(False)
        if self.tray_icon:
            if self.cfg.get("minimize_to_tray", False) and QSystemTrayIcon.isSystemTrayAvailable():
                self.tray_icon.show()
            else:
                self.tray_icon.hide()
        changed_audio = any(
            old.get(k) != self.cfg.get(k)
            for k in ("language", "microphone_device", "whisper_beam_size")
        )
        enabled = self.cfg.get("microphone_enabled", True)
        if changed_audio or old.get("microphone_enabled", True) != enabled:
            self.stop_listener()
            if enabled:
                self.start_listener()
        elif self.worker and self.worker.listener:
            self.worker.listener.prefix_enabled = self.cfg.get("prefix_enabled", False)
            self.worker.listener.prefix = self.cfg.get("wake_prefix", "Jarvis")
        self.mic_status.setText("Настройки сохранены.")

    def preview_voice(self):
        self.save_settings()
        language = self.cfg.get("language", "ru")
        example = {
            "ru": "Здравствуйте. Я Джарвис, ваш голосовой помощник.",
            "en": "Hello. I am Jarvis, your voice assistant.",
            "ro": "Salut. Sunt Jarvis, asistentul tău vocal.",
        }.get(language, "Здравствуйте. Я Джарвис, ваш голосовой помощник.")
        self.mic_status.setText("Проверяю голос…")
        if speak(example, enabled=True, language=language):
            self.mic_status.setText("Голос воспроизведён.")
        else:
            self.mic_status.setText("Голос недоступен: откройте voice_error.log.")

    def apply_appearance(self):
        theme = self.cfg.get("ui_theme", "dark")
        accent = self.cfg.get("ui_accent", "#3978f6")
        style = STYLE
        if theme == "light":
            # Replace all dark surfaces and main text colours for a readable light theme.
            replacements = {
                "#101319": "#f5f7fb",
                "#151a23": "#eef1f7",
                "#1b2029": "#ffffff",
                "#131820": "#ffffff",
                "#252c38": "#e3e8f2",
                "#252d3a": "#dce7ff",
                "#222936": "#e6ecf6",
                "#303744": "#ccd4e0",
                "#343c4a": "#b4becc",
                "#363f4e": "#b4becc",
                "#e9edf5": "#20293b",
                "#f4f6fb": "#162034",
                "#b7bfcc": "#344054",
                "#cbd2dd": "#344054",
                "#a2a9b7": "#667085",
            }
            for old, new in replacements.items():
                style = style.replace(old, new)
        style = style.replace("#3978f6", accent).replace("#4b83ff", accent)
        app = QApplication.instance()
        if app:
            app.setStyleSheet(style)
        self.setWindowOpacity(max(0.65, 1.0 - float(self.cfg.get("ui_transparency", 0)) / 100))
        self.avatar.setVisible(bool(self.cfg.get("ui_animations", True)))
        self.setWindowFlag(
            Qt.WindowType.WindowStaysOnTopHint,
            bool(self.cfg.get("always_on_top", False)),
        )
        if self.isVisible():
            self.show()

    def _set_autostart(self, enabled):
        if sys.platform != "win32":
            return
        try:
            import winreg
            key_path = r"Software\\Microsoft\\Windows\\CurrentVersion\\Run"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                if enabled:
                    executable = str(BASE / ".venv" / "Scripts" / "pythonw.exe")
                    command = f'"{executable}" "{BASE / "main.py"}"'
                    winreg.SetValueEx(key, "LuxAI_Jarvis", 0, winreg.REG_SZ, command)
                else:
                    try:
                        winreg.DeleteValue(key, "LuxAI_Jarvis")
                    except FileNotFoundError:
                        pass
        except Exception as exc:
            QMessageBox.warning(self, "Автозапуск", f"Не удалось изменить автозапуск: {exc}")

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray_icon = QSystemTrayIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon), self
        )
        self.tray_icon.setToolTip("Jarvis")
        menu = QMenu(self)
        show_action = QAction("Открыть Jarvis", self)
        show_action.triggered.connect(self.show_from_tray)
        menu.addAction(show_action)
        quit_action = QAction("Выход", self)
        quit_action.triggered.connect(self.quit_from_tray)
        menu.addAction(quit_action)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(
            lambda reason: self.show_from_tray()
            if reason == QSystemTrayIcon.ActivationReason.Trigger else None
        )
        if self.cfg.get("minimize_to_tray", False):
            self.tray_icon.show()

    def show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_from_tray(self):
        self._quitting = True
        self.close()

    def sync_prefix(self, enabled):
        # Keep both controls synchronized without restarting/blocking the audio thread.
        if hasattr(self, "prefix") and self.prefix.isChecked() != enabled:
            self.prefix.blockSignals(True)
            self.prefix.setChecked(enabled)
            self.prefix.blockSignals(False)
        if hasattr(self, "home_prefix") and self.home_prefix.isChecked() != enabled:
            self.home_prefix.blockSignals(True)
            self.home_prefix.setChecked(enabled)
            self.home_prefix.blockSignals(False)
        if hasattr(self, "mic"):
            self.save_settings()
        if self.worker and self.worker.listener:
            self.worker.listener.prefix_enabled = bool(enabled)
            self.worker.listener.prefix = (self.cfg.get("wake_prefix", "Jarvis") or "Jarvis").strip().lower()

    def sync_quiet(self, enabled):
        if hasattr(self, "tts"):
            self.tts.setChecked(not enabled)
        if hasattr(self, "mic"):
            self.save_settings()

    def set_always_on_top(self, enabled):
        self.settings_panel.on_top.setChecked(enabled)
        self.save_settings()
        self.apply_appearance()

    def toggle_mic(self, enabled):
        self.save_settings()
        if enabled:
            self.start_listener()
        else:
            self.stop_listener()
            self.mic_status.setText("●  Microfon oprit")

    def start_listener(self):
        if self.worker and self.worker.isRunning():
            return
        self.save_settings()
        # Always pass the latest saved prefix settings to a newly started listener.
        self.worker = VoiceWorker(dict(self.cfg))
        self.worker.transcript.connect(self.handle_voice)
        self.worker.status.connect(self.mic_status.setText)
        self.worker.start()

    def stop_listener(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait(2500)
            if self.worker.isRunning():
                self.worker.terminate()
                self.worker.wait(1000)

    def pick_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "Alege model GGUF", "", "Modele GGUF (*.gguf)")
        if path:
            self.cfg["llm_model_path"] = path
            save_config(self.cfg)
            self.agent.update_config(self.cfg)
            if hasattr(self, "model_label"):
                self.model_label.setText(Path(path).name)
            self.mic_status.setText("Model selectat — se va încărca la prima comandă.")

    def handle_voice(self, text):
        # Voice answers can approve/deny an action while its confirmation dialog is open.
        if self.pending_confirmation_dialog is not None:
            answer = self._parse_confirmation(text)
            if answer is not None:
                self.pending_confirmation_result = answer
                self.pending_confirmation_dialog.done(1 if answer else 0)
                return

        spoken = text.strip()
        if not spoken:
            return
        # Always record what was recognized, including speech without the wake prefix.
        self.append_message("Tu (voce)", spoken, "#79a6ff")

        if self.cfg.get("prefix_enabled", False):
            prefix = (self.cfg.get("wake_prefix", "Jarvis") or "Jarvis").strip()
            # Whisper may transcribe the same wake word as Жарвис, Джарвис or Jarvis.
            # Match only the initial name, then pass the rest of the utterance as a command.
            aliases = [prefix, "Jarvis", "Джарвис", "Жарвис", "Джервис", "Жервис"]
            variants = "|".join(re.escape(name) for name in aliases if name)
            match = re.match(
                r"^\s*(?:" + variants + r")(?=$|[\s,.:;!?—–-])",
                spoken,
                flags=re.IGNORECASE,
            )
            if not match:
                reminder = (f"Для активации скажите «{prefix}» перед командой." if self.cfg.get("language") == "ru" else f"Pentru activare, începe comanda cu «{prefix}».")
                self.mic_status.setText(reminder)
                self.append_message("Jarvis", reminder, "#a5b9dc")
                return
            spoken = spoken[match.end():].lstrip(" ,.!?:;-")
            if not spoken:
                reminder = ("Слушаю. Произнесите команду после имени." if self.cfg.get("language") == "ru" else "Te ascult. Spune comanda după prefix.")
                self.mic_status.setText(reminder)
                self.append_message("Jarvis", reminder, "#a5b9dc")
                return
        self.mic_status.setText("Команда распознана — выполняю…" if self.cfg.get("language") == "ru" else "Comandă vocală recunoscută — procesez…")
        self.run_command(spoken)

    def _parse_confirmation(self, text):
        t = text.lower().strip()
        t = html.unescape(t)
        yes = ["yes", "yeah", "yep", "да", "ага", "конечно", "подтверждаю",
               "давай", "так", "так, да", "так пожалуйста", "da", "да", "sigur", "confirm", "confirmă", "permite", "desigur", "ok", "okay"]
        no = ["no", "nope", "нет", "не надо", "отмена", "отмени", "не разрешаю",
              "nu", "nu permite", "anulează", "anuleaza", "refuz", "stop"]
        yes.extend(word.strip().lower() for word in self.cfg.get("confirm_yes_words", "").split(",") if word.strip())
        no.extend(word.strip().lower() for word in self.cfg.get("confirm_no_words", "").split(",") if word.strip())
        normalized = re.sub(r"[.!?,;:]+", "", t).strip()
        if normalized in yes:
            return True
        if normalized in no:
            return False
        return None

    def submit_command(self):
        text = self.command.text().strip()
        if not text:
            return
        self.command.clear()
        self.append_message("Tu", text, "#79a6ff")
        self.run_command(text)

    def append_message(self, who, text, color):
        safe = html.escape(str(text)).replace("\n", "<br>")
        entry = f'<p style="margin:8px 0"><b style="color:{color}">{html.escape(who)}:</b><br>{safe}</p>'
        self.log.append(entry)
        self.command_history.append(entry)
        self.home_history.append(entry)
        self.history.append((who, str(text)))

    def run_command(self, text):
        self.save_settings()
        try:
            pieces = [text]
            connectors = [
                token.strip() for token in
                self.cfg.get("command_chain_words", "и затем, потом").split(",")
                if token.strip()
            ]
            for connector in connectors:
                split_parts = []
                for part in pieces:
                    split_parts.extend(re.split(r"\\s+" + re.escape(connector) + r"\\s+", part, flags=re.IGNORECASE))
                pieces = split_parts
            pieces = [piece.strip() for piece in pieces if piece.strip()]
            if not pieces or len(pieces) > 4:
                pieces = [text]
            responses = []
            for part in pieces:
                answer = self.agent.handle(part, confirm_callback=self.confirm_action)
                responses.append(answer)
                if "отмен" in answer.lower() or "anulat" in answer.lower() or "cancelled" in answer.lower():
                    break
            result = "\\n".join(responses)
        except Exception as e:
            result = f"Ошибка: {e}" if self.cfg.get("language") == "ru" else f"Eroare: {e}"
        self.append_message("Jarvis", result, "#a5b9dc")
        if self.cfg.get("tts_enabled", True):
            played = speak(result, enabled=True, language=self.cfg.get("language", "ru"))
            if not played:
                self.mic_status.setText(
                    "Нет русской голосовой модели. Проверьте voice_error.log и папку voices."
                    if self.cfg.get("language") == "ru"
                    else "Vocea nu este disponibilă. Verifică voice_error.log și folderul voices."
                )

    def confirm_action(self, description):
        if not self.cfg.get("confirm_desktop_actions", True):
            return True
        dialog = QMessageBox(self)
        russian = self.cfg.get("language") == "ru"
        dialog.setWindowTitle("Подтвердите действие" if russian else "Confirmă acțiunea")
        if russian:
            dialog.setText(f"Джарвис хочет выполнить действие:\n\n{description}\n\nСкажите «да» или «нет», либо нажмите кнопку.")
            dialog.setInformativeText("Голосовое подтверждение доступно, пока микрофон включён.")
        else:
            dialog.setText(f"Jarvis dorește să execute:\n\n{description}\n\nSpune „da” sau „nu” ori alege un buton.")
            dialog.setInformativeText("Răspuns vocal disponibil cât timp microfonul este activ.")
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText("Да" if russian else "Da")
        dialog.button(QMessageBox.StandardButton.No).setText("Нет" if russian else "Nu")
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        self.pending_confirmation_dialog = dialog
        self.pending_confirmation_result = None
        QTimer.singleShot(
            max(5, min(180, int(self.cfg.get("confirmation_timeout", 30)))) * 1000,
            lambda: dialog.reject() if dialog.isVisible() else None,
        )
        try:
            clicked = dialog.exec()
            if self.pending_confirmation_result is not None:
                return self.pending_confirmation_result
            return clicked == QMessageBox.StandardButton.Yes
        finally:
            self.pending_confirmation_dialog = None
            self.pending_confirmation_result = None

    def screen_action(self):
        try:
            path = capture_screen()
            QMessageBox.information(self, "Captură ecran", f"Captură salvată local:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Captură ecran", str(e))

    def ocr_action(self):
        try:
            path = capture_screen()
            text = read_screen_text(path, self.cfg.get("tesseract_path", ""))
            dialog = QMessageBox(self)
            dialog.setWindowTitle("Text detectat pe ecran")
            dialog.setText(text[:4000] or "(Nu s-a detectat text.)")
            dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
            dialog.exec()
            if text:
                self.append_message("OCR", text[:10000], "#a5b9dc")
        except Exception as e:
            QMessageBox.warning(self, "OCR", f"OCR nu este configurat sau a eșuat:\n{e}")

    def closeEvent(self, event):
        if (
            not self._quitting
            and self.cfg.get("minimize_to_tray", False)
            and self.tray_icon
            and QSystemTrayIcon.isSystemTrayAvailable()
        ):
            self.hide()
            event.ignore()
            return
        if self.tray_icon:
            self.tray_icon.hide()
        self.stop_listener()
        event.accept()

def load_project_font():
    """Download Fuzzy Bubbles into the project on first launch and register it in Qt."""
    font_dir = BASE / "assets" / "fonts"
    font_dir.mkdir(parents=True, exist_ok=True)
    fonts = {
        "FuzzyBubbles-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/fuzzybubbles/FuzzyBubbles-Regular.ttf",
        "FuzzyBubbles-Bold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/fuzzybubbles/FuzzyBubbles-Bold.ttf",
    }
    loaded = False
    for filename, url in fonts.items():
        path = font_dir / filename
        try:
            if not path.exists() or path.stat().st_size < 1000:
                request = urllib.request.Request(url, headers={"User-Agent": "NexoraAI/1.0"})
                with urllib.request.urlopen(request, timeout=12) as response:
                    data = response.read()
                if len(data) < 1000:
                    raise ValueError("Fișierul fontului descărcat pare invalid.")
                path.write_bytes(data)
            if QFontDatabase.addApplicationFont(str(path)) >= 0:
                loaded = True
        except Exception as exc:
            print(f"Nu am putut încărca fontul {filename}: {exc}")
    return loaded

app = QApplication(sys.argv)
app.setStyle("Fusion")
load_project_font()
app.setStyleSheet(STYLE)
available_fonts = {family.lower() for family in QFontDatabase.families()}
app.setFont(QFont("Fuzzy Bubbles" if "fuzzy bubbles" in available_fonts else "Segoe UI", 10))
w = MainWindow()
w.show()
sys.exit(app.exec())
