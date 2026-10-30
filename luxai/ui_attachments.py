"""Attachment selection, local previews and explicit file-edit review dialogs."""
from __future__ import annotations

import base64
from pathlib import Path
import threading

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from luxai.chat_attachments import (
    AttachmentError, apply_text_edit, load_attachment, load_attachments,
    propose_text_edit, save_text_copy,
)
from luxai.icons import icon, set_button_icon
from luxai.ui_i18n import get_ui_language, normalize_language


def _t(ru, en, ro, language=None):
    return {"ru": ru, "en": en, "ro": ro}[normalize_language(language or get_ui_language())]


def _plain_label(text="", parent=None):
    result = QLabel(text, parent)
    result.setTextFormat(Qt.TextFormat.PlainText)
    result.setWordWrap(True)
    return result


def _image(item):
    value = QPixmap()
    if getattr(item, "image_data_url", ""):
        try:
            value.loadFromData(base64.b64decode(item.image_data_url.split(",", 1)[1], validate=True))
        except (ValueError, IndexError):
            pass
    return value


class AttachmentPreviewDialog(QDialog):
    def __init__(self, attachment, parent=None):
        super().__init__(parent)
        self.setProperty("i18n_skip", True)
        self.setWindowTitle(attachment.name)
        self.resize(760, 590)
        outer = QVBoxLayout(self)
        name = _plain_label(attachment.name)
        name.setProperty("i18n_skip", True)
        outer.addWidget(name)
        if attachment.kind == "image":
            area = QScrollArea()
            area.setWidgetResizable(True)
            picture = QLabel()
            picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pixmap = _image(attachment)
            picture.setPixmap(pixmap.scaled(960, 800, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
            area.setWidget(picture)
            outer.addWidget(area, 1)
        else:
            body = QPlainTextEdit()
            body.setReadOnly(True)
            body.setPlainText(attachment.text)
            outer.addWidget(body, 1)
        if getattr(attachment, "warnings", ()):
            outer.addWidget(_plain_label("\n".join(attachment.warnings)))
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        outer.addWidget(close)


class AttachmentTray(QFrame):
    """Pinned snapshots, with local asynchronous loading and no uploads."""
    add_requested = Signal()
    changed = Signal()
    loading_changed = Signal(bool)
    error = Signal(str)
    _loaded = Signal(int, object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AttachmentTray")
        self._attachments = ()
        self._loading = False
        self._load_generation = 0
        self._cloud = False
        self._language = get_ui_language()
        self._dialogs = []
        self.setAcceptDrops(True)
        self.setStyleSheet("""
            QFrame#AttachmentTray {background: transparent; border: none;}
            QPushButton#AttachmentAddButton {background: transparent; border: none;}
            QListWidget#AttachmentFiles {background: transparent; border: none;}
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(5)
        row = QHBoxLayout()
        self.controls = row
        row.setSpacing(8)
        self.add_button = QPushButton()
        self.add_button.setObjectName("AttachmentAddButton")
        set_button_icon(self.add_button, "file-plus-corner")
        self.add_button.clicked.connect(self.add_requested.emit)
        row.addWidget(self.add_button)
        self.route_hint = _plain_label()
        self.route_hint.setObjectName("Muted")
        row.addWidget(self.route_hint, 1)
        self.remove_button = QPushButton()
        set_button_icon(self.remove_button, "x")
        self.remove_button.clicked.connect(self.remove_selected)
        row.addWidget(self.remove_button)
        self.files = QListWidget()
        self.files.setObjectName("AttachmentFiles")
        self.files.setViewMode(QListWidget.ViewMode.IconMode)
        self.files.setFlow(QListWidget.Flow.LeftToRight)
        self.files.setWrapping(True)
        self.files.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.files.setMovement(QListWidget.Movement.Static)
        self.files.setGridSize(QSize(150, 105))
        self.files.setIconSize(QSize(58, 58))
        self.files.setSpacing(6)
        self.files.setMaximumHeight(216)
        self.files.setMinimumHeight(108)
        self.files.itemDoubleClicked.connect(self._preview)
        self.files.itemSelectionChanged.connect(self._update_remove_button)
        outer.addWidget(self.files)
        outer.addLayout(row)
        self.files.hide()
        self._loaded.connect(self._on_loaded)
        self.set_language(self._language)

    @property
    def loading(self):
        return self._loading

    def attachments(self):
        return tuple(self._attachments)

    def set_language(self, language):
        self._language = normalize_language(language)
        self.add_button.setIcon(QIcon())  # '+' only, no doubled file-plus glyph
        self.add_button.setText("+")
        self.add_button.setAccessibleName(_t("Прикрепить", "Attach", "Atașează", self._language))
        self.add_button.setToolTip(_t("Добавить фотографии и файлы", "Add photos and files",
                                     "Adaugă fotografii și fișiere", self._language))
        self.remove_button.setIcon(QIcon())
        self.remove_button.setText("×")
        self.remove_button.setAccessibleName(_t("Убрать", "Remove", "Elimină", self._language))
        self.remove_button.setToolTip(_t("Убрать вложение из чата", "Remove attachment from chat",
                                        "Elimină atașamentul din chat", self._language))
        self.files.setToolTip(_t("Двойной щелчок — просмотр вложения", "Double-click to preview an attachment",
                                "Dublu clic pentru a previzualiza un atașament", self._language))
        self._update_hint()
        self._update_remove_button()

    def set_delivery_mode(self, cloud=False):
        self._cloud = bool(cloud)
        self._update_hint()

    def _update_hint(self):
        if self._loading:
            caption = _t("Чтение вложений…", "Reading attachments…", "Se citesc atașamentele…", self._language)
        elif self._cloud:
            caption = _t("При отправке выбранные файлы получит облачный AI.",
                         "Send shares selected files with the configured cloud AI.",
                         "La trimitere, fișierele selectate ajung la AI cloud configurat.", self._language)
        else:
            caption = _t("Вложения обрабатываются локально. Перетащите файлы сюда.",
                         "Attachments are processed locally. Drop files here.",
                         "Atașamentele sunt procesate local. Trage fișierele aici.", self._language)
        self.route_hint.setText(caption)
        self.route_hint.setVisible(bool(self._attachments) or self._loading)

    def _update_remove_button(self):
        self.remove_button.setEnabled(not self._loading and self.files.currentItem() is not None)
        self.remove_button.setVisible(bool(self._attachments))

    def _set_loading(self, value):
        self._loading = bool(value)
        self.add_button.setEnabled(not self._loading)
        self._update_remove_button()
        self._update_hint()
        self.loading_changed.emit(self._loading)

    def add_paths(self, paths):
        if self._loading:
            return False
        paths = tuple(str(path) for path in paths)
        if not paths:
            return False
        self._load_generation += 1
        generation = self._load_generation
        self._set_loading(True)
        # PDF parsing and image validation never block Qt, and selection never
        # performs OCR/model inference or network access.
        def read():
            try:
                loaded, error = load_attachments(paths), ""
            except (AttachmentError, OSError, ValueError) as exc:
                loaded, error = (), str(exc)
            except Exception as exc:
                loaded, error = (), _t("Не удалось прочитать вложение", "Could not read attachment",
                                       "Nu am putut citi atașamentul", self._language) + f" ({type(exc).__name__})"
            try:
                self._loaded.emit(generation, loaded, error)
            except RuntimeError:
                pass  # The containing window was destroyed while reading.
        threading.Thread(target=read, daemon=True, name="JarvisAttachmentRead").start()
        return True

    def _on_loaded(self, generation, loaded, error):
        if generation != self._load_generation:
            return
        self._set_loading(False)
        if error:
            self.error.emit(error)
            return
        try:
            self.add_attachments(loaded)
        except AttachmentError as exc:
            self.error.emit(str(exc))

    def add_attachments(self, attachments):
        by_path = {str(item.path): item for item in self._attachments}
        for item in attachments:
            by_path[str(item.path)] = item
        values = tuple(by_path.values())
        if len(values) > 8 or sum(item.size for item in values) > 20 * 1024 * 1024:
            raise AttachmentError(_t("Не больше 8 файлов общим размером 20 МБ.",
                                     "Use at most 8 files totaling 20 MB.",
                                     "Alege cel mult 8 fișiere, în total 20 MB.", self._language))
        self._attachments = values
        self._refresh()

    def replace_attachment(self, attachment):
        self.add_attachments((attachment,))

    def reload_attachment(self, identifier):
        current = next((item for item in self._attachments if item.id == identifier), None)
        if current is not None:
            return self.add_paths((current.path,))
        return False

    def remove(self, identifier):
        self._attachments = tuple(item for item in self._attachments if item.id != identifier)
        self._refresh()

    def remove_selected(self):
        item = self.files.currentItem()
        if item is not None:
            self.remove(item.data(Qt.ItemDataRole.UserRole))

    def clear(self):
        self._load_generation += 1
        self._set_loading(False)
        self._attachments = ()
        self._refresh()

    def _refresh(self):
        selected = self.files.currentItem()
        selected_id = selected.data(Qt.ItemDataRole.UserRole) if selected is not None else None
        self.files.clear()
        for item in self._attachments:
            caption = item.name
            row = QListWidgetItem(caption)
            row.setData(Qt.ItemDataRole.UserRole, item.id)
            row.setToolTip(item.name + "\n" + item.kind.upper())
            pixmap = _image(item)
            if not pixmap.isNull():
                from PySide6.QtGui import QIcon
                row.setIcon(QIcon(pixmap))
            else:
                row.setIcon(icon("file-text"))
            self.files.addItem(row)
            if item.id == selected_id:
                self.files.setCurrentItem(row)
        self.files.setVisible(bool(self._attachments))
        if self.files.currentItem() is None and self.files.count():
            self.files.setCurrentRow(0)
        self._update_remove_button()
        self.changed.emit()

    def _preview(self, row):
        selected = next((item for item in self._attachments
                         if item.id == row.data(Qt.ItemDataRole.UserRole)), None)
        if selected is None:
            return
        dialog = AttachmentPreviewDialog(selected, self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._dialogs.append(dialog)
        dialog.finished.connect(lambda *_: self._dialogs.remove(dialog) if dialog in self._dialogs else None)
        dialog.show()

    def dragEnterEvent(self, event):
        if not self._loading and event.mimeData().hasUrls() and all(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths and not self._loading:
            self.add_paths(paths)
            event.acceptProposedAction()


class AttachmentEditDialog(QDialog):
    """Review a model proposal; only explicit user clicks can save anything."""
    applied = Signal(object)
    saved_copy = Signal(str)

    def __init__(self, proposal, parent=None):
        super().__init__(parent)
        self.proposal = proposal
        self._language = get_ui_language()
        self.setObjectName("AttachmentEditDialog")
        self.setWindowTitle(_t("Изменения файла", "Review file edits", "Verifică modificările"))
        self.setWindowIcon(icon("file-text"))
        self.resize(850, 650)
        self.setMinimumSize(560, 420)
        outer = QVBoxLayout(self)
        self.title = _plain_label(proposal.attachment.name)
        self.title.setProperty("i18n_skip", True)
        self.title.setObjectName("PageTitle")
        outer.addWidget(self.title)
        self.notice = _plain_label(_t(
            "Проверьте изменения. Исходный файл сохранится только после нажатия «Применить».",
            "Review the changes. The original file is saved only when you select Apply.",
            "Verifică modificările. Originalul se salvează doar când apeși Aplică."))
        self.notice.setObjectName("Muted")
        outer.addWidget(self.notice)
        self.tabs = QTabWidget()
        self.diff_view = QPlainTextEdit()
        self.diff_view.setReadOnly(True)
        self.diff_view.setPlainText(proposal.diff)
        self.tabs.addTab(self.diff_view, _t("Разница", "Changes", "Diferențe"))
        self.original_view = QPlainTextEdit()
        self.original_view.setReadOnly(True)
        self.original_view.setPlainText(proposal.attachment.text)
        self.tabs.addTab(self.original_view, _t("Оригинал", "Original", "Original"))
        self.new_text = QPlainTextEdit()
        self.new_text.setPlainText(proposal.new_text)
        self.new_text.textChanged.connect(self._refresh_diff)
        self.tabs.addTab(self.new_text, _t("Новый текст", "New text", "Text nou"))
        outer.addWidget(self.tabs, 1)
        self.warning = _plain_label()
        self.warning.setProperty("i18n_skip", True)
        outer.addWidget(self.warning)
        self.buttons = QDialogButtonBox()
        self.apply_button = self.buttons.addButton(_t("Применить", "Apply", "Aplică"),
                                                   QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_button.setObjectName("Primary")
        self.copy_button = self.buttons.addButton(_t("Сохранить копию…", "Save copy…", "Salvează o copie…"),
                                                  QDialogButtonBox.ButtonRole.ActionRole)
        self.cancel_button = self.buttons.addButton(_t("Отмена", "Cancel", "Anulează"),
                                                    QDialogButtonBox.ButtonRole.RejectRole)
        self.apply_button.clicked.connect(self.apply_changes)
        self.copy_button.clicked.connect(self.save_copy)
        self.cancel_button.clicked.connect(self.reject)
        outer.addWidget(self.buttons)
        self._update_warning()

    def _current_proposal(self):
        return propose_text_edit((self.proposal.attachment,), self.proposal.attachment.id,
                                 self.new_text.toPlainText())

    def _refresh_diff(self):
        try:
            current = self._current_proposal()
            self.diff_view.setPlainText(current.diff)
            self._update_warning(current)
        except (AttachmentError, ValueError) as exc:
            self.warning.setText(str(exc))
            self.apply_button.setEnabled(False)
            self.copy_button.setEnabled(False)

    def _update_warning(self, proposal=None):
        proposal = proposal or self.proposal
        export_only = bool(getattr(proposal, "export_only", False))
        notes = list(getattr(proposal, "warnings", ()) or ())
        if export_only:
            notes.insert(0, _t("Это изменение можно сохранить только как текстовую копию.",
                               "This change can only be saved as a text copy.",
                               "Această modificare poate fi salvată doar ca o copie text."))
        self.warning.setText("\n".join(notes))
        self.warning.setVisible(bool(notes))
        self.apply_button.setEnabled(not export_only)
        self.copy_button.setEnabled(True)

    def _show_error(self, error):
        QMessageBox.warning(self, _t("Ошибка", "Error", "Eroare"), str(error))

    def apply_changes(self):
        try:
            current = self._current_proposal()
            apply_text_edit(current, confirmed=True)
        except (AttachmentError, OSError, ValueError) as exc:
            self._show_error(exc)
            return
        try:
            updated = load_attachment(current.attachment.path)
        except (AttachmentError, OSError, ValueError):
            self._show_error(_t("Изменения сохранены. Прикрепите файл заново, чтобы обновить просмотр.",
                                "Changes were saved. Attach the file again to refresh its preview.",
                                "Modificările au fost salvate. Atașează fișierul din nou pentru a actualiza previzualizarea."))
            self.accept()
            return
        self.applied.emit(updated)
        self.accept()

    def save_copy(self):
        try:
            current = self._current_proposal()
        except (AttachmentError, ValueError) as exc:
            self._show_error(exc)
            return
        suffix = ".txt" if getattr(current, "export_only", False) else current.attachment.path.suffix
        initial = current.attachment.path.with_name(current.attachment.path.stem + "-edited" + suffix)
        chosen, _ = QFileDialog.getSaveFileName(self, _t("Сохранить копию", "Save a copy", "Salvează o copie"),
                                               str(initial), _t("Файлы", "Files", "Fișiere") + " (*)")
        if not chosen:
            return
        try:
            saved = save_text_copy(current, Path(chosen))
        except (AttachmentError, OSError, ValueError) as exc:
            self._show_error(exc)
            return
        self.saved_copy.emit(str(getattr(saved, "path", saved)))
        self.accept()
