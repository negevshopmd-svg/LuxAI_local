"""Integrated window header with native move/resize and accessible controls."""
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from luxai.icons import set_button_icon
from luxai.ui_i18n import tr


class WindowHeader(QWidget):
    def __init__(self, owner, title, microphone, parent=None):
        super().__init__(parent)
        self._owner = owner
        self._drag_offset = None
        self.setObjectName("WindowHeader")
        self.setStyleSheet("QWidget#WindowHeader {background:transparent;}")
        row = QHBoxLayout(self)
        row.setContentsMargins(24, 8, 8, 8)
        row.setSpacing(0)
        self.leading = QWidget()
        self.leading.setObjectName("HeaderLeading")
        self.leading.setStyleSheet("QWidget#HeaderLeading {background:transparent;}")
        leading = QHBoxLayout(self.leading)
        leading.setContentsMargins(0, 0, 0, 0)
        leading.setSpacing(12)
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        leading.addWidget(title)
        leading.addStretch(1)
        leading.addWidget(microphone)
        row.addWidget(self.leading)
        row.addStretch(1)
        self.minimize_button = self._button("minus", owner.showMinimized)
        self.maximize_button = self._button("window-maximize", self.toggle_maximized)
        self.close_button = self._button("x", owner.close, close=True)
        self.close_button.installEventFilter(self)
        for button in (self.minimize_button, self.maximize_button, self.close_button):
            row.addWidget(button)
        self.set_leading_width(440)
        self.refresh_labels()

    def eventFilter(self, watched, event):
        if watched is self.close_button:
            if event.type() == QEvent.Type.Enter:
                set_button_icon(self.close_button, "x", size=17, role="white")
            elif event.type() == QEvent.Type.Leave:
                set_button_icon(self.close_button, "x", size=17)
        return super().eventFilter(watched, event)

    def _button(self, name, callback, *, close=False):
        button = QPushButton()
        button.setObjectName("WindowClose" if close else "WindowControl")
        button.setFixedSize(42, 40)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        set_button_icon(button, name, size=17)
        button.clicked.connect(callback)
        return button

    def set_leading_width(self, width):
        self.leading.setFixedWidth(max(300, int(width)))

    def refresh_labels(self):
        self.setAccessibleName(tr("Переместить окно"))
        for button, source in (
            (self.minimize_button, "Свернуть окно"),
            (self.maximize_button, "Восстановить" if self._owner.isMaximized() else "Развернуть"),
            (self.close_button, "Закрыть"),
        ):
            button.setToolTip(tr(source))
            button.setAccessibleName(tr(source))
        set_button_icon(self.maximize_button, "copy" if self._owner.isMaximized() else "window-maximize", size=17)

    def toggle_maximized(self):
        if self._owner.isMaximized():
            self._owner.showNormal()
        else:
            self._owner.showMaximized()
        self.refresh_labels()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._owner.windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
            if not self._owner.isMaximized():
                self._drag_offset = event.globalPosition().toPoint() - self._owner.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._owner.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class _ResizeHandle(QWidget):
    def __init__(self, owner, edges):
        super().__init__(owner)
        self._owner, self.edges = owner, edges
        self._origin = self._geometry = None
        self.setObjectName("WindowResizeHandle")
        self.setStyleSheet("background:transparent;border:none;")
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        horizontal = bool(edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
        vertical = bool(edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
        if horizontal and vertical:
            diagonal = edges in (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.Edge.RightEdge | Qt.Edge.BottomEdge)
            cursor = Qt.CursorShape.SizeFDiagCursor if diagonal else Qt.CursorShape.SizeBDiagCursor
        else:
            cursor = Qt.CursorShape.SizeHorCursor if horizontal else Qt.CursorShape.SizeVerCursor
        self.setCursor(cursor)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        handle = self._owner.windowHandle()
        if handle is None or not handle.startSystemResize(self.edges):
            self._origin = event.globalPosition().toPoint()
            self._geometry = QRect(self._owner.geometry())
        event.accept()

    def mouseMoveEvent(self, event):
        if self._origin is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return super().mouseMoveEvent(event)
        delta = event.globalPosition().toPoint() - self._origin
        rect = QRect(self._geometry)
        if self.edges & Qt.Edge.LeftEdge:
            rect.setLeft(min(rect.left() + delta.x(), rect.right() - self._owner.minimumWidth() + 1))
        if self.edges & Qt.Edge.RightEdge:
            rect.setRight(max(rect.right() + delta.x(), rect.left() + self._owner.minimumWidth() - 1))
        if self.edges & Qt.Edge.TopEdge:
            rect.setTop(min(rect.top() + delta.y(), rect.bottom() - self._owner.minimumHeight() + 1))
        if self.edges & Qt.Edge.BottomEdge:
            rect.setBottom(max(rect.bottom() + delta.y(), rect.top() + self._owner.minimumHeight() - 1))
        self._owner.setGeometry(rect)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._origin = self._geometry = None
        super().mouseReleaseEvent(event)


class WindowChrome(QObject):
    """Keep frameless windows resizable without intercepting content clicks."""
    def __init__(self, owner, header):
        super().__init__(owner)
        self.owner, self.header = owner, header
        left, right, top, bottom = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        self.handles = [_ResizeHandle(owner, edges) for edges in (
            left, right, top, bottom, left | top, right | top, left | bottom, right | bottom,
        )]
        owner.installEventFilter(self)
        self.update_geometry()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.WindowStateChange):
            self.update_geometry()
            self.header.refresh_labels()
        return super().eventFilter(watched, event)

    def update_geometry(self):
        border, width, height = 5, self.owner.width(), self.owner.height()
        rects = (
            (0, border, border, height - 2 * border),
            (width - border, border, border, height - 2 * border),
            (border, 0, width - 2 * border, border),
            (border, height - border, width - 2 * border, border),
            (0, 0, border, border), (width - border, 0, border, border),
            (0, height - border, border, border), (width - border, height - border, border, border),
        )
        resize_enabled = not (self.owner.isMaximized() or self.owner.isFullScreen())
        for handle, rect in zip(self.handles, rects):
            handle.setGeometry(*rect)
            handle.setVisible(resize_enabled)
            handle.raise_()
