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


def model_status(configured: str, *, directory: Path | None = None) -> tuple[bool, str]:
    """Small diagnostic suitable for display without loading llama.cpp into Qt."""
    import importlib.util
    model = resolve_model_path(configured, directory=directory)
    if model is None:
        return False, "No model selected or model file missing. Place a .gguf in models/."
    try:
        with model.open("rb") as handle:
            valid = model.stat().st_size >= MIN_GGUF_BYTES and handle.read(4) == GGUF_MAGIC
    except OSError:
        valid = False
    if not valid:
        return False, "GGUF file is invalid or incomplete. Download/copy it again."
    try:
        installed = importlib.util.find_spec("llama_cpp") is not None
    except (ImportError, ValueError):
        installed = False
    if not installed:
        return False, "llama-cpp-python is missing. Run install_local_ai.bat."
    return True, "GGUF found and local backend installed. Actual load depends on available RAM."
