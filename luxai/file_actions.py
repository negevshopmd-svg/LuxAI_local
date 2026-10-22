"""Small, safe filesystem toolkit for voice commands.

No arbitrary shell, no delete/overwrite, no absolute user/model supplied paths.
Writes are restricted to top-level Desktop/Documents/Downloads (or the user's
OneDrive Desktop if Windows redirected it). Every write requires approval in
LocalAgent; filename validation is rechecked at the filesystem boundary.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

ALLOWED_LOCATIONS = ("desktop", "documents", "downloads")
ALLOWED_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".log"}
DEFAULT_FILE = "Новый файл.txt"
DEFAULT_FOLDER = "Новая папка"


def user_folder(location="desktop", home: Path | None = None) -> Path:
    location = str(location or "").lower()
    if location not in ALLOWED_LOCATIONS:
        raise ValueError("Unsupported folder")
    home = Path(home) if home is not None else Path.home()
    local_name = {"desktop": "Desktop", "documents": "Documents", "downloads": "Downloads"}[location]
    primary = home / local_name
    if primary.is_dir() or location == "downloads":
        return primary
    if home == Path.home():
        for env in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            root = os.getenv(env)
            if root and (Path(root) / local_name).is_dir():
                return Path(root) / local_name
    return primary


def safe_name(name: str, is_folder=False) -> str:
    value = str(name or "").strip().strip("'\"«»“”")
    if not value:
        value = DEFAULT_FOLDER if is_folder else DEFAULT_FILE
    if not is_folder and "." not in value:
        value += ".txt"
    if (
        len(value) > 100 or value in (".", "..")
        or any(ord(c) < 32 or c in '/\\<>:"|?*' for c in value)
        or value.endswith((" ", "."))
        or value.casefold().split(".")[0] in {
            "con", "prn", "aux", "nul",
            *(f"com{i}" for i in range(1, 10)),
            *(f"lpt{i}" for i in range(1, 10)),
        }
    ):
        raise ValueError("Unsafe filename")
    if not is_folder and Path(value).suffix.casefold() not in ALLOWED_EXTENSIONS:
        raise ValueError("Only .txt, .md, .csv, .json and .log files are supported")
    return value


def _unique_name(directory: Path, name: str) -> Path:
    target = directory / name
    if not target.exists():
        return target
    # Never replace an existing file or folder.
    root, suffix = (target.stem, target.suffix) if target.suffix else (target.name, "")
    for n in range(2, 1000):
        candidate = directory / f"{root} ({n}){suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError("Too many similarly named files")


def create_user_item(action: str, name: str = "", location="desktop", content="", home=None) -> Path:
    if action not in {"create_file", "create_folder"}:
        raise ValueError("Unsupported file operation")
    directory = user_folder(location, home=home)
    # Create destination folder as needed; cannot escape the chosen root.
    directory.mkdir(parents=True, exist_ok=True)
    valid_name = safe_name(name, is_folder=action == "create_folder")
    if directory.is_symlink():
        raise ValueError("Destination is a symlink")
    target = _unique_name(directory, valid_name)
    if target.is_symlink():
        raise ValueError("Target is a symlink")
    if action == "create_folder":
        target.mkdir(exist_ok=False)
    else:
        content = str(content or "")
        if len(content) > 4096:
            raise ValueError("Text is too long")
        with target.open("x", encoding="utf-8") as output:
            output.write(content)
    return target


def list_user_items(location="desktop", home=None) -> list[str]:
    directory = user_folder(location, home=home)
    if not directory.is_dir():
        return []
    entries = sorted(directory.iterdir(), key=lambda p: p.name.casefold())
    return [entry.name + ("/" if entry.is_dir() else "") for entry in entries[:25]]


def parse_file_intent(text: str) -> dict | None:
    """Recognize short Russian filesystem requests without loading a model."""
    text = str(text or "").strip()
    lowered = text.casefold()
    place = "desktop"
    if re.search(r"(?:документ[а-я]*|documents|documente)", lowered):
        place = "documents"
    elif re.search(r"(?:загрузк[а-я]*|downloads|descărcări)", lowered):
        place = "downloads"
    if re.search(r"(?:рабоч(?:ем|ий) стол(?:е|а)|desktop|десктоп)", lowered):
        place = "desktop"

    if re.search(r"(?:что|какие)\s+(?:есть\s+)?(?:файлы|файлов|папки)\b|(?:покажи|список)\s+(?:мне\s+)?(?:файлы|файлов|папки)", lowered):
        return {"action": "list_files", "target": "", "location": place, "content": ""}
    if not re.search(r"\b(?:создай|создать|сделай|создавай|create|creează|creeaza)\b", lowered):
        return None
    matched = re.search(r"\b(?:файл|файлик|file|fișier|fisier|папку|папка|folder|директорию)\b", lowered)
    if matched is None:
        return None
    kind = "create_folder" if matched.group(0) in ("папку", "папка", "folder", "директорию") else "create_file"
    tail = text[matched.end():].strip()
    # A missing name with only a placement clause uses a harmless default.
    tail = re.sub(
        r"^(?:на\s+рабоч(?:ем|ий)\s+стол(?:е|а)|в\s+(?:папке\s+)?(?:документах|загрузках)|on\s+(?:the\s+)?desktop)\s*$",
        "", tail, flags=re.IGNORECASE,
    )
    # Remove common placement suffix. A name can contain spaces, e.g. Мой отчёт.
    tail = re.split(
        r"\s+(?:на\s+рабоч(?:ем|ий)\s+стол(?:е|а)|в\s+(?:папке\s+)?(?:документ[а-я]*|загрузк[а-я]*)|on\s+(?:the\s+)?desktop)\b",
        tail, maxsplit=1, flags=re.IGNORECASE,
    )[0].strip()
    # Do not fabricate a file name from instructions containing a freeform path.
    tail = re.sub(r"^(?:с\s+именем|под\s+именем|с\s+названием|по\s+имени)\s+", "", tail, flags=re.IGNORECASE)
    tail = tail.strip(" '\"«».,!?")
    if not tail or tail in ("на", "в"):
        tail = DEFAULT_FOLDER if kind == "create_folder" else DEFAULT_FILE
    try:
        name = safe_name(tail, is_folder=kind == "create_folder")
    except ValueError:
        return None
    return {"action": kind, "target": name, "location": place, "content": ""}
