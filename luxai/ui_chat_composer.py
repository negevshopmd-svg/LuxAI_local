"""Expanding chat input with local file/image paste before an explicit Send."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPlainTextEdit

from luxai.clipboard_attachments import (
    ClipboardAttachmentError, ClipboardImageStore, pasted_file_paths,
)
from luxai.ui_i18n import get_ui_language, normalize_language


def _paste_error(code):
    language = normalize_language(get_ui_language())
    messages = {
        "count": ("Вставляйте не больше 8 файлов за раз.",
                  "Paste at most 8 files at a time.",
                  "Lipește cel mult 8 fișiere odată."),
        "paths": ("Не удалось прочитать скопированные пути. Скопируйте файлы заново.",
                  "Could not read the copied file paths. Copy the files again.",
                  "Nu am putut citi căile copiate. Copiază fișierele din nou."),
        "mixed_urls": ("Прикрепить можно только локальные файлы. Вставьте веб-ссылку как текст.",
                       "Only local files can be attached. Paste web links as text.",
                       "Poți atașa doar fișiere locale. Lipește adresele web ca text."),
        "image_size": ("Изображение из буфера слишком большое: до 25 мегапикселей и 10 МБ.",
                       "The clipboard image is too large: use at most 25 megapixels and 10 MB.",
                       "Imaginea din clipboard este prea mare: maximum 25 de megapixeli și 10 MB."),
        "image": ("Не удалось прикрепить изображение из буфера. Скопируйте его заново или выберите файл.",
                  "Could not attach the clipboard image. Copy it again or choose its file.",
                  "Nu am putut atașa imaginea din clipboard. Copiaz-o din nou sau alege fișierul."),
    }
    return messages.get(code, messages["image"])[{"ru": 0, "en": 1, "ro": 2}[language]]


class ChatPromptEdit(QPlainTextEdit):
    returnPressed = Signal()
    paths_pasted = Signal(object)
    attachment_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatMessageField")
        self.setPlaceholderText("Напишите сообщение или команду…")
        self.setTabChangesFocus(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumHeight(43)
        self.setMaximumHeight(148)
        self._clipboard_images = ClipboardImageStore()
        self.destroyed.connect(self._clipboard_images.cleanup)
        self.textChanged.connect(self._resize_to_text)
        self._resize_to_text()

    def text(self):
        return self.toPlainText()

    def setText(self, text):
        self.setPlainText(str(text))
        # QLineEdit.setText positions the caret at the end; keep that behavior
        # for voice/status restores and existing UI integration tests.
        self.setCursorPosition(len(self.toPlainText()))

    def cursorPosition(self):
        """QLineEdit compatibility for existing settings/localization workflows."""
        return self.textCursor().position()

    def setCursorPosition(self, position):
        cursor = self.textCursor()
        cursor.setPosition(max(0, min(int(position), len(self.toPlainText()))))
        self.setTextCursor(cursor)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.returnPressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def canInsertFromMimeData(self, source):
        # QPlainTextEdit's context-menu Paste must also be enabled for an image
        # with no textual representation (for example Windows Snipping Tool).
        return bool(source.hasImage() or source.hasUrls() or
                    source.hasFormat('application/x-qt-windows-mime;value="FileNameW"') or
                    super().canInsertFromMimeData(source))

    def insertFromMimeData(self, source):
        try:
            paths = pasted_file_paths(source)
            if paths:
                self.paths_pasted.emit(list(paths))
                return
            if source.hasImage():
                path = self._clipboard_images.stage(source.imageData())
                self.paths_pasted.emit([str(path)])
                return
        except ClipboardAttachmentError as exc:
            self.attachment_error.emit(_paste_error(exc.code))
            return
        # Ordinary prose, URLs and code keep the native text-paste behavior.
        super().insertFromMimeData(source)

    def release_pasted_files(self, paths):
        """After the tray snapshots a batch, release only our staged PNGs.

        A rejected/busy batch should be released immediately. Source files from
        Explorer are never owned by this widget and are never removed.
        """
        self._clipboard_images.release(paths)

    def _resize_to_text(self):
        # QPlainTextDocumentLayout.documentSize().height() is a line count,
        # not a pixel height. Its block rectangles include wrapped visual lines.
        # Stop at our cap so a very large pasted text does not scan every block.
        layout = self.document().documentLayout()
        content_height = 0
        block = self.document().begin()
        while block.isValid() and content_height < 148:
            content_height += layout.blockBoundingRect(block).height()
            block = block.next()
        height = min(148, max(43, int(content_height) + 20))
        if self.height() != height:
            self.setFixedHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_to_text()
