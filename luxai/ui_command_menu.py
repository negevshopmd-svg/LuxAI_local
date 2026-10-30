"""Accessible command popover with the same grouped layout as the library."""
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QMenu

from luxai.icons import icon, theme_color
from luxai.styles import theme_colors


class CommandContextMenu(QMenu):
    """Keep normal QAction keyboard behavior while drawing destructive rows red."""

    def __init__(self, parent=None, *, config=None):
        super().__init__(parent)
        config = config or {}
        self.colors = theme_colors(config.get("ui_theme", "dark"),
                                   config.get("ui_accent", "#3978f6"))
        self.setObjectName("CommandContextMenu")
        self.setProperty("jarvisIconTheme", config.get("ui_theme", "dark"))
        self.setProperty("jarvisIconAccent", self.colors["accent"])
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._danger_actions = set()
        p = self.colors
        self.setStyleSheet(f"""
            QMenu#CommandContextMenu {{background:{p['surface']}; color:{p['text']};
                border:1px solid {p['border']}; border-radius:12px; padding:6px;
                min-width:265px; font-size:13px;}}
            QMenu#CommandContextMenu::item {{padding:8px 22px 8px 34px;
                border-radius:6px; min-height:17px;}}
            QMenu#CommandContextMenu::item:selected {{background:{p['hover']};}}
            QMenu#CommandContextMenu::item:disabled {{color:{p['muted']};}}
            QMenu#CommandContextMenu::icon {{left:10px; width:16px; height:16px;}}
            QMenu#CommandContextMenu::separator {{height:1px; background:{p['border']};
                margin:6px 8px;}}
        """)

    def add_command(self, text, icon_name, callback, *, danger=False, enabled=True):
        color = theme_color("danger", self) if danger else self.colors["text"]
        action = self.addAction(icon(icon_name, color=color), text)
        action.setData({"icon": icon_name, "danger": danger})
        action.setEnabled(enabled)
        action.triggered.connect(callback)
        if danger:
            self._danger_actions.add(action)
        return action

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for action in self._danger_actions:
            rect = self.actionGeometry(action)
            if not rect.isValid() or not action.isVisible():
                continue
            selected = self.activeAction() is action
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.colors["hover"] if selected else self.colors["surface"])
            painter.drawRoundedRect(rect, 6, 6)
            color = theme_color("danger", self) if action.isEnabled() else self.colors["muted"]
            action.icon().paint(painter, QRect(rect.left() + 10, rect.center().y() - 8, 16, 16))
            painter.setPen(QColor(color))
            painter.drawText(rect.adjusted(54, 0, -12, 0),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             action.text())
        painter.end()
