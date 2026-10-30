"""Availability is not a generated reply; only real GGUF results prove health."""
import json
import ntpath
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from PySide6.QtCore import QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from luxai import gguf_backend as backend
from luxai import local_ai_health as health
from luxai.local_ai_status import (
    LocalAIStatus, LocalAIStatusMonitor, configuration_signature, inspect_local_ai,
)
from luxai.local_models import MIN_GGUF_BYTES


class LocalAIHealth093dTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.model = Path(directory.name) / "model.gguf"
        self.model.write_bytes(b"GGUF" + b"\0" * MIN_GGUF_BYTES)
        self.config = {"llm_model_path": str(self.model), "local_llm_fallback_enabled": True}
        self.installed = mock.patch("luxai.local_ai_status.importlib.util.find_spec", return_value=object())
        self.installed.start()
        self.addCleanup(self.installed.stop)

    def result(self, reply="Actual model reply", **options):
        result = {"choices": [{"message": {"content": reply}}]}
        return SimpleNamespace(returncode=options.get("returncode", 0),
                               stdout=backend.SENTINEL + json.dumps(result), stderr="")

    def test_disabled_and_missing_models_do_not_report_available(self):
        with mock.patch("luxai.local_ai_status.resolve_model_path") as resolve:
            state = inspect_local_ai(dict(self.config, local_llm_fallback_enabled=False))
            self.assertEqual(state.state, "disabled")
            resolve.assert_not_called()
            resolve.return_value = None
            self.assertEqual(inspect_local_ai({}).state, "no_model")

    def test_incomplete_file_and_missing_or_preparing_engine_are_distinct(self):
        self.model.write_bytes(b"GGUF")
        self.assertEqual(inspect_local_ai(self.config).state, "invalid_model")
        self.model.write_bytes(b"GGUF" + b"\0" * MIN_GGUF_BYTES)
        with (mock.patch("luxai.local_ai_status.importlib.util.find_spec", return_value=None),
              mock.patch("luxai.local_ai_setup.setup_status", return_value="installing")):
            self.assertEqual(inspect_local_ai(self.config).state, "preparing")
        with (mock.patch("luxai.local_ai_status.importlib.util.find_spec", return_value=None),
              mock.patch("luxai.local_ai_setup.setup_status", return_value="ready")):
            self.assertEqual(inspect_local_ai(self.config).state, "engine_missing")

    def test_availability_never_loads_the_model_or_claims_success(self):
        with mock.patch.object(backend.IsolatedGGUF, "__init__", side_effect=AssertionError("no model load")):
            self.assertEqual(inspect_local_ai(self.config).state, "available")
        self.assertIsNone(health.inference_status(health.model_identity(self.model)))

    def test_real_nonempty_backend_reply_proves_health(self):
        model = backend.IsolatedGGUF(str(self.model))
        with mock.patch.object(backend.subprocess, "run", return_value=self.result()) as run:
            model.create_chat_completion(messages=[{"role": "user", "content": "private prompt"}])
        self.assertEqual(inspect_local_ai(self.config).state, "success")
        observed = health.inference_status(health.model_identity(self.model))
        self.assertEqual(set(observed), {"request", "state", "code"})
        self.assertNotIn("private prompt", repr(observed))
        run.assert_called_once()

    def test_empty_malformed_timeout_and_crash_results_are_not_success(self):
        model = backend.IsolatedGGUF(str(self.model))
        for result, code in ((self.result(""), "empty_reply"),
                             (self.result(returncode=1), "worker_failed"),
                             (SimpleNamespace(returncode=0, stdout="missing sentinel", stderr=""), "invalid_reply")):
            with self.subTest(code=code), mock.patch.object(backend.subprocess, "run", return_value=result):
                if code == "empty_reply":
                    model("hello")
                else:
                    with self.assertRaises(backend.GGUFWorkerError):
                        model("hello")
                state = inspect_local_ai(self.config)
                self.assertEqual((state.state, state.error), ("error", code))
        with mock.patch.object(backend.subprocess, "run", side_effect=subprocess.TimeoutExpired("worker", 1)):
            with self.assertRaises(backend.GGUFWorkerError):
                model("hello")
        self.assertEqual(inspect_local_ai(self.config).error, "timeout")

    def test_busy_retry_does_not_erase_another_inflight_request(self):
        token = health.begin_inference(self.model)
        before = health.inference_status(health.model_identity(self.model))
        with mock.patch.object(backend, "_INFERENCE_LOCK") as lock:
            lock.acquire.return_value = False
            with self.assertRaises(backend.GGUFWorkerError) as error:
                backend.IsolatedGGUF(str(self.model))("hello")
            self.assertEqual(error.exception.code, "busy")
            lock.release.assert_not_called()
        self.assertEqual(health.inference_status(health.model_identity(self.model)), before)
        health.finish_inference(token, True)
        self.assertEqual(inspect_local_ai(self.config).state, "success")

    def test_replacing_model_file_and_old_completions_cannot_reuse_green_status(self):
        older = health.begin_inference(self.model)
        newer = health.begin_inference(self.model)
        self.assertFalse(health.finish_inference(older, True))
        self.assertEqual(inspect_local_ai(self.config).state, "working")
        health.finish_inference(newer, True)
        self.assertEqual(inspect_local_ai(self.config).state, "success")
        with self.model.open("ab") as source:
            source.write(b"replacement")
        self.assertEqual(inspect_local_ai(self.config).state, "available")

    def test_windows_short_long_and_case_aliases_share_physical_file_health(self):
        short = r"C:\Users\RUNNER~1\models\model.gguf"
        long = "c:/users/runner admin/models/model.gguf"
        aliases = {short: r"C:\Users\Runner Admin\models\MODEL.gguf",
                   long: r"c:\users\runner admin\models\model.gguf"}
        physical_model = self.model

        class WindowsFile:
            def __init__(self, name):
                self.name = name

            def __str__(self):
                return self.name

            def resolve(self):
                return WindowsFile(aliases.get(self.name, self.name))

            def stat(self):
                return physical_model.stat()

        with (mock.patch.object(health, "Path", side_effect=lambda value: WindowsFile(str(value))),
              mock.patch.object(health, "os", SimpleNamespace(path=SimpleNamespace(normcase=ntpath.normcase)))):
            token = health.begin_inference(short)
            identity = health.model_identity(long)
            self.assertEqual(identity[0], ntpath.normcase(aliases[long]))
            self.assertEqual(health.inference_status(identity)["state"], "working")
            health.finish_inference(token, True)
            self.assertEqual(health.inference_status(identity)["state"], "success")
            with physical_model.open("ab") as source:
                source.write(b"replacement")
            self.assertIsNone(health.inference_status(health.model_identity(long)))


class LocalAIStatusMonitor093dTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def monitor(self, config, probe):
        monitor = LocalAIStatusMonitor(lambda: dict(config), probe=probe)
        self.addCleanup(monitor.close)
        return monitor

    def wait(self, condition):
        end = time.monotonic() + 3
        while not condition() and time.monotonic() < end:
            QTest.qWait(10)
        self.assertTrue(condition())

    def test_model_switch_rejects_stale_success_and_runs_only_one_probe(self):
        config = {"llm_model_path": "old.gguf"}
        entered = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)
        calls = []
        def probe(captured):
            calls.append((captured["llm_model_path"], threading.get_ident()))
            if captured["llm_model_path"] == "old.gguf":
                entered.set()
                release.wait(2)
            return LocalAIStatus("success" if captured["llm_model_path"] == "old.gguf" else "available",
                                 configuration_signature(captured))
        monitor = self.monitor(config, probe)
        states = []
        monitor.changed.connect(states.append)
        monitor.refresh()
        self.assertTrue(entered.wait(1))
        config["llm_model_path"] = "new.gguf"
        monitor.refresh()
        monitor.refresh()
        release.set()
        self.wait(lambda: monitor.current.state == "available")
        self.assertFalse(any(state.state == "success" for state in states))
        self.assertEqual([call[0] for call in calls], ["old.gguf", "new.gguf"])
        self.assertTrue(all(call[1] != threading.get_ident() for call in calls))

    def test_visible_only_polling_and_shutdown_ignore_late_worker_results(self):
        config = {}
        gate = threading.Event()
        self.addCleanup(gate.set)
        def probe(captured):
            gate.wait(2)
            return LocalAIStatus("success", configuration_signature(captured))
        monitor = self.monitor(config, probe)
        host = QWidget()
        self.addCleanup(host.close)
        monitor.watch(host)
        host.show()
        self.app.processEvents()
        self.assertTrue(monitor._timer.isActive())
        host.hide()
        self.assertFalse(monitor._timer.isActive())
        states = []
        monitor.changed.connect(states.append)
        monitor.close()
        gate.set()
        QTest.qWait(30)
        self.assertEqual(states, [])

    def test_addons_has_only_readonly_local_state_and_retains_cloud_check(self):
        import main
        class AddonsHost(QWidget):
            build_addons = main.MainWindow.build_addons
            _render_local_ai_status = main.MainWindow._render_local_ai_status
            _refresh_local_ai_status = main.MainWindow._refresh_local_ai_status
            def __init__(self):
                super().__init__()
                self.cfg = {"local_llm_fallback_enabled": False}
                self.pages = QStackedWidget()
                QVBoxLayout(self).addWidget(self.pages)
                self._update_cloud_indicator = mock.Mock()
                self._start_cloud_check = mock.Mock()
                self.build_addons()
        host = AddonsHost()
        self.addCleanup(host.close)
        self.addCleanup(host._local_ai_monitor.close)
        host.show()
        self.wait(lambda: host._local_ai_monitor.current.state == "disabled")
        buttons = host.pages.widget(0).findChildren(QPushButton)
        self.assertEqual(buttons, [host.cloud_check_button])
        self.assertIn("выключен", host.local_ai_indicator.text())
        self.assertFalse(hasattr(host, "pick_model"))


if __name__ == "__main__":
    unittest.main()
