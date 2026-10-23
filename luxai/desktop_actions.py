"""Trusted actions selected in Jarvis's graphical command editor.

Only manually saved terminal commands can be executed, after displaying the
full command and explicit approval. Online AI never supplies executable shell
scripts. Keyboard/mouse operations are prevalidated GUI-created macro steps.
"""
from __future__ import annotations

import base64
import ctypes
import os
import subprocess
import sys
import threading
import time
import uuid
import urllib.parse
import webbrowser
from pathlib import Path

from luxai.action_catalog import HOTKEYS, validate_step


def _type_unicode_windows(text: str):
    """Type Cyrillic/Unicode using Windows SendInput (without clipboard edits)."""
    if sys.platform != "win32":
        raise OSError("Ввод текста доступен только на Windows")
    from ctypes import wintypes

    ULONG_PTR = ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = (
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        )

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = (
            ("dx", wintypes.LONG), ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR),
        )

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = (("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                    ("wParamH", wintypes.WORD))

    class INPUT_UNION(ctypes.Union):
        _fields_ = (("ki", KEYBDINPUT), ("mi", MOUSEINPUT),
                    ("hi", HARDWAREINPUT))

    class INPUT(ctypes.Structure):
        _fields_ = (("type", wintypes.DWORD), ("u", INPUT_UNION))

    user32 = ctypes.windll.user32
    send = user32.SendInput
    send.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    send.restype = wintypes.UINT
    # UTF-16 code units (including both halves of surrogate pairs).
    encoded = text.encode("utf-16-le")
    if len(encoded) // 2 > 350:
        raise ValueError("Слишком длинный текст")
    events = []
    for position in range(0, len(encoded), 2):
        code_unit = int.from_bytes(encoded[position:position + 2], "little")
        for flags in (0x0004, 0x0004 | 0x0002):  # UNICODE, KEYUP
            event = INPUT()
            event.type = 1
            event.u.ki = KEYBDINPUT(0, code_unit, flags, 0, 0)
            events.append(event)
    if events:
        array = (INPUT * len(events))(*events)
        count = send(len(array), array, ctypes.sizeof(INPUT))
        if count != len(array):
            raise OSError("Windows rejected keyboard input")


_mouse_hold_lock = threading.Lock()


def _launch_user_script(action: str, command: str) -> str:
    """Launch an explicitly configured script with user privileges only.

    Cloud plans and voice-wizard plans never carry these actions. Caller
    revalidates the manually saved step and requires explicit confirmation
    of the complete command on every launch.
    """
    if sys.platform != "win32":
        raise OSError("CMD и PowerShell доступны только на Windows")
    args = (
        ["cmd.exe", "/D", "/C", command]
        if action == "run_cmd"
        else ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command]
    )
    completed = subprocess.run(
        args,
        cwd=str(Path.home()),
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=25,
        check=False,
    )
    if completed.returncode != 0:
        raise OSError(f"Команда завершилась с ошибкой (код {completed.returncode}).")
    return "Команда выполнена в Windows."



def _mouse_hold(button: str, seconds: int):
    """Always release mouse even if application closes during a hold."""
    if not _mouse_hold_lock.acquire(blocking=False):
        raise RuntimeError("Другое удержание мыши ещё выполняется")

    import pyautogui as gui

    def release():
        try:
            gui.mouseDown(button=button)
            try:
                time.sleep(seconds)
            finally:
                gui.mouseUp(button=button)
        finally:
            _mouse_hold_lock.release()

    threading.Thread(target=release, daemon=True, name="JarvisMouseRelease").start()


def _play_mci_mp3(path: str):
    """Play user-selected MP3 via native Windows MCI asynchronously."""
    winmm = ctypes.windll.winmm
    alias = "jarvis_" + uuid.uuid4().hex[:15]
    command = f'open "{path}" type mpegvideo alias {alias}'
    if winmm.mciSendStringW(command, None, 0, None):
        raise OSError("Не удалось открыть MP3 через Windows MCI")
    if winmm.mciSendStringW(f"play {alias}", None, 0, None):
        winmm.mciSendStringW(f"close {alias}", None, 0, None)
        raise OSError("Не удалось воспроизвести MP3")

    def close_after_playback():
        buffer = ctypes.create_unicode_buffer(128)
        try:
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                time.sleep(0.5)
                if winmm.mciSendStringW(
                    f"status {alias} mode", buffer, len(buffer), None
                ):
                    break
                if buffer.value.lower() not in {"playing", "seeking"}:
                    break
        finally:
            winmm.mciSendStringW(f"close {alias}", None, 0, None)

    threading.Thread(
        target=close_after_playback, daemon=True, name="JarvisMP3",
    ).start()


def _app_volume(target: str):
    """Set current audio session volume for a known selected application."""
    app, value = target.split(":", 1)
    processes = {
        "telegram": ("telegram.exe",), "discord": ("discord.exe",),
        "steam": ("steam.exe", "steamwebhelper.exe"),
        "chrome": ("chrome.exe",), "firefox": ("firefox.exe",),
        "edge": ("msedge.exe",), "spotify": ("spotify.exe",),
    }
    if app not in processes:
        raise OSError("Для этого приложения нет звуковой сессии")
    try:
        import comtypes
        from pycaw.pycaw import AudioUtilities
    except ImportError as exc:
        raise OSError("Установите зависимости pycaw и comtypes через Update.bat") from exc

    comtypes.CoInitialize()
    try:
        sessions = AudioUtilities.GetAllSessions()
        matched = 0
        for session in sessions:
            try:
                if session.Process and session.Process.name().casefold() in processes[app]:
                    session.SimpleAudioVolume.SetMasterVolume(int(value) / 100, None)
                    matched += 1
            except (OSError, AttributeError):
                continue
        if matched == 0:
            raise OSError("Приложение не запущено или нет активного аудиопотока")
    finally:
        comtypes.CoUninitialize()


def _monitor_power(on: bool):
    if sys.platform != "win32":
        raise OSError("Управление экраном доступно только на Windows")
    SMTO_ABORTIFHUNG = 0x0002
    result = ctypes.c_size_t()
    ctypes.windll.user32.SendMessageTimeoutW(
        0xFFFF, 0x0112, 0xF170, -1 if on else 2,
        SMTO_ABORTIFHUNG, 1500, ctypes.byref(result),
    )
    # Windows may prevent the monitor from turning on/off depending on
    # hardware and power policy; SendMessage is a best-effort request.


def _female_sapi(text: str):
    if sys.platform != "win32":
        raise OSError("Системная озвучка доступна только на Windows")
    encoded_text = base64.b64encode(text.encode("utf-8")).decode("ascii")
    # User text is passed as a base64 literal, not executable PowerShell code.
    code = (
        "Add-Type -AssemblyName System.Speech;"
        "$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$voice.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::Female);"
        "$voice.Speak([Text.Encoding]::UTF8.GetString("
        f"[Convert]::FromBase64String('{encoded_text}')));"
        "$voice.Dispose();"
    )
    subprocess.Popen(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
         "-EncodedCommand", base64.b64encode(code.encode("utf-16-le")).decode("ascii")],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def execute_desktop_step(raw: dict) -> str:
    """Execute one saved, validated local action after confirmation.

    CMD, PowerShell and file launching are not available to cloud plan schemas.
    Long playback and mouse-hold actions are queued, avoiding UI blocking.
    """
    step = validate_step(raw)
    action, target = step["action"], step["target"]

    if action == "noop":
        return ""
    if action == "open_website":
        if not webbrowser.open(target, new=2):
            raise OSError("Не удалось открыть сайт")
        return "Открыл сайт."
    if action in {"search_web", "open_first_result"}:
        params = {"q": target}
        if action == "open_first_result":
            params["btnI"] = "I"
        url = "https://www.google.com/search?" + urllib.parse.urlencode(params)
        if not webbrowser.open(url, new=2):
            raise OSError("Не удалось открыть поисковик")
        return (
            "Открываю первый результат через поиск Google."
            if action == "open_first_result" else
            "Открыл результаты поиска."
        )
    if action in {"run_cmd", "run_powershell"}:
        return _launch_user_script(action, target)
    if action == "run_file":
        if sys.platform != "win32":
            raise OSError("Открытие пользовательских файлов доступно только на Windows")
        os.startfile(target)
        return "Запускаю выбранный файл."
    if action in {"speak_text", "speak_ready", "speak_done"}:
        return {
            "speak_text": target,
            "speak_ready": "Вас понял, сэр.",
            "speak_done": "Всё готово, сэр.",
        }[action]
    if action == "voice_male":
        return target  # Jarvis's normal response TTS reads this at macro completion.
    if action == "voice_female":
        _female_sapi(target)
        return "Запущена женская системная озвучка."
    if action in {"play_mp3", "play_wav"}:
        if sys.platform != "win32":
            raise OSError("Воспроизведение файлов доступно только на Windows")
        if not Path(target).is_file():
            raise FileNotFoundError("Аудиофайл отсутствует")
        if action == "play_wav":
            import winsound
            winsound.PlaySound(
                target,
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
        else:
            _play_mci_mp3(target)
        return "Воспроизвожу аудиофайл."
    if action in {"monitor_on", "monitor_off"}:
        _monitor_power(on=action == "monitor_on")
        return "Команда управления монитором отправлена Windows."
    if action == "sleep_pc":
        if sys.platform != "win32":
            raise OSError("Спящий режим поддерживается только на Windows")
        if not ctypes.windll.powrprof.SetSuspendState(False, False, False):
            raise OSError("Windows не разрешила спящий режим")
        return "Компьютер переведён в спящий режим."
    if action == "lock_screen":
        if sys.platform != "win32":
            raise OSError("Блокировка экрана доступна только на Windows")
        if not ctypes.windll.user32.LockWorkStation():
            raise OSError("Не удалось заблокировать экран")
        return "Экран заблокирован."
    if action == "app_volume":
        if sys.platform != "win32":
            raise OSError("Громкость приложения поддерживается только на Windows")
        _app_volume(target)
        return "Громкость приложения изменена."

    if sys.platform != "win32":
        raise OSError("Это действие поддерживается только на Windows")

    if action == "type_text":
        _type_unicode_windows(target)
        return "Текст введён."

    import pyautogui as gui
    gui.FAILSAFE = True
    gui.PAUSE = 0.06
    if action == "hotkey":
        gui.hotkey(*HOTKEYS[target], interval=0.07)
        return f"Нажато: {target.upper()}."
    if action == "key_sequence":
        # Validated characters only; no shell, scripts or arbitrary shortcuts.
        gui.press(target.split(","), interval=0.08)
        return "Клавиши нажаты по очереди."
    if action == "press_key":
        gui.press(target)
        return f"Нажата клавиша {target.upper()}."
    if action == "press_enter":
        gui.press("enter")
        return "Нажат Enter."
    if action == "save_document":
        gui.hotkey("ctrl", "s", interval=0.08)
        return "Нажато Ctrl+S."
    if action == "mouse_right_click":
        gui.click(button="right")
        return "Правый клик выполнен."
    if action == "mouse_click":
        gui.click()
        return "Левый клик выполнен."
    if action == "mouse_double_click":
        gui.doubleClick(interval=0.14)
        return "Двойной клик выполнен."
    if action == "mouse_middle_click":
        gui.click(button="middle")
        return "Клик колёсиком выполнен."
    if action == "mouse_scroll":
        gui.scroll(int(target))
        return "Прокрутка выполнена."
    if action == "mouse_move":
        x, y = (int(part) for part in target.split(","))
        if not gui.onScreen(x, y):
            raise ValueError("Координаты за пределами экрана")
        gui.moveTo(x, y, duration=0.15)
        return "Курсор перемещён."
    if action in ("mouse_hold", "mouse_right_hold"):
        _mouse_hold("right" if action == "mouse_right_hold" else "left", int(target))
        return "Кнопка мыши временно удерживается."
    if action == "volume_up":
        gui.press("volumeup", presses=2, interval=0.05)
        return "Громкость увеличена."
    if action == "volume_down":
        gui.press("volumedown", presses=2, interval=0.05)
        return "Громкость уменьшена."
    raise ValueError("Действие не поддерживается исполнителем")
