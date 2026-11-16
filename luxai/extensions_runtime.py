"""Runtime of the working extensions (0.4.0).

The Extensions page only edits state; ``ExtensionsRuntime.apply(state)``
starts or stops every *ready* plugin from it. Global shortcuts use their own
``WindowsHotkeyListener`` (RegisterHotKey, no keyboard hooks) so they never
interfere with command shortcuts. Everything here stays on this computer:
no plugin sends clipboard, files or screenshots to any network service.

Pure helpers (cleanup planning, conversion, snippet expansion, secret
heuristics) have no Qt dependency so they are covered by plain unit tests.
"""
from __future__ import annotations

import ctypes
import datetime as _dt
import os
import re
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from luxai.extensions_catalog import PLUGIN_BY_ID, parse_snippets, text

# --- pure helpers ----------------------------------------------------------

CLEANUP_GROUPS = {
    "images": ({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".svg", ".tif", ".tiff", ".ico"},
               {"ru": "Картинки", "en": "Images", "ro": "Imagini"}),
    "video": ({".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".m4v"},
              {"ru": "Видео", "en": "Video", "ro": "Video"}),
    "music": ({".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus"},
              {"ru": "Музыка", "en": "Music", "ro": "Muzică"}),
    "documents": ({".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".rtf", ".odt",
                   ".ods", ".csv", ".epub", ".djvu", ".fb2"},
                  {"ru": "Документы", "en": "Documents", "ro": "Documente"}),
    "archives": ({".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"},
                 {"ru": "Архивы", "en": "Archives", "ro": "Arhive"}),
    "installers": ({".exe", ".msi", ".msix", ".appx", ".msixbundle"},
                   {"ru": "Установщики", "en": "Installers", "ro": "Instalatoare"}),
}
_PARTIAL = {".crdownload", ".part", ".partial", ".tmp", ".download", ".opdownload"}
_SKIP_NAMES = {"desktop.ini", "thumbs.db"}


@dataclass(frozen=True)
class CleanupStep:
    source: Path
    target: Path | None  # None means "send to Recycle Bin"
    group: str


def downloads_folder() -> Path:
    """The user's real Downloads known folder (it can be relocated)."""
    if sys.platform == "win32":
        try:
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

            folder = GUID(0x374DE290, 0x123F, 0x4565, (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
            pointer = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder), 0, None, ctypes.byref(pointer)) == 0:
                try:
                    return Path(pointer.value)
                finally:
                    ctypes.windll.ole32.CoTaskMemFree(pointer)
        except (OSError, AttributeError, ValueError):
            pass
    return Path.home() / "Downloads"


def plan_cleanup(folder: Path, *, min_age_days: int, installer_trash_days: int,
                 language: str = "ru", now: float | None = None) -> list[CleanupStep]:
    """Plan moving top-level files of ``folder`` into typed subfolders.

    Only regular top-level files are considered: folders, hidden files,
    partial downloads and files younger than ``min_age_days`` are left alone.
    """
    now = time.time() if now is None else now
    folder = Path(folder)
    steps = []
    try:
        entries = sorted(folder.iterdir(), key=lambda item: item.name.casefold())
    except OSError:
        return []
    for entry in entries:
        try:
            if not entry.is_file() or entry.is_symlink():
                continue
            name = entry.name
            if name.startswith(".") or name.casefold() in _SKIP_NAMES:
                continue
            suffix = entry.suffix.casefold()
            if suffix in _PARTIAL:
                continue
            age_days = (now - entry.stat().st_mtime) / 86400
        except OSError:
            continue
        if age_days < min_age_days:
            continue
        group = next((key for key, (suffixes, _) in CLEANUP_GROUPS.items() if suffix in suffixes), "")
        if not group:
            continue
        if group == "installers" and installer_trash_days > 0 and age_days >= installer_trash_days:
            steps.append(CleanupStep(entry, None, group))
            continue
        label = CLEANUP_GROUPS[group][1].get(language) or CLEANUP_GROUPS[group][1]["ru"]
        steps.append(CleanupStep(entry, folder / label / name, group))
    return steps


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise OSError("Слишком много файлов с одинаковым именем.")


def run_cleanup(steps: list[CleanupStep], *, trash=None) -> tuple[int, int, list[str]]:
    """Execute a plan. Returns (moved, trashed, errors)."""
    if trash is None:
        from send2trash import send2trash as trash
    moved = trashed = 0
    errors = []
    for step in steps:
        try:
            if not step.source.is_file():
                continue
            if step.target is None:
                trash(str(step.source))
                trashed += 1
            else:
                step.target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(step.source), str(unique_path(step.target)))
                moved += 1
        except Exception as error:  # one locked file must not stop the rest
            errors.append(f"{step.source.name}: {error}")
    return moved, trashed, errors


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".ico"}


def convert_image(source: Path, fmt: str, *, quality: int = 85, max_side: int = 0) -> Path:
    """Write a converted copy next to ``source``; never overwrite anything."""
    from PIL import Image

    fmt = fmt.lower()
    if fmt not in {"png", "jpg", "webp", "ico", "pdf"}:
        raise ValueError("Неподдерживаемый формат.")
    source = Path(source)
    with Image.open(source) as opened:
        image = opened.copy()
    if max_side and max(image.size) > max_side:
        image.thumbnail((max_side, max_side))
    target = unique_path(source.with_name(f"{source.stem}{'_' + fmt if source.suffix.lower().lstrip('.') == fmt else ''}.{fmt}"))
    if fmt in {"jpg", "pdf"} and image.mode not in ("RGB", "L"):
        background = Image.new("RGB", image.size, "white")
        rgba = image.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        image = background
    if fmt == "jpg":
        image.save(target, "JPEG", quality=int(quality), optimize=True)
    elif fmt == "webp":
        image.save(target, "WEBP", quality=int(quality))
    elif fmt == "ico":
        sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= max(image.size)] or [(16, 16)]
        image.save(target, "ICO", sizes=sizes)
    elif fmt == "pdf":
        image.save(target, "PDF", resolution=150.0)
    else:
        image.save(target, "PNG", optimize=True)
    return target


_SECRET_TOKEN = re.compile(r"^[A-Za-z0-9_\-+/=.:]{16,200}$")


def looks_secret(value: str) -> bool:
    """Heuristic: one-time codes, tokens and password-like single words."""
    value = str(value or "").strip()
    if not value or "\n" in value or " " in value:
        return False
    if re.fullmatch(r"\d{5,8}", value):
        return True
    if value.lower().startswith(("sk-", "ghp_", "github_pat_", "xox", "aiza")):
        return True
    if _SECRET_TOKEN.fullmatch(value) and not value.lower().startswith(("http://", "https://", "www.")):
        classes = sum(bool(re.search(pattern, value)) for pattern in (r"[a-z]", r"[A-Z]", r"\d", r"[_\-+/=.:]"))
        return classes >= 3
    if 8 <= len(value) <= 40 and re.search(r"[a-z]", value) and re.search(r"[A-Z]", value) \
            and re.search(r"\d", value) and re.search(r"[^A-Za-z0-9]", value):
        return True
    return False


def expand_snippet(body: str, now: _dt.datetime | None = None) -> str:
    now = now or _dt.datetime.now()
    replacements = {
        "{дата}": now.strftime("%d.%m.%Y"), "{date}": now.strftime("%d.%m.%Y"), "{data}": now.strftime("%d.%m.%Y"),
        "{время}": now.strftime("%H:%M"), "{time}": now.strftime("%H:%M"), "{ora}": now.strftime("%H:%M"),
    }
    for key, value in replacements.items():
        body = body.replace(key, value)
    return body


def break_message(kind: str, language: str) -> str:
    messages = {
        "eyes": {"ru": "Пора дать глазам отдых: 20 секунд смотрите на что-нибудь вдали.",
                 "en": "Time to rest your eyes: look at something far away for 20 seconds.",
                 "ro": "E timpul să-ți odihnești ochii: privește ceva departe timp de 20 de secunde."},
        "water": {"ru": "Выпейте немного воды.", "en": "Have a little water.", "ro": "Bea puțină apă."},
        "stretch": {"ru": "Встаньте и разомнитесь пару минут.", "en": "Stand up and stretch for a couple of minutes.",
                    "ro": "Ridică-te și întinde-te câteva minute."},
    }
    return messages[kind].get(language) or messages[kind]["ru"]


# --- Windows helpers -------------------------------------------------------

def idle_seconds() -> float:
    if sys.platform != "win32":
        return 0.0

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return max(0.0, (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0)


def _foreground_rect():
    if sys.platform != "win32":
        return None
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    rect = wintypes.RECT()
    try:
        # DWM bounds exclude the invisible resize border of Windows 10/11.
        if ctypes.windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
            raise OSError
    except OSError:
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    return (rect.left, rect.top, width, height) if width > 0 and height > 0 else None


def foreground_is_fullscreen() -> bool:
    if sys.platform != "win32":
        return False
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd or hwnd in (user32.GetDesktopWindow(), user32.GetShellWindow()):
        return False
    rect = _foreground_rect()
    if rect is None:
        return False
    from ctypes import wintypes

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    monitor = user32.MonitorFromWindow(hwnd, 2)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(info)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return False
    m = info.rcMonitor
    left, top, width, height = rect
    return left <= m.left and top <= m.top and left + width >= m.right and top + height >= m.bottom


MEDIA_KEYS = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1,
              "volume_up": 0xAF, "volume_down": 0xAE, "mute": 0xAD}


def press_virtual_key(code: int) -> None:
    if sys.platform != "win32":
        return
    user32 = ctypes.windll.user32
    user32.keybd_event(code, 0, 0x0001, 0)        # KEYEVENTF_EXTENDEDKEY
    user32.keybd_event(code, 0, 0x0001 | 0x0002, 0)  # + KEYEVENTF_KEYUP


def _set_foreground(hwnd: int) -> None:
    if sys.platform == "win32" and hwnd:
        try:
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        except OSError:
            pass


def _send_paste() -> None:
    import pyautogui
    pyautogui.hotkey("ctrl", "v", interval=0.05)


def screenshots_folder(configured: str) -> Path:
    if configured:
        return Path(os.path.expandvars(os.path.expanduser(configured)))
    return Path.home() / "Pictures" / "Jarvis Screenshots"


def capture_png(region=None) -> bytes:
    """PNG bytes of the whole virtual screen or a (left, top, w, h) region."""
    import mss
    import mss.tools
    with mss.mss() as grabber:
        monitor = grabber.monitors[0] if region is None else {
            "left": region[0], "top": region[1], "width": region[2], "height": region[3]}
        shot = grabber.grab(monitor)
        return mss.tools.to_png(shot.rgb, shot.size)


# --- Qt runtime ------------------------------------------------------------

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, Signal  # noqa: E402
from PySide6.QtGui import QCursor, QGuiApplication, QImage  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)


class PickerPopup(QDialog):
    """Small searchable list shown at the cursor (clipboard / snippets)."""
    picked = Signal(object)
    pin_toggled = Signal(object)

    def __init__(self, title: str, items: list[tuple[str, object, bool]], *, placeholder: str,
                 empty: str, pin_label: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("ExtensionPicker")
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setProperty("i18n_skip", True)
        self.resize(380, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        heading = QLabel(title)
        heading.setStyleSheet("font-size:15px;font-weight:700;")
        layout.addWidget(heading)
        self.search = QLineEdit()
        self.search.setPlaceholderText(placeholder)
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.setProperty("i18n_skip", True)
        self.list.itemActivated.connect(self._activate)
        self.list.itemDoubleClicked.connect(self._activate)
        layout.addWidget(self.list, 1)
        self.empty = QLabel(empty)
        self.empty.setObjectName("Muted")
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        if pin_label:
            row = QHBoxLayout()
            self.pin_button = QPushButton(pin_label)
            self.pin_button.clicked.connect(self._pin)
            row.addWidget(self.pin_button)
            row.addStretch()
            layout.addLayout(row)
        for label, payload, pinned in items:
            item = QListWidgetItem(("📌 " if pinned else "") + label)
            item.setData(Qt.ItemDataRole.UserRole, payload)
            item.setToolTip(label[:500])
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.empty.setVisible(self.list.count() == 0)
        self.search.setFocus()

    def _filter(self, value):
        words = value.casefold().split()
        for row in range(self.list.count()):
            item = self.list.item(row)
            item.setHidden(not all(word in item.text().casefold() for word in words))
        visible = [row for row in range(self.list.count()) if not self.list.item(row).isHidden()]
        if visible:
            self.list.setCurrentRow(visible[0])

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            item = self.list.currentItem()
            if item is not None and not item.isHidden():
                self._activate(item)
            return
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self.search.hasFocus():
            self.list.setFocus()
            self.list.keyPressEvent(event)
            return
        super().keyPressEvent(event)

    def _activate(self, item):
        payload = item.data(Qt.ItemDataRole.UserRole)
        self.close()
        self.picked.emit(payload)

    def _pin(self):
        item = self.list.currentItem()
        if item is not None:
            self.pin_toggled.emit(item.data(Qt.ItemDataRole.UserRole))
            self.close()

    def show_at_cursor(self):
        position = QCursor.pos()
        screen = QGuiApplication.screenAt(position) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(area.left(), position.x() - 20), area.right() - self.width())
        y = min(max(area.top(), position.y() - 20), area.bottom() - self.height())
        self.move(QPoint(x, y))
        self.show()
        self.raise_()
        self.activateWindow()


class DictationOverlay(QDialog):
    """Small always-on-top status pill that never takes keyboard focus."""

    def __init__(self):
        super().__init__(None)
        self.setObjectName("DictationOverlay")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setProperty("i18n_skip", True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        self.label = QLabel()
        self.label.setStyleSheet("font-size:14px;font-weight:600;")
        layout.addWidget(self.label)
        self.setStyleSheet("QDialog#DictationOverlay{border:1px solid #7b5cf0;border-radius:14px;}")

    def show_text(self, message: str):
        self.label.setText(message)
        self.adjustSize()
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(area.center().x() - self.width() // 2, area.bottom() - self.height() - 48)
        self.show()
        self.raise_()


class RingDialog(QDialog):
    """Always-on-top alarm window with Snooze and Stop."""
    snoozed = Signal()
    stopped = Signal()

    def __init__(self, title: str, body: str, snooze_label: str, stop_label: str):
        super().__init__(None)
        self.setObjectName("RingDialog")
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setProperty("i18n_skip", True)
        self.setStyleSheet("QDialog#RingDialog{border:2px solid #7c3aed;border-radius:16px;}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(10)
        heading = QLabel(title)
        heading.setStyleSheet("font-size:22px;font-weight:800;")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)
        if body:
            text_label = QLabel(body)
            text_label.setWordWrap(True)
            text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            text_label.setStyleSheet("font-size:15px;")
            layout.addWidget(text_label)
        row = QHBoxLayout()
        snooze = QPushButton(snooze_label)
        snooze.setMinimumHeight(40)
        snooze.clicked.connect(lambda: (self.snoozed.emit(), self.close()))
        stop = QPushButton(stop_label)
        stop.setObjectName("Primary")
        stop.setMinimumHeight(40)
        stop.setDefault(True)
        stop.clicked.connect(lambda: (self.stopped.emit(), self.close()))
        row.addWidget(snooze)
        row.addWidget(stop)
        layout.addLayout(row)
        self.resize(380, 180)

    def show_centered(self):
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - self.width() // 2, screen.center().y() - self.height() // 2)
        self.show()
        self.raise_()
        self.activateWindow()


def _beep(frequency: int):
    """Short cue; played before the microphone opens so it is not recorded."""
    if sys.platform != "win32":
        return
    import winsound
    try:
        winsound.Beep(frequency, 60)
    except RuntimeError:
        pass


def _tr3(ru, en, ro, language):
    return {"ru": ru, "en": en, "ro": ro}.get(language, ru)


class ExtensionsRuntime(QObject):
    """Starts/stops ready plugins. ``host`` is the MainWindow-like object.

    The host may provide: ``cfg`` (dict), ``tray_icon``, ``_queue_speech(text, lang)``,
    ``stop_speaking()``. Missing members are tolerated (tests use a stub).
    """
    hotkey = Signal(str)
    notice = Signal(str)
    dictation_result = Signal(str, str, bool)  # text, error, test
    dictation_done = Signal(str)  # last dictated text, for the settings page
    pc_status_changed = Signal(str, dict)  # state, details (bot name, error)
    timers_changed = Signal()
    _pc_update = Signal(dict)
    _pc_status = Signal(str, dict)

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.state: dict = {}
        self.errors: dict[str, str] = {}
        self.clipboard_items: list[dict] = []  # {"text": str, "pinned": bool}
        self._ignore_clipboard_text = None
        self._listener = None
        self._reading = False
        self._active_seconds = 0.0
        self._break_index = 0
        self._last_tick = time.monotonic()
        self.hotkey.connect(self._on_hotkey)
        self._break_timer = QTimer(self)
        self._break_timer.setInterval(30_000)
        self._break_timer.timeout.connect(self._tick_breaks)
        self._cleanup_timer = QTimer(self)
        self._cleanup_timer.setInterval(60 * 60 * 1000)
        self._cleanup_timer.timeout.connect(self._auto_cleanup)
        self._clipboard_connected = False
        self._recorder = None
        self._dictation_target = 0
        self._dictation_test = False
        self._dictation_busy = False
        self._dictation_source = "key"
        self._overlay = None
        self.last_dictation = ""
        self.test_sink = None  # settings page test box, when focused inside Jarvis
        self._dictation_timer = QTimer(self)
        self._dictation_timer.setInterval(60)
        self._dictation_timer.timeout.connect(self._dictation_tick)
        from luxai.dictation import DoubleTapDetector
        self._double_tap = DoubleTapDetector()
        self._tap_timer = QTimer(self)
        self._tap_timer.setInterval(25)
        self._tap_timer.timeout.connect(self._poll_double_tap)
        self.dictation_result.connect(self._on_dictation_result)
        self._bot = None
        self._bot_token = ""
        self._pc_applied_once = False
        self.pc_state = ("stopped", {})
        from luxai.telegram_control import MenuState
        self._menu_state = MenuState()
        self._pc_update.connect(self._on_pc_update)
        self._timer_store = None
        self._timer_tick = QTimer(self)
        self._timer_tick.setInterval(1000)
        self._timer_tick.timeout.connect(self._check_timers)
        self._ringing: list = []  # (timer, dialog)
        self._ring_until = 0.0
        self._ring_beeper = QTimer(self)
        self._ring_beeper.setInterval(1400)
        self._ring_beeper.timeout.connect(self._ring_beep)
        self._pc_status.connect(self._on_pc_status)

    # -- helpers --
    @property
    def language(self) -> str:
        cfg = getattr(self.host, "cfg", {}) or {}
        language = cfg.get("ui_language", "ru")
        return language if language in ("ru", "en", "ro") else "ru"

    def enabled(self, plugin_id: str) -> bool:
        return bool(self.state.get(plugin_id, {}).get("enabled"))

    def settings(self, plugin_id: str) -> dict:
        return self.state.get(plugin_id, {}).get("settings", {})

    def _notify(self, message: str, *, speak: bool = False):
        tray = getattr(self.host, "tray_icon", None)
        try:
            from PySide6.QtWidgets import QSystemTrayIcon
            if tray is not None and tray.isVisible() and QSystemTrayIcon.supportsMessages():
                tray.showMessage("Jarvis", message, QSystemTrayIcon.MessageIcon.Information, 8000)
            else:
                self.notice.emit(message)
        except Exception:
            self.notice.emit(message)
        if speak and hasattr(self.host, "_queue_speech"):
            self.host._queue_speech(message, self.language)

    # -- lifecycle --
    def apply(self, state: dict):
        self.state = state
        if self.enabled("breaks"):
            if not self._break_timer.isActive():
                self._active_seconds = 0.0
                self._last_tick = time.monotonic()
                self._break_timer.start()
        else:
            self._break_timer.stop()
        clipboard = QApplication.clipboard() if QApplication.instance() else None
        if clipboard is not None:
            if self.enabled("clipboard_history") and not self._clipboard_connected:
                clipboard.dataChanged.connect(self._on_clipboard)
                self._clipboard_connected = True
            elif not self.enabled("clipboard_history") and self._clipboard_connected:
                try:
                    clipboard.dataChanged.disconnect(self._on_clipboard)
                except (RuntimeError, TypeError):
                    pass
                self._clipboard_connected = False
        if self.enabled("clipboard_history"):
            self._trim_clipboard()
        if self.enabled("smart_dictation") and self.settings("smart_dictation").get("trigger") == "right_ctrl_double" \
                and sys.platform == "win32":
            if not self._tap_timer.isActive():
                self._tap_timer.start()
        else:
            self._tap_timer.stop()
        if not self.enabled("smart_dictation") and self.dictating:
            self.cancel_dictation()
        self._apply_pc_control()
        self._apply_timers()
        if self.enabled("downloads_cleanup") and self.settings("downloads_cleanup").get("auto"):
            if not self._cleanup_timer.isActive():
                self._cleanup_timer.start()
                QTimer.singleShot(15_000, self._auto_cleanup)
        else:
            self._cleanup_timer.stop()
        self._sync_hotkeys()

    def hotkey_entries(self) -> list[dict]:
        entries = []
        for plugin_id, entry in self.state.items():
            plugin = PLUGIN_BY_ID.get(plugin_id)
            if plugin is None or not plugin.ready or not entry.get("enabled"):
                continue
            for setting in plugin.settings:
                if plugin_id == "smart_dictation" and entry["settings"].get("trigger") != "hotkey":
                    continue
                if setting.kind == "hotkey" and entry["settings"].get(setting.key):
                    entries.append({"id": f"{plugin_id}.{setting.key}", "enabled": True,
                                    "hotkey": entry["settings"][setting.key]})
        return entries

    def _sync_hotkeys(self):
        entries = self.hotkey_entries()
        if self._listener is None:
            if not entries:
                return
            from luxai.command_triggers import WindowsHotkeyListener
            self._listener = WindowsHotkeyListener(self.hotkey.emit)
        try:
            self._listener.sync(entries)
        except ValueError as error:
            self.errors = {"hotkeys": str(error)}
            return
        QTimer.singleShot(400, self._collect_hotkey_errors)

    def _collect_hotkey_errors(self):
        if self._listener is not None:
            self.errors = dict(self._listener.errors)

    def stop(self):
        self._timer_tick.stop()
        self._ring_beeper.stop()
        self._stop_bot()
        self.cancel_dictation()
        self._tap_timer.stop()
        self._break_timer.stop()
        self._cleanup_timer.stop()
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    # -- hotkeys --
    def _on_hotkey(self, identifier: str):
        plugin_id, _, key = identifier.partition(".")
        if not self.enabled(plugin_id):
            return
        if plugin_id == "smart_dictation":
            self.toggle_dictation()
        elif plugin_id == "clipboard_history":
            self.open_clipboard_history()
        elif plugin_id == "quick_inserts":
            self.open_snippets()
        elif plugin_id == "read_aloud":
            self.read_selection()
        elif plugin_id == "media_keys" and key in MEDIA_KEYS:
            press_virtual_key(MEDIA_KEYS[key])
        elif plugin_id == "screenshots":
            self.take_screenshot(window=(key == "window_hotkey"))

    # -- dialog actions --
    def run_action(self, plugin_id: str, action: str, parent=None, settings: dict | None = None):
        if settings is not None:
            self.state.setdefault(plugin_id, {"enabled": False, "settings": {}})["settings"] = dict(settings)
        handlers = {
            ("read_aloud", "test"): lambda: self._speak(_tr3(
                "Так звучит чтение вслух. Выделите текст и нажмите клавишу.",
                "This is how read aloud sounds. Select text and press the shortcut.",
                "Așa sună citirea cu voce. Selectează text și apasă combinația.", self.language)),
            ("clipboard_history", "open"): self.open_clipboard_history,
            ("clipboard_history", "clear"): self.clear_clipboard,
            ("quick_inserts", "open"): lambda: self.open_snippets(paste=False),
            ("breaks", "test"): lambda: self.remind_break(force=True),
            ("smart_dictation", "test"): lambda: self.start_dictation(test=True),
            ("smart_dictation", "copy_last"): self.copy_last_dictation,
            ("pc_control", "check"): self.check_pc_connection,
            ("pc_control", "open"): self.open_bot,
            ("converter", "convert"): lambda: self.convert_dialog(parent),
            ("screenshots", "capture"): lambda: QTimer.singleShot(350, self.take_screenshot),
            ("screenshots", "open_folder"): self.open_screenshots_folder,
            ("downloads_cleanup", "preview"): lambda: self.cleanup_dialog(parent, execute=False),
            ("downloads_cleanup", "run"): lambda: self.cleanup_dialog(parent, execute=True),
        }
        handler = handlers.get((plugin_id, action))
        if handler is not None:
            handler()

    def _speak(self, message: str):
        if hasattr(self.host, "_queue_speech"):
            self.host._queue_speech(message, self.language)

    # -- smart dictation --
    def _dictation_words(self, key: str) -> str:
        words = {
            "listening": ("● Говорите… ({key} — закончить)", "● Speak… ({key} to finish)", "● Vorbește… ({key} pentru stop)"),
            "listening_hold": ("● Говорите, пока держите {key}", "● Speak while holding {key}", "● Vorbește cât ții {key}"),
            "listening_voice": ("● Говорите… (пауза — закончить)", "● Speak… (pause to finish)", "● Vorbește… (pauza oprește)"),
            "test": ("● Проверка: говорите 5 секунд…", "● Test: speak for 5 seconds…", "● Test: vorbește 5 secunde…"),
            "working": ("Распознаю…", "Recognizing…", "Recunosc…"),
            "nothing": ("Речь не распознана.", "No speech recognized.", "Nu s-a recunoscut nimic."),
            "mic": ("Диктовка: ", "Dictation: ", "Dictare: "),
            "busy": ("Диктовка ещё распознаётся.", "Dictation is still being recognized.", "Dictarea încă se recunoaște."),
            "result": ("Распознано:", "Recognized:", "Recunoscut:"),
            "empty": ("Пока ничего не продиктовано.", "Nothing dictated yet.", "Nimic dictat încă."),
            "copied": ("Последняя диктовка скопирована.", "The last dictation was copied.", "Ultima dictare a fost copiată."),
            "rctrl": ("Правый Ctrl", "Right Ctrl", "Ctrl dreapta"),
        }[key]
        return _tr3(*words, self.language)

    @property
    def dictating(self) -> bool:
        return self._recorder is not None

    def _key_label(self) -> str:
        settings = self.settings("smart_dictation")
        if settings.get("trigger") != "hotkey":
            return self._dictation_words("rctrl") + " ×2"
        return "+".join(part.capitalize() for part in str(settings.get("hotkey", "")).split("+")) or "…"

    def _poll_double_tap(self):
        from luxai.dictation import right_ctrl_down
        event = self._double_tap.update(right_ctrl_down(), time.monotonic())
        mode = self.settings("smart_dictation").get("mode", "hold")
        if event == "double":
            if self.dictating:
                if mode != "hold":
                    self.stop_dictation()
            else:
                self.start_dictation()
        elif event == "release" and mode == "hold" and self.dictating and self._dictation_source == "key":
            self.stop_dictation()

    def toggle_dictation(self):
        if self.dictating:
            if self.settings("smart_dictation").get("mode") != "hold":
                self.stop_dictation()
            return
        self.start_dictation()

    def start_dictation(self, test: bool = False, *, source: str = "key", target: int | None = None):
        from luxai.dictation import DICTATION_ACTIVE, Recorder
        if self.dictating:
            return False
        if self._dictation_busy:
            self._notify(self._dictation_words("busy"))
            return False
        settings = self.settings("smart_dictation")
        cfg = dict(getattr(self.host, "cfg", {}) or {})
        DICTATION_ACTIVE.set()  # close the command listener gate first
        if settings.get("sound", True):
            _beep(880)
        try:
            recorder = Recorder(cfg)
            recorder.start()
        except Exception as error:
            DICTATION_ACTIVE.clear()
            self._notify(self._dictation_words("mic") + str(error))
            return False
        self._recorder = recorder
        self._dictation_test = test
        self._dictation_source = source
        self._dictation_target = 0 if test else (target if target is not None else _foreground_window())
        self._dictation_started = time.monotonic()
        if self._overlay is None:
            self._overlay = DictationOverlay()
        if test:
            key = "test"
        elif source == "voice":
            key = "listening_voice"
        else:
            key = "listening_hold" if settings.get("mode", "hold") == "hold" else "listening"
        self._overlay.show_text(self._dictation_words(key).format(key=self._key_label()))
        self._dictation_timer.start()
        return True

    def _dictation_tick(self):
        from luxai.dictation import key_held
        recorder = self._recorder
        if recorder is None:
            self._dictation_timer.stop()
            return
        settings = self.settings("smart_dictation")
        elapsed = time.monotonic() - self._dictation_started
        mode = settings.get("mode", "hold")
        pause = int(settings.get("silence_pause", 2))
        if recorder.full or (self._dictation_test and elapsed >= 5):
            self.stop_dictation()
        elif self._dictation_test:
            return
        elif self._dictation_source == "voice" or mode == "toggle":
            if recorder.silent_for() >= pause or (not recorder.voiced_once and elapsed >= 8):
                self.stop_dictation()
        elif (settings.get("trigger") == "hotkey" and elapsed > 0.25
                and not key_held(settings.get("hotkey", ""))):
            self.stop_dictation()

    def cancel_dictation(self):
        from luxai.dictation import DICTATION_ACTIVE
        self._dictation_timer.stop()
        if self._recorder is not None:
            self._recorder.stop()
            self._recorder = None
        if self._overlay is not None:
            self._overlay.hide()
        DICTATION_ACTIVE.clear()

    def stop_dictation(self):
        from luxai import dictation
        recorder = self._recorder
        if recorder is None:
            return
        self._recorder = None
        self._dictation_timer.stop()
        audio = recorder.stop()
        settings = dict(self.settings("smart_dictation"))
        if settings.get("sound", True):
            threading.Thread(target=_beep, args=(660,), daemon=True).start()
        if self._overlay is not None:
            self._overlay.show_text(self._dictation_words("working"))
        cfg = dict(getattr(self.host, "cfg", {}) or {})
        language = settings.get("language", "auto")
        if language == "auto":
            language = cfg.get("language", "auto")
        language = None if language in ("auto", "", None) else language
        model_provider = getattr(self.host, "dictation_model", None)
        planner = getattr(self.host, "online_planner", None)
        test = self._dictation_test
        self._dictation_busy = True

        def work():
            try:
                model = model_provider() if callable(model_provider) else None
                if model is None:
                    model = dictation.load_model(cfg.get("whisper_model_path") or cfg.get("whisper_model") or "small")
                text = dictation.transcribe(model, audio, language, int(cfg.get("whisper_beam_size", 1) or 1))
                self.dictation_result.emit(self.finish_text(text, settings, planner), "", test)
            except Exception as error:
                self.dictation_result.emit("", f"{type(error).__name__}: {error}", test)

        threading.Thread(target=work, daemon=True, name="JarvisDictation").start()

    @staticmethod
    def finish_text(text: str, settings: dict, planner=None) -> str:
        from luxai.dictation import apply_spoken_punctuation
        if text and settings.get("punctuation", True):
            text = apply_spoken_punctuation(text)
        if text and settings.get("ai_cleanup") and planner is not None and hasattr(planner, "polish_dictation"):
            text = planner.polish_dictation(text) or text
        return text

    def _on_dictation_result(self, text: str, error: str, test: bool):
        from luxai.dictation import DICTATION_ACTIVE
        self._dictation_busy = False
        if self._overlay is not None:
            self._overlay.hide()
        DICTATION_ACTIVE.clear()
        if error:
            self._notify(self._dictation_words("mic") + error)
            return
        if not text:
            self._notify(self._dictation_words("nothing"))
            return
        self.last_dictation = text
        self.dictation_done.emit(text)
        if test:
            QMessageBox.information(None, _tr3("Умная диктовка", "Smart dictation", "Dictare inteligentă", self.language),
                                    self._dictation_words("result") + "\n\n" + text)
            return
        self.insert_dictation(text, self._dictation_target)

    def insert_dictation(self, text: str, target: int):
        from luxai.dictation import type_text, wait_for_modifiers_released
        if not target and self.test_sink is not None and self.test_sink(text):
            return
        if not target:
            QApplication.clipboard().setText(text)
            self._notify(_tr3("Нет активного поля — текст скопирован в буфер обмена.",
                              "No active field — the text was copied to the clipboard.",
                              "Niciun câmp activ — textul a fost copiat în clipboard.", self.language))
            return
        wait_for_modifiers_released()
        _set_foreground(target)
        try:
            type_text(text)
        except Exception as error:
            QApplication.clipboard().setText(text)
            self._notify(_tr3("Не удалось напечатать, текст в буфере обмена: ",
                              "Could not type; the text is on the clipboard: ",
                              "Nu am putut scrie; textul e în clipboard: ", self.language) + str(error))

    def handle_voice_request(self, spoken: str, target: int) -> bool:
        """«Джарвис, напиши …»: type at once, or record until a pause."""
        if not self.enabled("smart_dictation"):
            return False
        settings = self.settings("smart_dictation")
        if not settings.get("voice_trigger"):
            return False
        from luxai.dictation import voice_dictation_request
        cfg = getattr(self.host, "cfg", {}) or {}
        request = voice_dictation_request(spoken, settings.get("voice_phrases", ""), cfg.get("wake_prefix", ""))
        if request is None:
            return False
        if request:
            text = self.finish_text(request, settings)
            self.last_dictation = text
            self.dictation_done.emit(text)
            self.insert_dictation(text, target)
        else:
            self.start_dictation(source="voice", target=target)
        return True

    def copy_last_dictation(self):
        if not self.last_dictation:
            self._notify(self._dictation_words("empty"))
            return
        QApplication.clipboard().setText(self.last_dictation)
        self._notify(self._dictation_words("copied"))

    # -- secrets --
    def has_secret(self, plugin_id: str, key: str) -> bool:
        if (plugin_id, key) != ("pc_control", "token"):
            return False
        try:
            from luxai.secure_keys import has_api_key
            return has_api_key("telegram")
        except Exception:
            return False

    def store_secret(self, plugin_id: str, key: str, value: str):
        """Validate and save a secret in DPAPI; raises ValueError on bad input."""
        if (plugin_id, key) != ("pc_control", "token"):
            raise ValueError("unknown secret")
        from luxai.telegram_control import valid_token
        if not valid_token(value):
            raise ValueError(_tr3("Неверный формат токена. Скопируйте его из @BotFather целиком.",
                                  "Invalid token format. Copy the whole token from @BotFather.",
                                  "Format de token invalid. Copiază tot tokenul de la @BotFather.", self.language))
        from luxai.secure_keys import store_api_key
        store_api_key(value, "telegram")
        self._stop_bot()  # restart with the new token on the next apply

    def _token(self) -> str:
        try:
            from luxai.secure_keys import get_api_key
            return get_api_key("telegram")
        except Exception:
            return ""

    # -- PC Control (Telegram) --
    def _apply_pc_control(self):
        first = not self._pc_applied_once
        self._pc_applied_once = True
        settings = self.settings("pc_control")
        if not self.enabled("pc_control"):
            self._stop_bot()
            self._set_pc_status("stopped", {})
            return
        if first and not settings.get("autostart", True):
            self._set_pc_status("stopped", {"message": _tr3("Не запускается вместе с программой.",
                                                            "Not started with the app.", "Nu pornește odată cu aplicația.",
                                                            self.language)})
            return
        token = self._token()
        if not token:
            self._stop_bot()
            self._set_pc_status("error", {"message": _tr3("Укажите токен бота.", "Enter the bot token.",
                                                          "Introdu tokenul botului.", self.language)})
            return
        if self._bot is not None and self._bot.running and self._bot_token == token:
            return
        self._stop_bot()
        from luxai.telegram_control import TelegramBot
        self._bot_token = token
        self._bot = TelegramBot(token, self._pc_update.emit, self._pc_status.emit)
        self._set_pc_status("connecting", {})
        self._bot.start()

    def _stop_bot(self):
        if self._bot is not None:
            self._bot.stop()
            self._bot = None
            self._bot_token = ""

    def _set_pc_status(self, state, details):
        self.pc_state = (state, dict(details))
        self.pc_status_changed.emit(state, dict(details))

    def _on_pc_status(self, state, details):
        if state == "stopped" and self._bot is not None and self._bot.running:
            return
        self._set_pc_status(state, details)

    def check_pc_connection(self, token: str | None = None):
        """Verify a token (the typed one or the saved one) with getMe."""
        token = (token or "").strip() or self._token()
        if not token:
            self._set_pc_status("error", {"message": _tr3("Укажите токен бота.", "Enter the bot token.",
                                                          "Introdu tokenul botului.", self.language)})
            return
        from luxai.telegram_control import TelegramError, call
        self._set_pc_status("checking", {})

        def work():
            try:
                me = call(token, "getMe") or {}
                self._pc_status.emit("connected" if self._bot is not None and self._bot.running else "checked",
                                     {"name": me.get("first_name", ""), "username": me.get("username", "")})
            except TelegramError as error:
                self._pc_status.emit("error", {"message": str(error)})

        threading.Thread(target=work, daemon=True, name="JarvisTelegramCheck").start()

    def open_bot(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        username = self.pc_state[1].get("username") or (self._bot.me.get("username") if self._bot else "")
        if username:
            QDesktopServices.openUrl(QUrl("https://t.me/" + username))
        else:
            self.check_pc_connection()

    def _registry_entries(self):
        registry = getattr(self.host, "command_registry", None)
        try:
            return registry.entries() if registry is not None else []
        except Exception:
            return []

    def pc_menu_preview(self):
        from luxai.telegram_control import command_folders
        name = self.pc_state[1].get("name") or self.pc_state[1].get("username") or "Jarvis"
        return name, [folder for folder, _ in command_folders(self._registry_entries(), self.language)]

    def _bot_send(self, method, params):
        if self._bot is not None:
            self._bot.send(method, params)

    def _send_menu(self, chat_id, *, edit_message=None, folder=None, text_message=None):
        from luxai import telegram_control as tg
        settings = self.settings("pc_control")
        mode = settings.get("ui_mode", "inline")
        folders = tg.command_folders(self._registry_entries(), self.language)
        if folder is None:
            markup = tg.main_menu(folders, self.language, mode, self._menu_state)
            body = text_message or tg.t("menu", self.language)
        else:
            entries = dict(folders).get(folder, [])
            markup = tg.folder_menu(folder, entries, self.language, mode, self._menu_state)
            body = tg.t("folder", self.language, name=folder) + ("" if entries else "\n" + tg.t("empty", self.language))
        if edit_message and mode == "inline":
            self._bot_send("editMessageText", {"chat_id": chat_id, "message_id": edit_message, "text": body,
                                               "reply_markup": markup})
        else:
            self._bot_send("sendMessage", {"chat_id": chat_id, "text": body, "reply_markup": markup})

    def _on_pc_update(self, update):
        """Handle one Telegram update on the GUI thread."""
        from luxai import telegram_control as tg
        if not self.enabled("pc_control") or self._bot is None:
            return
        settings = self.settings("pc_control")
        language = self.language
        message = update.get("message") or {}
        query = update.get("callback_query") or {}
        sender = (message.get("from") or query.get("from") or {}).get("id")
        chat = (message.get("chat") or (query.get("message") or {}).get("chat") or {}).get("id")
        if sender is None or chat is None:
            return
        owner = str(settings.get("owner_id") or "").strip()
        if query:
            self._bot_send("answerCallbackQuery", {"callback_query_id": query.get("id")})
        if not owner:
            # Setup help only: tell the sender their ID, run nothing.
            if message:
                self._bot_send("sendMessage", {"chat_id": chat, "text": tg.t("your_id", language, id=sender)})
            return
        if str(sender) != owner:
            return  # strangers get no answer at all
        if query:
            resolved = self._menu_state.resolve(query.get("data"))
            message_id = (query.get("message") or {}).get("message_id")
            if resolved is None:
                self._send_menu(chat)
                return
            kind, value = resolved
            if kind == "f":
                self._send_menu(chat, edit_message=message_id, folder=value)
            elif kind in ("m", "r"):
                self._send_menu(chat, edit_message=message_id)
            elif kind == "c":
                self._request_run(chat, value)
            elif kind == "y":
                self._run_remote(chat, value, confirmed=True)
            elif kind == "n":
                self._bot_send("sendMessage", {"chat_id": chat, "text": tg.t("cancelled", language)})
            return
        text_value = str(message.get("text") or "").strip()
        if not text_value:
            return
        lowered = text_value.casefold()
        if lowered in ("/start", "/menu", "/help") or lowered == tg.t("refresh", language).casefold() \
                or lowered == tg.t("back", language).casefold():
            self._send_menu(chat)
            return
        folders = tg.command_folders(self._registry_entries(), language)
        folder_names = {name.casefold(): name for name, _ in folders}
        if lowered in folder_names:
            self._send_menu(chat, folder=folder_names[lowered])
            return
        entry = next((item for _, items in folders for item in items if item["title"].casefold() == lowered), None)
        if entry is None:
            registry = getattr(self.host, "command_registry", None)
            try:
                found = registry.match(text_value, source="text") if registry is not None else None
            except Exception:
                found = None
            if found and found.get("enabled", True) and not found.get("agent"):
                entry = found
        if entry is None:
            if not settings.get("ignore_unknown"):
                self._send_menu(chat, text_message=tg.t("not_found", language))
            return
        self._request_run(chat, entry["id"])

    def _find_entry(self, identifier):
        return next((item for item in self._registry_entries()
                     if item["id"] == identifier and item.get("enabled", True) and not item.get("agent")), None)

    def _request_run(self, chat, identifier):
        from luxai import telegram_control as tg
        entry = self._find_entry(identifier)
        if entry is None:
            self._bot_send("sendMessage", {"chat_id": chat, "text": tg.t("gone", self.language)})
            return
        if entry.get("ask_before_run") and self.settings("pc_control").get("confirm_sensitive", True):
            self._bot_send("sendMessage", {"chat_id": chat, "text": tg.t("confirm", self.language, title=entry["title"]),
                                           "reply_markup": tg.confirm_menu(identifier, self.language, self._menu_state)})
            return
        self._run_remote(chat, identifier, confirmed=False)

    def _run_remote(self, chat, identifier, *, confirmed: bool):
        from luxai import telegram_control as tg
        entry = self._find_entry(identifier)
        if entry is None:
            self._bot_send("sendMessage", {"chat_id": chat, "text": tg.t("gone", self.language)})
            return
        settings = self.settings("pc_control")
        origin = {"telegram_chat": chat, "title": entry["title"],
                  "speak": bool(settings.get("voice_replies", True)), "confirmed": confirmed}
        runner = getattr(self.host, "run_command_entry", None)
        if runner is None:
            return
        accepted = runner(entry, origin=origin)
        if accepted is False:
            self._bot_send("sendMessage", {"chat_id": chat, "text": tg.t("busy", self.language)})
        elif settings.get("notify", True):
            self._bot_send("sendMessage", {"chat_id": chat, "text": tg.t("started", self.language, title=entry["title"])})

    def remote_command_finished(self, origin: dict, result: str, ok: bool):
        """Called by MainWindow when a Telegram-started command finishes."""
        from luxai import telegram_control as tg
        chat = origin.get("telegram_chat")
        if chat is None or not self.settings("pc_control").get("notify", True):
            return
        head = tg.t("done" if ok else "failed", self.language, title=origin.get("title", ""))
        body = (head + ("\n" + result[:3500] if result else "")).strip()
        self._bot_send("sendMessage", {"chat_id": chat, "text": body})

    # -- timers and alarms --
    @property
    def timer_store(self):
        if self._timer_store is None:
            from luxai.command_registry import DATA_DIR
            from luxai.timers import TimerStore
            self._timer_store = TimerStore(getattr(self, "timers_path", None) or DATA_DIR / "timers.json")
        return self._timer_store

    def _apply_timers(self):
        if self.enabled("timers"):
            if not self._timer_tick.isActive():
                self._timer_tick.start()
                QTimer.singleShot(0, self._check_timers)  # ring alarms missed while closed
        else:
            self._timer_tick.stop()

    def _words(self, key, **values):
        words = {
            "timer_set": ("Таймер на {d} запущен.", "Timer for {d} started.", "Cronometru de {d} pornit."),
            "remind_set": ("Напомню через {d}: {label}.", "I'll remind you in {d}: {label}.", "Îți amintesc în {d}: {label}."),
            "alarm_set": ("Будильник поставлен на {t}{day}.", "Alarm set for {t}{day}.", "Alarmă setată la {t}{day}."),
            "tomorrow": (" (завтра)", " (tomorrow)", " (mâine)"),
            "cancel_one": ("Отменил: {what}.", "Cancelled: {what}.", "Anulat: {what}."),
            "cancel_n": ("Отменено: {n}.", "Cancelled: {n}.", "Anulate: {n}."),
            "none": ("Нет активных таймеров и будильников.", "No active timers or alarms.", "Nu există cronometre sau alarme active."),
            "timer_name": ("таймер на {d}", "{d} timer", "cronometru de {d}"),
            "alarm_name": ("будильник на {t}", "alarm at {t}", "alarmă la {t}"),
            "left": ("{what}: осталось {left}", "{what}: {left} left", "{what}: au mai rămas {left}"),
            "ring_timer": ("Время вышло: таймер на {d}.", "Time is up: {d} timer.", "Timpul a expirat: cronometru de {d}."),
            "ring_remind": ("Напоминание: {label}.", "Reminder: {label}.", "Memento: {label}."),
            "ring_alarm": ("Будильник: {t}.", "Alarm: {t}.", "Alarmă: {t}."),
            "title_timer": ("Таймер", "Timer", "Cronometru"),
            "title_alarm": ("Будильник", "Alarm", "Alarmă"),
            "snooze": ("Отложить на {n} мин", "Snooze {n} min", "Amână {n} min"),
            "stop": ("Стоп", "Stop", "Stop"),
            "too_many": ("Слишком много таймеров (максимум 20).", "Too many timers (20 at most).", "Prea multe cronometre (maximum 20)."),
            "disabled": ("Таймеры выключены. Включите «Таймеры и будильники» в Расширениях.",
                         "Timers are off. Turn on “Timers and alarms” in Extensions.",
                         "Cronometrele sunt oprite. Activează „Cronometre și alarme” în Extensii."),
        }[key]
        return _tr3(*words, self.language).format(**values)

    def _describe(self, timer) -> str:
        from luxai.timers import format_duration
        if timer.kind == "alarm":
            return self._words("alarm_name", t=_dt.datetime.fromtimestamp(timer.due).strftime("%H:%M"))
        name = self._words("timer_name", d=format_duration(timer.duration, self.language))
        return f"{name} ({timer.label})" if timer.label else name

    def active_timers(self):
        return list(self.timer_store.items)

    def add_timer(self, kind: str, *, seconds: int = 0, at=None, label: str = "") -> str:
        """Create a timer/alarm and return the confirmation sentence."""
        from luxai.timers import format_duration, new_timer
        now = _dt.datetime.now()
        if kind == "alarm":
            due = at.timestamp()
            timer = new_timer("alarm", due, label)
        else:
            due = now.timestamp() + seconds
            timer = new_timer("timer", due, label, seconds)
        try:
            self.timer_store.add(timer)
        except ValueError:
            return self._words("too_many")
        self._apply_timers()
        self.timers_changed.emit()
        if kind == "alarm":
            day = self._words("tomorrow") if at.date() != now.date() else ""
            return self._words("alarm_set", t=at.strftime("%H:%M"), day=day)
        if label:
            return self._words("remind_set", d=format_duration(seconds, self.language), label=label)
        return self._words("timer_set", d=format_duration(seconds, self.language))

    def cancel_timer(self, identifier: str):
        if self.timer_store.remove(identifier):
            self.timers_changed.emit()

    def handle_timer_request(self, text: str) -> str | None:
        """Reply text when ``text`` is a timer/alarm request, else None."""
        from luxai.timers import format_countdown, parse_request
        request = parse_request(text)
        if request is None:
            return None
        if not self.enabled("timers"):
            return self._words("disabled")
        if request.kind == "timer":
            return self.add_timer("timer", seconds=request.seconds, label=request.label)
        if request.kind == "alarm":
            return self.add_timer("alarm", at=request.at, label=request.label)
        items = self.active_timers()
        if request.kind == "list":
            if not items:
                return self._words("none")
            lines = []
            for item in items[:8]:
                if item.kind == "alarm":
                    lines.append(self._describe(item))
                else:
                    lines.append(self._words("left", what=self._describe(item), left=format_countdown(item.remaining())))
            return "\n".join(lines)
        kind = request.label if request.label in ("timer", "alarm") else ""
        targets = [item for item in items if not kind or item.kind == kind]
        if not targets:
            return self._words("none")
        if request.all:
            for item in targets:
                self.timer_store.remove(item.id)
            self.timers_changed.emit()
            return self._words("cancel_n", n=len(targets))
        first = targets[0]
        self.cancel_timer(first.id)
        return self._words("cancel_one", what=self._describe(first))

    def _check_timers(self):
        for timer in self.timer_store.due():
            self.timer_store.remove(timer.id)
            self.timers_changed.emit()
            self.ring(timer)

    def _ring_text(self, timer) -> str:
        from luxai.timers import format_duration
        if timer.kind == "alarm":
            return self._words("ring_alarm", t=_dt.datetime.fromtimestamp(timer.due).strftime("%H:%M"))
        if timer.label:
            return self._words("ring_remind", label=timer.label)
        return self._words("ring_timer", d=format_duration(timer.duration, self.language))

    def ring(self, timer):
        settings = self.settings("timers")
        message = self._ring_text(timer)
        cfg = getattr(self.host, "cfg", {}) or {}
        self._notify(message, speak=bool(settings.get("speak", True)) and cfg.get("tts_enabled", True))
        dialog = None
        if settings.get("popup", True):
            title = self._words("title_alarm" if timer.kind == "alarm" else "title_timer")
            dialog = RingDialog(title, message, self._words("snooze", n=int(settings.get("snooze", 5))), self._words("stop"))
            dialog.snoozed.connect(lambda t=timer: self.snooze(t))
            dialog.stopped.connect(self.stop_ringing)
            dialog.show_centered()
        self._ringing.append((timer, dialog))
        if settings.get("sound", True):
            self._ring_until = time.monotonic() + int(settings.get("ring_seconds", 60))
            self._ring_beep()
            self._ring_beeper.start()

    def _ring_beep(self):
        if time.monotonic() >= self._ring_until or not self._ringing:
            self._ring_beeper.stop()
            return
        if sys.platform == "win32":
            def pattern():
                import winsound
                for frequency in (988, 1319, 988):
                    try:
                        winsound.Beep(frequency, 120)
                    except RuntimeError:
                        return
            threading.Thread(target=pattern, daemon=True).start()

    def stop_ringing(self):
        self._ring_beeper.stop()
        for _, dialog in self._ringing:
            try:
                if dialog is not None:
                    dialog.close()
            except RuntimeError:
                pass
        self._ringing = []

    def snooze(self, timer):
        from luxai.timers import new_timer
        minutes = int(self.settings("timers").get("snooze", 5))
        self.stop_ringing()
        due = _dt.datetime.now().timestamp() + minutes * 60
        try:
            self.timer_store.add(new_timer(timer.kind, due, timer.label, timer.duration))
        except ValueError:
            return
        self.timers_changed.emit()

    # -- breaks --
    def _tick_breaks(self):
        now = time.monotonic()
        elapsed = min(120.0, now - self._last_tick)
        self._last_tick = now
        settings = self.settings("breaks")
        if idle_seconds() >= int(settings.get("idle_reset", 5)) * 60:
            self._active_seconds = 0.0
            return
        self._active_seconds += elapsed
        if self._active_seconds >= int(settings.get("interval", 50)) * 60:
            self.remind_break()

    def remind_break(self, force: bool = False) -> str:
        settings = self.settings("breaks")
        if not force and settings.get("skip_fullscreen", True) and foreground_is_fullscreen():
            return ""  # try again on the next tick, without resetting
        kinds = [kind for kind in ("eyes", "water", "stretch") if settings.get(kind, True)] or ["eyes"]
        kind = kinds[self._break_index % len(kinds)]
        self._break_index += 1
        self._active_seconds = 0.0
        message = break_message(kind, self.language)
        self._notify(message, speak=bool(settings.get("speak")))
        return message

    # -- clipboard history --
    def _on_clipboard(self):
        clipboard = QApplication.clipboard()
        value = clipboard.text()
        if not value or not value.strip():
            return
        if value == self._ignore_clipboard_text:
            self._ignore_clipboard_text = None
            return
        self.remember_clipboard(value)

    def remember_clipboard(self, value: str):
        if len(value) > 20000:
            value = value[:20000]
        if self.settings("clipboard_history").get("ignore_secrets", True) and looks_secret(value):
            return
        existing = next((item for item in self.clipboard_items if item["text"] == value), None)
        pinned = bool(existing and existing["pinned"])
        if existing:
            self.clipboard_items.remove(existing)
        self.clipboard_items.insert(0, {"text": value, "pinned": pinned})
        self._trim_clipboard()

    def _trim_clipboard(self):
        limit = int(self.settings("clipboard_history").get("limit", 50))
        unpinned = [item for item in self.clipboard_items if not item["pinned"]]
        for item in unpinned[limit:]:
            self.clipboard_items.remove(item)

    def clear_clipboard(self):
        self.clipboard_items = [item for item in self.clipboard_items if item["pinned"]]

    def _popup_texts(self):
        return {
            "search": _tr3("Поиск…", "Search…", "Caută…", self.language),
            "empty_clip": _tr3("История пуста. Скопируйте что-нибудь (Ctrl+C).", "History is empty. Copy something (Ctrl+C).",
                               "Istoricul e gol. Copiază ceva (Ctrl+C).", self.language),
            "empty_snip": _tr3("Нет фрагментов. Добавьте их в настройках «Быстрых вставок».",
                               "No snippets. Add them in the Quick inserts settings.",
                               "Nu există fragmente. Adaugă-le în setările Inserții rapide.", self.language),
            "pin": _tr3("Закрепить / открепить", "Pin / unpin", "Fixează / anulează", self.language),
            "clip": _tr3("История буфера обмена", "Clipboard history", "Istoric clipboard", self.language),
            "snip": _tr3("Быстрые вставки", "Quick inserts", "Inserții rapide", self.language),
        }

    def open_clipboard_history(self):
        words = self._popup_texts()
        target = _foreground_window()
        ordered = [item for item in self.clipboard_items if item["pinned"]] + \
                  [item for item in self.clipboard_items if not item["pinned"]]
        items = [(" ".join(item["text"].split())[:120], item["text"], item["pinned"]) for item in ordered]
        popup = PickerPopup(words["clip"], items, placeholder=words["search"], empty=words["empty_clip"], pin_label=words["pin"])
        paste = bool(self.settings("clipboard_history").get("paste_on_pick", True))
        popup.picked.connect(lambda value: self._insert_text(value, target, paste=paste, restore=False))
        popup.pin_toggled.connect(self._toggle_pin)
        popup.show_at_cursor()
        self._popup = popup
        return popup

    def _toggle_pin(self, value):
        for item in self.clipboard_items:
            if item["text"] == value:
                item["pinned"] = not item["pinned"]
                break

    def open_snippets(self, paste: bool = True):
        words = self._popup_texts()
        target = _foreground_window()
        snippets = parse_snippets(self.settings("quick_inserts").get("snippets", ""))
        items = [(f"{name} — {' '.join(body.split())[:80]}", body, False) for name, body in snippets]
        popup = PickerPopup(words["snip"], items, placeholder=words["search"], empty=words["empty_snip"])
        popup.picked.connect(lambda body: self._insert_text(expand_snippet(body), target, paste=paste, restore=True))
        popup.show_at_cursor()
        self._popup = popup
        return popup

    def _insert_text(self, value: str, target_hwnd: int, *, paste: bool, restore: bool):
        clipboard = QApplication.clipboard()
        previous = clipboard.text() if restore else None
        self._ignore_clipboard_text = value
        clipboard.setText(value)
        if not paste or not target_hwnd:
            return

        def do_paste():
            _set_foreground(target_hwnd)
            QTimer.singleShot(120, finish)

        def finish():
            try:
                _send_paste()
            except Exception as error:
                self.notice.emit(str(error))
            if restore and previous is not None:
                def put_back():
                    self._ignore_clipboard_text = previous
                    QApplication.clipboard().setText(previous)
                QTimer.singleShot(700, put_back)

        QTimer.singleShot(80, do_paste)

    # -- read aloud --
    def read_selection(self):
        settings = self.settings("read_aloud")
        if self._reading and settings.get("second_press_stops", True):
            self._reading = False
            if hasattr(self.host, "stop_speaking"):
                self.host.stop_speaking()
            return
        from luxai.selection import copy_selected_text, finish_selected_copy
        from luxai.screen_interact import _foreground_hwnd
        clipboard = QApplication.clipboard()
        hwnd = _foreground_hwnd()
        try:
            _, before, saved = copy_selected_text(clipboard, hwnd)
        except Exception as error:
            self._notify(str(error))
            return

        def finish():
            try:
                selected = finish_selected_copy(clipboard, hwnd, before, saved)
            except Exception as error:
                self._notify(str(error))
                return
            limit = int(settings.get("max_chars", 4000))
            selected = selected.split("\n[Выделение сокращено", 1)[0][:limit]
            self._reading = True
            if hasattr(self.host, "_queue_speech"):
                from luxai.response_language import reply_language
                cfg = getattr(self.host, "cfg", {}) or {}
                self.host._queue_speech(selected, reply_language(cfg, selected))
            QTimer.singleShot(max(4000, len(selected) * 70), lambda: setattr(self, "_reading", False))

        QTimer.singleShot(260, finish)

    # -- screenshots --
    def take_screenshot(self, window: bool = False) -> Path | None:
        settings = self.settings("screenshots")
        region = _foreground_rect() if window else None
        try:
            data = capture_png(region)
        except Exception as error:
            self._notify(_tr3("Не удалось сделать снимок: ", "Screenshot failed: ", "Captura a eșuat: ", self.language) + str(error))
            return None
        saved = None
        if settings.get("to_clipboard", True):
            image = QImage.fromData(data, "PNG")
            if not image.isNull():
                self._ignore_clipboard_text = None
                QApplication.clipboard().setImage(image)
        if settings.get("to_file", True):
            try:
                folder = screenshots_folder(settings.get("folder", ""))
                folder.mkdir(parents=True, exist_ok=True)
                saved = unique_path(folder / _dt.datetime.now().strftime("Screenshot %Y-%m-%d %H-%M-%S.png"))
                saved.write_bytes(data)
            except OSError as error:
                self._notify(str(error))
                return None
        where = str(saved) if saved else _tr3("буфер обмена", "clipboard", "clipboard", self.language)
        self._notify(_tr3("Снимок сохранён: ", "Screenshot saved: ", "Captură salvată: ", self.language) + where)
        return saved

    def open_screenshots_folder(self):
        folder = screenshots_folder(self.settings("screenshots").get("folder", ""))
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(folder))  # noqa: S606 - opens our own output folder

    # -- converter --
    def convert_dialog(self, parent=None):
        settings = self.settings("converter")
        files, _ = QFileDialog.getOpenFileNames(
            parent, _tr3("Выберите картинки", "Choose images", "Alege imagini", self.language), str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff *.ico)")
        if not files:
            return []
        made, errors = [], []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for name in files[:200]:
                try:
                    made.append(convert_image(Path(name), settings.get("format", "png"),
                                              quality=int(settings.get("quality", 85)),
                                              max_side=int(settings.get("max_side", 0))))
                except Exception as error:
                    errors.append(f"{Path(name).name}: {error}")
        finally:
            QApplication.restoreOverrideCursor()
        message = _tr3(f"Готово: {len(made)} файл(ов) рядом с оригиналами.",
                       f"Done: {len(made)} file(s) next to the originals.",
                       f"Gata: {len(made)} fișier(e) lângă originale.", self.language)
        if errors:
            message += "\n\n" + "\n".join(errors[:10])
        QMessageBox.information(parent, _tr3("Конвертер", "Converter", "Convertor", self.language), message)
        return made

    # -- downloads cleanup --
    def _cleanup_plan(self):
        settings = self.settings("downloads_cleanup")
        configured = settings.get("folder", "")
        folder = Path(os.path.expandvars(os.path.expanduser(configured))) if configured else downloads_folder()
        return folder, plan_cleanup(folder, min_age_days=int(settings.get("min_age", 1)),
                                    installer_trash_days=int(settings.get("old_installers", 0)),
                                    language=self.language)

    def cleanup_dialog(self, parent=None, execute: bool = False):
        folder, steps = self._cleanup_plan()
        title = _tr3("Уборка загрузок", "Downloads cleanup", "Curățenie în Descărcări", self.language)
        if not steps:
            QMessageBox.information(parent, title, _tr3(f"В папке {folder} нечего убирать.",
                                                        f"Nothing to clean in {folder}.",
                                                        f"Nimic de curățat în {folder}.", self.language))
            return (0, 0, [])
        lines = []
        for step in steps[:25]:
            where = _tr3("→ Корзина", "→ Recycle Bin", "→ Coș", self.language) if step.target is None \
                else f"→ {step.target.parent.name}"
            lines.append(f"{step.source.name}  {where}")
        if len(steps) > 25:
            lines.append(f"… +{len(steps) - 25}")
        summary = "\n".join(lines)
        if not execute:
            QMessageBox.information(parent, title, summary)
            return (0, 0, [])
        trashed = sum(1 for step in steps if step.target is None)
        question = _tr3(f"Переместить {len(steps) - trashed} файл(ов) по папкам" + (f" и {trashed} — в Корзину" if trashed else "") + "?",
                        f"Move {len(steps) - trashed} file(s) into folders" + (f" and {trashed} to the Recycle Bin" if trashed else "") + "?",
                        f"Mut {len(steps) - trashed} fișier(e) în dosare" + (f" și {trashed} în Coș" if trashed else "") + "?",
                        self.language)
        if QMessageBox.question(parent, title, question + "\n\n" + summary) != QMessageBox.StandardButton.Yes:
            return (0, 0, [])
        result = run_cleanup(steps)
        self._report_cleanup(result, parent)
        return result

    def _report_cleanup(self, result, parent=None):
        moved, trashed, errors = result
        message = _tr3(f"Разложено: {moved}, в Корзину: {trashed}.", f"Sorted: {moved}, to Recycle Bin: {trashed}.",
                       f"Sortate: {moved}, în Coș: {trashed}.", self.language)
        if errors:
            message += "\n" + "\n".join(errors[:5])
        if parent is not None:
            QMessageBox.information(parent, _tr3("Уборка загрузок", "Downloads cleanup", "Curățenie în Descărcări", self.language), message)
        else:
            self._notify(message)

    def _auto_cleanup(self):
        if not (self.enabled("downloads_cleanup") and self.settings("downloads_cleanup").get("auto")):
            return
        cfg = getattr(self.host, "cfg", None)
        today = _dt.date.today().isoformat()
        meta = cfg.setdefault("extensions_meta", {}) if isinstance(cfg, dict) else {}
        if meta.get("downloads_last_run") == today:
            return
        _, steps = self._cleanup_plan()
        meta["downloads_last_run"] = today
        if hasattr(self.host, "save_extensions_meta"):
            self.host.save_extensions_meta()
        if steps:
            moved, trashed, errors = run_cleanup(steps)
            if moved or trashed:
                self._report_cleanup((moved, trashed, errors))


def _foreground_window() -> int:
    if sys.platform != "win32":
        return 0
    hwnd = int(ctypes.windll.user32.GetForegroundWindow() or 0)
    try:
        from ctypes import wintypes
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            return 0  # never paste into Jarvis' own window
    except OSError:
        pass
    return hwnd


__all__ = [
    "CleanupStep", "ExtensionsRuntime", "PickerPopup", "plan_cleanup", "run_cleanup", "convert_image",
    "looks_secret", "expand_snippet", "break_message", "downloads_folder", "unique_path", "text",
]
