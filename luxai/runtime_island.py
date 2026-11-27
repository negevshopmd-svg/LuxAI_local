"""Status island glue (0.4.3x): turns Jarvis' state into island activities and runs its buttons.

A mixin of ``ExtensionsRuntime`` (kept in its own file so the 4k-line runtime does not grow):
``_apply_island`` opens/closes the window and the background probe, ``_tick_island`` (5×/s, cheap,
UI thread: only reads flags already in memory) chooses what to show, ``_on_island_action`` runs a
button. Media / volume / battery / notifications are read by ``IslandProbe`` in its own thread.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QTimer

from luxai import status_island as si


def _tr3(ru, en, ro, language):
    return {"ru": ru, "en": en, "ro": ro}.get(language, ru)


class IslandMixin:
    """Needs: self.host, self.state helpers (enabled/settings/language), the timers, breaks, captions,
    dictation and converter members of ExtensionsRuntime."""

    def _island_init(self):
        self._island = None
        self._island_probe = None
        self._island_snapshot: dict = {}
        self._island_flashes: dict[str, si.Activity] = {}
        self._island_prev_volume = None
        self._island_prev_battery = None
        self._island_reply = ""
        self._island_reply_until = 0.0
        self._island_ticks = 0
        self._island_full_seconds = 0
        self._island_ring_since = 0.0
        self._island_dismissed: set = set()
        self._island_convert = None
        self._island_hold_until = 0.0  # hidden on purpose (a screenshot is being taken)
        self._island_game = None          # the game session now: {key, name, created}
        self._island_game_hidden = ""     # «hide until I quit» for this session key
        self._island_play_today: dict = {}  # game name → seconds played today (memory only)
        self._island_play_day = ""
        self._island_steam_done_at = 0.0
        self._island_discord_busy = False
        self._island_timer = QTimer(self)
        self._island_timer.setInterval(200)
        self._island_timer.timeout.connect(self._tick_island)
        self._island_probe_report.connect(self._on_island_probe)
        self._island_toasts.connect(self._on_island_toasts)
        self._island_discord_done.connect(self._on_island_discord_done)

    # -- lifecycle --------------------------------------------------------------------------------
    def _island_accent(self) -> str:
        return (getattr(self.host, "cfg", {}) or {}).get("ui_accent", "#3978f6")

    def _apply_island(self):
        if not self.enabled("status_island"):
            self._close_island()
            return
        settings = self.settings("status_island")
        from luxai.ui_status_island import IslandWindow
        if self._island is None:
            self._island = IslandWindow()
            self._island.action.connect(self._on_island_action)
        self._island.apply(settings, self.language, self._island_accent())
        on = lambda source: si.source_on(source, settings)  # noqa: E731
        wants = {"media": on("media"), "volume": on("volume"), "battery": on("battery"),
                 "notifications": on("notifications"), "games": on("games"), "discord": on("discord"),
                 "steam": on("steam"),
                 "game_options": {"user_games": settings.get("my_games", ""), "ignored": settings.get("not_games", ""),
                                  "use_fullscreen": bool(settings.get("game_fullscreen", True))}}
        if self._island_probe is None:
            self._island_probe = si.IslandProbe(self._island_probe_report.emit, toasts=self._island_toasts.emit, **wants)
            self._island_probe.start()
        else:
            self._island_probe.configure(**wants)
        if not self._island_timer.isActive():
            self._island_timer.start()
        self._tick_island()

    def _close_island(self):
        self._island_timer.stop()
        probe, self._island_probe = self._island_probe, None
        if probe is not None:
            probe.stop()
        window, self._island = self._island, None
        self._island_snapshot = {}
        self._island_prev_volume = self._island_prev_battery = None
        self._island_flashes.clear()
        if window is not None:
            try:
                window.close()
                window.deleteLater()
            except RuntimeError:
                pass

    # -- events from Jarvis ---------------------------------------------------------------------
    def island_reply(self, text: str):
        """A finished answer of Jarvis (called by the main window)."""
        if self._island is None:
            return
        value = si.short(text, 140)
        self._island_reply = value
        seconds = min(12.0, 4.0 + len(value) / 22)
        self._island_reply_until = time.monotonic() + seconds
        from luxai.avatar import looks_failed
        if looks_failed(text):
            self.island_flash("error", si.word("error", self.language), value, seconds)
        else:
            self.island_flash("reply", si.word("reply", self.language), value, seconds)

    def island_flash(self, kind: str, title: str, subtitle: str = "", seconds: float = 4.0, **data):
        if self._island is None:
            return
        self._island_flashes[kind] = si.Activity(kind, title, subtitle, until=time.monotonic() + seconds,
                                                 progress=data.pop("progress", None), data=data)
        self._tick_island()

    def show_island_demo(self):
        if self._island is None:
            return _tr3("Сначала включите «Островок».", "Turn on “Status island” first.",
                        "Pornește întâi „Insula de stare”.", self.language)
        self.island_flash("demo", si.word("demo", self.language), si.word("demo_sub", self.language), 6.0)
        return ""

    def toggle_island(self):
        if self._island is not None:
            self._island.toggle_pinned()

    def _on_island_probe(self, snapshot):
        old = self._island_snapshot
        self._island_snapshot = snapshot
        now = time.monotonic()
        settings = self.settings("status_island")
        volume = snapshot.get("volume")
        seconds = float(si.clamp_int(settings.get("flash_seconds", 3), 1, 10, 3))
        flash = si.volume_activity(volume, self._island_prev_volume, now, seconds, self.language)
        if volume is not None:
            if flash is not None and "volume" in old:
                self._island_flashes["volume"] = flash
            self._island_prev_volume = volume
        battery = snapshot.get("battery")
        flash = si.battery_activity(battery, self._island_prev_battery, now, self.language)
        if flash is not None:
            self._island_flashes["battery"] = flash
        if battery is not None:
            self._island_prev_battery = battery
        self._island_game_session(snapshot.get("game"), settings)
        done = snapshot.get("steam_done")
        if done and done.get("at", 0) > self._island_steam_done_at:
            self._island_steam_done_at = done["at"]
            name = done.get("name") or f"Steam {done.get('appid', '')}"
            self.island_flash("steam_done", name, si.word("steam_done", self.language), 8.0)
        self._tick_island()

    # -- games --------------------------------------------------------------------------------------
    def _island_today(self) -> dict:
        import datetime as _dt
        day = _dt.date.today().isoformat()
        if day != self._island_play_day:
            self._island_play_day, self._island_play_today = day, {}
        return self._island_play_today

    def _island_game_session(self, game, settings):
        """A game started → the card opens for a moment; it ended → «You played 1 h 05 min»."""
        key = f"{game.get('pid')}:{game.get('created')}" if game else ""
        current = self._island_game
        if current is not None and current["key"] != key:
            played = max(0.0, time.time() - float(current["created"]))
            today = self._island_today()
            today[current["name"]] = today.get(current["name"], 0.0) + played
            self._island_game = None
            if settings.get("game_summary", True) and played >= 60:
                total = si.format_played(today[current["name"]], self.language)
                sub = current["name"] + (" · " + si.word("today", self.language, t=total)
                                         if today[current["name"]] > played + 59 else "")
                self.island_flash("played", si.word("played", self.language, t=si.format_played(played, self.language)),
                                  sub, 6.0)
        if game and (current is None or current["key"] != key):
            self._island_game = {"key": key, "name": game.get("name", ""), "created": game.get("created") or time.time()}
            if settings.get("game_peek", True) and self._island is not None and si.source_on("games", settings):
                QTimer.singleShot(300, lambda: self._island is not None and self._island.peek(4.0))

    def _island_game_activity(self) -> si.Activity | None:
        game = self._island_snapshot.get("game")
        if not game or self._island_game is None or self._island_game["key"] == self._island_game_hidden:
            return None
        today = self._island_today().get(self._island_game["name"], 0.0)
        return si.game_activity(game, time.time(), today, self.language)

    def _on_island_toasts(self, items):
        settings = self.settings("status_island")
        if self._island is None or not si.source_on("notifications", settings):
            return
        seconds = float(si.clamp_int(settings.get("notification_seconds", 5), 2, 15, 5))
        item = items[-1]
        app = item.get("app") or _tr3("Уведомление", "Notification", "Notificare", self.language)
        texts = [t for t in item.get("texts", []) if t]
        if settings.get("notification_text", True):
            subtitle = si.short(" — ".join(texts[:2]), 120)
        else:
            subtitle = _tr3("Новое сообщение", "New message", "Mesaj nou", self.language)
        if len(items) > 1:
            subtitle = f"+{len(items) - 1} · " + subtitle
        self.island_flash("notification", si.short(app, 40), subtitle, seconds)

    # -- choosing ---------------------------------------------------------------------------------
    def _island_flags(self) -> dict:
        cfg = getattr(self.host, "cfg", {}) or {}
        return {"mic_on": bool(cfg.get("microphone_enabled", True)), "quiet": not cfg.get("tts_enabled", True),
                "captions": bool(self.captions_visible)}

    def _island_voice(self, settings) -> si.Activity | None:
        host = self.host
        flags = self.avatar_flags()
        heard = settings.get("show_hearing", False) and getattr(host, "_audio_event", "") in ("speech_started", "transcribing")
        flags["listening"] = heard
        queue = getattr(host, "_command_queue", None) or []
        queued = max(0, sum(len(group.get("parts", [])) for group in queue[:1]) + len(queue) - 1) if queue else 0
        waiting = bool(getattr(host, "_pending_agent_task", None) or getattr(host, "_pending_discord_message", None))
        activity = si.voice_activity(flags, getattr(host, "_active_text", "") or "", waiting, queued, self.language)
        if activity is not None and activity.kind == "speaking" and self._island_reply:
            activity.subtitle = self._island_reply
        return activity

    def _island_timer_activity(self) -> si.Activity | None:
        if not self.enabled("timers"):
            return None
        ringing = [timer for timer, _dialog in self._ringing]
        if ringing:
            if not self._island_ring_since:
                self._island_ring_since = time.monotonic()
            if time.monotonic() - self._island_ring_since > 180:
                ringing = []  # nobody answered for 3 minutes: the island goes back to normal
        else:
            self._island_ring_since = 0.0
        try:
            timers = self.active_timers()
        except Exception:
            timers = []
        return si.timer_activity(timers, time.time(), self.language, ringing)

    def _island_tools(self) -> list:
        found = []
        language = self.language
        if self.dictating:
            found.append(si.Activity("dictation", si.word("dictation", language), si.word("dictation_sub", language)))
        if getattr(self, "_converting", False):
            progress = self._island_convert
            found.append(si.Activity("convert", si.word("convert", language),
                                     f"{round(progress * 100)}%" if progress is not None else "", progress=progress))
        if self.captions_visible:
            found.append(si.Activity("captions", si.word("captions", language), si.word("captions_sub", language)))
        kind = getattr(self, "_break_card_kind", "")
        if kind:
            from luxai.extensions_runtime import break_message, break_title
            found.append(si.Activity("break", break_title(kind, language), break_message(kind, language), key=kind))
        return found

    def _island_activities(self, settings) -> list:
        now = time.monotonic()
        activities = [a for a in self._island_flashes.values() if a.until > now and a.kind not in self._island_dismissed]
        self._island_flashes = {k: a for k, a in self._island_flashes.items() if a.until > now}
        if not any(a.kind == "error" for a in activities) and self.avatar_flags().get("error") and self._island_reply:
            activities.append(si.Activity("error", si.word("error", self.language), self._island_reply, until=now + 2.5))
        voice = self._island_voice(settings)
        if voice is not None:
            activities.append(voice)
            if voice.kind in ("speaking", "working"):
                activities = [a for a in activities if a.kind != "reply"]  # the reply is under «speaking» already
        timer = self._island_timer_activity()
        if timer is not None:
            activities.append(timer)
        game = self._island_game_activity()
        if game is not None:
            activities.append(game)
        for activity in (si.discord_activity(self._island_snapshot.get("discord"), time.time(), self.language),
                         si.steam_activity(self._island_snapshot.get("steam"), self.language)):
            if activity is not None:
                activities.append(activity)
        activities.extend(self._island_tools())
        media = si.media_activity(self._island_snapshot.get("media"), self.language)
        if media is not None and (media.data.get("playing") or settings.get("paused_media", True)):
            activities.append(media)
        return activities

    def _tick_island(self):
        window = self._island
        if window is None:
            return
        settings = self.settings("status_island")
        self._island_ticks += 1
        if self._island_ticks % 5 == 0:  # once a second
            from luxai.avatar import fullscreen_app_running
            full = bool(settings.get("hide_fullscreen", True)) and fullscreen_app_running()
            # A game is the one full-screen program the island stays for (when «Games» is on).
            playing = si.source_on("games", settings) and self._island_game_activity() is not None
            self._island_full_seconds = self._island_full_seconds + 1 if full and not playing else 0
            window.follow_cursor_screen()
        window.set_suppressed(self._island_full_seconds >= 2 or time.monotonic() < self._island_hold_until)
        if self._island_ticks % 5 == 0:
            if self._island_ticks % 25 == 0:
                if not window.expanded:
                    window.place()  # resolution / scaling / taskbar changed, a monitor was unplugged
                window.keep_on_top()
        activities = self._island_activities(settings)
        main, second = si.choose(activities, settings)
        if main is not None and main.kind not in si.TRANSIENT:
            self._island_dismissed.discard(main.kind)
        window.set_content(main, second, self._island_flags())

    # -- buttons ----------------------------------------------------------------------------------
    def _on_island_action(self, name: str):
        group, _, what = name.partition(":")
        handler = {"media": self._island_media, "timer": self._island_timer_button, "ring": self._island_ring,
                   "break": self._island_break, "quick": self._island_quick, "tap": self._island_tap,
                   "voice": lambda _w: self._island_stop_voice(), "dictation": self._island_dictation,
                   "captions": lambda _w: self.hide_captions(), "dismiss": lambda _w: self._island_dismiss(),
                   "open": lambda _w: self._island_open(), "game": self._island_game_button,
                   "discord": self._island_discord, "steam": self._island_steam}.get(group)
        if handler is not None:
            handler(what)
        self._tick_island()

    def _island_discord(self, what: str):
        """Volume in the probe thread; mic / headphones with Discord's own buttons on a short worker thread."""
        if what in ("up", "down"):
            if self._island_probe is not None:
                self._island_probe.command(f"discord_{what}")
            return
        if what not in ("mic", "deaf") or self._island_discord_busy:
            return
        self._island_discord_busy = True
        language = self.language

        def work():
            try:
                from luxai.discord_island import toggle_discord
                reply = toggle_discord(what, language)
            except Exception:
                reply = ""
            self._island_discord_done.emit(reply)
        import threading
        threading.Thread(target=work, daemon=True, name="JarvisIslandDiscord").start()

    def _on_island_discord_done(self, reply: str):
        self._island_discord_busy = False
        if self._island_probe is not None:
            self._island_probe.command("discord_refresh")
        if reply and self._island is not None:
            self.island_flash("reply", si.word("discord", self.language), reply, 3.0)

    def _island_steam(self, what: str):
        if what == "open":
            try:
                import os
                os.startfile("steam://open/downloads")  # Steam's own link: its downloads page
            except OSError:
                pass

    def _island_game_button(self, what: str):
        if what == "hide" and self._island_game is not None:
            self._island_game_hidden = self._island_game["key"]  # back by itself with the next game
            if self._island is not None:
                self._island.expanded = self._island.pinned = False

    def _island_media(self, what: str):
        if self._island_probe is not None:
            self._island_probe.command(what)

    def _island_timer_button(self, what: str):
        main = self._island.main if self._island is not None else None
        if main is None or main.kind != "timer":
            return
        timer = next((t for t in self.active_timers() if t.id == main.key), None)
        if timer is None:
            return
        if what == "cancel":
            self.cancel_timer(timer.id)
            return
        extra = 60 if what == "add60" else 300
        from luxai.timers import new_timer
        longer = new_timer(timer.kind, timer.due + extra, timer.label, timer.duration + extra if timer.duration else 0)
        try:
            self.timer_store.add(longer)  # the new one first: a failed save changes nothing
        except (ValueError, OSError):
            self.notice.emit(self._words("save_failed"))
            return
        if not self.cancel_timer(timer.id):
            try:
                self.timer_store.remove(longer.id)
            except OSError:
                pass
        self.timers_changed.emit()

    def _island_ring(self, what: str):
        if what == "stop":
            self.stop_ringing()
        elif what == "snooze" and self._ringing:
            timer, dialog = self._ringing[0]
            self.snooze(timer, dialog)

    def _island_break(self, what: str):
        kind = getattr(self, "_break_card_kind", "")
        if kind:
            self._break_answer(kind, what if what in ("done", "later", "skip") else "done",
                               bool(getattr(self, "_break_card_test", False)))

    def _island_dictation(self, what: str):
        if what == "cancel":
            self.cancel_dictation()
        else:
            self.stop_dictation()

    def _island_stop_voice(self):
        stop = getattr(self.host, "stop_speaking", None)
        if callable(stop):
            stop()

    def _island_open(self):
        show = getattr(self.host, "show_from_tray", None)
        if callable(show):
            show()

    def _island_dismiss(self):
        main = self._island.main if self._island is not None else None
        if main is None:
            return
        if main.kind in si.TRANSIENT:
            self._island_flashes.pop(main.kind, None)
            if main.kind == "reply":
                self._island_reply_until = 0.0
        else:
            self._island_dismissed.add(main.kind)

    def _island_tap(self, kind: str):
        """A click on the pill itself: the most natural action for what it shows."""
        actions = {"break": lambda: self._island_break("done"), "ring": lambda: self._island_ring("stop"),
                   "speaking": self._island_stop_voice, "media": lambda: self._island_media("play_pause"),
                   "dictation": lambda: self._island_dictation("stop"), "captions": self._island_open_captions,
                   "notification": self._island_dismiss, "reply": self._island_open, "error": self._island_open,
                   "volume": self._island_dismiss, "battery": self._island_dismiss, "demo": self._island_dismiss,
                   "played": self._island_dismiss, "game": lambda: self._island.peek(5.0) if self._island else None,
                   "discord": lambda: self._island_discord("mic"), "steam": lambda: self._island_steam("open"),
                   "steam_done": self._island_dismiss}
        action = actions.get(kind, self._island_open)
        action()

    def _island_open_captions(self):
        open_page = getattr(self.host, "open_extension", None)
        if callable(open_page):
            open_page("live_captions")
        else:
            self._island_open()

    def _island_quick(self, what: str):
        host = self.host
        cfg = getattr(host, "cfg", {}) or {}
        if what == "mic" and hasattr(host, "toggle_microphone_from_header"):
            host.toggle_microphone_from_header(not cfg.get("microphone_enabled", True))
        elif what == "quiet":
            quiet = getattr(host, "home_quiet", None)
            value = bool(cfg.get("tts_enabled", True))  # speaking now → quiet on
            if quiet is not None:
                quiet.setChecked(value)
            elif hasattr(host, "sync_quiet"):
                host.sync_quiet(value)
        elif what == "captions":
            self.toggle_captions()
        elif what == "screenshot":
            self._island_screenshot()
        elif what == "timer":
            if self.enabled("timers"):
                self.island_flash("reply", si.word("timer", self.language), self.add_timer("timer", seconds=300), 3.0)
            else:
                self._notify(self._words("disabled"))
        elif what == "clipboard":
            if self.enabled("clipboard_history"):
                self.open_clipboard_history()
            else:
                self._notify(_tr3("Включите «Историю буфера обмена» в Расширениях.",
                                  "Turn on “Clipboard history” in Extensions.",
                                  "Pornește „Istoricul clipboard” în Extensii.", self.language))
        elif what == "jarvis":
            self._island_open()

    def _island_screenshot(self):
        """The island hides itself first, so it is never in the picture."""
        window = self._island
        self._island_hold_until = time.monotonic() + 1.2
        if window is not None:
            window.expanded = window.pinned = False
            window.set_suppressed(True)
        QTimer.singleShot(500, self.take_screenshot)
