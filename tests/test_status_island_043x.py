"""0.4.3x: the status island — priorities, live activities, the morphing window, its buttons and settings."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from luxai import extensions_catalog as catalog  # noqa: E402
from luxai import status_island as si  # noqa: E402
from luxai.timers import new_timer  # noqa: E402

DEFAULTS = {s.key: s.default for s in catalog.PLUGIN_BY_ID["status_island"].settings}


class ChooseTests(unittest.TestCase):
    def test_an_alarm_beats_everything_and_music_waits_in_the_bubble(self):
        media = si.Activity("media", "Song")
        ring = si.Activity("ring", "Time is up")
        speaking = si.Activity("speaking", "Jarvis")
        main, second = si.choose([media, speaking, ring], DEFAULTS)
        self.assertEqual(main.kind, "ring")
        self.assertEqual(second.kind, "media")

    def test_a_switched_off_kind_is_never_shown(self):
        main, second = si.choose([si.Activity("media", "Song")], dict(DEFAULTS, p_media="off"))
        self.assertIsNone(main)
        self.assertIsNone(second)

    def test_expired_flashes_are_gone_and_flashes_never_take_the_bubble(self):
        now = time.monotonic()
        old = si.Activity("notification", "Telegram", until=now - 1)
        volume = si.Activity("volume", "Volume", until=now + 3)
        reply = si.Activity("reply", "Jarvis", until=now + 3)
        main, second = si.choose([old, volume, reply], DEFAULTS, now)
        self.assertEqual(main.kind, "volume")
        self.assertIsNone(second)

    def test_no_bubble_when_turned_off(self):
        _main, second = si.choose([si.Activity("timer", "T"), si.Activity("media", "M")], dict(DEFAULTS, second=False))
        self.assertIsNone(second)


class WordingTests(unittest.TestCase):
    def test_countdown(self):
        self.assertEqual(si.format_left(245), "4:05")
        self.assertEqual(si.format_left(3723), "1:02:03")
        self.assertEqual(si.format_left(-5), "0:00")

    def test_media_position_moves_only_while_playing(self):
        media = {"position": 10.0, "duration": 100.0, "reported": 1000.0, "playing": True}
        self.assertAlmostEqual(si.media_position(media, 1004.0), 14.0)
        self.assertAlmostEqual(si.media_position(dict(media, playing=False), 1004.0), 10.0)
        self.assertEqual(si.media_position(media, 5000.0), 100.0)  # never past the end

    def test_soonest_timer_with_progress_and_end_time(self):
        now = time.time()
        later = new_timer("timer", now + 900, "", 1000)
        soon = new_timer("timer", now + 60, "tea", 120)
        activity = si.timer_activity([later, soon], now, "ro", [])
        self.assertEqual(activity.key, soon.id)
        self.assertEqual(activity.title, "Memento")  # a labelled timer is a reminder
        self.assertEqual(activity.data["left"], "1:00")
        self.assertAlmostEqual(activity.progress, 0.5, places=2)
        self.assertTrue(activity.data["ends"].startswith("până la "))
        self.assertEqual(activity.data["count"], 2)

    def test_ringing_wins(self):
        timer = new_timer("alarm", time.time() - 1, "call Ana")
        activity = si.timer_activity([], time.time(), "en", [timer])
        self.assertEqual((activity.kind, activity.title, activity.subtitle), ("ring", "Time is up", "call Ana"))

    def test_voice_states(self):
        self.assertEqual(si.voice_activity({"speak": True, "exec": True}, "x", False, 0, "en").kind, "speaking")
        working = si.voice_activity({"exec": True}, "open youtube", False, 2, "ru")
        self.assertEqual(working.kind, "working")
        self.assertIn("open youtube", working.subtitle)
        self.assertIn("2", working.subtitle)
        self.assertEqual(si.voice_activity({}, "", True, 0, "en").kind, "waiting")
        self.assertIsNone(si.voice_activity({}, "", False, 0, "en"))

    def test_volume_flashes_only_on_a_change(self):
        now = time.monotonic()
        self.assertIsNone(si.volume_activity({"level": 0.5, "muted": False}, None, now, 3, "en"))  # first read
        self.assertIsNone(si.volume_activity({"level": 0.5, "muted": False}, {"level": 0.5, "muted": False}, now, 3, "en"))
        muted = si.volume_activity({"level": 0.5, "muted": True}, {"level": 0.5, "muted": False}, now, 3, "ro")
        self.assertEqual((muted.title, muted.progress), ("Fără sunet", 0.0))

    def test_battery_warns_once_when_crossing_a_mark(self):
        now = time.monotonic()
        low = si.battery_activity({"percent": 19, "plugged": False}, {"percent": 21, "plugged": False}, now, "en")
        self.assertEqual(low.title, "Battery low")
        self.assertIsNone(si.battery_activity({"percent": 18, "plugged": False}, {"percent": 19, "plugged": False}, now, "en"))
        plugged = si.battery_activity({"percent": 50, "plugged": True}, {"percent": 50, "plugged": False}, now, "ru")
        self.assertEqual(plugged.title, "Заряжается")
        self.assertIsNone(si.battery_activity(None, None, now, "en"))  # a desktop PC

    def test_every_word_exists_in_three_languages(self):
        for key, values in si.WORDS.items():
            self.assertEqual(len(values), 3, key)
            self.assertTrue(all(value.strip() for value in values), key)

    def test_a_hostile_number_falls_back(self):
        self.assertEqual(si.clamp_int("nan", 1, 10, 3), 3)
        self.assertEqual(si.clamp_int(10 ** 9, 1, 10, 3), 10)
        self.assertEqual(si.clamp_int(None, 1, 10, 3), 3)


class ProbeTests(unittest.TestCase):
    def test_a_media_call_that_never_finishes_has_a_deadline(self):
        loop = asyncio.new_event_loop()
        self.addCleanup(loop.close)
        reader = si.MediaReader(loop)
        never = loop.create_future()
        started = time.monotonic()
        with self.assertRaises(asyncio.TimeoutError):
            reader._wait(never, 0.2)
        self.assertLess(time.monotonic() - started, 2)

    def test_a_failed_read_is_quiet_and_the_manager_is_asked_again(self):
        reader = si.MediaReader(asyncio.new_event_loop())
        self.addCleanup(reader.loop.close)
        reader.manager = SimpleNamespace(get_current_session=mock.Mock(side_effect=OSError("restarted")))
        reader.available = True
        for _ in range(3):
            self.assertIsNone(reader.read())
        self.assertIsNone(reader.manager)

    @unittest.skipUnless(sys.platform == "win32", "COM apartments exist on Windows only")
    def test_the_probe_thread_is_multithreaded_even_when_comtypes_would_choose_sta(self):
        result = {}

        def run():
            result["ok"] = si.enter_multithreaded_apartment()
            import ctypes
            # CoInitializeEx with MTA again returns S_FALSE (1) only when the thread already is MTA.
            result["again"] = ctypes.windll.ole32.CoInitializeEx(None, 0)
        thread = threading.Thread(target=run)
        thread.start()
        thread.join(10)
        self.assertTrue(result["ok"])
        self.assertEqual(result["again"], 1)

    def test_commands_are_queued_and_limited(self):
        probe = si.IslandProbe(lambda _s: None)
        for _ in range(20):
            probe.command("play_pause")
        probe.command("format_disk")
        self.assertEqual(len(probe._commands), 8)
        self.assertNotIn("format_disk", probe._commands)

    def test_toasts_are_only_read_when_asked(self):
        seen = []
        probe = si.IslandProbe(lambda _s: None, toasts=seen.append, notifications=False)
        self.assertIsNone(probe._poll_toasts(None))
        watcher = SimpleNamespace(poll=lambda: [{"app": "Telegram", "texts": ["hi"]}])
        probe.configure(notifications=True)
        self.assertIs(probe._poll_toasts(watcher), watcher)
        self.assertEqual(seen, [[{"app": "Telegram", "texts": ["hi"]}]])


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def window(self, **settings):
        from luxai.ui_status_island import IslandWindow
        window = IslandWindow()
        self.addCleanup(window.deleteLater)
        window.apply(dict(DEFAULTS, **settings), "ro", "#3978f6")
        return window

    def test_idle_shapes(self):
        window = self.window(idle="clock")
        self.assertGreater(window._target_size()[0], 0)
        window.apply(dict(DEFAULTS, idle="hide"), "ro", "#3978f6")
        self.assertEqual(window._target_size(), (0.0, 0.0))

    def test_hidden_in_full_screen(self):
        window = self.window()
        window.set_content(si.Activity("media", "Song"), None, {})
        window.set_suppressed(True)
        self.assertEqual(window._target_size(), (0.0, 0.0))

    def test_the_card_is_taller_than_the_pill_and_bigger_is_bigger(self):
        window = self.window()
        window.set_content(si.Activity("timer", "Timer", progress=0.5, data={"left": "4:05"}), None, {})
        compact = window._target_size()
        window.expanded = True
        expanded = window._target_size()
        self.assertGreater(expanded[1], compact[1] * 2)
        big = self.window(size="130")
        big.set_content(si.Activity("timer", "Timer", progress=0.5, data={"left": "4:05"}), None, {})
        self.assertGreater(big._target_size()[1], compact[1])

    def test_buttons_for_each_kind_in_every_language(self):
        window = self.window()
        for language in ("ru", "en", "ro"):
            window.language = language
            for kind in ("timer", "ring", "speaking", "break", "dictation", "captions", "notification"):
                controls = window._controls(si.Activity(kind, "x"))
                self.assertTrue(controls, kind)
                self.assertTrue(all(label.strip() for _name, label in controls))
        media = window._controls(si.Activity("media", "x", data={"playing": True, "can_next": False, "can_previous": False}))
        self.assertEqual(media, [("media:play_pause", "@pause")])  # YouTube: no next / previous

    def test_painting_registers_the_buttons_and_a_click_runs_one(self):
        window = self.window()
        window.expanded = True
        window.set_content(si.Activity("media", "Song", "Artist", progress=0.3,
                                       data={"playing": False, "duration": 200, "position": 60}), None,
                           {"mic_on": True})
        window._rect = window._to = window._pill_rect(*window._target_size())
        window._content_since = 0
        window.grab()  # paints
        names = [name for _rect, name in window._buttons]
        self.assertIn("media:play_pause", names)
        self.assertIn("quick:mic", names)
        fired = []
        window.action.connect(fired.append)
        rect = next(rect for rect, name in window._buttons if name == "media:play_pause")
        event = SimpleNamespace(position=lambda: rect.center(), button=lambda: Qt.MouseButton.LeftButton)
        window.mouseReleaseEvent(event)
        self.assertEqual(fired, ["media:play_pause"])

    def test_a_click_on_the_pill_is_its_main_action_and_right_click_closes(self):
        window = self.window()
        window.set_content(si.Activity("break", "Eyes", "Look away"), None, {})
        window._rect = window._to = window._pill_rect(*window._target_size())
        fired = []
        window.action.connect(fired.append)
        center = window._rect.center()
        window.mouseReleaseEvent(SimpleNamespace(position=lambda: center, button=lambda: Qt.MouseButton.LeftButton))
        window.mouseReleaseEvent(SimpleNamespace(position=lambda: center, button=lambda: Qt.MouseButton.RightButton))
        self.assertEqual(fired, ["tap:break", "dismiss"])

    def test_outside_the_pill_nothing_happens(self):
        window = self.window()
        window.set_content(si.Activity("media", "Song"), None, {})
        window._rect = window._to = window._pill_rect(*window._target_size())
        fired = []
        window.action.connect(fired.append)
        window.mouseReleaseEvent(SimpleNamespace(position=lambda: QPointF(1, window.height() - 1),
                                                 button=lambda: Qt.MouseButton.LeftButton))
        self.assertEqual(fired, [])

    def test_the_notch_is_glued_to_the_top(self):
        window = self.window(style="notch")
        self.assertEqual(window._pill_rect(200, 36).top(), 0.0)
        bottom = self.window(style="notch", edge="bottom")  # a notch exists only at the top
        self.assertFalse(bottom.notch)

    def test_the_spring_ends_exactly_where_it_should(self):
        from luxai.ui_status_island import ease_spring
        self.assertEqual(ease_spring(1.0), 1.0)
        self.assertGreater(max(ease_spring(t / 100) for t in range(100)), 1.0)  # a small overshoot

    def test_compact_text_says_what_happened(self):
        from luxai.ui_status_island import compact_text
        self.assertEqual(compact_text(si.Activity("notification", "Telegram", "Ana: hi")), "Telegram: Ana: hi")
        self.assertEqual(compact_text(si.Activity("working", "Working", "open youtube")), "open youtube")
        self.assertEqual(compact_text(si.Activity("media", "Song", "Artist")), "Song")

    def test_frames_slow_down_when_nothing_moves(self):
        window = self.window()
        window.set_content(si.Activity("media", "Song", data={"playing": False}), None, {})
        window._anim_start = 0
        window._content_since = 0
        window._tick()
        self.assertEqual(window._frame.interval(), 250)
        window.set_content(si.Activity("media", "Song", data={"playing": True}), None, {})
        window._anim_start = 0
        window._content_since = 0
        window._tick()
        self.assertEqual(window._frame.interval(), 16)


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, **settings):
        from luxai import extensions_runtime as runtime
        host = SimpleNamespace(cfg={"ui_language": "ro", "microphone_enabled": True, "tts_enabled": True},
                               tray_icon=None, online_planner=None, _queue_speech=lambda *a: None,
                               stop_speaking=mock.Mock(), show_from_tray=mock.Mock(),
                               toggle_microphone_from_header=mock.Mock(), _processing=False, _command_queue=[])
        engine = runtime.ExtensionsRuntime(host)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        engine.timers_path = Path(folder.name) / "timers.json"
        self.addCleanup(lambda: (engine.stop(), engine.deleteLater(),
                                 QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)))
        probe = mock.Mock()
        with mock.patch.object(si, "IslandProbe", return_value=probe):
            engine.apply(catalog.normalize_state({"status_island": {"enabled": True, "settings": settings},
                                                  "timers": {"enabled": True}}))
        return engine, host, probe

    def test_turning_it_on_and_off(self):
        engine, _host, probe = self.make()
        self.assertIsNotNone(engine._island)
        probe.start.assert_called_once()
        engine.apply(catalog.normalize_state({"status_island": {"enabled": False}}))
        self.assertIsNone(engine._island)
        probe.stop.assert_called_once()

    def test_a_running_timer_is_shown_and_one_minute_can_be_added(self):
        engine, _host, _probe = self.make()
        engine.add_timer("timer", seconds=300)
        engine._tick_island()
        self.assertEqual(engine._island.main.kind, "timer")
        before = engine.active_timers()[0].due
        engine._on_island_action("timer:add60")
        timers = engine.active_timers()
        self.assertEqual(len(timers), 1)
        self.assertAlmostEqual(timers[0].due - before, 60, places=3)
        engine._tick_island()
        engine._on_island_action("timer:cancel")
        self.assertEqual(engine.active_timers(), [])

    def test_an_answer_of_jarvis_flashes_and_can_be_closed(self):
        engine, _host, _probe = self.make()
        engine.island_reply("Am deschis YouTube.")
        self.assertEqual(engine._island.main.kind, "reply")
        engine._on_island_action("dismiss")
        self.assertIsNone(engine._island.main)

    def test_a_break_reminder_is_answered_from_the_island(self):
        engine, _host, _probe = self.make()
        engine.state["breaks"] = {"enabled": True, "settings": {}}
        engine.show_break_card("eyes")
        engine._tick_island()
        self.assertEqual(engine._island.main.kind, "break")
        with mock.patch.object(engine, "_count_break") as counted:
            engine._on_island_action("tap:break")
        counted.assert_called_once_with("done")
        self.assertEqual(engine._break_card_kind, "")

    def test_a_test_break_never_counts(self):
        engine, _host, _probe = self.make()
        engine.show_break_card("water", test=True)
        with mock.patch.object(engine, "_count_break") as counted:
            engine._on_island_action("break:done")
        counted.assert_not_called()

    def test_quick_buttons_reach_jarvis(self):
        engine, host, probe = self.make()
        engine._on_island_action("quick:mic")
        host.toggle_microphone_from_header.assert_called_once_with(False)
        engine._on_island_action("quick:jarvis")
        host.show_from_tray.assert_called_once()
        engine._on_island_action("media:next")
        probe.command.assert_called_with("next")

    def test_the_island_hides_itself_for_a_screenshot(self):
        engine, _host, _probe = self.make()
        with mock.patch("PySide6.QtCore.QTimer.singleShot") as later:
            engine._on_island_action("quick:screenshot")
        self.assertTrue(engine._island.suppressed)
        self.assertEqual(later.call_args.args[1], engine.take_screenshot)
        engine._island_hold_until = 0
        engine._tick_island()
        self.assertFalse(engine._island.suppressed)

    def test_speaking_shows_the_answer_and_stop_silences(self):
        engine, host, _probe = self.make()
        engine.island_reply("Bună seara.")
        with mock.patch("luxai.voices.barge_in_ready") as speaking:
            speaking.is_set.return_value = True
            engine._tick_island()
        self.assertEqual(engine._island.main.kind, "speaking")
        self.assertEqual(engine._island.main.subtitle, "Bună seara.")
        engine._on_island_action("voice:stop")
        host.stop_speaking.assert_called_once()

    def test_notifications_respect_privacy(self):
        engine, _host, _probe = self.make(p_notifications="normal", notification_text=False)
        engine._on_island_toasts([{"app": "Telegram", "texts": ["Ana", "secret"]}])
        main = engine._island.main
        self.assertEqual(main.title, "Telegram")
        self.assertNotIn("secret", main.subtitle)

    def test_notifications_off_show_nothing(self):
        engine, _host, _probe = self.make()
        engine._on_island_toasts([{"app": "Telegram", "texts": ["hi"]}])
        self.assertIsNone(engine._island.main)

    def test_the_shortcut_pins_the_card(self):
        engine, _host, _probe = self.make()
        engine._on_hotkey("status_island.hotkey")
        self.assertTrue(engine._island.pinned and engine._island.expanded)
        self.assertIn({"id": "status_island.hotkey", "enabled": True, "hotkey": "ctrl+alt+i"}, engine.hotkey_entries())

    def test_volume_change_flashes(self):
        engine, _host, _probe = self.make()
        engine._on_island_probe({"volume": {"level": 0.5, "muted": False}})
        self.assertIsNone(engine._island.main)  # the first reading is not a change
        engine._on_island_probe({"volume": {"level": 0.7, "muted": False}})
        self.assertEqual(engine._island.main.kind, "volume")

    def test_main_window_reports_answers(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("self.extensions_runtime.island_reply(result)", source)


class GameDetectTests(unittest.TestCase):
    """0.4.3y: which game runs, with its Steam name and pictures, read from the local Steam folders only."""

    def steam(self):
        from luxai.game_detect import SteamIndex
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name) / "Steam"
        other = Path(folder.name) / "SteamLibrary"
        (root / "steamapps").mkdir(parents=True)
        (other / "steamapps").mkdir(parents=True)
        (root / "steamapps" / "libraryfolders.vdf").write_text(
            '"libraryfolders"\n{\n "0"\n {\n  "path"  "%s"\n }\n "1"\n {\n  "path"  "%s"\n }\n}\n'
            % (str(root).replace("\\", "\\\\"), str(other).replace("\\", "\\\\")), encoding="utf-8")
        (other / "steamapps" / "appmanifest_730.acf").write_text(
            '"AppState"\n{\n "appid" "730"\n "name" "Counter-Strike 2"\n "installdir" "Counter-Strike Global Offensive"\n}\n',
            encoding="utf-8")
        cache = root / "appcache" / "librarycache" / "730"
        (cache / "162664aa5da85f418105350c5d67ca565f6c3713").mkdir(parents=True)
        (cache / ("8dbc71957312bbd3baea65848b545be9eae2a355" + ".jpg")).write_bytes(b"icon")
        (cache / "162664aa5da85f418105350c5d67ca565f6c3713" / "header.jpg").write_bytes(b"banner")
        exe = other / "steamapps" / "common" / "Counter-Strike Global Offensive" / "game" / "bin" / "win64" / "cs2.exe"
        return SteamIndex(str(root)), str(exe)

    def test_a_steam_game_gets_its_real_name_and_pictures(self):
        steam, exe = self.steam()
        self.assertEqual(steam.find(exe), ("730", "Counter-Strike 2"))
        self.assertEqual(steam.pictures("730"), (b"icon", b"banner"))
        self.assertEqual(steam.pictures("../../etc"), (b"", b""))  # only a number is a Steam app

    def detector(self, exe, steam=None, created=100.0):
        from luxai.game_detect import GameDetector
        info = {"exe": exe, "created": created}
        detector = GameDetector(steam or mock.Mock(find=lambda _e: None, pictures=lambda _a: (b"", b"")),
                                process_info=lambda pid: dict(info) if info else None)
        return detector, info

    def test_a_game_is_found_and_stays_while_alt_tabbed(self):
        steam, exe = self.steam()
        detector, info = self.detector(exe, steam)
        with mock.patch("luxai.game_detect.foreground_pid", return_value=4242), \
                mock.patch("luxai.game_detect.fullscreen_state", return_value=0):
            game = detector.poll()
        self.assertEqual((game["name"], game["appid"], game["icon"]), ("Counter-Strike 2", "730", b"icon"))
        with mock.patch("luxai.game_detect.foreground_pid", return_value=0):
            self.assertIs(detector.poll(), game)  # another window in front: still playing
        info["created"] = 555.0  # the pid was reused by another program: the game ended
        with mock.patch("luxai.game_detect.foreground_pid", return_value=0):
            self.assertIsNone(detector.poll())

    def test_what_counts_as_a_game(self):
        from luxai import game_detect as gd
        self.assertTrue(gd.in_game_folder(r"C:\Program Files\Epic Games\Fortnite\FortniteClient-Win64-Shipping.exe"))
        self.assertFalse(gd.in_game_folder(r"C:\Program Files\Notepad++\notepad++.exe"))
        self.assertEqual(gd.readable_name("HogwartsLegacy-Win64-Shipping.exe"), "HogwartsLegacy")
        cases = [(r"C:\Program Files\Google\Chrome\Application\chrome.exe", 3, {}, False),  # a full-screen video
                 (r"C:\Tools\emulator.exe", 3, {}, True),  # any other full-screen 3D program
                 (r"C:\Tools\emulator.exe", 3, {"use_fullscreen": False}, False),
                 (r"C:\Tools\mygame.exe", 0, {"user_games": "MyGame.exe"}, True),
                 (r"C:\Games\Witcher3\witcher3.exe", 0, {"ignored": "witcher3"}, False),
                 (r"C:\Program Files (x86)\Steam\steam.exe", 3, {}, False)]  # the launcher itself
        for exe, state, options, expected in cases:
            detector, _info = self.detector(exe)
            detector.configure(**options)
            with mock.patch("luxai.game_detect.file_description", return_value=""):
                self.assertEqual(detector.identify(7, state) is not None, expected, exe)

    def test_a_program_that_is_not_a_game_is_looked_at_once(self):
        detector, _info = self.detector(r"C:\Tools\editor.exe")
        calls = []
        original = detector.process_info
        detector.process_info = lambda pid: calls.append(pid) or original(pid)
        detector.identify(9, 0)
        detector.identify(9, 0)
        self.assertEqual(calls, [9])

    def test_played_time_wording(self):
        self.assertEqual(si.format_played(3900, "ru"), "1 ч 05 мин")
        self.assertEqual(si.format_played(720, "en"), "12 min")
        self.assertEqual(si.format_played(40, "ro"), "40 s")

    def test_the_game_activity(self):
        game = {"pid": 1, "created": time.time() - 4985, "name": "Counter-Strike 2", "icon": b"i", "banner": b"b"}
        activity = si.game_activity(game, time.time(), 3600, "ro")
        self.assertEqual(activity.kind, "game")
        self.assertTrue(activity.data["elapsed"].startswith("1:23:0"))
        self.assertIn("azi 2 h 23 min", activity.subtitle)
        self.assertIsNone(si.game_activity(None, time.time(), 0, "ro"))


class GameRuntimeTests(RuntimeTests.__mro__[0]):
    """Sessions: the card opens when a game starts, «You played …» when it ends, hide until quit."""

    def game(self, pid=1, created=None, name="Counter-Strike 2"):
        return {"pid": pid, "created": created or time.time() - 600, "name": name, "exe": "", "icon": b"", "banner": b""}

    def test_start_play_and_end(self):
        engine, _host, _probe = self.make()
        game = self.game()
        with mock.patch.object(engine._island, "peek") as peek, \
                mock.patch("PySide6.QtCore.QTimer.singleShot", side_effect=lambda _ms, call: call()):
            engine._on_island_probe({"game": game})
        peek.assert_called_once_with(4.0)
        self.assertEqual(engine._island.main.kind, "game")
        engine._on_island_probe({"game": None})
        main = engine._island.main
        self.assertEqual(main.kind, "played")
        self.assertIn("10 min", main.title)
        self.assertGreater(engine._island_play_today["Counter-Strike 2"], 590)

    def test_a_short_start_says_nothing_when_it_ends(self):
        engine, _host, _probe = self.make()
        engine._on_island_probe({"game": self.game(created=time.time() - 5)})
        engine._on_island_probe({"game": None})
        self.assertIsNone(engine._island.main)

    def test_hide_until_quit_and_back_with_the_next_game(self):
        engine, _host, _probe = self.make()
        engine._on_island_probe({"game": self.game()})
        engine._on_island_action("game:hide")
        self.assertIsNone(engine._island.main)
        engine._on_island_probe({"game": self.game(pid=2, name="Dota 2")})
        self.assertEqual(engine._island.main.kind, "played")  # first «You played 10 min» of the last game
        engine._on_island_action("dismiss")
        self.assertEqual(engine._island.main.title, "Dota 2")

    def test_the_island_stays_over_a_game_but_not_over_a_film(self):
        engine, _host, _probe = self.make()
        engine._island_ticks = 4
        with mock.patch("luxai.avatar.fullscreen_app_running", return_value=True):
            engine._on_island_probe({"game": self.game()})
            for _ in range(12):
                engine._tick_island()
            self.assertFalse(engine._island.suppressed)
            engine._on_island_probe({"game": None})
            for _ in range(12):
                engine._tick_island()
            self.assertTrue(engine._island.suppressed)

    def test_discord_call_buttons(self):
        engine, _host, probe = self.make()
        engine._on_island_probe({"discord": {"since": time.time() - 30, "where": "@Ana", "mic_muted": False,
                                             "deafened": False, "volume": 0.7}})
        self.assertEqual(engine._island.main.kind, "discord")
        engine._on_island_action("discord:up")
        probe.command.assert_called_with("discord_up")
        done = threading.Event()
        replies = []
        engine._island_discord_done.connect(lambda reply: (replies.append(reply), done.set()))
        with mock.patch("luxai.discord_island.toggle_discord", return_value="Microfon oprit.") as toggled:
            engine._on_island_action("discord:mic")
            for _ in range(100):
                QCoreApplication.processEvents()
                if done.is_set():
                    break
                time.sleep(0.01)
        toggled.assert_called_once_with("mic", "ro")
        self.assertEqual(replies, ["Microfon oprit."])
        self.assertFalse(engine._island_discord_busy)

    def test_steam_download_and_finish(self):
        engine, _host, _probe = self.make()
        download = {"appid": "1222140", "phase": "downloading", "downloaded": 2e10, "total": 5.5e10, "rate": 3e7,
                    "eta": 1000, "name": "Detroit: Become Human", "icon": b""}
        engine._on_island_probe({"steam": download})
        self.assertEqual(engine._island.main.kind, "steam")
        with mock.patch("os.startfile", create=True) as opened:
            engine._on_island_action("tap:steam")
        opened.assert_called_once_with("steam://open/downloads")
        engine._on_island_probe({"steam": None, "steam_done": {"appid": "1222140", "at": time.time(),
                                                                "name": "Detroit: Become Human"}})
        self.assertEqual((engine._island.main.kind, engine._island.main.title), ("steam_done", "Detroit: Become Human"))

    def test_games_off_stops_detection(self):
        from luxai import status_island as module
        with mock.patch.object(module, "IslandProbe") as made:
            engine, _host, _probe = self.make(p_games="off")
            engine._island_probe = None
            engine._apply_island()
        self.assertFalse(made.call_args.kwargs["games"])
        self.assertFalse(made.call_args.kwargs["notifications"])  # off by default
        self.assertTrue(made.call_args.kwargs["discord"] and made.call_args.kwargs["steam"])


STEAM_LOG = """[2026-11-27 20:54:14] AppID 1222140 update canceled : Priority (Suspended)
[2026-11-27 20:54:17] AppID 1222140 state changed : Update Required,Update Queued,Update Running,Update Started,
[2026-11-27 20:54:17] AppID 1222140 update started : download 14309456/54953473904, store 0/0, reuse 0/0, delta 0/0, stage 15878289/63077578235
[2026-11-27 20:54:17] AppID 1222140 App update changed : Running Update,Downloading,Staging,
[2026-11-27 20:55:17] Current download rate: 240.000 Mbps
[2026-11-27 20:56:17] Current download rate: 240.000 Mbps
"""


class SteamDownloadTests(unittest.TestCase):
    """0.4.3y: Steam downloads from Steam's own content log (progress, speed, time left, paused, finished)."""

    def feed(self, text):
        from luxai.steam_activity import SteamDownloads
        downloads = SteamDownloads()
        for line in text.splitlines():
            downloads.feed(line)
        return downloads

    def stamp(self, text):
        import datetime as dt
        return dt.datetime.strptime(text, "%Y-%m-%d %H:%M:%S").timestamp()

    def test_progress_speed_and_time_left(self):
        downloads = self.feed(STEAM_LOG)
        state = downloads.state(self.stamp("2026-11-27 20:56:17"))
        self.assertEqual((state["appid"], state["phase"]), ("1222140", "downloading"))
        self.assertAlmostEqual(state["rate"], 30e6)
        self.assertAlmostEqual(state["downloaded"], 14309456 + 30e6 * 60, delta=1)  # one minute at the last rate
        self.assertAlmostEqual(state["eta"], (54953473904 - state["downloaded"]) / 30e6, delta=1)
        later = downloads.state(self.stamp("2026-11-27 20:57:17"))  # estimated between the log lines
        self.assertGreater(later["downloaded"], state["downloaded"])

    def test_paused_and_finished(self):
        downloads = self.feed(STEAM_LOG + "[2026-11-27 21:00:00] AppID 1222140 App update changed : None\n")
        self.assertEqual(downloads.state()["phase"], "paused")
        downloads.feed("[2026-11-27 21:30:00] AppID 1222140 finished update, 1 mounted depots (BuildID 1)")
        self.assertIsNone(downloads.state())
        self.assertEqual(downloads.take_done()[0]["appid"], "1222140")
        self.assertEqual(downloads.take_done(), [])

    def test_a_silent_log_is_not_a_running_download(self):
        downloads = self.feed(STEAM_LOG)
        state = downloads.state(self.stamp("2026-11-27 21:30:00"))
        self.assertEqual(state["phase"], "paused")
        self.assertIsNone(state["eta"])

    def test_the_log_is_followed_from_its_end_and_after_rotation(self):
        from luxai.steam_activity import SteamDownloads
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        log = Path(folder.name) / "content_log.txt"
        log.write_text("[2026-11-27 10:00:00] old line\n" + STEAM_LOG, encoding="utf-8")
        downloads = SteamDownloads(log)
        downloads.poll()
        self.assertEqual(downloads.state()["appid"], "1222140")
        with open(log, "a", encoding="utf-8") as handle:
            handle.write("[2026-11-27 20:57:00] AppID 1222140 App update changed : Running Update,Verifying,\n")
        downloads.poll()
        self.assertEqual(downloads.state()["phase"], "verifying")
        log.write_text("[2026-11-27 22:00:00] AppID 1222140 finished update\n", encoding="utf-8")  # Steam rotated
        downloads.poll()
        self.assertIsNone(downloads.state())

    def test_words_and_units(self):
        from luxai.steam_activity import human_bytes, human_eta, human_rate
        self.assertEqual(human_bytes(21.8e9, "ro"), "21,8 GB")
        self.assertEqual(human_bytes(21.8e9, "en"), "21.8 GB")
        self.assertEqual(human_rate(33e6, "ru"), "33 МБ/с")
        self.assertEqual(human_eta(997, "ro"), "16 min")
        self.assertEqual(human_eta(3900, "en"), "1 h 05 min")
        activity = si.steam_activity({"appid": "1222140", "phase": "downloading", "downloaded": 21.8e9, "total": 55e9,
                                      "rate": 33e6, "eta": 997, "name": "Detroit: Become Human"}, "ro")
        self.assertEqual(activity.title, "Detroit: Become Human")
        self.assertIn("Se descarcă", activity.subtitle)
        self.assertEqual(activity.data["percent"], "40%")


class DiscordCallTests(unittest.TestCase):
    """0.4.3y: a Discord voice call — Windows says Discord holds the mic; the panel says where."""

    def test_a_call_with_where_mic_and_duration(self):
        from luxai.discord_island import DiscordCall
        holds = {"value": True}
        panel = mock.Mock(return_value={"connected": True, "where": "@Ana", "mic_muted": True, "deafened": False})
        call = DiscordCall(holds_microphone=lambda: holds["value"], panel_reader=panel, window_finder=lambda: 77)
        with mock.patch("luxai.discord_island.discord_volume", return_value=0.8):
            state = call.poll(1000.0)
            self.assertEqual((state["where"], state["mic_muted"], state["volume"]), ("@Ana", True, 0.8))
            call.poll(1001.0)
            self.assertEqual(panel.call_count, 1)  # the window is read every 3 s, not every second
            activity = si.discord_activity(call.poll(1065.0), 1065.0, "ro")
        self.assertEqual(activity.title, "Apel Discord")
        self.assertEqual(activity.data["elapsed"], "1:05")
        self.assertIn("microfon oprit", activity.subtitle)
        holds["value"] = False
        self.assertIsNone(call.poll(1070.0))

    def test_an_unreadable_window_still_shows_the_call(self):
        from luxai.discord_island import DiscordCall
        call = DiscordCall(holds_microphone=lambda: True, panel_reader=mock.Mock(side_effect=OSError("elevated")),
                           window_finder=lambda: 77)
        with mock.patch("luxai.discord_island.discord_volume", return_value=None):
            state = call.poll(1000.0)
        self.assertEqual(state["where"], "")
        self.assertEqual(si.discord_activity(state, 1000.0, "en").subtitle, "Voice channel")

    def test_volume_steps_stay_between_0_and_100(self):
        from luxai import discord_island as di
        volume = SimpleNamespace(level=0.95)
        session = SimpleNamespace(SimpleAudioVolume=SimpleNamespace(
            GetMasterVolume=lambda: volume.level, SetMasterVolume=lambda value, _ctx: setattr(volume, "level", value)))
        with mock.patch.object(di, "_discord_sessions", return_value=[session, session]):
            self.assertEqual(di.change_discord_volume(0.1), 1.0)
            self.assertEqual(di.change_discord_volume(-0.1), 0.9)
        with mock.patch.object(di, "_discord_sessions", return_value=[]):
            self.assertIsNone(di.change_discord_volume(0.1))

    def test_the_island_never_presses_discords_shortcut(self):
        from luxai import discord_island as di
        with mock.patch("luxai.discord_audio.set_discord_audio", return_value=None), \
                mock.patch("luxai.discord_audio.force_toggle") as forced:
            reply = di.toggle_discord("mic", "ro")
        forced.assert_not_called()  # it would bring Discord to the front, out of a game
        self.assertIn("Discord", reply)


class PriorityTests(unittest.TestCase):
    """0.4.3y: every source has a priority (or «Off»): e.g. only Discord, or Discord before Jarvis."""

    def test_only_discord(self):
        settings = dict(DEFAULTS, **{f"p_{source}": "off" for source in si.SOURCES if source != "discord"})
        activities = [si.Activity("media", "Song"), si.Activity("speaking", "Jarvis"), si.Activity("discord", "Call"),
                      si.Activity("timer", "Timer"), si.Activity("ring", "Ring")]
        main, second = si.choose(activities, settings)
        self.assertEqual(main.kind, "discord")
        self.assertIsNone(second)

    def test_a_higher_priority_wins_and_equal_ones_keep_the_natural_order(self):
        activities = [si.Activity("speaking", "Jarvis"), si.Activity("discord", "Call")]
        self.assertEqual(si.choose(activities, DEFAULTS)[0].kind, "speaking")
        self.assertEqual(si.choose(activities, dict(DEFAULTS, p_discord="high"))[0].kind, "discord")
        self.assertEqual(si.choose(activities, dict(DEFAULTS, p_jarvis="low"))[0].kind, "discord")

    def test_a_ringing_alarm_beats_high_but_not_first(self):
        activities = [si.Activity("ring", "Ring"), si.Activity("discord", "Call")]
        self.assertEqual(si.choose(activities, dict(DEFAULTS, p_discord="high"))[0].kind, "ring")
        self.assertEqual(si.choose(activities, dict(DEFAULTS, p_discord="top", p_timers="low"))[0].kind, "discord")

    def test_the_reply_switch_still_works(self):
        self.assertIsNone(si.choose([si.Activity("reply", "Jarvis")], dict(DEFAULTS, show_reply=False))[0])

    def test_a_damaged_level_falls_back(self):
        self.assertEqual(si.level("media", {"p_media": "loud"}), si.LEVELS["normal"])


class CatalogTests(unittest.TestCase):
    def test_ready_with_every_setting_in_a_section_once(self):
        plugin = catalog.PLUGIN_BY_ID["status_island"]
        self.assertTrue(plugin.ready)
        keys = [key for section in catalog.sections_for(plugin) for key in section.keys]
        self.assertEqual(sorted(keys), sorted(setting.key for setting in plugin.settings))
        self.assertEqual(len(keys), len(set(keys)))

    def test_grid_sections_hold_only_switches(self):
        plugin = catalog.PLUGIN_BY_ID["status_island"]
        kinds = {setting.key: setting.kind for setting in plugin.settings}
        for section in catalog.sections_for(plugin):
            for _title, keys in section.groups:
                self.assertTrue(all(kinds[key] == "bool" for key in keys), section.id)

    def test_all_texts_in_three_languages(self):
        plugin = catalog.PLUGIN_BY_ID["status_island"]
        values = [plugin.title, plugin.description, catalog.BASIC_NOTE["status_island"]]
        for setting in plugin.settings:
            values.append(setting.label)
            values.extend(label for _value, label in setting.options)
            values.extend(item for item in (setting.hint, setting.suffix) if item)
        for value in values:
            self.assertEqual(set(value), {"ru", "en", "ro"})
            self.assertTrue(all(value[language].strip() for language in ("ru", "en", "ro")), value)

    def test_hostile_settings_are_cleaned(self):
        state = catalog.normalize_state({"status_island": {"enabled": True, "settings": {
            "size": "9999", "opacity": "-5", "idle": ["x"], "offset": float("nan"), "hover_delay": 10 ** 9}}})
        settings = state["status_island"]["settings"]
        self.assertEqual(settings["size"], "100")
        self.assertIn(settings["idle"], ("dot", "clock", "clock_date", "hide"))
        self.assertTrue(40 <= settings["opacity"] <= 100)
        self.assertTrue(0 <= settings["offset"] <= 80)
        self.assertTrue(0 <= settings["hover_delay"] <= 1500)

    def test_no_hostile_value_of_any_plugin_crashes_the_loader(self):
        hostile = (float("inf"), float("nan"), ["x"], {"a": 1}, None, 10 ** 30, "", "\x00")
        for plugin in catalog.PLUGINS:
            for value in hostile:
                raw = {plugin.id: {"enabled": True, "settings": {s.key: value for s in plugin.settings}}}
                state = catalog.normalize_state(raw)  # must not raise
                self.assertIn(plugin.id, state)

    def test_stopping_the_hotkey_listener_while_its_thread_exits(self):
        """The pump thread cleared _thread_id between the check and PostThreadMessageW (flaky ArgumentError)."""
        from luxai.command_triggers import WindowsHotkeyListener

        class Vanishing(WindowsHotkeyListener):
            reads = 0

            @property
            def _thread_id(self):
                Vanishing.reads += 1
                return 1234 if Vanishing.reads == 1 else None

            @_thread_id.setter
            def _thread_id(self, value):
                pass

        listener = Vanishing(lambda _identifier: None)
        with mock.patch("ctypes.windll", create=True) as windll:
            listener._post(0x0012)
        windll.user32.PostThreadMessageW.assert_called_once_with(1234, 0x0012, 0, 0)

    def test_the_media_api_is_a_dependency(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        for package in ("winrt-runtime", "winrt-Windows.Media.Control", "winrt-Windows.Storage.Streams",
                        "winrt-Windows.Foundation"):
            self.assertIn(package, requirements)


if __name__ == "__main__":
    unittest.main()
