"""Read-only local AI availability plus observations from actual GGUF replies."""
from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import threading

from PySide6.QtCore import QEvent, QObject, QTimer, Signal, Slot

from luxai.local_ai_health import inference_status, model_identity
from luxai.local_models import GGUF_MAGIC, MIN_GGUF_BYTES, resolve_model_path


def configuration_signature(config):
    return (config.get("local_llm_fallback_enabled", True) is not False,
            str(config.get("llm_model_path", "") or ""))


@dataclass(frozen=True)
class LocalAIStatus:
    state: str
    signature: tuple
    identity: tuple | None = None
    error: str = ""


def inspect_local_ai(config):
    """Read only a header, filesystem metadata and package metadata; no inference."""
    signature = configuration_signature(config)
    if not signature[0]:
        return LocalAIStatus("disabled", signature)
    model = resolve_model_path(signature[1])
    if model is None:
        return LocalAIStatus("no_model", signature)
    identity = model_identity(model)
    try:
        with model.open("rb") as source:
            valid = identity[1] is not None and identity[1] >= MIN_GGUF_BYTES and source.read(4) == GGUF_MAGIC
        if model_identity(model) != identity:
            return LocalAIStatus("checking", signature)
    except OSError:
        valid = False
    if not valid:
        return LocalAIStatus("invalid_model", signature, identity)
    try:
        installed = importlib.util.find_spec("llama_cpp") is not None
    except (ImportError, ValueError):
        installed = False
    if not installed:
        from luxai.local_ai_setup import setup_status
        return LocalAIStatus("preparing" if setup_status() == "installing" else "engine_missing", signature, identity)
    observation = inference_status(identity)
    if observation:
        return LocalAIStatus(observation["state"], signature, identity, observation["code"])
    return LocalAIStatus("available", signature, identity)


def status_text(status):
    """Application-owned source phrases; tr() is applied only at render time."""
    return {
        "checking": ("●  Локальный AI: проверка состояния…", "Проверяю модель и локальный движок без загрузки модели."),
        "disabled": ("●  Локальный AI выключен", "Включите локальный AI и выберите модель в настройках."),
        "no_model": ("●  Локальный AI: модель не выбрана", "Выберите доступный файл .gguf в настройках."),
        "invalid_model": ("●  Локальный AI: файл модели недоступен", "Файл GGUF повреждён или неполон. Проверьте модель в настройках."),
        "preparing": ("●  Локальный AI: движок подготавливается…", "Автоматическая подготовка движка ещё не завершена."),
        "engine_missing": ("●  Локальный AI: движок недоступен", "Движок подготавливается автоматически при запуске и обновлении. Проверьте состояние в настройках."),
        "available": ("●  Локальный AI готов к запуску", "Модель и движок найдены. Работа подтвердится после ответа локальной модели."),
        "working": ("●  Локальный AI готовит ответ…", "Сейчас выполняется запрос к выбранной локальной модели."),
        "success": ("●  Локальный AI работает", "Выбранная локальная модель успешно вернула ответ в этом сеансе."),
        "error": ("●  Локальный AI: последний запрос завершился ошибкой", "Проверьте файл модели и доступную память в настройках."),
    }.get(status.state, ("●  Локальный AI: состояние недоступно", "Не удалось проверить локальную модель. Проверьте настройки."))


class LocalAIStatusMonitor(QObject):
    """One bounded background probe; stale config/results cannot turn status green."""
    changed = Signal(object)
    _ready = Signal(int, object)

    def __init__(self, config_getter, parent=None, *, probe=None):
        super().__init__(parent)
        self._config_getter = config_getter
        self._probe = probe or inspect_local_ai
        self._generation = 0
        self._busy = False
        self._closed = False
        self._requested = False
        self.current = LocalAIStatus("checking", configuration_signature(config_getter()))
        self._ready.connect(self._on_ready)
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self.refresh)

    def watch(self, widget):
        self._watched = widget
        widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is getattr(self, "_watched", None):
            if event.type() == QEvent.Type.Show:
                self._timer.start()
                self.refresh()
            elif event.type() == QEvent.Type.Hide:
                self._timer.stop()
        return super().eventFilter(watched, event)

    @Slot()
    def refresh(self):
        if self._closed:
            return
        config = dict(self._config_getter())
        signature = configuration_signature(config)
        if signature != self.current.signature:
            self._generation += 1
            self.current = LocalAIStatus("checking", signature)
            self.changed.emit(self.current)
        if self._busy:
            self._requested = True
            return
        generation = self._generation
        self._busy = True

        def work():
            try:
                status = self._probe(config)
            except Exception:
                status = LocalAIStatus("unavailable", signature)
            if not self._closed:
                try:
                    self._ready.emit(generation, status)
                except RuntimeError:
                    pass
        threading.Thread(target=work, daemon=True, name="JarvisLocalAIStatus").start()

    @Slot(int, object)
    def _on_ready(self, generation, status):
        self._busy = False
        if self._closed:
            return
        signature = configuration_signature(self._config_getter())
        if generation == self._generation and status.signature == signature:
            self.current = status
            self.changed.emit(status)
        else:
            self._requested = True
        if self._requested:
            self._requested = False
            self.refresh()

    def close(self):
        self._closed = True
        self._generation += 1
        self._timer.stop()
