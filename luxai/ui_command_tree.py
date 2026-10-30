"""Command-library branch painting independent of the Windows native style."""
from __future__ import annotations

from PySide6.QtCore import QPersistentModelIndex, Qt
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractItemView, QTreeWidget

from luxai.styles import theme_colors


class CommandTreeWidget(QTreeWidget):
    """Paint the indentation gutter as part of each row, with plain chevrons.

    Native branch primitives may use the OS highlight palette rather than the
    application's item stylesheet. Keep QTreeWidget's expansion/keyboard logic,
    but draw this small area ourselves so hover cannot create a green block.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._colors = theme_colors()
        self._hovered_index = QPersistentModelIndex()
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

    def set_colors(self, colors):
        self._colors = dict(colors)
        self.viewport().update()

    def mouseMoveEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        current = QPersistentModelIndex(index.siblingAtColumn(0))
        if current != self._hovered_index:
            self._hovered_index = current
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        # A row's child edit/menu button is still inside the same viewport.
        if not self.viewport().rect().contains(self.viewport().mapFromGlobal(QCursor.pos())):
            self._hovered_index = QPersistentModelIndex()
            self.viewport().update()
        super().leaveEvent(event)

    def drawBranches(self, painter, rect, index):
        """Deliberately avoid the platform's PE_IndicatorBranch primitive."""
        row = index.siblingAtColumn(0)
        selected = self.selectionModel().isSelected(row)
        hovered = self._hovered_index == row
        colors = self._colors
        background = colors["selection"] if selected else colors["hover"] if hovered else colors["surface"]
        painter.save()
        painter.setClipRect(rect)
        painter.fillRect(rect, QColor(background))
        if self.model().hasChildren(row):
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(colors["text"] if selected or hovered else colors["muted"]))
            pen.setWidthF(1.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
            cell = min(self.indentation(), rect.width())
            x = rect.left() + (cell - 1) / 2 if rtl else rect.right() - (cell - 1) / 2
            y = rect.center().y() + 0.5
            path = QPainterPath()
            if self.isExpanded(row):
                path.moveTo(x - 3, y - 1.5)
                path.lineTo(x, y + 1.5)
                path.lineTo(x + 3, y - 1.5)
            else:
                direction = -1 if rtl else 1
                path.moveTo(x - 1.5 * direction, y - 3)
                path.lineTo(x + 1.5 * direction, y)
                path.lineTo(x - 1.5 * direction, y + 3)
            painter.drawPath(path)
        painter.restore()
