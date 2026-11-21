"""0.4.3l: review of Codex's browser-caption work (0.4.3g–k), measured on a real YouTube page.

- The video wait is a setting («Wait for captions»: start / off / always), short, and the opening is ready
  after a 12 s reserve (it waited for the whole buffered minute: 28 s, 70 s with ads).
- Only NEW audio is sent (34 MB in two minutes before, 5.7 MB after); Jarvis rebuilds the window from
  numbered pieces and asks for the whole window only when a piece is missing.
"""
from __future__ import annotations

import base64
import http.client
import json
import unittest
from pathlib import Path

from luxai import film_captions as fc

ROOT = Path(__file__).resolve().parents[1]


def packet(pieces, *, full=False, epoch=1, offset=0.0, header=b"HDR"):
    return {"kind": "webm", "track": 1, "offset": offset, "epoch": epoch, "full": full, "header": header,
            "pieces": pieces}


class AssemblyTests(unittest.TestCase):
    def test_new_pieces_extend_the_window(self):
        assembly = fc.BufferAssembly()
        whole, need = assembly.feed("p", packet([(1, 0, b"aa"), (2, 0, b"bb")], full=True))
        self.assertEqual((whole[3], need), (b"HDRaabb", False))
        whole, need = assembly.feed("p", packet([(2, 2, b"BB"), (3, 0, b"cc")]))
        self.assertEqual((whole[3], need), (b"HDRaabbBBcc", False))

    def test_a_missing_piece_asks_for_the_whole_window(self):
        assembly = fc.BufferAssembly()
        assembly.feed("p", packet([(1, 0, b"aa")], full=True))
        self.assertEqual(assembly.feed("p", packet([(3, 0, b"cc")])), (None, True))   # piece 2 never came
        self.assertEqual(assembly.feed("p", packet([(4, 0, b"dd")])), (None, True))   # still nothing to build on
        whole, need = assembly.feed("p", packet([(2, 0, b"bb"), (3, 0, b"cc"), (4, 0, b"dd")], full=True))
        self.assertEqual((whole[3], need), (b"HDRbbccdd", False))

    def test_a_continuation_must_start_where_the_piece_ended(self):
        assembly = fc.BufferAssembly()
        assembly.feed("p", packet([(1, 0, b"aaaa")], full=True))
        self.assertEqual(assembly.feed("p", packet([(1, 2, b"xx")])), (None, True))

    def test_a_new_epoch_or_offset_is_a_new_window(self):
        assembly = fc.BufferAssembly()
        assembly.feed("p", packet([(1, 0, b"aa")], full=True))
        self.assertEqual(assembly.feed("p", packet([(2, 0, b"bb")], epoch=2)), (None, True))
        whole, _ = assembly.feed("p", packet([(5, 0, b"ee")], full=True, offset=30.0))
        self.assertEqual((whole[2], whole[3]), (30.0, b"HDRee"))

    def test_the_window_stays_bounded(self):
        assembly = fc.BufferAssembly()
        big = b"x" * (fc.MAX_AUDIO_BYTES // 2 + 10)
        assembly.feed("p", packet([(1, 0, big)], full=True))
        assembly.feed("p", packet([(2, 0, big)]))
        whole, _ = assembly.feed("p", packet([(3, 0, big)]))
        self.assertLessEqual(len(whole[3]), fc.MAX_AUDIO_BYTES + 3)

    def test_players_are_kept_apart_and_bounded(self):
        assembly = fc.BufferAssembly()
        for owner in range(10):
            assembly.feed(owner, packet([(1, 0, b"aa")], full=True))
        self.assertEqual(len(assembly._windows), fc.BufferAssembly.WINDOWS)

    def test_report_parsing_validates_pieces(self):
        def report(pieces, header=b"HDR"):
            return json.dumps({"tab": 1, "page": "https://www.youtube.com/watch?v=x", "active": True, "visible": True,
                               "buffer": {"kind": "webm", "track": 1, "offset": 0, "epoch": 1, "full": True,
                                          "header": base64.b64encode(header).decode(),
                                          "pieces": pieces}}).encode()
        good = fc.parse_report(report([[1, 0, base64.b64encode(b"aa").decode()]]), with_audio=True)
        self.assertEqual(good["buffer"]["pieces"], [(1, 0, b"aa")])
        for bad in ([[0, 0, "YWE="]], [[1, -1, "YWE="]], [[1, 0, "not base64!"]], [[1, 0]], [],
                    [[1, 0, "YWE="]] * (fc.MAX_PIECES + 1)):
            self.assertIsNone(fc.parse_report(report(bad), with_audio=True), bad)
        self.assertIsNone(fc.parse_report(report([[1, 0, "YWE="]], header=b"h" * 40000), with_audio=True))


class BridgeWaitTests(unittest.TestCase):
    def post(self, port, path, body):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("POST", path, body=json.dumps(body).encode(), headers={
            "Origin": "chrome-extension://" + "a" * 32, "X-Jarvis-Token": "t" * 48, "Content-Type": "application/json"})
        answer = connection.getresponse()
        return json.loads(answer.read() or b"{}")

    def test_wait_mode_decides_what_the_extension_may_do(self):
        underruns = []
        bridge = fc.BridgeServer(lambda _r: None, port=47394, token="t" * 48, on_preroll=lambda _r: None,
                                 on_underrun=lambda r: underruns.append(1) or True)
        self.assertTrue(bridge.start())
        self.addCleanup(bridge.stop)
        bridge.want = True
        state = {"tab": 1, "page": "https://site.example/film", "paused": False, "active": True, "visible": True}
        answer = self.post(47394, "/v1/state", state)
        self.assertEqual((answer["preroll"], answer["hold_ms"]), (True, fc.OPENING_HOLD_MS))
        self.assertNotIn("underrun", answer)  # «only at the start»: never held during the film
        bridge.wait_mode = "always"
        self.assertTrue(self.post(47394, "/v1/state", state)["underrun"])
        bridge.wait_mode = "off"
        answer = self.post(47394, "/v1/state", state)
        self.assertNotIn("preroll", answer)
        self.assertNotIn("underrun", answer)
        bridge.wait_mode = "nonsense"
        self.assertEqual(bridge.wait_mode, "start")

    def test_the_bridge_rebuilds_pieces_and_asks_again_after_a_gap(self):
        reports = []
        bridge = fc.BridgeServer(reports.append, port=47395, token="t" * 48)
        self.assertTrue(bridge.start())
        self.addCleanup(bridge.stop)
        bridge.want = True

        def audio(pieces, full):
            return {"tab": 1, "doc": "d", "session": 1, "page": "https://www.youtube.com/watch?v=x", "active": True,
                    "visible": True, "paused": False,
                    "buffer": {"kind": "webm", "track": 1, "offset": 0, "epoch": 1, "full": full,
                               "header": base64.b64encode(b"H").decode(),
                               "pieces": [[n, 0, base64.b64encode(data).decode()] for n, data in pieces]}}
        self.assertNotIn("need_full", self.post(47395, "/v1/audio", audio([(1, b"a")], True)))
        self.assertEqual(reports[-1]["buffer"][3], b"Ha")
        self.assertTrue(self.post(47395, "/v1/audio", audio([(3, b"c")], False))["need_full"])
        self.assertIsNone(reports[-1]["buffer"])


class SettingTests(unittest.TestCase):
    def test_wait_setting_and_opening_reserve(self):
        from luxai.extensions_catalog import PLUGINS
        live = next(plugin for plugin in PLUGINS if plugin.id == "live_captions")
        wait = next(setting for setting in live.settings if setting.key == "film_wait")
        self.assertEqual(wait.default, "start")
        self.assertEqual([value for value, _label in wait.options], ["start", "off", "always"])
        self.assertLessEqual(fc.OPENING_HOLD_MS, 10000)
        self.assertLessEqual(fc.OPENING_RESERVE_SECONDS, 15.0)


class ExtensionCodeTests(unittest.TestCase):
    def test_extension_contract(self):
        page = (ROOT / "browser_extension" / "youtube_audio.js").read_text(encoding="utf-8")
        content = (ROOT / "browser_extension" / "content.js").read_text(encoding="utf-8")
        background = (ROOT / "browser_extension" / "background.js").read_text(encoding="utf-8")
        manifest = json.loads((ROOT / "browser_extension" / "manifest.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(tuple(map(int, manifest["version"].split("."))), (1, 9, 0))
        self.assertIn("chunk.sent = chunk.size", page)               # only new bytes
        self.assertIn('"jarvis-buffer-resync"', page)                # whole window again on request
        self.assertIn("old.pieces.concat(next.pieces)", content)      # never dropped in the page…
        self.assertIn("old.pieces.concat(next.pieces)", background)   # …nor in the background queue
        self.assertIn("MIN_HELD_DURATION = 60", content)             # ads and previews are never held
        self.assertIn('.ad-showing', content)
        self.assertIn("preparationLimit - heldMs", content)          # one short budget per page
        self.assertIn('prerollSupported = data.preroll === true', background)  # «off» is honoured at once


if __name__ == "__main__":
    unittest.main()
