"""Bounded snapshots of explicitly selected chat files and reviewable edits.

Attachment contents are untrusted input. This module never executes them,
uploads them, chooses another target path, or downloads an OCR dependency.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import difflib
import hashlib
import io
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import uuid
import warnings


MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_ATTACHMENTS = 8
MAX_EXTRACTED_CHARS = 24_000
MAX_IMAGE_PIXELS = 25_000_000
MAX_IMAGE_EDGE = 1600
BACKUP_ROOT = Path(__file__).resolve().parents[1] / ".luxai_data" / "file_edits"
TEXT_SUFFIXES = frozenset({
    ".txt", ".md", ".csv", ".tsv", ".json", ".jsonl", ".log", ".yaml", ".yml",
    ".xml", ".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx", ".py",
    ".toml", ".ini", ".cfg", ".conf", ".c", ".h", ".cpp", ".hpp", ".cs",
    ".java", ".rs", ".go", ".sql", ".sh", ".bat", ".ps1", ".r", ".tex",
})
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})


class AttachmentError(ValueError):
    """An attachment cannot be read or safely written as requested."""


@dataclass(frozen=True)
class Attachment:
    id: str
    path: Path
    name: str
    kind: str
    size: int
    sha256: str
    text: str
    content: bytes
    encoding: str = ""
    newline: str = "\n"
    bom: bytes = b""
    image_data_url: str = ""
    warnings: tuple[str, ...] = ()
    editable: bool = False
    truncated: bool = False
    stat_signature: tuple[int, ...] = ()


@dataclass(frozen=True)
class EditProposal:
    attachment: Attachment
    new_text: str
    new_content: bytes
    diff: str
    export_only: bool = False
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class EditResult:
    path: Path
    backup_path: Path | None
    sha256: str


def _signature(info: os.stat_result) -> tuple[int, ...]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _check_path(path: Path, *, file_required: bool = True) -> None:
    """Reject symbolic links and Windows reparse points, including ancestors."""
    try:
        for part in (path, *path.parents):
            try:
                info = part.lstat()
            except FileNotFoundError:
                if part == path and not file_required:
                    continue
                raise AttachmentError("The selected path no longer exists.")
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise AttachmentError("Linked files or folders are not supported; select the original file.")
        if file_required and not path.is_file():
            raise AttachmentError("Select a regular file, not a folder or device.")
    except OSError as exc:
        raise AttachmentError(f"Cannot access the selected file: {type(exc).__name__}.") from exc


def _read_file(path: Path) -> tuple[bytes, tuple[int, ...]]:
    _check_path(path)
    try:
        before = path.stat()
        if before.st_size > MAX_FILE_BYTES:
            raise AttachmentError("Each attachment must be at most 10 MB.")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if _signature(opened) != _signature(before):
                raise AttachmentError("The file changed while it was being attached. Select it again.")
            data = handle.read(MAX_FILE_BYTES + 1)
        _check_path(path)
        after = path.stat()
        if len(data) > MAX_FILE_BYTES:
            raise AttachmentError("Each attachment must be at most 10 MB.")
        if _signature(after) != _signature(before):
            raise AttachmentError("The file changed while it was being attached. Select it again.")
        return data, _signature(after)
    except OSError as exc:
        raise AttachmentError(f"Cannot read the selected file: {type(exc).__name__}.") from exc


def _text_content(data: bytes) -> tuple[str, str, str, bytes, tuple[str, ...], bool]:
    bom = b""
    notes = []
    if data.startswith(b"\xef\xbb\xbf"):
        encoding, bom = "utf-8", b"\xef\xbb\xbf"
    elif data.startswith(b"\xff\xfe"):
        encoding, bom = "utf-16-le", b"\xff\xfe"
    elif data.startswith(b"\xfe\xff"):
        encoding, bom = "utf-16-be", b"\xfe\xff"
    else:
        encoding = "utf-8"
    raw = data[len(bom):]
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        if bom:
            raise AttachmentError("The text does not match its encoding marker.")
        try:
            text = raw.decode("cp1251")
        except UnicodeDecodeError as exc:
            raise AttachmentError("Unsupported text encoding; save the file as UTF-8.") from exc
        encoding = "cp1251"
        notes.append("Text decoded as Windows-1251; edits retain this encoding.")
    if "\x00" in text or any(ord(char) < 32 and char not in "\t\r\n\f" for char in text):
        raise AttachmentError("The selected text file contains binary data or unsupported control characters.")
    endings = set()
    if "\r\n" in text:
        endings.add("\r\n")
    without_crlf = text.replace("\r\n", "")
    if "\n" in without_crlf:
        endings.add("\n")
    if "\r" in without_crlf:
        endings.add("\r")
    newline = next(iter(endings)) if len(endings) == 1 else "\n"
    mixed = len(endings) > 1
    if mixed:
        notes.append("Mixed line endings: read-only to preserve the original formatting.")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized, encoding, newline, bom, tuple(notes), mixed


def _image_content(data: bytes) -> str:
    try:
        from PIL import Image, ImageOps
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as check:
                if check.format not in {"PNG", "JPEG", "WEBP"}:
                    raise AttachmentError("Only PNG, JPEG and WebP image contents are supported.")
                if check.width * check.height > MAX_IMAGE_PIXELS:
                    raise AttachmentError("The image is too large; choose an image below 25 megapixels.")
                check.verify()
            with Image.open(io.BytesIO(data)) as original:
                image = ImageOps.exif_transpose(original)
                image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                output = io.BytesIO()
                image.save(output, format="PNG")
                mime = "image/png"
                if output.tell() > 4 * 1024 * 1024:
                    # Bound noisy photos as well as dimensions. Re-encoding
                    # discards EXIF and other original metadata in both cases.
                    flat = Image.new("RGB", image.size, "white")
                    flat.paste(image, mask=image.getchannel("A") if image.mode == "RGBA" else None)
                    output = io.BytesIO()
                    flat.save(output, format="JPEG", quality=85)
                    mime = "image/jpeg"
        return "data:" + mime + ";base64," + base64.b64encode(output.getvalue()).decode("ascii")
    except AttachmentError:
        raise
    except Exception as exc:
        raise AttachmentError(f"Cannot decode this image safely: {type(exc).__name__}.") from exc


def load_attachment(path: str | Path) -> Attachment:
    """Snapshot one selected file locally; image loading never runs OCR."""
    selected = Path(path).expanduser().absolute()
    data, signature = _read_file(selected)
    suffix = selected.suffix.casefold()
    common = dict(id=uuid.uuid4().hex, path=selected, name=selected.name,
                  size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                  content=data, stat_signature=signature)
    if suffix in TEXT_SUFFIXES or selected.name.casefold() in {"license", "notice", "dockerfile", "makefile"}:
        text, encoding, newline, bom, notes, mixed = _text_content(data)
        truncated = len(text) > MAX_EXTRACTED_CHARS
        if truncated:
            notes += ("Text exceeds the chat limit; only an excerpt is available and editing is disabled.",)
        return Attachment(**common, kind="text", text=text[:MAX_EXTRACTED_CHARS], encoding=encoding,
                          newline=newline, bom=bom, warnings=notes, truncated=truncated,
                          editable=not mixed and not truncated)
    if suffix in IMAGE_SUFFIXES:
        return Attachment(**common, kind="image", text="", image_data_url=_image_content(data))
    if suffix in {".pdf", ".docx"}:
        from luxai.attachment_documents import docx_editable, extract_docx, extract_pdf
        try:
            extractor = extract_pdf if suffix == ".pdf" else extract_docx
            text, notes = extractor(data, max_chars=MAX_EXTRACTED_CHARS)
        except (ValueError, RuntimeError, OSError) as exc:
            raise AttachmentError(str(exc)) from exc
        truncated = any("truncat" in note.casefold() for note in notes)
        return Attachment(**common, kind=suffix[1:], text=text, warnings=tuple(notes),
                          editable=suffix == ".docx" and not truncated and docx_editable(data),
                          truncated=truncated)
    raise AttachmentError(
        f"Unsupported file type {suffix or '(no extension)'}. Attach text/code, PDF, DOCX, PNG, JPEG or WebP. "
        "This file has not been executed or modified."
    )


def load_attachments(paths) -> tuple[Attachment, ...]:
    selected = tuple(paths)
    if len(selected) > MAX_ATTACHMENTS:
        raise AttachmentError("Select at most 8 attachments per message.")
    result = []
    total = 0
    seen = set()
    unique = []
    for path in selected:
        key = os.path.normcase(str(Path(path).expanduser().absolute()))
        if key in seen:
            continue
        candidate = Path(path).expanduser().absolute()
        _check_path(candidate)
        try:
            total += candidate.stat().st_size
        except OSError as exc:
            raise AttachmentError("Cannot inspect the selected attachment.") from exc
        if total > MAX_TOTAL_BYTES:
            raise AttachmentError("Attachments must total at most 20 MB per message.")
        unique.append(path)
        seen.add(key)
    total = 0
    for path in unique:
        attachment = load_attachment(path)
        total += attachment.size
        if total > MAX_TOTAL_BYTES:
            raise AttachmentError("Attachments must total at most 20 MB per message.")
        result.append(attachment)
    return tuple(result)


def attachment_context(attachments, max_chars: int = MAX_EXTRACTED_CHARS) -> str:
    """Describe untrusted snapshots without exposing original filesystem paths."""
    max_chars = max(0, min(int(max_chars), 200_000))
    pieces = []
    remaining = max_chars
    for attachment in attachments:
        header = f"[Attachment id={attachment.id} name={attachment.name!r} type={attachment.kind}]\n"
        if len(header) >= remaining:
            break
        body = attachment.text or ("[Image attached; inspect supplied image or request local OCR.]" if attachment.kind == "image" else "[No text extracted.]")
        ending = "\n[/Attachment]\n"
        capacity = max(0, remaining - len(header) - len(ending))
        if len(body) > capacity:
            marker = "\n[Context truncated; do not propose a full-file edit.]"
            body = body[:max(0, capacity - len(marker))] + marker[:capacity]
        block = (header + body + ending)[:remaining]
        pieces.append(block)
        remaining -= len(block)
    return "".join(pieces)


def extract_image_text(attachment: Attachment) -> str:
    """Run installed local OCR only when requested from a response worker."""
    prefix = attachment.image_data_url.partition(",")[0]
    if attachment.kind != "image" or prefix not in {"data:image/png;base64", "data:image/jpeg;base64"}:
        raise AttachmentError("Select an image attachment for OCR.")
    try:
        from luxai.ocr_setup import ensure_tesseract
        binary, models = ensure_tesseract(allow_download=False)
        with tempfile.TemporaryDirectory(prefix="luxai_attachment_ocr_") as temporary:
            image = Path(temporary) / ("attachment.jpg" if "jpeg" in prefix else "attachment.png")
            image.write_bytes(base64.b64decode(attachment.image_data_url.partition(",")[2], validate=True))
            command = [str(binary), str(image), "stdout", "--tessdata-dir", str(models), "-l", "rus+eng"]
            result = subprocess.run(command, shell=False, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=25, check=False,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise AttachmentError("Local OCR could not read this image.")
        return result.stdout[:MAX_EXTRACTED_CHARS]
    except AttachmentError:
        raise
    except Exception as exc:
        raise AttachmentError(f"Local OCR is unavailable ({type(exc).__name__}); use a vision model or install OCR.") from exc


def _encoded_text(attachment: Attachment, text: str) -> bytes:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    try:
        return attachment.bom + normalized.replace("\n", attachment.newline).encode(attachment.encoding)
    except UnicodeEncodeError as exc:
        raise AttachmentError("The edited text cannot be represented in the original encoding; save a UTF-8 text copy instead.") from exc


def propose_text_edit(attachments, attachment_id: str, new_text: str) -> EditProposal:
    """Create a preview for an attachment ID from the actual selected set."""
    selected = [attachment for attachment in attachments if attachment.id == attachment_id]
    if len(selected) != 1:
        raise AttachmentError("The edit target is not one of the selected attachments.")
    attachment = selected[0]
    if not isinstance(new_text, str) or len(new_text) > MAX_EXTRACTED_CHARS:
        raise AttachmentError("The edited text must be a string of at most 24000 characters.")
    # DOCX uses vertical tabs to distinguish manual breaks from paragraphs.
    # Plain text must remain readable by the same validator used on attach.
    controls = "\t\r\n\f" if attachment.kind == "text" else "\t\r\n\f\v"
    if any((ord(char) < 32 and char not in controls)
           or 0xD800 <= ord(char) <= 0xDFFF for char in new_text):
        raise AttachmentError("The edited text contains unsupported control characters or invalid Unicode.")
    if attachment.truncated or attachment.kind not in {"text", "docx", "pdf"}:
        raise AttachmentError("This attachment cannot be edited from the available text. Attach a complete text document.")
    notes = ()
    export_only = attachment.kind == "pdf"
    normalized = new_text.replace("\r\n", "\n").replace("\r", "\n")
    if attachment.kind == "text":
        if not attachment.editable:
            raise AttachmentError("This text is read-only to preserve its original formatting.")
        try:
            content = _encoded_text(attachment, normalized)
        except AttachmentError:
            content = normalized.encode("utf-8")
            export_only = True
            notes = ("The original encoding cannot represent the edit. Save a UTF-8 .txt copy; the original remains unchanged.",)
    elif attachment.kind == "docx":
        from luxai.attachment_documents import rewrite_docx
        try:
            content = rewrite_docx(attachment.content, normalized)
            notes = ("DOCX paragraphs and package parts are preserved; edited paragraphs use their first run's formatting.",)
        except ValueError as exc:
            export_only = True
            content = normalized.encode("utf-8")
            notes = (f"DOCX structure cannot be preserved: {exc}. Save an edited .txt copy instead.",)
    else:
        content = normalized.encode("utf-8")
        notes = ("PDF editing is a plain-text export only; the original PDF is unchanged.",)
    if len(content) > MAX_FILE_BYTES:
        raise AttachmentError("The edited file would exceed 10 MB.")
    diff = "\n".join(difflib.unified_diff(attachment.text.splitlines(), normalized.splitlines(),
                                        fromfile=attachment.name, tofile=attachment.name + " (proposed)",
                                        lineterm=""))
    return EditProposal(attachment, normalized, content, diff, export_only, notes)


def _verify_original(attachment: Attachment) -> None:
    current, signature = _read_file(attachment.path)
    if hashlib.sha256(current).hexdigest() != attachment.sha256 or signature != attachment.stat_signature:
        raise AttachmentError("The original file changed outside this chat. Attach it again before applying edits.")


def apply_text_edit(proposal: EditProposal, *, confirmed: bool = False,
                    backup_root: str | Path | None = None) -> EditResult:
    """Apply a reviewed proposal to its original selected file, with backup."""
    if confirmed is not True:
        raise AttachmentError("Preview and confirm the proposed edit before applying it.")
    if proposal.export_only:
        raise AttachmentError("This proposal can only be saved as a text copy; the original format cannot be replaced.")
    attachment = proposal.attachment
    if hashlib.sha256(attachment.content).hexdigest() != attachment.sha256:
        raise AttachmentError("The attachment snapshot is invalid. Select the file again.")
    _verify_original(attachment)
    backup_directory = Path(backup_root) if backup_root is not None else BACKUP_ROOT
    backup_directory = backup_directory.expanduser().absolute()
    try:
        for parent in (backup_directory, *backup_directory.parents):
            if parent.exists() or parent.is_symlink():
                _check_path(parent, file_required=False)
        backup_directory.mkdir(parents=True, exist_ok=True)
        _check_path(backup_directory, file_required=False)
        backup = backup_directory / (uuid.uuid4().hex + "-" + attachment.name[:100] + ".bak")
        with backup.open("xb") as output:
            os.chmod(backup, 0o600)
            output.write(attachment.content)
            output.flush()
            os.fsync(output.fileno())
        descriptor, name = tempfile.mkstemp(prefix=".luxai-edit-", dir=attachment.path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(proposal.new_content)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, stat.S_IMODE(attachment.path.stat().st_mode))
            _verify_original(attachment)  # Recheck after backup and staging.
            os.replace(temporary, attachment.path)
            applied, _ = _read_file(attachment.path)
            if hashlib.sha256(applied).hexdigest() != hashlib.sha256(proposal.new_content).hexdigest():
                raise AttachmentError("The file changed while the edit was being verified. The original backup is retained.")
        finally:
            temporary.unlink(missing_ok=True)
    except AttachmentError:
        raise
    except OSError as exc:
        raise AttachmentError(f"The edit could not be applied safely: {type(exc).__name__}. The original or backup remains available.") from exc
    return EditResult(attachment.path, backup, hashlib.sha256(proposal.new_content).hexdigest())


def save_text_copy(proposal: EditProposal, chosen_path: str | Path) -> EditResult:
    """Save to a destination explicitly chosen in the UI, never overwrite."""
    destination = Path(chosen_path).expanduser().absolute()
    _check_path(destination, file_required=False)
    if destination.exists():
        raise AttachmentError("The copy destination already exists. Choose a new filename.")
    suffix = destination.suffix.casefold()
    if suffix == ".docx" and proposal.attachment.kind == "docx" and not proposal.export_only:
        data = proposal.new_content
    elif suffix == ".txt":
        data = proposal.new_text.replace("\v", "\n").encode("utf-8")
    elif proposal.attachment.kind == "text" and not proposal.export_only and suffix in TEXT_SUFFIXES:
        data = proposal.new_content
    else:
        raise AttachmentError("Choose .txt for a plain-text export, or the supported original document format.")
    try:
        with destination.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    except OSError as exc:
        raise AttachmentError(f"Cannot save this copy: {type(exc).__name__}.") from exc
    return EditResult(destination, None, hashlib.sha256(data).hexdigest())
