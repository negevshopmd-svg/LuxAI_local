"""Which game is running (0.4.3y), for the status island: name, icon, banner, since when.

Everything is local and read-only: the foreground window's program, the Steam
libraries on this PC (``libraryfolders.vdf`` + ``appmanifest_*.acf`` give the
real game name) and Steam's own picture cache (``appcache/librarycache``: the
small icon and the header banner). Nothing is downloaded or saved. Runs on the
island probe thread, never on the Qt UI thread.

A program counts as a game when its .exe lives in a Steam / Epic / GOG / Riot /
Ubisoft / EA / Battle.net / Xbox games folder, when its name is in the user's
own list, or when Windows says a Direct3D program runs full screen (browsers
and video players excepted). Once found, a game stays «running» until its
process ends, even while you alt-tab.
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

GAME_FOLDERS = tuple("\\" + name.replace("/", "\\") + "\\" for name in (
    "steamapps/common", "epic games", "gog galaxy/games", "gog games", "riot games", "ubisoft game launcher/games",
    "ea games", "electronic arts", "battle.net", "xboxgames", "games", "steamlibrary", "rockstar games",
    "wargaming.net", "minecraft"))
# Never games, even full screen: browsers (video full screen), players, Office, the shell, launchers themselves.
NOT_GAMES = {
    "chrome", "msedge", "firefox", "opera", "opera_gx", "brave", "vivaldi", "yandex", "browser", "iexplore",
    "vlc", "mpc-hc", "mpc-hc64", "mpc-be64", "potplayer", "potplayermini64", "mpv", "wmplayer", "video.ui",
    "powerpnt", "winword", "excel", "acrord32", "explorer", "applicationframehost", "searchhost", "startmenuexperiencehost",
    "steam", "steamwebhelper", "epicgameslauncher", "galaxyclient", "riotclientservices", "battle.net", "eadesktop",
    "upc", "ubisoftconnect", "discord", "obs64", "obs32", "jarvis", "python", "pythonw", "snippingtool", "screenclippinghost",
    "unitycrashhandler64", "crashreporter", "easyanticheat", "beservice", "vgc", "textinputhost",
    "epicwebhelper", "unrealcefsubprocess", "crashreportclient", "riotclientux", "leagueclient", "leagueclientux",
    "galaxyclient helper", "eabackgroundservice", "socialclubhelper", "launcher", "updater", "uninstall", "unins000",
}
SUFFIXES = re.compile(r"(?i)[-_ ]?(win64|win32|x64|x86|shipping|dx11|dx12|vulkan|launcher|client|game)$")


def exe_stem(path: str) -> str:
    return Path(str(path or "")).stem.casefold()


def readable_name(path: str) -> str:
    """«RDR2.exe» → «RDR2», «HogwartsLegacy-Win64-Shipping» → «HogwartsLegacy»."""
    stem = Path(str(path or "")).stem
    for _ in range(3):
        stem = SUFFIXES.sub("", stem)
    return stem.replace("_", " ").strip() or Path(str(path or "")).stem


def in_game_folder(path: str) -> bool:
    lowered = str(path or "").casefold().replace("/", "\\")
    return any(folder in lowered for folder in GAME_FOLDERS) and "\\windows\\" not in lowered[:12]


def parse_user_list(value: str) -> set[str]:
    return {exe_stem(item.strip()) for item in str(value or "").replace(",", "\n").splitlines() if item.strip()}


# --- Steam -------------------------------------------------------------------------------------

def _vdf_values(text: str, key: str) -> list[str]:
    return [match.replace("\\\\", "\\") for match in re.findall(r'"%s"\s+"([^"]*)"' % re.escape(key), text, re.I)]


class SteamIndex:
    """installdir → (appid, name) for every Steam library on this PC; re-read at most every 10 minutes."""

    def __init__(self, steam_root: str | None = None):
        self._root = steam_root
        self.games: dict[str, tuple[str, str]] = {}
        self.read_at = 0.0

    def root(self) -> Path | None:
        if self._root:
            return Path(self._root)
        if sys.platform != "win32":
            return None
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                value = winreg.QueryValueEx(key, "SteamPath")[0]
            return Path(value) if value else None
        except OSError:
            return None

    def refresh(self, force: bool = False):
        if not force and self.games and time.monotonic() - self.read_at < 600:
            return
        self.read_at = time.monotonic()
        root = self.root()
        if root is None:
            return
        libraries = [root]
        try:
            text = (root / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
            libraries += [Path(path) for path in _vdf_values(text, "path")]
        except OSError:
            pass
        games = {}
        for library in dict.fromkeys(libraries):
            try:
                manifests = list((library / "steamapps").glob("appmanifest_*.acf"))[:2000]
            except OSError:
                continue
            for manifest in manifests:
                try:
                    text = manifest.read_text(encoding="utf-8", errors="replace")[:20000]
                except OSError:
                    continue
                appid, name, folder = (_vdf_values(text, key)[:1] for key in ("appid", "name", "installdir"))
                if appid and name and folder:
                    games[folder[0].casefold()] = (appid[0], name[0])
        self.games = games

    def name_of(self, appid: str) -> str:
        self.refresh()
        return next((name for found, name in self.games.values() if found == str(appid)), "")

    def find(self, exe: str) -> tuple[str, str] | None:
        lowered = str(exe or "").replace("/", "\\")
        match = re.search(r"(?i)\\steamapps\\common\\([^\\]+)", lowered)
        if not match:
            return None
        self.refresh()
        found = self.games.get(match.group(1).casefold())
        if found is None and time.monotonic() - self.read_at > 30:
            self.refresh(force=True)  # a game installed a minute ago
            found = self.games.get(match.group(1).casefold())
        return found

    def pictures(self, appid: str) -> tuple[bytes, bytes]:
        """(small icon, header banner) from Steam's local picture cache, if it has them."""
        root = self.root()
        if root is None or not str(appid).isdigit():
            return b"", b""
        folder = root / "appcache" / "librarycache" / str(appid)
        icon = banner = b""
        try:
            files = [path for path in folder.rglob("*") if path.is_file()][:60]
        except OSError:
            files = []
        for path in files:
            name = path.name.casefold()
            if not icon and re.fullmatch(r"[0-9a-f]{40}\.jpg", name) and path.parent == folder:
                icon = _read_small(path, 200_000)
            if name in ("header.jpg", "library_header.jpg") and not banner:
                banner = _read_small(path, 2_000_000)
        if not banner:
            hero = next((path for path in files if path.name.casefold() == "library_hero.jpg"), None)
            banner = _read_small(hero, 2_000_000) if hero else b""
        return icon, banner


def _read_small(path: Path, limit: int) -> bytes:
    try:
        if path.stat().st_size > limit:
            return b""
        return path.read_bytes()
    except OSError:
        return b""


# --- Windows ------------------------------------------------------------------------------------

def foreground_pid() -> int:
    if sys.platform != "win32":
        return 0
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return 0
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def fullscreen_state() -> int:
    """SHQueryUserNotificationState: 3 = Direct3D full screen, 2 = busy (a full-screen window), 0 = unknown."""
    if sys.platform != "win32":
        return 0
    import ctypes
    state = ctypes.c_int(0)
    try:
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return 0
    except (OSError, AttributeError):
        return 0
    return int(state.value)


def file_description(path: str) -> str:
    """The «File description» of an .exe (what Task Manager shows), or ""."""
    if sys.platform != "win32" or not path:
        return ""
    import ctypes
    try:
        version = ctypes.WinDLL("version")
        size = version.GetFileVersionInfoSizeW(str(path), None)
        if not size or size > 4_000_000:
            return ""
        data = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(str(path), 0, size, data):
            return ""
        pointer, length = ctypes.c_void_p(), ctypes.c_uint()
        if not version.VerQueryValueW(data, "\\VarFileInfo\\Translation", ctypes.byref(pointer), ctypes.byref(length)) \
                or length.value < 4:
            return ""
        lang, codepage = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_ushort * 2)).contents
        key = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\FileDescription"
        if not version.VerQueryValueW(data, key, ctypes.byref(pointer), ctypes.byref(length)) or not length.value:
            return ""
        value = ctypes.wstring_at(pointer, length.value).strip("\x00 ").strip()
        return value[:60]
    except Exception:
        return ""


# --- the detector -------------------------------------------------------------------------------

class GameDetector:
    """``poll()`` once a second → the running game as a plain dict, or None."""

    def __init__(self, steam: SteamIndex | None = None, process_info=None):
        self.steam = steam or SteamIndex()
        self.process_info = process_info or _process_info
        self.user_games: set[str] = set()
        self.ignored: set[str] = set()
        self.use_fullscreen = True
        self.current: dict | None = None
        self._looked: dict[int, bool] = {}  # pid → was it a game (each process is looked at once)

    def configure(self, user_games: str = "", ignored: str = "", use_fullscreen: bool = True):
        self.user_games = parse_user_list(user_games)
        self.ignored = parse_user_list(ignored)
        self.use_fullscreen = bool(use_fullscreen)
        self._looked.clear()

    def poll(self) -> dict | None:
        if self.current is not None and not self._alive(self.current["pid"]):
            self.current = None
        pid = foreground_pid()
        if pid and pid != os.getpid() and (self.current is None or pid != self.current["pid"]):
            game = self.identify(pid, fullscreen_state())
            if game is not None:
                self.current = game
        return self.current

    def _alive(self, pid: int) -> bool:
        info = self.process_info(pid)
        return bool(info) and info.get("created") == self.current.get("created")

    def identify(self, pid: int, state: int) -> dict | None:
        if self._looked.get(pid) is False and state != 3:
            return None
        info = self.process_info(pid)
        if not info:
            return None
        exe = info["exe"]
        stem = exe_stem(exe)
        if stem in NOT_GAMES or stem in self.ignored:
            self._looked[pid] = False
            return None
        steam = self.steam.find(exe)
        is_game = bool(steam) or stem in self.user_games or in_game_folder(exe) \
            or (self.use_fullscreen and state == 3)
        if not is_game:
            self._looked[pid] = False
            if len(self._looked) > 500:
                self._looked.clear()
            return None
        self._looked[pid] = True
        name = steam[1] if steam else (file_description(exe) or readable_name(exe))
        icon, banner = self.steam.pictures(steam[0]) if steam else (b"", b"")
        return {"pid": pid, "exe": exe, "name": name, "appid": steam[0] if steam else "", "created": info["created"],
                "icon": icon, "banner": banner, "source": "steam" if steam else "pc"}


def _process_info(pid: int) -> dict | None:
    try:
        import psutil
        process = psutil.Process(pid)
        return {"exe": process.exe(), "created": round(process.create_time(), 1)}
    except Exception:
        return None
