"""Public GitHub release checks and an explicit handoff to the Windows updater.

The update check only reads a small version file. Installation remains the
existing updater's transaction, after the running application has exited.
"""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import urllib.request
import webbrowser

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from luxai.icons import set_button_icon, set_label_icon
from luxai.ui_home import ToggleSwitch
from luxai.ui_i18n import tr, translate_widgets
from luxai.ui_preferences import PreferenceRow
from luxai.ui_sidebar import application_version


ROOT = Path(__file__).resolve().parents[1]
VERSION_URL = "https://raw.githubusercontent.com/negevshopmd-svg/LuxAI_local/main/version.txt"
CHANGELOG_URL = "https://github.com/negevshopmd-svg/LuxAI_local/blob/main/CHANGELOG.md"
_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)(?:\.?([a-z]+))?", re.IGNORECASE)


def version_key(value: str) -> tuple[int, int, int, str]:
    """Support both historical 0.3.9.e and compact 0.3.9g patch labels."""
    match = _VERSION.fullmatch(str(value).strip())
    if not match:
        raise ValueError("Invalid application version")
    major, minor, patch, suffix = match.groups()
    return int(major), int(minor), int(patch), (suffix or "").lower()


def fetch_latest_version() -> str:
    request = urllib.request.Request(VERSION_URL, headers={"User-Agent": "LuxAI-Settings"})
    with urllib.request.urlopen(request, timeout=12) as response:
        data = response.read(257)
    if len(data) > 256:
        raise ValueError("Version response is too large")
    version = data.decode("utf-8-sig").strip()
    version_key(version)
    return version


# Only static command text is passed to cmd.exe; the project path is the
# subprocess working directory, never part of a shell expression. Waiting on a
# Windows process handle avoids replacing code while Jarvis is still running.
_UPDATER_HANDOFF = r'''
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
root = Path(sys.argv[1])
pid = int(sys.argv[2])
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel.OpenProcess.restype = wintypes.HANDLE
kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel.WaitForSingleObject.restype = wintypes.DWORD
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
kernel.CloseHandle.restype = wintypes.BOOL
handle = kernel.OpenProcess(0x00100000, False, pid)
if handle:
    try:
        if kernel.WaitForSingleObject(handle, 60000) != 0:
            sys.exit(1)
    finally:
        kernel.CloseHandle(handle)
elif ctypes.get_last_error() != 87:
    sys.exit(1)
subprocess.Popen([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "Update.bat"],
                 cwd=str(root), creationflags=subprocess.CREATE_NEW_CONSOLE)
'''


def launch_updater_after_exit() -> None:
    if sys.platform != "win32":
        raise OSError("The bundled updater requires Windows")
    if not (ROOT / "Update.bat").is_file():
        raise FileNotFoundError("Update.bat")
    subprocess.Popen(
        [sys.executable, "-I", "-c", _UPDATER_HANDOFF, str(ROOT), str(os.getpid())],
        cwd=str(ROOT), shell=False,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


class SettingsUpdates(QWidget):
    preferences_changed = Signal()
    quit_requested = Signal()
    _check_finished = Signal(object, str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsUpdates")
        self.installed_version = application_version()
        self.latest_version = None
        self.last_checked = None
        self.checking = False
        self._auto_checked = False
        self._status_source = "Обновления ещё не проверялись"

        body = QVBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.version_label = QLabel()
        self.version_label.setTextFormat(Qt.TextFormat.PlainText)
        self.version_label.setProperty("i18n_skip", True)
        self.whats_new = QPushButton("Что нового")
        set_button_icon(self.whats_new, "external-link")
        self.whats_new.clicked.connect(lambda: webbrowser.open(CHANGELOG_URL))
        body.addWidget(PreferenceRow("Установленная версия", "", self.version_label))
        links = QHBoxLayout()
        links.addStretch()
        links.addWidget(self.whats_new)
        body.addLayout(links)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 16, 0, 6)
        self.status_icon = QLabel()
        set_label_icon(self.status_icon, "circle-help", size=17, role="muted")
        status_row.addWidget(self.status_icon, 0, Qt.AlignmentFlag.AlignTop)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setProperty("i18n_skip", True)
        status_row.addWidget(self.status, 1)
        body.addLayout(status_row)
        self.last_check_label = QLabel()
        self.last_check_label.setObjectName("Muted")
        self.last_check_label.setWordWrap(True)
        self.last_check_label.setProperty("i18n_skip", True)
        body.addWidget(self.last_check_label)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 10, 0, 10)
        self.check_button = QPushButton("Проверить обновления")
        set_button_icon(self.check_button, "refresh-cw")
        self.check_button.clicked.connect(self.start_check)
        actions.addWidget(self.check_button)
        self.install_button = QPushButton("Закрыть Jarvis и обновить")
        set_button_icon(self.install_button, "download")
        self.install_button.clicked.connect(self.request_install)
        self.install_button.hide()
        actions.addWidget(self.install_button)
        body.addLayout(actions)

        self.automatic = ToggleSwitch(bool(config.get("check_updates_automatically", False)))
        body.addWidget(PreferenceRow(
            "Проверять обновления автоматически",
            "Один раз при открытии настроек. Установка запускается только по вашей кнопке.",
            self.automatic,
        ))
        self.automatic.toggled.connect(self._automatic_changed)
        self.platform_hint = QLabel("На Windows обновление выполняется через Update.bat после закрытия Jarvis.")
        self.platform_hint.setObjectName("Muted")
        self.platform_hint.setWordWrap(True)
        body.addWidget(self.platform_hint)
        self._check_finished.connect(self._on_check_finished)
        self.retranslate()

    def collect(self):
        return {"check_updates_automatically": self.automatic.isChecked()}

    def showEvent(self, event):
        super().showEvent(event)
        self._maybe_auto_check()

    def _automatic_changed(self, *_):
        self.preferences_changed.emit()
        self._maybe_auto_check()

    def _maybe_auto_check(self):
        if self.isVisible() and self.automatic.isChecked() and not self._auto_checked:
            self._auto_checked = True
            QTimer.singleShot(0, self.start_check)

    def start_check(self):
        if self.checking:
            return
        self.checking = True
        self._status_source = "Проверяю обновления…"
        self.check_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.retranslate()
        signal = self._check_finished

        def check():
            try:
                latest, error = fetch_latest_version(), ""
            except Exception:
                latest, error = None, "Не удалось проверить обновления. Проверьте подключение и повторите."
            try:
                signal.emit(latest, error)
            except RuntimeError:
                pass  # Settings may be destroyed while the bounded request finishes.

        threading.Thread(target=check, name="LuxAI-update-check", daemon=True).start()

    def _on_check_finished(self, latest, error):
        self.checking = False
        self.last_checked = datetime.now().astimezone()
        self.check_button.setEnabled(True)
        self.install_button.setEnabled(True)
        self.latest_version = latest
        available = False
        if error:
            self._status_source = error
            name, role = "circle-alert", "warning"
        else:
            try:
                installed_key, latest_key = version_key(self.installed_version), version_key(latest)
            except ValueError:
                self._status_source = "Не удалось определить установленную версию."
                name, role = "circle-alert", "warning"
            else:
                available = latest_key > installed_key
                if available:
                    self._status_source = "Доступна версия {version}"
                    name, role = "download", "accent"
                elif latest_key == installed_key:
                    self._status_source = "У вас последняя версия"
                    name, role = "check-circle-2", "success"
                else:
                    self._status_source = "Установленная версия новее опубликованной"
                    name, role = "check-circle-2", "success"
        self.install_button.setVisible(available and sys.platform == "win32")
        set_label_icon(self.status_icon, name, size=17, role=role)
        self.retranslate()

    def request_install(self):
        if self.checking or not self.latest_version:
            return
        try:
            if version_key(self.latest_version) <= version_key(self.installed_version):
                return
        except ValueError:
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle(tr("Обновления"))
        dialog.setText(tr("Закрыть Jarvis и запустить обновление? Настройки и модели сохранятся."))
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText(tr("Да"))
        dialog.button(QMessageBox.StandardButton.No).setText(tr("Нет"))
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        if dialog.exec() != QMessageBox.StandardButton.Yes:
            return
        try:
            launch_updater_after_exit()
        except OSError:
            self._status_source = "Не удалось запустить Update.bat. Закройте Jarvis и запустите его вручную."
            self.retranslate()
            return
        self.quit_requested.emit()

    def retranslate(self):
        translate_widgets(self)
        self.version_label.setText(self.installed_version)
        self.status.setText(tr(self._status_source).format(version=self.latest_version or ""))
        if self.last_checked:
            self.last_check_label.setText(tr("Последняя проверка: {time}").format(
                time=self.last_checked.strftime("%d.%m.%Y %H:%M")))
        else:
            self.last_check_label.setText(tr("Последняя проверка: ещё не выполнялась"))
