"""Bounded document extraction and reviewed DOCX paragraph-text rewriting."""
from __future__ import annotations

import io
import json
import re
import stat
import subprocess
import sys
import zipfile
from copy import deepcopy
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree


MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_CONTEXT_CHARS = 100_000
MAX_DOCX_ENTRIES = 2_000
MAX_DOCX_EXPANDED_BYTES = 40 * 1024 * 1024
MAX_DOCX_XML_BYTES = 8 * 1024 * 1024
MAX_DOCX_COMPRESSION_RATIO = 200
PDF_TIMEOUT_SECONDS = 30
WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _validate_input(data: bytes, max_chars: int) -> None:
    if not isinstance(data, bytes):
        raise ValueError("Document input must be bytes.")
    if not data:
        raise ValueError("The attached document is empty.")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError("The attached document exceeds the 10 MiB limit.")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or not 1 <= max_chars <= MAX_CONTEXT_CHARS:
        raise ValueError("Document context limit must be between 1 and 100000 characters.")


# Parsing runs in its own interpreter: malformed PDFs cannot block the UI's
# worker indefinitely or change the shared process's parser limits. No file
# paths, commands, PDF JavaScript, actions or embedded attachments are executed.
_PDF_WORKER = r'''
import io
import json
import logging
import sys

logging.disable(logging.CRITICAL)
try:
    import resource
    memory = 512 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
except (ImportError, OSError, ValueError):
    pass

def extract():
    try:
        import pypdf
        from pypdf import filters
    except ImportError:
        raise ValueError("PDF extraction requires pypdf>=6.10; repair the LuxAI installation.")
    required = ("ZLIB_MAX_OUTPUT_LENGTH", "LZW_MAX_OUTPUT_LENGTH",
                "RUN_LENGTH_MAX_OUTPUT_LENGTH", "MAX_ARRAY_BASED_STREAM_OUTPUT_LENGTH",
                "MAX_DECLARED_STREAM_LENGTH", "ZLIB_MAX_RECOVERY_INPUT_LENGTH")
    if not all(hasattr(filters, name) for name in required):
        raise ValueError("Safe PDF extraction requires pypdf>=6.10; repair the LuxAI installation.")
    for name in required:
        setattr(filters, name, 8 * 1024 * 1024)
    filters.ZLIB_MAX_RECOVERY_INPUT_LENGTH = 1024 * 1024
    original_decode = filters.decode_stream_data
    decoded_bytes = 0
    def bounded_decode(stream, *args, **kwargs):
        nonlocal decoded_bytes
        result = original_decode(stream, *args, **kwargs)
        decoded_bytes += len(result)
        if decoded_bytes > 32 * 1024 * 1024:
            raise ValueError("The PDF exceeds the 32 MiB decoded-stream budget.")
        return result
    filters.decode_stream_data = bounded_decode
    data = sys.stdin.buffer.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("The attached PDF exceeds the 10 MiB limit.")
    reader = pypdf.PdfReader(io.BytesIO(data), strict=True, root_object_recovery_limit=1000)
    if reader.is_encrypted:
        raise ValueError("Password-protected PDFs are not supported. Attach an unlocked copy.")
    count = len(reader.pages)
    if count > 100:
        raise ValueError("The attached PDF exceeds the 100-page limit.")
    limit = int(sys.argv[1])
    parts = []
    length = 0
    truncated = False
    for index, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        separator = "\n\n" if parts else ""
        remaining = max(0, limit - length)
        addition = separator + text
        parts.append(addition[:remaining])
        length += min(remaining, len(addition))
        if len(addition) > remaining or (length >= limit and index + 1 < count):
            truncated = True
            break
    text = "".join(parts).strip()
    warnings = []
    if truncated:
        warnings.append("PDF text was truncated to the attachment context limit.")
    if not text:
        warnings.append("No extractable PDF text was found; scanned pages may need image OCR.")
    return {"text": text, "warnings": warnings}

try:
    result = extract()
except ValueError as exc:
    result = {"error": str(exc)[:300]}
except MemoryError:
    result = {"error": "The PDF exceeds safe parser memory limits."}
except Exception as exc:
    result = {"error": "The PDF could not be read safely (" + type(exc).__name__ + ")."}
sys.stdout.write(json.dumps(result, ensure_ascii=True))
'''


def extract_pdf(data: bytes, *, max_chars: int = 24_000) -> tuple[str, tuple[str, ...]]:
    """Extract PDF text with page, decompression, time and output limits."""
    _validate_input(data, max_chars)
    if not data.startswith(b"%PDF-"):
        raise ValueError("The selected file is not a valid PDF document.")
    interpreter = Path(sys.executable)
    if interpreter.name.casefold() == "pythonw.exe":
        # GUI startup uses pythonw, whose standard streams may be absent.
        # Launch the sibling console interpreter invisibly with real pipes.
        interpreter = interpreter.with_name("python.exe")
        if not interpreter.is_file():
            raise ValueError("The isolated PDF reader's Python interpreter is unavailable.")
    try:
        result = subprocess.run(
            [str(interpreter), "-I", "-c", _PDF_WORKER, str(max_chars)], input=data,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=PDF_TIMEOUT_SECONDS,
            check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("PDF extraction exceeded the 30-second safety limit.") from exc
    except OSError as exc:
        raise ValueError("The isolated PDF reader could not be started.") from exc
    if result.returncode or len(result.stdout) > 6 * max_chars + 4096:
        raise ValueError("The PDF reader stopped before safe extraction completed.")
    try:
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError("The PDF reader returned an invalid result.")
        if "error" in payload:
            raise ValueError(str(payload["error"])[:300])
        text = payload["text"]
        warnings = payload["warnings"]
        if (not isinstance(text, str) or len(text) > max_chars
                or not isinstance(warnings, list) or len(warnings) > 10
                or any(not isinstance(item, str) or len(item) > 300 for item in warnings)):
            raise ValueError("The PDF reader returned an invalid result.")
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("The PDF reader returned an invalid result.") from exc
    return text, tuple(warnings)


def _parse_word_xml(data: bytes) -> ElementTree.Element:
    try:
        if data.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
            raise ValueError("UTF-32 DOCX XML is not supported.")
        encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        text = data.decode(encoding)
        if "\x00" in text:
            raise ValueError("DOCX XML requires UTF-8 or BOM-marked UTF-16 encoding.")
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, flags=re.IGNORECASE):
            raise ValueError("DOCX XML entity declarations are not supported.")
        root = ElementTree.fromstring(text)
        count = 0
        stack = [(root, 1)]
        while stack:
            element, depth = stack.pop()
            count += 1
            if count > 200_000:
                raise ValueError("The DOCX XML contains too many elements.")
            if depth > 128:
                raise ValueError("The DOCX XML exceeds the safe nesting limit.")
            stack.extend((child, depth + 1) for child in element)
        return root
    except (UnicodeError, ElementTree.ParseError) as exc:
        raise ValueError("The DOCX contains invalid or unsupported document XML.") from exc


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    parts = []
    stack = list(reversed(list(paragraph)))
    while stack:
        item = stack.pop()
        if item.tag == WORD_NAMESPACE + "t":
            parts.append(item.text or "")
        elif item.tag == WORD_NAMESPACE + "tab":
            parts.append("\t")
        elif item.tag in {WORD_NAMESPACE + "br", WORD_NAMESPACE + "cr"}:
            # Keep paragraph separators unambiguous for a reviewed text edit.
            parts.append("\v")
        elif item.tag not in {WORD_NAMESPACE + "pPr", WORD_NAMESPACE + "rPr"}:
            stack.extend(reversed(list(item)))
    return "".join(parts)


def _read_docx(data: bytes) -> tuple[ElementTree.Element, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_DOCX_ENTRIES:
                raise ValueError("The DOCX archive contains too many entries.")
            if sum(info.file_size for info in entries) > MAX_DOCX_EXPANDED_BYTES:
                raise ValueError("The DOCX archive exceeds the 40 MiB expansion limit.")
            seen = set()
            for info in entries:
                name = info.filename
                path = PurePosixPath(name)
                key = name.casefold()
                if (not path.parts or path.is_absolute() or ".." in path.parts
                        or "\\" in name or any(ord(char) < 32 for char in name)
                        or any(":" in part for part in path.parts)
                        or stat.S_ISLNK(info.external_attr >> 16) or key in seen):
                    raise ValueError("The DOCX archive contains an unsafe entry.")
                if info.flag_bits & 1:
                    raise ValueError("Encrypted DOCX archives are not supported.")
                if info.file_size > MAX_DOCX_COMPRESSION_RATIO * max(1, info.compress_size):
                    raise ValueError("The DOCX archive exceeds the safe compression ratio.")
                seen.add(key)
            if "word/document.xml" not in archive.namelist() or "[Content_Types].xml" not in archive.namelist():
                raise ValueError("The file is not a DOCX document; its main XML is missing.")
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_DOCX_XML_BYTES:
                raise ValueError("The DOCX document XML exceeds the 8 MiB limit.")
            with archive.open(info) as source:
                xml = source.read(MAX_DOCX_XML_BYTES + 1)
            if len(xml) > MAX_DOCX_XML_BYTES:
                raise ValueError("The DOCX document XML exceeds the 8 MiB limit.")
            root = _parse_word_xml(xml)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
        raise ValueError("The DOCX archive is damaged or uses unsupported compression.") from exc

    if root.tag != WORD_NAMESPACE + "document":
        raise ValueError("The DOCX document XML has an invalid root element.")
    body = root.find(WORD_NAMESPACE + "body")
    if body is None:
        raise ValueError("The DOCX main document body is missing.")
    return root, xml


def extract_docx(data: bytes, *, max_chars: int = 24_000) -> tuple[str, tuple[str, ...]]:
    """Read paragraph text in order, retaining empty paragraphs and table cells.

    A newline separates paragraphs; a vertical tab represents a line break
    inside a paragraph. These boundaries also define safe DOCX text edits.
    """
    _validate_input(data, max_chars)
    root, _ = _read_docx(data)
    body = root.find(WORD_NAMESPACE + "body")
    text = "\n".join(_paragraph_text(paragraph) for paragraph in body.iter(WORD_NAMESPACE + "p"))
    truncated = len(text) > max_chars
    text = text[:max_chars]
    warnings = ["DOCX context contains main-body paragraph text only; headers, footnotes and embedded objects are not included."]
    if truncated:
        warnings.append("DOCX text was truncated to the attachment context limit.")
    if not text.strip():
        warnings.append("No readable text was found in the DOCX main document body.")
    return text, tuple(warnings)


def _editable_paragraphs(root: ElementTree.Element) -> list[ElementTree.Element] | None:
    body = root.find(WORD_NAMESPACE + "body")
    paragraphs = list(body.iter(WORD_NAMESPACE + "p"))
    if not paragraphs:
        return None
    for paragraph in paragraphs:
        for child in paragraph:
            if child.tag == WORD_NAMESPACE + "pPr":
                continue
            if child.tag != WORD_NAMESPACE + "r":
                return None
            for content in child:
                if content.tag not in {WORD_NAMESPACE + name for name in ("rPr", "t", "tab", "br", "cr")}:
                    return None
                if content.tag == WORD_NAMESPACE + "br" and content.get(WORD_NAMESPACE + "type", "textWrapping") != "textWrapping":
                    return None
    return paragraphs


def docx_editable(data: bytes) -> bool:
    """Whether paragraph text can be changed without dropping complex objects."""
    _validate_input(data, MAX_CONTEXT_CHARS)
    root, xml = _read_docx(data)
    if _editable_paragraphs(root) is None:
        return False
    try:
        _serialize_word_xml(root, xml)
    except ValueError:
        return False
    return True


def _serialize_word_xml(root: ElementTree.Element, original_xml: bytes) -> bytes:
    # Keep original aliases used by QName-valued attributes, even when that
    # namespace has no surviving element. Conflicting aliases are read-only.
    aliases = {}
    for _event, (prefix, namespace) in ElementTree.iterparse(io.BytesIO(original_xml), events=("start-ns",)):
        if prefix in aliases and aliases[prefix] != namespace:
            raise ValueError("DOCX namespace aliases require a TXT copy for safe editing.")
        aliases[prefix] = namespace
    rendered = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
    rendered_aliases = {pair[0]: pair[1] for _event, pair in
                        ElementTree.iterparse(io.BytesIO(rendered), events=("start-ns",))}
    for prefix, namespace in aliases.items():
        attribute = "xmlns:" + prefix if prefix else "xmlns"
        if prefix in rendered_aliases:
            if rendered_aliases[prefix] != namespace:
                raise ValueError("DOCX namespace aliases require a TXT copy for safe editing.")
        else:
            root.set(attribute, namespace)
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)


def rewrite_docx(data: bytes, new_text: str) -> bytes:
    """Replace existing paragraph text, preserving document/package structure.

    Paragraph count must remain identical. Each paragraph keeps its attributes,
    paragraph properties and first-run formatting; unrelated ZIP entries stay
    byte-for-byte identical after decompression. Complex paragraph content is
    read-only instead of silently losing fields, links or embedded objects.
    """
    _validate_input(data, MAX_CONTEXT_CHARS)
    if not isinstance(new_text, str) or len(new_text) > MAX_CONTEXT_CHARS:
        raise ValueError("DOCX replacement text must contain at most 100000 characters.")
    new_text = new_text.replace("\r\n", "\n").replace("\r", "\n")
    if any(not (char in "\t\n\v" or 0x20 <= ord(char) <= 0xD7FF
                or 0xE000 <= ord(char) <= 0xFFFD or 0x10000 <= ord(char) <= 0x10FFFF)
           for char in new_text):
        raise ValueError("DOCX replacement text contains unsupported control characters.")
    root, original_xml = _read_docx(data)
    paragraphs = _editable_paragraphs(root)
    if paragraphs is None:
        raise ValueError("This DOCX contains complex paragraph content; export a TXT copy to edit its text safely.")
    lines = new_text.split("\n")
    if len(lines) != len(paragraphs):
        raise ValueError("DOCX edits must keep the existing paragraph count; export a TXT copy to change its structure.")
    for paragraph, replacement in zip(paragraphs, lines):
        if replacement == _paragraph_text(paragraph):
            continue
        old_run = paragraph.find(WORD_NAMESPACE + "r")
        run_properties = old_run.find(WORD_NAMESPACE + "rPr") if old_run is not None else None
        for child in list(paragraph):
            if child.tag != WORD_NAMESPACE + "pPr":
                paragraph.remove(child)
        run = ElementTree.SubElement(paragraph, WORD_NAMESPACE + "r")
        if run_properties is not None:
            run.append(deepcopy(run_properties))
        for chunk in re.split(r"([\t\v])", replacement):
            if chunk == "\t":
                ElementTree.SubElement(run, WORD_NAMESPACE + "tab")
            elif chunk == "\v":
                ElementTree.SubElement(run, WORD_NAMESPACE + "br")
            elif chunk:
                text = ElementTree.SubElement(run, WORD_NAMESPACE + "t")
                text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                text.text = chunk
    rendered = _serialize_word_xml(root, original_xml)
    output = io.BytesIO()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(output, "w") as target:
            for info in source.infolist():
                content = rendered if info.filename == "word/document.xml" else source.read(info)
                target.writestr(info, content)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
        raise ValueError("The DOCX package is damaged or uses unsupported compression; export a TXT copy to edit its text.") from exc
    rewritten = output.getvalue()
    if len(rewritten) > MAX_DOCUMENT_BYTES:
        raise ValueError("The edited DOCX would exceed the 10 MiB attachment limit.")
    return rewritten
