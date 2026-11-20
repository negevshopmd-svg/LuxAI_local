"""Capture what the PC plays (WASAPI loopback), as 16 kHz mono float32.

Two ways, both only on this computer — nothing is saved or sent:

* process loopback (Windows 10 2004+): the sound of ONE program and its child
  processes;
* system loopback: everything the default speakers play. Jarvis's own voice is
  muted by the caller while it speaks.

Windows converts the audio to 16 kHz mono 16-bit PCM for us
(AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM), exactly what Whisper wants.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys
import threading
import time
from ctypes import POINTER, byref, c_void_p, wintypes

import numpy as np

SAMPLE_RATE = 16000

if sys.platform == "win32":
    import comtypes
    from comtypes import COMMETHOD, GUID, HRESULT, IUnknown, COMObject

    REFERENCE_TIME = ctypes.c_longlong

    class WAVEFORMATEX(ctypes.Structure):
        _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD), ("nSamplesPerSec", wintypes.DWORD),
                    ("nAvgBytesPerSec", wintypes.DWORD), ("nBlockAlign", wintypes.WORD),
                    ("wBitsPerSample", wintypes.WORD), ("cbSize", wintypes.WORD)]

    class IAudioCaptureClient(IUnknown):
        _iid_ = GUID("{C8ADBD64-E71E-48a0-A4DE-185C395CD317}")
        _methods_ = [
            COMMETHOD([], HRESULT, "GetBuffer", (["out"], POINTER(POINTER(ctypes.c_byte)), "data"),
                      (["out"], POINTER(ctypes.c_uint32), "frames"), (["out"], POINTER(wintypes.DWORD), "flags"),
                      (["out"], POINTER(ctypes.c_uint64), "position"), (["out"], POINTER(ctypes.c_uint64), "qpc")),
            COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], ctypes.c_uint32, "frames")),
            COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], POINTER(ctypes.c_uint32), "frames")),
        ]

    class IAudioClient(IUnknown):
        _iid_ = GUID("{1CB9AD4C-DBFA-4c32-B178-C2F568A703B2}")
        _methods_ = [
            COMMETHOD([], HRESULT, "Initialize", (["in"], ctypes.c_int, "mode"), (["in"], wintypes.DWORD, "flags"),
                      (["in"], REFERENCE_TIME, "duration"), (["in"], REFERENCE_TIME, "period"),
                      (["in"], POINTER(WAVEFORMATEX), "format"), (["in"], POINTER(GUID), "session")),
            COMMETHOD([], HRESULT, "GetBufferSize", (["out"], POINTER(ctypes.c_uint32), "frames")),
            COMMETHOD([], HRESULT, "GetStreamLatency", (["out"], POINTER(REFERENCE_TIME), "latency")),
            COMMETHOD([], HRESULT, "GetCurrentPadding", (["out"], POINTER(ctypes.c_uint32), "frames")),
            COMMETHOD([], HRESULT, "IsFormatSupported", (["in"], ctypes.c_int, "mode"),
                      (["in"], POINTER(WAVEFORMATEX), "format"), (["out"], POINTER(POINTER(WAVEFORMATEX)), "closest")),
            COMMETHOD([], HRESULT, "GetMixFormat", (["out"], POINTER(POINTER(WAVEFORMATEX)), "format")),
            COMMETHOD([], HRESULT, "GetDevicePeriod", (["out"], POINTER(REFERENCE_TIME), "default"),
                      (["out"], POINTER(REFERENCE_TIME), "minimum")),
            COMMETHOD([], HRESULT, "Start"),
            COMMETHOD([], HRESULT, "Stop"),
            COMMETHOD([], HRESULT, "Reset"),
            COMMETHOD([], HRESULT, "SetEventHandle", (["in"], wintypes.HANDLE, "event")),
            COMMETHOD([], HRESULT, "GetService", (["in"], POINTER(GUID), "iid"), (["out"], POINTER(c_void_p), "service")),
        ]

    class IActivateAudioInterfaceAsyncOperation(IUnknown):
        _iid_ = GUID("{72A22D78-CDE4-431D-B8CC-843A71199B6D}")
        _methods_ = [
            COMMETHOD([], HRESULT, "GetActivateResult", (["out"], POINTER(HRESULT), "result"),
                      (["out"], POINTER(POINTER(IUnknown)), "interface")),
        ]

    class IActivateAudioInterfaceCompletionHandler(IUnknown):
        _iid_ = GUID("{41D949AB-9862-444A-80F6-C261334DA5EB}")
        _methods_ = [
            COMMETHOD([], HRESULT, "ActivateCompleted",
                      (["in"], POINTER(IActivateAudioInterfaceAsyncOperation), "operation")),
        ]

    class IAgileObject(IUnknown):
        _iid_ = GUID("{94ea2b94-e9cc-49e0-c0ff-ee64ca8f5b90}")
        _methods_ = []

    class _Handler(COMObject):
        _com_interfaces_ = [IActivateAudioInterfaceCompletionHandler, IAgileObject]

        def __init__(self):
            super().__init__()
            self.done = threading.Event()
            self.operation = None

        def ActivateCompleted(self, operation):
            self.operation = operation
            self.done.set()
            return 0

    class _LoopbackParams(ctypes.Structure):
        _fields_ = [("TargetProcessId", wintypes.DWORD), ("ProcessLoopbackMode", ctypes.c_int)]

    class _ActivationParams(ctypes.Structure):
        _fields_ = [("ActivationType", ctypes.c_int), ("ProcessLoopbackParams", _LoopbackParams)]

    class _Blob(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.ULONG), ("pBlobData", c_void_p)]

    class _PropVariant(ctypes.Structure):
        _fields_ = [("vt", wintypes.USHORT), ("r1", wintypes.WORD), ("r2", wintypes.WORD), ("r3", wintypes.WORD),
                    ("blob", _Blob)]

LOOPBACK = 0x00020000
EVENTCALLBACK = 0x00040000
AUTOCONVERTPCM = 0x80000000
SRC_DEFAULT_QUALITY = 0x08000000
INCLUDE_TREE, EXCLUDE_TREE = 0, 1


def _pcm16_mono() -> "WAVEFORMATEX":
    return WAVEFORMATEX(1, 1, SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16, 0)


def _activate_process_loopback(pid: int, mode: int):
    params = _ActivationParams(1, _LoopbackParams(pid, mode))
    variant = _PropVariant()
    variant.vt = 65  # VT_BLOB
    variant.blob = _Blob(ctypes.sizeof(params), ctypes.cast(ctypes.pointer(params), c_void_p))
    handler = _Handler()
    operation = POINTER(IActivateAudioInterfaceAsyncOperation)()
    function = ctypes.windll.mmdevapi.ActivateAudioInterfaceAsync
    function.argtypes = [wintypes.LPCWSTR, POINTER(GUID), POINTER(_PropVariant),
                         POINTER(IActivateAudioInterfaceCompletionHandler),
                         POINTER(POINTER(IActivateAudioInterfaceAsyncOperation))]
    function.restype = HRESULT
    iid = IAudioClient._iid_
    function("VAD\\Process_Loopback", byref(iid), byref(variant),
             handler.QueryInterface(IActivateAudioInterfaceCompletionHandler), byref(operation))
    if not handler.done.wait(5):
        raise RuntimeError("Windows did not activate process loopback")
    result, unknown = operation.GetActivateResult()
    if result != 0 or not unknown:
        raise OSError(f"Process loopback unavailable (0x{result & 0xFFFFFFFF:08X})")
    return unknown.QueryInterface(IAudioClient)


def _activate_system_loopback():
    from pycaw.pycaw import AudioUtilities
    device = AudioUtilities.GetSpeakers()
    raw = getattr(device, "_dev", device)
    unknown = raw.Activate(IAudioClient._iid_, comtypes.CLSCTX_ALL, None)
    return unknown.QueryInterface(IAudioClient)


class LoopbackCapture:
    """Background thread calling ``on_audio(float32 16 kHz mono chunk)``."""

    RETRY_SECONDS = 1.5
    APP_FAILURES_BEFORE_SYSTEM = 3   # then «all PC sound» is used instead of the one program
    FAILURES_BEFORE_REPORT = 3       # only a capture that keeps failing is shown on the bar

    def __init__(self, on_audio, *, app_pid: int = 0, exclude_pid: int = 0, on_error=None, app_name: str = "",
                 on_notice=None):
        self.on_audio = on_audio
        self.on_error = on_error
        self.on_notice = on_notice      # a soft message (e.g. «switched to all PC sound»)
        self.app_pid = app_pid
        self.app_name = app_name        # to find the program again after it restarted (a new pid)
        self.exclude_pid = exclude_pid or os.getpid()
        self.mode = ""
        self._stop = threading.Event()
        self._thread = None
        self.started = threading.Event()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="JarvisLoopback")
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def _open(self):
        """(client, event-driven?) — process loopback first, system loopback as fallback."""
        if self.app_pid:
            client = _activate_process_loopback(self.app_pid, INCLUDE_TREE)
            fmt = _pcm16_mono()
            client.Initialize(0, LOOPBACK | EVENTCALLBACK | AUTOCONVERTPCM | SRC_DEFAULT_QUALITY,
                              2_000_000, 0, byref(fmt), None)
            self.mode = "app"
            return client, True
        # All sound: the speakers' mix. (Excluding Jarvis's process tree would also
        # drop every program Jarvis started, so its own voice is muted by the caller.)
        client = _activate_system_loopback()
        fmt = _pcm16_mono()
        client.Initialize(0, LOOPBACK | AUTOCONVERTPCM | SRC_DEFAULT_QUALITY, 2_000_000, 0, byref(fmt), None)
        self.mode = "system"
        return client, False

    def _run(self):
        """Capture until stopped. Windows audio can fail at any time (0x8000FFFF «catastrophic failure»
        when a program restarts its audio process, AUDCLNT_E_DEVICE_INVALIDATED when the speakers change):
        the capture is reopened instead of stopping the captions for good."""
        ctypes.oledll.ole32.CoInitializeEx(None, 0)  # MTA: the activation callback is agile
        failures = 0
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                try:
                    self._capture_once()
                    return  # stopped normally
                except Exception as error:
                    self.started.set()
                    self._had_error = True
                    _log_capture_error(error, self.mode or ("app" if self.app_pid else "system"))
                    failures = 1 if time.monotonic() - started > 30 else failures + 1  # long runs reset the count
                    if self.app_pid and failures >= self.APP_FAILURES_BEFORE_SYSTEM:
                        self.app_pid = 0  # the one program keeps failing: listen to all PC sound
                        failures = 0
                        if self.on_notice is not None:
                            self.on_notice("system")
                    elif failures >= self.FAILURES_BEFORE_REPORT and self.on_error is not None:
                        self.on_error(f"{type(error).__name__}: {error}")
                    if self._stop.wait(self.RETRY_SECONDS):
                        return
                    if self.app_pid and self.app_name:
                        self.app_pid = app_pid(self.app_name) or self.app_pid  # restarted → new pid
        finally:
            try:
                ctypes.oledll.ole32.CoUninitialize()
            except OSError:
                pass

    def _capture_once(self):
        event = None
        client = None
        try:
            client, event_driven = self._open()
            if event_driven:
                kernel32 = ctypes.windll.kernel32
                kernel32.CreateEventW.restype = wintypes.HANDLE
                event = kernel32.CreateEventW(None, False, False, None)
                client.SetEventHandle(event)
            pointer = client.GetService(byref(IAudioCaptureClient._iid_))
            capture = ctypes.cast(pointer, POINTER(IAudioCaptureClient))
            client.Start()
            self.started.set()
            if getattr(self, "_had_error", False):
                self._had_error = False
                if self.on_notice is not None:
                    self.on_notice("recovered")  # the error on the bar can go away
            silence_until = time.monotonic()
            while not self._stop.is_set():
                if event:
                    ctypes.windll.kernel32.WaitForSingleObject(event, 200)
                else:
                    time.sleep(0.03)
                chunks = []
                while True:
                    size = capture.GetNextPacketSize()
                    if not size:
                        break
                    data, frames, flags, _pos, _qpc = capture.GetBuffer()
                    if frames:
                        if flags & 0x2:  # AUDCLNT_BUFFERFLAGS_SILENT
                            chunks.append(np.zeros(frames, dtype=np.float32))
                        else:
                            raw = ctypes.string_at(data, frames * 2)
                            chunks.append(np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0)
                    capture.ReleaseBuffer(frames)
                if chunks:
                    self.on_audio(np.concatenate(chunks))
                elif not event and time.monotonic() > silence_until:
                    # System loopback delivers nothing while nothing plays: feed silence
                    # so the recogniser can finish the last phrase.
                    self.on_audio(np.zeros(int(SAMPLE_RATE * 0.1), dtype=np.float32))
                    silence_until = time.monotonic() + 0.1
            client.Stop()
        finally:
            if event:
                ctypes.windll.kernel32.CloseHandle(event)
            client = None


def _log_capture_error(error, mode: str) -> None:
    """logs/captions_error.log: what failed, for diagnosis (never audio or text)."""
    import traceback
    try:
        folder = Path(__file__).resolve().parents[1] / "logs"
        folder.mkdir(exist_ok=True)
        path = folder / "captions_error.log"
        if path.is_file() and path.stat().st_size > 256 * 1024:
            path.unlink()
        with path.open("a", encoding="utf-8") as stream:
            stream.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} capture ({mode}): {type(error).__name__}: {error}\n")
            stream.write("".join(traceback.format_exception(type(error), error, error.__traceback__)[-3:]))
    except OSError:
        pass


# Windows parts that have windows but never play sound worth captioning.
SYSTEM_APPS = frozenset({
    "explorer.exe", "applicationframehost.exe", "textinputhost.exe", "shellexperiencehost.exe",
    "searchhost.exe", "searchapp.exe", "startmenuexperiencehost.exe", "systemsettings.exe",
    "taskmgr.exe", "lockapp.exe", "dwm.exe", "ctfmon.exe", "nvidia share.exe",
})


def _root(process):
    """The top process of a program (Chrome/Discord run many with one name)."""
    name, root = process.name(), process
    while True:
        parent = root.parent()
        if parent is None or parent.name() != name:
            return root
        root = parent


def _window_pids() -> set[int]:
    """Processes that own a visible, titled top-level window."""
    import ctypes
    from ctypes import wintypes
    # A private user32 with exact types (the shared one may carry other signatures).
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    for name in ("IsWindowVisible", "GetWindowTextLengthW"):
        getattr(user32, name).argtypes = [wintypes.HWND]
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    pids: set[int] = set()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd, _param):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0 \
                and not user32.GetWindow(hwnd, 4):  # GW_OWNER: skip dialogs/tool windows of others
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            pids.add(pid.value)
        return True

    user32.EnumWindows(collect, 0)
    return pids


def audio_apps() -> list[tuple[str, int]]:
    """(exe name, root pid) of programs to listen to: those playing sound now
    first, then every other open program with a window (a browser has no audio
    session until it plays something, so it must be listed anyway)."""
    if sys.platform != "win32":
        return []
    import psutil
    own = os.getpid()
    playing: dict[str, int] = {}
    windowed: dict[str, int] = {}
    try:
        from pycaw.pycaw import AudioUtilities
        sessions = AudioUtilities.GetAllSessions()
    except Exception:
        sessions = []
    for session in sessions:
        process = getattr(session, "Process", None)
        if process is None or process.pid == own:
            continue
        try:
            root = _root(process)
            playing.setdefault(root.name(), root.pid)
        except (psutil.Error, OSError):
            continue
    try:
        pids = _window_pids()
    except Exception:
        pids = set()
    for pid in pids:
        if pid in (0, own):
            continue
        try:
            root = _root(psutil.Process(pid))
            name = root.name()
        except (psutil.Error, OSError):
            continue
        if name.casefold() in SYSTEM_APPS or name.casefold() in ("jarvis.exe", "python.exe", "pythonw.exe"):
            continue
        if name not in playing:
            windowed.setdefault(name, root.pid)
    order = lambda item: item[0].casefold()
    return sorted(playing.items(), key=order) + sorted(windowed.items(), key=order)


def app_pid(name: str) -> int:
    """Root pid of the running program ``name`` (exe), 0 when not running."""
    if not name:
        return 0
    for exe, pid in audio_apps():
        if exe.casefold() == name.casefold():
            return pid
    import psutil
    for process in psutil.process_iter(["name", "pid"]):
        try:
            if (process.info["name"] or "").casefold() == name.casefold():
                root = process
                while root.parent() is not None and root.parent().name().casefold() == name.casefold():
                    root = root.parent()
                return root.pid
        except (psutil.Error, OSError):
            continue
    return 0
