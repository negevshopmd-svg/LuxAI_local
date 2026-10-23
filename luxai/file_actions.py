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

# Placement is a clause, not any mention of "documents" in a filename. Keep
# this shared by open and rename so a requested folder never becomes part of
# the basename or silently redirects an operation to Desktop.
_FILE_LOCATION_SUFFIX = re.compile(
    r"\s+(?:"
    r"(?P<desktop>на\s+рабоч(?:ем|ий)\s+стол(?:е|а)|"
    r"с\s+рабоч(?:его|ем)\s+стол(?:а|е)|"
    r"на\s+(?:десктопе|desktop)|с\s+(?:десктопа|desktop)|"
    r"(?:on|from)\s+(?:the\s+)?desktop|(?:de\s+pe|pe|din)\s+(?:desktop|birou))|"
    r"(?P<documents>в\s+(?:папке\s+)?(?:документах|документы)|"
    r"из\s+(?:папки\s+)?документов|"
    r"(?:in|from)\s+(?:the\s+)?documents(?:\s+folder)?|"
    r"(?:din|în|in)\s+(?:(?:folderul|dosarul)\s+)?documente)|"
    r"(?P<downloads>в\s+(?:папке\s+)?(?:загрузках|загрузки)|"
    r"из\s+(?:папки\s+)?загрузок|"
    r"(?:in|from)\s+(?:the\s+)?downloads(?:\s+folder)?|"
    r"(?:din|în|in)\s+(?:(?:folderul|dosarul)\s+)?(?:descărcări|descarcari))"
    r")\s*[.!?]*$",
    flags=re.IGNORECASE,
)


def split_file_location(text: str) -> tuple[str, str]:
    """Separate a supported trailing placement clause from a spoken name."""
    match = _FILE_LOCATION_SUFFIX.search(text)
    if match is None:
        return text, "desktop"
    return text[:match.start()].rstrip(), match.lastgroup


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
    # Whisper can transcribe the spoken TXT extension in Cyrillic.
    # These are explicit transcription variants, not arbitrary extensions.
    if not is_folder:
        value = re.sub(r"(?i)\.(?:текст|тексте|тхт|тиэксти)$", ".txt", value)
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
    text, place = split_file_location(str(text or "").strip())
    lowered = text.casefold()

    # Allow bounded offline rename/Recycle Bin workflows, with a real
    # last-created file context. If the command is incomplete, ask for a
    # filename rather than claiming a write happened.
    rename = re.search(
        r"\b(?:переименуй|переименовать|переименуйте|rename|redenumește|redenumeste)\b\s+(.+)",
        text, flags=re.IGNORECASE,
    )
    if rename:
        body = re.sub(
            r"^(?:файл|файлик|file|fișierul|fisierul|fișier|fisier)\s+",
            "", rename.group(1), flags=re.IGNORECASE,
        )
        match = re.fullmatch(
            r'''("[^"]+"|'[^']+'|«[^»]+»|“[^”]+”|.+?)\s+(?:в|на|как|to|în|in)\s+(.+?)\s*[.!?]*''',
            body, flags=re.IGNORECASE,
        )
        if not match:
            return None
        original, destination = match.groups()
        original = original.strip(" '\"«»“”")
        # Only a genuine pronoun can refer to the last created item. An
        # explicitly named source must never be replaced by that context.
        pronouns = {
            "его", "её", "ее", "это", "этот", "этот файл", "созданный файл",
            "последний файл", "it", "this file", "that file", "acesta", "acest fișier",
        }
        try:
            if not original:
                return None
            source = "@last" if original.casefold() in pronouns else safe_name(original, is_folder=True)
            target = safe_name(destination.strip(" .,!?:"))
        except ValueError:
            return None
        return {
            "action": "rename_file", "source": source, "target": target,
            "location": place, "content": "",
        }

    if re.search(r"\b(?:удали|удалить|сотри|удалите|delete)\b", lowered):
        match = re.search(
            r"\b(?:файл|file)\s+([A-Za-zА-Яа-яЁё0-9_.() -]{1,100})",
            text, flags=re.IGNORECASE,
        )
        source = "@last"
        if match:
            candidate = re.split(
                r"\s+(?:с|из)\s+рабоч(?:его|ем)\s+стол(?:а|е)",
                match.group(1), maxsplit=1, flags=re.IGNORECASE,
            )[0].strip(" .,!?")
            if candidate.casefold() not in {"его", "этот", "новый", ""}:
                try:
                    source = safe_name(candidate, is_folder=True)
                except ValueError:
                    return None
        return {
            "action": "trash_file", "source": source, "target": "",
            "location": place, "content": "",
        }

    if re.search(r"(?:что|какие)\s+(?:есть\s+)?(?:файлы|файлов|папки)\b|(?:покажи|список)\s+(?:мне\s+)?(?:файлы|файлов|папки)", lowered):
        return {"action": "list_files", "target": "", "location": place, "content": ""}
    if not re.search(r"\b(?:создай|создать|сделай|создавай|create|creează|creeaza)\b", lowered):
        return None
    matched = re.search(r"\b(?:файл|файлик|file|fișier|fisier|папку|папка|folder|директорию)\b", lowered)
    if matched is None:
        return None
    kind = "create_folder" if matched.group(0) in ("папку", "папка", "folder", "директорию") else "create_file"
    tail = text[matched.end():].strip().strip(" .,!?:;")
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


def resolve_user_item(name: str, location="desktop", home=None) -> Path:
    """Resolve an existing top-level file using a basename, never a path."""
    directory = user_folder(location, home=home)
    if not directory.is_dir():
        raise FileNotFoundError(f"Папка {location} отсутствует")
    # safe_name() may add .txt to an extensionless file; this is appropriate
    # for new files, not existing folders. Check both exact names safely.
    checked = safe_name(name, is_folder=True)
    path = directory / checked
    if not path.exists():
        raise FileNotFoundError(f"Не найдено: {checked}")
    if path.is_symlink():
        raise ValueError("Ссылки и ярлыки файлов не изменяются")
    return path


def rename_user_item(source: str, destination: str, location="desktop", home=None) -> Path:
    """Rename only within the same allowed user directory; never overwrite."""
    original = resolve_user_item(source, location, home)
    new_name = safe_name(destination, is_folder=original.is_dir())
    target = original.parent / new_name
    if target == original:
        raise ValueError("Новое имя совпадает с текущим")
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Файл «{target.name}» уже существует")
    original.rename(target)
    if not target.exists() or original.exists():
        raise OSError("Переименование не подтверждено")
    return target


def trash_user_item(name: str, location="desktop", home=None) -> str:
    """Move one user-visible file to Recycle Bin, never permanently delete."""
    original = resolve_user_item(name, location, home)
    if original.is_dir():
        raise ValueError("Удаление папок голосом отключено")
    from send2trash import send2trash
    saved_name = original.name
    send2trash(str(original))
    if original.exists():
        raise OSError("Windows не подтвердил перемещение в корзину")
    return saved_name
