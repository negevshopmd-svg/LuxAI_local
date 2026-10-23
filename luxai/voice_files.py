"""Open a specifically named, existing Desktop/Documents/Downloads file by voice.

No recursive search, arbitrary model-supplied paths or shell execution.
Names are matched case-insensitively against REAL top-level filenames.
Executable and script files require an explicit approval, even if ordinary
document opens are configured to run without prompts.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys

from luxai.fast_intents import strip_wake_name
from luxai.file_actions import user_folder, split_file_location

OPEN_FILE_RE = re.compile(
    r"^\s*(?:открой|откроет|откроешь|открывай|открыть|откройте|запусти|открой-ка|"
    r"open|deschide)\s+"
    r"(?:(?:пожалуйста|мне|этот|мой|мою|my|te rog)\s+)*"
    r"(?:файл|файлик|документ|папку|папка|file|document|"
    r"fișierul|fisierul|fișier|fisier|folder)\s+(.+?)\s*$",
    flags=re.IGNORECASE,
)
# Shell/script files and Windows shortcuts may perform arbitrary operations.
# Such files cannot be opened silently, even if the user asks for no prompts.
EXECUTABLE_SUFFIXES = {
    ".exe", ".com", ".bat", ".cmd", ".ps1", ".psm1", ".vbs",
    ".vbe", ".js", ".jse", ".wsf", ".wsh", ".msi", ".msp",
    ".scr", ".hta", ".lnk", ".url", ".reg", ".jar", ".py", ".pyw",
}
# Readable files Windows can open normally; refuse unrecognized formats
# instead of implicitly executing them.
DOCUMENT_SUFFIXES = {
    ".txt", ".md", ".pdf", ".doc", ".docx", ".odt", ".rtf",
    ".xlsx", ".xls", ".csv", ".ppt", ".pptx", ".png", ".jpg",
    ".jpeg", ".gif", ".bmp", ".webp", ".mp3", ".wav", ".mp4",
    ".mkv", ".avi", ".json", ".xml", ".log", ".html", ".htm",
    ".zip", ".7z",
}


def parse_open_user_file(text: str) -> dict | None:
    """Match explicit "open file X on Desktop", not "open Explorer"."""
    cleaned = strip_wake_name(text).strip()
    match = OPEN_FILE_RE.fullmatch(cleaned)
    if not match:
        return None
    name, location = split_file_location(match.group(1).strip())
    name = name.strip(" \t.,!?\"'«»“”")
    # Optional "in Word": this is not part of the file name; association
    # is decided by Windows after opening the existing document.
    name = re.sub(
        r"\s+в\s+(?:ворде|word|ворд)\s*$", "", name, flags=re.I
    ).strip(" \t.,!?\"'«»“”")
    if not name or len(name) > 180:
        return None
    if any(char in name for char in "\\/:*?\"<>|") or ".." in name:
        return None
    if re.search(r"[\x00-\x1f]", name):
        return None
    return {"action": "open_user_file", "target": name, "location": location}


def resolve_named_file(name: str, location="desktop", *, home=None) -> Path:
    """Return an exact, unique local file (or folder) with no traversal."""
    if location not in ("desktop", "documents", "downloads"):
        raise ValueError("Разрешены только Desktop, Documents и Downloads.")
    if not isinstance(name, str) or not 1 <= len(name) <= 180:
        raise ValueError("Назовите файл.")
    if any(c in name for c in "\\/:*?\"<>|") or ".." in name or re.search(r"[\x00-\x1f]", name):
        raise ValueError("Недопустимое имя файла.")
    directory = user_folder(location, home=home)
    if not directory.is_dir():
        raise FileNotFoundError(f"Папка {location} не найдена.")
    matches = []
    for path in directory.iterdir():
        if path.is_symlink():
            continue
        if path.name.casefold() == name.casefold():
            matches.append(path)
    if not matches and "." not in name:
        for path in directory.iterdir():
            if not path.is_file() or path.is_symlink():
                continue
            if path.stem.casefold() == name.casefold():
                matches.append(path)
    if len(matches) > 1:
        alternatives = ", ".join(sorted(p.name for p in matches)[:8])
        raise ValueError(
            f"Найдено несколько файлов с таким именем: {alternatives}. "
            "Уточните расширение."
        )
    if not matches:
        raise FileNotFoundError(
            f"Файл «{name}» не найден в {location}. "
            "Проверьте точное название или укажите расширение."
        )
    candidate = matches[0]
    if candidate.is_file() and candidate.suffix.casefold() not in (
        EXECUTABLE_SUFFIXES | DOCUMENT_SUFFIXES
    ):
        raise ValueError(
            "Неизвестный тип файла. Откройте его вручную "
            "или выберите в редакторе команд."
        )
    return candidate


def open_user_file(
    target: str, location="desktop", *,
    confirm=None, home=None,
) -> tuple[bool, str]:
    try:
        path = resolve_named_file(target, location, home=home)
    except (FileNotFoundError, OSError, ValueError) as exc:
        return False, str(exc)
    if sys.platform != "win32":
        return False, "Открытие файлов голосом поддерживается только в Windows."
    if path.is_file() and path.suffix.casefold() in EXECUTABLE_SUFFIXES:
        if confirm is None or not confirm(
            "⚠ Выполняемый файл или скрипт может изменять систему. "
            f"Запустить «{path.name}»? Полный путь: {path}"
        ):
            return False, "Запуск исполняемого файла отменён."
    try:
        # os.startfile invokes the documented Windows default file association,
        # not a shell or untrusted CMD string. It does not report app load.
        os.startfile(str(path))
    except OSError as exc:
        return False, f"Windows не смог открыть «{path.name}»: {exc}"
    return True, (
        f"Передал Windows запрос открыть «{path.name}» ({location}). "
        "Проверьте, что документ открылся."
    )
