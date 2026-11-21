"""Guided installation of the Jarvis browser extension (0.4.2z+).

Chrome installs extensions without clicks only from the Chrome Web Store; until the extension is
published there, the user loads the shipped folder once («Load unpacked»). This window opens the
browser's extensions page and Explorer, copies the folder path for the file dialog, explains the three
clicks and turns green by itself as soon as the extension reports to Jarvis.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

FOLDER = Path(__file__).resolve().parents[1] / "browser_extension"
# The Chrome Web Store ID once the extension is published there (tests/build_extension_package.py):
# then installing is one click on its store page instead of developer mode.
STORE_ID = ""


def _t(language: str, ru: str, en: str, ro: str) -> str:
    return {"ru": ru, "en": en, "ro": ro}.get(language, ru)


def find_browser() -> tuple[str, Path] | None:
    """("chrome" | "edge", executable) — Chrome first, the user asked for Chrome."""
    if sys.platform != "win32":
        return None
    roots = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
             os.environ.get("LOCALAPPDATA", "")]
    for name, relative in (("chrome", r"Google\Chrome\Application\chrome.exe"),
                           ("edge", r"Microsoft\Edge\Application\msedge.exe")):
        for root in roots:
            if root and (Path(root) / relative).is_file():
                return name, Path(root) / relative
    return None


def extensions_address(name: str) -> str:
    return f"{name}://extensions"


def open_extensions_page() -> str:
    """Bring the user's browser forward (the store page once published); returns the browser name.

    Chrome refuses chrome:// addresses given on its command line (a new empty tab opens instead), so the
    address is put on the clipboard and the guide says «paste it in the address bar»."""
    found = find_browser()
    if found is None:
        return ""
    name, exe = found
    arguments = [str(exe)]
    if STORE_ID:
        arguments.append(f"https://chromewebstore.google.com/detail/{STORE_ID}")
    else:
        copy_text(extensions_address(name))
        arguments.append("--new-window")
    try:
        subprocess.Popen(arguments, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        return ""
    return name


def copy_text(value: str) -> None:
    from luxai.clipboard_store import suppress
    suppress(1.5)  # Jarvis's own copy never enters the clipboard history
    QApplication.clipboard().setText(value)


def copy_folder_path() -> None:
    copy_text(str(FOLDER))


class ExtensionInstallDialog(QDialog):
    def __init__(self, language: str, parent=None, browser: str | None = None):
        super().__init__(parent)
        self.language = language
        if browser is None:
            found = find_browser()
            browser = found[0] if found else "chrome"
        self.browser = browser
        name = "Edge" if browser == "edge" else "Chrome"
        address = extensions_address(browser)
        self.setWindowTitle("Jarvis")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMinimumWidth(520)
        lang = language
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(10)
        title = QLabel(_t(lang, f"Расширение Jarvis для {name}", f"Jarvis extension for {name}", f"Extensia Jarvis pentru {name}"))
        title.setStyleSheet("font-size:20px; font-weight:800;")
        layout.addWidget(title)
        intro = QLabel(_t(
            lang,
            "С ним субтитры фильма в браузере готовятся заранее и каждое слово появляется точно вовремя. "
            f"{name} уже открыт — нужно несколько кликов, один раз:",
            "With it, film captions in the browser are prepared in advance and every word appears exactly on time. "
            f"{name} is already open — a few clicks, once:",
            "Cu ea, subtitrările filmelor din browser se pregătesc din timp și fiecare cuvânt apare exact la timp. "
            f"{name} e deja deschis — câteva clicuri, o singură dată:"))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        steps = [
            _t(lang, f"1. В адресной строке {name} вставьте (Ctrl+V) и нажмите Enter: {address} "
                     "(адрес уже скопирован).",
               f"1. In {name}'s address bar paste (Ctrl+V) and press Enter: {address} (already copied).",
               f"1. În bara de adrese din {name} lipește (Ctrl+V) și apasă Enter: {address} (adresa e deja copiată)."),
            _t(lang, "2. Справа вверху включите «Режим разработчика».",
               "2. Top right: turn on «Developer mode».",
               "2. Dreapta sus: pornește „Modul dezvoltator” (Developer mode)."),
            _t(lang, f"3. Нажмите «Скопировать путь» здесь, затем в {name} — «Загрузить распакованное расширение».",
               f"3. Click «Copy the path» here, then «Load unpacked» in {name}.",
               f"3. Apasă aici „Copiază calea”, apoi în {name} „Încarcă extensia neîmpachetată” (Load unpacked)."),
            _t(lang, "4. В окне выбора папки вставьте путь (Ctrl+V) в адресную строку вверху, нажмите Enter, "
                     "затем «Выбор папки».",
               "4. In the folder window, paste the path (Ctrl+V) into the address bar at the top, press Enter, "
               "then «Select Folder».",
               "4. În fereastra de alegere a dosarului, lipește calea (Ctrl+V) în bara de sus, apasă Enter, "
               "apoi „Selectare folder”."),
        ]
        if STORE_ID:
            steps = [_t(lang, "На открывшейся странице нажмите «Установить».", "On the page that opened, click «Add to Chrome».",
                        "Pe pagina deschisă apasă „Adaugă în Chrome”.")]
        for step in steps:
            label = QLabel(step)
            label.setWordWrap(True)
            layout.addWidget(label)
        path = QLabel(str(FOLDER))
        path.setVisible(not STORE_ID)
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path.setStyleSheet("font-family:Consolas,monospace; padding:6px; border-radius:6px; background:rgba(127,127,127,0.15);")
        path.setWordWrap(True)
        layout.addWidget(path)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.copy_button = QPushButton(_t(lang, "Скопировать путь", "Copy the path", "Copiază calea"))
        self.copy_button.clicked.connect(copy_folder_path)
        self.open_button = QPushButton(_t(lang, f"Открыть {name} ещё раз", f"Open {name} again",
                                          f"Deschide {name} din nou"))
        self.open_button.clicked.connect(self.start)
        self.close_button = QPushButton(_t(lang, "Закрыть", "Close", "Închide"))
        self.close_button.setObjectName("Primary")
        self.close_button.clicked.connect(self.close)
        row.addWidget(self.copy_button)
        row.addWidget(self.open_button)
        row.addStretch(1)
        row.addWidget(self.close_button)
        layout.addLayout(row)
        self.done_already = False
        self._waiting()

    def _waiting(self):
        self.status.setStyleSheet("color:#e5bd69; font-weight:600;")
        self.status.setText(_t(self.language, "Жду расширение… (после добавления это окно само станет зелёным)",
                               "Waiting for the extension… (this window turns green by itself once it is added)",
                               "Aștept extensia… (după adăugare, fereastra devine verde singură)"))

    def start(self):
        """Open the browser with the extensions address on the clipboard (the folder as a fallback)."""
        browser = open_extensions_page()
        if not browser:
            self.status.setStyleSheet("color:#e5484d; font-weight:600;")
            self.status.setText(_t(self.language, "Chrome или Edge не найден или не запустился. Установите Chrome и повторите.",
                                   "Chrome or Edge was not found or did not start. Install Chrome and try again.",
                                   "Chrome sau Edge nu a fost găsit sau nu a pornit. Instalează Chrome și încearcă din nou."))
            if sys.platform == "win32":
                os.startfile(str(FOLDER))  # noqa: S606 - our own folder
        return browser

    def connected(self, info: dict | None = None):
        self.done_already = True
        browser = "Edge" if (info or {}).get("browser") == "edge" else "Chrome"
        self.status.setStyleSheet("color:#3ecf8e; font-weight:700;")
        self.status.setText(_t(self.language,
                               f"✓ Готово! Расширение работает в {browser}. Включите фильм — субтитры появятся заранее.",
                               f"✓ Done! The extension works in {browser}. Play a film — the captions will be ready in advance.",
                               f"✓ Gata! Extensia funcționează în {browser}. Pornește un film — subtitrările vor fi gata din timp."))
        self.copy_button.hide()
        self.open_button.hide()
