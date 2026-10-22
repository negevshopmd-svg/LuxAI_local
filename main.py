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
from luxai.command_registry import CommandRegistry
from luxai.ui_commands import CommandsPage
from luxai.command_wizard import CommandWizard, is_create_command_request
from luxai.intent_routing import is_operational_request, routine_reply, suspicious_completion_reply
from luxai.ocr_setup import ensure_tesseract, find_tesseract, language_data_ready
from luxai.websites import website_plan
from luxai.voice_files import parse_open_user_file
from luxai.voice_shortcuts import keyboard_action_plan, command_capabilities_reply
from luxai.screen_interact import (
    _foreground_hwnd, _valid_external_window,
    is_screen_inspection_request, button_choice,
    inspect_screen_buttons, click_inspected_button,
)
from luxai.ui_screen_assist import ScreenAssistDialog
from luxai.weather_service import is_weather_question, get_weather_report
from luxai.voice_desktop import (
    is_dictation_start, is_dictation_stop, dictation_text,
    wants_screen_read, wants_discord_mic_mute,
    read_screen_locally, toggle_discord_microphone,
)
from luxai.desktop_actions import _type_unicode_windows

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
    wizard_plan_ready = Signal(str, object)
    macro_step_ready = Signal(int, bool, str)
    direct_task_ready = Signal(str, str, str)
    screen_inspection_ready = Signal(str, object, str)
    ocr_setup_ready = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Jarvis")
        self.resize(1120, 720)
        self.setMinimumSize(900, 600)
        self.cfg = load_config()
        self.agent = LocalAgent(self.cfg)
        self.command_registry = CommandRegistry()
        self.command_wizard = CommandWizard(
            self.command_registry, self.cfg.get("wake_prefix", "Jarvis"),
        )
        self.online_planner = OnlinePlanner(self.cfg)
        self.online_plan_ready.connect(self._on_online_plan)
        self.direct_task_ready.connect(self._on_direct_task_ready)
        self.screen_inspection_ready.connect(self._on_screen_inspection_ready)
        self.ocr_setup_ready.connect(self._on_ocr_setup_ready)
        self.macro_step_ready.connect(self._on_macro_step_ready)
        self.wizard_plan_ready.connect(self._on_wizard_plan)
        self.local_reply_ready.connect(self._on_local_reply)
        self.api_test_result.connect(self._on_api_test_result)
        self.tts_played.connect(self._on_tts_played)
        self._command_queue = []
        self._active_text = None
        self._processing = False
        self.dictation_active = False
        self._screen_snapshot = None
        self._pending_screen_click = None
        self._screen_dialog = None
        self._last_external_hwnd = 0
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
        self.mic_status.setText(self._provider_status_text())
        # Remember the last other foreground window while Jarvis is out of
        # focus; the screen panel itself must not become the click target.
        self._foreground_observer = QTimer(self)
        self._foreground_observer.setInterval(450)
        self._foreground_observer.timeout.connect(self._remember_external_window)
        self._foreground_observer.start()

        if self.cfg.get("microphone_enabled", True):
            self.start_listener()
        # OCR is part of Jarvis. If Update.bat couldn't finish installing it
        # (offline Windows or locked directory), retry without freezing GUI.
        if sys.platform == "win32":
            threading.Thread(
                target=self._ocr_setup_worker, daemon=True,
                name="JarvisBundledOCR",
            ).start()

    def _ocr_setup_worker(self):
        try:
            binary, languages = ensure_tesseract(
                self.cfg.get("tesseract_path", "")
            )
            success, message = True, (
                f"Встроенный Tesseract OCR готов: rus + eng. "
                f"Файлы: {binary.parent}"
            )
        except Exception as exc:
            success, message = False, (
                "Встроенный OCR пока недоступен: " + str(exc)[:250]
            )
        if not self._closed:
            try:
                self.ocr_setup_ready.emit(success, message)
            except RuntimeError:
                pass

    def _on_ocr_setup_ready(self, success, message):
        if self._closed:
            return
        self._ocr_ready = bool(success)
        if hasattr(self, "settings_panel"):
            try:
                self.settings_panel.set_ocr_status(success, message)
            except (AttributeError, RuntimeError):
                pass
        # Do not overwrite microphone/online command state mid-conversation.
        if not success and not self._processing:
            self.mic_status.setToolTip(message)

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
        self.home_page.screen_assist_button.clicked.connect(self.request_screen_inspection)
        self.volume.valueChanged.connect(self.sync_volume)
        self.pages.addWidget(self.home_page)

    def build_commands(self):
        """Show editable built-in and learned commands instead of only history."""
        self.commands_page = CommandsPage(self.command_registry)
        self.commands_page.run_requested.connect(self.run_saved_command)
        self.commands_page.voice_create_requested.connect(self.start_voice_command_wizard)
        self.pages.addWidget(self.commands_page)

    def _wizard_response(self, message):
        if not message:
            return
        self.append_message("Jarvis", message, "#a5b9dc")
        self.mic_status.setText("Создание голосовой команды")
        if self.cfg.get("tts_enabled", True):
            self._queue_speech(message, self.cfg.get("language", "ru"))

    def start_voice_command_wizard(self):
        if self.command_wizard.active:
            self._wizard_response("Команда уже создаётся. Продолжите или скажите «отмена».")
            return
        self.command_wizard.wake_prefix = self.cfg.get("wake_prefix", "Jarvis")
        self._wizard_response(self.command_wizard.start())

    def _wizard_handle_answer(self, text):
        response, online_description, saved = self.command_wizard.feed(text)
        self._wizard_response(response)
        if saved:
            self.commands_page.refresh()
        if online_description:
            if self.online_planner.enabled():
                history = tuple()
                threading.Thread(
                    target=self._wizard_online_thread,
                    args=(online_description, history),
                    daemon=True, name="JarvisVoiceCommandPlanner",
                ).start()
            else:
                response, _ = self.command_wizard.accept_online_plan(None)
                self._wizard_response(response)

    def _wizard_online_thread(self, description, history):
        try:
            proposal = self.online_planner.plan(description, history=history)
        except Exception:
            proposal = None
        if not self._closed:
            try:
                self.wizard_plan_ready.emit(description, proposal)
            except RuntimeError:
                pass

    def _on_wizard_plan(self, description, plan):
        if self._closed or not self.command_wizard.active:
            return
        if self.command_wizard.stage != "online" or self.command_wizard.description != description:
            return
        response, _ = self.command_wizard.accept_online_plan(plan)
        self._wizard_response(response)

    def run_saved_command(self, entry):
        if not isinstance(entry, dict) or not entry.get("enabled"):
            return
        self.show_page(3)  # command result is visible in the chat log
        phrase = entry.get("phrases", [""])
        if phrase:
            self.append_message("Tu", phrase[0], "#79a6ff")
            self.run_command(phrase[0])

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
        if hasattr(self, "command_wizard"):
            self.command_wizard.wake_prefix = self.cfg.get("wake_prefix", "Jarvis")

    def _provider_status_text(self):
        """Show configuration state, not an unverified claim of API connectivity."""
        if self.online_planner.enabled():
            provider = self.cfg.get("online_provider", "openai")
            name = PROVIDERS.get(provider, {}).get("label", provider)
            return f"Онлайн-ИИ настроен: {name} → Windows (проверить ключ)"
        if self.cfg.get("online_agent_enabled", False):
            return "Онлайн-ИИ включён, но ключ выбранного провайдера не сохранён"
        return "Облачный ИИ выключен — локальный режим"

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
        self.mic_status.setText("Настройки сохранены. " + self._provider_status_text())

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

        # Dictation explicitly bypasses AI and wake-word filtering. Only an
        # exact stop phrase ends it; other speech is typed into the other app.
        if self.dictation_active:
            self._type_voice_chunk(spoken)
            return

        # Wizard replies do not need the wake word: the assistant explicitly
        # asked the user to dictate a phrase or action in the next utterance.
        if self.command_wizard.active:
            self._wizard_handle_answer(spoken)
            return

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
        if self.dictation_active:
            self._type_voice_chunk(text)
            return
        if is_dictation_start(text):
            self.dictation_active = True
            prompt = (
                "Режим диктовки включён. Переключитесь в редактор текста. "
                "Я буду печатать услышанное в активном окне; "
                "скажите «стоп», чтобы закончить."
            )
            self.append_message("Jarvis", prompt, "#a5b9dc")
            self.mic_status.setText("Диктовка включена — скажите «стоп» для завершения")
            return
        if self.command_wizard.active:
            self._wizard_handle_answer(text)
            return
        if is_create_command_request(text):
            self.start_voice_command_wizard()
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

    def _type_voice_chunk(self, spoken):
        if is_dictation_stop(spoken):
            self.dictation_active = False
            answer = "Диктовка остановлена. Ничего больше не печатаю."
            self.append_message("Jarvis", answer, "#a5b9dc")
            self.mic_status.setText(answer)
            return
        from PySide6.QtWidgets import QApplication
        if self.isActiveWindow() or QApplication.activeWindow() is self:
            self.mic_status.setText(
                "Откройте и активируйте окно редактора. "
                "В окне Jarvis диктовка не печатает."
            )
            return
        part = dictation_text(spoken)
        if not part:
            return
        try:
            # Windows Unicode SendInput inserts the transcribed content as text,
            # without clipboard copies or LLM-generated arbitrary hotkeys.
            _type_unicode_windows(part[:350])
            self.mic_status.setText("Диктовка: текст отправлен в активное окно")
        except (OSError, ValueError) as error:
            self.mic_status.setText(f"Диктовка: текст не введён: {error}")
            self.append_message("Jarvis", f"Не удалось ввести текст: {error}", "#a5b9dc")

    def _direct_task_worker(self, text, mode):
        try:
            if mode == "weather":
                answer = get_weather_report(
                    text, default_city=self.cfg.get("weather_city", "Кишинёв")
                )
                if not answer:
                    answer = "Не удалось распознать запрос о погоде."
            elif mode == "screen":
                answer = read_screen_locally(self.cfg.get("tesseract_path", ""))
            else:
                answer = "Неизвестное локальное действие."
        except Exception as exc:
            if mode == "weather":
                answer = (
                    "Не удалось получить актуальный прогноз от Open-Meteo: "
                    f"{type(exc).__name__}: {str(exc)[:180]}. "
                    "Для прогноза нужен интернет, но API-ключ Gemini не требуется."
                )
            else:
                answer = f"Не удалось прочитать экран: {type(exc).__name__}: {str(exc)[:180]}"
        if not self._closed:
            try:
                self.direct_task_ready.emit(text, mode, answer)
            except RuntimeError:
                pass

    def _on_direct_task_ready(self, text, mode, answer):
        if self._closed or not self._processing or self._active_text != text:
            return
        self._current_route = "Open-Meteo" if mode == "weather" else "локальный OCR"
        self._resolved_command(text, answer)

    def _remember_external_window(self):
        if sys.platform != "win32" or self._closed:
            return
        try:
            hwnd = _foreground_hwnd()
            _valid_external_window(hwnd)
        except (OSError, ValueError):
            return
        self._last_external_hwnd = hwnd

    def request_screen_inspection(self, checked=False):
        """Home panel button: inspect the most recently focused other app."""
        self._start_screen_inspection("__GUI_SCREEN__")

    def _start_screen_inspection(self, original_text):
        if sys.platform != "win32":
            if original_text != "__GUI_SCREEN__":
                self._current_route = "Windows UI Automation"
                self._resolved_command(original_text, "Просмотр кнопок доступен только в Windows.")
            else:
                self.mic_status.setText("Просмотр кнопок доступен только в Windows.")
            return
        hwnd = _foreground_hwnd()
        try:
            _valid_external_window(hwnd)
        except (OSError, ValueError):
            hwnd = getattr(self, "_last_external_hwnd", 0)
        try:
            _valid_external_window(hwnd)
        except (OSError, ValueError):
            message = (
                "Не нашёл другое активное окно. Откройте нужную программу, "
                "переключитесь в неё и скажите «Жарвис, покажи кнопки на экране»."
            )
            if original_text == "__GUI_SCREEN__":
                self.mic_status.setText(message)
            else:
                self._current_route = "Windows UI Automation"
                self._resolved_command(original_text, message)
            return

        self._last_external_hwnd = hwnd
        self.mic_status.setText("Сканирую видимые кнопки Windows UI Automation…")
        try:
            from ctypes import wintypes
            import ctypes
            ctypes.windll.user32.SetForegroundWindow(wintypes.HWND(hwnd))
        except (AttributeError, OSError):
            pass

        def begin():
            if self._closed:
                return
            threading.Thread(
                target=self._screen_inspection_worker,
                args=(original_text, hwnd),
                daemon=True,
                name="JarvisScreenInspector",
            ).start()
        QTimer.singleShot(240, begin)

    def _screen_inspection_worker(self, text, hwnd):
        try:
            inspected = inspect_screen_buttons(hwnd)
            error = ""
        except Exception as exc:
            inspected = None
            error = f"{type(exc).__name__}: {str(exc)[:230]}"
        if not self._closed:
            try:
                self.screen_inspection_ready.emit(text, inspected, error)
            except RuntimeError:
                pass

    def _on_screen_inspection_ready(self, text, snapshot, error):
        if self._closed:
            return
        gui_request = text == "__GUI_SCREEN__"
        if not gui_request and (
            not self._processing or text != self._active_text
        ):
            return
        if error or snapshot is None:
            self._pending_screen_click = None
            answer = (
                "Не удалось проверить кнопки: " + (error or "нет доступного окна")
            )
            if gui_request:
                self.mic_status.setText(answer)
            else:
                self._current_route = "Windows UI Automation"
                self._resolved_command(text, answer)
            return

        self._screen_snapshot = snapshot
        if self._screen_dialog is None:
            panel = ScreenAssistDialog(snapshot, self)
            panel.click_requested.connect(
                lambda kind: self.run_command(
                    "Нажми да" if kind == "yes" else "Нажми нет"
                )
            )
            panel.refresh_requested.connect(self.request_screen_inspection)
            self._screen_dialog = panel
        else:
            self._screen_dialog.set_snapshot(snapshot)
        self._screen_dialog.show()
        self._screen_dialog.raise_()
        self._screen_dialog.activateWindow()
        count = len(snapshot.buttons)
        message = (
            f"Снимок экрана готов: {snapshot.title}. "
            f"Распознано доступных кнопок Да/Нет: {count}. "
            "Скажите «нажми да» или «нажми нет»."
        )
        self.mic_status.setText(message)
        auto_click = getattr(self, "_pending_screen_click", None)
        self._pending_screen_click = None
        if not gui_request and auto_click:
            # A direct «нажми да» triggers inspection automatically; the
            # subsequent modal confirmation still requires an explicit yes.
            self._current_route = "Windows UI Automation"
            self._resolved_command(
                text, self._click_screen_choice(auto_click),
            )
        elif not gui_request:
            self._current_route = "Windows UI Automation"
            self._resolved_command(text, message)

    def _click_screen_choice(self, choice):
        snapshot = getattr(self, "_screen_snapshot", None)
        if snapshot is None:
            return (
                "Сначала скажите «Покажи кнопки на экране», "
                "чтобы выбрать окно и кнопку."
            )
        panel = getattr(self, "_screen_dialog", None)
        if panel is not None:
            panel.hide()
        result = click_inspected_button(
            snapshot, choice, confirm=self.confirm_action,
        )
        if result.startswith("Нажал"):
            self._screen_snapshot = None
            if panel is not None:
                panel.close()
        elif panel is not None:
            panel.show()
        return result

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
            prefix = self.cfg.get("wake_prefix", "Jarvis")
            if self.command_registry.disabled_match(text, prefix):
                self._current_route = "выключенная команда"
                self._resolved_command(text, "Эта команда отключена в библиотеке команд.")
                return

            saved = self.command_registry.match(text, prefix)

            # Live weather and local screen OCR use dedicated, verifiable
            # services. They work even if Gemini is quota-blocked (HTTP 429).
            if is_weather_question(text):
                self.mic_status.setText("Получаю актуальный прогноз Open-Meteo…")
                threading.Thread(
                    target=self._direct_task_worker, args=(text, "weather"),
                    daemon=True, name="JarvisWeather",
                ).start()
                return
            if wants_screen_read(text):
                self.mic_status.setText("Читаю снимок экрана локально…")
                threading.Thread(
                    target=self._direct_task_worker, args=(text, "screen"),
                    daemon=True, name="JarvisScreenOCR",
                ).start()
                return
            if wants_discord_mic_mute(text):
                self._current_route = "Discord: глобальная комбинация клавиш"
                answer = toggle_discord_microphone(self.confirm_action)
                self._resolved_command(text, answer)
                return

            # Explicitly authored/learned personal commands are intentionally
            # instant, even if Gemini is enabled. Every unknown spoken action
            # is handed to Gemini first when the cloud key works.
            if saved is not None and not saved.get("builtin", True):
                self._execute_registered(text, saved)
                return

            choice = button_choice(text)
            if choice:
                import time
                snapshot = getattr(self, "_screen_snapshot", None)
                if snapshot is None or time.monotonic() - snapshot.captured > 90:
                    self._pending_screen_click = choice
                    self._start_screen_inspection(text)
                else:
                    self._current_route = "Windows UI Automation"
                    self._resolved_command(text, self._click_screen_choice(choice))
                return
            if is_screen_inspection_request(text):
                self._start_screen_inspection(text)
                return
            # Files explicitly named on the user's Desktop/Documents/Downloads
            # are opened by Windows directly; never reinterpret a file request
            # as launching Explorer, or ask a cloud model for an arbitrary path.
            file_plan = parse_open_user_file(text)
            if file_plan is not None:
                answer = self.agent.execute_plan(
                    text, file_plan, confirm_callback=self.confirm_action,
                )
                self._current_route = "локальные файлы Windows"
                self._resolved_command(text, answer or "Не удалось открыть файл.")
                return

            # Hotkeys and command-editor capabilities are known locally.
            keyboard = keyboard_action_plan(text)
            if keyboard is not None:
                # Only target the currently focused external application.
                if self.isActiveWindow():
                    answer = (
                        "Выберите окно другой программы и повторите команду. "
                        "В окно самого Jarvis клавиши не отправляются."
                    )
                else:
                    answer = self.agent.execute_plan(
                        text, keyboard, confirm_callback=self.confirm_action,
                    ) or "Клавиша не нажата."
                self._current_route = "локальная клавиатура"
                self._resolved_command(text, answer)
                return
            capabilities = command_capabilities_reply(text)
            if capabilities is not None:
                self._current_route = "каталог действий"
                self._resolved_command(text, capabilities)
                return

            site = website_plan(text)
            if site is not None:
                answer = self.agent.execute_plan(
                    text, site, confirm_callback=self.confirm_action,
                )
                self._current_route = "браузер HTTPS"
                self._resolved_command(text, answer or "Не удалось открыть сайт.")
                return

            quick = routine_reply(text, self.cfg.get("language", "ru"))
            if quick is not None:
                self.agent.remember(text, quick)
                self._current_route = "быстрый ответ"
                self._resolved_command(text, quick)
                return

            if self.online_planner.enabled():
                provider = self.cfg.get("online_provider", "gemini")
                label = PROVIDERS.get(provider, {}).get("label", provider)
                self.mic_status.setText(
                    f"Шаг 1/2: онлайн-планировщик {label} анализирует запрос…"
                )
                history = tuple(dict(msg) for msg in self.agent.history[-4:])
                threading.Thread(
                    target=self._online_thread, args=(text, history),
                    daemon=True, name="JarvisCloudFirst",
                ).start()
                return

            # No API key / offline: only safe deterministic actions are allowed
            # to report execution. Local GGUF never acts as a CMD terminal.
            self._safe_local_fallback(
                text, "Gemini не подключён или отсутствует API-ключ",
                saved=saved,
            )
        except Exception as exc:
            self._resolved_command(text, self._error_message(exc))

    def _execute_registered(self, text, saved):
        if saved.get("steps"):
            self._run_saved_steps(text, saved["steps"])
            return
        plan = {
            "action": saved["action"],
            "target": saved.get("target", ""),
            "location": saved.get("location", "desktop"),
            "appid": saved.get("appid"),
        }
        answer = self.agent.execute_plan(
            text, plan, confirm_callback=self.confirm_action,
        )
        self._current_route = "сохранённая команда"
        self._resolved_command(text, answer or "Команда не выполнена.")

    def _safe_local_fallback(self, text, reason="", saved=None):
        """Safe non-AI execution fallback; never synthesize fake file actions."""
        try:
            if saved is None:
                saved = self.command_registry.match(
                    text, self.cfg.get("wake_prefix", "Jarvis"),
                )
            if saved:
                self._execute_registered(text, saved)
                return
            answer = self.agent.handle_fast(
                text, confirm_callback=self.confirm_action,
            )
        except Exception as exc:
            answer = f"Локальная команда завершилась ошибкой: {exc}"
        if answer is not None:
            self._current_route = "локальный исполнитель (без Gemini)"
            self._resolved_command(text, answer)
            return
        if is_operational_request(text):
            self._current_route = "операция не выполнена"
            diagnostic = (": " + reason) if reason else ""
            self._resolved_command(
                text,
                "Системное действие НЕ выполнено" + diagnostic +
                ". Проверьте Gemini/API или создайте пользовательскую команду.",
            )
            return
        self._start_local_chat(text, reason=reason)

    def _run_saved_steps(self, text, steps):
        """Run a verified command's actions in order, with async QTimer pauses."""
        from luxai.action_catalog import validate_step
        try:
            verified = [validate_step(item) for item in steps]
            if not 1 <= len(verified) <= 8:
                raise ValueError("Недопустимое количество действий")
        except (TypeError, ValueError) as exc:
            self._current_route = "ошибка команды"
            self._resolved_command(text, f"Недопустимая команда: {exc}")
            return
        self._macro_context = {
            "text": text,
            "steps": verified,
            "index": 0,
            "messages": [],
        }
        self._current_route = "готовая команда"
        self._next_macro_step()

    def _next_macro_step(self):
        if self._closed or not self._processing:
            return
        ctx = getattr(self, "_macro_context", None)
        if not ctx:
            return
        if ctx["index"] >= len(ctx["steps"]):
            output = " ".join(ctx["messages"]) or "Команда выполнена."
            self._macro_context = None
            self._resolved_command(ctx["text"], output)
            return
        step = ctx["steps"][ctx["index"]]
        ctx["index"] += 1
        if step["action"] in ("wait_seconds", "wait_minutes"):
            count = int(step["target"])
            milliseconds = count * (60000 if step["action"] == "wait_minutes" else 1000)
            unit = "мин" if step["action"] == "wait_minutes" else "сек"
            self.mic_status.setText(f"Пауза {count} {unit} (шаг {ctx['index']})")
            QTimer.singleShot(milliseconds, self._next_macro_step)
            return
        if step["action"] == "tray_minimize":
            if not self.tray_icon or not QSystemTrayIcon.isSystemTrayAvailable():
                ctx["messages"].append("Системный трей недоступен.")
                result = " ".join(ctx["messages"])
                self._macro_context = None
                self._resolved_command(ctx["text"], result)
                return
            self.tray_icon.show()
            self.hide()
            ctx["messages"].append("Jarvis свёрнут в системный трей.")
            QTimer.singleShot(0, self._next_macro_step)
            return
        if step["action"] in {
            "run_cmd", "run_powershell", "app_volume", "voice_female",
            "sleep_pc",
        }:
            from luxai.action_catalog import CATALOG
            title = CATALOG[step["action"]]["title"]
            detail = step["target"]
            if step["action"] in ("run_cmd", "run_powershell", "sleep_pc") and not self.confirm_action(
                "⚠ Подтвердите действие: " + title +
                (("\n\n" + detail) if detail else "") +
                ("\n\nЭто ваша вручную сохранённая команда. "
                 "Она может изменить систему или файлы."
                 if step["action"] in ("run_cmd", "run_powershell") else "")
            ):
                ctx["messages"].append("Действие отменено.")
                result = " ".join(ctx["messages"])
                self._macro_context = None
                self._resolved_command(ctx["text"], result)
                return
            self.mic_status.setText(f"Выполняется шаг {ctx['index']}: {title}")
            threading.Thread(
                target=self._macro_worker,
                args=(dict(step), ctx["index"]),
                daemon=True,
                name="JarvisManualAction",
            ).start()
            return
        try:
            self.agent.last_execution_success = False
            answer = self.agent.execute_plan(
                ctx["text"], step, confirm_callback=self.confirm_action,
            )
            if answer:
                ctx["messages"].append(str(answer))
            if not self.agent.last_execution_success:
                ctx["messages"].append(
                    f"Последующие действия не выполнены (шаг {ctx['index']})."
                )
                output = " ".join(ctx["messages"])
                self._macro_context = None
                self._resolved_command(ctx["text"], output)
                return
        except Exception as exc:
            ctx["messages"].append(f"Шаг {ctx['index']}: {exc}")
            output = " ".join(ctx["messages"])
            self._macro_context = None
            self._resolved_command(ctx["text"], output)
            return
        # Schedule instead of recursion so UI remains responsive.
        QTimer.singleShot(0, self._next_macro_step)

    def _macro_worker(self, step, index):
        from luxai.desktop_actions import execute_desktop_step
        try:
            output = execute_desktop_step(step)
            ok = True
        except Exception as exc:
            output = str(exc)
            ok = False
        if not self._closed:
            try:
                self.macro_step_ready.emit(index, ok, output)
            except RuntimeError:
                pass

    def _on_macro_step_ready(self, index, ok, message):
        ctx = getattr(self, "_macro_context", None)
        if self._closed or not ctx or not self._processing or ctx["index"] != index:
            return
        if message:
            ctx["messages"].append(message if ok else f"Шаг {index}: {message}")
        if not ok:
            ctx["messages"].append("Оставшиеся действия не выполнены.")
            result = " ".join(ctx["messages"])
            self._macro_context = None
            self._resolved_command(ctx["text"], result)
        else:
            QTimer.singleShot(0, self._next_macro_step)

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
        provider = self.cfg.get("online_provider", "openai")
        label = PROVIDERS.get(provider, {}).get("label", provider)
        if not proposal:
            error = self.online_planner.last_error or "не удалось получить план"
            self.mic_status.setText("Ошибка онлайн-планировщика: " + error)
            self._safe_local_fallback(text, f"{label}: {error}")
            return

        if (
            proposal.get("action") == "reply"
            and is_operational_request(text)
            and suspicious_completion_reply(proposal.get("reply", ""))
        ):
            # An LLM claiming an action succeeded is NOT an execution trace.
            self._safe_local_fallback(
                text,
                f"{label} прислал текст вместо исполняемого плана",
            )
            return

        self.mic_status.setText(
            f"Шаг 2/2: локальный исполнитель выполняет план {label}…"
        )
        try:
            answer = self.agent.execute_plan(
                text, proposal, confirm_callback=self.confirm_action,
            )
        except Exception as exc:
            answer = f"Локальный исполнитель завершился ошибкой: {exc}"
        if answer is not None:
            if getattr(self.agent, "last_execution_success", False):
                learned = self.command_registry.learn(
                    text, proposal, success=True,
                )
                if learned:
                    self.commands_page.refresh()
            self._current_route = "Gemini → Windows" if provider == "gemini" else (label + " → Windows")
            self._resolved_command(text, answer)
        else:
            self._safe_local_fallback(
                text, f"план {label} не поддержан локальным исполнителем",
            )

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
        # Ordinary app launches, documents, sites, text and hotkeys execute
        # immediately. Previous config.json files used
        # confirm_desktop_actions=True by default; ignore that legacy option
        # so users don't inherit endless prompts after the upgrade.
        # Explicit risky operations still present a dialog even when the
        # general confirmation toggle is disabled.
        risk = "⚠" in str(description)
        if not risk and not self.cfg.get("confirm_all_actions", False):
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

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(build_styles())
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
