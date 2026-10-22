"""No-network tests for the API-key verification button backend."""
import json
import unittest
import urllib.error
from unittest import mock

from luxai.api_verification import check_api_key
from luxai.online_agent import OnlinePlanner


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "online_provider": "deepseek",
            "online_model": "deepseek-flash",
            "online_timeout": 5,
        }

    def test_valid_new_key_checks_selected_provider(self):
        valid = {
            "choices": [{"message": {"content": json.dumps({
                "action": "reply", "target": "", "reply": "OK",
            })}}],
        }
        with mock.patch.object(OnlinePlanner, "_request", return_value=valid) as send:
            passed, message = check_api_key(self.settings, "fake-not-a-real-api-key")
        self.assertTrue(passed)
        self.assertIn("API работает", message)
        self.assertEqual(send.call_args.args[0], "deepseek")
        self.assertEqual(send.call_args.args[1], "deepseek-flash")
        self.assertEqual(send.call_args.args[2], "fake-not-a-real-api-key")

    def test_http_error_categories(self):
        expected = {
            401: "ключ", 402: "средств", 403: "доступа",
            404: "модель", 429: "лимит", 400: "формат",
        }
        for status, keyword in expected.items():
            with self.subTest(status=status):
                error = urllib.error.HTTPError(
                    "https://api.deepseek.com/chat/completions",
                    status, "Fake error", {}, None,
                )
                with mock.patch.object(OnlinePlanner, "_request", side_effect=error):
                    passed, message = check_api_key(self.settings, "fake-secret")
                self.assertFalse(passed)
                self.assertIn(keyword, message.lower())
                self.assertNotIn("fake-secret", message)

    def test_network_failure(self):
        error = urllib.error.URLError("fake network failure")
        with mock.patch.object(OnlinePlanner, "_request", side_effect=error):
            success, result = check_api_key(self.settings, "fake-secret")
        self.assertFalse(success)
        self.assertIn("подключения", result)
        self.assertNotIn("fake-secret", result)

    def test_empty_key_rejected_without_network_call(self):
        with mock.patch.object(OnlinePlanner, "_request") as call:
            passed, message = check_api_key(self.settings, "")
        self.assertFalse(passed)
        self.assertIn("не введён", message)
        call.assert_not_called()

    def test_invalid_model_or_custom_endpoint_rejected(self):
        settings = {
            "online_provider": "custom",
            "online_model": "example-model",
            "online_custom_url": "http://localhost/chat/completions",
        }
        with mock.patch.object(OnlinePlanner, "_request") as call:
            ok, message = check_api_key(settings, "fake-secret")
        self.assertFalse(ok)
        self.assertIn("HTTPS", message)
        call.assert_not_called()

    def test_successful_http_with_bad_json_is_not_marked_working(self):
        invalid = {"choices": [{"message": {"content": "hello world"}}]}
        with mock.patch.object(OnlinePlanner, "_request", return_value=invalid):
            ok, message = check_api_key(self.settings, "fake-secret")
        self.assertFalse(ok)
        self.assertIn("формату", message)


if __name__ == "__main__":
    unittest.main()
