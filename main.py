import re
import sys, os, json, html, urllib.request
import queue
import threading
import hashlib
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
from luxai.voices import stop_speaking as stop_voice_output
from luxai.voice_rules import is_stop_speech_command, is_hallucinated_outro
from luxai.screen import capture_screen, read_screen_text
from luxai.settings_panel import SettingsPanel
from luxai.ui_home import HomePage
from luxai.ui_sidebar import NavigationSidebar
from luxai.styles import build_styles
from luxai.ui_i18n import get_ui_language, set_ui_language, translate_widgets, tr, normalize_language
from luxai.response_language import reply_language
from luxai.online_agent import OnlinePlanner
from luxai.secure_keys import store_api_key, get_api_key, key_storage_status
from luxai.api_verification import check_api_key_detailed
from luxai.cloud_status import cloud_status_text
from luxai.api_providers import PROVIDERS
from luxai.command_registry import CommandRegistry
from luxai.ui_commands import CommandsPage
from luxai.command_wizard import CommandWizard, is_create_command_request
from luxai.discord_research import (
    detect_research_dm_request, prepare_discord_draft, submit_discord_draft,
)
from luxai.discord_screen_review import (
    detect_discord_screen_review, looks_like_discord_screen_review,
    run_discord_screen_review,
)
from luxai.macro_planner import needs_live_macro_planning
from luxai.action_catalog import describe_step
from luxai.visual_click import (
    capture_window, find_visual_target, click_visual_target, parse_click_target,
)
from luxai.intent_routing import is_operational_request, routine_reply, suspicious_completion_reply
from luxai.ocr_setup import ensure_tesseract, find_tesseract, language_data_ready
from luxai.websites import website_plan
from luxai.voice_files import parse_open_user_file
from luxai.voice_shortcuts import keyboard_action_plan, command_capabilities_reply
from luxai.voice_actions import parse_action_sequence
from luxai.selection import (
    selected_text_intent, copy_selected_text, finish_selected_copy,
    extractive_fallback,
)
from luxai.screen_interact import (
    _foreground_hwnd, _valid_external_window,
    is_screen_inspection_request, button_choice,
    inspect_screen_buttons, click_inspected_button,
)
from luxai.ui_screen_assist import ScreenAssistDialog
from luxai.weather_service import is_weather_question, get_weather_report
from luxai.voice_desktop import (
    is_dictation_start, is_dictation_stop, dictation_text,
    wants_screen_read, wants_discord_mic_mute, wants_discord_mic_visual_click,
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
    """Write preferences atomically, so an interrupted shutdown won't erase them."""
    target = CONFIG.with_name(CONFIG.name + ".tmp")
    try:
        target.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(target, CONFIG)
    finally:
        target.unlink(missing_ok=True)

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
    state = Signal(str, object)
    level = Signal(float)
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.listener = None
    def stop_capture(self):
        if self.listener is not None:
            self.listener.stop()

    def run(self):
        failed = False
        try:
            from luxai.voice import ModelLoadError
            if self.isInterruptionRequested():
                return
            model_choice = self.cfg.get("whisper_model_path") or self.cfg.get("whisper_model") or "small"
            params = {
                "prefix_enabled": self.cfg.get("prefix_enabled", False),
                "prefix": self.cfg.get("wake_prefix", "Jarvis"),
                "language": self.cfg.get("language", "auto"),
                "microphone_device": self.cfg.get("microphone_device", -1),
                "beam_size": self.cfg.get("whisper_beam_size", 1),
                "microphone_name": self.cfg.get("microphone_name", ""),
                "microphone_hostapi": self.cfg.get("microphone_hostapi", ""),
                "sensitivity": self.cfg.get("microphone_sensitivity", 1.0),
                "speech_pause": self.cfg.get("speech_pause_seconds", 2.3),
                "status_callback": lambda event, details: self.state.emit(event, details),
                "level_callback": self.level.emit,
            }
            try:
                self.listener = VoiceListener(model_path=model_choice, **params)
            except ModelLoadError as exc:
                if str(model_choice) == "small" or self.isInterruptionRequested():
                    raise
                self.status.emit(
                    f"Whisper {model_choice} unavailable ({type(exc).__name__}); trying small..."
                )
                self.listener = VoiceListener(model_path="small", **params)
            if self.isInterruptionRequested():
                self.listener.stop()
                return
            for text in self.listener.listen():
                if self.isInterruptionRequested():
                    break
                if text:
                    self.transcript.emit(text)
        except Exception as e:
            failed = True
            self.status.emit(f"Microfon/Whisper: {e}")
            self.state.emit("error", {"message": str(e)})
        finally:
            if self.listener:
                self.listener.stop()
            if not failed:
                self.state.emit("stopped", {})


class AudioDiagnosticsWorker(QThread):
    completed = Signal(dict)
    level = Signal(float)

    def __init__(self, config, probe=False):
        super().__init__()
        self.config = dict(config)
        self.probe = probe
        self.stop_event = threading.Event()

    def stop_capture(self):
        self.stop_event.set()

    def run(self):
        try:
            from luxai.diagnostics import collect_diagnostics, microphone_probe
            report = collect_diagnostics(self.config)
            if self.probe and not self.stop_event.is_set():
                report["microphone_probe"] = microphone_probe(
                    device=self.config.get("microphone_device", -1),
                    microphone_name=self.config.get("microphone_name", ""),
                    microphone_hostapi=self.config.get("microphone_hostapi", ""),
                    duration=4.0, level_callback=self.level.emit, stop_event=self.stop_event,
                )
            self.completed.emit(report)
        except Exception as exc:
            self.completed.emit({"error": type(exc).__name__})

class MainWindow(QMainWindow):
    online_plan_ready = Signal(str, object)
    local_reply_ready = Signal(str, str)
    api_test_result = Signal(str, bool, str, object)
    cloud_check_result = Signal(str, str, bool, str)
    tts_played = Signal(bool, int)
    wizard_plan_ready = Signal(str, object)
    macro_step_ready = Signal(int, bool, str)
    visual_step_ready = Signal(int, object, str)
    discord_draft_ready = Signal(int, object, str)
    discord_contact_prompt = Signal(object)
    discord_open_ready = Signal(int, object, str)
    research_notepad_ready = Signal(int, object, str)
    discord_send_ready = Signal(int, object, str)
    discord_review_ready = Signal(int, object, str)
    discord_mic_visual_ready = Signal(str, str)
    visual_reasoner_ready = Signal(str, str)
    direct_macro_ready = Signal(str, object, str)
    direct_task_ready = Signal(str, str, str)
    screen_inspection_ready = Signal(str, object, str)
    ocr_setup_ready = Signal(bool, str)
    selected_summary_ready = Signal(str, str, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Jarvis")
        self.resize(1120, 720)
        self.setMinimumSize(900, 600)
        self.cfg = load_config()
        set_ui_language(self.cfg.get("ui_language", "ru"))
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
        self.selected_summary_ready.connect(self._on_selected_summary_ready)
        self.macro_step_ready.connect(self._on_macro_step_ready)
        self.visual_step_ready.connect(self._on_visual_step_ready)
        self.discord_draft_ready.connect(self._on_discord_draft_ready)
        self.discord_contact_prompt.connect(self._on_discord_contact_prompt)
        self.discord_open_ready.connect(self._on_discord_open_ready)
        self.research_notepad_ready.connect(self._on_research_notepad_ready)
        self.discord_send_ready.connect(self._on_discord_send_ready)
        self.discord_review_ready.connect(self._on_discord_review_ready)
        self.discord_mic_visual_ready.connect(self._on_discord_mic_visual_ready)
        self.visual_reasoner_ready.connect(self._on_visual_reasoner_ready)
        self.direct_macro_ready.connect(self._on_direct_macro_ready)
        self.wizard_plan_ready.connect(self._on_wizard_plan)
        self.local_reply_ready.connect(self._on_local_reply)
        self.api_test_result.connect(self._on_api_test_result)
        self.cloud_check_result.connect(self._on_cloud_check_result)
        self.tts_played.connect(self._on_tts_played)
        self._command_queue = []
        self._active_text = None
        self._processing = False
        self.dictation_active = False
        self._screen_snapshot = None
        self._pending_screen_click = None
        self._screen_dialog = None
        self._last_external_hwnd = 0
        self._last_visual_goal = None
        self._last_visual_goal_at = 0.0
        self._current_route = ""
        self._closed = False
        self._api_test_running = False
        self._api_test_requested_model = None
        self._api_test_requested_key = None
        self._cloud_probe_signature = None
        self._cloud_verified_signature = None
        self._cloud_probe_failed = False
        self._cloud_probe_message = ""
        self._cloud_probe_running = False
        self._cloud_first_check_done = False
        self._speech_queue = queue.Queue(maxsize=8)
        self._speech_generation = 0
        self._speech_thread = threading.Thread(target=self._speech_loop, daemon=True, name="JarvisSpeech")
        self._speech_thread.start()
        self.worker = None
        self.audio_diagnostics_worker = None
        self._pending_microphone_test = None
        self._probe_resume_listener = False
        self._audio_event = "stopped"
        self._audio_details = {}
        self._last_microphone_probe = None
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
        self.apply_ui_language()
        self.show_page(0)
        self.mic_status.setText(self._provider_status_text())
        self._on_audio_state("stopped", {})
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
        self.home_page.selection_summary_button.clicked.connect(
            lambda checked=False: self.run_command(
                "Жарвис, перескажи выделенный текст"
            )
        )
        self.home_page.microphone_test_button.clicked.connect(self.test_microphone)
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
            proposal = self.online_planner.plan_macro(description)
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
        response, _ = self.command_wizard.accept_online_plan(
            plan, error=self.online_planner.last_error if plan is None else ""
        )
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
        cloud_frame, cloud_box = card()
        self.cloud_indicator = QLabel("●  Облачный AI: не проверен")
        self.cloud_indicator.setObjectName("CloudAIStatus")
        self.cloud_indicator.setStyleSheet("color:#c6a35f;font-size:15px;font-weight:650;")
        cloud_box.addWidget(self.cloud_indicator)
        self.cloud_details = QLabel("Ключ и связь с API будут проверены через выбранный провайдер.")
        self.cloud_details.setWordWrap(True)
        self.cloud_details.setObjectName("Muted")
        cloud_box.addWidget(self.cloud_details)
        self.cloud_check_button = QPushButton("Проверить облачный AI")
        self.cloud_check_button.setObjectName("Primary")
        self.cloud_check_button.clicked.connect(lambda: self._start_cloud_check(force=True))
        cloud_box.addWidget(self.cloud_check_button)
        layout.addWidget(cloud_frame)
        self._update_cloud_indicator()
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
            on_install_local_ai=self.install_local_ai,
        )
        self.mic = self.settings_panel.mic
        self.prefix = self.settings_panel.prefix
        self.tts = self.settings_panel.tts
        self.prefix_text = self.settings_panel.prefix_text
        self.language = self.settings_panel.language
        self.model_label = self.settings_panel.model_label
        self.pages.addWidget(self.settings_panel)
        self.settings_panel.test_microphone.clicked.connect(self.test_microphone)
        self.settings_panel.restart_microphone.clicked.connect(self.restart_microphone)
        self.settings_panel.export_diagnostics.clicked.connect(self.export_diagnostics)

    def apply_ui_language(self):
        """Change UI language in-place without touching the voice/Whisper language."""
        language = normalize_language(self.cfg.get("ui_language", "ru"))
        set_ui_language(language)
        self.sidebar.set_language(language)
        if getattr(self, "_tray_show_action", None) is not None:
            self._tray_show_action.setText(tr("Открыть Jarvis", language))
            self._tray_quit_action.setText(tr("Выход", language))
        self.commands_page.interface_language = language
        self.commands_page.refresh()
        translate_widgets(self, language)
        self._update_cloud_indicator()
        self.show_page(self.pages.currentIndex())
        if hasattr(self, "_audio_event"):
            self._on_audio_state(self._audio_event, self._audio_details)

    def show_page(self, index):
        self.pages.setCurrentIndex(index)
        titles = ["Главная", "Команды", "Дополнения", "Jarvis AI", "Настройки"]
        self.header_title.setText("Jarvis   |   " + tr(titles[index]))
        self.sidebar.set_active(index)
        if index == 2 and hasattr(self, "cloud_indicator"):
            self._update_cloud_indicator()
            if not self._cloud_first_check_done:
                self._cloud_first_check_done = True
                self._start_cloud_check()

    def toggle_microphone_from_header(self, enabled):
        self.settings_panel.mic.setChecked(bool(enabled))
        self.apply_settings()

    def _cloud_signature(self):
        """Bind a status to exactly the stored key, provider, model and endpoint."""
        cfg = self.cfg
        provider = cfg.get("online_provider", "openai")
        if provider not in PROVIDERS:
            return None
        key = get_api_key(provider)
        if not key:
            return None
        canonical = "|".join((
            provider, str(cfg.get("online_model", "")),
            str(cfg.get("online_custom_url", "")),
            key, str(bool(cfg.get("online_agent_enabled", False))),
        ))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _update_cloud_indicator(self):
        if not hasattr(self, "cloud_indicator"):
            return
        provider = self.cfg.get("online_provider", "openai")
        name = PROVIDERS.get(provider, {}).get("label", provider)
        signature = self._cloud_signature()
        storage = key_storage_status(provider) if provider in PROVIDERS else "missing"
        if not self.cfg.get("online_agent_enabled", False):
            state = "disabled"
        elif not signature:
            state = "missing"
        elif self._cloud_probe_running and signature == self._cloud_probe_signature:
            state = "checking"
        elif self._cloud_verified_signature == signature:
            state = "online"
        elif self._cloud_probe_failed and signature == self._cloud_probe_signature:
            state = "offline"
        else:
            state = "unchecked"
        detail = ""
        if state == "missing" and storage == "unreadable":
            detail = {
                "ru": "Сохранённый ключ не читается в текущей учётной записи Windows.",
                "en": "The saved key cannot be decrypted by this Windows user.",
                "ro": "Cheia salvată nu poate fi decriptată de acest utilizator Windows.",
            }.get(get_ui_language(), "Saved key unreadable.")
        if state == "offline":
            detail = self._cloud_probe_message
        title, body, color = cloud_status_text(state, name, get_ui_language(), detail)
        self.cloud_indicator.setText(title)
        self.cloud_indicator.setStyleSheet(f"color:{color};font-size:15px;font-weight:650;")
        self.cloud_details.setText(body)

    def _start_cloud_check(self, force=False):
        if self._closed or self._cloud_probe_running:
            return
        signature = self._cloud_signature()
        if not self.cfg.get("online_agent_enabled", False) or not signature:
            self._update_cloud_indicator()
            return
        if not force and self._cloud_verified_signature == signature:
            return
        provider = self.cfg.get("online_provider", "openai")
        key = get_api_key(provider)
        settings = dict(self.cfg)
        self._cloud_probe_signature = signature
        self._cloud_probe_failed = False
        self._cloud_probe_running = True
        self._update_cloud_indicator()
        self.cloud_check_button.setEnabled(False)
        threading.Thread(
            target=self._cloud_check_worker,
            args=(provider, signature, settings, key),
            name="JarvisCloudHealth", daemon=True,
        ).start()

    def _cloud_check_worker(self, provider, signature, settings, key):
        try:
            valid, message, model = check_api_key_detailed(settings, key)
        except Exception:
            valid, message, model = False, "Ошибка подключения к облачному API.", None
        if not self._closed:
            try:
                self.cloud_check_result.emit(provider, signature, valid, message)
            except RuntimeError:
                pass

    def _on_cloud_check_result(self, provider, signature, valid, message):
        self._cloud_probe_running = False
        self.cloud_check_button.setEnabled(True)
        if self._closed or signature != self._cloud_signature() or (
            provider != self.cfg.get("online_provider")
        ):
            self._update_cloud_indicator()
            return
        if valid:
            self._cloud_verified_signature = signature
            self._cloud_probe_failed = False
        else:
            self._cloud_verified_signature = None
            self._cloud_probe_failed = True
            self._cloud_probe_message = message
        self._update_cloud_indicator()

    def save_settings(self, *_):
        if not hasattr(self, "settings_panel"):
            return
        old_signature = self._cloud_signature()
        old_configuration = dict(self.cfg)
        self.cfg.update(self.settings_panel.collect())
        key_field = self.settings_panel.api_key_entry
        new_key = key_field.text().strip()
        if new_key:
            try:
                provider = self.settings_panel.online_provider.currentData()
                store_api_key(new_key, provider)
                if get_api_key(provider) != new_key:
                    raise OSError("API key could not be read back")
            except (ValueError, OSError, RuntimeError) as exc:
                # Never clear the text: the user must be able to retry.
                self.mic_status.setText("Ошибка сохранения ключа API. Проверьте права Windows.")
                self.settings_panel.key_status.setText(
                    "Не удалось сохранить API-ключ. Поле не очищено; повторите сохранение."
                )
                self._cloud_verified_signature = None
                self.cfg = old_configuration
                self._update_cloud_indicator()
                return False
            key_field.clear()
            self.settings_panel.refresh_key_status()
        try:
            save_config(self.cfg)
        except OSError:
            self.mic_status.setText("Ошибка сохранения config.json.")
            return False
        if self._cloud_signature() != old_signature:
            self._cloud_verified_signature = None
            self._cloud_probe_failed = False
            self._cloud_first_check_done = False
        self._update_cloud_indicator()
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
            lang = get_ui_language()
            return (f"Online AI configured: {name} → Windows (test key)" if lang == "en"
                    else f"AI online configurat: {name} → Windows (verifică cheia)" if lang == "ro"
                    else f"Онлайн-ИИ настроен: {name} → Windows (проверить ключ)")
        if self.cfg.get("online_agent_enabled", False):
            return tr("Онлайн-ИИ включён, но ключ выбранного провайдера не сохранён")
        return tr("Облачный ИИ выключен — локальный режим")

    def apply_settings(self, *_):
        """Save settings and apply them to running services where supported."""
        old = dict(self.cfg)
        if self.save_settings() is False:
            return
        self.apply_appearance()
        self.apply_ui_language()
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
            for k in ("language", "microphone_device", "microphone_name", "microphone_hostapi",
                      "microphone_sensitivity", "speech_pause_seconds",
                      "whisper_beam_size", "whisper_model", "whisper_model_path")
        )
        enabled = self.cfg.get("microphone_enabled", True)
        if changed_audio or old.get("microphone_enabled", True) != enabled:
            if not enabled:
                if self._pending_microphone_test is not None:
                    self._set_diagnostic_controls(True)
                self._pending_microphone_test = None
                self._probe_resume_listener = False
            self._listener_restart_pending = bool(enabled)
            self.stop_listener()
            if enabled:
                self.start_listener()
        elif self.worker and self.worker.listener:
            self.worker.listener.prefix_enabled = self.cfg.get("prefix_enabled", False)
            self.worker.listener.prefix = self.cfg.get("wake_prefix", "Jarvis")
        self.mic_status.setText(tr("Настройки сохранены.") + " " + self._provider_status_text())
        self._on_audio_state(self._audio_event, self._audio_details)

    def test_online_api(self):
        """Verify the API; save provider, model and key only after test success."""
        if self._api_test_running or self._closed:
            return
        settings = self.settings_panel.collect()
        provider = settings.get("online_provider", "openai")
        if provider not in PROVIDERS:
            self.settings_panel.show_test_result("Выберите поставщика API.", False)
            return
        # Do not persist a failed/unverified key. A successful test may
        # save it automatically for use in the next app session.
        key = self.settings_panel.api_key_entry.text().strip() or get_api_key(provider)
        if not key:
            message = "Введите новый API-ключ или сохраните его перед проверкой."
            self.settings_panel.show_test_result(message, False)
            self.mic_status.setText(message)
            return
        self._api_test_running = True
        self._api_test_requested_model = settings.get("online_model")
        self._api_test_requested_key = key
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
            self._api_test_requested_key = None
            return
        if (
            valid and suggested_model and
            panel.online_model.text().strip() == self._api_test_requested_model and
            suggested_model != panel.online_model.text().strip()
        ):
            panel.online_model.setText(suggested_model)
        if valid:
            # The UI might have changed while the network request was running.
            # Persist only the exact key that actually passed validation.
            current = panel.api_key_entry.text().strip() or get_api_key(provider)
            if current != self._api_test_requested_key:
                panel.show_test_result(
                    "Ключ изменился во время проверки. Проверьте новый ключ повторно.", False
                )
                self._api_test_requested_key = None
                return
            if current == self._api_test_requested_key:
                if self.save_settings() is False:
                    panel.show_test_result(
                        "Проверка прошла, но ключ НЕ удалось сохранить. Повторите сохранение.",
                        False,
                    )
                    self._api_test_requested_key = None
                    return
                self._cloud_verified_signature = self._cloud_signature()
                self._cloud_probe_failed = False
                self._cloud_first_check_done = True
                self._update_cloud_indicator()
                message += {
                    "ru": " Ключ и настройки сохранены.",
                    "en": " Key and settings saved.",
                    "ro": " Cheia și setările au fost salvate.",
                }.get(get_ui_language(), " Key and settings saved.")
        panel.show_test_result(message, valid)
        self._api_test_requested_key = None
        self.mic_status.setText(message)

    def preview_voice(self):
        self.save_settings()
        language = self.cfg.get("language", "ru")
        # Preview the voice chosen in Settings even if the microphone's
        # recognition language is different. Normal replies still use their
        # actual language; this never alters speech-recognition settings.
        from luxai.voice_presets import VOICE_PRESETS
        chosen_voice = self.cfg.get("voice_id", "")
        for voice_language, preset in VOICE_PRESETS.items():
            if preset["id"] == chosen_voice:
                language = voice_language
                break
        if language not in ("ru", "ro", "en"):
            language = "ru"
        example = {
            "ru": "Здравствуйте. Я Джарвис, ваш голосовой помощник.",
            "en": "Hello. I am Jarvis, your voice assistant.",
            "ro": "Salut. Sunt Jarvis, asistentul tău vocal.",
        }[language]
        status = {
            "ru": "Загружаю голос при необходимости и воспроизвожу пример…",
            "en": "Downloading the voice if needed and playing a sample…",
            "ro": "Descarc vocea dacă este necesar și redau un exemplu…",
        }
        self.mic_status.setText(status[language])
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
        self._tray_show_action = show_action
        self._tray_quit_action = quit_action
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

    def _on_audio_level(self, rms):
        import math
        if self._closed:
            return
        if self._audio_event in ("stopped", "error", "input_stalled"):
            rms = 0.0
        value = 0 if rms <= 0 else int(max(0, min(100, (20 * math.log10(max(rms, 1e-8)) + 70) / 0.7)))
        self.home_page.microphone_level.setValue(value)
        self.settings_panel.audio_level.setValue(value)

    def _on_audio_state(self, event, details):
        """Show capture readiness separately from the requested on/off switch."""
        if self._closed:
            return
        self._audio_event, self._audio_details = event, dict(details or {})
        messages = {
            "stopped": "Микрофон выключен",
            "loading_model": "Загрузка модели распознавания… Первый запуск может занять несколько минут.",
            "model_ready": "Модель готова. Открытие микрофона…",
            "listening": "Микрофон принимает звук",
            "speech_started": "Речь обнаружена…",
            "transcribing": "Распознавание речи…",
            "no_speech": "Речь не распознана. Проверьте язык и уровень сигнала.",
            "transcription_error": "Ошибка распознавания",
            "input_warning": "Проблема аудиопотока",
            "input_stalled": "Нет аудиоданных. Переподключите гарнитуру и перезапустите микрофон.",
            "input_silent": "Звука нет. Проверьте вход Headset / Hands-Free, кнопку Mute и разрешения Windows.",
            "error": "Микрофон не запущен",
            "testing": "Проверка микрофона: говорите в течение четырёх секунд…",
            "waiting_for_capture": "Ожидание завершения текущей загрузки или распознавания. Проверка начнётся после остановки микрофона.",
            "probe_ok": "Микрофон слышит звук. Если команд нет, проверьте язык и модель Whisper.",
            "probe_silent": "Звука нет. Проверьте вход Headset / Hands-Free, кнопку Mute и разрешения Windows.",
            "probe_clipped": "Сигнал перегружен. Уменьшите усиление микрофона в Windows.",
        }
        message = tr(messages.get(event, "Проблема аудиопотока"))
        detail = self._audio_details.get("message", "") if event in ("error", "transcription_error", "input_warning") else ""
        if detail:
            message += ": " + str(detail)[:400]
        if event == "listening" and self._audio_details.get("device"):
            message += ": " + str(self._audio_details["device"])
        self.home_page.microphone_state.setText(message)
        self.settings_panel.audio_status.setText(message)
        if event in ("no_speech", "transcription_error", "error", "input_warning", "input_stalled", "input_silent", "probe_ok", "probe_silent", "probe_clipped"):
            self.settings_panel.audio_feedback.setText(message)
        elif event in ("speech_started", "testing"):
            self.settings_panel.audio_feedback.clear()
        live = event in ("listening", "speech_started", "transcribing", "no_speech", "transcription_error", "input_warning")
        error = event in ("error", "input_stalled", "input_silent", "probe_silent", "probe_clipped")
        self.header_mic_button.setText("◉" if live else "!" if error else "…" if event in ("loading_model", "model_ready", "testing", "waiting_for_capture") else "◌")
        self.header_mic_button.setToolTip(message)
        self.header_mic_button.setStyleSheet("color:" + ("#ef7777" if error else "#80c99b" if live else "#d8ba70") + ";")
        if event in ("stopped", "error", "input_stalled"):
            self._on_audio_level(0)

    def restart_microphone(self):
        if self._pending_microphone_test is not None:
            self._set_diagnostic_controls(True)
        self._pending_microphone_test = None
        self.settings_panel.mic.setChecked(True)
        self.header_mic_button.setChecked(True)
        if self.save_settings() is False:
            return
        diagnostic = self.audio_diagnostics_worker
        if diagnostic and diagnostic.isRunning():
            self._probe_resume_listener = True
            diagnostic.stop_capture()
            return
        self._listener_restart_pending = True
        self.stop_listener()
        if not self.worker or not self.worker.isRunning():
            self.start_listener()

    def test_microphone(self):
        """Test the selected input without downloading or initializing Whisper."""
        if self._closed or self._pending_microphone_test is not None or (self.audio_diagnostics_worker and self.audio_diagnostics_worker.isRunning()):
            return
        self._pending_microphone_test = self.settings_panel.collect()
        self._probe_resume_listener = bool(self.worker and self.worker.isRunning())
        self._listener_restart_pending = False
        self._set_diagnostic_controls(False)
        if self.worker and self.worker.isRunning():
            self.stop_listener()
            self._on_audio_state("waiting_for_capture", {})
        else:
            self._begin_microphone_test()

    def _begin_microphone_test(self):
        config = self._pending_microphone_test
        self._pending_microphone_test = None
        if config is None or self._closed:
            return
        self._on_audio_state("testing", {})
        self._start_audio_diagnostics(config, probe=True)

    def export_diagnostics(self):
        if self._closed or self._pending_microphone_test is not None or (self.audio_diagnostics_worker and self.audio_diagnostics_worker.isRunning()):
            return
        self._start_audio_diagnostics(self.settings_panel.collect(), probe=False)

    def _start_audio_diagnostics(self, config, probe):
        if self._closed or (self.audio_diagnostics_worker and self.audio_diagnostics_worker.isRunning()):
            return False
        worker = AudioDiagnosticsWorker(config, probe=probe)
        self.audio_diagnostics_worker = worker
        worker.level.connect(self._on_diagnostic_level)
        worker.completed.connect(self._on_audio_diagnostics)
        worker.finished.connect(self._on_audio_diagnostics_finished)
        self._set_diagnostic_controls(False)
        worker.start()
        return True

    def _set_diagnostic_controls(self, enabled):
        self.settings_panel.test_microphone.setEnabled(enabled)
        self.home_page.microphone_test_button.setEnabled(enabled)
        self.settings_panel.export_diagnostics.setEnabled(enabled)

    def _on_diagnostic_level(self, rms):
        if self.sender() is self.audio_diagnostics_worker:
            self._on_audio_level(rms)

    def _on_audio_diagnostics(self, report):
        if self._closed:
            return
        worker = self.sender()
        if worker is not self.audio_diagnostics_worker:
            return
        if worker.probe:
            result = report.get("microphone_probe", {})
            if result.get("cancelled"):
                self._on_audio_state("stopped", {})
                return
            self._last_microphone_probe = dict(result)
            self._last_microphone_probe["requested_endpoint"] = {
                "index": worker.config.get("microphone_device", -1),
                "name": worker.config.get("microphone_name", ""),
                "hostapi": worker.config.get("microphone_hostapi", ""),
            }
            if not result.get("ok"):
                self._on_audio_state("error", {"message": result.get("error") or report.get("error", "Audio input unavailable")})
            elif result.get("silent"):
                self._on_audio_state("probe_silent", {})
            elif result.get("clipped"):
                self._on_audio_state("probe_clipped", {})
            else:
                self._on_audio_state("probe_ok", {})
        else:
            if self._last_microphone_probe is not None:
                report["last_microphone_probe"] = self._last_microphone_probe
            path, _ = QFileDialog.getSaveFileName(self, tr("Сохранить диагностику"), "luxai-diagnostics.json", "JSON (*.json)")
            if path:
                try:
                    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                except OSError:
                    QMessageBox.warning(self, tr("Ошибка"), tr("Не удалось сохранить диагностику."))

    def _on_audio_diagnostics_finished(self):
        worker = self.sender()
        if worker is not self.audio_diagnostics_worker:
            return
        self.audio_diagnostics_worker = None
        worker.deleteLater()
        self._set_diagnostic_controls(True)
        if getattr(self, "_pending_close", False):
            self._pending_close = False
            QTimer.singleShot(0, self.close)
        elif self._probe_resume_listener and not self._closed:
            self._probe_resume_listener = False
            if self.cfg.get("microphone_enabled", True):
                QTimer.singleShot(0, self.start_listener)

    def toggle_mic(self, enabled):
        self.save_settings()
        if enabled:
            self.start_listener()
        else:
            if self._pending_microphone_test is not None:
                self._set_diagnostic_controls(True)
            self._pending_microphone_test = None
            self._probe_resume_listener = False
            self._listener_restart_pending = False
            self.stop_listener()
            self.mic_status.setText("●  Микрофон выключен")

    def start_listener(self):
        if self._closed:
            return
        if self.audio_diagnostics_worker and self.audio_diagnostics_worker.isRunning():
            self._probe_resume_listener = True
            return
        if self.worker and self.worker.isRunning():
            self._listener_restart_pending = True
            return
        if self.save_settings() is False:
            return
        # Always pass the latest saved prefix settings to a newly started listener.
        if not self.cfg.get("microphone_enabled", True):
            self._listener_restart_pending = False
            self._probe_resume_listener = False
            self._on_audio_state("stopped", {})
            return
        self._listener_restart_pending = False
        self.worker = VoiceWorker(dict(self.cfg))
        self.worker.finished.connect(self._on_listener_finished)
        self.worker.transcript.connect(self._on_voice_transcript)
        self.worker.status.connect(self._on_voice_status)
        self.worker.state.connect(self._on_voice_state)
        self.worker.level.connect(self._on_voice_level)
        self._on_audio_state("loading_model", {})
        self.worker.start()

    def _on_voice_transcript(self, text):
        worker = self.sender()
        if (not self._closed and worker is not None and worker is self.worker and not worker.isInterruptionRequested()
                and self.cfg.get("microphone_enabled", True)):
            self.handle_voice(text)

    def _on_voice_status(self, message):
        worker = self.sender()
        if not self._closed and worker is not None and worker is self.worker and not worker.isInterruptionRequested():
            self.mic_status.setText(message)

    def _on_voice_state(self, event, details):
        worker = self.sender()
        if worker is not None and worker is self.worker and not worker.isInterruptionRequested():
            self._on_audio_state(event, details)

    def _on_voice_level(self, rms):
        worker = self.sender()
        if worker is not None and worker is self.worker and not worker.isInterruptionRequested():
            self._on_audio_level(rms)

    def stop_listener(self):
        """Request safe stop; never terminate a thread inside PortAudio / CTranslate2."""
        diagnostic = self.audio_diagnostics_worker
        if diagnostic and diagnostic.isRunning():
            diagnostic.stop_capture()
        worker = self.worker
        if worker and worker.isRunning():
            worker.requestInterruption()
            worker.stop_capture()
            # Keep the QThread alive until it actually finishes.
            # Qt terminate() can crash native microphone/Whisper runtimes.
            if not worker.wait(250):
                self.mic_status.setText("Микрофон завершает текущую обработку…")
        self._on_audio_state("stopped", {})

    def _on_listener_finished(self):
        worker = self.sender()
        if worker is not self.worker:
            return
        self.worker = None
        worker.deleteLater()
        if getattr(self, "_pending_close", False):
            self._pending_close = False
            QTimer.singleShot(0, self.close)
            return
        if self._pending_microphone_test is not None and not self._closed:
            self._begin_microphone_test()
            return
        if getattr(self, "_listener_restart_pending", False) and not self._closed:
            self._listener_restart_pending = False
            QTimer.singleShot(0, self.start_listener)

    def install_local_ai(self):
        """Explicit opt-in: install official prebuilt CPU backend in this .venv."""
        if sys.platform != "win32":
            self.mic_status.setText("This installer is supported only on Windows.")
            return
        import subprocess
        script = BASE / "install_local_ai.bat"
        if not script.is_file():
            self.mic_status.setText("install_local_ai.bat missing. Run Update.bat.")
            return
        try:
            subprocess.Popen(
                ["cmd.exe", "/c", str(script)], cwd=str(BASE),
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            self.mic_status.setText(
                "Installing GGUF support in a separate console. Refresh models after completion."
            )
        except OSError as error:
            self.mic_status.setText(
                f"Could not launch local AI installer: {type(error).__name__}"
            )

    def pick_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "Alege model GGUF", "", "Modele GGUF (*.gguf)")
        if path:
            self.cfg["llm_model_path"] = str(Path(path).resolve())
            panel = self.settings_panel
            index = panel.model_select.findData(self.cfg["llm_model_path"])
            if index < 0:
                panel.model_select.addItem(Path(path).name + " (external)", self.cfg["llm_model_path"])
                index = panel.model_select.count() - 1
            panel.model_select.setCurrentIndex(index)
            self.save_settings()
            self.mic_status.setText("Model selectat. Pentru chat GGUF este necesar llama-cpp-python.")

    def handle_voice(self, text):
        # A single clear stop word interrupts TTS even in the middle of
        # speaking. Dictation retains its own existing stop behavior.
        if is_hallucinated_outro(text):
            return
        if not self.dictation_active and is_stop_speech_command(text):
            self.append_message("Tu (voce)", text.strip(), "#79a6ff")
            self.stop_speaking()
            return
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
            aliases += ["Jarvis", "Джарвис", "Жарвис", "Джервис", "Жервис", "Жарис", "Джарис"]
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
        # "You missed, try again" is meaningful feedback about the LAST
        # desktop goal, not a new small-talk request. Retry from a NEW image
        # rather than replaying yesterday's click coordinates or old macro.
        from luxai.visual_reasoner import is_visual_feedback
        import time
        retry_feedback = ""
        window_recovery_app = ""
        old = getattr(self, "_last_visual_goal", None)
        age = time.monotonic() - getattr(self, "_last_visual_goal_at", 0.0)
        if old and 0 <= age <= 600:
            from luxai.discord_window_state import is_background_window_correction
            if (is_background_window_correction(text)
                    and re.search(r"(?:discord|дискорд\w*)", old, re.I)):
                # User corrected PROCESS existence versus visible WINDOW.
                # Recover the app window only; never auto-send a message
                # that happened to be included in the earlier request.
                window_recovery_app = "discord"
            elif is_visual_feedback(text):
                retry_feedback, text = text, old
        if len(self._command_queue) >= 8:
            self.mic_status.setText("Очередь заполнена. Подождите завершения команды.")
            return
        pieces = [text]
        connectors = [
            word.strip() for word in self.cfg.get("command_chain_words", "и затем, потом").split(",")
            if word.strip()
        ]
        if needs_live_macro_planning(text):
            # Preserve multi-step intent even when cloud AI is disabled:
            # never execute the first standalone screenshot and lose the rest.
            # previously discarded interdependent screen actions.
            connectors = []
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
        self._command_queue.append({
            "parts": pieces, "answers": [], "routes": [],
            "original_text": text, "visual_feedback": retry_feedback,
            "window_recovery_app": window_recovery_app,
        })
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

    def _start_selection_request(self, spoken, mode):
        """Copy a deliberate browser/editor selection, preserving clipboard.

        The clipboard and GUI focus are touched only on the Qt main thread.
        Selected text is sent to the configured cloud AI only when the user
        has explicitly requested a summary and cloud AI is enabled.
        """
        if sys.platform != "win32":
            self._current_route = "Windows: выделенный текст"
            self._resolved_command(
                spoken, "Чтение выделенного текста доступно только в Windows."
            )
            return
        from ctypes import wintypes
        import ctypes
        target = _foreground_hwnd()
        try:
            _valid_external_window(target)
        except (OSError, ValueError):
            target = getattr(self, "_last_external_hwnd", 0)
        try:
            _valid_external_window(target)
        except (OSError, ValueError):
            self._current_route = "Windows: выделенный текст"
            self._resolved_command(
                spoken,
                "Не вижу внешнее окно с выделением. "
                "Выделите текст в браузере или редакторе, переключитесь "
                "в него и повторите команду.",
            )
            return
        self._last_external_hwnd = target
        try:
            ctypes.windll.user32.SetForegroundWindow(wintypes.HWND(target))
        except (AttributeError, OSError):
            pass
        self.mic_status.setText("Читаю выделенный текст из активного окна…")
        QTimer.singleShot(
            150,
            lambda: self._copy_selection_start(spoken, mode, target),
        )

    def _copy_selection_start(self, spoken, mode, hwnd):
        if self._closed or not self._processing or spoken != self._active_text:
            return
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        try:
            _, before, saved = copy_selected_text(clipboard, hwnd)
        except Exception as exc:
            self._current_route = "Windows: выделенный текст"
            self._resolved_command(spoken, str(exc))
            return
        QTimer.singleShot(
            300,
            lambda: self._copy_selection_finish(
                spoken, mode, hwnd, before, saved,
            ),
        )

    def _copy_selection_finish(self, spoken, mode, hwnd, before, saved):
        if self._closed or not self._processing or spoken != self._active_text:
            return
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        try:
            selected = finish_selected_copy(
                clipboard, hwnd, before, saved,
            )
        except Exception as exc:
            self._current_route = "Windows: выделенный текст"
            self._resolved_command(spoken, str(exc))
            return
        if mode == "read":
            answer = "Выделено: " + selected[:1500]
            if len(selected) > 1500:
                answer += "… (показано только начало)"
            self._current_route = "Windows: выделенный текст"
            self._resolved_command(spoken, answer)
            return
        self.mic_status.setText("Составляю краткий пересказ выделения…")
        threading.Thread(
            target=self._selected_summary_worker,
            args=(spoken, selected),
            daemon=True, name="JarvisSelectedTextSummary",
        ).start()

    def _selected_summary_worker(self, spoken, selected):
        """Cloud first when connected, then offline GGUF, then extractive."""
        answer = None
        route = "выделение: исходный текст"
        try:
            if self.online_planner.enabled():
                answer = self.online_planner.summarize_selection(selected)
                if answer:
                    route = "выделение → облачный AI"
            if not answer and self.cfg.get("local_llm_fallback_enabled", True):
                answer = self.agent.summarize_selection(selected)
                if answer:
                    route = "выделение → локальный GGUF"
        except Exception:
            # Neither the selected text nor credentials enter error messages.
            answer = None
        if not answer:
            answer = extractive_fallback(selected)
        if not self._closed:
            try:
                self.selected_summary_ready.emit(spoken, route, answer)
            except RuntimeError:
                pass

    def _on_selected_summary_ready(self, spoken, route, answer):
        if self._closed or not self._processing or spoken != self._active_text:
            return
        self._current_route = route
        self._resolved_command(spoken, answer)

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
            from luxai.visual_reasoner import is_visual_goal
            feedback = self._command_queue[0].get("visual_feedback", "")
            if is_visual_goal(text):
                import time
                self._last_visual_goal = text
                self._last_visual_goal_at = time.monotonic()
            recovery_app = self._command_queue[0].get("window_recovery_app", "")
            if recovery_app == "discord":
                # This is a request to reveal the GUI, not to replay the
                # previous Discord message or unsafe keyboard actions.
                from luxai.windows_apps import launch_installed_app
                ok, result = launch_installed_app("discord")
                self._current_route = "Discord: проверка видимого окна"
                self._resolved_command(text, result)
                return
            if feedback:
                # Replay the INTENT through a new observe/plan/verify loop,
                # never replay a stale macro or an unverified click location.
                self._start_visual_reasoner(text, feedback=feedback)
                return


            # Real text highlighting lives in the active application's
            # selection, not in a screenshot. Copy it before model routing.
            selected_mode = selected_text_intent(text)
            if selected_mode is not None:
                self._start_selection_request(text, selected_mode)
                return

            # Previously, local screen inspection matched "найди ... экран"
            # inside compound tasks before opening Discord or another app.
            # Saved exact commands take priority, then the ENTIRE chained
            # request goes to the validated macro planner.
            # Native Discord intents take priority over older saved macros.
            # Preserve longstanding local Discord microphone controls.
            # Generic macros also match words like "нажми на кнопку" and
            # must not preempt a known, deterministic local operation.
            if wants_discord_mic_visual_click(text):
                self._start_discord_mic_visual(text)
                return
            if wants_discord_mic_mute(text):
                self._current_route = "Discord: глобальная комбинация клавиш"
                answer = toggle_discord_microphone(self.confirm_action)
                self._resolved_command(text, answer)
                return
            # Auto-learned one-shot "open app" shortcuts must not shadow a
            # richer visual user goal that also requested actual UI work.
            # Manually created custom commands continue to take precedence.
            if saved is not None and not (
                (is_visual_goal(text) or is_discord_message_request(text))
                and saved.get("learned", False)
            ):
                self._execute_registered(text, saved)
                return
            # Keep known HTTPS-site opening local and OFFLINE. A browser
            # launch is not a reason to upload screenshots or run the
            # adaptive visual navigator.
            site = website_plan(text)
            if site is not None:
                answer = self.agent.execute_plan(
                    text, site, confirm_callback=self.confirm_action,
                )
                self._current_route = "браузер HTTPS"
                self._resolved_command(text, answer or "Не удалось открыть сайт.")
                return
            # Novel visual goals are solved by repeated real observations,
            # not by a one-shot macro which cannot see whether a click worked.
            # Dedicated Discord message/contact and sourced-research tools
            # retain their stronger safeguards, including send confirmation.
            # DMs and other external-effect instructions must use the
            # atomic/confirmed tools, not general screenshot mouse clicks.
            from luxai.macro_planner import is_discord_message_request
            discord_message = is_discord_message_request(text)
            if is_visual_goal(text) and not (
                discord_message
                or detect_research_dm_request(text)
                or detect_discord_screen_review(text)
                or looks_like_discord_screen_review(text)
            ):
                from luxai.discord_navigation import detect_discord_open_dm
                from luxai.research_notepad import detect_research_notepad
                if not detect_discord_open_dm(text) and not detect_research_notepad(text):
                    self._start_visual_reasoner(text)
                    return
            if needs_live_macro_planning(text):
                if not self.online_planner.enabled():
                    self._current_route = "сложные голосовые команды"
                    self._resolved_command(
                        text,
                        "Команда из нескольких шагов не выполнена. "
                        "Для анализа снимков и поиска элементов включите "
                        "онлайн AI с поддержкой изображений и проверьте API-ключ."
                    )
                    return
                self.mic_status.setText("AI планирует всю последовательность действий…")
                threading.Thread(
                    target=self._direct_macro_worker, args=(text,),
                    daemon=True, name="JarvisLiveMacroPlanner",
                ).start()
                return

            # Live weather and local screen OCR use dedicated, verifiable
            # services. They work even if Gemini is quota-blocked (HTTP 429).
            if re.search(
                r"(?i)(?:размер|разрешени|resolution|rezoluți|rezoluti)"
                r".{0,22}(?:экран|диспле|screen|monitor|ecran)",
                text,
            ):
                from luxai.desktop_actions import execute_desktop_step
                try:
                    info = execute_desktop_step({"action": "display_info"})
                except (OSError, RuntimeError, ValueError) as exc:
                    info = "Не удалось определить экран: " + str(exc)[:140]
                self._current_route = "локальная конфигурация дисплея"
                self._resolved_command(text, info)
                return
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
            voice_steps = parse_action_sequence(text)
            keyboard = keyboard_action_plan(text)
            if voice_steps is not None or keyboard is not None:
                # Only target the currently focused external application.
                if self.isActiveWindow():
                    answer = (
                        "Выберите окно другой программы и повторите команду. "
                        "В окно самого Jarvis клавиши не отправляются."
                    )
                else:
                    steps = voice_steps if voice_steps is not None else [keyboard]
                    if len(steps) > 1:
                        self._current_route = "локальные голосовые действия"
                        self._run_saved_steps(text, steps)
                        return
                    answer = self.agent.execute_plan(
                        text, steps[0], confirm_callback=self.confirm_action,
                    ) or "Действие не выполнено."
                self._current_route = "локальная клавиатура и мышь"
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

            quick = routine_reply(text, reply_language(self.cfg, text))
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
        if step["action"] == "research_notepad_facts":
            self.mic_status.setText("Получаю три факта из Википедии и проверяю Блокнот…")
            threading.Thread(
                target=self._research_notepad_worker,
                args=(step["target"], ctx["index"], ctx),
                daemon=True, name="JarvisResearchNotepad",
            ).start()
            return
        if step["action"] == "discord_open_dm":
            username = step["target"]
            if not self.online_planner.enabled():
                ctx["messages"].append(
                    "Для поиска контакта Discord нужен AI с поддержкой изображений."
                )
                self._finish_visual_macro()
                return
            if not self._allow_cloud_screenshots():
                ctx["messages"].append("Передача снимков для поиска Discord отменена.")
                self._finish_visual_macro()
                return
            self.mic_status.setText(f"Проверяю Discord и открываю чат {username}…")
            threading.Thread(
                target=self._discord_open_worker,
                args=(username, ctx["index"], ctx),
                daemon=True, name="JarvisDiscordOpenDM",
            ).start()
            return
        if step["action"] == "discord_screen_review":
            username = step["target"]
            if not self.online_planner.enabled():
                ctx["messages"].append(
                    "Нужен AI с поддержкой изображений для поиска в Discord."
                )
                self._finish_visual_macro()
                return
            approval = (
                f"Открыть именно Discord, сделать снимок, найти пользователя "
                f"«{username}», "
                "сделать второй снимок и кратко пересказать его?\n\n"
                "Два снимка будут сохранены локально в Pictures/LuxAI. "
                "До ТРЁХ изображений Discord (поиск, проверка чата и анализ "
                "второго снимка) будут переданы выбранному облачному AI. "
                "Они могут содержать личные переписки. Продолжить? "
                "Никакие сообщения отправляться не будут."
            )
            if not self._allow_cloud_screenshots():
                ctx["messages"].append("Отправка снимков в AI отменена.")
                self._finish_visual_macro()
                return
            self.mic_status.setText(f"Открываю Discord и ищу @{username}…")
            threading.Thread(
                target=self._discord_review_worker,
                args=(username, ctx["index"], ctx),
                daemon=True, name="JarvisDiscordVisualReview",
            ).start()
            return
        if step["action"] == "discord_send_text":
            if not self.online_planner.enabled():
                ctx["messages"].append(
                    "Для поиска и проверки Discord нужен AI с поддержкой изображений."
                )
                self._finish_visual_macro()
                return
            if not self._allow_cloud_screenshots():
                ctx["messages"].append("Передача снимков отменена.")
                self._finish_visual_macro()
                return
            self.mic_status.setText("Discord: проверяю пользователя и готовлю черновик…")
            threading.Thread(
                target=self._discord_draft_worker,
                args=(dict(step), ctx["index"]),
                daemon=True, name="JarvisDiscordUserTextDraft",
            ).start()
            return
        if step["action"] == "discord_research_dm":
            topic, username = step["target"].rsplit("||", 1)
            if not self.online_planner.enabled():
                ctx["messages"].append(
                    "Включите AI с поддержкой анализа изображений для поиска Discord."
                )
                self._finish_visual_macro()
                return
            approval = (
                f"Подготовить сообщение для Discord @{username} по теме «{topic}»?\n\n"
                "Jarvis получит статью из Wikipedia, откроет установленный "
                "Discord и передаст ДО ПЯТИ снимков окна вашему AI-провайдеру "
                "(видимые личные сообщения, при необходимости результаты "
                "поиска, заголовок чата и финальная проверка перед отправкой). "
                "Если имя на экране отличается от произнесённого, "
                "Jarvis отдельно спросит, правильный ли это человек. "
                "Скриншоты могут содержать личные сообщения. "
                "Перед отправкой текста будет ещё одно подтверждение."
            )
            if not self._allow_cloud_screenshots():
                ctx["messages"].append("Согласие на отправку скриншотов не получено.")
                self._finish_visual_macro()
                return
            self.mic_status.setText(f"Ищу информацию и чат Discord @{username}…")
            threading.Thread(
                target=self._discord_draft_worker,
                args=(dict(step), ctx["index"]),
                daemon=True, name="JarvisDiscordResearch",
            ).start()
            return
        if step["action"] == "visual_click":
            label, clicks = parse_click_target(step["target"])
            if not self.online_planner.enabled():
                ctx["messages"].append("Для визуального клика включите AI с поддержкой изображений.")
                self._finish_visual_macro()
                return
            hwnd = _foreground_hwnd()
            try:
                _valid_external_window(hwnd)
            except (OSError, ValueError):
                hwnd = getattr(self, "_last_external_hwnd", 0)
            try:
                _valid_external_window(hwnd)
            except (OSError, ValueError):
                ctx["messages"].append(
                    "Откройте целевую программу, активируйте её окно и повторите команду."
                )
                self._finish_visual_macro()
                return
            # A screenshot is not sent to the cloud without user consent,
            # even when the voice shortcut was previously saved.
            warning = (
                "⚠ Отправить снимок выбранного окна внешнему AI-сервису "
                f"и нажать на «{label}» {clicks} раз(а)?\n"
                "Снимок может содержать личную информацию. "
                "Если не согласны, выберите Нет."
            )
            if not self._allow_cloud_screenshots():
                ctx["messages"].append("Отправка снимка отменена пользователем.")
                self._finish_visual_macro()
                return
            self._last_external_hwnd = hwnd
            self.mic_status.setText(f"AI анализирует окно для «{label}»…")
            try:
                import ctypes
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            except (AttributeError, OSError):
                pass
            # Let the confirmation dialog disappear before capturing pixels.
            QTimer.singleShot(
                350, lambda: threading.Thread(
                    target=self._visual_worker,
                    args=(dict(step), ctx["index"], hwnd),
                    daemon=True, name="JarvisVisualLocator",
                ).start()
            )
            return
        if step["action"] == "close_window":
            hwnd = _foreground_hwnd()
            try:
                _valid_external_window(hwnd)
            except (OSError, ValueError):
                hwnd = getattr(self, "_last_external_hwnd", 0)
            try:
                _valid_external_window(hwnd)
            except (OSError, ValueError):
                ctx["messages"].append("Не найдено активное внешнее окно для закрытия.")
                self._finish_visual_macro()
                return
            if not self.confirm_action(
                "⚠ Закрыть активное окно другой программы? "
                "Несохранённые изменения могут быть потеряны."
            ):
                ctx["messages"].append("Закрытие окна отменено.")
                self._finish_visual_macro()
                return
            try:
                import ctypes
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            except (AttributeError, OSError):
                pass
            QTimer.singleShot(
                300, lambda: threading.Thread(
                    target=self._macro_worker,
                    args=(dict(step), ctx["index"]),
                    daemon=True, name="JarvisCloseWindow",
                ).start()
            )
            return
        if step["action"] == "empty_recycle_bin":
            if not self.confirm_action(
                "⚠ БЕЗВОЗВРАТНО удалить ВСЕ файлы из корзины Windows? "
                "Отменить удаление после этого будет невозможно."
            ):
                ctx["messages"].append("Очистка корзины отменена.")
                self._finish_visual_macro()
                return
            threading.Thread(
                target=self._macro_worker,
                args=(dict(step), ctx["index"]),
                daemon=True, name="JarvisRecycleBin",
            ).start()
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
            "display_info", "mouse_move", "mouse_right_click", "mouse_click",
        }:
            threading.Thread(
                target=self._macro_worker, args=(dict(step), ctx["index"]),
                daemon=True, name="JarvisLocalMouseStep",
            ).start()
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
            # A browser search steals the foreground. An "open Notepad,
            # then type" macro must explicitly verify and focus Notepad.
            if step["action"] == "type_text" and ctx.get("last_opened_app") == "notepad":
                from luxai.research_notepad import _focus_notepad_window
                _focus_notepad_window()
            self.agent.last_execution_success = False
            answer = self.agent.execute_plan(
                ctx["text"], step, confirm_callback=self.confirm_action,
            )
            if answer:
                ctx["messages"].append(str(answer))
            if self.agent.last_execution_success and step["action"] == "open_app":
                ctx["last_opened_app"] = step["target"]
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

    def _finish_visual_macro(self):
        ctx = getattr(self, "_macro_context", None)
        if ctx is None:
            return
        output = " ".join(ctx["messages"]) or "Действие не выполнено."
        self._macro_context = None
        self._resolved_command(ctx["text"], output)

    def _research_notepad_worker(self, topic, index, context):
        try:
            from luxai.research_notepad import write_researched_facts_to_notepad
            result = write_researched_facts_to_notepad(
                topic, cancelled=lambda: self._closed or self._macro_context is not context
            )
            error = ""
        except (ValueError, RuntimeError, OSError) as exc:
            result, error = None, f"{type(exc).__name__}: {str(exc)[:170]}"
        except Exception:
            result, error = None, "Не получилось подтвердить факты или окно Блокнота."
        if not self._closed:
            try:
                self.research_notepad_ready.emit(index, result, error)
            except RuntimeError:
                pass

    def _on_research_notepad_ready(self, index, result, error):
        ctx = getattr(self, "_macro_context", None)
        if (self._closed or ctx is None or not self._processing
                or ctx["index"] != index):
            return
        if error or result is None:
            ctx["messages"].append(
                "Запись фактов в Блокнот не выполнена: " + (error or "")
            )
            self._finish_visual_macro()
            return
        ctx["messages"].append(result)
        QTimer.singleShot(0, self._next_macro_step)

    def _discord_open_worker(self, username, index, context):
        try:
            from luxai.discord_navigation import open_discord_contact
            result = open_discord_contact(
                self.online_planner, username,
                confirm_candidate=lambda spoken, displayed:
                    self._confirm_discord_contact_in_ui(spoken, displayed, context),
                cancelled=lambda: self._closed or self._macro_context is not context,
            )
            error = ""
        except (ValueError, OSError, RuntimeError) as exc:
            result, error = None, f"{type(exc).__name__}: {str(exc)[:180]}"
        except Exception:
            result, error = None, "Не получилось подтвердить открытие чата Discord."
        if not self._closed:
            try:
                self.discord_open_ready.emit(index, result, error)
            except RuntimeError:
                pass

    def _on_discord_open_ready(self, index, result, error):
        ctx = getattr(self, "_macro_context", None)
        if (self._closed or ctx is None or not self._processing
                or ctx["index"] != index):
            return
        if error or result is None:
            ctx["messages"].append(
                "Discord: чат не открыт или не подтверждён. " + (error or "")
            )
            self._finish_visual_macro()
            return
        ctx["messages"].append(result)
        QTimer.singleShot(0, self._next_macro_step)

    def _discord_review_worker(self, username, index, context):
        try:
            result = run_discord_screen_review(
                self.online_planner, username,
                cancelled=lambda: self._closed or self._macro_context is not context,
            )
            error = ""
        except (OSError, RuntimeError, ValueError, PermissionError) as exc:
            result = None
            if isinstance(exc, ValueError) and "Control not found" in str(exc):
                error = (
                    "Discord не подтвердил точного пользователя или заголовок чата. "
                    "Снимки могут остаться локально; сообщений не отправлено."
                )
            else:
                error = f"{type(exc).__name__}: {str(exc)[:170]}"
        except Exception:
            result, error = None, "Не удалось безопасно исследовать окно Discord."
        if not self._closed:
            try:
                self.discord_review_ready.emit(index, result, error)
            except RuntimeError:
                pass

    def _on_discord_review_ready(self, index, result, error):
        ctx = getattr(self, "_macro_context", None)
        if self._closed or ctx is None or not self._processing or ctx["index"] != index:
            return
        if result is None or error:
            ctx["messages"].append(
                "Discord: последовательность остановлена. " +
                (error or "результат не получен.")
            )
            self._finish_visual_macro()
            return
        ctx["messages"].append(result)
        QTimer.singleShot(0, self._next_macro_step)

    def _confirm_discord_contact_in_ui(self, spoken, displayed, context):
        """Ask the GUI thread before clicking a visually similar contact.

        A background worker must never show Qt dialogs directly. This
        bounded handoff prevents waiting forever when the window is closed
        or another command supersedes the current one.
        """
        response = {
            "spoken": spoken, "displayed": displayed,
            "context": context, "event": threading.Event(),
            "approved": False,
        }
        if self._closed or context is None or self._macro_context is not context:
            return False
        self.discord_contact_prompt.emit(response)
        for _ in range(360):  # at most 90 s for an interactive decision
            if response["event"].wait(0.25):
                return bool(response["approved"])
            if self._closed or self._macro_context is not context:
                return False
        return False

    def _on_discord_contact_prompt(self, response):
        ctx = getattr(self, "_macro_context", None)
        try:
            if (self._closed or not self._processing or
                    ctx is None or ctx is not response["context"]):
                return
            response["approved"] = bool(self.confirm_action(
                "Discord: имя, которое вы произнесли: "
                f"«{response['spoken']}».\\n"
                "На снимке найден отдельный пользователь: "
                f"«{response['displayed']}».\\n\\n"
                "Это ТОТ ЖЕ САМЫЙ человек? Нажмите Да только "
                "после личной проверки имени. При Нет Jarvis "
                "не откроет беседу и ничего не отправит."
            ))
        finally:
            response["event"].set()

    def _discord_draft_worker(self, step, index):
        try:
            context = getattr(self, "_macro_context", None)
            if step["action"] == "discord_send_text":
                from luxai.discord_research import validate_discord_text_target
                person, message = validate_discord_text_target(step["target"])
                target = "Direct user message||" + person
            else:
                target, message = step["target"], None
            draft = prepare_discord_draft(
                self.online_planner, target, message_override=message,
                confirm_candidate=lambda spoken, displayed: (
                    self._confirm_discord_contact_in_ui(
                        spoken, displayed, context
                    )
                ),
                cancelled=lambda: self._closed or self._macro_context is not context,
            )
            error = ""
        except (OSError, RuntimeError, ValueError) as exc:
            draft = None
            # Do not expose chat screenshots, provider bodies or credentials.
            if isinstance(exc, ValueError) and (
                "Control not found" in str(exc)
                or "unambiguously" in str(exc)
            ):
                error = (
                    "Discord не показал однозначного пользователя или поле сообщения. "
                    "Проверьте написание ника в Discord и повторите команду; "
                    "ничего не было отправлено."
                )
            else:
                error = str(exc)[:220]
        except Exception:
            draft, error = None, "Не удалось подготовить сообщение в Discord."
        if not self._closed:
            try:
                self.discord_draft_ready.emit(index, draft, error)
            except RuntimeError:
                pass

    def _on_discord_draft_ready(self, index, draft, error):
        ctx = getattr(self, "_macro_context", None)
        if self._closed or ctx is None or not self._processing or ctx["index"] != index:
            return
        if draft is None:
            ctx["messages"].append(
                "Discord: сообщение не отправлено. " +
                (error or "Не удалось уверенно найти нужного пользователя.")
            )
            self._finish_visual_macro()
            return
        preview = (
            f"Получатель Discord: @{draft.username}\n"
            f"Подготовленный текст:\n\n{draft.message}\n\n"
            "Перед отправкой Jarvis проверит имя адресата и поле сообщения "
            "по НОВОМУ снимку Discord. После этого он заменит содержимое "
            "этого поля ТОЧНЫМ текстом, который показан выше, и нажмёт Enter. "
            "Если диалог, поле ввода или окно не распознаны однозначно, "
            "отправка отменяется. Разрешить такую проверку, замену черновика "
            "и отправку?"
        )
        if not self.confirm_action(preview):
            ctx["messages"].append(
                "Отправка отменена. Черновик остался в Discord, Enter не нажимался."
            )
            self._finish_visual_macro()
            return
        self.mic_status.setText(
            f"Проверяю чат @{draft.username} и подготавливаю одобренный текст…"
        )
        threading.Thread(
            target=self._discord_send_worker,
            args=(draft, ctx["index"], ctx),
            daemon=True, name="JarvisDiscordVerifiedSend",
        ).start()

    def _discord_send_worker(self, draft, index, context):
        try:
            result = submit_discord_draft(
                draft, self.online_planner,
                cancelled=lambda: self._closed or self._macro_context is not context,
            )
            error = ""
        except (OSError, RuntimeError, ValueError) as exc:
            result = None
            if isinstance(exc, ValueError) and (
                "Control not found" in str(exc) or "unambiguously" in str(exc)
            ):
                error = (
                    "Не смог однозначно подтвердить имя получателя или найти "
                    "поле ввода в Discord на новом снимке. Ничего не отправлено."
                )
            else:
                error = f"{type(exc).__name__}: {str(exc)[:160]}"
        except Exception:
            result, error = None, "Не удалось безопасно проверить отправку Discord."
        if not self._closed:
            try:
                self.discord_send_ready.emit(index, result, error)
            except RuntimeError:
                pass

    def _on_discord_send_ready(self, index, result, error):
        ctx = getattr(self, "_macro_context", None)
        if self._closed or ctx is None or not self._processing or ctx["index"] != index:
            return
        if result is None or error:
            ctx["messages"].append(
                "Discord: сообщение не отправлено. " + (error or "проверка не пройдена.")
            )
            self._finish_visual_macro()
            return
        ctx["messages"].append(result)
        QTimer.singleShot(0, self._next_macro_step)

    def _visual_worker(self, step, index, hwnd):
        try:
            label, count = parse_click_target(step["target"])
            screenshot = capture_window(hwnd)
            point = find_visual_target(self.online_planner, label, screenshot)
            result = {"capture": screenshot, "point": point, "count": count, "label": label}
            error = ""
        except Exception as exc:
            result = None
            # Never show cloud response bodies or image bytes to the UI.
            import urllib.error
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (400, 404, 415, 422):
                error = (
                    "Выбранная модель не смогла обработать изображение. "
                    "Выберите Gemini или OpenAI с поддержкой зрения."
                )
            elif isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
                error = "Лимит запросов облачного AI достигнут (HTTP 429)."
            elif isinstance(exc, ValueError) and "Control not found" in str(exc):
                error = (
                    "Элемент не найден на выбранном экране. "
                    "Убедитесь, что открыта НУЖНАЯ программа, "
                    "а кнопка или пользователь действительно виден в ней."
                )
            else:
                error = f"{type(exc).__name__}: {str(exc)[:180]}"
        if not self._closed:
            try:
                self.visual_step_ready.emit(index, result, error)
            except RuntimeError:
                pass

    def _on_visual_step_ready(self, index, result, error):
        ctx = getattr(self, "_macro_context", None)
        if self._closed or not ctx or not self._processing or ctx["index"] != index:
            return
        if result is None or error:
            ctx["messages"].append(
                "Визуальное действие не выполнено: " + (error or "объект не найден")
            )
            self._finish_visual_macro()
            return
        try:
            click_visual_target(result["capture"], result["point"], result["count"])
            ctx["messages"].append(
                f"Нажал {result['count']} раз(а) на «{result['label']}» "
                f"в точке {result['point']}."
            )
        except Exception as exc:
            ctx["messages"].append(
                "Окно изменилось или клик не выполнен: " + str(exc)[:180]
            )
            self._finish_visual_macro()
            return
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

    def _allow_cloud_screenshots(self):
        """Request permission once per run, not for every screenshot."""
        if getattr(self, "_visual_upload_consent_session", False):
            return True
        approved = self.confirm_action(
            "Разрешить отправку снимков окон выбранному облачному AI "
            "для визуальных команд до закрытия Jarvis? Изображения могут "
            "содержать личные сообщения и другие данные. Локальные снимки "
            "не отправляются. Отправка сообщений по-прежнему требует "
            "отдельного подтверждения."
        )
        if approved:
            self._visual_upload_consent_session = True
        return bool(approved)

    def _start_visual_reasoner(self, text, feedback=""):
        if not self.online_planner.enabled():
            self._current_route = "AI: визуальная проверка"
            self._resolved_command(
                text, "Для анализа и проверки нового действия нужен "
                "облачный AI с поддержкой изображений и API-ключ."
            )
            return
        if not self._allow_cloud_screenshots():
            self._current_route = "AI: визуальная проверка"
            self._resolved_command(text, "Анализ экрана отменён.")
            return
        self.mic_status.setText("AI наблюдает окно и планирует следующий шаг…")
        threading.Thread(
            target=self._visual_reasoner_worker,
            args=(text, feedback),
            daemon=True, name="JarvisClosedLoopReasoner",
        ).start()

    def _visual_reasoner_worker(self, text, feedback):
        try:
            from luxai.visual_reasoner import run_visual_reasoner
            answer = run_visual_reasoner(
                self.online_planner, text, feedback=feedback,
                preferred_hwnd=getattr(self, "_last_external_hwnd", 0),
                cancelled=lambda: (
                    self._closed or not self._processing
                    or self._active_text != text
                ),
            )
        except (OSError, RuntimeError, ValueError, PermissionError) as exc:
            answer = (
                "Визуальная задача остановлена: " +
                f"{type(exc).__name__}: {str(exc)[:180]}"
            )
        except Exception:
            answer = "Визуальный агент остановился без подтверждённого результата."
        if not self._closed:
            try:
                self.visual_reasoner_ready.emit(text, answer)
            except RuntimeError:
                pass

    def _on_visual_reasoner_ready(self, text, answer):
        if self._closed or not self._processing or self._active_text != text:
            return
        self._current_route = "AI: наблюдение → действие → проверка"
        self._resolved_command(text, answer)

    def _start_discord_mic_visual(self, text):
        """Restore a specific local visual command without cloud macro planning."""
        if not self.online_planner.enabled():
            self._current_route = "Discord: визуальное управление"
            self._resolved_command(
                text, "Для визуального поиска кнопки микрофона в Discord "
                "нужен включённый AI с поддержкой изображений и API-ключ."
            )
            return
        approved = self._allow_cloud_screenshots()
        if not approved:
            self._current_route = "Discord: визуальное управление"
            self._resolved_command(text, "Визуальное управление микрофоном отменено.")
            return
        self.mic_status.setText("Проверяю окно Discord и кнопку микрофона…")
        threading.Thread(
            target=self._discord_mic_visual_worker,
            args=(text,), daemon=True, name="JarvisDiscordMicVisual",
        ).start()

    def _discord_mic_visual_worker(self, text):
        try:
            from luxai.discord_mic_visual import click_discord_microphone_by_screenshot
            from luxai.voice_desktop import discord_mic_visual_mode
            answer = click_discord_microphone_by_screenshot(
                self.online_planner,
                mode=discord_mic_visual_mode(text) or "toggle",
                cancelled=lambda: (
                    self._closed or not self._processing or self._active_text != text
                ),
            )
        except (OSError, RuntimeError, ValueError, PermissionError) as exc:
            if isinstance(exc, ValueError) and (
                "Control not found" in str(exc) or "unambiguously" in str(exc)
            ):
                answer = (
                    "Не нашёл однозначно кнопку микрофона в окне Discord. "
                    "Клик не выполнен."
                )
            else:
                answer = (
                    "Не удалось безопасно нажать кнопку Discord: "
                    f"{type(exc).__name__}: {str(exc)[:170]}"
                )
        except Exception:
            answer = "Не удалось безопасно выполнить визуальную команду Discord."
        if not self._closed:
            try:
                self.discord_mic_visual_ready.emit(text, answer)
            except RuntimeError:
                pass

    def _on_discord_mic_visual_ready(self, text, answer):
        if self._closed or not self._processing or self._active_text != text:
            return
        self._current_route = "Discord: визуальное управление"
        self._resolved_command(text, answer)

    def _direct_macro_worker(self, text):
        try:
            from luxai.macro_planner import (
                validate_generated_macro, plan_known_visual_sequence,
            )
            review_user = detect_discord_screen_review(text)
            from luxai.discord_navigation import detect_discord_open_dm
            from luxai.research_notepad import detect_research_notepad
            open_user = detect_discord_open_dm(text)
            facts_topic = detect_research_notepad(text)
            parsed = detect_research_dm_request(text)
            known = None
            if not review_user and not parsed and not open_user and not facts_topic:
                known = plan_known_visual_sequence(text)
            if facts_topic:
                proposal = validate_generated_macro(
                    {"steps": [{"action": "research_notepad_facts", "target": facts_topic}]},
                    text,
                )
                error = "" if proposal else "Не удалось определить тему исследования."
            elif open_user:
                proposal = validate_generated_macro(
                    {"steps": [{"action": "discord_open_dm", "target": open_user}]},
                    text,
                )
                error = "" if proposal else "Не удалось определить контакт Discord."
            elif review_user:
                proposal = validate_generated_macro(
                    {"steps": [{"action": "discord_screen_review",
                                 "target": review_user}]}, text,
                )
                error = "" if proposal else "Не удалось определить пользователя Discord."
            elif looks_like_discord_screen_review(text):
                proposal = None
                error = (
                    "Я понял, что это команда для поиска пользователя в переписке, "
                    "но не могу уверенно определить название приложения или имя. "
                    "Повторите запрос, чётко произнеся Discord и имя пользователя."
                )
            elif parsed:
                topic, username = parsed
                proposal = validate_generated_macro(
                    {"steps": [{"action": "discord_research_dm",
                                 "target": topic + "||" + username}]},
                    text,
                )
                error = "" if proposal else "Не удалось определить тему или получателя."
            elif known:
                proposal, error = known, ""
            else:
                proposal = self.online_planner.plan_macro(text)
                error = self.online_planner.last_error if proposal is None else ""
        except Exception:
            proposal, error = None, "Не удалось обработать команду."
        if not self._closed:
            try:
                self.direct_macro_ready.emit(text, proposal, error)
            except RuntimeError:
                pass

    def _on_direct_macro_ready(self, text, proposal, error):
        if self._closed or not self._processing or self._active_text != text:
            return
        if proposal is None:
            self._current_route = "AI визуальных действий"
            self._resolved_command(
                text, "Команда не выполнена: " + (error or "нет подходящего плана")
            )
            return
        steps = proposal.get("steps", [])
        if not steps:
            self._resolved_command(text, "AI не нашёл допустимых действий.")
            return
        summary = "\n".join(
            f"{i}. {describe_step(step)}" for i, step in enumerate(steps, 1)
        )
        if not self.confirm_action(
            "⚠ AI предлагает выполнить следующую последовательность:\n" +
            summary[:1600] + "\n\nПродолжить?"
        ):
            self._resolved_command(text, "Команда отменена пользователем.")
            return
        self._run_saved_steps(text, steps)

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
            answer = {
                "ru": "Облачный ИИ недоступен. Проверьте API-ключ и соединение. Простые команды работают без ИИ.",
                "en": "Cloud AI is unavailable. Check your API key and connection. Simple commands work without AI.",
                "ro": "AI-ul cloud nu este disponibil. Verifică cheia API și conexiunea. Comenzile simple funcționează fără AI.",
            }[reply_language(self.cfg, text)]
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
        language = reply_language(self.cfg, getattr(self, "_active_text", "") or "")
        prefix = {"ru": "Ошибка", "en": "Error", "ro": "Eroare"}[language]
        if isinstance(exc, ModuleNotFoundError) and exc.name == "llama_cpp":
            return {
                "ru": "Не установлен необязательный модуль llama-cpp-python. Простые команды работают.",
                "en": "The optional llama-cpp-python module is missing. Simple commands still work.",
                "ro": "Lipsește modulul opțional llama-cpp-python. Comenzile simple funcționează.",
            }[language]
        if isinstance(exc, ModuleNotFoundError):
            package = str(exc.name or "unknown")[:80]
            message = {
                "ru": f"Отсутствует модуль {package}. Запустите install_windows.bat для восстановления зависимостей.",
                "en": f"Missing module {package}. Run install_windows.bat to repair dependencies.",
                "ro": f"Lipsește modulul {package}. Rulează install_windows.bat pentru repararea dependențelor.",
            }
            return message[language]
        return f"{prefix}: {exc}"

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
                self._queue_speech(result, reply_language(self.cfg, group.get("original_text", "")))
        QTimer.singleShot(0, self._dispatch_command)

    def stop_speaking(self):
        """Stop current voice and discard queued replies without killing threads."""
        self._speech_generation += 1
        while True:
            try:
                item = self._speech_queue.get_nowait()
                if item is None:
                    self._speech_queue.put_nowait(None)
                    break
            except queue.Empty:
                break
        stop_voice_output()
        if not self._closed:
            self.mic_status.setText("Jarvis: воспроизведение остановлено.")

    def _queue_speech(self, text, language):
        if self._closed:
            return
        item = (text, language, self._speech_generation)
        try:
            self._speech_queue.put_nowait(item)
        except queue.Full:
            try:
                self._speech_queue.get_nowait()
                self._speech_queue.put_nowait(item)
            except queue.Empty:
                pass

    def _speech_loop(self):
        while True:
            task = self._speech_queue.get()
            if task is None:
                return
            text, language, generation = task
            if generation != self._speech_generation:
                continue
            try:
                played = speak(text, enabled=True, language=language)
            except Exception:
                played = False
            if not self._closed:
                try:
                    self.tts_played.emit(played, generation)
                except RuntimeError:
                    pass

    def _on_tts_played(self, played, generation):
        # A deliberate spoken stop is not a missing voice or synthesis error.
        if generation != self._speech_generation:
            return
        if hasattr(self, "settings_panel"):
            self.settings_panel.refresh_voice_status()
        if not played:
            language = reply_language(self.cfg)
            self.mic_status.setText({
                "ru": "Голос недоступен. Проверьте voice_error.log.",
                "en": "Voice unavailable. Check voice_error.log.",
                "ro": "Vocea nu este disponibilă. Verifică voice_error.log.",
            }[language])

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
        self.stop_speaking()
        try:
            self._speech_queue.put_nowait(None)
        except queue.Full:
            pass
        self._listener_restart_pending = False
        self.stop_listener()
        diagnostic_busy = self.audio_diagnostics_worker is not None and self.audio_diagnostics_worker.isRunning()
        if (self.worker is not None and self.worker.isRunning()) or diagnostic_busy:
            # Do not destroy a running Qt thread when closing the window.
            self._pending_close = True
            self.hide()
            event.ignore()
            return
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
