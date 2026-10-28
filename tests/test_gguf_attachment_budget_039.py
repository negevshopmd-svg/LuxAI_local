"""Larger file requests opt into bounded GGUF resources without changing voice."""
from dataclasses import replace
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from luxai.attachment_chat import (
    MAX_LOCAL_CONTEXT_CHARS, MAX_LOCAL_REQUEST_CHARS, attachment_messages,
    respond_to_attachments,
)
from luxai.chat_attachments import load_attachment
from luxai.gguf_backend import GGUFWorkerError, IsolatedGGUF, SENTINEL, inference_budget
from luxai import gguf_worker


def completed():
    return subprocess.CompletedProcess(["python"], 0,
        stdout=SENTINEL + json.dumps({"choices": [{"message": {"content": "reply"}}]}) + "\n", stderr="")


class GGUFAttachmentBudget039Tests(unittest.TestCase):
    def request(self, **kwargs):
        with mock.patch("luxai.gguf_backend.subprocess.run", return_value=completed()) as run:
            IsolatedGGUF("fixture.gguf").create_chat_completion(
                messages=[{"role": "user", "content": "bounded request"}], **kwargs)
        return json.loads(run.call_args.kwargs["input"]), run.call_args.kwargs

    def test_default_voice_budget_and_timeout_remain_unchanged(self):
        payload, options = self.request(max_tokens=6000)
        self.assertNotIn("n_ctx", payload)
        self.assertEqual(payload["max_tokens"], 400)
        self.assertEqual(options["timeout"], 150)
        self.assertEqual(inference_budget(), (1536, 160))

    def test_explicit_file_budget_is_serialized_and_clamped_at_both_boundaries(self):
        payload, options = self.request(max_tokens=999999, n_ctx=999999)
        self.assertEqual((payload["n_ctx"], payload["max_tokens"]), (8192, 4096))
        self.assertEqual(options["timeout"], 300)
        low, _ = self.request(max_tokens=999999, n_ctx=-1)
        self.assertEqual((low["n_ctx"], low["max_tokens"]), (1536, 400))
        self.assertEqual(inference_budget(4096, 5000), (4096, 2048))

    def test_completion_fallback_keeps_extended_budget_and_does_not_cut_prompt_tail(self):
        with mock.patch("luxai.gguf_backend.subprocess.run", return_value=completed()) as run:
            IsolatedGGUF("fixture.gguf")("the complete prompt", max_tokens=4096, n_ctx=8192)
        payload = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(payload["prompt"], "the complete prompt")
        self.assertEqual((payload["n_ctx"], payload["max_tokens"]), (8192, 4096))
        long_prompt = "x" * 11000 + "TAIL"
        code, _, llm, _, _ = self.run_worker({
            "model": "fixture.gguf", "prompt": long_prompt, "n_ctx": 8192, "max_tokens": 100,
        }, prompt_tokens=3000)
        self.assertEqual(code, 0)
        self.assertEqual(llm.call_args.args[0], long_prompt)

    def run_worker(self, payload, prompt_tokens=1000):
        llm = mock.Mock()
        llm.tokenize.return_value = list(range(prompt_tokens))
        llm.create_chat_completion.return_value = {"choices": [{"message": {"content": "ok"}}]}
        llm.return_value = {"choices": [{"text": "ok"}]}
        constructor = mock.Mock(return_value=llm)
        output, error = io.StringIO(), io.StringIO()
        with (mock.patch.dict(sys.modules, {"llama_cpp": SimpleNamespace(Llama=constructor)}),
              mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))),
              mock.patch.object(sys, "stdout", output), mock.patch.object(sys, "stderr", error)):
            code = gguf_worker.main()
        return code, constructor, llm, output.getvalue(), error.getvalue()

    def test_real_worker_setup_keeps_default_memory_and_output_without_tokenizer_work(self):
        code, constructor, llm, output, _ = self.run_worker({
            "model": "fixture.gguf", "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 6000,
        })
        self.assertEqual(code, 0)
        self.assertEqual(constructor.call_args.kwargs["n_ctx"], 1536)
        self.assertEqual(llm.create_chat_completion.call_args.kwargs["max_tokens"], 400)
        llm.tokenize.assert_not_called()
        self.assertIn(SENTINEL, output)

    def test_extended_worker_caps_output_to_actual_remaining_prompt_space(self):
        code, constructor, llm, _, _ = self.run_worker({
            "model": "fixture.gguf", "messages": [{"role": "user", "content": "private text"}],
            "max_tokens": 999999, "n_ctx": 999999,
        }, prompt_tokens=6000)
        self.assertEqual(code, 0)
        self.assertEqual(constructor.call_args.kwargs["n_ctx"], 8192)
        self.assertEqual(llm.create_chat_completion.call_args.kwargs["max_tokens"], 8192 - 6000 - 256)
        llm.tokenize.assert_called_once()

    def test_oversized_extended_input_never_generates_and_error_does_not_echo_private_data(self):
        code, _, llm, output, error = self.run_worker({
            "model": "fixture.gguf", "messages": [{"role": "user", "content": "private text"}],
            "max_tokens": 4096, "n_ctx": 8192,
        }, prompt_tokens=8100)
        self.assertEqual(code, 2)
        llm.create_chat_completion.assert_not_called()
        self.assertNotIn("private text", output + error)
        self.assertIn("ValueError", error)

    def test_busy_worker_cannot_start_a_second_native_model(self):
        lock = mock.Mock()
        lock.acquire.return_value = False
        with (mock.patch("luxai.gguf_backend._INFERENCE_LOCK", lock),
              mock.patch("luxai.gguf_backend.subprocess.run") as run):
            with self.assertRaisesRegex(GGUFWorkerError, "busy") as caught:
                IsolatedGGUF("fixture.gguf").create_chat_completion(messages=[])
        self.assertEqual(caught.exception.code, "busy")
        lock.acquire.assert_called_once_with(timeout=2)
        lock.release.assert_not_called()
        run.assert_not_called()

    def test_lock_is_released_even_when_native_worker_times_out(self):
        lock = mock.Mock()
        lock.acquire.return_value = True
        with (mock.patch("luxai.gguf_backend._INFERENCE_LOCK", lock),
              mock.patch("luxai.gguf_backend.subprocess.run", side_effect=subprocess.TimeoutExpired("fixture", 1))):
            with self.assertRaises(GGUFWorkerError):
                IsolatedGGUF("fixture.gguf").create_chat_completion(messages=[], n_ctx=8192)
        lock.release.assert_called_once_with()

    def test_local_context_truncation_is_explicit_and_clears_edit_permission(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "document.txt"
            path.write_text("Original text", encoding="utf-8")
            attachment = load_attachment(path)
        long_text = replace(attachment, text="x" * (MAX_LOCAL_CONTEXT_CHARS + 100))
        messages, allowed, warnings = attachment_messages(
            "Correct the document.", (long_text,), {}, "local", local=True)
        document = json.loads(messages[1]["content"])["attachments"][0]
        self.assertLessEqual(len(document["content"]), MAX_LOCAL_CONTEXT_CHARS)
        self.assertTrue(document["truncated"])
        self.assertFalse(document["can_propose_edit"])
        self.assertFalse(allowed)
        self.assertTrue(any("truncated" in item for item in warnings))
        # A byte budget also bounds non-Latin input without splitting UTF-8.
        unicode_text = replace(attachment, text="ș" * MAX_LOCAL_CONTEXT_CHARS)
        messages, allowed, _ = attachment_messages("Edit it.", (unicode_text,), {}, "local", local=True)
        document = json.loads(messages[1]["content"])["attachments"][0]
        self.assertLessEqual(len(document["content"].encode("utf-8")), MAX_LOCAL_CONTEXT_CHARS)
        self.assertFalse(allowed)

    def test_attachment_request_opts_into_budget_and_oversized_user_instruction_is_not_truncated(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "document.txt"
            path.write_text("Original text", encoding="utf-8")
            attachment = load_attachment(path)
            llm = mock.Mock()
            llm.create_chat_completion.return_value = {"choices": [{"message": {"content": '{"reply":"Read locally.","edits":[]}'}}]}
            loader = mock.Mock(return_value=llm)
            agent = SimpleNamespace(config={"response_language": "en"}, _load_llm=loader)
            result = respond_to_attachments(None, agent, "Read this file.", (attachment,))
            self.assertEqual(result.text, "Read locally.")
            self.assertEqual(llm.create_chat_completion.call_args.kwargs["n_ctx"], 8192)
            self.assertEqual(llm.create_chat_completion.call_args.kwargs["max_tokens"], 4096)
            loader.reset_mock()
            result = respond_to_attachments(None, agent, "a" * (MAX_LOCAL_REQUEST_CHARS + 1), (attachment,))
            loader.assert_not_called()
            self.assertFalse(result.edits)
            self.assertIn("Shorten", result.text)
            self.assertTrue(result.warnings)
            with self.assertRaisesRegex(ValueError, "Shorten"):
                attachment_messages("a" * (MAX_LOCAL_REQUEST_CHARS + 1), (attachment,), {}, "local", local=True)

    def test_busy_local_attachment_request_returns_clear_retry_without_edits(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "document.txt"
            path.write_text("Original text", encoding="utf-8")
            attachment = load_attachment(path)
            llm = mock.Mock()
            llm.create_chat_completion.side_effect = GGUFWorkerError("busy", code="busy")
            agent = SimpleNamespace(config={"response_language": "en"}, _load_llm=lambda: llm)
            result = respond_to_attachments(None, agent, "Correct this file.", (attachment,))
            self.assertFalse(result.edits)
            self.assertIn("previous request", result.text)
            self.assertIn("try again", result.text)
            self.assertEqual(path.read_text(), "Original text")


if __name__ == "__main__":
    unittest.main()
