"""Local on-screen button inspection using Windows UI Automation (UIA).

Do NOT guess coordinates with an AI model or OCR. We click only a unique
accessible Button control in the previously inspected application window,
after the user explicitly requests Yes/No and confirms the exact window.
Screenshots remain in this process; they are never sent to cloud providers.
"""
from __future__ import annotations

from dataclasses import dataclass
import ctypes
import io
import os
import re
import sys
import time
from typing import Callable

from luxai.fast_intents import strip_wake_name

BUTTON_NAMES = {
    "yes": {"yes", "y", "да", "да!", "oui", "так", "confirm", "confirmă", "confirm",
            "accept", "acceptă", "accepta"},
    "no": {"no", "нет", "nu", "cancel", "отмена", "отменить", "отклонить"},
}
BUTTON_ALIASES = {
    "yes": {"да", "yes", "da", "confirmar", "confirmă", "confirm", "accept", "ok"},
    "no": {"нет", "no", "nu", "отмена", "cancel"},
}
INSPECT_RE = re.compile(
    r"(?:\b(?:покажи|найди|посмотри|просканируй|увидь|проверь)\b"
    r".{0,70}\b(?:кнопк\w*|диалог\w*|экран\w*)\b"
    r"|\b(?:видишь|видно)\b.{0,50}\b(?:да|нет|кнопк\w*)\b"
    r"|\b(?:show|inspect|find)\b.{0,30}\b(?:buttons?|screen)\b)",
    re.IGNORECASE,
)
BUTTON_COMMAND_RE = re.compile(
    r"^\s*(?:нажми|нажать|нажми\s+на|кликни|кликнуть|"
    r"щелкни|выбери|подтверди|press|click|apasă|apasa)\s+"
    r"(?:(?:на|по)\s+)?(?:кнопк\w*\s+)?"
    r"(да|нет|yes|no|da|nu|ок|ok|отмена|cancel)\s*[.!?]*\s*$",
    re.IGNORECASE,
)
RISKY_TITLE = re.compile(
    r"(?:user account control|контроль учетных записей|"
    r"управление учетными записями|учетные данные windows|"
    r"windows security|безопасность windows|credential|"
    r"smart screen|smartscreen|uac|разрешить внесение изменений)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class VisibleButton:
    label: str
    rect: tuple[int, int, int, int]

    @property
    def center(self) -> tuple[int, int]:
        left, top, right, bottom = self.rect
        return ((left + right) // 2, (top + bottom) // 2)


@dataclass(frozen=True)
class ScreenInspection:
    hwnd: int
    pid: int
    title: str
    buttons: tuple[VisibleButton, ...]
    captured: float
    screenshot: bytes = b""


def is_screen_inspection_request(text: str) -> bool:
    return bool(INSPECT_RE.search(strip_wake_name(text)))


def button_choice(text: str) -> str | None:
    clean = strip_wake_name(text)
    match = BUTTON_COMMAND_RE.fullmatch(clean)
    if not match:
        return None
    phrase = match.group(1).casefold()
    return ("yes" if phrase in {"да", "yes", "da", "ок", "ok"} else "no")


def _normalized_button_name(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "").casefold()).strip(" &._\t\r\n")
    # Win32 UIA may report "&Yes" or "Да (Y)"
    return re.sub(r"\s*\([a-zа-я]\)\s*$", "", value).strip()


def classify_button(text: str) -> str | None:
    value = _normalized_button_name(text)
    if value in BUTTON_NAMES["yes"]:
        return "yes"
    if value in BUTTON_NAMES["no"]:
        return "no"
    return None


def _foreground_hwnd() -> int:
    if sys.platform != "win32":
        return 0
    return int(ctypes.windll.user32.GetForegroundWindow())


def _window_pid(hwnd: int) -> int:
    from ctypes import wintypes
    process = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(
        wintypes.HWND(hwnd), ctypes.byref(process),
    )
    return int(process.value)


def _window_title(hwnd: int) -> str:
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(wintypes.HWND(hwnd), buf, len(buf))
    return buf.value[:255]


def _valid_external_window(hwnd: int) -> tuple[int, str]:
    if sys.platform != "win32":
        raise OSError("Визуальное управление доступно только на Windows.")
    if not hwnd or not ctypes.windll.user32.IsWindow(hwnd):
        raise ValueError("Активное окно не найдено.")
    if not ctypes.windll.user32.IsWindowVisible(hwnd):
        raise ValueError("Окно не видно на экране.")
    pid = _window_pid(hwnd)
    if not pid or pid == os.getpid():
        raise ValueError("Перейдите в другую программу: окно Jarvis не сканируется.")
    title = _window_title(hwnd)
    if not title or RISKY_TITLE.search(title):
        raise ValueError("Защищённое или неизвестное окно не поддерживается.")
    return pid, title


def _read_uia_buttons(hwnd: int) -> tuple[VisibleButton, ...]:
    try:
        import comtypes
        comtypes.CoInitialize()
    except ImportError as exc:
        raise OSError("Нужны pywinauto и comtypes. Запустите Update.bat.") from exc

    try:
        try:
            from pywinauto import Desktop
        except ImportError as exc:
            raise OSError("Не установлена pywinauto. Запустите Update.bat.") from exc

        root = Desktop(backend="uia").window(handle=hwnd).wrapper_object()
        bounds = root.rectangle()
        found: list[VisibleButton] = []
        for button in root.descendants(control_type="Button")[:200]:
            try:
                if not button.is_visible() or not button.is_enabled():
                    continue
                label = button.window_text().strip()
                if classify_button(label) is None:
                    continue
                r = button.rectangle()
                x1, y1, x2, y2 = int(r.left), int(r.top), int(r.right), int(r.bottom)
                if (
                    x1 < bounds.left or y1 < bounds.top
                    or x2 > bounds.right or y2 > bounds.bottom
                    or x2 <= x1 or y2 <= y1
                ):
                    continue
                # Don't let a 1-pixel or full-screen "button" become an
                # arbitrary coordinate selector.
                if not 14 <= x2 - x1 <= 450 or not 12 <= y2 - y1 <= 170:
                    continue
                found.append(VisibleButton(label=label, rect=(x1, y1, x2, y2)))
            except Exception:
                continue
        return tuple(found)
    finally:
        comtypes.CoUninitialize()


def _screenshot_png() -> bytes:
    import mss
    from PIL import Image
    with mss.mss() as screen:
        image = screen.grab(screen.monitors[1])
    picture = Image.frombytes("RGB", image.size, image.rgb)
    picture.thumbnail((1080, 620))
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def inspect_screen_buttons(hwnd: int | None = None, *, include_image=True) -> ScreenInspection:
    target = _foreground_hwnd() if hwnd is None else int(hwnd)
    pid, title = _valid_external_window(target)
    controls = _read_uia_buttons(target)
    screenshot = _screenshot_png() if include_image else b""
    return ScreenInspection(
        hwnd=target, pid=pid, title=title, buttons=controls,
        captured=time.monotonic(), screenshot=screenshot,
    )


def select_unique_button(snapshot: ScreenInspection, choice: str) -> VisibleButton:
    if choice not in ("yes", "no"):
        raise ValueError("Можно выбрать только Да или Нет.")
    found = [b for b in snapshot.buttons if classify_button(b.label) == choice]
    if len(found) != 1:
        if len(found) > 1:
            raise ValueError(
                f"На экране несколько кнопок «{choice}». "
                "Не буду угадывать, какую нажать."
            )
        raise ValueError(
            f"В выбранном окне нет доступной кнопки «{choice}» через UI Automation. "
            "Я не буду угадывать координаты по изображению."
        )
    return found[0]


def click_inspected_button(
    snapshot: ScreenInspection,
    choice: str,
    *,
    confirm: Callable[[str], bool] | None,
) -> str:
    """Click only after explicit confirmation, on same process/window/button.

    Confirmation opens a Jarvis window, so we reactivate and re-inspect
    the original target. Never click a guessed OCR pixel or changed button.
    """
    if not isinstance(snapshot, ScreenInspection):
        return "Сначала скажите «Покажи кнопки на экране»."
    if time.monotonic() - snapshot.captured > 90:
        return "Снимок экрана устарел. Скажите «Покажи кнопки на экране» ещё раз."
    try:
        original = select_unique_button(snapshot, choice)
        pid, title = _valid_external_window(snapshot.hwnd)
        if pid != snapshot.pid or title != snapshot.title:
            return "Окно изменилось с момента снимка. Сначала обновите просмотр."
        if confirm is None or not confirm(
            f"⚠ В окне «{title}» нажать кнопку «{original.label}»?\n"
            "Это действие может подтвердить операцию в другом приложении."
        ):
            return "Нажатие отменено."

        from ctypes import wintypes
        user32 = ctypes.windll.user32
        # Revalidate after the modal approval has been dismissed.
        pid_now, title_now = _valid_external_window(snapshot.hwnd)
        if pid_now != snapshot.pid or title_now != snapshot.title:
            return "Окно изменилось. Клик отменён."
        user32.SetForegroundWindow(wintypes.HWND(snapshot.hwnd))
        time.sleep(0.18)
        if _foreground_hwnd() != snapshot.hwnd:
            return "Не удалось активировать нужное окно Windows. Клик не выполнен."
        new = inspect_screen_buttons(snapshot.hwnd, include_image=False)
        candidate = select_unique_button(new, choice)
        if (
            abs(candidate.center[0] - original.center[0]) > 16
            or abs(candidate.center[1] - original.center[1]) > 16
        ):
            return "Кнопка сместилась. Не нажимаю без нового снимка."
        if _foreground_hwnd() != snapshot.hwnd:
            return "Активное окно изменилось. Клик не выполнен."
        import pyautogui
        pyautogui.moveTo(*candidate.center, duration=0.12)
        if _foreground_hwnd() != snapshot.hwnd:
            return "Активное окно изменилось. Клик не выполнен."
        pyautogui.click(*candidate.center)
        return (
            f"Нажал кнопку «{candidate.label}» в окне «{title}». "
            "Не могу гарантировать, что приложение приняло действие."
        )
    except (ValueError, OSError, RuntimeError) as exc:
        return f"Клик не выполнен: {exc}"
