"""Real application icons for the command library (0.4.2o), as in Luxify.

The icon comes from the program installed on this PC (its .exe, through the
Windows shell), drawn on a small rounded tile in the app's theme. A program
that is not installed gets a simple glyph in its own colour. Nothing is
downloaded and no brand artwork is shipped.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFileInfo, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap

# group key -> the program whose icon is shown («windows» is drawn: four panes)
SOURCES = {
    "windows": None, "chrome": "chrome", "telegram": "telegram", "spotify": "spotify", "word": "word",
    "discord": "discord", "steam": "steam", "firefox": "firefox", "edge": "edge", "youtube": None,
    "yandex_music": None, "other": None, "defaults": None, "folder": None,
}
FALLBACK = {  # glyph, colour — only when the program is not installed
    "windows": ("monitor", "#3b82f6"), "chrome": ("globe", "#4285f4"), "telegram": ("send", "#2aa3e0"),
    "spotify": ("audio-lines", "#1db954"), "word": ("file-text", "#2b5eb4"), "discord": ("message-square", "#5865f2"),
    "steam": ("gamepad-2", "#5fa9df"), "firefox": ("globe", "#ff7139"), "edge": ("globe", "#1b9de2"),
    "youtube": ("play", "#ff2d2d"), "yandex_music": ("file-music", "#ffcc00"), "other": ("layout-grid", ""), "defaults": ("package", ""), "folder": ("folder", ""),
}
GROUP_KEYS = {
    "Управление Windows": "windows", "Управление Google Chrome": "chrome", "Управление YouTube": "youtube",
    "Управление Telegram": "telegram", "Управление Spotify": "spotify", "Управление Word": "word",
    "Управление Yandex Music": "yandex_music", "Управление Discord": "discord", "Игры Steam": "steam",
    "Другие приложения": "other",
}
_paths: dict[str, Path | None] = {}
_icons: dict[tuple, QIcon] = {}


def _shortcut_target(path: Path) -> Path | None:
    try:
        import win32com.client
        target = win32com.client.Dispatch("WScript.Shell").CreateShortCut(str(path)).Targetpath
        return Path(target) if target and Path(target).is_file() else None
    except Exception:
        return None


def program_path(key: str) -> Path | None:
    if key in _paths:
        return _paths[key]
    source = SOURCES.get(key)
    found = None
    if source:
        try:
            from luxai.windows_apps import resolve_installed_app
            found = resolve_installed_app(source)
        except Exception:
            found = None
        if found is not None and found.suffix.casefold() == ".lnk":
            # Discord's shortcut points to Update.exe: its icon is still Discord's.
            found = _shortcut_target(found) or found
    _paths[key] = found
    return found


def _program_pixmap(key: str, size: int) -> QPixmap | None:
    path = program_path(key)
    if path is None:
        return None
    from PySide6.QtWidgets import QFileIconProvider
    icon = QFileIconProvider().icon(QFileInfo(str(path)))
    if icon.isNull():
        return None
    pixmap = icon.pixmap(QSize(max(size, 32), max(size, 32)))
    return None if pixmap.isNull() else pixmap


def tile_icon(key: str, theme: str = "dark", size: int = 26, ratio: float = 2.0) -> QIcon:
    """The app's icon on a rounded tile; cached per theme."""
    cache = (key, theme, size, ratio)
    if cache in _icons:
        return _icons[cache]
    from luxai.icons import icon as glyph
    from luxai.styles import DARK, LIGHT
    palette = LIGHT if theme == "light" else DARK
    canvas = QPixmap(int(size * ratio), int(size * ratio))
    canvas.setDevicePixelRatio(ratio)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(0.5, 0.5, size - 1, size - 1), 7.5, 7.5)
    painter.fillPath(tile, QColor(palette["control"]))
    painter.setPen(QColor(palette["border"]))
    painter.drawPath(tile)
    inner = round(size * 0.62)
    offset = (size - inner) / 2
    picture = _program_pixmap(key, inner)
    if key == "windows":
        _draw_panes(painter, offset, inner)
    elif picture is not None:
        painter.drawPixmap(QRectF(offset, offset, inner, inner), picture, QRectF(picture.rect()))
    else:
        name, colour = FALLBACK.get(key, ("folder", ""))
        mark = glyph(name, color=colour or palette["muted"]).pixmap(QSize(int(inner * ratio), int(inner * ratio)))
        painter.drawPixmap(QRectF(offset, offset, inner, inner), mark, QRectF(mark.rect()))
    painter.end()
    result = QIcon(canvas)
    _icons[cache] = result
    return result


def _draw_panes(painter: QPainter, offset: float, inner: float) -> None:
    """Four blue panes, the usual sign for Windows."""
    from PySide6.QtGui import QLinearGradient
    gap = inner * 0.08
    side = (inner - gap) / 2
    gradient = QLinearGradient(offset, offset, offset + inner, offset + inner)
    gradient.setColorAt(0, QColor("#53b6ff"))
    gradient.setColorAt(1, QColor("#0a6cdc"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    for column in (0, 1):
        for row in (0, 1):
            painter.drawRoundedRect(QRectF(offset + column * (side + gap), offset + row * (side + gap), side, side), 1.2, 1.2)


def padded_icon(source: QIcon, inner: int, size: int = 26, ratio: float = 2.0) -> QIcon:
    """A smaller glyph centred in the tree's icon box, so command rows stay light next to the tiles."""
    canvas = QPixmap(int(size * ratio), int(size * ratio))
    canvas.setDevicePixelRatio(ratio)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    picture = source.pixmap(QSize(int(inner * ratio), int(inner * ratio)))
    offset = (size - inner) / 2
    painter.drawPixmap(QRectF(offset, offset, inner, inner), picture, QRectF(picture.rect()))
    painter.end()
    return QIcon(canvas)
