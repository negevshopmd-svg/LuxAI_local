"""Provider routing, key isolation and safe endpoint tests (no real API calls)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from luxai.api_providers import (
    PROVIDERS, endpoint_for, model_for, validate_custom_url,
)
from luxai import secure_keys
from luxai.online_agent import OnlinePlanner


class ProviderTests(unittest.TestCase):
    def test_deepseek_endpoint_and_fast_model(self):
        self.assertEqual(
            endpoint_for("deepseek"), "https://api.deepseek.com/chat/completions"
        )
        self.assertEqual(model_for("deepseek"), "deepseek-flash")

    def test_catalog_endpoints_use_https(self):
        for provider in PROVIDERS:
            if provider != "custom":
                with self.subTest(provider=provider):
                    self.assertTrue(endpoint_for(provider).startswith("https://"))
                    self.assertTrue(model_for(provider))

    def test_custom_endpoints_cannot_use_http_localhost_or_credentials(self):
        invalid = (
            "http://example.com/v1/chat/completions",
            "https://localhost/v1/chat/completions",
            "https://127.0.0.1/v1/chat/completions",
            "https://x:y@example.com/v1/chat/completions",
            "https://example.com/v1/chat/completions?api_key=hello",
            "https://example.com/other",
            "https://192.168.1.2/v1/chat/completions",
        )
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_custom_url(url)
        self.assertEqual(
            validate_custom_url("https://example.com/v1/chat/completions"),
            "https://example.com/v1/chat/completions",
        )

    def test_keys_isolated_by_provider(self):
        # Simulate DPAPI in CI on Linux without ever handling real credentials.
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(secure_keys, "SECRET_DIR", Path(folder)), mock.patch.object(
                secure_keys, "_win_crypt", side_effect=lambda data, encrypt: data[::-1]
            ), mock.patch.dict(os.environ, {
                "OPENAI_API_KEY": "",
                "DEEPSEEK_API_KEY": "",
            }):
                secure_keys.store_api_key("fake-openai-key", "openai")
                secure_keys.store_api_key("fake-deepseek-key", "deepseek")
                self.assertEqual(secure_keys.get_api_key("openai"), "fake-openai-key")
                self.assertEqual(secure_keys.get_api_key("deepseek"), "fake-deepseek-key")
                self.assertNotEqual(
                    secure_keys._secret_file("openai"), secure_keys._secret_file("deepseek")
                )
                secure_keys.clear_api_key("deepseek")
                self.assertFalse(secure_keys.has_api_key("deepseek"))
                self.assertTrue(secure_keys.has_api_key("openai"))

    def test_online_planner_uses_selected_deepseek_key(self):
        fake_reply = {"choices": [{"message": {"content": json.dumps({
            "action": "reply", "target": "", "reply": "Привет."
        })}}]}
        config = {
            "online_provider": "deepseek",
            "online_model": "deepseek-flash",
            "online_agent_enabled": True,
        }
        planner = OnlinePlanner(config)
        with mock.patch(
            "luxai.online_agent.get_api_key", return_value="fake-secret"
        ) as key, mock.patch.object(
            planner, "_request", return_value=fake_reply
        ) as request:
            self.assertEqual(planner.plan("Привет")["reply"], "Привет.")
        key.assert_any_call("deepseek")
        self.assertEqual(request.call_args.args[0], "deepseek")
        self.assertEqual(request.call_args.args[1], "deepseek-flash")

    def test_provider_switch_invalidates_cached_plans(self):
        planner = OnlinePlanner({"online_provider": "deepseek"})
        planner._cache[("deepseek", "hello")] = {"action": "reply", "target": "", "reply": "A"}
        planner.update_config({"online_provider": "groq"})
        self.assertFalse(planner._cache)

    def test_deepseek_request_has_bearer_auth_and_json_mode(self):
        planner = OnlinePlanner({"online_provider": "deepseek"})
        with mock.patch("luxai.online_agent.urllib.request.build_opener") as build:
            response = build.return_value.open.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = b'{"choices":[]}'
            planner._request(
                "deepseek", "deepseek-flash", "fake-private-key",
                [{"role": "system", "content": "JSON"}, {"role": "user", "content": "Hi"}], 5,
            )
            req = build.return_value.open.call_args.args[0]
            self.assertEqual(req.full_url, "https://api.deepseek.com/chat/completions")
            self.assertEqual(req.get_header("Authorization"), "Bearer fake-private-key")
            self.assertEqual(
                json.loads(req.data)["response_format"], {"type": "json_object"}
            )

    def test_anthropic_request_uses_native_api_headers(self):
        planner = OnlinePlanner({"online_provider": "anthropic"})
        with mock.patch("luxai.online_agent.urllib.request.build_opener") as build:
            response = build.return_value.open.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = b'{"content":[]}'
            planner._request(
                "anthropic", "claude-haiku-4-5", "fake-claude-key",
                [{"role": "system", "content": "JSON"}, {"role": "user", "content": "Hi"}], 5,
            )
            req = build.return_value.open.call_args.args[0]
            self.assertEqual(req.full_url, "https://api.anthropic.com/v1/messages")
            self.assertEqual(req.get_header("X-api-key"), "fake-claude-key")
            self.assertEqual(req.get_header("Anthropic-version"), "2023-06-01")
            payload = json.loads(req.data)
            self.assertEqual(payload["messages"], [{"role": "user", "content": "Hi"}])

    def test_no_key_means_no_request(self):
        planner = OnlinePlanner({"online_agent_enabled": True, "online_provider": "deepseek"})
        with mock.patch("luxai.online_agent.get_api_key", return_value=""), mock.patch.object(
            planner, "_request"
        ) as request:
            self.assertFalse(planner.enabled())
            self.assertIsNone(planner.plan("Привет"))
            request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
