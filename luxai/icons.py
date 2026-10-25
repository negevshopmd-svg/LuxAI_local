"""Local SVG icons with sharp Qt rendering and theme-aware widget updates.

Lucide's geometry is bundled under its ISC license. No fonts, network calls or
extra Python dependencies are required. Item metadata preserves selections when
the theme changes; icons never replace visible labels or accessibility text.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QComboBox, QLabel, QListWidget, QTreeWidget, QWidget


ASSET_DIR = Path(__file__).resolve().parent / "assets" / "icons"
ICON_NAME_ROLE = int(Qt.ItemDataRole.UserRole) + 60
ICON_COLOR_ROLE = int(Qt.ItemDataRole.UserRole) + 61
_theme, _accent = "dark", "#3978f6"
_ALIASES = {
    "stop-square": "square-stop", "check-circle-2": "circle-check",
    "x-circle": "circle-x", "layers-3": "layers", "clock-3": "clock",
    "music-2": "audio-lines", "music": "audio-lines", "code-2": "code-xml",
    "trash-2": "trash", "history": "clock", "file-code-2": "file-code-corner",
    "file-audio": "file-music", "file-plus-2": "file-plus-corner",
    "circle-help": "circle-question-mark", "text-select": "text-cursor",
}


def _context(widget=None):
    # The application applies a single theme across all top-level windows.
    # Qt parent traversal and repeated reads of unset dynamic properties
    # during bulk tree-icon refresh can corrupt references on Linux/PySide6.
    # refresh_icons updates these values before repainting any items.
    return _theme, _accent


def _color(role="default", widget=None):
    theme, accent = _context(widget)
    light = theme == "light"
    if widget is not None and role == "default" and (widget.property("active") or widget.property("selected")):
        role = "accent"
    return {
        "default": "#334155" if light else "#d9e2ef",
        "muted": "#64748b" if light else "#94a3b8",
        "accent": accent, "white": "#ffffff",
        "danger": "#b91c1c" if light else "#fb8d8d",
        "success": "#15803d" if light else "#80c99b",
        "warning": "#a16207" if light else "#e5bd69",
    }.get(role, "#334155" if light else "#d9e2ef")


@lru_cache(maxsize=192)
def _svg(name):
    canonical = _ALIASES.get(name, name)
    if not canonical or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in canonical):
        raise ValueError("Invalid icon name")
    path = ASSET_DIR / "jarvis.svg" if canonical == "jarvis" else ASSET_DIR / "lucide" / (canonical + ".svg")
    return path.read_bytes()


def _rasterize(renderer, size, scale, opacity):
    """Rasterize an SVG using Qt's standard paint and pixmap classes."""
    pixels = max(1, round(size * scale))
    pixmap = QPixmap(pixels, pixels)
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(opacity)
        renderer.render(painter, QRectF(0, 0, size, size))
    finally:
        painter.end()
    return pixmap


@lru_cache(maxsize=192)
def _colored_icon(name, color):
    svg = _svg(name).replace(b"currentColor", color.encode("ascii"))
    renderer = QSvgRenderer(svg)
    if not renderer.isValid():
        raise ValueError(f"Unable to render SVG icon: {name}")
    # Qt's native pixmap engine safely manages copies and widget lifetimes.
    value = QIcon()
    for size in (20, 24, 48, 64):
        for scale in (1.0, 2.0):
            value.addPixmap(_rasterize(renderer, size, scale, 1.0), QIcon.Mode.Normal)
            value.addPixmap(_rasterize(renderer, size, scale, 0.4), QIcon.Mode.Disabled)
    return value


def icon(name, *, color=None, size=20):
    """Return a scalable icon; ``size`` documents its intended widget size."""
    del size  # SVG engine paints at the size requested by Qt, including HiDPI.
    value = QColor(color or _color())
    if not value.isValid():
        raise ValueError("Invalid icon color")
    return QIcon(_colored_icon(name, value.name()))


def set_button_icon(button, name, *, size=18, role="default"):
    button.setProperty("jarvisIcon", name)
    button.setProperty("jarvisIconRole", role)
    button.setProperty("jarvisIconSize", size)
    button.setIcon(icon(name, color=_color(role, button)))
    button.setIconSize(QSize(size, size))


def set_label_icon(label, name, *, size=18, role="default"):
    label.setProperty("jarvisIcon", name)
    label.setProperty("jarvisIconRole", role)
    label.setProperty("jarvisIconSize", size)
    box_size = int(label.property("jarvisIconBoxSize") or size)
    label.setFixedSize(box_size, box_size)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setPixmap(icon(name, color=_color(role, label)).pixmap(QSize(size, size), label.devicePixelRatioF()))


def _refresh_item(item, widget, *, column=None):
    if column is None:
        name, role = item.data(ICON_NAME_ROLE), item.data(ICON_COLOR_ROLE)
    else:
        name, role = item.data(column, ICON_NAME_ROLE), item.data(column, ICON_COLOR_ROLE)
    if name:
        value = icon(str(name), color=_color(str(role or "default"), widget))
        item.setIcon(value) if column is None else item.setIcon(column, value)


def set_item_icon(item, name, *, widget, column=None, role="default"):
    if column is None:
        item.setData(ICON_NAME_ROLE, name)
        item.setData(ICON_COLOR_ROLE, role)
    else:
        item.setData(column, ICON_NAME_ROLE, name)
        item.setData(column, ICON_COLOR_ROLE, role)
    _refresh_item(item, widget, column=column)


def refresh_icons(root, theme="dark", accent="#3978f6"):
    """Refresh registered icon widgets/items without rebuilding live controls."""
    global _theme, _accent
    _theme = "light" if theme == "light" else "dark"
    _accent = QColor(accent).name() if QColor(accent).isValid() else "#3978f6"
    root.setProperty("jarvisIconTheme", _theme)
    root.setProperty("jarvisIconAccent", _accent)
    from PySide6.QtGui import QAction
    for action in root.findChildren(QAction):
        name = action.property("jarvisIcon")
        if name:
            role = str(action.property("jarvisIconRole") or "default")
            action.setIcon(icon(name, color=_color(role, root)))
    for widget in [root] + root.findChildren(QWidget):
        name = widget.property("jarvisIcon")
        if name:
            size = int(widget.property("jarvisIconSize") or 18)
            role = str(widget.property("jarvisIconRole") or "default")
            if isinstance(widget, QLabel):
                set_label_icon(widget, name, size=size, role=role)
            elif hasattr(widget, "setIcon"):
                set_button_icon(widget, name, size=size, role=role)
        if isinstance(widget, QComboBox):
            for index in range(widget.count()):
                name = widget.itemData(index, ICON_NAME_ROLE)
                if name:
                    role = str(widget.itemData(index, ICON_COLOR_ROLE) or "default")
                    widget.setItemIcon(index, icon(name, color=_color(role, widget)))
        elif isinstance(widget, QListWidget):
            for index in range(widget.count()):
                _refresh_item(widget.item(index), widget)
        elif isinstance(widget, QTreeWidget):
            def visit(parent):
                for index in range(parent.childCount()):
                    child = parent.child(index)
                    for column in range(widget.columnCount()):
                        _refresh_item(child, widget, column=column)
                    visit(child)
            visit(widget.invisibleRootItem())
