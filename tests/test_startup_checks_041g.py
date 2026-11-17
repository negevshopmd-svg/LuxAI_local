"""0.4.1g Startup: cloud and local AI are checked at once; Fish is warmed."""
import unittest
from unittest import mock

import main
from luxai.local_ai_status import LocalAIStatus


class _Thread:
    def __init__(self, target=None, **_kwargs):
        self.target = target

    def start(self):
        self.target()


class StartupChecksTests(unittest.TestCase):
    def fake(self):
        window = mock.Mock()
        window._closed = False
        window._cloud_first_check_done = False
        window.cfg = {"llm_model_path": "C:/models/test.gguf", "local_llm_fallback_enabled": True}
        return window

    def test_cloud_check_and_one_tiny_local_reply(self):
        window = self.fake()
        worker = mock.Mock()
        with mock.patch.object(main.threading, "Thread", _Thread), \
                mock.patch("luxai.local_ai_status.inspect_local_ai", return_value=LocalAIStatus("available", ())), \
                mock.patch("luxai.local_models.resolve_model_path", return_value="C:/models/test.gguf"), \
                mock.patch("luxai.gguf_backend.IsolatedGGUF", return_value=worker) as backend:
            main.MainWindow._startup_ai_checks(window)
        window._start_cloud_check.assert_called_once_with()
        self.assertTrue(window._cloud_first_check_done)
        backend.assert_called_once_with("C:/models/test.gguf")
        self.assertEqual(worker.create_chat_completion.call_args.kwargs["max_tokens"], 4)
        self.assertEqual(window.local_ai_checked.emit.call_count, 2)  # «working», then the result

    def test_no_model_or_already_confirmed_does_not_load_anything(self):
        for state in ("no_model", "disabled", "success", "engine_missing"):
            window = self.fake()
            window._cloud_first_check_done = True
            with mock.patch.object(main.threading, "Thread", _Thread), \
                    mock.patch("luxai.local_ai_status.inspect_local_ai", return_value=LocalAIStatus(state, ())), \
                    mock.patch("luxai.gguf_backend.IsolatedGGUF") as backend:
                main.MainWindow._startup_ai_checks(window)
            backend.assert_not_called()
            window._start_cloud_check.assert_not_called()

    def test_failure_never_crashes_startup(self):
        window = self.fake()
        with mock.patch.object(main.threading, "Thread", _Thread), \
                mock.patch("luxai.local_ai_status.inspect_local_ai", side_effect=RuntimeError("boom")):
            main.MainWindow._startup_ai_checks(window)
        window.local_ai_checked.emit.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
