"""Exercise transport retries and verification through actual request building."""
import io
import json
import unittest
import urllib.error
from unittest import mock

from luxai.api_verification import check_api_key_detailed
from luxai.cloud_http import read_json_response, request_timeout
from luxai.gemini_models import list_gemini_models
from luxai.online_agent import OnlinePlanner


class CloudTransportTests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "online_provider": "openai", "online_model": "gpt-4.1-nano",
            "online_agent_enabled": True, "online_timeout": 60,
        }
        self.reply = {"choices": [{"message": {"content": json.dumps({
            "action": "reply", "target": "", "reply": "OK",
        })}}]}

    def response(self, value=None):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = json.dumps(self.reply if value is None else value).encode()
        return response

    def error(self, status, headers=None):
        return urllib.error.HTTPError(
            "https://api.openai.com/v1/chat/completions", status,
            "Upstream returned a failure", headers or {}, io.BytesIO(b"untrusted body"),
        )

    def test_verification_recovers_from_503_with_same_key_url_model_and_body(self):
        with mock.patch("luxai.online_agent.urllib.request.build_opener") as build, mock.patch(
            "luxai.cloud_http.time.sleep",
        ) as pause:
            build.return_value.open.side_effect = [self.error(503), self.response()]
            passed, message, model = check_api_key_detailed(self.settings, "fake-secret")
            self.assertTrue(passed, message)
            self.assertEqual(model, "gpt-4.1-nano")
            calls = build.return_value.open.call_args_list
            self.assertEqual(len(calls), 2)
            self.assertIs(calls[0].args[0], calls[1].args[0])
            request = calls[0].args[0]
            self.assertEqual(request.full_url, "https://api.openai.com/v1/chat/completions")
            self.assertEqual(request.get_header("Authorization"), "Bearer fake-secret")
            self.assertEqual(json.loads(request.data)["model"], "gpt-4.1-nano")
            self.assertGreater(calls[0].kwargs["timeout"], 50)
            pause.assert_called_once_with(0.4)

    def test_persistent_503_stops_after_one_retry_and_keeps_safe_diagnostic(self):
        with mock.patch("luxai.online_agent.urllib.request.build_opener") as build, mock.patch(
            "luxai.cloud_http.time.sleep",
        ):
            build.return_value.open.side_effect = [self.error(503), self.error(503)]
            passed, message, model = check_api_key_detailed(self.settings, "fake-secret")
            self.assertFalse(passed)
            self.assertIsNone(model)
            self.assertEqual(build.return_value.open.call_count, 2)
            self.assertIn("503", message)
            self.assertIn("временно", message)
            self.assertIn("не означает", message)
            self.assertNotIn("fake-secret", message)
            self.assertNotIn("untrusted body", message)

    def test_auth_quota_model_redirect_and_timeout_errors_are_not_retried(self):
        for failure in [*(self.error(n) for n in (301, 400, 401, 402, 403, 404, 429)),
                        TimeoutError("server may already have accepted request")]:
            with self.subTest(failure=type(failure).__name__, status=getattr(failure, "code", None)):
                opener = mock.Mock()
                opener.open.side_effect = failure
                with mock.patch("luxai.cloud_http.time.sleep") as pause:
                    with self.assertRaises(type(failure)):
                        read_json_response(opener, object(), 60)
                self.assertEqual(opener.open.call_count, 1)
                pause.assert_not_called()

    def test_retry_after_is_obeyed_and_second_timeout_uses_remaining_budget(self):
        opener = mock.Mock()
        opener.open.side_effect = [self.error(503, {"Retry-After": "2"}), self.response({})]
        with mock.patch("luxai.cloud_http.time.monotonic", side_effect=[0, 0, 1, 3]), mock.patch(
            "luxai.cloud_http.time.sleep",
        ) as pause:
            self.assertEqual(read_json_response(opener, object(), 5), {})
        pause.assert_called_once_with(2)
        self.assertEqual([c.kwargs["timeout"] for c in opener.open.call_args_list], [5, 2])

    def test_long_retry_after_or_exhausted_time_budget_returns_without_retry(self):
        for timeout, headers in ((60, {"Retry-After": "60"}), (0.5, {})):
            opener = mock.Mock()
            opener.open.side_effect = self.error(503, headers)
            with self.subTest(timeout=timeout), mock.patch("luxai.cloud_http.time.sleep") as pause:
                with self.assertRaises(urllib.error.HTTPError):
                    read_json_response(opener, object(), timeout)
                self.assertEqual(opener.open.call_count, 1)
                pause.assert_not_called()

    def test_gemini_discovery_recovers_from_gateway_error(self):
        with mock.patch("luxai.gemini_models.urllib.request.build_opener") as build, mock.patch(
            "luxai.cloud_http.time.sleep",
        ):
            build.return_value.open.side_effect = [self.error(502), self.response({
                "data": [{"id": "gemini-2.5-flash"}],
            })]
            self.assertEqual(list_gemini_models("fake-gemini-key"), ["gemini-2.5-flash"])
            self.assertEqual(build.return_value.open.call_count, 2)
            self.assertIs(build.return_value.open.call_args_list[0].args[0],
                          build.return_value.open.call_args_list[1].args[0])

    def test_gemini_discovery_honors_configured_timeout_instead_of_hidden_ten_second_cap(self):
        with mock.patch("luxai.gemini_models.urllib.request.build_opener") as build:
            build.return_value.open.return_value = self.response({"data": [{"id": "gemini-2.5-flash"}]})
            self.assertEqual(list_gemini_models("fake-gemini-key", timeout=60), ["gemini-2.5-flash"])
            self.assertGreater(build.return_value.open.call_args.kwargs["timeout"], 50)

    def test_invalid_or_oversized_success_response_is_not_retried(self):
        for body in (b"not JSON", b"x" * 17):
            opener = mock.Mock()
            response = self.response({})
            response.read.return_value = body
            opener.open.return_value = response
            with self.subTest(body=body), self.assertRaises(ValueError):
                read_json_response(opener, object(), 5, limit=16)
            self.assertEqual(opener.open.call_count, 1)

    def test_timeout_normalizes_legacy_invalid_and_user_preferences(self):
        for value, expected in ((5, 60), (35, 35), (120, 120), (500, 120), (None, 60), ("oops", 60)):
            with self.subTest(value=value):
                self.assertEqual(request_timeout({"online_timeout": value}), expected)

    def test_gemini_models_outage_can_verify_only_the_configured_model_by_generation(self):
        settings = dict(self.settings, online_provider="gemini", online_model="gemini-2.5-flash")
        with mock.patch("luxai.online_agent.urllib.request.build_opener") as build, mock.patch(
            "luxai.cloud_http.time.sleep",
        ):
            build.return_value.open.side_effect = [self.error(503), self.error(503), self.response()]
            passed, message, model = check_api_key_detailed(settings, "fake-gemini-key")
            self.assertTrue(passed, message)
            self.assertEqual(model, "gemini-2.5-flash")
            requests = [call.args[0] for call in build.return_value.open.call_args_list]
            self.assertEqual([request.method for request in requests], ["GET", "GET", "POST"])
            self.assertTrue(all(request.full_url.startswith("https://generativelanguage.googleapis.com/")
                                for request in requests))
            self.assertEqual(json.loads(requests[-1].data)["model"], "gemini-2.5-flash")

    def test_gemini_models_outage_never_invents_an_unknown_model_or_claims_no_generation_success(self):
        settings = dict(self.settings, online_provider="gemini")
        for configured, chat_response in (("Antigravity", self.reply),
                                          ("gemini-2.5-flash", {"choices": []})):
            with self.subTest(configured=configured), mock.patch(
                "luxai.api_verification.list_gemini_models", side_effect=self.error(503),
            ), mock.patch.object(OnlinePlanner, "_request", return_value=chat_response) as send:
                passed, message, model = check_api_key_detailed(
                    dict(settings, online_model=configured), "fake-gemini-key",
                )
                self.assertFalse(passed)
                self.assertIsNone(model)
                self.assertEqual(send.call_count, int(configured.startswith("gemini-")))

    def test_reset_connection_state_clears_stale_credential_error_cache_and_cooldown(self):
        planner = OnlinePlanner(self.settings)
        planner._blocked_until = float("inf")
        planner.last_error = "Old authentication failure"
        planner._cooldown_reason = "Old credential quota"
        planner._cache["old-user"] = {"action": "open_app", "target": "discord"}
        planner.reset_connection_state()
        self.assertEqual(planner._blocked_until, 0)
        self.assertEqual(planner.last_error, "")
        self.assertEqual(planner._cooldown_reason, "")
        self.assertFalse(planner._cache)
        with mock.patch("luxai.online_agent.get_api_key", return_value="fake-new-key"), mock.patch.object(
            planner, "_request", return_value=self.reply,
        ) as send:
            self.assertEqual(planner.plan("Hello")["reply"], "OK")
            send.assert_called_once()

    def test_plan_cooldown_preserves_503_reason_without_calling_it_invalid_key(self):
        planner = OnlinePlanner(self.settings)
        with mock.patch("luxai.online_agent.get_api_key", return_value="fake-secret"), mock.patch.object(
            planner, "_request", side_effect=self.error(503),
        ) as request:
            self.assertIsNone(planner.plan("Hello"))
            self.assertIn("503", planner.last_error)
            self.assertIn("не означает", planner.last_error)
            self.assertIsNone(planner.plan("Another question"))
            self.assertIn("503", planner.last_error)
            self.assertEqual(request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
