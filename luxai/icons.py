"""Local SVG icons with sharp Qt rendering and theme-aware widget updates.

Lucide's geometry is bundled under its ISC license. No fonts, network calls or
extra Python dependencies are required. Item metadata preserves selections when
the theme changes; icons never replace visible labels or accessibility text.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPixmap
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
    node = widget
    while node is not None:
        theme = node.property("jarvisIconTheme")
        if theme:
            return str(theme), str(node.property("jarvisIconAccent") or _accent)
        node = node.parent()
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


def theme_color(role="default", widget=None):
    """Expose the current widget's theme color to custom painted controls."""
    return _color(role, widget)


@lru_cache(maxsize=192)
def _svg(name):
    canonical = _ALIASES.get(name, name)
    if not canonical or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in canonical):
        raise ValueError("Invalid icon name")
    path = ASSET_DIR / "jarvis.svg" if canonical == "jarvis" else ASSET_DIR / "lucide" / (canonical + ".svg")
    return path.read_bytes()


class _SvgEngine(QIconEngine):
    def __init__(self, svg):
        super().__init__()
        self.svg = svg

    def clone(self):
        return _SvgEngine(self.svg)

    def paint(self, painter, rect, mode, state):
        renderer = QSvgRenderer(self.svg)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if mode == QIcon.Mode.Disabled:
            painter.setOpacity(painter.opacity() * 0.4)
        side = min(rect.width(), rect.height())
        bounds = QRectF(rect.x() + (rect.width() - side) / 2,
                        rect.y() + (rect.height() - side) / 2, side, side)
        renderer.render(painter, bounds)
        painter.restore()

    def pixmap(self, size, mode, state):
        return self.scaledPixmap(size, mode, state, 1.0)

    def scaledPixmap(self, size, mode, state, scale):
        pixmap = QPixmap(max(1, round(size.width() * scale)), max(1, round(size.height() * scale)))
        pixmap.setDevicePixelRatio(scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, QRectF(0, 0, size.width(), size.height()).toRect(), mode, state)
        painter.end()
        return pixmap

    def actualSize(self, size, mode, state):
        return size


@lru_cache(maxsize=384)
def _colored_icon(name, color):
    svg = _svg(name)
    if name == "jarvis" and color != "#3978f6":
        accent = QColor(color)
        gradient = {
            b"#60a5fa": accent.lighter(130).name().encode("ascii"),
            b"#3978f6": accent.name().encode("ascii"),
            b"#244bcb": accent.darker(135).name().encode("ascii"),
        }
        svg = re.sub(b"#(?:60a5fa|3978f6|244bcb)", lambda match: gradient[match[0]], svg)
    return QIcon(_SvgEngine(svg.replace(b"currentColor", color.encode("ascii"))))


def icon(name, *, color=None, size=20):
    """Return a scalable icon; ``size`` documents its intended widget size."""
    del size  # SVG engine paints at the size requested by Qt, including HiDPI.
    value = QColor(color or _color("accent" if name == "jarvis" else "default"))
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
        if widget.property("jarvisBrandMark"):
            widget.update()
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
