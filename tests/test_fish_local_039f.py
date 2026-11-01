"""Offline Fish S2 release regressions: no cloud, optional assets, cancellation."""
from __future__ import annotations
import io
import json
import os
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest import mock
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from luxai import fish_local, voices
from luxai.fish_local_worker import PREFIX, Engine
from luxai import fish_local_setup


def wav_sample(sample_rate=24000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(b"\x00\x00" * 500)
    return buf.getvalue()


class FishLocalTests(unittest.TestCase):
    def test_local_engine_is_not_a_cloud_api_provider(self):
        self.assertEqual(fish_local.MODEL_NAME, "s2-pro-q4_k_m.gguf")
        self.assertEqual(fish_local.FISH_DIR.name, "fishaudio")
        self.assertNotIn("fish_local", ("fish",))
        self.assertNotIn("https://api.fish.audio", Path(fish_local.__file__).read_text("utf-8"))

    def test_speech_assets_are_not_downloaded_during_ready_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(fish_local, "FISH_DIR", Path(tmp)), mock.patch.object(
                    fish_local, "RUNTIME_DIR", Path(tmp) / "runtime"):
                found, code = fish_local.ready()
                self.assertFalse(found)
                self.assertEqual(code, "fish_model_missing")

    def test_cancelled_call_does_not_open_worker_or_fetch_model(self):
        with mock.patch.object(fish_local, "ready", return_value=(True, "ready")):
            with mock.patch.object(fish_local, "choose_runtime", return_value=Path("s2.dll")):
                with mock.patch("luxai.fish_local.subprocess.Popen") as popen:
                    engine = fish_local.ResidentEngine()
                    with self.assertRaises(fish_local.FishLocalError):
                        engine.synthesize("hello", cancelled=lambda: True)
                    popen.assert_not_called()

    def test_stop_does_not_wait_for_busy_synthesis_lock(self):
        class Dummy:
            def __init__(self):
                self.killed = False
            def poll(self):
                return None
            def terminate(self):
                self.killed = True
            def wait(self, timeout):
                return 0
        worker = fish_local.ResidentEngine()
        p = Dummy()
        worker._process = p
        worker._guard.acquire()
        outcome = []
        t = threading.Thread(target=lambda: (worker.stop(), outcome.append(True)))
        t.start()
        t.join(timeout=1.0)
        worker._guard.release()
        self.assertFalse(t.is_alive(), "Stop must not wait for synthesis lock")
        self.assertEqual(outcome, [True])
        self.assertTrue(p.killed)

    def test_install_package_rejects_remote_path_expansion(self):
        redirect = fish_local_setup.SafeRedirect()
        req = __import__("urllib.request", fromlist=["Request"]).Request(
            "https://huggingface.co/rodrigomt/s2-pro-gguf")
        with self.assertRaises(fish_local_setup.InstallError):
            redirect.redirect_request(req, None, 302, "moved", {},
                                      "http://127.0.0.1:8080/private")

    def test_existing_model_is_never_replaced_by_speech(self):
        with mock.patch.object(fish_local, "ready", return_value=(False, "fish_model_missing")):
            with mock.patch.object(fish_local, "choose_runtime") as choose:
                with self.assertRaisesRegex(fish_local.FishLocalError, "fish_model_missing"):
                    fish_local.ResidentEngine().synthesize("test")
                choose.assert_not_called()

    def test_worker_json_protocol_prefix_is_fixed(self):
        self.assertEqual(PREFIX, fish_local.PROTOCOL)
        self.assertTrue(PREFIX.startswith("FISH_LOCAL_"))

    def test_native_voice_playback_uses_no_api_key_or_fish_http(self):
        wav = wav_sample()
        settings = {"voice_engine": "fish_local", "voice_volume": 50,
                    "language": "ru", "fish_local_threads": 4}
        manager = voices.VoiceManager()
        with mock.patch.object(manager, "_load_config", return_value=settings), \
             mock.patch("luxai.fish_local.synthesize", return_value=wav) as synth, \
             mock.patch("luxai.secure_keys.get_api_key") as credentials, \
             mock.patch("sounddevice.play") as play, \
             mock.patch("sounddevice.wait"):
            result = manager._speak("Привет", "ru", voices._cancel_token())
        self.assertTrue(result)
        self.assertEqual(synth.call_args.args[0], "Привет")
        self.assertEqual(synth.call_args.kwargs["threads"], 4)
        credentials.assert_not_called()
        play.assert_called_once()

    def test_long_speech_is_segmented_not_truncated(self):
        manager = voices.VoiceManager()
        sentence = "Модель работает локально и отвечает голосом. "
        message = sentence * 16
        cfg = {"voice_engine": "fish_local", "voice_volume": 80, "language": "ru"}
        with mock.patch.object(manager, "_load_config", return_value=cfg), \
             mock.patch("luxai.fish_local.synthesize", return_value=wav_sample()) as synth, \
             mock.patch("sounddevice.play"), mock.patch("sounddevice.wait"):
            self.assertTrue(manager._speak(message, "ru", voices._cancel_token()))
        self.assertGreater(synth.call_count, 1)
        self.assertEqual(" ".join(call.args[0].strip() for call in synth.call_args_list),
                         " ".join(message[:700].split()))
        self.assertTrue(all(len(call.args[0]) <= 350 for call in synth.call_args_list))

    def test_native_44100_hz_audio_is_played_at_original_sample_rate(self):
        manager = voices.VoiceManager()
        cfg = {"voice_engine": "fish_local", "voice_volume": 70, "language": "ru"}
        with mock.patch.object(manager, "_load_config", return_value=cfg), \
             mock.patch("luxai.fish_local.synthesize", return_value=wav_sample(44100)), \
             mock.patch("sounddevice.play") as play, mock.patch("sounddevice.wait"):
            self.assertTrue(manager._speak("Привет", "ru", voices._cancel_token()))
        self.assertEqual(play.call_args.args[1], 44100)

    def test_settings_offer_offline_voice_without_key(self):
        from PySide6.QtWidgets import QApplication
        from luxai.settings_panel import SettingsPanel
        app = QApplication.instance() or QApplication([])
        panel = SettingsPanel({"voice_engine": "fish_local"}, lambda *_: None,
                              lambda *_: None, lambda *_: None)
        self.addCleanup(panel.close)
        self.assertEqual(panel.voice_engine.currentData(), "fish_local")
        self.assertEqual(panel.collect()["fish_local_threads"], 0)
        self.assertTrue(panel.fish_controls.isHidden())
        self.assertEqual(panel.collect()["fish_local_reference"], "")


if __name__ == "__main__":
    unittest.main()
