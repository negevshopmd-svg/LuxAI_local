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


BREAK_KINDS = ("eyes", "stretch", "water")
BREAK_IDLE_RESET = 5 * 60   # away this long = a break, counting starts over
BREAK_ACTIVE_IDLE = 60      # no input for a minute: time stops counting
BREAK_SNOOZE = 10 * 60
BREAK_RESUME_DELAY = 30     # a delayed reminder comes 30 s after a game/call ends


def break_title(kind: str, language: str) -> str:
    titles = {"eyes": ("Глаза — правило 20-20-20", "Eyes — the 20-20-20 rule", "Ochi — regula 20-20-20"),
              "stretch": ("Разминка", "Stretch", "Întinderi"), "water": ("Вода", "Water", "Apă")}[kind]
    return dict(zip(("ru", "en", "ro"), titles)).get(language, titles[0])


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


def _set_foreground(hwnd: int) -> bool:
    """Bring ``hwnd`` forward; True only when it exists and really is the foreground window now."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd):
            return False
        user32.SetForegroundWindow(hwnd)
        for _ in range(10):
            if int(user32.GetForegroundWindow() or 0) == int(hwnd):
                return True
            time.sleep(0.03)
    except OSError:
        return False
    return False


def _send_paste() -> None:
    from luxai.keys import press, release_modifiers
    release_modifiers()
    press("ctrl", "v", interval=0.05)


def screenshots_folder(configured: str) -> Path:
    if configured:
        return Path(os.path.expandvars(os.path.expanduser(configured)))
    return Path.home() / "Pictures" / "Jarvis Screenshots"


def capture_raw(region=None) -> tuple[bytes, int, int]:
    """(BGRA pixels, width, height) of the whole virtual screen or a (left, top, w, h) region."""
    import mss
    with mss.mss() as grabber:
        monitor = grabber.monitors[0] if region is None else {
            "left": region[0], "top": region[1], "width": region[2], "height": region[3]}
        shot = grabber.grab(monitor)
        return bytes(shot.bgra), shot.width, shot.height


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


class BreakCard(QDialog):
    """Reminder card in the bottom-right corner: Done / Later / Skip.

    It never takes the keyboard focus, so typing and games are not
    interrupted; an unanswered card counts as skipped after 3 minutes.
    """
    answered = Signal(str)  # done | later | skip

    def __init__(self, title: str, body: str, labels):
        super().__init__(None)
        self.setObjectName("BreakCard")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setProperty("i18n_skip", True)
        self.setStyleSheet("QDialog#BreakCard{border:1px solid #3aa05a;border-radius:14px;}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setStyleSheet("font-size:15px;font-weight:700;")
        layout.addWidget(heading)
        text_label = QLabel(body)
        text_label.setWordWrap(True)
        layout.addWidget(text_label)
        row = QHBoxLayout()
        for answer, label in zip(("done", "later", "skip"), labels):
            button = QPushButton(label)
            if answer == "done":
                button.setObjectName("Primary")
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda checked=False, a=answer: self.answered.emit(a))
            row.addWidget(button)
        layout.addLayout(row)
        self.setFixedWidth(340)
        self._expire = QTimer(self)
        self._expire.setSingleShot(True)
        self._expire.timeout.connect(lambda: self.answered.emit("skip"))
        self._expire.start(3 * 60 * 1000)

    def show_in_corner(self):
        self.adjustSize()
        area = QGuiApplication.primaryScreen().availableGeometry()
        self.move(area.right() - self.width() - 18, area.bottom() - self.height() - 18)
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
        snooze.clicked.connect(self.snoozed.emit)  # closed by the runtime once the snooze is saved
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


class AsyncReply(str):
    """Returned by a chat handler that answers later through ``ExtensionsRuntime.chat_reply``."""


class ExtensionsRuntime(QObject):
    """Starts/stops ready plugins. ``host`` is the MainWindow-like object.

    The host may provide: ``cfg`` (dict), ``tray_icon``, ``_queue_speech(text, lang)``,
    ``stop_speaking()``. Missing members are tolerated (tests use a stub).
    """
    hotkey = Signal(str)
    notice = Signal(str)
    chat_reply = Signal(str, str)  # reply, voice language ("" = Jarvis' own) — answers that come later
    dictation_result = Signal(str, str, bool)  # text, error, test
    dictation_done = Signal(str)  # last dictated text, for the settings page
    _read_chunk = Signal(str, str, int)  # text, language, reading generation
    _read_notice = Signal(str)
    _notif_ready = Signal(str)  # a (translated) notification sentence
    pc_status_changed = Signal(str, dict)  # state, details (bot name, error)
    timers_changed = Signal()
    notification_apps_changed = Signal()
    convert_progress = Signal(float)
    convert_done = Signal(list, list)  # results, errors
    _pc_update = Signal(dict)
    _pc_status = Signal(str, dict)

    breaks_changed = Signal()
    clipboard_changed = Signal()
    captions_changed = Signal(bool)
    _cap_partial = Signal(str)
    _cap_final = Signal(str)
    _cap_translated = Signal(str, str)
    _cap_partial_translated = Signal(str, str, int)  # draft text, its translation, phrase number
    _cap_corrected = Signal(str, str)  # hybrid: draft line, precise text
    _film_report = Signal(object)  # a player report from the Chrome extension (film captions in advance)
    _film_error = Signal(str)
    _extension_hello = Signal(object)  # the browser extension says it is installed
    _cap_error = Signal(str)
    _clip_ai_ready = Signal(str, str)  # mode, result ("" = failed)
    _clip_image_ready = Signal(bytes, bytes, int, int, str)  # png, thumb, width, height, app
    _clip_native_ready = Signal(object)  # what the worker read from the clipboard (audit 2 #14)
    _auto_cleanup_done = Signal(object, str)  # (moved, trashed, errors), day (audit 2 #19)
    _screenshot_done = Signal(str, bool, str)  # saved path ("" = not saved), copied, error
    _notif_items = Signal(object, object)  # new notifications, the watcher that read them (audit 2 #27)
    _clip_history_loaded = Signal(object, int)  # loaded ClipboardHistory, load generation (audit 2 #17)

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.state: dict = {}
        self.errors: dict[str, str] = {}
        from luxai.clipboard_store import ClipboardHistory
        self.clip_history = ClipboardHistory()
        self._clip_loaded = False
        self._clip_save_timer = QTimer(self)
        self._clip_save_timer.setSingleShot(True)
        self._clip_save_timer.setInterval(1500)
        self._clip_save_timer.timeout.connect(self._save_clip_history)
        self._clip_read_timer = QTimer(self)
        self._clip_read_timer.setSingleShot(True)
        self._clip_read_timer.setInterval(60)
        self._clip_read_timer.timeout.connect(self._read_clipboard)
        self._clip_image_ready.connect(self._on_clip_image_ready)
        self._clip_native_ready.connect(self._on_clip_native)
        self._auto_cleanup_done.connect(self._on_auto_cleanup_done)
        self._screenshot_done.connect(self._on_screenshot_done)
        self._auto_cleanup_running = False
        self._clip_history_loaded.connect(self._on_clip_history_loaded)
        self._clip_save_lock = threading.Lock()
        # One worker each instead of a thread per event (audit 2 #14-#17): reads, picture encoding and
        # saves run in order, a waiting job is replaced by a newer one, and close waits for the last save.
        from luxai.background import LatestWorker, SerialQueue
        # Audit 2 #23: chat and notification translations share ONE worker with an explicit queue (the
        # offline model translates one text at a time anyway), so bursts never pile up threads and the
        # answers come back in the order they were asked.
        self._translations = SerialQueue("JarvisTranslate", limit=32)
        self._clip_reader = LatestWorker("JarvisClipboardRead")
        self._clip_images = LatestWorker("JarvisClipboardImage")
        self._clip_saver = LatestWorker("JarvisClipboardSave")
        self._clip_load_generation = 0
        self._stopping = False
        self._clip_ai_ready.connect(self._on_clip_ai_ready)
        self.captions_visible = False
        self._captions_bar = None
        self._captions_capture = None
        self._captions_engine = None
        self._captions_config = None
        self._captions_autostart_done = False
        self._avatar_window = None
        self._avatar_meter = None
        self._avatar_audio_key = None
        self._avatar_first_apply = True
        self._avatar_session_hidden = False
        self._avatar_error_until = 0.0
        self._avatar_ticks = 0
        self._avatar_full_seconds = 0
        self._avatar_timer = QTimer(self)
        self._avatar_timer.setInterval(100)
        self._avatar_timer.timeout.connect(self._tick_avatar)
        self._cap_partial.connect(self._on_cap_partial)
        self._cap_partial_translated.connect(self._on_cap_partial_translated)
        self._cap_corrected.connect(self._on_cap_corrected)
        self._film_report.connect(self._on_film_report)
        self._film_error.connect(self._on_film_error)
        self._extension_hello.connect(self._on_extension_hello)
        self._extension_dialog = None
        self._extension_offered = False  # asked once per session at most
        self._film_bridge = None
        self._film = None          # (key, clock, timeline, transcriber) of the film being prepared
        self._film_active = False  # prepared lines are on the bar now
        self._film_shown = None
        self._film_timer = QTimer(self)
        self._film_timer.setInterval(80)  # words appear in step with the film
        self._film_timer.timeout.connect(self._film_tick)
        self._cap_phrase = 0  # increases with every finished phrase: late draft translations are dropped
        self._cap_final.connect(self._on_cap_final)
        self._cap_translated.connect(self._on_cap_translated)
        self._cap_error.connect(self._on_cap_error)
        self._ignore_clipboard_text = None
        self._listener = None
        self._reading = False
        self._active_seconds = 0.0
        self._break_index = 0
        self._last_tick = time.monotonic()
        self.hotkey.connect(self._on_hotkey)
        self._break_timer = QTimer(self)
        self._break_timer.setInterval(5_000)
        self._break_timer.timeout.connect(self._tick_breaks)
        self.break_active = {kind: 0.0 for kind in BREAK_KINDS}
        self._break_due: list[str] = []
        self._break_card = None
        self._break_card_kind = ""
        self._break_silenced = False
        self._break_resume_at = 0.0
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
        self._reading_generation = 0
        self._read_chunk.connect(self._on_read_chunk)
        self._read_notice.connect(self._notify)
        self._notif_ready.connect(self._accept_notification)
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
        self._bot_generation = 0  # audit 2 #40: signals of an old bot are ignored
        self.pc_state = ("stopped", {})
        from luxai.telegram_control import MenuState
        self._menu_state = MenuState()
        self._pc_update.connect(self._on_pc_update)
        self._timer_store = None
        self._timer_tick = QTimer(self)
        self._timer_tick.setInterval(1000)
        self._timer_tick.timeout.connect(self._check_timers)
        self._ringing: list = []  # (timer, dialog)
        from collections import deque
        self._notif_watcher = None
        self._notif_timer = QTimer(self)
        self._notif_timer.setInterval(2000)
        self._notif_timer.timeout.connect(self._poll_notifications_async)
        self._notif_items.connect(self._on_notif_items)
        from luxai.background import LatestWorker as _LatestWorker
        self._notif_reader = _LatestWorker("JarvisNotificationRead")
        self.notification_memory = deque(maxlen=20)  # composed texts, memory only
        self.missed_notifications = deque(maxlen=20)
        self._notif_pending = []
        self.dnd_until = 0.0
        self.seen_notification_apps: set[str] = set()
        self._converting = False
        self._convert_overlay = None
        self.convert_progress.connect(self._on_convert_progress)
        self.convert_done.connect(self._on_convert_done)
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
                self.break_active = {kind: 0.0 for kind in BREAK_KINDS}
                self._last_tick = time.monotonic()
                self._break_timer.start()
        else:
            self._break_timer.stop()
            self._close_break_card()
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
            if not self._clip_loaded:
                self._clip_loaded = True
                if self.settings("clipboard_history").get("persist", True):
                    self._load_clip_history_async()
            self._trim_clipboard()
        if self.enabled("smart_dictation") and self.settings("smart_dictation").get("trigger") == "right_ctrl_double" \
                and sys.platform == "win32":
            if not self._tap_timer.isActive():
                self._tap_timer.start()
        else:
            self._tap_timer.stop()
        if not self.enabled("smart_dictation") and (self.dictating or getattr(self, "_dictation_busy", False)):
            # Also while the recording is being TRANSCRIBED (audit 2 #22): the result is invalidated.
            self.cancel_dictation()
        self._apply_pc_control()
        self._apply_captions()
        self._apply_avatar()
        self._apply_timers()
        self._apply_notifications()
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

    # -- live captions --
    def _captions_settings_key(self):
        settings = self.settings("live_captions")
        return (settings.get("language"), settings.get("source"), settings.get("quality"))

    def _migrate_caption_quality(self):
        """0.4.2y: «Fast and accurate» was the saved default for everyone; it becomes «Hybrid» once.
        A choice the user makes afterwards is never changed again."""
        cfg = getattr(self.host, "cfg", None)
        if not isinstance(cfg, dict):
            return
        meta = cfg.setdefault("extensions_meta", {})
        if meta.get("captions_hybrid_migrated"):
            return
        if getattr(self.host, "extensions_page", None) is None:
            return  # the page saves the change; without it, try again at the next start
        # Marked in memory: it is written with the next save of the settings (no config write at start-up
        # unless the setting really changes), so a «balanced» chosen later is kept.
        meta["captions_hybrid_migrated"] = True
        if self.settings("live_captions").get("quality") == "balanced" and hasattr(self.host, "update_extension_setting"):
            self.host.update_extension_setting("live_captions", "quality", "hybrid")

    def _apply_captions(self):
        if not getattr(self, "_caption_quality_checked", False):
            self._caption_quality_checked = True
            QTimer.singleShot(0, self._migrate_caption_quality)
        if not self.enabled("live_captions"):
            if self.captions_visible:
                self.hide_captions()
            if self._film_bridge is not None:
                self._stop_film()
            return
        if self.settings("live_captions").get("browser_films", True):
            self._start_film_bridge()
        elif self._film_bridge is not None:
            self._stop_film()
        if not self._captions_autostart_done:
            self._captions_autostart_done = True
            if self.settings("live_captions").get("show_on_start") and not self.captions_visible:
                QTimer.singleShot(1500, self.show_captions)
                return
        if self.captions_visible:
            self._configure_bar()
            if self._captions_config != self._captions_settings_key():
                self._start_caption_audio()  # language or source changed
            if self.settings("live_captions").get("browser_films", True):
                self._start_film_bridge()
            elif self._film_bridge is not None:
                self._stop_film()

    def _configure_bar(self):
        settings = self.settings("live_captions")
        if self._captions_bar is None:
            return
        try:
            lines = int(settings.get("lines", "2"))
        except (TypeError, ValueError):
            lines = 2
        self._captions_bar.configure(
            font_size=settings.get("font_size", 26), opacity=int(settings.get("opacity", 72)) / 100, lines=lines,
            show_original=bool(settings.get("show_original", True)) or not settings.get("translate"))

    def _captions_words(self, key: str, **values) -> str:
        words = {
            "listening": ("Слушаю звук компьютера…", "Listening to the PC sound…", "Ascult sunetul PC-ului…"),
            "listening_app": ("Слушаю {app}…", "Listening to {app}…", "Ascult {app}…"),
            "no_app": ("{app} сейчас не запущен — слушаю весь звук.", "{app} is not running — listening to all sound.",
                       "{app} nu rulează — ascult tot sunetul."),
            "error": ("Субтитры: {error}", "Captions: {error}", "Subtitrări: {error}"),
            "shown": ("Показал субтитры.", "Captions are on.", "Am afișat subtitrările."),
            "hidden": ("Скрыл субтитры.", "Captions are off.", "Am ascuns subtitrările."),
        }[key]
        index = {"ru": 0, "en": 1, "ro": 2}.get(self.language, 0)
        return words[index].format(**values)

    def show_captions(self):
        from luxai.live_captions import CaptionBar
        if not self.enabled("live_captions"):
            # «Показать субтитры» turns the plugin on, as in Luxify.
            if hasattr(self.host, "set_extension_enabled"):
                self.host.set_extension_enabled("live_captions", True)
            else:
                self.state.setdefault("live_captions", {"enabled": False, "settings": {}})["enabled"] = True
        if self._captions_bar is None:
            bar = CaptionBar()
            bar.closed_by_user.connect(self.hide_captions)
            bar.moved.connect(self._save_captions_position)
            self._captions_bar = bar
        self._configure_bar()
        cfg = getattr(self.host, "cfg", None)
        saved = (cfg.get("extensions_meta", {}) if isinstance(cfg, dict) else {}).get("captions_position")
        self._captions_bar.place(saved)
        self._captions_bar.show()
        self.captions_visible = True
        self._start_caption_audio()
        self._start_film_bridge()
        QTimer.singleShot(1500, self._offer_browser_extension)
        if self.settings("live_captions").get("translate"):
            from luxai import offline_translate
            offline_translate.download_in_background()  # once, ≈640 MB; the original until then
            if offline_translate.installed():  # load it now so the first phrase is not late
                threading.Thread(target=offline_translate.get, daemon=True, name="JarvisTranslatorLoad").start()
        self.captions_changed.emit(True)
        return self._captions_words("shown")

    def hide_captions(self):
        self._stop_film(keep_bridge=self.enabled("live_captions"))
        self._stop_caption_audio()
        bar, self._captions_bar = self._captions_bar, None
        if bar is not None:
            try:
                bar.close()
                bar.deleteLater()
            except RuntimeError:
                pass
        was = self.captions_visible
        self.captions_visible = False
        if was:
            self.captions_changed.emit(False)
        return self._captions_words("hidden")

    def toggle_captions(self):
        return self.hide_captions() if self.captions_visible else self.show_captions()

    def reset_captions_position(self):
        cfg = getattr(self.host, "cfg", None)
        if isinstance(cfg, dict):
            cfg.setdefault("extensions_meta", {}).pop("captions_position", None)
            if hasattr(self.host, "save_extensions_meta"):
                self.host.save_extensions_meta()
        if self._captions_bar is not None:
            self._captions_bar.place(None)

    def _save_captions_position(self, x: int, y: int):
        cfg = getattr(self.host, "cfg", None)
        if isinstance(cfg, dict):
            cfg.setdefault("extensions_meta", {})["captions_position"] = [int(x), int(y)]
            if hasattr(self.host, "save_extensions_meta"):
                self.host.save_extensions_meta()

    def _caption_language(self):
        """None = detect what is spoken (a video's language is not the voice-command one)."""
        language = self.settings("live_captions").get("language", "auto")
        return language if language in ("ru", "en", "ro") else None

    def _captions_translate_only(self) -> bool:
        settings = self.settings("live_captions")
        planner = getattr(self.host, "online_planner", None)
        return bool(settings.get("translate")) and not settings.get("show_original", False) \
            and planner is not None and planner.enabled()

    def _start_caption_audio(self):
        from luxai import dictation
        from luxai.live_captions import CaptionEngine
        from luxai.loopback_audio import LoopbackCapture, app_pid
        self._stop_caption_audio()
        settings = self.settings("live_captions")
        self._captions_config = self._captions_settings_key()
        cfg = dict(getattr(self.host, "cfg", {}) or {})
        provider = getattr(self.host, "dictation_model", None)

        quality = settings.get("quality", "hybrid")

        language = self._caption_language()

        def model():
            from luxai.live_captions import QUALITY_MODELS, caption_model, hybrid_draft_model
            if quality == "hybrid":
                return caption_model(hybrid_draft_model(language), threads=6)
            if quality in QUALITY_MODELS:
                return caption_model(QUALITY_MODELS[quality])
            loaded = provider() if callable(provider) else None
            return loaded or dictation.load_model(cfg.get("whisper_model_path") or cfg.get("whisper_model") or "small")

        def precise():
            from luxai.live_captions import caption_model, hybrid_precise_model
            return caption_model(hybrid_precise_model(language), threads=8)

        hybrid = quality == "hybrid"
        engine = CaptionEngine(model, language, self._cap_partial.emit, self._cap_final.emit,
                               on_error=self._cap_error.emit, precise_provider=precise if hybrid else None,
                               on_correct=self._cap_corrected.emit if hybrid else None)
        self._cap_phrase += 1
        source = str(settings.get("source") or "")
        pid = app_pid(source) if source else 0
        if self._captions_bar is not None:
            app = source.removesuffix(".exe")
            if source and not pid:
                self._captions_bar.placeholder = self._captions_words("no_app", app=app)
            else:
                self._captions_bar.placeholder = self._captions_words("listening_app" if pid else "listening", app=app)
            self._captions_bar.render()
        from luxai.voices import barge_in_ready as jarvis_speaking
        import numpy as _np
        mute = {"until": 0.0}

        def feed(chunk):
            # Jarvis's own voice never gets into the captions (plus a short tail).
            if jarvis_speaking.is_set():
                mute["until"] = time.monotonic() + 0.5
            if time.monotonic() < mute["until"]:
                chunk = _np.zeros_like(chunk)
            engine.feed(chunk)

        capture = LoopbackCapture(feed, app_pid=pid, on_error=self._cap_error.emit)
        self._captions_engine = engine.start()
        self._captions_capture = capture.start()

    # -- film captions in advance (Chrome extension) --
    def _start_film_bridge(self):
        if not self.settings("live_captions").get("browser_films", True):
            return
        if self._film_bridge is None:
            from luxai.film_captions import BridgeServer
            bridge = BridgeServer(self._film_report.emit, on_hello=self._extension_hello.emit)
            if bridge.start():
                self._film_bridge = bridge
        if self._film_bridge is not None and self.captions_visible and not self._film_timer.isActive():
            self._film_timer.start()

    def _stop_film(self, keep_bridge: bool = False):
        """Stop preparing (and showing) film lines; ``keep_bridge`` keeps listening for the extension."""
        self._film_timer.stop()
        if not keep_bridge:
            bridge, self._film_bridge = self._film_bridge, None
            if bridge is not None:
                bridge.stop()
        film, self._film = self._film, None
        if film is not None:
            film[3].stop()
        self._set_film_active(False)

    # -- the browser extension: installed? --
    def extension_installed(self) -> bool:
        meta = (getattr(self.host, "cfg", {}) or {}).get("extensions_meta", {})
        return bool(isinstance(meta, dict) and meta.get("browser_extension_seen"))

    def _remember_extension(self, info: dict):
        cfg = getattr(self.host, "cfg", None)
        if not isinstance(cfg, dict):
            return
        meta = cfg.setdefault("extensions_meta", {})
        value = {"version": str(info.get("version", ""))[:16], "browser": info.get("browser", "chrome")}
        if meta.get("browser_extension_seen") != value:
            meta["browser_extension_seen"] = value
            if hasattr(self.host, "save_extensions_meta"):
                self.host.save_extensions_meta()

    def _on_extension_hello(self, info):
        info = info if isinstance(info, dict) else {}
        self._remember_extension(info)
        dialog = self._extension_dialog
        if dialog is not None:
            try:
                dialog.connected(info)
            except RuntimeError:
                self._extension_dialog = None

    def _offer_browser_extension(self):
        """At captions start: offer the extension once (Yes / Later / Never) when it is not installed yet."""
        from luxai.ui_browser_extension import find_browser
        cfg = getattr(self.host, "cfg", None)
        meta = cfg.get("extensions_meta", {}) if isinstance(cfg, dict) else {}
        if (self._extension_offered or self.extension_installed() or not self.captions_visible
                or not self.settings("live_captions").get("browser_films", True)
                or (isinstance(meta, dict) and meta.get("browser_extension_never")) or find_browser() is None):
            return
        self._extension_offered = True
        box = QMessageBox()
        box.setWindowTitle("Jarvis")
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.setText(_tr3("Установить расширение Jarvis для Chrome?",
                         "Install the Jarvis extension for Chrome?",
                         "Instalez extensia Jarvis pentru Chrome?", self.language))
        box.setInformativeText(_tr3(
            "С ним субтитры фильмов в браузере готовятся заранее: каждое слово появляется ровно тогда, когда его "
            "произносят, с готовым переводом. Без него субтитры работают как сейчас (с задержкой ~1–2 с).",
            "With it, captions of films in the browser are prepared in advance: every word appears exactly when it "
            "is spoken, already translated. Without it, captions work as now (~1-2 s behind).",
            "Cu ea, subtitrările filmelor din browser se pregătesc din timp: fiecare cuvânt apare exact când e rostit, "
            "deja tradus. Fără ea, subtitrările merg ca acum (cu ~1–2 s întârziere).", self.language))
        yes = box.addButton(_tr3("Да, установить", "Yes, install", "Da, instalează", self.language),
                            QMessageBox.ButtonRole.AcceptRole)
        box.addButton(_tr3("Позже", "Later", "Mai târziu", self.language), QMessageBox.ButtonRole.RejectRole)
        never = box.addButton(_tr3("Больше не спрашивать", "Don't ask again", "Nu mai întreba", self.language),
                              QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(yes)
        box.exec()
        if box.clickedButton() is yes:
            self.open_browser_extension()
        elif box.clickedButton() is never and isinstance(cfg, dict):
            cfg.setdefault("extensions_meta", {})["browser_extension_never"] = True
            if hasattr(self.host, "save_extensions_meta"):
                self.host.save_extensions_meta()

    def _on_film_report(self, report):
        """A player report (Qt thread). A new film (other tab, page or length) starts its own preparation."""
        if not self.extension_installed():
            self._on_extension_hello({"version": "", "browser": "chrome"})  # reports = it is installed
        if not self.captions_visible or self._film_bridge is None:
            return
        candidates = list(report.get("media") or [])
        if not candidates:
            return
        key = (report["tab"], report["page"], round(report["duration"]))
        film = self._film
        if film is None or film[0] != key or film[3].stopped:
            if film is not None:
                film[3].stop()
            from luxai.film_captions import CueTimeline, FilmTranscriber, PlayerClock
            from luxai.live_captions import caption_model
            clock, timeline = PlayerClock(), CueTimeline()
            target = self._caption_target()
            translate = None
            if target is not None:
                def translate(text, source, target=target):
                    from luxai.translation import text_language, translate_offline
                    if text_language(text) == target:
                        return ""
                    return translate_offline(text, target, source) or ""
            # The best model: the film is prepared ahead, so there is time for it.
            transcriber = FilmTranscriber(candidates, report["page"], clock, timeline,
                                          lambda: caption_model("large-v3-turbo", threads=8),
                                          language=self._caption_language(), translate=translate,
                                          on_error=self._film_error.emit, video_duration=report["duration"],
                                          fast_model_provider=lambda: caption_model("small", threads=6))
            self._film = (key, clock, timeline, transcriber)
            clock.update(report["time"], report["paused"], report["rate"], report["duration"])
            transcriber.start()
            return
        film[1].update(report["time"], report["paused"], report["rate"], report["duration"])

    def _on_film_error(self, error: str):
        # Not usable (protected or refused media): the normal live captions simply continue.
        import logging
        logging.getLogger(__name__).info("Film captions: %s", error)

    def _film_tick(self):
        film = self._film
        bar = self._captions_bar
        if film is None or bar is None or not film[1].alive():
            self._set_film_active(False)
            return
        position = film[1].position()
        if not film[2].is_covered(position):
            self._set_film_active(False)  # not prepared yet here: the live captions show it
            return
        self._set_film_active(True)
        cues = film[2].lines_at(position, keep=bar.max_lines)
        # Words appear as they are spoken in the film (the rest of the line waits invisible).
        reveal = {cue.text: cue.shown(position) for cue in cues}
        cues = [cue for cue in cues if reveal[cue.text][0] or reveal[cue.text][1]]
        shown = [(cue.text, cue.translation, reveal[cue.text]) for cue in cues]
        if shown != self._film_shown:
            self._film_shown = shown
            bar.reveal = reveal
            bar.lines = [(cue.text, cue.translation) for cue in cues]
            bar.partial = ""
            bar.partial_translation = ""
            bar.render()

    def _set_film_active(self, active: bool):
        engine = self._captions_engine
        if engine is not None:
            engine.paused = active  # also a live engine restarted meanwhile (settings changed)
        if active == self._film_active:
            return
        self._film_active = active
        self._film_shown = None
        if self._captions_bar is not None:
            self._captions_bar.reveal = {}
        bar = self._captions_bar
        if bar is not None:
            bar.lines = []
            bar.partial = ""
            bar.partial_translation = ""
            bar.render()

    def open_browser_extension(self):
        """The guided installation window: opens the extensions page, copies the folder path, turns green
        by itself when the extension reports (the bridge listens while the window is open)."""
        from luxai.ui_browser_extension import ExtensionInstallDialog
        self._start_film_bridge_for_install()
        dialog = self._extension_dialog
        try:
            if dialog is not None and dialog.isVisible():
                dialog.raise_()
                dialog.activateWindow()
                return
        except RuntimeError:
            pass
        dialog = ExtensionInstallDialog(self.language)
        dialog.destroyed.connect(lambda *_: setattr(self, "_extension_dialog", None))
        self._extension_dialog = dialog
        dialog.show()
        dialog.start()
        if self.extension_installed():
            meta = (getattr(self.host, "cfg", {}) or {}).get("extensions_meta", {})
            dialog.connected(meta.get("browser_extension_seen") if isinstance(meta, dict) else None)

    def _start_film_bridge_for_install(self):
        if self._film_bridge is None:
            from luxai.film_captions import BridgeServer
            bridge = BridgeServer(self._film_report.emit, on_hello=self._extension_hello.emit)
            if bridge.start():
                self._film_bridge = bridge

    def _stop_caption_audio(self):
        capture, self._captions_capture = self._captions_capture, None
        engine, self._captions_engine = self._captions_engine, None
        if capture is not None:
            threading.Thread(target=capture.stop, daemon=True).start()
        if engine is not None:
            engine.stop()

    def _on_cap_partial(self, text: str):
        if self._captions_bar is None or self._film_active:
            return
        # «Only the translation»: the growing original is not shown.
        self._captions_bar.set_partial("" if self._captions_translate_only() else text)
        if text and self.settings("live_captions").get("quality", "hybrid") == "hybrid":
            self._translate_caption_draft(text)

    def _caption_target(self) -> str | None:
        """The translation language when captions are translated, else None."""
        settings = self.settings("live_captions")
        from luxai import offline_translate
        if not settings.get("translate") or not offline_translate.installed():
            return None
        target = settings.get("translate_to", "app")
        if target not in ("ru", "en", "ro"):
            from luxai.response_language import reply_language
            target = reply_language(getattr(self.host, "cfg", {}) or {})
        return target

    def _translate_caption_draft(self, text: str):
        """Hybrid: the growing draft is translated too, so the translation appears ~1 s after the words.

        One worker, only the NEWEST draft waits (older ones are skipped); a draft translation that
        comes back after its phrase was finished is ignored (the final translation replaces it).
        """
        target = self._caption_target()
        if target is None:
            return
        from luxai.translation import text_language
        if text_language(text) == target:
            return
        engine = self._captions_engine
        source = (getattr(engine, "detected", None) or self._caption_language() or "") if engine else ""
        phrase = self._cap_phrase
        if getattr(self, "_cap_draft_worker", None) is None:
            from luxai.background import LatestWorker
            self._cap_draft_worker = LatestWorker("JarvisCaptionDraftTranslate")

        def work():
            if phrase != self._cap_phrase:
                return  # the phrase finished while this draft waited
            from luxai.translation import translate_offline
            try:
                translated = translate_offline(text, target, source)
            except Exception:
                translated = None
            if translated:
                self._cap_partial_translated.emit(text, translated, phrase)

        self._cap_draft_worker.submit(work)

    def _on_cap_corrected(self, draft: str, precise: str):
        """Hybrid: the precise model finished a line — replace the draft and translate it again."""
        bar = self._captions_bar
        if bar is None or self._film_active:
            return
        if not draft:  # a phrase only the precise model could read: a new line
            self._on_cap_final(precise)
            return
        target = self._caption_target()
        from luxai.translation import text_language
        translate = target is not None and text_language(precise) != target
        if bar.correct_line(draft, precise, pending=translate) and translate:
            engine = self._captions_engine
            source = (getattr(engine, "detected", None) or self._caption_language() or "") if engine else ""
            self._queue_caption_translation(precise, target, source)

    def _on_cap_partial_translated(self, text: str, translated: str, phrase: int):
        if phrase == self._cap_phrase:
            self._cap_last_draft = (text, translated)  # a final line with the same text reuses it
        if self._captions_bar is None or phrase != self._cap_phrase:
            return
        self._captions_bar.set_partial("" if self._captions_translate_only() else text, translated)

    def _on_cap_final(self, text: str):
        self._cap_phrase += 1  # a draft translation still on its way is dropped
        last_draft, self._cap_last_draft = getattr(self, "_cap_last_draft", ("", "")), ("", "")
        if self._captions_bar is None or self._film_active:
            return
        self._captions_bar.partial_translation = ""  # the final line replaces the draft
        if last_draft[0] == text and last_draft[1]:
            self._captions_bar.add_final(text, last_draft[1])  # already translated as a draft: no wait
            return
        settings = self.settings("live_captions")
        from luxai import offline_translate
        if not settings.get("translate") or not offline_translate.installed():
            self._captions_bar.add_final(text)  # the translator is still downloading
            return
        from luxai.response_language import reply_language
        from luxai.translation import text_language
        target = settings.get("translate_to", "app")
        if target not in ("ru", "en", "ro"):
            target = reply_language(getattr(self.host, "cfg", {}) or {})
        if text_language(text) == target:
            self._captions_bar.add_final(text)  # already in the wanted language
            return
        self._captions_bar.add_final(text, pending=True)

        engine = self._captions_engine
        source = (getattr(engine, "detected", None) or self._caption_language() or "") if engine else ""
        self._queue_caption_translation(text, target, source)

    def _queue_caption_translation(self, text: str, target: str, source: str = ""):
        """One translation at a time, newest first; a failed one shows the original.

        The offline translator takes ≈0.5 s a phrase; when speech comes faster,
        older waiting phrases show their original so the bar never lags behind.
        """
        import queue as _queue
        if getattr(self, "_cap_translate_queue", None) is None:
            self._cap_translate_queue = _queue.Queue()

            def worker():
                while True:
                    item = self._cap_translate_queue.get()
                    if item is None:
                        return
                    # Too many waiting: the older ones show their original right away.
                    while self._cap_translate_queue.qsize() > 1:
                        stale = self._cap_translate_queue.get()
                        if stale is None:
                            return
                        self._cap_translated.emit(item[0], "")
                        item = stale
                    original, language, spoken = item
                    from luxai.translation import translate_offline
                    try:
                        translated = translate_offline(original, language, spoken)
                    except Exception:
                        translated = None
                    self._cap_translated.emit(original, translated or "")  # "" = show the original

            threading.Thread(target=worker, daemon=True, name="JarvisCaptionTranslate").start()
        self._cap_translate_queue.put((text, target, source))

    def _on_cap_translated(self, original: str, translated: str):
        if self._captions_bar is not None:
            self._captions_bar.set_translation(original, translated)

    def _on_cap_error(self, error: str):
        if self._captions_bar is not None:
            self._captions_bar.placeholder = self._captions_words("error", error=error[:160])
            self._captions_bar.render()

    def handle_captions_request(self, text: str) -> str | None:
        phrase = " ".join(str(text or "").casefold().replace("ё", "е").split()).strip(" .!?")
        phrase = re.sub(r"^(?:джарвис|жарвис|jarvis)[,\s]+", "", phrase)
        show = re.fullmatch(r"(?:покажи|включи|запусти|открой)\s+(?:живые\s+)?субтитры"
                            r"|(?:show|turn\s+on|enable)\s+(?:the\s+)?(?:live\s+)?captions"
                            r"|(?:arat[ăa]|porne[șs]te|activeaz[ăa])\s+subtitr[ăa]rile(?:\s+live)?", phrase)
        hide = re.fullmatch(r"(?:скрой|спрячь|выключи|убери|закрой)\s+(?:живые\s+)?субтитры"
                            r"|(?:hide|turn\s+off|disable)\s+(?:the\s+)?(?:live\s+)?captions"
                            r"|(?:ascunde|opre[șs]te|dezactiveaz[ăa])\s+subtitr[ăa]rile(?:\s+live)?", phrase)
        if show:
            return self.show_captions()
        if hide:
            return self.hide_captions()
        return None

    # -- visual avatar --
    def _avatar_base_color(self) -> str:
        settings = self.settings("visual_avatar")
        if settings.get("color_mode") == "theme":
            return (getattr(self.host, "cfg", {}) or {}).get("ui_accent", "#3978f6")
        return settings.get("color") or "#1f8fe0"

    def _avatar_screen(self) -> int:
        try:
            return int(self.settings("visual_avatar").get("monitor", "0") or 0)
        except (TypeError, ValueError):
            return 0

    def _apply_avatar(self):
        if not self.enabled("visual_avatar"):
            self._avatar_first_apply = False
            self._close_avatar()
            return
        settings = self.settings("visual_avatar")
        if self._avatar_first_apply:
            self._avatar_first_apply = False
            # «Запускать вместе с программой» off: it waits for «покажи аватар».
            self._avatar_session_hidden = not settings.get("autostart", True)
        if self._avatar_session_hidden:
            self._close_avatar()
            return
        from luxai.avatar import AvatarWindow, LevelMeter
        if self._avatar_window is None:
            self._avatar_meter = LevelMeter()
            self._avatar_window = AvatarWindow(self._avatar_meter)
            self._avatar_window.moved.connect(self._avatar_moved)
        self._avatar_window.apply(settings, self._avatar_base_color(), self._avatar_screen())
        key = (settings.get("source"), settings.get("apps"), bool(settings.get("react", True)))
        if key != self._avatar_audio_key:
            self._avatar_audio_key = key
            from luxai.clipboard_store import parse_names
            if settings.get("react", True):
                self._avatar_meter.start(settings.get("source", "voice"), parse_names(settings.get("apps", "")))
            else:
                self._avatar_meter.stop()
        self._avatar_window.show()
        if not self._avatar_timer.isActive():
            self._avatar_timer.start()

    def _close_avatar(self):
        self._avatar_timer.stop()
        window, self._avatar_window = self._avatar_window, None
        meter, self._avatar_meter = self._avatar_meter, None
        self._avatar_audio_key = None
        if meter is not None:
            meter.stop()
        if window is not None:
            try:
                window.view.timer.stop()
                window.close()
                window.deleteLater()
            except RuntimeError:
                pass

    def avatar_flags(self) -> dict:
        from luxai.voices import barge_in_ready
        cfg = getattr(self.host, "cfg", {}) or {}
        home = getattr(self.host, "avatar", None)
        return {
            "error": time.monotonic() < self._avatar_error_until,
            "exec": bool(getattr(self.host, "_processing", False)),
            "speak": barge_in_ready.is_set(),
            "mic_off": not cfg.get("microphone_enabled", True),
            "quiet": not cfg.get("tts_enabled", True),
            "prefix": bool(cfg.get("prefix_enabled", False)),
            "listening": bool(getattr(home, "_listening", False)),
        }

    def avatar_event(self, event: str):
        if event == "error":
            self._avatar_error_until = time.monotonic() + 2.5

    def _tick_avatar(self):
        from luxai.avatar import resolve_state
        window = self._avatar_window
        if window is None:
            return
        settings = self.settings("visual_avatar")
        state, color = resolve_state(self.avatar_flags(), settings, self._avatar_base_color())
        window.view.set_target(color)
        window.view.mode = state  # listening has its own animation (waves, calm orb)
        self._avatar_ticks += 1
        if self._avatar_ticks % 10 == 0:  # once a second
            from luxai.avatar import fullscreen_app_running
            full = bool(settings.get("hide_fullscreen", True)) and fullscreen_app_running()
            self._avatar_full_seconds = self._avatar_full_seconds + 1 if full else 0
            if self._avatar_full_seconds >= 2:  # a real game/video, not a flash of a screenshot overlay
                if window.isVisible():
                    window.hide()
            else:
                # Always back: shown, on top and on a screen, whatever happened.
                window.keep_visible(self._avatar_screen())

    def _avatar_moved(self, x: int, y: int):
        value = f"{int(x)},{int(y)}"
        if hasattr(self.host, "update_extension_setting"):
            self.host.update_extension_setting("visual_avatar", "position", value)
        else:
            self.state.setdefault("visual_avatar", {"enabled": True, "settings": {}})["settings"]["position"] = value

    def reset_avatar_position(self):
        if hasattr(self.host, "update_extension_setting"):
            self.host.update_extension_setting("visual_avatar", "position", "br")
        else:
            self.state.setdefault("visual_avatar", {"enabled": True, "settings": {}})["settings"]["position"] = "br"
            if self._avatar_window is not None:
                self._apply_avatar()

    def show_avatar(self) -> str:
        self._avatar_session_hidden = False
        self._avatar_first_apply = False
        if not self.enabled("visual_avatar") and hasattr(self.host, "set_extension_enabled"):
            self.host.set_extension_enabled("visual_avatar", True)  # saves and applies
        else:
            self.state.setdefault("visual_avatar", {"enabled": True, "settings": {}})["enabled"] = True
            self._apply_avatar()
        return _tr3("Показал аватар.", "The avatar is on.", "Am afișat avatarul.", self.language)

    def hide_avatar(self) -> str:
        self._avatar_session_hidden = True
        self._close_avatar()
        return _tr3("Скрыл аватар.", "The avatar is hidden.", "Am ascuns avatarul.", self.language)

    def handle_avatar_request(self, text: str) -> str | None:
        phrase = " ".join(str(text or "").casefold().replace("ё", "е").split()).strip(" .!?")
        phrase = re.sub(r"^(?:джарвис|жарвис|jarvis)[,\s]+", "", phrase)
        if re.fullmatch(r"(?:покажи|включи|верни)\s+(?:визуальн\w+\s+)?аватар\w*|(?:show|turn\s+on)\s+(?:the\s+)?avatar"
                        r"|(?:arat[ăa]|porne[șs]te)\s+avatarul", phrase):
            return self.show_avatar()
        if re.fullmatch(r"(?:скрой|спрячь|выключи|убери)\s+(?:визуальн\w+\s+)?аватар\w*|(?:hide|turn\s+off)\s+(?:the\s+)?avatar"
                        r"|(?:ascunde|opre[șs]te)\s+avatarul", phrase):
            return self.hide_avatar()
        return None

    def stop(self):
        self._stopping = True  # late clipboard / dictation / translation callbacks do nothing now
        self._stop_film()  # the browser bridge too (the port is free for the next start)
        clipboard = QApplication.clipboard() if QApplication.instance() else None
        if clipboard is not None and self._clipboard_connected:
            try:
                clipboard.dataChanged.disconnect(self._on_clipboard)
            except (RuntimeError, TypeError):
                pass
            self._clipboard_connected = False
        self._clip_read_timer.stop()
        self._clip_load_generation += 1  # a history still loading is not merged any more
        if self._clip_save_timer.isActive():
            self._clip_save_timer.stop()
            self._save_clip_history(wait=True)  # the last copies are not lost on close (audit #14)
        else:
            self._clip_saver.wait(8.0)  # a save that already started finishes first (audit 2 #15)
        self._close_avatar()
        self.hide_captions()
        self._notif_timer.stop()
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
        elif plugin_id == "live_captions":
            self.toggle_captions()
        elif plugin_id == "quick_inserts":
            self.open_snippets()
        elif plugin_id == "read_aloud":
            self.read_selection()
        elif plugin_id == "media_keys" and key in MEDIA_KEYS:
            press_virtual_key(MEDIA_KEYS[key])
        elif plugin_id == "screenshots":
            self.take_screenshot(window=(key == "window_hotkey"))
        elif plugin_id == "notification_reader":
            self.repeat_last_notification()
        elif plugin_id == "converter":
            if key == "region_hotkey":
                self.start_region_convert()
            else:
                self.start_convert_circle()

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
            ("clipboard_history", "clear_all"): self.clear_clipboard_all,
            ("live_captions", "toggle"): self.toggle_captions,
            ("visual_avatar", "reset_position"): self.reset_avatar_position,
            ("live_captions", "reset_position"): self.reset_captions_position,
            ("live_captions", "browser_extension"): self.open_browser_extension,
            ("quick_inserts", "open"): lambda: self.open_snippets(paste=False),
            ("breaks", "test"): lambda: self.remind_break(force=True),
            ("breaks", "try_eyes"): lambda: self.show_break_card("eyes", test=True),
            ("breaks", "try_stretch"): lambda: self.show_break_card("stretch", test=True),
            ("breaks", "try_water"): lambda: self.show_break_card("water", test=True),
            ("smart_dictation", "test"): lambda: self.start_dictation(test=True),
            ("smart_dictation", "copy_last"): self.copy_last_dictation,
            ("pc_control", "check"): self.check_pc_connection,
            ("pc_control", "open"): self.open_bot,
            ("converter", "convert"): lambda: self.choose_files_to_convert(parent),
            ("notification_reader", "test"): lambda: self._speak(self.NOTIFICATION_SAMPLE.get(self.language, self.NOTIFICATION_SAMPLE["ru"])),
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
        self._dictation_gen = getattr(self, "_dictation_gen", 0) + 1
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
        self._dictation_gen = getattr(self, "_dictation_gen", 0) + 1  # a running transcription is dropped
        self._dictation_busy = False
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
        generation = getattr(self, "_dictation_gen", 0)

        def current() -> bool:
            return generation == getattr(self, "_dictation_gen", 0) and not getattr(self, "_stopping", False)

        def work():
            try:
                model = model_provider() if callable(model_provider) else None
                if model is None:
                    model = dictation.load_model(cfg.get("whisper_model_path") or cfg.get("whisper_model") or "small")
                text = dictation.transcribe(model, audio, language, int(cfg.get("whisper_beam_size", 1) or 1))
                result = (self.finish_text(text, settings, planner), "", test)
            except Exception as error:
                result = ("", f"{type(error).__name__}: {error}", test)
            if current():
                self._dictation_result_gen = generation
                self.dictation_result.emit(*result)

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
        if getattr(self, "_dictation_result_gen", 0) != getattr(self, "_dictation_gen", 0):
            # An older recording (cancelled meanwhile): cancel_dictation already released the state;
            # a NEWER dictation may be running now, so nothing is touched (audit 2 #22).
            return
        if getattr(self, "_stopping", False) or not self.enabled("smart_dictation"):
            # Turned off or closing: release the state, but never insert the text (audit #4, 2 #22).
            self._dictation_busy = False
            if self._overlay is not None:
                self._overlay.hide()
            DICTATION_ACTIVE.clear()
            return
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
        if not target and self.test_sink is not None and self.test_sink(text):
            return
        if not target:
            QApplication.clipboard().setText(text)
            self._notify(_tr3("Нет активного поля — текст скопирован в буфер обмена.",
                              "No active field — the text was copied to the clipboard.",
                              "Niciun câmp activ — textul a fost copiat în clipboard.", self.language))
            return
        self._type_when_released(text, target, time.monotonic() + 1.5)

    def _type_when_released(self, text: str, target: int, deadline: float):
        """Type only after Ctrl/Alt/Shift/Win are released, checked with a Qt timer instead of sleeping
        on the UI thread (audit 2 #38); a key still held after 1.5 s → the text goes to the clipboard."""
        from luxai.dictation import modifiers_held, type_text
        if modifiers_held():
            if time.monotonic() < deadline:
                QTimer.singleShot(40, lambda: self._type_when_released(text, target, deadline))
                return
            QApplication.clipboard().setText(text)
            self._notify(_tr3("Клавиша Ctrl/Alt/Shift всё ещё нажата — текст скопирован в буфер обмена.",
                              "Ctrl/Alt/Shift is still held — the text was copied to the clipboard.",
                              "Ctrl/Alt/Shift e încă apăsată — textul a fost copiat în clipboard.", self.language))
            return
        if not _set_foreground(target):
            # The window was closed or Windows refused to bring it forward: typing now would land in
            # whatever window is active (audit #3). Keep the text for an explicit paste instead.
            QApplication.clipboard().setText(text)
            self._notify(_tr3("Окно, куда вы диктовали, недоступно — текст скопирован в буфер обмена.",
                              "The window you dictated into is not available — the text is on the clipboard.",
                              "Fereastra în care dictai nu mai e disponibilă — textul e în clipboard.", self.language))
            return
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
        self._bot_generation += 1
        generation = self._bot_generation
        # Every signal carries the bot generation: a reply of the OLD bot that is still in the Qt queue
        # after a token change never updates the new bot's state (audit 2 #40).
        self._bot = TelegramBot(token, lambda update, g=generation: self._pc_update.emit(dict(update, _bot_gen=g)),
                                lambda state, details, g=generation: self._pc_status.emit(state, dict(details or {}, _bot_gen=g)))
        self._set_pc_status("connecting", {})
        self._bot.start()

    def _stop_bot(self):
        if self._bot is not None:
            self._bot_generation += 1
            self._bot.stop()
            self._bot = None
            self._bot_token = ""

    def _set_pc_status(self, state, details):
        self.pc_state = (state, dict(details))
        self.pc_status_changed.emit(state, dict(details))

    def _from_old_bot(self, payload) -> bool:
        generation = payload.pop("_bot_gen", None) if isinstance(payload, dict) else None
        return generation is not None and generation != self._bot_generation

    def _on_pc_status(self, state, details):
        details = dict(details or {})
        if self._from_old_bot(details):
            return
        if state == "undelivered":
            # A reply to the phone was lost: say so here, so the command is not sent twice blindly (audit #24).
            self.notice.emit(_tr3("Telegram: ответ на телефон не доставлен — ", "Telegram: the reply to the phone was not delivered — ",
                                  "Telegram: răspunsul către telefon nu a fost livrat — ", self.language)
                             + str(details.get("message", ""))[:160])
            return
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
        update = dict(update or {})
        if self._from_old_bot(update) or not self.enabled("pc_control") or self._bot is None:
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

    # -- notification reader --
    NOTIFICATION_SAMPLE = {
        "ru": "Telegram: Мама — Купи хлеба по дороге домой, пожалуйста. И молоко, если будет.",
        "en": "Telegram: Mom — Please grab some bread on the way home. And milk, if they have it.",
        "ro": "Telegram: Mama — Te rog, ia pâine în drum spre casă. Și lapte, dacă găsești.",
    }

    def _apply_notifications(self):
        from luxai.notifications import NotificationWatcher
        if not self.enabled("notification_reader"):
            self._notif_timer.stop()
            self._notif_watcher = None
            return
        if self._notif_watcher is None:
            self._notif_watcher = NotificationWatcher(getattr(self, "notifications_db", None))
            self._notif_watcher.prime()  # never read what was already there
        meta = (getattr(self.host, "cfg", {}) or {}).get("extensions_meta", {})
        self.seen_notification_apps.update(str(name)[:40] for name in meta.get("notification_apps", [])[:100])
        if not self._notif_timer.isActive():
            self._notif_timer.start()

    def _remember_app(self, app):
        if not app or app in self.seen_notification_apps:
            return
        self.seen_notification_apps.add(app)
        cfg = getattr(self.host, "cfg", None)
        if isinstance(cfg, dict):
            meta = cfg.setdefault("extensions_meta", {})
            meta["notification_apps"] = sorted(self.seen_notification_apps)[:100]
            if hasattr(self.host, "save_extensions_meta"):
                self.host.save_extensions_meta()
        self.notification_apps_changed.emit()

    def _silence_reason(self) -> str:
        from luxai import notifications as n
        settings = self.settings("notification_reader")
        cfg = getattr(self.host, "cfg", {}) or {}
        if n.computer_locked():
            return "locked"
        if time.time() < self.dnd_until:
            return "dnd"
        if settings.get("quiet_enabled") and n.in_quiet_hours(_dt.datetime.now().hour, int(settings.get("quiet_from", 23)),
                                                              int(settings.get("quiet_to", 8))):
            return "quiet_hours"
        if settings.get("silent_quiet_mode", True) and not cfg.get("tts_enabled", True):
            return "quiet_mode"
        if settings.get("silent_fullscreen", True) and foreground_is_fullscreen():
            return "fullscreen"
        if settings.get("silent_calls", True) and n.microphone_in_use_by_other_app():
            return "call"
        return ""

    def notification_texts(self, items) -> list[str]:
        """Compose (and group) a batch of {app, texts} into sentences."""
        from luxai import notifications as n
        settings = self.settings("notification_reader")
        rules = n.parse_rules(settings.get("app_rules", ""))
        options = dict(say_app=bool(settings.get("say_app", True)), mode=settings.get("read_mode", "text"),
                       skip_codes=bool(settings.get("skip_codes", True)), skip_links=bool(settings.get("skip_links", True)),
                       limit=int(settings.get("max_length", 140)), language=self.language)
        by_app: dict[str, list] = {}
        for item in items:
            self._remember_app(item["app"])
            if not item["texts"] or not n.app_allowed(item["app"], rules):
                continue
            by_app.setdefault(item["app"], []).append(item["texts"])
        result = []
        for app, entries in by_app.items():
            if len(entries) > 1 and settings.get("group", True):
                result.append(n.group_message(app, [texts[0] for texts in entries], len(entries), self.language,
                                              say_app=options["say_app"]))
            else:
                result.extend(filter(None, (n.compose(app, texts, **options) for texts in entries)))
        return result

    def _poll_notifications_async(self):
        """Read the Windows notification database on a worker (audit 2 #27): a busy database can wait
        its 0.5 s there, never in the window. One read at a time; results come back as one batch."""
        watcher = self._notif_watcher
        if watcher is None:
            return

        def work():
            try:
                items = watcher.poll()
            except Exception:
                return
            self._notif_items.emit(items or [], watcher)  # also empty: pending «missed» are flushed

        self._notif_reader.submit(work)

    def _on_notif_items(self, items, watcher):
        if watcher is not self._notif_watcher or getattr(self, "_stopping", False):
            return  # turned off (or restarted) meanwhile
        self._handle_notification_items(items)

    def _poll_notifications(self):
        if self._notif_watcher is None:
            return
        self._handle_notification_items(self._notif_watcher.poll())

    def _handle_notification_items(self, items):
        for value in self.notification_texts(items):
            if self.settings("notification_reader").get("translate", True) and self._notification_foreign(value):
                self._translate_notification(value)  # arrives later through _notif_ready
            else:
                self._accept_notification(value, flush=False)
        self._flush_notifications()

    def _split_app(self, value: str):
        for app in sorted(self.seen_notification_apps, key=len, reverse=True):
            if app and value.startswith(app + ": "):
                return app + ": ", value[len(app) + 2:]
        return "", value

    def _notification_foreign(self, value: str) -> bool:
        from luxai.translation import needs_translation
        _, body = self._split_app(value)
        return needs_translation(body, self.reading_target())

    def reading_target(self) -> str:
        from luxai.response_language import reply_language
        return reply_language(getattr(self.host, "cfg", {}) or {})

    def _translate_notification(self, value: str, *, wait: bool = False):
        prefix, body = self._split_app(value)
        target = self.reading_target()

        def work():
            translated = None
            try:
                from luxai.translation import translate_offline
                translated = translate_offline(body, target)
            except Exception:
                translated = None
            self._notif_ready.emit(prefix + translated if translated else value)

        if wait:
            work()
        elif not self._translations.submit(work):
            self._notif_ready.emit(value)  # the queue is full: read it untranslated rather than lose it

    def _accept_notification(self, value: str, flush: bool = True):
        self.notification_memory.append(value)
        self._notif_pending.append(value)
        if flush:
            self._flush_notifications()

    def _flush_notifications(self):
        from luxai.dictation import DICTATION_ACTIVE
        if not self._notif_pending:
            return
        if DICTATION_ACTIVE.is_set() or self.dictating:
            return  # wait for our turn
        settings = self.settings("notification_reader")
        reason = self._silence_reason()
        if reason or not settings.get("read_now", True):
            self.missed_notifications.extend(self._notif_pending)
            self._notif_pending = []
            return
        pending, self._notif_pending = self._notif_pending, []
        for value in pending:
            self._speak_notification(value)

    def _speak_notification(self, value):
        if hasattr(self.host, "_queue_speech"):
            from luxai.translation import text_language
            _, body = self._split_app(value)
            language = text_language(body)
            if language not in ("ru", "ro", "en"):
                language = self.reading_target()
            self.host._queue_speech(value, language)

    def repeat_last_notification(self):
        if self.notification_memory:
            self._speak_notification(self.notification_memory[-1])

    def _nw(self, key, **values):
        words = {
            "none": ("Новых уведомлений нет.", "No new notifications.", "Nu sunt notificări noi."),
            "no_last": ("Уведомлений ещё не было.", "There were no notifications yet.", "Încă nu au fost notificări."),
            "off": ("Хорошо, уведомления читать не буду. Спросите «что пришло», чтобы узнать пропущенное.",
                    "OK, I won't read notifications. Ask “what came in” to hear missed ones.",
                    "Bine, nu mai citesc notificările. Întreabă „ce a venit” ca să auzi ce ai ratat."),
            "on": ("Хорошо, буду читать новые уведомления.", "OK, I'll read new notifications.", "Bine, voi citi notificările noi."),
            "dnd": ("Хорошо, час не буду читать уведомления.", "OK, no notifications for an hour.",
                    "Bine, o oră nu citesc notificările."),
            "disabled": ("Озвучка уведомлений выключена. Включите её в Расширениях.",
                         "Notification reader is off. Turn it on in Extensions.",
                         "Citirea notificărilor e oprită. Pornește-o în Extensii."),
            "more": ("И ещё {n}.", "And {n} more.", "Și încă {n}."),
        }[key]
        return _tr3(*words, self.language).format(**values)

    def handle_notification_request(self, text: str) -> str | None:
        from luxai.notifications import parse_voice_request
        request = parse_voice_request(text)
        if request is None:
            return None
        if not self.enabled("notification_reader"):
            return self._nw("disabled")
        if request == "missed":
            items = list(self.missed_notifications) + self._notif_pending
            self.missed_notifications.clear()
            self._notif_pending = []
            if not items:
                return self._nw("none")
            shown = items[-5:]
            extra = len(items) - len(shown)
            return "\n".join(shown) + (("\n" + self._nw("more", n=extra)) if extra else "")
        if request == "last":
            return self.notification_memory[-1] if self.notification_memory else self._nw("no_last")
        if request == "dnd":
            self.dnd_until = time.time() + 3600
            return self._nw("dnd")
        enable = request == "on"
        updater = getattr(self.host, "update_extension_setting", None)
        if callable(updater):
            updater("notification_reader", "read_now", enable)
        else:
            self.state["notification_reader"]["settings"]["read_now"] = enable
        return self._nw("on" if enable else "off")

    def handle_text_request(self, text: str) -> str | None:
        """Typed or spoken requests handled by extensions (notifications, timers)."""
        return (self.handle_notification_request(text) or self.handle_timer_request(text)
                or self.handle_clipboard_request(text) or self.handle_captions_request(text)
                or self.handle_avatar_request(text) or self.handle_translate_request(text))

    def handle_translate_request(self, text: str) -> str | None:
        """«Переведи …» / «Tradu …» / «Translate …» in the chat: the offline translator answers (≈0.5 s).

        Without a named language the text must be in another language than the
        request word — «переведи компьютер в спящий режим» stays a PC command.
        """
        from luxai import chat_translate, offline_translate
        from luxai.response_language import reply_language
        from luxai.translation import translate_offline
        parsed = chat_translate.parse_request(text)
        if parsed is None:
            return None
        value, named, verb_language = parsed
        source = offline_translate.source_language(value) if value else ""
        if not named and (not value or not source or source == verb_language):
            return None
        if not value:
            return _tr3("Что перевести? Например: «переведи на английский: доброе утро».",
                        "What should I translate? For example: “translate to Romanian: good morning”.",
                        "Ce să traduc? De exemplu: „tradu în engleză: bună dimineața”.", self.language)
        jarvis = reply_language(getattr(self.host, "cfg", {}) or {})
        target = chat_translate.choose_target(value, named, jarvis)
        if source == target:
            return value
        if not offline_translate.installed():
            offline_translate.download_in_background()
            return _tr3("Переводчик ещё скачивается (≈640 МБ, один раз) — попробуйте через пару минут.",
                        "The translator is still downloading (≈640 MB, once) — try again in a few minutes.",
                        "Traducătorul încă se descarcă (≈640 MB, o singură dată) — încearcă peste câteva minute.",
                        self.language)
        language = self.language

        def work():
            # Loading the model (~1 s) and translating must never freeze the window (audit 2026-11-19, #26).
            try:
                result = translate_offline(value, target, source)
            except Exception:
                result = None
            if result:
                self.chat_reply.emit(result, target if target in ("ru", "en", "ro") else "")
            else:
                self.chat_reply.emit(_tr3("Не получилось перевести этот текст.", "Could not translate this text.",
                                          "Textul nu a putut fi tradus.", language), "")

        if not self._translations.submit(work):
            return _tr3("Переводчик занят — попробуйте через минуту.", "The translator is busy — try again in a minute.",
                        "Traducătorul e ocupat — încearcă peste un minut.", self.language)
        return AsyncReply("…")

    def take_reply_language(self) -> str | None:
        """The language of the last reply when it differs from Jarvis' (a translation), once."""
        language, self._reply_language = getattr(self, "_reply_language", None), None
        return language

    # -- converter circle --
    def _cw(self, key, **values):
        words = {
            "nothing": ("Выделите файлы в Проводнике или на рабочем столе, или скопируйте картинку.",
                        "Select files in Explorer or on the desktop, or copy a picture.",
                        "Selectează fișiere în Explorer sau pe desktop, ori copiază o imagine."),
            "unsupported": ("Эти файлы не поддерживаются: нужны картинки, звук или видео.",
                            "These files are not supported: images, audio or video are needed.",
                            "Fișierele nu sunt acceptate: e nevoie de imagini, sunet sau video."),
            "busy": ("Конвертер ещё работает.", "The converter is still working.", "Convertorul încă lucrează."),
            "working": ("Конвертирую… {p}%", "Converting… {p}%", "Convertesc… {p}%"),
            "done": ("Готово: {names}", "Done: {names}", "Gata: {names}"),
            "errors": ("Не получилось: {names}", "Failed: {names}", "Nu a reușit: {names}"),
            "copied": ("Картинка скопирована в буфер обмена.", "Picture copied to the clipboard.", "Imaginea a fost copiată în clipboard."),
            "files": ("{n} файл(ов)", "{n} file(s)", "{n} fișier(e)"),
            "area": ("Обведите область — Esc для отмены", "Draw an area — Esc to cancel", "Încadrează o zonă — Esc pentru anulare"),
            "crop_title": ("Обрезать", "Crop", "Decupează"),
            "crop_ok": ("Обрезать", "Crop", "Decupează"),
            "cancel": ("Отмена", "Cancel", "Anulează"),
            "back": ("Назад", "Back", "Înapoi"),
        }[key]
        return _tr3(*words, self.language).format(**values)

    def _convert_out_dir(self, *, forced: bool = False):
        settings = self.settings("converter")
        if settings.get("destination") == "folder" or forced:
            configured = settings.get("folder", "")
            if configured:
                return Path(os.path.expandvars(os.path.expanduser(configured)))
            return downloads_folder() / "Jarvis Converted"
        return None

    def _circle_theme(self):
        choice = self.settings("converter").get("circle_theme", "app")
        cfg = getattr(self.host, "cfg", {}) or {}
        theme = cfg.get("ui_theme", "dark") if choice == "app" else choice
        return ("light" if theme == "light" else "dark"), cfg.get("ui_accent", "#3978f6")

    def start_convert_circle(self):
        """Read the Explorer/desktop selection (or a copied picture), then show the circle."""
        if self._converting:
            self._notify(self._cw("busy"))
            return
        from luxai.dictation import wait_for_modifiers_released
        hwnd = int(ctypes.windll.user32.GetForegroundWindow() or 0) if sys.platform == "win32" else 0
        name = ""
        if hwnd:
            buffer = ctypes.create_unicode_buffer(64)
            ctypes.windll.user32.GetClassNameW(hwnd, buffer, 64)
            name = buffer.value
        clipboard = QApplication.clipboard()
        if name in ("CabinetWClass", "ExploreWClass", "Progman", "WorkerW"):
            from luxai.selection import capture_clipboard, clipboard_sequence, restore_clipboard
            saved = capture_clipboard(clipboard)
            before = clipboard_sequence()
            wait_for_modifiers_released()
            try:
                from luxai.keys import press, release_modifiers
                release_modifiers()
                press("ctrl", "c", interval=0.05)
            except Exception:
                pass

            def after_copy():
                changed = clipboard_sequence() != before
                sources = self._clipboard_sources(clipboard)
                if changed and saved is not None:
                    self._ignore_clipboard_text = clipboard.text() or None
                    restore_clipboard(clipboard, saved)
                self._show_convert_circle(sources)

            QTimer.singleShot(350, after_copy)
            return
        self._show_convert_circle(self._clipboard_sources(clipboard))

    def _clipboard_sources(self, clipboard):
        data = clipboard.mimeData()
        if data is not None and data.hasUrls():
            paths = [Path(url.toLocalFile()) for url in data.urls() if url.isLocalFile()]
            return [path for path in paths if path.is_file()][:200]
        image = clipboard.image()
        if not image.isNull():
            folder = self._convert_out_dir(forced=True)
            folder.mkdir(parents=True, exist_ok=True)
            target = unique_path(folder / _dt.datetime.now().strftime("Картинка %Y-%m-%d %H-%M-%S.png"))
            if image.save(str(target), "PNG"):
                return [target]
        return []

    def start_region_convert(self):
        from luxai.ui_convert_circle import RegionSelector
        selector = RegionSelector(self._cw("area"))
        selector.selected.connect(self._region_selected)
        selector.start()
        self._region_selector = selector

    def _region_selected(self, pixmap):
        folder = self._convert_out_dir(forced=True)
        folder.mkdir(parents=True, exist_ok=True)
        target = unique_path(folder / _dt.datetime.now().strftime("Снимок %Y-%m-%d %H-%M-%S.png"))
        if pixmap.save(str(target), "PNG"):
            self._show_convert_circle([target])

    def choose_files_to_convert(self, parent=None):
        files, _ = QFileDialog.getOpenFileNames(parent, _tr3("Выберите файлы", "Choose files", "Alege fișiere", self.language),
                                                str(Path.home()))
        if files:
            self._show_convert_circle([Path(name) for name in files])

    def convert_sectors(self, kind: str) -> list[tuple[str, str, str]]:
        settings = self.settings("converter")
        L3 = lambda ru, en, ro: _tr3(ru, en, ro, self.language)  # noqa: E731
        catalog = {
            "image": [("s_format", "format", L3("Формат", "Format", "Format"), "image"),
                      ("s_compress", "compress", L3("Сжать", "Compress", "Comprimă"), "package"),
                      ("s_resize", "resize", L3("Уменьшить", "Downsize", "Micșorează"), "minus"),
                      ("s_rotate", "rotate", L3("Повернуть", "Rotate", "Rotește"), "rotate-cw"),
                      ("s_crop", "crop", L3("Обрезать", "Crop", "Decupează"), "scan"),
                      ("s_nometa", "nometa", L3("Без метаданных", "No metadata", "Fără metadate"), "eye-off"),
                      ("s_pdf", "pdf", L3("В PDF", "To PDF", "În PDF"), "file-text"),
                      ("s_clipboard", "clipboard", L3("В буфер", "To clipboard", "În clipboard"), "clipboard")],
            "audio": [(f"s_{fmt}", f"audio:{fmt}", fmt.upper(), "audio-lines")
                      for fmt in ("mp3", "m4a", "wav", "flac", "ogg", "opus")],
            "video": [("s_mp4", "video:mp4", L3("В MP4", "To MP4", "În MP4"), "play"),
                      ("s_vcompress", "video:compress", L3("Сжать видео", "Compress video", "Comprimă video"), "package"),
                      ("s_gif", "video:gif", L3("В GIF", "To GIF", "În GIF"), "image"),
                      ("s_tomp3", "audio:mp3", L3("Звук в MP3", "Audio to MP3", "Sunet în MP3"), "audio-lines"),
                      ("s_mute", "video:mute", L3("Без звука", "No sound", "Fără sunet"), "volume-x")],
        }[kind]
        return [(action, label, icon_name) for key, action, label, icon_name in catalog if settings.get(key, True)]

    def _show_convert_circle(self, sources, items=None, title=None):
        from luxai.converter import kind_of
        from luxai.ui_convert_circle import RadialMenu
        if not sources:
            self._notify(self._cw("nothing"))
            return
        kinds = [kind_of(path) for path in sources]
        kind = next((k for k in ("image", "video", "audio") if k in kinds), "")
        if not kind:
            self._notify(self._cw("unsupported"))
            return
        sources = [path for path, k in zip(sources, kinds) if k == kind]
        items = items if items is not None else self.convert_sectors(kind)
        if not items:
            return
        if title is None:
            title = sources[0].name if len(sources) == 1 else self._cw("files", n=len(sources))
            if len(title) > 22:
                title = title[:20] + "…"
        theme, accent = self._circle_theme()
        menu = RadialMenu(items, title, theme=theme, accent=accent)
        menu.picked.connect(lambda action: self._convert_pick(action, sources))
        menu.show_at()
        self._circle = menu

    def _convert_pick(self, action, sources):
        L3 = lambda ru, en, ro: _tr3(ru, en, ro, self.language)  # noqa: E731
        sub = {
            "format": [(f"format:{fmt}", fmt.upper(), "image") for fmt in ("png", "jpg", "webp", "ico", "bmp")],
            "resize": [("resize:75", "75%", "minus"), ("resize:50", "50%", "minus"), ("resize:25", "25%", "minus"),
                       ("resize:px1920", "1920 px", "monitor"), ("resize:px1280", "1280 px", "monitor")],
            "rotate": [("rotate:right", L3("90° вправо", "90° right", "90° dreapta"), "rotate-cw"),
                       ("rotate:left", L3("90° влево", "90° left", "90° stânga"), "rotate-ccw"),
                       ("rotate:180", "180°", "refresh-cw"),
                       ("rotate:mirror", L3("Отразить", "Mirror", "Oglindește"), "move")],
        }
        if action in sub:
            self._show_convert_circle(sources, sub[action], title=L3("Выберите", "Choose", "Alege"))
            return
        if action == "clipboard":
            image = QImage(str(sources[0]))
            if not image.isNull():
                QApplication.clipboard().setImage(image)
                self._notify(self._cw("copied"))
            return
        if action == "crop":
            from luxai.ui_convert_circle import CropDialog
            dialog = CropDialog(sources[0], self._cw("crop_title"), self._cw("crop_ok"), self._cw("cancel"))
            dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            if dialog.exec() != QDialog.DialogCode.Accepted or dialog.box is None:
                return
            action = "crop:" + ",".join(str(round(value)) for value in dialog.box)
            sources = sources[:1]
        self.run_conversion(action, sources)

    def run_conversion(self, action, sources, *, wait: bool = False):
        """Run one circle action in a worker thread (``wait`` for tests)."""
        from luxai import converter
        if self._converting:
            self._notify(self._cw("busy"))
            return None
        quality = int(self.settings("converter").get("quality", 85))
        out_dir = self._convert_out_dir()
        self._converting = True
        if self._convert_overlay is None:
            self._convert_overlay = DictationOverlay()
        self._convert_overlay.show_text(self._cw("working", p=0))
        total = len(sources)

        def work():
            results, errors = [], []
            if action == "pdf":
                try:
                    results.append(converter.images_to_pdf(sources, out_dir=out_dir))
                except Exception as error:
                    errors.append(f"PDF: {error}")
            else:
                for index, source in enumerate(sources):
                    def progress(value, index=index):
                        self.convert_progress.emit((index + value) / total)
                    try:
                        name, _, arg = action.partition(":")
                        if name == "format":
                            out = converter.image_format(source, arg, quality=quality, out_dir=out_dir)
                        elif name == "compress":
                            out = converter.image_compress(source, quality=quality, out_dir=out_dir)
                        elif name == "resize":
                            out = (converter.image_resize(source, max_side=int(arg[2:]), quality=quality, out_dir=out_dir)
                                   if arg.startswith("px") else
                                   converter.image_resize(source, percent=int(arg), quality=quality, out_dir=out_dir))
                        elif name == "rotate":
                            out = converter.image_rotate(source, arg, quality=quality, out_dir=out_dir)
                        elif name == "crop":
                            out = converter.image_crop(source, [float(v) for v in arg.split(",")], quality=quality, out_dir=out_dir)
                        elif name == "nometa":
                            out = converter.image_strip_metadata(source, out_dir=out_dir)
                        elif name == "audio":
                            tag = "audio" if converter.kind_of(source) == "video" else ""
                            out = converter.audio_convert(source, arg, out_dir=out_dir, progress=progress, tag=tag)
                        elif name == "video":
                            out = converter.video_convert(source, mode=arg, out_dir=out_dir, progress=progress)
                        else:
                            raise ValueError(action)
                        results.append(out)
                    except Exception as error:
                        errors.append(f"{Path(source).name}: {error}")
                    self.convert_progress.emit((index + 1) / total)
            self.convert_done.emit([str(path) for path in results], errors)

        if wait:
            work()
            return True
        threading.Thread(target=work, daemon=True, name="JarvisConverter").start()
        return True

    def _on_convert_progress(self, value):
        if self._converting and self._convert_overlay is not None:
            self._convert_overlay.show_text(self._cw("working", p=int(value * 100)))

    def _on_convert_done(self, results, errors):
        self._converting = False
        if self._convert_overlay is not None:
            self._convert_overlay.hide()
        self.last_conversion = (list(results), list(errors))
        if results:
            names = ", ".join(Path(path).name for path in results[:3]) + (f" +{len(results) - 3}" if len(results) > 3 else "")
            self._notify(self._cw("done", names=names))
        if errors:
            self._notify(self._cw("errors", names="; ".join(errors[:3])))

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
            if self._ringing:
                self.stop_ringing()  # turning the extension off silences a ringing alarm too (audit #19)

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
            "save_failed": ("Не удалось сохранить таймеры (ошибка диска) — ничего не изменено.",
                            "Could not save the timers (disk error) — nothing was changed.",
                            "Nu am putut salva cronometrele (eroare de disc) — nu s-a schimbat nimic."),
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
        except OSError:
            return _tr3("Не удалось сохранить таймер на диск — попробуйте ещё раз.",
                        "Could not save the timer to disk — please try again.",
                        "Cronometrul nu a putut fi salvat pe disc — încearcă din nou.", self.language)
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
            try:
                removed = self.timer_store.remove_many([item.id for item in targets])
            except OSError:
                return self._words("save_failed")
            self.timers_changed.emit()
            return self._words("cancel_n", n=removed)
        first = targets[0]
        self.cancel_timer(first.id)
        return self._words("cancel_one", what=self._describe(first))

    def _check_timers(self):
        if not self.enabled("timers"):
            return  # a delayed check after the extension was turned off (audit #19)
        rung = getattr(self, "_rung_ids", None)
        if rung is None:
            rung = self._rung_ids = set()
        for timer in self.timer_store.due():
            if timer.id in rung:
                # Rang already, but its removal could not be saved: try again, never ring twice.
                try:
                    self.timer_store.remove(timer.id)
                    rung.discard(timer.id)
                except OSError:
                    pass
                continue
            # Ring FIRST, then remove: a locked file or a crash in between may ring again
            # after a restart, but never loses the alarm (audit #9).
            rung.add(timer.id)
            self.ring(timer)
            try:
                self.timer_store.remove(timer.id)
                rung.discard(timer.id)
            except OSError:
                pass
            self.timers_changed.emit()

    def _ring_text(self, timer) -> str:
        from luxai.timers import format_duration
        if timer.kind == "alarm" and not timer.label:
            return self._words("ring_alarm", t=_dt.datetime.fromtimestamp(timer.due).strftime("%H:%M"))
        if timer.label:  # «remind me at 09:30 to call Ana» shows «call Ana» (audit #15)
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
            dialog.snoozed.connect(lambda t=timer, d=dialog: self.snooze(t, d))
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

    def snooze(self, timer, dialog=None):
        """Save the snoozed alarm FIRST; only then close THIS alarm's window (audit 2 #18).

        Other alarms that ring at the same time stay open. When the snooze cannot be saved (20
        timers already, disk error) the window stays and the reason is shown.
        """
        from luxai.timers import new_timer
        minutes = int(self.settings("timers").get("snooze", 5))
        due = _dt.datetime.now().timestamp() + minutes * 60
        try:
            self.timer_store.add(new_timer(timer.kind, due, timer.label, timer.duration))
        except ValueError:
            self.notice.emit(self._words("too_many"))
            return False
        except OSError:
            self.notice.emit(self._words("save_failed"))
            return False
        keep = []
        for entry in self._ringing:
            ringing_timer, ringing_dialog = entry
            if (dialog is not None and ringing_dialog is dialog) or (dialog is None and ringing_timer is timer):
                try:
                    if ringing_dialog is not None:
                        ringing_dialog.close()
                except RuntimeError:
                    pass
            else:
                keep.append(entry)
        self._ringing = keep
        if not keep:
            self._ring_beeper.stop()
        self.timers_changed.emit()
        return True

    # -- breaks --
    def _break_interval(self, kind: str) -> int:
        try:
            return int(self.settings("breaks").get(f"{kind}_every", {"eyes": 20, "stretch": 55, "water": 90}[kind])) * 60
        except (TypeError, ValueError):
            return {"eyes": 20, "stretch": 55, "water": 90}[kind] * 60

    def _break_kinds(self):
        settings = self.settings("breaks")
        return [kind for kind in BREAK_KINDS if settings.get(f"{kind}_on", True)]

    def break_stats(self):
        cfg = getattr(self.host, "cfg", None)
        meta = cfg.get("extensions_meta", {}) if isinstance(cfg, dict) else {}
        stats = meta.get("breaks_today", {})
        if stats.get("date") != _dt.date.today().isoformat():
            return 0, 0
        return int(stats.get("done", 0)), int(stats.get("skipped", 0))

    def _count_break(self, field: str):
        cfg = getattr(self.host, "cfg", None)
        if not isinstance(cfg, dict):
            return
        meta = cfg.setdefault("extensions_meta", {})
        today = _dt.date.today().isoformat()
        stats = meta.get("breaks_today", {})
        if stats.get("date") != today:
            stats = {"date": today, "done": 0, "skipped": 0}
        stats[field] = int(stats.get(field, 0)) + 1
        meta["breaks_today"] = stats
        if hasattr(self.host, "save_extensions_meta"):
            self.host.save_extensions_meta()
        self.breaks_changed.emit()

    def _break_silence(self) -> str:
        from luxai import notifications as n
        settings = self.settings("breaks")
        cfg = getattr(self.host, "cfg", {}) or {}
        try:
            start, end = int(settings.get("quiet_from", 22)), int(settings.get("quiet_to", 8))
        except (TypeError, ValueError):
            start, end = 22, 8
        if settings.get("quiet_enabled") and n.in_quiet_hours(_dt.datetime.now().hour, start, end):
            return "quiet_hours"
        if settings.get("silent_quiet_mode", True) and not cfg.get("tts_enabled", True):
            return "quiet_mode"
        if settings.get("silent_fullscreen", True) and foreground_is_fullscreen():
            return "fullscreen"
        if settings.get("silent_calls", True) and n.microphone_in_use_by_other_app():
            return "call"
        if settings.get("silent_windows_dnd", True) and n.windows_do_not_disturb():
            return "windows_dnd"
        return ""

    def _tick_breaks(self):
        from luxai import notifications as n
        now = time.monotonic()
        elapsed = now - self._last_tick
        self._last_tick = now
        # Sleep/hibernate (a long gap), a locked PC or 5 minutes away = a break.
        if elapsed > 120 or n.computer_locked() or idle_seconds() >= BREAK_IDLE_RESET:
            self.break_active = {kind: 0.0 for kind in BREAK_KINDS}
            self._break_due = []
            return
        if idle_seconds() < BREAK_ACTIVE_IDLE:  # only real work counts
            for kind in self._break_kinds():
                self.break_active[kind] += elapsed
                if self.break_active[kind] >= self._break_interval(kind) and kind not in self._break_due \
                        and kind != self._break_card_kind:
                    self._break_due.append(kind)
        if not self._break_due or self._break_card is not None:
            return
        if self._break_silence():
            self._break_silenced = True
            return
        if self._break_silenced:  # wait half a minute after the game/call ended
            self._break_silenced = False
            self._break_resume_at = now + BREAK_RESUME_DELAY
        if now < self._break_resume_at:
            return
        kind = self._break_due.pop(0)
        self._break_due = [k for k in self._break_due if k != kind]
        self.show_break_card(kind)

    def show_break_card(self, kind: str, *, test: bool = False):
        settings = self.settings("breaks")
        self._close_break_card()
        card = BreakCard(break_title(kind, self.language), break_message(kind, self.language),
                         [_tr3("Сделал", "Done", "Gata", self.language), _tr3("Отложить", "Later", "Mai târziu", self.language),
                          _tr3("Пропустить", "Skip", "Sar", self.language)])
        card.answered.connect(lambda answer, k=kind, t=test: self._break_answer(k, answer, t))
        self._break_card = card
        self._break_card_kind = kind
        card.show_in_corner()
        if settings.get("voice") and hasattr(self.host, "_queue_speech"):
            self.host._queue_speech(break_message(kind, self.language), self.language)
        return card

    def _break_answer(self, kind: str, answer: str, test: bool):
        self._close_break_card()
        if test:
            return  # «Попробовать сейчас» never touches counters or statistics
        if answer == "later":
            self.break_active[kind] = max(0.0, self._break_interval(kind) - BREAK_SNOOZE)
            return
        self.break_active[kind] = 0.0
        self._count_break("done" if answer == "done" else "skipped")

    def _close_break_card(self):
        card, self._break_card = self._break_card, None
        self._break_card_kind = ""
        if card is not None:
            try:
                card.close()
                card.deleteLater()
            except RuntimeError:
                pass

    def remind_break(self, force: bool = False) -> str:
        """Show the next enabled reminder now (used by older callers)."""
        kinds = self._break_kinds() or ["eyes"]
        kind = kinds[self._break_index % len(kinds)]
        self._break_index += 1
        if not force and self._break_silence():
            return ""
        self.show_break_card(kind, test=force)
        return break_message(kind, self.language)

    # -- clipboard history --
    @property
    def clipboard_items(self) -> list[dict]:
        """Text items, newest first (older callers and tests)."""
        return [item for item in self.clip_history.items if item["kind"] == "text"]

    def _on_clipboard(self):
        """dataChanged arrives inside a Windows clipboard notification; reading OLE data there failed
        with 0x8001010D / 0x80010108 (logs/fatal_error.log). Read a moment later, on the Qt loop."""
        if getattr(self, "_stopping", False):
            return
        if not self._clip_read_timer.isActive():
            self._clip_read_timer.start()

    def _read_clipboard(self):
        if getattr(self, "_stopping", False) or not self.enabled("clipboard_history"):
            return
        if sys.platform == "win32" and not getattr(self, "_clip_qt_only", False):
            # Audit 2 #14: read on a worker with the Win32 API; a slow clipboard owner can no longer
            # freeze the window. Qt's reader stays as the fallback.
            settings = dict(self.settings("clipboard_history"))
            self._clip_reader.submit(lambda: self._native_clipboard_job(settings))
            return
        try:
            self._read_clipboard_now()
        except Exception as error:  # a clipboard owner that fails to deliver must not break Jarvis
            self._clip_error(error)

    def _native_clipboard_job(self, settings: dict):
        """Worker thread: read, filter private/excluded copies, decode pictures; the GUI only adds text."""
        from luxai import clipboard_native as native
        from luxai import clipboard_store as store
        if store.suppressed() or getattr(self, "_stopping", False):
            return
        try:
            snapshot = native.read_clipboard()
        except Exception as error:
            self._clip_error(error)
            self._clip_native_ready.emit({"fallback": True})
            return
        if snapshot is None or store.marked_private(snapshot["formats"]):
            return
        app = store.clipboard_owner_app()
        if store.excluded_app(app, store.parse_names(settings.get("exclude_apps", ""))):
            return
        if not snapshot["text"]:
            if snapshot["image"] and settings.get("images", True):
                if not snapshot["dib"]:
                    self._clip_native_ready.emit({"fallback": True})  # too big or unusual: Qt decides
                    return
                image = QImage()
                if not image.loadFromData(native.dib_to_bmp(snapshot["dib"]), "BMP") or image.isNull():
                    self._clip_native_ready.emit({"fallback": True})
                    return
                self._encode_clip_image(image, app)
            return
        self._clip_native_ready.emit({"text": snapshot["text"], "html": snapshot["html"], "app": app})

    def _on_clip_native(self, payload):
        if getattr(self, "_stopping", False) or not self.enabled("clipboard_history"):
            return
        if payload.get("fallback"):
            try:
                self._read_clipboard_now()
            except Exception as error:
                self._clip_error(error)
            return
        value = payload.get("text", "")
        if not value or not value.strip():
            return
        if value == self._ignore_clipboard_text:
            self._ignore_clipboard_text = None
            return
        self.remember_clipboard(value, html=payload.get("html", ""), app=payload.get("app", ""))

    def _clip_error(self, error):
        try:
            folder = Path(__file__).resolve().parents[1] / "logs"
            folder.mkdir(exist_ok=True)
            with (folder / "clipboard_error.log").open("a", encoding="utf-8") as stream:
                stream.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {type(error).__name__}: {str(error)[:200]}\n")
        except OSError:
            pass

    def _read_clipboard_now(self):
        from luxai import clipboard_store as store
        if store.suppressed():
            return
        clipboard = QApplication.clipboard()
        data = clipboard.mimeData()
        if data is None:
            return
        settings = self.settings("clipboard_history")
        formats = {}
        for name in data.formats():
            if any(marker in name.casefold() for marker in ("exclude", "canincludeinclipboardhistory", "viewer ignore")):
                formats[name] = bytes(data.data(name))
        if store.marked_private(formats):
            return
        app = store.clipboard_owner_app()
        if store.excluded_app(app, store.parse_names(settings.get("exclude_apps", ""))):
            return
        if data.hasImage() and not data.hasText():
            if settings.get("images", True):
                self._remember_image(clipboard.image(), app)
            return
        value = data.text() if data.hasText() else ""
        if not value or not value.strip():
            return
        if value == self._ignore_clipboard_text:
            self._ignore_clipboard_text = None
            return
        html = data.html() if data.hasHtml() else ""
        self.remember_clipboard(value, html=html, app=app)

    def remember_clipboard(self, value: str, *, html: str = "", app: str = ""):
        if self.settings("clipboard_history").get("ignore_secrets", True) and looks_secret(value):
            return
        self.clip_history.add_text(value, html=html, app=app)
        self._clip_changed()

    def _remember_image(self, image, app: str = ""):
        """Qt path (fallback/tests): copy the picture, encode it on the single picture worker."""
        if image is None or image.isNull():
            return
        picture = image.copy()  # QImage is safe to use on another thread once copied
        self._clip_images.submit(lambda: self._encode_clip_image(picture, app))

    def _encode_clip_image(self, image, app: str = ""):
        """Worker thread. One picture at a time; a picture still waiting is replaced by a newer copy
        (audit 2 #16), so fast copies of big images cannot pile up encoders and memory."""
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice

        def png(picture) -> bytes:
            array = QByteArray()
            buffer = QBuffer(array)
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            picture.save(buffer, "PNG")
            return bytes(array)

        try:
            width, height = image.width(), image.height()
            # A huge screenshot is reduced BEFORE encoding (the store keeps at most MAX_IMAGE_BYTES anyway).
            if width * height > 12_000_000:
                image = image.scaled(4096, 4096, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            thumb = image.scaled(96, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self._clip_image_ready.emit(png(image), png(thumb), width, height, app)
        except Exception as error:
            self._clip_error(error)

    def _on_clip_image_ready(self, data: bytes, thumb: bytes, width: int, height: int, app: str):
        if getattr(self, "_stopping", False) or not self.enabled("clipboard_history"):
            return
        self.clip_history.add_image(data, thumb=thumb, size=(width, height), app=app)
        self._clip_changed()

    def _clip_changed(self):
        self._trim_clipboard()
        self._clip_save_timer.start()
        self.clipboard_changed.emit()

    def _trim_clipboard(self):
        settings = self.settings("clipboard_history")
        try:
            keep = int(settings.get("keep", "100"))
            age = int(settings.get("max_age", "0"))
        except (TypeError, ValueError):
            keep, age = 100, 0
        self.clip_history.trim(keep)
        self.clip_history.prune(age)

    def _save_clip_history(self, *, wait: bool = False):
        """Encrypt and write the history on the single save worker (it can be megabytes).

        Audit 2 #15: saves run in the order they were requested and a save still waiting is replaced
        by the newer snapshot, so an old snapshot is never written after a new one. ``wait`` (on close)
        waits — at most 8 s — for the last accepted save, never for the lock on the UI thread.
        """
        from luxai.clipboard_store import ClipboardHistory, history_file
        path = history_file()
        persist = self.settings("clipboard_history").get("persist", True) and self.enabled("clipboard_history")
        snapshot = ClipboardHistory()
        snapshot.items = [dict(item) for item in self.clip_history.items]

        def work():
            with self._clip_save_lock:
                try:
                    if persist:
                        snapshot.save(path)
                    elif path.exists():
                        path.unlink()
                except OSError as error:  # reported, and the previous file stays as it was (audit #14)
                    self._clip_error(error)

        self._clip_saver.submit(work)
        if wait:
            self._clip_saver.wait(8.0)

    def _load_clip_history_async(self):
        """Read, decrypt and decode the saved history on a worker (audit 2 #17)."""
        from luxai.clipboard_store import ClipboardHistory, history_file
        self._clip_load_generation += 1
        generation = self._clip_load_generation
        path = history_file()

        def work():
            loaded = ClipboardHistory()
            try:
                loaded.load(path)
            except (OSError, ValueError, MemoryError) as error:
                self._clip_error(error)
                return
            self._clip_history_loaded.emit(loaded, generation)

        threading.Thread(target=work, daemon=True, name="JarvisClipboardLoad").start()

    def _on_clip_history_loaded(self, loaded, generation: int):
        if generation != self._clip_load_generation or getattr(self, "_stopping", False):
            return
        # Copies made while the file was loading stay on top; saved items follow (same content once).
        known = {item.get("key") for item in self.clip_history.items}
        for item in loaded.items:
            if item.get("key") in known:
                continue
            item["id"] = self.clip_history._new_id()
            self.clip_history.items.append(item)
        self._trim_clipboard()
        self.clipboard_changed.emit()

    def clear_clipboard(self):
        self.clip_history.clear()
        self._clip_changed()

    def clear_clipboard_all(self):
        self.clip_history.clear_all()
        self._clip_changed()

    def clipboard_counts(self) -> tuple[int, int]:
        items = self.clip_history.items
        return len(items), sum(1 for item in items if item.get("pinned"))

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
        from luxai.ui_clipboard import ClipboardPopup
        self._trim_clipboard()
        target = _foreground_window()
        popup = ClipboardPopup(self.clip_history.ordered(), self.language)
        popup.picked.connect(lambda item_id, plain: self._paste_clip(item_id, plain, target))
        popup.pin_toggled.connect(self._toggle_pin)
        popup.removed.connect(self._remove_clip)
        popup.ai_requested.connect(self._clip_ai)
        self.clipboard_changed.connect(popup.refresh_from_runtime)
        popup.runtime_items = lambda: self.clip_history.ordered()
        popup.show_at_cursor()
        self._popup = popup
        return popup

    def _toggle_pin(self, value):
        """``value`` is an item id (popup) or a text (older callers)."""
        if isinstance(value, str):
            item = next((entry for entry in self.clip_history.items if entry.get("text") == value), None)
            if item is None:
                return
            value = item["id"]
        self.clip_history.toggle_pin(value)
        self._clip_changed()

    def _remove_clip(self, item_id: int):
        self.clip_history.remove(item_id)
        self._clip_changed()

    def _clip_mime(self, item: dict, plain: bool):
        from PySide6.QtCore import QMimeData
        data = QMimeData()
        if item["kind"] == "image":
            data.setImageData(QImage.fromData(item["png"]))
        else:
            data.setText(item["text"])
            if not plain and item.get("html"):
                data.setHtml(item["html"])
        return data

    def _paste_clip(self, item_id: int, plain: bool, target_hwnd: int):
        from luxai import clipboard_store as store
        item = self.clip_history.find(item_id)
        if item is None:
            return
        # The chosen item becomes the newest one; our own clipboard write is muted.
        self.clip_history.items.remove(item)
        self.clip_history.items.insert(0, item)
        self._clip_changed()
        store.suppress(1.5)
        if item["kind"] == "text":
            self._ignore_clipboard_text = item["text"]
        QApplication.clipboard().setMimeData(self._clip_mime(item, plain))
        if not target_hwnd:
            return
        self._paste_into(target_hwnd)

    def _paste_into(self, target_hwnd: int, after=None):
        """Bring the target forward and press Ctrl+V only while it is STILL the foreground window.

        Audit 2 #6: the result of the activation was ignored and the window could change during the
        120 ms wait, so private text could land in another program. Now: activation must succeed and
        the foreground is checked again right before Ctrl+V; otherwise nothing is pasted and the
        text simply stays on the clipboard. ``after`` runs only after a real paste.
        """
        def refused():
            self.notice.emit(_tr3(
                "Окно для вставки сменилось — ничего не вставлено. Текст в буфере обмена: Ctrl+V вставит его.",
                "The target window changed — nothing was pasted. The text is on the clipboard: Ctrl+V pastes it.",
                "Fereastra țintă s-a schimbat — nu am lipit nimic. Textul e în clipboard: Ctrl+V îl lipește.",
                self.language))

        def do_paste():
            if not _set_foreground(target_hwnd):
                refused()
                return
            QTimer.singleShot(120, finish)

        def finish():
            if _foreground_window() != int(target_hwnd):
                refused()
                return
            try:
                _send_paste()
            except Exception as error:
                self.notice.emit(str(error))
                return
            if after is not None:
                after()

        QTimer.singleShot(80, do_paste)

    def paste_previous(self) -> str:
        """«Вставь предыдущее» — the text copied before the current one."""
        value = self.clip_history.previous_text()
        if value is None:
            return _tr3("В истории нет предыдущей записи.", "There is no previous item in the history.",
                        "Nu există un element anterior în istoric.", self.language)
        item = next(entry for entry in self.clip_history.items if entry["kind"] == "text" and entry["text"] == value)
        target = _foreground_window()
        from luxai.screen_interact import _window_pid
        own = bool(target) and _window_pid(target) == os.getpid()
        self._paste_clip(item["id"], False, 0 if own else target)
        if own:
            return _tr3("Скопировал предыдущее в буфер обмена — Ctrl+V вставит его.",
                        "Copied the previous item to the clipboard — Ctrl+V pastes it.",
                        "Am copiat elementul anterior în clipboard — Ctrl+V îl lipește.", self.language)
        return _tr3("Вставил предыдущее.", "Pasted the previous item.", "Am lipit elementul anterior.", self.language)

    def handle_clipboard_request(self, text: str) -> str | None:
        if not self.enabled("clipboard_history"):
            return None
        phrase = " ".join(str(text or "").casefold().replace("ё", "е").split()).strip(" .!?")
        phrase = re.sub(r"^(?:джарвис|жарвис|jarvis)[,\s]+", "", phrase)
        if re.fullmatch(r"(?:вставь|вставить|вставка)\s+(?:предыдущ\w*|прошл\w*|предпоследн\w*)(?:\s+(?:скопированн\w*|текст|запис\w*))?"
                        r"|paste\s+(?:the\s+)?previous(?:\s+(?:one|item|copy))?"
                        r"|lipe[șs]te\s+(?:precedentul|anteriorul|ce\s+am\s+copiat\s+[îi]nainte)", phrase):
            return self.paste_previous()
        return None

    def _clip_ai(self, item_id: int, mode: str):
        item = self.clip_history.find(item_id)
        planner = getattr(self.host, "online_planner", None)
        if item is None or item["kind"] != "text":
            return
        if mode == "translate":
            self._clip_translate(item["text"])
            return
        if planner is None or not planner.enabled():
            self.notice.emit(_tr3("Для этого нужен облачный ИИ — подключите ключ в настройках Jarvis.",
                                  "This needs the cloud AI — add a key in Jarvis settings.",
                                  "E nevoie de AI în cloud — adaugă o cheie în setările Jarvis.", self.language))
            return
        value = item["text"]
        self.notice.emit(_tr3("Нейросеть работает…", "AI is working…", "AI lucrează…", self.language))

        def work():
            result = None
            try:
                result = planner.transform_text(value, mode)
            except Exception:
                result = None
            self._clip_ai_ready.emit(mode, result or "")

        threading.Thread(target=work, daemon=True, name="JarvisClipboardAI").start()

    def _clip_translate(self, value: str):
        """«Перевести» in the clipboard history: the offline translator, no key needed."""
        from luxai import offline_translate
        from luxai.response_language import reply_language
        from luxai.offline_translate import source_language
        from luxai.translation import translate_offline
        target = reply_language(getattr(self.host, "cfg", {}) or {})
        if source_language(value) == target:
            target = "en" if target != "en" else "ru"
        if not offline_translate.installed():
            offline_translate.download_in_background()
            self.notice.emit(_tr3("Переводчик ещё скачивается (≈640 МБ) — попробуйте через пару минут.",
                                  "The translator is still downloading (≈640 MB) — try again in a few minutes.",
                                  "Traducătorul încă se descarcă (≈640 MB) — încearcă peste câteva minute.", self.language))
            return

        def work():
            try:
                result = translate_offline(value, target)
            except Exception:
                result = None
            self._clip_ai_ready.emit("translate", result or "")

        threading.Thread(target=work, daemon=True, name="JarvisClipboardTranslate").start()

    def _on_clip_ai_ready(self, mode: str, result: str):
        from luxai import clipboard_store as store
        if not result:
            if mode == "translate":
                self.notice.emit(_tr3("Не получилось перевести этот текст.", "Could not translate this text.",
                                      "Textul nu a putut fi tradus.", self.language))
            else:
                self.notice.emit(_tr3("Нейросеть не ответила. Попробуйте ещё раз.", "The AI did not answer. Try again.",
                                      "AI nu a răspuns. Încearcă din nou.", self.language))
            return
        self.clip_history.add_text(result, app="Jarvis AI")
        self._clip_changed()
        store.suppress(1.5)
        self._ignore_clipboard_text = result
        _mute_clipboard_history()
        QApplication.clipboard().setText(result)
        self.notice.emit(_tr3("Готово — результат в буфере обмена и первым в истории. Ctrl+V вставит его.",
                              "Done — the result is on the clipboard and first in the history. Ctrl+V pastes it.",
                              "Gata — rezultatul e în clipboard și primul în istoric. Ctrl+V îl lipește.", self.language))

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
        from luxai.selection import capture_clipboard, clipboard_sequence, restore_clipboard
        clipboard = QApplication.clipboard()
        # Audit 2 #24: keep ALL formats (image, files, formatting), not only the text, and put them
        # back only while the clipboard still holds Jarvis's own write (sequence unchanged).
        previous = None
        if restore and paste and target_hwnd:
            try:
                previous = capture_clipboard(clipboard)
            except Exception:
                previous = None
        self._ignore_clipboard_text = value
        _mute_clipboard_history()
        clipboard.setText(value)
        if not paste or not target_hwnd:
            return
        ours = clipboard_sequence()

        def put_back():
            if previous is None or clipboard_sequence() != ours:
                return  # the user copied something else meanwhile: never overwrite it
            try:
                restore_clipboard(QApplication.clipboard(), previous)
            except Exception:
                pass

        self._paste_into(target_hwnd, after=lambda: QTimer.singleShot(700, put_back))

    # -- read aloud --
    def reading_language(self) -> str:
        from luxai.response_language import reply_language
        choice = self.settings("read_aloud").get("translate_to", "auto")
        if choice in ("ru", "ro", "en"):
            return choice
        return reply_language(getattr(self.host, "cfg", {}) or {})

    def read_text(self, text: str, *, wait: bool = False):
        """Read ``text`` aloud in pieces, translating each piece first when needed."""
        from luxai import translation
        settings = self.settings("read_aloud")
        target = self.reading_language()
        chunks = translation.split_chunks(text)
        if not chunks:
            return
        translate = bool(settings.get("translate", True)) and translation.needs_translation(text, target)
        self._reading_generation += 1
        generation = self._reading_generation
        self._reading = True
        def translate_piece(piece):
            try:
                return translation.translate_offline(piece, target)
            except Exception:
                return None

        def work():
            failed = False
            for piece in chunks:
                if generation != self._reading_generation:
                    return  # stopped by a second press or a new reading
                language = target
                if not translate:
                    # Read it in its own language (an English text with an English voice).
                    own = translation.text_language(piece)
                    language = own if own in ("ru", "ro", "en") else target
                if translate:
                    translated = translate_piece(piece)
                    if translated:
                        piece = translated
                    else:
                        failed = True
                        from luxai.response_language import detect_language
                        language = translation.text_language(piece) if translation.text_language(piece) in ("ru", "ro", "en") \
                            else detect_language(piece, target)
                # Do not overrun the speech queue (8 items) with a long text.
                queue = getattr(self.host, "_speech_queue", None)
                while queue is not None and queue.qsize() >= 5 and generation == self._reading_generation:
                    time.sleep(0.2)
                if generation != self._reading_generation:
                    return
                self._read_chunk.emit(piece, language, generation)
            if failed:
                self._read_notice.emit(_tr3("Перевод недоступен — читаю оригинал.",
                                            "Translation unavailable — reading the original.",
                                            "Traducerea nu e disponibilă — citesc originalul.", self.language))

        if wait:
            work()
        else:
            threading.Thread(target=work, daemon=True, name="JarvisReadAloud").start()
        QTimer.singleShot(max(4000, len(text) * 70), lambda g=generation: g == self._reading_generation
                          and setattr(self, "_reading", False))

    def _on_read_chunk(self, text, language, generation):
        if generation == self._reading_generation and hasattr(self.host, "_queue_speech"):
            self.host._queue_speech(text, language)

    def read_selection(self):
        settings = self.settings("read_aloud")
        if self._reading and settings.get("second_press_stops", True):
            self._reading = False
            self._reading_generation += 1  # stop translating/queueing the rest
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

        from luxai.selection import clipboard_sequence, selected_text_by_automation

        def give_up():
            # No copy at all (some Electron apps ignore a synthetic Ctrl+C):
            # read the selection through Windows UI Automation instead.
            if saved is not None and clipboard_sequence() == before:
                pass  # nothing changed, nothing to restore
            text_found = selected_text_by_automation(hwnd)
            if text_found:
                read(text_found)
                return
            from luxai.selection import admin_window_message, window_runs_as_admin
            if window_runs_as_admin(hwnd):
                self._notify(admin_window_message(hwnd))  # Windows blocks Jarvis there
                return
            try:
                finish_selected_copy(clipboard, hwnd, before, saved)
            except Exception as error:
                self._notify(str(error))

        def read(selected):
            limit = int(settings.get("max_chars", 4000))
            selected = selected.split("\n[Выделение сокращено", 1)[0][:limit]
            self.read_text(selected)

        def finish(attempt=0):
            # Check at once and then often; Electron apps (Discord) may need ~1-2 s.
            if clipboard_sequence() == before:
                if attempt == 12:
                    from luxai import keys
                    keys.press("ctrl", "insert", interval=0.05)  # the other copy shortcut
                if attempt < 45:
                    QTimer.singleShot(40, lambda: finish(attempt + 1))
                    return
                give_up()
                return
            try:
                selected = finish_selected_copy(clipboard, hwnd, before, saved)
            except Exception as error:
                self._notify(str(error))
                return
            read(selected)

        QTimer.singleShot(20, finish)

    # -- screenshots --
    def take_screenshot(self, window: bool = False) -> Path | None:
        settings = self.settings("screenshots")
        to_clipboard, to_file = bool(settings.get("to_clipboard", True)), bool(settings.get("to_file", True))
        if not (to_clipboard or to_file):
            self._notify(_tr3("Снимок не сделан: включите «В буфер обмена» или «Сохранять в папку».",
                              "No screenshot: turn on «To clipboard» or «Save to folder».",
                              "Nicio captură: activează „În clipboard” sau „Salvează în folder”.", self.language))
            return None
        region = _foreground_rect() if window else None
        if window and not region:
            # None means «whole screen» to capture_png: a window shot must never become a full-screen
            # picture (with everything else on it) — audit #37.
            self._notify(_tr3("Не удалось определить активное окно — снимок не сделан.",
                              "Could not find the active window — no screenshot taken.",
                              "Fereastra activă nu a putut fi găsită — nu am făcut captura.", self.language))
            return None
        try:
            pixels, width, height = capture_raw(region)
            # The raw pixels become the picture directly (audit 2 #36): no PNG encode + decode on the
            # UI thread for the clipboard; the file is encoded and written on a worker.
            image = QImage(pixels, width, height, width * 4, QImage.Format.Format_RGB32).copy()
        except Exception as error:
            self._notify(_tr3("Не удалось сделать снимок: ", "Screenshot failed: ", "Captura a eșuat: ", self.language) + str(error))
            return None
        copied = False
        if to_clipboard and not image.isNull():
            self._ignore_clipboard_text = None
            QApplication.clipboard().setImage(image)
            copied = True
        if to_file:
            folder = screenshots_folder(settings.get("folder", ""))
            name = _dt.datetime.now().strftime("Screenshot %Y-%m-%d %H-%M-%S.png")

            def work():
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                    saved = unique_path(folder / name)
                    if not image.save(str(saved), "PNG"):
                        saved.unlink(missing_ok=True)
                        raise OSError("PNG")
                    self._screenshot_done.emit(str(saved), copied, "")
                except OSError as error:
                    self._screenshot_done.emit("", copied, str(error))

            threading.Thread(target=work, daemon=True, name="JarvisScreenshotSave").start()
            return None
        self._on_screenshot_done("", copied, "")
        return None

    def _on_screenshot_done(self, saved: str, copied: bool, error: str):
        if error:
            self._notify(error)
        places = ([saved] if saved else []) + ([_tr3("буфер обмена", "clipboard", "clipboard", self.language)]
                                               if copied else [])
        if not places:
            self._notify(_tr3("Снимок не сохранён.", "The screenshot was not saved.", "Captura nu a fost salvată.",
                              self.language))
            return None
        self._notify(_tr3("Снимок сохранён: ", "Screenshot saved: ", "Captură salvată: ", self.language)
                     + " + ".join(places))

    def open_screenshots_folder(self):
        folder = screenshots_folder(self.settings("screenshots").get("folder", ""))
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(folder))  # noqa: S606 - opens our own output folder

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
        """Scan and move on a worker (audit 2 #19): a big folder, a slow disk or the Recycle Bin can no
        longer freeze the window. The day is marked done only AFTER a run without errors; with errors
        it is tried again at the next hourly check."""
        if not (self.enabled("downloads_cleanup") and self.settings("downloads_cleanup").get("auto")):
            return
        if self._auto_cleanup_running:
            return
        cfg = getattr(self.host, "cfg", None)
        today = _dt.date.today().isoformat()
        meta = cfg.get("extensions_meta", {}) if isinstance(cfg, dict) else {}
        if isinstance(meta, dict) and meta.get("downloads_last_run") == today:
            return
        self._auto_cleanup_running = True

        def work():
            try:
                _folder, steps = self._cleanup_plan()
                result = run_cleanup(steps) if steps else (0, 0, [])
            except Exception as error:
                result = (0, 0, [f"{type(error).__name__}: {error}"])
            self._auto_cleanup_done.emit(result, today)

        threading.Thread(target=work, daemon=True, name="JarvisDownloadsCleanup").start()

    def _on_auto_cleanup_done(self, result, day: str):
        self._auto_cleanup_running = False
        if getattr(self, "_stopping", False):
            return
        moved, trashed, errors = result
        if not errors:
            cfg = getattr(self.host, "cfg", None)
            if isinstance(cfg, dict):
                cfg.setdefault("extensions_meta", {})["downloads_last_run"] = day
                if hasattr(self.host, "save_extensions_meta"):
                    self.host.save_extensions_meta()
        if moved or trashed or (errors and getattr(self, "_cleanup_error_day", "") != day):
            if errors:
                self._cleanup_error_day = day  # the same failure is reported once a day, not every hour
            self._report_cleanup((moved, trashed, errors))


def _mute_clipboard_history() -> None:
    """Jarvis's own temporary clipboard writes never enter the history."""
    from luxai.clipboard_store import suppress
    suppress(1.5)


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
