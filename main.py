import re
import sys, json, html
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QLineEdit, QTextEdit, QFileDialog, QMessageBox,
    QComboBox, QStackedWidget, QFrame, QSlider, QSizePolicy
)

from luxai.agent import LocalAgent
from luxai.voice import VoiceListener, speak
from luxai.screen import capture_screen, read_screen_text

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "config.json"

STYLE = """
QWidget { background:#101319; color:#e9edf5; font-family:'Segoe UI'; font-size:13px; }
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
                model_path=self.cfg.get("whisper_model_path") or self.cfg.get("whisper_model", "small"),
                prefix_enabled=self.cfg.get("prefix_enabled", False),
                prefix=self.cfg.get("wake_prefix", "Jarvis"),
                language=self.cfg.get("language", "auto"),
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
        self.setWindowTitle("Nexora AI")
        self.resize(1120, 720)
        self.setMinimumSize(900, 600)
        self.cfg = load_config()
        self.agent = LocalAgent(self.cfg)
        self.worker = None
        self.history = []
        self.nav_buttons = []
        self.pending_confirmation_dialog = None
        self.pending_confirmation_result = None

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

        for label, page in [("⌂   Acasă", 0), ("☷   Comenzi", 1), ("▦   Instrumente", 2), ("▣   Nexora AI", 3), ("☷   Setări", 4)]:
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
        self.header_title = QLabel("Nexora AI   |   Acasă")
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
        title = QLabel("Bine ai venit în Nexora AI!")
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
        self.home_history.setPlaceholderText("Bine ai venit în Nexora AI!\nÎncă nu există comenzi.")
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
        for text, page_num in [("Открыть Nexora AI", 3), ("Настройки", 4), ("Дополнения", 2)]:
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
        title = QLabel("Nexora AI")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        subtitle = QLabel("Общение с локальным помощником. Ваши модели и настройки остаются на компьютере.")
        subtitle.setObjectName("Muted")
        layout.addWidget(subtitle)
        frame, box = card()
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Nexora AI появится здесь после первого сообщения.")
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
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("Настройки")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        desc = QLabel("Setările sunt salvate local în config.json.")
        desc.setObjectName("Muted")
        layout.addWidget(desc)
        frame, box = card()
        self.mic = QCheckBox("Microfon activ")
        self.mic.setChecked(self.cfg.get("microphone_enabled", True))
        self.mic.toggled.connect(self.toggle_mic)
        box.addWidget(self.mic)
        self.prefix = QCheckBox("Necesită prefix pentru activare")
        self.prefix.setChecked(self.cfg.get("prefix_enabled", False))
        self.prefix.toggled.connect(self.sync_prefix)
        box.addWidget(self.prefix)
        self.tts = QCheckBox("Răspuns vocal")
        self.tts.setChecked(self.cfg.get("tts_enabled", True))
        self.tts.toggled.connect(self.save_settings)
        box.addWidget(self.tts)
        row = QHBoxLayout()
        row.addWidget(QLabel("Prefix de activare"))
        self.prefix_text = QLineEdit(self.cfg.get("wake_prefix", "Jarvis"))
        row.addWidget(self.prefix_text, 1)
        row.addWidget(QLabel("Limbă"))
        self.language = QComboBox()
        for label, value in [("Detectare automată", "auto"), ("Română", "ro"), ("Русский", "ru"), ("English", "en")]:
            self.language.addItem(label, value)
        idx = self.language.findData(self.cfg.get("language", "auto"))
        self.language.setCurrentIndex(max(0, idx))
        row.addWidget(self.language)
        box.addLayout(row)
        model_row = QHBoxLayout()
        self.model_label = QLabel(Path(self.cfg.get("llm_model_path", "")).name or "Nicio model selectat")
        self.model_label.setObjectName("Muted")
        model_row.addWidget(self.model_label, 1)
        choose = QPushButton("Alege model .gguf")
        choose.clicked.connect(self.pick_model)
        model_row.addWidget(choose)
        box.addLayout(model_row)
        save = QPushButton("Salvează setările")
        save.setObjectName("Primary")
        save.clicked.connect(self.save_settings)
        box.addWidget(save)
        layout.addWidget(frame)
        layout.addStretch()
        self.pages.addWidget(page)

    def show_page(self, index):
        self.pages.setCurrentIndex(index)
        titles = ["Главная", "Команды", "Дополнения", "Nexora AI", "Настройки"]
        self.header_title.setText("Nexora AI   |   " + titles[index])
        for i, button in enumerate(self.nav_buttons):
            button.setProperty("active", i == index)
            button.style().unpolish(button)
            button.style().polish(button)

    def save_settings(self, *_):
        if not hasattr(self, "mic"):
            return
        self.cfg.update({
            "microphone_enabled": self.mic.isChecked(),
            "prefix_enabled": self.prefix.isChecked(),
            "wake_prefix": self.prefix_text.text().strip() or "Jarvis",
            "language": self.language.currentData(),
            "tts_enabled": self.tts.isChecked(),
        })
        save_config(self.cfg)
        if self.agent:
            self.agent.update_config(self.cfg)

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
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.show()

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
        self.append_message("Tu (voce)", text, "#79a6ff")
        self.run_command(text)

    @staticmethod
    def _parse_confirmation(text):
        t = text.lower().strip()
        t = html.unescape(t)
        yes = ["yes", "yeah", "yep", "да", "ага", "конечно", "подтверждаю",
               "давай", "так", "так, да", "так пожалуйста", "da", "да", "sigur", "confirm", "confirmă", "permite", "desigur", "ok", "okay"]
        no = ["no", "nope", "нет", "не надо", "отмена", "отмени", "не разрешаю",
              "nu", "nu permite", "anulează", "anuleaza", "refuz", "stop"]
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
            result = self.agent.handle(text, confirm_callback=self.confirm_action)
        except Exception as e:
            result = f"Eroare: {e}"
        self.append_message("Nexora AI", result, "#a5b9dc")
        if self.cfg.get("tts_enabled", True):
            speak(result, enabled=True)

    def confirm_action(self, description):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Confirmă acțiunea")
        dialog.setText(f"Nexora AI dorește să execute:\\n\\n{description}\\n\\nSpune „da” sau „nu” ori alege un buton.")
        dialog.setInformativeText("Răspuns vocal disponibil cât timp microfonul este activ.")
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText("Da")
        dialog.button(QMessageBox.StandardButton.No).setText("Nu")
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        self.pending_confirmation_dialog = dialog
        self.pending_confirmation_result = None
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
        self.stop_listener()
        event.accept()

app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(STYLE)
w = MainWindow()
w.show()
sys.exit(app.exec())
