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


def _tr3(ru, en, ro, language):
    return {"ru": ru, "en": en, "ro": ro}.get(language, ru)


class ExtensionsRuntime(QObject):
    """Starts/stops ready plugins. ``host`` is the MainWindow-like object.

    The host may provide: ``cfg`` (dict), ``tray_icon``, ``_queue_speech(text, lang)``,
    ``stop_speaking()``. Missing members are tolerated (tests use a stub).
    """
    hotkey = Signal(str)
    notice = Signal(str)

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
        if plugin_id == "clipboard_history":
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
