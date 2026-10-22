"""Gemini auth and model selection tests, without a real API key or network."""
import json
import unittest
import urllib.error
from unittest import mock

from luxai.api_verification import check_api_key_detailed
from luxai.gemini_models import (
    MODELS_ENDPOINT, choose_gemini_model, list_gemini_models, parse_model_ids,
)
from luxai.online_agent import OnlinePlanner


class GeminiModelsTests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "online_provider": "gemini",
            "online_model": "Antigravity",
            "online_timeout": 5,
            # This stale custom endpoint must never affect the Gemini URL.
            "online_custom_url": "https://api.orcarouter.ai/v1/chat/completions",
        }

    def test_gemini_model_parser_excludes_non_chat_agents(self):
        data = {"data": [
            {"id": "Antigravity"},
            {"id": "gemini-3.8-flash"},
            {"id": "models/gemini-3.5-flash-lite"},
            {"id": "gemini-3.8-live"},
            {"id": "gemini-3.8-flash-tts"},
            {"id": "gemini-embedding-2"},
            {"id": "gemini-nano-banana-2"},
        ]}
        result = parse_model_ids(data)
        self.assertEqual(
            result,
            ["gemini-3.5-flash-lite", "gemini-3.8-flash"],
        )
        self.assertEqual(
            choose_gemini_model(result, "Antigravity"),
            "gemini-3.5-flash-lite",
        )

    def test_get_models_uses_google_host_with_bearer_auth_only(self):
        with mock.patch("luxai.gemini_models.urllib.request.build_opener") as opener:
            resp = opener.return_value.open.return_value.__enter__.return_value
            resp.status = 200
            resp.read.return_value = json.dumps({
                "data": [{"id": "gemini-3.5-flash-lite"}],
            }).encode("utf-8")
            result = list_gemini_models("fake-gemini-key", timeout=5)
            self.assertEqual(result, ["gemini-3.5-flash-lite"])
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, MODELS_ENDPOINT)
            self.assertNotIn("fake-gemini-key", request.full_url)
            self.assertEqual(
                request.get_header("Authorization"), "Bearer fake-gemini-key",
            )

    def test_antigravity_is_replaced_only_after_successful_generation(self):
        response = {"choices": [{"message": {"content": json.dumps({
            "action": "reply", "target": "", "reply": "OK",
        })}}]}
        with mock.patch(
            "luxai.api_verification.list_gemini_models",
            return_value=["gemini-3.5-flash-lite", "gemini-3.8-flash"],
        ), mock.patch.object(
            OnlinePlanner, "_request", return_value=response,
        ) as call:
            passed, message, selected = check_api_key_detailed(
                self.settings, "fake-gemini-key",
            )
        self.assertTrue(passed)
        self.assertEqual(selected, "gemini-3.5-flash-lite")
        self.assertIn("Antigravity", message)
        self.assertEqual(call.call_args.args[0], "gemini")
        self.assertEqual(call.call_args.args[1], "gemini-3.5-flash-lite")
        self.assertEqual(call.call_args.args[2], "fake-gemini-key")

    def test_gemini_invalid_key_fails_before_chat_call(self):
        err = urllib.error.HTTPError(
            MODELS_ENDPOINT, 401, "invalid", {}, None,
        )
        with mock.patch(
            "luxai.api_verification.list_gemini_models", side_effect=err,
        ), mock.patch.object(OnlinePlanner, "_request") as call:
            passed, message, suggestion = check_api_key_detailed(
                self.settings, "fake-invalid-key",
            )
        self.assertFalse(passed)
        self.assertIn("401", message)
        self.assertIsNone(suggestion)
        call.assert_not_called()
        self.assertNotIn("fake-invalid-key", message)

    def test_gemini_unavailable_model_retries_one_other_accessible_model(self):
        invalid = urllib.error.HTTPError(
            MODELS_ENDPOINT, 404, "model unavailable", {}, None,
        )
        response = {"choices": [{"message": {"content": json.dumps({
            "action": "reply", "target": "", "reply": "OK",
        })}}]}
        settings = dict(self.settings, online_model="gemini-3.8-flash")
        with mock.patch(
            "luxai.api_verification.list_gemini_models",
            return_value=["gemini-3.8-flash", "gemini-3.5-flash-lite"],
        ), mock.patch.object(
            OnlinePlanner, "_request", side_effect=[invalid, response],
        ) as call:
            ok, msg, selected = check_api_key_detailed(settings, "fake-gemini-key")
        self.assertTrue(ok)
        self.assertEqual(selected, "gemini-3.5-flash-lite")
        self.assertEqual(call.call_count, 2)
        self.assertIn("модель", msg.lower())

    def test_gemini_key_does_not_run_any_raw_shell_commands(self):
        payload = {"action": "open_app", "target": "cmd", "reply": ""}
        self.assertIsNone(OnlinePlanner._validate(payload))


if __name__ == "__main__":
    unittest.main()
