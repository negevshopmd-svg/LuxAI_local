import re
import sys, os, json, html, urllib.request
import queue
import threading
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
from luxai.ui_home import HomePage
from luxai.ui_sidebar import NavigationSidebar
from luxai.styles import build_styles
from luxai.online_agent import OnlinePlanner
from luxai.secure_keys import store_api_key, get_api_key
from luxai.api_verification import check_api_key_detailed
from luxai.api_providers import PROVIDERS

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "config.json"


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
            self.status.emit("Микрофон включён — локальное распознавание")
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
            self.status.emit("Микрофон выключен")

class MainWindow(QMainWindow):
    online_plan_ready = Signal(str, object)
    local_reply_ready = Signal(str, str)
    api_test_result = Signal(str, bool, str, object)
    tts_played = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Jarvis")
        self.resize(1120, 720)
        self.setMinimumSize(900, 600)
        self.cfg = load_config()
        self.agent = LocalAgent(self.cfg)
        self.online_planner = OnlinePlanner(self.cfg)
        self.online_plan_ready.connect(self._on_online_plan)
        self.local_reply_ready.connect(self._on_local_reply)
        self.api_test_result.connect(self._on_api_test_result)
        self.tts_played.connect(self._on_tts_played)
        self._command_queue = []
        self._active_text = None
        self._processing = False
        self._current_route = ""
        self._closed = False
        self._api_test_running = False
        self._api_test_requested_model = None
        self._speech_queue = queue.Queue(maxsize=8)
        self._speech_thread = threading.Thread(target=self._speech_loop, daemon=True, name="JarvisSpeech")
        self._speech_thread.start()
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

        self.sidebar = NavigationSidebar()
        self.sidebar.page_selected.connect(self.show_page)
        self.nav_buttons = self.sidebar.nav_buttons
        outer.addWidget(self.sidebar)

        content = QWidget()
        self.content_frame = content
        content.setObjectName("MainContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 18)
        content_layout.setSpacing(14)
        header = QHBoxLayout()
        self.header_title = QLabel("Jarvis   |   Главная")
        self.header_title.setObjectName("HeaderTitle")
        self.header_title.setStyleSheet("font-size:17px;font-weight:650;")
        header.addWidget(self.header_title)
        header.addStretch()
        self.mic_status = QLabel("●  Локальный режим")
        self.mic_status.setStyleSheet("color:#8ea2c2;padding-right:8px;")
        header.addWidget(self.mic_status)
        self.header_mic_button = QPushButton("◉" if self.cfg.get("microphone_enabled", True) else "◌")
        self.header_mic_button.setObjectName("HeaderMic")
        self.header_mic_button.setFixedSize(42, 40)
        self.header_mic_button.setToolTip("Включить или выключить микрофон")
        self.header_mic_button.setCheckable(True)
        self.header_mic_button.setChecked(self.cfg.get("microphone_enabled", True))
        self.header_mic_button.clicked.connect(self.toggle_microphone_from_header)
        header.addWidget(self.header_mic_button)
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
        """Create the separate Luxify-inspired home widget."""
        self.home_page = HomePage(self.cfg)
        self.home_history = self.home_page.home_history
        self.home_prefix = self.home_page.home_prefix
        self.home_quiet = self.home_page.home_quiet
        self.home_avatar = self.home_page.home_avatar
        self.home_top = self.home_page.home_top
        self.volume = self.home_page.volume
        self.volume_label = self.home_page.volume_label
        self.avatar = self.home_page.avatar

        self.home_prefix.toggled.connect(self.sync_prefix)
        self.home_quiet.toggled.connect(self.sync_quiet)
        self.home_avatar.toggled.connect(self.sync_animation)
        self.home_top.toggled.connect(self.set_always_on_top)
        self.volume.valueChanged.connect(self.sync_volume)
        self.pages.addWidget(self.home_page)

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
            on_test_online=self.test_online_api,
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
        titles = ["Главная", "Команды", "Дополнения", "Jarvis AI", "Настройки"]
        self.header_title.setText("Jarvis   |   " + titles[index])
        self.sidebar.set_active(index)

    def toggle_microphone_from_header(self, enabled):
        self.settings_panel.mic.setChecked(bool(enabled))
        self.apply_settings()

    def save_settings(self, *_):
        if not hasattr(self, "settings_panel"):
            return
        self.cfg.update(self.settings_panel.collect())
        key_field = self.settings_panel.api_key_entry
        new_key = key_field.text().strip()
        if new_key:
            try:
                store_api_key(new_key, self.settings_panel.online_provider.currentData())
                key_field.clear()
                self.settings_panel.refresh_key_status()
            except (ValueError, OSError, RuntimeError) as exc:
                self.mic_status.setText("Ошибка сохранения ключа API.")
                print(f"API key storage failed: {type(exc).__name__}")
        save_config(self.cfg)
        if self.agent:
            self.agent.update_config(self.cfg)
        self.online_planner.update_config(self.cfg)

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
        if hasattr(self, "volume"):
            self.volume.blockSignals(True)
            self.volume.setValue(int(self.cfg.get("voice_volume", 80)))
            self.volume.blockSignals(False)
            self.volume_label.setText(f"{self.volume.value()}%")
        if hasattr(self, "header_mic_button"):
            mic_enabled = self.cfg.get("microphone_enabled", True)
            self.header_mic_button.blockSignals(True)
            self.header_mic_button.setChecked(mic_enabled)
            self.header_mic_button.setText("◉" if mic_enabled else "◌")
            self.header_mic_button.blockSignals(False)
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

    def test_online_api(self):
        """Test the text currently in the key field (or stored key), without saving."""
        if self._api_test_running or self._closed:
            return
        settings = self.settings_panel.collect()
        provider = settings.get("online_provider", "openai")
        if provider not in PROVIDERS:
            self.settings_panel.show_test_result("Выберите поставщика API.", False)
            return
        # Do not save the field or update any persisted settings during a test.
        key = self.settings_panel.api_key_entry.text().strip() or get_api_key(provider)
        if not key:
            message = "Введите новый API-ключ или сохраните его перед проверкой."
            self.settings_panel.show_test_result(message, False)
            self.mic_status.setText(message)
            return
        self._api_test_running = True
        self._api_test_requested_model = settings.get("online_model")
        self.settings_panel.set_test_busy(True)
        self.mic_status.setText("Проверяю подключение к API…")
        threading.Thread(
            target=self._test_online_thread,
            args=(provider, settings, key),
            name="JarvisApiTest",
            daemon=True,
        ).start()

    def _test_online_thread(self, provider, settings, key):
        try:
            valid, message, suggested_model = check_api_key_detailed(settings, key)
        except Exception:
            valid, message, suggested_model = (
                False, "Ошибка проверки API. Проверьте настройки и подключение.", None,
            )
        if not self._closed:
            try:
                self.api_test_result.emit(provider, valid, message, suggested_model)
            except RuntimeError:
                pass

    def _on_api_test_result(self, provider, valid, message, suggested_model):
        self._api_test_running = False
        if self._closed or not hasattr(self, "settings_panel"):
            return
        panel = self.settings_panel
        # Do not alter a model/provider changed while the asynchronous test ran.
        if panel.online_provider.currentData() != provider:
            panel.set_test_busy(False)
            panel.refresh_key_status()
            return
        if (
            valid and suggested_model and
            panel.online_model.text().strip() == self._api_test_requested_model and
            suggested_model != panel.online_model.text().strip()
        ):
            panel.online_model.setText(suggested_model)
        panel.show_test_result(message, valid)
        self.mic_status.setText(message)

    def preview_voice(self):
        self.save_settings()
        language = self.cfg.get("language", "ru")
        example = {
            "ru": "Здравствуйте. Я Джарвис, ваш голосовой помощник.",
            "en": "Hello. I am Jarvis, your voice assistant.",
            "ro": "Salut. Sunt Jarvis, asistentul tău vocal.",
        }.get(language, "Здравствуйте. Я Джарвис, ваш голосовой помощник.")
        self.mic_status.setText("Воспроизвожу пример голоса…")
        self._queue_speech(example, language)

    def apply_appearance(self):
        """Apply the shared look to every page, including the separate home."""
        theme = self.cfg.get("ui_theme", "dark")
        accent = self.cfg.get("ui_accent", "#3978f6")
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_styles(theme, accent))

        # SettingsPanel has a local frame style; keep it synchronized too.
        if hasattr(self, "settings_panel"):
            card_bg = "#ffffff" if theme == "light" else "#1b1d20"
            card_border = "#cdd6e4" if theme == "light" else "#30343a"
            heading_color = "#162034" if theme == "light" else "#f0f2f6"
            for section in self.settings_panel.sections:
                section.setStyleSheet(
                    f"QFrame#SettingsCard {{background:{card_bg}; border:1px solid {card_border}; border-radius:15px;}}"
                    "QFrame#SettingsCard QLabel {background:transparent; border:0;}"
                    "QFrame#SettingsCard QCheckBox {background:transparent; border:0;}"
                )
                for child in section.findChildren(QLabel):
                    if child.text() in [name for name, _ in self.settings_panel.SECTIONS]:
                        child.setStyleSheet(
                            f"font-size:18px; font-weight:700; color:{heading_color};"
                        )

        self.setWindowOpacity(
            max(0.65, 1.0 - float(self.cfg.get("ui_transparency", 0)) / 100)
        )
        self.avatar.set_theme(theme)
        self.avatar.set_animated(bool(self.cfg.get("ui_animations", True)))
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
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
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

    def sync_volume(self, value):
        if hasattr(self, "volume_label"):
            self.volume_label.setText(f"{value}%")
        if hasattr(self, "settings_panel"):
            self.settings_panel.voice_volume.setValue(value)
            self.save_settings()

    def sync_animation(self, enabled):
        self.avatar.set_animated(enabled)
        if hasattr(self, "settings_panel"):
            self.settings_panel.animations.setChecked(enabled)
            self.save_settings()

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
            self.mic_status.setText("●  Микрофон выключен")

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
            configured = str(self.cfg.get("wake_prefix", "Jarvis") or "Jarvis")
            # Accept multiple names separated by commas, plus common Whisper variants.
            aliases = [name.strip() for name in configured.split(",") if name.strip()]
            aliases += ["Jarvis", "Джарвис", "Жарвис", "Джервис", "Жервис"]
            prefix = aliases[0]
            variants = "|".join(
                re.escape(name) for name in sorted(set(aliases), key=len, reverse=True)
            )
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
        color_line = "#4388f9" if who.startswith("Tu") else "#868d98"
        self.home_history.append(
            f'<p style="margin:5px 0; padding-left:10px; border-left:2px solid {color_line};">'
            f'<span style="color:{color_line};font-weight:600;">{html.escape(who)}</span>  {safe}</p>'
        )
        self.history.append((who, str(text)))

    def run_command(self, text):
        """Queue multi-part commands, routing unfamiliar ones off the UI thread."""
        text = str(text or "").strip()
        if not text:
            return
        self.save_settings()
        if len(self._command_queue) >= 8:
            self.mic_status.setText("Очередь заполнена. Подождите завершения команды.")
            return
        pieces = [text]
        connectors = [
            word.strip() for word in self.cfg.get("command_chain_words", "и затем, потом").split(",")
            if word.strip()
        ]
        for connector in connectors:
            next_parts = []
            for part in pieces:
                next_parts.extend(
                    re.split(r"\s+" + re.escape(connector) + r"\s+", part, flags=re.IGNORECASE)
                )
            pieces = next_parts
        pieces = [part.strip() for part in pieces if part.strip()]
        if not pieces or len(pieces) > 4:
            pieces = [text]
        self._command_queue.append({"parts": pieces, "answers": [], "routes": []})
        self._dispatch_command()

    def _dispatch_command(self):
        if self._processing or self._closed or not self._command_queue:
            return
        current = self._command_queue[0]
        if not current["parts"]:
            self._finish_command_group()
            return
        text = current["parts"].pop(0)
        self._active_text = text
        self._processing = True
        try:
            # Fast deterministic commands never need a cloud round trip or LLM.
            answer = self.agent.handle_fast(text, confirm_callback=self.confirm_action)
            if answer is not None:
                self._current_route = "быстро"
                self._resolved_command(text, answer)
                return
        except Exception as exc:
            self._resolved_command(text, self._error_message(exc))
            return

        if self.online_planner.enabled():
            provider = self.cfg.get("online_provider", "openai")
            label = PROVIDERS.get(provider, {}).get("label", provider)
            self.mic_status.setText(f"Онлайн-агент {label} обрабатывает команду…")
            history = tuple(dict(msg) for msg in self.agent.history[-4:])
            threading.Thread(
                target=self._online_thread, args=(text, history),
                daemon=True, name="JarvisOnlinePlanner",
            ).start()
        else:
            reason = (
                "нет сохранённого ключа онлайн-агента"
                if self.cfg.get("online_agent_enabled", False)
                else "облачный помощник выключен"
            )
            self._start_local_chat(text, reason=reason)

    def _online_thread(self, text, history):
        try:
            proposal = self.online_planner.plan(text, history=history)
        except Exception:
            proposal = None
        if not self._closed:
            try:
                self.online_plan_ready.emit(text, proposal)
            except RuntimeError:
                pass

    def _on_online_plan(self, text, proposal):
        if self._closed or not self._processing or text != self._active_text:
            return
        answer = None
        if proposal:
            try:
                answer = self.agent.execute_plan(
                    text, proposal, confirm_callback=self.confirm_action,
                )
            except Exception:
                answer = None
        if answer is not None:
            provider = self.cfg.get("online_provider", "openai")
            self._current_route = "онлайн: " + PROVIDERS.get(provider, {}).get("label", provider)
            self._resolved_command(text, answer)
        else:
            self._start_local_chat(text, reason="облачный ответ недоступен")

    def _start_local_chat(self, text, reason=""):
        if not self.cfg.get("local_llm_fallback_enabled", True):
            self._current_route = "без тяжёлой модели"
            answer = (
                "Облачный агент недоступен. Проверьте API-ключ и соединение. "
                "Быстрые голосовые команды продолжают работать."
                if self.cfg.get("language") == "ru" else
                "Agentul online nu este disponibil. Verifică cheia API și conexiunea."
            )
            self._resolved_command(text, answer)
            return
        self._current_route = "локальный GGUF"
        suffix = f" ({reason})" if reason else ""
        self.mic_status.setText("Локальный ИИ готовит ответ…" + suffix)
        threading.Thread(
            target=self._local_thread, args=(text,),
            daemon=True, name="JarvisLocalChat",
        ).start()

    def _local_thread(self, text):
        try:
            answer = self.agent.handle_chat(text)
        except Exception as exc:
            answer = self._error_message(exc)
        if not self._closed:
            try:
                self.local_reply_ready.emit(text, answer)
            except RuntimeError:
                pass

    def _on_local_reply(self, text, answer):
        if not self._closed and self._processing and text == self._active_text:
            self._resolved_command(text, answer)

    def _error_message(self, exc):
        if self.cfg.get("language") == "ru":
            return f"Ошибка: {exc}"
        return f"Eroare: {exc}"

    def _resolved_command(self, text, answer):
        if not self._command_queue:
            return
        group = self._command_queue[0]
        group["answers"].append(str(answer or ""))
        group["routes"].append(self._current_route or "локально")
        self._current_route = ""
        self._processing = False
        self._active_text = None
        if any(word in str(answer).lower() for word in ("отмен", "anulat", "cancelled")):
            group["parts"].clear()
        QTimer.singleShot(0, self._dispatch_command)

    def _finish_command_group(self):
        if not self._command_queue:
            return
        group = self._command_queue.pop(0)
        result = "\n".join(answer for answer in group["answers"] if answer).strip()
        routes = list(dict.fromkeys(route for route in group["routes"] if route))
        if result:
            self.append_message("Jarvis", result, "#a5b9dc")
            self.mic_status.setText("Готово: " + (", ".join(routes) or "локально"))
            if self.cfg.get("tts_enabled", True):
                self._queue_speech(result, self.cfg.get("language", "ru"))
        QTimer.singleShot(0, self._dispatch_command)

    def _queue_speech(self, text, language):
        if self._closed:
            return
        try:
            self._speech_queue.put_nowait((text, language))
        except queue.Full:
            # Prefer the latest relevant reply when many messages arrive rapidly.
            try:
                self._speech_queue.get_nowait()
                self._speech_queue.put_nowait((text, language))
            except queue.Empty:
                pass

    def _speech_loop(self):
        while True:
            task = self._speech_queue.get()
            if task is None:
                return
            text, language = task
            try:
                played = speak(text, enabled=True, language=language)
            except Exception:
                played = False
            if not self._closed:
                try:
                    self.tts_played.emit(played)
                except RuntimeError:
                    pass

    def _on_tts_played(self, played):
        if not played:
            self.mic_status.setText("Нет подходящего голоса. Проверьте voice_error.log.")

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
        self._closed = True
        try:
            self._speech_queue.put_nowait(None)
        except queue.Full:
            pass
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
app.setFont(QFont("Segoe UI", 10))
app.setStyleSheet(build_styles())
w = MainWindow()
w.show()
sys.exit(app.exec())
