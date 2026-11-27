"""Status island (0.4.3x): what happens right now, in one pill at the screen edge.

Pure logic, no Qt: the activities the island can show, which one wins, how
times are written, plus the background probe that reads the Windows media
session (what plays, its cover and position), the master volume and the
battery. The probe runs in its own thread and hands plain dictionaries to the
Qt side, so the UI thread never waits for COM / WinRT calls.

Nothing here is written to disk or logs: titles of songs and notification
texts stay in memory only.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

# Kinds in the order they win when several are active at once (first = most important).
PRIORITY = ("ring", "error", "listening", "speaking", "working", "waiting", "break", "dictation", "convert",
            "notification", "played", "steam_done", "volume", "reply", "discord", "game", "steam", "timer", "media",
            "captions", "battery", "demo")
# Kinds that only flash for a few seconds.
TRANSIENT = {"error", "notification", "volume", "reply", "battery", "demo", "played", "steam_done"}
# Colour of each kind (the «activity» accent mode).
COLORS = {
    "ring": "#ff9f0a", "error": "#ff453a", "listening": "#30d158", "speaking": "#0a84ff", "working": "#bf5af2",
    "waiting": "#ffd60a", "break": "#32d74b", "dictation": "#ff375f", "convert": "#64d2ff", "notification": "#0a84ff",
    "volume": "#ffffff", "reply": "#5e9cff", "timer": "#ff9f0a", "media": "#ff375f", "captions": "#64d2ff",
    "battery": "#30d158", "demo": "#bf5af2", "game": "#30d158", "played": "#30d158",
    "discord": "#5865f2", "steam": "#66c0f4", "steam_done": "#66c0f4",
}
# Which source each kind belongs to: every source has its own priority in the settings (or «Off»).
SOURCE = {
    "ring": "timers", "timer": "timers", "listening": "jarvis", "speaking": "jarvis", "working": "jarvis",
    "waiting": "jarvis", "error": "jarvis", "reply": "jarvis", "break": "breaks", "dictation": "tools",
    "convert": "tools", "captions": "tools", "notification": "notifications", "volume": "volume", "media": "media",
    "battery": "battery", "game": "games", "played": "games", "discord": "discord", "steam": "steam",
    "steam_done": "steam",
}
SOURCES = ("jarvis", "discord", "games", "steam", "media", "timers", "notifications", "volume", "tools", "breaks",
           "battery")
LEVELS = {"off": -1, "low": 0, "normal": 1, "high": 2, "top": 3}
DEFAULT_LEVELS = {"jarvis": "normal", "discord": "normal", "games": "normal", "steam": "normal", "media": "normal",
                  "timers": "normal", "notifications": "off", "volume": "normal", "tools": "normal", "breaks": "normal",
                  "battery": "low"}
BUBBLE_KINDS = ("timer", "media", "captions", "dictation", "convert", "game", "discord", "steam")
SIZES = {"85": 0.85, "100": 1.0, "115": 1.15, "130": 1.3}
BACKGROUNDS = {"black": "#000000", "graphite": "#1c1c1e", "midnight": "#0b1530", "glass": "#10131a"}


@dataclass
class Activity:
    kind: str
    title: str = ""
    subtitle: str = ""
    progress: float | None = None   # 0..1 (timer, media, volume, conversion)
    until: float = 0.0              # monotonic expiry for transient kinds (0 = while the source says so)
    key: str = ""                   # e.g. the timer id, to act on it
    data: dict = field(default_factory=dict)

    @property
    def rank(self) -> int:
        try:
            return PRIORITY.index(self.kind)
        except ValueError:
            return len(PRIORITY)


def level(kind: str, settings: dict) -> int:
    """The priority of a kind from its source's setting: -1 = never shown, 0 low … 3 always first.
    A ringing alarm is one step above its source, so it beats everything that is not «first»."""
    source = SOURCE.get(kind)
    if source is None:
        return LEVELS["normal"]
    value = LEVELS.get(str(settings.get(f"p_{source}", DEFAULT_LEVELS[source])), LEVELS[DEFAULT_LEVELS[source]])
    if kind == "reply" and not settings.get("show_reply", True):
        return -1
    if kind == "ring" and value >= 0:
        return min(LEVELS["top"], value + 2)
    return value


def allowed(kind: str, settings: dict) -> bool:
    return level(kind, settings) >= 0


def source_on(source: str, settings: dict) -> bool:
    return str(settings.get(f"p_{source}", DEFAULT_LEVELS.get(source, "normal"))) != "off"


def choose(activities, settings: dict, now: float | None = None) -> tuple[Activity | None, Activity | None]:
    """The main activity and a second one shown as a small bubble beside it (like two live activities)."""
    now = time.monotonic() if now is None else now
    alive = [a for a in activities if a is not None and allowed(a.kind, settings) and (not a.until or a.until > now)]
    alive.sort(key=lambda a: (-level(a.kind, settings), a.rank))
    if not alive:
        return None, None
    main = alive[0]
    second = None
    if settings.get("second", True):
        # The bubble shows a long-running thing (timer / media / captions), never a second flash.
        second = next((a for a in alive[1:] if a.kind in BUBBLE_KINDS
                       and a.kind != main.kind), None)
    return main, second


def format_left(seconds: float) -> str:
    """4:05, 59:59, 1:02:03 — a countdown as on a phone."""
    seconds = max(0, int(round(seconds)))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def media_position(media: dict, now_wall: float | None = None) -> float:
    """Where the track is now: the reported position plus the time since it was reported, while it plays."""
    position = float(media.get("position") or 0.0)
    duration = float(media.get("duration") or 0.0)
    if media.get("playing") and media.get("reported"):
        now_wall = time.time() if now_wall is None else now_wall
        position += max(0.0, now_wall - float(media["reported"]))
    return min(position, duration) if duration > 0 else position


def short(text: str, limit: int = 90) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def clamp_int(value, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def app_label(app_id: str) -> str:
    """«Spotify.exe» / «chrome.exe» / «SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify» → a readable name."""
    from luxai.notifications import app_name
    return app_name(app_id) or ""


# --- background probe ---------------------------------------------------------------------------

class IslandProbe:
    """Reads media / volume / battery in a background thread and reports changes.

    ``report(snapshot)`` is called from the probe thread with a fresh dict whenever something changed;
    the caller turns it into a Qt signal. Commands (play/pause, next, previous, seek) are queued and run
    on the same thread, the only one that touches WinRT/COM.
    """

    def __init__(self, report, *, media=True, volume=True, battery=True, notifications=False, toasts=None,
                 games=False, game_options=None, discord=False, steam=False):
        self.report = report
        self.toasts = toasts  # called with a list of new Windows notifications (app, texts)
        self.want = {"media": media, "volume": volume, "battery": battery, "notifications": notifications, "games": games,
                     "discord": discord, "steam": steam}
        self.game_options = dict(game_options or {})
        self._game_options_seen = None
        self._stop = threading.Event()
        self._commands: list[str] = []
        self._lock = threading.Lock()
        self._thread = None
        self.available = {"media": None, "volume": None, "battery": None}

    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="JarvisIslandProbe", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()

    def configure(self, *, media=True, volume=True, battery=True, notifications=False, games=False, game_options=None,
                  discord=False, steam=False):
        self.want = {"media": media, "volume": volume, "battery": battery, "notifications": notifications, "games": games,
                     "discord": discord, "steam": steam}
        self.game_options = dict(game_options or {})

    def command(self, name: str):
        if name in ("play_pause", "next", "previous", "discord_up", "discord_down", "discord_refresh"):
            with self._lock:
                if len(self._commands) < 8:
                    self._commands.append(name)

    # The loop: volume 4×/s (a change must show at once), media 1×/s, battery every 20 s.
    def _run(self):
        enter_multithreaded_apartment()
        loop = None
        try:
            import asyncio
            loop = asyncio.new_event_loop()
        except Exception:
            loop = None
        media_reader = MediaReader(loop) if loop is not None else None
        volume_reader = VolumeReader()
        watcher = None
        detector = None
        discord_tracker = None
        steam_tracker = None
        last = {}
        ticks = 0
        while not self._stop.is_set():
            snapshot = dict(last)
            with self._lock:
                commands, self._commands = self._commands, []
            for name in commands:
                if name.startswith("discord_"):
                    from luxai.discord_island import change_discord_volume
                    if name != "discord_refresh":
                        change_discord_volume(0.1 if name == "discord_up" else -0.1)
                    discord_tracker = self._poll_discord(discord_tracker, snapshot, force=True)
                elif media_reader is not None:
                    media_reader.command(name)
            if self.want["volume"]:
                snapshot["volume"] = volume_reader.read()
                self.available["volume"] = snapshot["volume"] is not None
            else:
                snapshot.pop("volume", None)
            if ticks % 4 == 0 or commands:
                if self.want["media"] and media_reader is not None:
                    snapshot["media"] = media_reader.read()
                    self.available["media"] = media_reader.available
                else:
                    snapshot.pop("media", None)
            if ticks % 80 == 0:
                snapshot["battery"] = read_battery() if self.want["battery"] else None
            if ticks % 8 == 0:
                watcher = self._poll_toasts(watcher)
            if ticks % 4 == 2:
                detector = self._poll_game(detector, snapshot)
            if ticks % 4 == 1:
                discord_tracker = self._poll_discord(discord_tracker, snapshot)
            if ticks % 8 == 3:
                steam_tracker = self._poll_steam(steam_tracker, snapshot)
            ticks += 1
            if snapshot != last:
                last = snapshot
                try:
                    self.report(dict(snapshot))
                except Exception:
                    pass
            self._stop.wait(0.25)
        if loop is not None:
            try:
                loop.close()
            except Exception:
                pass


    def _poll_game(self, detector, snapshot):
        """The running game (name, Steam icon / banner, since when) — once a second, on this thread."""
        if not self.want.get("games"):
            snapshot.pop("game", None)
            return None
        try:
            if detector is None:
                from luxai.game_detect import GameDetector
                detector = GameDetector()
            if self.game_options != self._game_options_seen:
                self._game_options_seen = dict(self.game_options)
                detector.configure(**self.game_options)
            snapshot["game"] = detector.poll()
        except Exception:
            snapshot["game"] = None
        return detector

    def _poll_discord(self, tracker, snapshot, force: bool = False):
        """A Discord voice call: where, mic / sound, the Discord volume."""
        if not self.want.get("discord"):
            snapshot.pop("discord", None)
            return None
        try:
            if tracker is None:
                from luxai.discord_island import DiscordCall
                tracker = DiscordCall()
            if force:
                tracker._panel_at = 0.0
            snapshot["discord"] = tracker.poll()
        except Exception:
            snapshot["discord"] = None
        return tracker

    def _poll_steam(self, tracker, snapshot):
        """A Steam download / install: how far, how fast, how long still; and the one that just finished."""
        if not self.want.get("steam"):
            snapshot.pop("steam", None)
            return None
        try:
            if tracker is None:
                from luxai.game_detect import SteamIndex
                from luxai.steam_activity import SteamDownloads
                tracker = SteamDownloads()
                tracker.index = SteamIndex()
                tracker.pictures = {}
            tracker.poll()
            state = tracker.state()
            if state is not None:
                appid = state["appid"]
                if appid not in tracker.pictures:
                    tracker.pictures[appid] = (tracker.index.name_of(appid), tracker.index.pictures(appid)[0])
                state["name"], state["icon"] = tracker.pictures[appid]
            snapshot["steam"] = state
            done = tracker.take_done()
            if done:
                snapshot["steam_done"] = dict(done[-1], at=time.time(), name=tracker.index.name_of(done[-1]["appid"]))
        except Exception:
            snapshot["steam"] = None
        return tracker

    def _poll_toasts(self, watcher):
        """New toasts since the island started (read-only, as the notification reader does)."""
        if not self.want.get("notifications") or self.toasts is None:
            return None  # turned off: the next start skips what came meanwhile
        try:
            if watcher is None:
                from luxai.notifications import NotificationWatcher
                watcher = NotificationWatcher()
                if not watcher.available():
                    return None
                watcher.prime()
                return watcher
            items = watcher.poll()
            if items:
                self.toasts(items)
        except Exception:
            pass
        return watcher


def enter_multithreaded_apartment() -> bool:
    """Put THIS thread in the COM multi-threaded apartment before anything else touches COM.

    WinRT async calls (the media session, its cover picture) complete on a thread pool and need no
    message loop only in MTA; in a single-threaded apartment the cover read waited forever. comtypes
    (pycaw) initialises the importing thread as STA, so it is imported here with MTA flags.
    """
    import sys
    if sys.platform != "win32":
        return False
    import ctypes
    result = ctypes.windll.ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED; S_OK / S_FALSE = ours now
    if "comtypes" not in sys.modules:
        had = hasattr(sys, "coinit_flags")
        previous = getattr(sys, "coinit_flags", None)
        sys.coinit_flags = 0
        try:
            import comtypes  # noqa: F401
        except Exception:
            pass
        finally:
            if had:
                sys.coinit_flags = previous
            else:
                del sys.coinit_flags
    return result in (0, 1)


class MediaReader:
    """The Windows «now playing» session (the same one the volume flyout shows)."""

    def __init__(self, loop):
        self.loop = loop
        self.manager = None
        self.available = None  # None = not tried, False = this PC / Python has no media API
        self._thumb_key = None
        self._thumb = b""
        self._failures = 0

    def _wait(self, operation, timeout: float = 2.0):
        """Every WinRT call gets a deadline: one that never completes must not freeze the probe."""
        import asyncio

        async def finish():
            return await operation
        return self.loop.run_until_complete(asyncio.wait_for(finish(), timeout))

    def _manager(self):
        if self.manager is None and self.available is not False:
            try:
                from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
                self.manager = self._wait(Manager.request_async(), 5.0)
                self.available = True
            except Exception:
                self.available = False
        return self.manager

    def _session(self):
        manager = self._manager()
        return manager.get_current_session() if manager is not None else None

    def read(self) -> dict | None:
        try:
            session = self._session()
            if session is None:
                return None
            props = self._wait(session.try_get_media_properties_async())
            playback = session.get_playback_info()
            timeline = session.get_timeline_properties()
            title = str(props.title or "")
            if not title:
                return None
            artist = str(props.artist or props.album_artist or "")
            key = (title, artist)
            if key != self._thumb_key:
                self._thumb_key = key
                self._thumb = self._read_thumbnail(props.thumbnail)
            duration = _seconds(timeline.end_time) - _seconds(timeline.start_time)
            reported = timeline.last_updated_time.timestamp() if timeline.last_updated_time else 0.0
            controls = playback.controls
            self._failures = 0
            return {
                "app": str(session.source_app_user_model_id or ""), "title": title, "artist": artist,
                "playing": int(playback.playback_status) == 4,
                "position": _seconds(timeline.position), "duration": max(0.0, duration),
                "reported": reported if 0 < reported <= time.time() + 5 else 0.0,
                "can_next": bool(controls.is_next_enabled), "can_previous": bool(controls.is_previous_enabled),
                "can_toggle": bool(controls.is_play_pause_toggle_enabled), "thumb": self._thumb,
            }
        except Exception:
            self._failures += 1
            if self._failures >= 3:
                self.manager = None  # the media service restarted: ask for a new manager
            return None

    def _read_thumbnail(self, reference) -> bytes:
        if reference is None:
            return b""
        try:
            from winrt.windows.storage.streams import Buffer, InputStreamOptions
            stream = self._wait(reference.open_read_async())
            size = int(stream.size)
            if not 0 < size <= 4 * 1024 * 1024:
                return b""
            buffer = Buffer(size)
            result = self._wait(stream.read_async(buffer, size, InputStreamOptions.NONE))
            return bytes(memoryview(result))[: int(result.length)]
        except Exception:
            return b""

    def command(self, name: str):
        try:
            session = self._session()
            if session is None:
                return
            call = {"play_pause": session.try_toggle_play_pause_async, "next": session.try_skip_next_async,
                    "previous": session.try_skip_previous_async}[name]
            self._wait(call())
        except Exception:
            pass


def _seconds(value) -> float:
    try:
        return float(value.total_seconds())
    except AttributeError:
        try:
            return float(value) / 10_000_000  # a raw TimeSpan in 100 ns units
        except (TypeError, ValueError):
            return 0.0


class VolumeReader:
    """Master volume and mute of the default output device (pycaw)."""

    def __init__(self):
        self.endpoint = None
        self.failed_at = 0.0

    def read(self) -> dict | None:
        if self.endpoint is None:
            if time.monotonic() - self.failed_at < 10:
                return None
            try:
                from pycaw.pycaw import AudioUtilities
                device = AudioUtilities.GetSpeakers()
                volume = getattr(device, "EndpointVolume", None)
                if volume is None:
                    from ctypes import POINTER, cast
                    from comtypes import CLSCTX_ALL
                    from pycaw.pycaw import IAudioEndpointVolume
                    interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                    volume = cast(interface, POINTER(IAudioEndpointVolume))
                self.endpoint = volume
            except Exception:
                self.failed_at = time.monotonic()
                return None
        try:
            return {"level": round(float(self.endpoint.GetMasterVolumeLevelScalar()), 2),
                    "muted": bool(self.endpoint.GetMute())}
        except Exception:
            self.endpoint = None  # the default device changed (headphones plugged in)
            self.failed_at = 0.0
            return None


def read_battery() -> dict | None:
    try:
        import psutil
        battery = psutil.sensors_battery()
    except Exception:
        return None
    if battery is None:
        return None  # a desktop PC
    return {"percent": int(battery.percent), "plugged": bool(battery.power_plugged)}


# --- what the island says ---------------------------------------------------------------------

WORDS = {
    "listening": ("Слушаю…", "Listening…", "Ascult…"),
    "working": ("Выполняю", "Working on it", "Lucrez"),
    "speaking": ("Jarvis говорит", "Jarvis is speaking", "Jarvis vorbește"),
    "waiting": ("Жду ответа", "Waiting for your answer", "Aștept răspunsul"),
    "error": ("Не получилось", "That did not work", "N-a mers"),
    "reply": ("Jarvis", "Jarvis", "Jarvis"),
    "timer": ("Таймер", "Timer", "Cronometru"),
    "alarm": ("Будильник", "Alarm", "Alarmă"),
    "reminder": ("Напоминание", "Reminder", "Memento"),
    "ring": ("Время вышло", "Time is up", "Timpul a expirat"),
    "volume": ("Громкость", "Volume", "Volum"),
    "muted": ("Без звука", "Muted", "Fără sunet"),
    "dictation": ("Диктовка", "Dictation", "Dictare"),
    "dictation_sub": ("Говорите — текст вставится у курсора", "Speak — the text goes to the cursor",
                      "Vorbește — textul apare la cursor"),
    "convert": ("Конвертирую", "Converting", "Convertesc"),
    "captions": ("Субтитры", "Captions", "Subtitrări"),
    "captions_sub": ("Включены", "On", "Pornite"),
    "battery_low": ("Батарея садится", "Battery low", "Bateria se descarcă"),
    "battery_charging": ("Заряжается", "Charging", "Se încarcă"),
    "battery_unplugged": ("От батареи", "On battery", "Pe baterie"),
    "nothing": ("Всё спокойно", "All quiet", "Totul e liniștit"),
    "demo": ("Так выглядит островок", "This is the island", "Așa arată insula"),
    "demo_sub": ("Наведите мышь — откроются действия", "Hover — the actions open", "Treci cu mouse-ul — apar acțiunile"),
    "queue": ("ещё {n} в очереди", "{n} more queued", "încă {n} în așteptare"),
    "mic_off": ("Микрофон выключен", "Microphone off", "Microfon oprit"),
    "ends": ("до {t}", "until {t}", "până la {t}"),
    "since": ("в игре с {t}", "playing since {t}", "în joc de la {t}"),
    "today": ("сегодня {t}", "today {t}", "azi {t}"),
    "played": ("Вы играли {t}", "You played {t}", "Ai jucat {t}"),
    "game_started": ("Игра запущена", "Game started", "Joc pornit"),
    "discord": ("Звонок Discord", "Discord call", "Apel Discord"),
    "discord_sub": ("Голосовой канал", "Voice channel", "Canal vocal"),
    "mic_muted": ("микрофон выключен", "mic muted", "microfon oprit"),
    "deafened": ("звук выключен", "sound off", "sunet oprit"),
    "steam_downloading": ("Загрузка", "Downloading", "Se descarcă"),
    "steam_installing": ("Установка", "Installing", "Se instalează"),
    "steam_verifying": ("Проверка файлов", "Verifying files", "Verific fișierele"),
    "steam_preparing": ("Подготовка", "Preparing", "Pregătire"),
    "steam_paused": ("Пауза", "Paused", "Pauză"),
    "steam_done": ("Установлено", "Installed", "Instalat"),
    "eta": ("осталось {t}", "{t} left", "mai rămân {t}"),
}
LANG_INDEX = {"ru": 0, "en": 1, "ro": 2}


def word(key: str, language: str, **values) -> str:
    value = WORDS[key][LANG_INDEX.get(language, 0)]
    return value.format(**values) if values else value


def voice_activity(flags: dict, active_text: str, waiting: bool, queued: int, language: str) -> Activity | None:
    """Jarvis itself: listening → working on «…» → speaking, or waiting for an answer."""
    if flags.get("speak"):
        return Activity("speaking", word("speaking", language), "")
    if flags.get("exec"):
        sub = short(active_text, 80)
        if queued > 0:
            sub = (sub + " · " if sub else "") + word("queue", language, n=queued)
        return Activity("working", word("working", language), sub)
    if waiting:
        return Activity("waiting", word("waiting", language), "")
    if flags.get("listening"):
        return Activity("listening", word("listening", language), "")
    return None


def timer_activity(timers, now_wall: float, language: str, ringing: list) -> Activity | None:
    """The ringing timer, else the one that ends first."""
    if ringing:
        timer = ringing[0]
        label = getattr(timer, "label", "") or ""
        return Activity("ring", word("ring", language), short(label, 60), key=getattr(timer, "id", ""))
    pending = [t for t in timers if getattr(t, "due", 0) > now_wall]
    if not pending:
        return None
    timer = min(pending, key=lambda t: t.due)
    left = timer.due - now_wall
    kind = "alarm" if timer.kind == "alarm" else ("reminder" if getattr(timer, "label", "") else "timer")
    duration = float(getattr(timer, "duration", 0) or 0)
    progress = None
    if timer.kind != "alarm" and duration > 0:
        progress = max(0.0, min(1.0, 1 - left / duration))
    title = word(kind, language)
    sub = short(timer.label, 50) if getattr(timer, "label", "") else ""
    import datetime as _dt
    ends = word("ends", language, t=_dt.datetime.fromtimestamp(timer.due).strftime("%H:%M"))
    return Activity("timer", title, sub, progress=progress, key=timer.id,
                    data={"left": format_left(left), "count": len(pending), "ends": ends})


def format_played(seconds: float, language: str) -> str:
    """«1 h 05 min» / «12 min» / «40 s» in the island's language."""
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    h, m, s_ = {"ru": ("ч", "мин", "с"), "en": ("h", "min", "s"), "ro": ("h", "min", "s")}.get(language, ("h", "min", "s"))
    if hours:
        return f"{hours} {h} {minutes:02d} {m}"
    if minutes:
        return f"{minutes} {m}"
    return f"{seconds} {s_}"


def game_activity(game: dict | None, now_wall: float, today_seconds: float, language: str) -> Activity | None:
    """The game you play: its icon and name, how long this session runs, the total for today."""
    if not game or not game.get("name"):
        return None
    import datetime as _dt
    elapsed = max(0.0, now_wall - float(game.get("created") or now_wall))
    started = _dt.datetime.fromtimestamp(float(game.get("created") or now_wall)).strftime("%H:%M")
    sub = word("since", language, t=started)
    if today_seconds + elapsed >= 60 and today_seconds > 0:
        sub += " · " + word("today", language, t=format_played(today_seconds + elapsed, language))
    return Activity("game", short(game["name"], 60), sub, key=f"{game.get('pid')}:{game.get('created')}",
                    data={"elapsed": format_left(elapsed), "icon": game.get("icon") or b"", "banner": game.get("banner") or b"",
                          "exe": game.get("exe", ""), "seconds": elapsed})


def discord_activity(call: dict | None, now_wall: float, language: str) -> Activity | None:
    """In a Discord call: where / with whom, for how long, mic and sound state, the Discord volume."""
    if not call:
        return None
    where = call.get("where") or ""
    elapsed = format_left(max(0.0, now_wall - float(call.get("since") or now_wall)))
    states = []
    if call.get("mic_muted"):
        states.append(word("mic_muted", language))
    if call.get("deafened"):
        states.append(word("deafened", language))
    sub = " · ".join([where] + states if where else states) or word("discord_sub", language)
    volume = call.get("volume")
    return Activity("discord", word("discord", language), sub, key="discord",
                    progress=None, data={"elapsed": elapsed, "where": where, "mic_muted": call.get("mic_muted"),
                                         "deafened": call.get("deafened"), "volume": volume})


def steam_activity(download: dict | None, language: str) -> Activity | None:
    """A Steam download / install / verification with its progress, speed and time left."""
    if not download:
        return None
    from luxai.steam_activity import human_bytes, human_eta, human_rate
    appid = str(download.get("appid", ""))
    name = download.get("name") or f"Steam {appid}"
    total = float(download.get("total") or 0)
    progress = min(1.0, float(download.get("downloaded") or 0) / total) if total > 0 else None
    phase = str(download.get("phase", "downloading"))
    parts = [word(f"steam_{phase}", language) if f"steam_{phase}" in WORDS else word("steam_downloading", language)]
    if total > 0:
        parts.append(f"≈{human_bytes(float(download.get('downloaded') or 0), language)} / {human_bytes(total, language)}")
    if phase == "downloading" and download.get("rate"):
        parts.append(human_rate(float(download["rate"]), language))
    eta = human_eta(download.get("eta"), language) if phase == "downloading" else ""
    return Activity("steam", short(name, 60), " · ".join(parts), progress=progress, key=appid,
                    data={"percent": f"{round((progress or 0) * 100)}%", "eta": eta, "appid": appid, "phase": phase,
                          "icon": download.get("icon") or b""})


def media_activity(media: dict | None, language: str) -> Activity | None:
    if not media or not media.get("title"):
        return None
    duration = float(media.get("duration") or 0)
    position = media_position(media)
    progress = position / duration if duration > 1 else None
    sub = media.get("artist") or app_label(media.get("app", ""))
    return Activity("media", short(media["title"], 70), short(sub, 60), progress=progress,
                    data={"playing": bool(media.get("playing")), "position": position, "duration": duration,
                          "thumb": media.get("thumb") or b"", "app": app_label(media.get("app", "")),
                          "can_next": media.get("can_next", True), "can_previous": media.get("can_previous", True)})


def volume_activity(volume: dict | None, previous: dict | None, now: float, seconds: float, language: str) -> Activity | None:
    """A volume change flashes the level (as the Windows flyout does, but in the island)."""
    if not volume or not previous or volume == previous:
        return None
    level = float(volume.get("level") or 0)
    title = word("muted", language) if volume.get("muted") else word("volume", language)
    return Activity("volume", title, f"{round(level * 100)}%", progress=0.0 if volume.get("muted") else level,
                    until=now + seconds, data={"muted": bool(volume.get("muted"))})


def battery_activity(battery: dict | None, previous: dict | None, now: float, language: str) -> Activity | None:
    """Plugged / unplugged, and a warning at 20 % and 10 %."""
    if not battery:
        return None
    percent = int(battery.get("percent", 0))
    if previous and battery.get("plugged") != previous.get("plugged"):
        key = "battery_charging" if battery.get("plugged") else "battery_unplugged"
        return Activity("battery", word(key, language), f"{percent}%", progress=percent / 100, until=now + 4)
    if not battery.get("plugged") and previous and any(percent <= mark < int(previous.get("percent", 101))
                                                         for mark in (20, 10, 5)):
        return Activity("battery", word("battery_low", language), f"{percent}%", progress=percent / 100, until=now + 8)
    return None
