"""Regression tests for missing local GGUF backend and response languages."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.modules.setdefault(
    "luxai.screen",
    types.SimpleNamespace(
        capture_screen=lambda: None,
        read_screen_text=lambda *args, **kwargs: "",
    ),
)

from luxai.agent import LocalAgent
from luxai.fast_intents import strip_wake_name
from luxai.intent_routing import routine_reply
from luxai.online_agent import OnlinePlanner
from luxai.response_language import reply_language


class VoiceLanguageAndOptionalLLMTests(unittest.TestCase):
    def test_hello_jarvis_without_gguf_stays_english(self):
        agent = LocalAgent({"language": "en"})
        with mock.patch.object(agent, "_load_llm", side_effect=AssertionError("No GGUF needed")):
            self.assertEqual(agent.handle_chat("Hello, Jarvis."), "Hello. I'm listening.")
            self.assertEqual(agent.handle_chat("Jarvis, hello."), "Hello. I'm listening.")

    def test_routine_replies_with_jarvis_after_greeting(self):
        self.assertEqual(strip_wake_name("Hello, Jarvis."), "Hello")
        self.assertEqual(routine_reply("Hello, Jarvis.", "en"), "Hello. I'm listening.")
        self.assertEqual(routine_reply("Salut, Jarvis!", "ro"), "Salut. Te ascult.")
        self.assertEqual(routine_reply("Привет, Джарвис!", "ru"), "Привет. Слушаю.")

    def test_no_llama_cpp_when_path_exists_is_handled_in_each_language(self):
        with tempfile.TemporaryDirectory() as root:
            model = Path(root) / "fake.gguf"
            # Valid-looking local file: import availability is checked after
            # GGUF signature/incomplete-file detection.
            model.write_bytes(b"GGUF" + b"\x00" * 1_048_576)
            for code, expected in (
                ("ru", "llama-cpp-python"),
                ("en", "llama-cpp-python"),
                ("ro", "llama-cpp-python"),
            ):
                with self.subTest(code=code), mock.patch.dict(sys.modules, {"llama_cpp": None}):
                    agent = LocalAgent({"llm_model_path": str(model), "language": code})
                    reply = agent.handle_chat("Tell me a story")
                    self.assertIn(expected, reply)
                    self.assertNotIn("No module named", reply)
                    self.assertEqual(agent._llm_error, "missing_llama_cpp")

    def test_explicit_output_language_overrides_microphone_and_ui(self):
        self.assertEqual(reply_language({
            "language": "ru", "ui_language": "ro", "response_language": "en",
        }, "Привет"), "en")
        self.assertEqual(reply_language({
            "language": "en", "ui_language": "ro", "response_language": "auto",
        }, "Привет"), "en")
        self.assertEqual(reply_language({
            "language": "auto", "ui_language": "ro", "response_language": "auto",
        }, "Hello, Jarvis."), "en")
        self.assertEqual(reply_language({
            "language": "auto", "ui_language": "en", "response_language": "auto",
        }, "Salut"), "ro")

    def test_online_prompt_uses_output_language(self):
        for code, phrase in (("en", "hello"), ("ro", "salut"), ("ru", "привет")):
            with self.subTest(code=code):
                planner = OnlinePlanner({
                    "online_provider": "openai", "online_model": "gpt-4.1-nano",
                    "online_agent_enabled": True, "language": "ru",
                    "response_language": code,
                })
                with (
                    mock.patch.object(planner, "enabled", return_value=True),
                    mock.patch("luxai.online_agent.get_api_key", return_value="test-key"),
                    mock.patch.object(planner, "_request", return_value={}) as request,
                    mock.patch.object(planner, "_extract_text", return_value='{"action":"reply","target":"","reply":"Hi"}'),
                ):
                    proposal = planner.plan(phrase)
                self.assertEqual(proposal["action"], "reply")
                messages = request.call_args.args[3]
                marker = {"en": "in English", "ro": "in Romanian", "ru": "in Russian"}[code]
                self.assertIn(marker, messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
