"""Decode explicitly copied local files and manage temporary clipboard PNGs.

No attachment is uploaded, opened in another application or executed here.
The ordinary attachment reader still validates each selected file and size.
"""
from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
import tempfile
import uuid

from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage, QPixmap

from luxai.chat_attachments import MAX_ATTACHMENTS, MAX_FILE_BYTES, MAX_IMAGE_PIXELS


class ClipboardAttachmentError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


_WINDOWS_FILENAMES = 'application/x-qt-windows-mime;value="FileNameW"'
_MAX_PATH_TEXT = 262_144


def _unique_paths(paths):
    result, seen = [], set()
    for path in paths:
        if not path or "\0" in path or len(path) > 32_768:
            raise ClipboardAttachmentError("paths")
        if not (Path(path).is_absolute() or PureWindowsPath(path).is_absolute()):
            raise ClipboardAttachmentError("paths")
        # QUrl.toLocalFile() uses forward slashes on Windows, while Explorer's
        # FileNameW and pathlib use native separators. Keep one native spelling
        # for every input without resolving links or accessing the file here.
        native_path = str(Path(path))
        key = os.path.normcase(native_path)
        if key not in seen:
            result.append(native_path)
            seen.add(key)
    if len(result) > MAX_ATTACHMENTS:
        raise ClipboardAttachmentError("count")
    return tuple(result)


def pasted_file_paths(source):
    """Return local URLs/Explorer files, or existing plain copied file paths.

    A browser URL or ordinary text returns an empty tuple so the editor can
    paste it as text. A local-file URL is explicit even if the file has since
    disappeared; the asynchronous attachment reader reports that failure.
    """
    if source.hasUrls():
        urls = source.urls()
        local = [url.toLocalFile() for url in urls if url.isLocalFile()]
        if local:
            if len(local) != len(urls):
                raise ClipboardAttachmentError("mixed_urls")
            return _unique_paths(local)
    if source.hasFormat(_WINDOWS_FILENAMES):
        raw = bytes(source.data(_WINDOWS_FILENAMES))
        if len(raw) > 2 * _MAX_PATH_TEXT:
            raise ClipboardAttachmentError("paths")
        try:
            paths = raw.decode("utf-16-le").rstrip("\0").split("\0")
        except UnicodeError as exc:
            raise ClipboardAttachmentError("paths") from exc
        return _unique_paths(paths)
    if not source.hasText():
        return ()
    text = source.text()
    if len(text) > _MAX_PATH_TEXT:
        return ()  # Large ordinary text is still normal text.
    lines = text.strip().splitlines()
    if not lines:
        return ()
    paths = []
    for line in lines:
        candidate = line.strip()
        if len(candidate) >= 2 and candidate[0] == candidate[-1] == '"':
            candidate = candidate[1:-1]
        url = QUrl(candidate)
        if url.isLocalFile():
            paths.append(url.toLocalFile())
            continue
        path = Path(candidate)
        try:
            if not path.is_absolute() or not path.is_file():
                return ()
        except (OSError, ValueError):
            return ()
        paths.append(str(path))
    return _unique_paths(paths)


class ClipboardImageStore:
    """Exclusive temporary directory; never take ownership of selected files."""
    def __init__(self):
        self._directory = None
        self._owned = set()

    def stage(self, value):
        if isinstance(value, QPixmap):
            value = value.toImage()
        if not isinstance(value, QImage) or value.isNull():
            raise ClipboardAttachmentError("image")
        if value.width() * value.height() > MAX_IMAGE_PIXELS:
            raise ClipboardAttachmentError("image_size")
        if self._directory is None:
            try:
                self._directory = tempfile.TemporaryDirectory(prefix="jarvis-clipboard-")
            except OSError as exc:
                raise ClipboardAttachmentError("image") from exc
        path = Path(self._directory.name) / f"clipboard-{uuid.uuid4().hex[:12]}.png"
        self._owned.add(str(path))
        try:
            if not value.save(str(path), "PNG"):
                raise ClipboardAttachmentError("image")
            if path.stat().st_size > MAX_FILE_BYTES:
                raise ClipboardAttachmentError("image_size")
        except (ClipboardAttachmentError, OSError) as exc:
            self.release((path,))
            if isinstance(exc, ClipboardAttachmentError):
                raise
            raise ClipboardAttachmentError("image") from exc
        return path

    def release(self, paths):
        for raw_path in paths:
            path = str(raw_path)
            if path not in self._owned:
                continue
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                continue  # A final cleanup can retry a Windows file still open.
            self._owned.discard(path)

    def cleanup(self, *_args):
        self.release(tuple(self._owned))
        if self._directory is not None and not self._owned:
            try:
                self._directory.cleanup()
            except OSError:
                return
            self._directory = None
