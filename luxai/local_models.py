"""Discover local GGUF files without persisting another PC's absolute paths."""
from __future__ import annotations

from pathlib import Path, PureWindowsPath

ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "models"
GGUF_MAGIC = b"GGUF"
MIN_GGUF_BYTES = 1_048_576


def available_models(directory: Path | None = None) -> list[dict]:
    directory = Path(directory) if directory is not None else MODELS_DIR
    if not directory.is_dir():
        return []
    entries: list[dict] = []
    # Allow organized subfolders, but do not follow directory or file symlinks.
    for path in sorted(directory.rglob("*"), key=lambda item: str(item).casefold()):
        if path.suffix.casefold() != ".gguf" or not path.is_file() or path.is_symlink():
            continue
        try:
            size = path.stat().st_size
            with path.open("rb") as file:
                valid = size >= MIN_GGUF_BYTES and file.read(4) == GGUF_MAGIC
        except OSError:
            continue
        entries.append({
            "path": str(path.resolve()),
            "name": str(path.relative_to(directory)).replace("\\", "/"),
            "bytes": size,
            "valid": bool(valid),
        })
    return entries


def resolve_model_path(configured: str, *, directory: Path | None = None) -> Path | None:
    """Resolve a moved model only when its name uniquely identifies a file.

    Never silently choose the first of two similarly named GGUF models.
    """
    if not configured:
        return None
    directory = Path(directory) if directory is not None else MODELS_DIR
    candidate = Path(str(configured)).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    local = directory / candidate
    if local.is_file():
        return local.resolve()
    # Old Windows paths must remain readable when validating on macOS/Linux
    # or after the files are moved from another machine.
    original_name = (PureWindowsPath(configured).name if "\\" in configured
                     else candidate.name)
    matches = [
        Path(item["path"]) for item in available_models(directory)
        if item["valid"] and Path(item["path"]).name.casefold() == original_name.casefold()
    ]
    return matches[0] if len(matches) == 1 else None


def format_model(item: dict) -> str:
    size = item["bytes"] / (1024**3)
    state = "" if item["valid"] else " — invalid / incomplete"
    return f'{item["name"]} ({size:.2f} GB){state}'
