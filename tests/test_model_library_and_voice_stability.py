"""Portable local AI / voice stability regression tests (offline, no microphone)."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest import mock

from luxai.local_models import available_models, resolve_model_path
from luxai.gguf_backend import IsolatedGGUF, GGUFWorkerError, SENTINEL


def gguf(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"GGUF" + b"\x00" * 1_048_577)
    return path


class PortableModelTests(unittest.TestCase):
    def test_discovers_nested_files_and_flags_partial_download(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            first = gguf(base / "small.gguf")
            nested = gguf(base / "large" / "other.GGUF")
            broken = base / "bad.gguf"
            broken.write_bytes(b"unfinished")
            found = available_models(base)
            self.assertEqual(len(found), 3)
            self.assertEqual({p.name for p in (first, nested)}, {"small.gguf", "other.GGUF"})
            self.assertFalse(next(i for i in found if i["name"] == "bad.gguf")["valid"])
            self.assertTrue(next(i for i in found if i["name"] == "small.gguf")["valid"])

    def test_restores_model_copied_from_another_windows_pc(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            copied = gguf(base / "Qwen3-8B-Q4_K_M.gguf")
            old = r"C:\Users\vlad\Desktop\LuxAI_Local\models\Qwen3-8B-Q4_K_M.gguf"
            self.assertEqual(resolve_model_path(old, directory=base), copied.resolve())

    def test_ambiguous_model_name_does_not_select_random_file(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            gguf(base / "a" / "shared.gguf")
            gguf(base / "b" / "shared.gguf")
            self.assertIsNone(resolve_model_path(r"C:\Other\models\shared.gguf", directory=base))

    def test_isolated_gguf_crash_does_not_crash_main(self):
        fake = subprocess.CompletedProcess(
            args=["python"], returncode=3221225477, stdout="", stderr="Access violation"
        )
        with mock.patch("luxai.gguf_backend.subprocess.run", return_value=fake):
            with self.assertRaisesRegex(GGUFWorkerError, "Jarvis remains running"):
                IsolatedGGUF("example.gguf").create_chat_completion(
                    messages=[{"role": "user", "content": "hello"}],
                )

    def test_isolated_gguf_success_and_timeout(self):
        fake = subprocess.CompletedProcess(
            args=["python"], returncode=0,
            stdout=SENTINEL + json.dumps({"choices": [{"message": {"content": "hello"}}]}) + "\n",
            stderr=""
        )
        with mock.patch("luxai.gguf_backend.subprocess.run", return_value=fake) as run:
            response = IsolatedGGUF("example.gguf").create_chat_completion(
                messages=[{"role": "user", "content": "hello"}]
            )
            self.assertEqual(response["choices"][0]["message"]["content"], "hello")
            self.assertIn("luxai.gguf_worker", run.call_args.args[0])
        with mock.patch("luxai.gguf_backend.subprocess.run", side_effect=subprocess.TimeoutExpired("gguf", 1)):
            with self.assertRaisesRegex(GGUFWorkerError, "timed out"):
                IsolatedGGUF("example.gguf").create_chat_completion(messages=[])

    def test_voice_options_for_romanian_are_stronger(self):
        from luxai.voice import recognition_options
        ro = recognition_options("ro", 1)
        en = recognition_options("en", 1)
        self.assertGreaterEqual(ro["beam_size"], 3)
        self.assertEqual(en["beam_size"], 1)
        self.assertIn("română", ro["initial_prompt"])
        self.assertIsNone(en["initial_prompt"])
        self.assertFalse(ro["vad_filter"])

    def test_no_unsafe_qthread_termination(self):
        root = Path(__file__).resolve().parents[1]
        main = (root / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("worker.terminate()", main)
        self.assertIn("worker.stop_capture()", main)
        settings = (root / "luxai" / "settings_panel.py").read_text(encoding="utf-8")
        self.assertIn('"llm_model_path": self.model_select.currentData()', settings)
        self.assertIn('"whisper_model": self.whisper_model.currentData()', settings)


if __name__ == "__main__":
    unittest.main()
