import sys, json
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QCheckBox, QLineEdit, QTextEdit, QFileDialog,
    QMessageBox, QComboBox)

from luxai.agent import LocalAgent
from luxai.voice import VoiceListener, speak
from luxai.screen import capture_screen, read_screen_text

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "config.json"

def load_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_config(cfg):
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

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
                prefix_enabled=self.cfg.get("prefix_enabled", True),
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
        self.setWindowTitle("Lux AI Local")
        self.resize(900, 680)
        self.cfg = load_config()
        self.agent = LocalAgent(self.cfg)
        self.worker = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        title = QLabel("LUX AI  ·  ASISTENT LOCAL")
        title.setStyleSheet("font-size:22px;font-weight:700;padding:8px")
        layout.addWidget(title)

        row = QHBoxLayout()
        self.mic = QCheckBox("Microfon activ")
        self.mic.setChecked(self.cfg.get("microphone_enabled", True))
        self.mic.toggled.connect(self.toggle_mic)
        row.addWidget(self.mic)
        self.prefix = QCheckBox("Necesită prefix")
        self.prefix.setChecked(self.cfg.get("prefix_enabled", True))
        self.prefix.toggled.connect(self.save_settings)
        row.addWidget(self.prefix)
        self.tts = QCheckBox("Răspuns vocal")
        self.tts.setChecked(self.cfg.get("tts_enabled", True))
        self.tts.toggled.connect(self.save_settings)
        row.addWidget(self.tts)
        row.addStretch()
        layout.addLayout(row)

        p = QHBoxLayout()
        p.addWidget(QLabel("Prefix:"))
        self.prefix_text = QLineEdit(self.cfg.get("wake_prefix", "Jarvis"))
        self.prefix_text.setMaximumWidth(180)
        p.addWidget(self.prefix_text)
        p.addWidget(QLabel("Limbă:"))
        self.language = QComboBox()
        self.language.addItem("Detectare automată", "auto")
        self.language.addItem("Română", "ro")
        self.language.addItem("Русский", "ru")
        self.language.addItem("English", "en")
        idx = self.language.findData(self.cfg.get("language", "auto"))
        self.language.setCurrentIndex(max(0, idx))
        p.addWidget(self.language)
        self.model_btn = QPushButton("Alege model AI (.gguf)")
        self.model_btn.clicked.connect(self.pick_model)
        p.addWidget(self.model_btn)
        p.addStretch()
        layout.addLayout(p)

        actions = QHBoxLayout()
        self.screen_btn = QPushButton("Captură ecran")
        self.screen_btn.clicked.connect(self.screen_action)
        self.ocr_btn = QPushButton("Citește textul de pe ecran")
        self.ocr_btn.clicked.connect(self.ocr_action)
        actions.addWidget(self.screen_btn)
        actions.addWidget(self.ocr_btn)
        layout.addLayout(actions)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Conversația cu Lux AI apare aici…")
        layout.addWidget(self.log, 1)

        cmd = QHBoxLayout()
        self.command = QLineEdit()
        self.command.setPlaceholderText("Scrie o comandă…")
        self.command.returnPressed.connect(self.submit_command)
        self.send = QPushButton("Trimite")
        self.send.clicked.connect(self.submit_command)
        cmd.addWidget(self.command, 1)
        cmd.addWidget(self.send)
        layout.addLayout(cmd)

        self.status = QLabel("Pregătit. Selectează un model GGUF pentru conversație AI.")
        self.status.setStyleSheet("padding:5px;color:#777")
        layout.addWidget(self.status)

        self.save_settings()
        if self.mic.isChecked():
            self.start_listener()

    def save_settings(self, *_):
        self.cfg.update({
            "microphone_enabled": self.mic.isChecked(),
            "prefix_enabled": self.prefix.isChecked(),
            "wake_prefix": self.prefix_text.text().strip() or "Jarvis",
            "language": self.language.currentData(),
            "tts_enabled": self.tts.isChecked()
        })
        save_config(self.cfg)
        if self.agent:
            self.agent.update_config(self.cfg)

    def toggle_mic(self, enabled):
        self.save_settings()
        if enabled:
            self.start_listener()
        else:
            self.stop_listener()
            self.status.setText("Microfon oprit — nu ascultă.")

    def start_listener(self):
        if self.worker and self.worker.isRunning():
            return
        self.save_settings()
        self.worker = VoiceWorker(dict(self.cfg))
        self.worker.transcript.connect(self.handle_voice)
        self.worker.status.connect(self.status.setText)
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
            self.status.setText("Model selectat. Se va încărca la prima comandă.")

    def handle_voice(self, text):
        self.log.append(f"<b>Tu (voce):</b> {text}")
        self.run_command(text)

    def submit_command(self):
        text = self.command.text().strip()
        if not text:
            return
        self.command.clear()
        self.log.append(f"<b>Tu:</b> {text}")
        self.run_command(text)

    def run_command(self, text):
        self.save_settings()
        try:
            result = self.agent.handle(text, confirm_callback=self.confirm_action)
        except Exception as e:
            result = f"Eroare: {e}"
        self.log.append(f"<b>Lux AI:</b> {result}")
        if self.cfg.get("tts_enabled", True):
            speak(result, enabled=True)

    def confirm_action(self, description):
        answer = QMessageBox.question(self, "Confirmă acțiunea",
            f"Lux AI dorește să execute:\n\n{description}\n\nPermiți această acțiune?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def screen_action(self):
        try:
            path = capture_screen()
            self.log.append(f"Captură salvată local: {path}")
        except Exception as e:
            QMessageBox.warning(self, "Captură ecran", str(e))

    def ocr_action(self):
        try:
            path = capture_screen()
            text = read_screen_text(path, self.cfg.get("tesseract_path", ""))
            self.log.append("<b>Text detectat pe ecran:</b><br>" + (text[:10000] or "(Nu s-a detectat text.)"))
        except Exception as e:
            QMessageBox.warning(self, "OCR", f"OCR nu este configurat sau a eșuat:\n{e}")

    def closeEvent(self, event):
        self.stop_listener()
        event.accept()

app = QApplication(sys.argv)
app.setStyle("Fusion")
w = MainWindow()
w.show()
sys.exit(app.exec())
