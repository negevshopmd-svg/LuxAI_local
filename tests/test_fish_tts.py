"""Fish TTS request policy and untrusted audio handling, without network access."""
from __future__ import annotations

import http.client
import io
import json
import unittest
import urllib.error
from unittest import mock
import wave

from luxai import fish_tts


class _PCMResponse:
    def __init__(self, body=b"\0\0" * 48, *, content_type="audio/pcm", status=200,
                 headers=None, on_read=None):
        self.status = status
        self.headers = {"Content-Type": content_type, **(headers or {})}
        self.stream = io.BytesIO(body)
        self.on_read = on_read
        self.closed = False
        self.read_count = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def read(self, size):
        self.read_count += 1
        if self.on_read is not None:
            self.on_read()
        return self.stream.read(size)

    read1 = read


class FishTTSTests(unittest.TestCase):
    def setUp(self):
        self.opener = mock.Mock()
        self.response = _PCMResponse()
        self.opener.open.return_value = self.response
        self.build = mock.patch("luxai.fish_tts.urllib.request.build_opener", return_value=self.opener).start()
        self.addCleanup(mock.patch.stopall)

    def generate(self, **kwargs):
        return fish_tts.synthesize("Сэр, всё готово.", "fake-private-key", **kwargs)

    def assert_error(self, code, **kwargs):
        with self.assertRaises(fish_tts.FishTTSError) as caught:
            self.generate(**kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn("fake-private-key", str(caught.exception))
        self.assertNotIn("private server body", str(caught.exception))
        return caught.exception

    def test_explicit_free_model_fixed_endpoint_voice_and_pcm_are_sent(self):
        audio = self.generate(language="ru", speed=1.2)
        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.fish.audio/v1/tts")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer fake-private-key")
        self.assertEqual(request.get_header("Model"), "s2.1-pro-free")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(request.get_header("Accept-encoding"), "identity")
        self.assertEqual(json.loads(request.data), {
            "text": "Сэр, всё готово.",
            "reference_id": "4c3eaacc1a0545cdb0295bfddf3e3785",
            "format": "pcm", "sample_rate": 24_000,
            "prosody": {"speed": 1.2}, "language": "ru",
        })
        self.assertEqual(self.opener.open.call_count, 1)
        self.assertEqual(self.opener.open.call_args.kwargs["timeout"], fish_tts.REQUEST_TIMEOUT_SECONDS)
        with wave.open(io.BytesIO(audio), "rb") as output:
            self.assertEqual((output.getnchannels(), output.getsampwidth(), output.getframerate()), (1, 2, 24_000))
            self.assertEqual(output.getnframes(), 48)
            self.assertEqual(output.readframes(48), b"\0\0" * 48)
        self.assertTrue(self.response.closed)

    def test_custom_voice_url_is_identifier_only_and_not_another_destination(self):
        selected = "ABCDEF0123456789ABCDEF0123456789"
        self.generate(voice_id=f"https://fish.audio/ru/m/{selected}/?shared=yes#preview")
        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, fish_tts.TTS_ENDPOINT)
        self.assertEqual(json.loads(request.data)["reference_id"], selected.lower())
        self.assertEqual(self.opener.open.call_count, 1)

    def test_supported_ids_and_official_locale_urls_normalize(self):
        selected = fish_tts.DEFAULT_FISH_VOICE.upper()
        for value in (selected, f"https://fish.audio/m/{selected}",
                      f"https://fish.audio/ru/m/{selected}/",
                      f"https://fish.audio/zh-CN/m/{selected}",
                      f"https://fish.audio:443/en/m/{selected}"):
            with self.subTest(value=value):
                self.assertEqual(fish_tts.normalize_voice_id(value), selected.lower())

    def test_other_hosts_userinfo_protocols_and_malformed_ids_are_rejected(self):
        selected = fish_tts.DEFAULT_FISH_VOICE
        invalid = ("", None, "1234", selected + "f", "x" * 501,
                   f"http://fish.audio/m/{selected}", f"https://fish.audio.evil/m/{selected}",
                   f"https://fish.audio@evil.example/m/{selected}",
                   f"https://other:secret@fish.audio/m/{selected}",
                   f"https://fish.audio:444/m/{selected}",
                   f"https://fish.audio:bad/m/{selected}",
                   f"https://fish.audio/m/{selected}/extra")
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                fish_tts.normalize_voice_id(value)
        self.build.assert_not_called()

    def test_absent_or_invalid_key_never_opens_a_request(self):
        for key, code in (("", "missing_key"), (None, "missing_key"),
                          ("bad\nheader", "invalid_key"), ("contains space", "invalid_key"),
                          ("é", "invalid_key"), ("k" * 2049, "invalid_key")):
            with self.subTest(code=code, length=len(key or "")), self.assertRaises(fish_tts.FishTTSError) as caught:
                fish_tts.synthesize("Hello", key)
            self.assertEqual(caught.exception.code, code)
        self.build.assert_not_called()

    def test_bad_text_speed_or_language_never_opens_a_request(self):
        parameters = ({"text": ""}, {"text": "\0"}, {"text": None},
                      {"text": "é" * (fish_tts.MAX_TEXT_UTF8_BYTES // 2 + 1)},
                      {"text": "\ud800"}, {"speed": float("nan")},
                      {"speed": float("inf")}, {"speed": 0.6}, {"speed": 1.5},
                      {"speed": "bad"}, {"language": "../ru"})
        for parameters in parameters:
            arguments = {"text": "Hello", "key": "fake-key", **parameters}
            with self.subTest(parameters=parameters), self.assertRaises(fish_tts.FishTTSError) as caught:
                fish_tts.synthesize(**arguments)
            self.assertEqual(caught.exception.code, "request")
        self.build.assert_not_called()

    def test_http_errors_are_sanitized_closed_and_never_retried_or_switched_to_paid(self):
        for status, code in ((301, "response"), (307, "response"), (308, "response"),
                             (400, "response"), (401, "auth"), (402, "payment"),
                             (403, "auth"), (404, "response"), (429, "rate_limit"),
                             (500, "unavailable"), (503, "unavailable")):
            body = io.BytesIO(b"private server body fake-private-key")
            failure = urllib.error.HTTPError(fish_tts.TTS_ENDPOINT, status,
                                             "private server body", {}, body)
            self.opener.open.reset_mock()
            self.opener.open.side_effect = failure
            with self.subTest(status=status):
                error = self.assert_error(code)
                self.assertTrue(error.__suppress_context__)
                self.assertTrue(body.closed)
                self.assertEqual(self.opener.open.call_count, 1)
                request = self.opener.open.call_args.args[0]
                self.assertEqual(request.get_header("Model"), "s2.1-pro-free")

    def test_redirect_handler_refuses_to_replay_authenticated_post(self):
        self.generate()
        handler = self.build.call_args.args[0]
        request = self.opener.open.call_args.args[0]
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                self.assertIsNone(handler.redirect_request(
                    request, None, status, "Moved", {}, "https://different.example/tts"))

    def test_network_failures_are_safe_and_not_retried(self):
        for failure, code in ((TimeoutError("private server body"), "timeout"),
                              (urllib.error.URLError(TimeoutError("private server body")), "timeout"),
                              (urllib.error.URLError("private server body"), "network"),
                              (OSError("private server body"), "network"),
                              (http.client.IncompleteRead(b"private server body"), "response")):
            self.opener.open.reset_mock()
            self.opener.open.side_effect = failure
            with self.subTest(failure=type(failure).__name__):
                self.assert_error(code)
                self.assertEqual(self.opener.open.call_count, 1)

    def test_success_status_must_contain_pcm_and_identity_encoding(self):
        for content_type in ("application/json", "text/plain", "text/html", "audio/wav", ""):
            self.response = _PCMResponse(content_type=content_type)
            self.opener.open.return_value = self.response
            with self.subTest(content_type=content_type):
                self.assert_error("response")
                self.assertEqual(self.response.read_count, 0)
                self.assertTrue(self.response.closed)
        self.response = _PCMResponse(headers={"Content-Encoding": "gzip"})
        self.opener.open.return_value = self.response
        self.assert_error("response")
        self.assertEqual(self.response.read_count, 0)

    def test_missing_language_is_not_sent_and_octet_stream_is_supported(self):
        self.opener.open.return_value = _PCMResponse(content_type="application/octet-stream; charset=binary")
        audio = self.generate()
        self.assertTrue(audio.startswith(b"RIFF"))
        self.assertNotIn("language", json.loads(self.opener.open.call_args.args[0].data))

    def test_empty_odd_or_truncated_audio_is_rejected_and_response_closed(self):
        for body, headers in ((b"", {}), (b"\0" * 3, {}),
                              (b"\0" * 8, {"Content-Length": "10"}),
                              (b"\0" * 8, {"Content-Length": "6"})):
            self.response = _PCMResponse(body, headers=headers)
            self.opener.open.return_value = self.response
            with self.subTest(size=len(body), headers=headers):
                self.assert_error("response")
                self.assertTrue(self.response.closed)

    def test_oversize_or_bad_advertised_length_is_rejected_before_reading(self):
        for length in ("0", "-2", "odd", "3", str(fish_tts.MAX_AUDIO_BYTES + 2)):
            self.response = _PCMResponse(headers={"Content-Length": length})
            self.opener.open.return_value = self.response
            with self.subTest(length=length):
                self.assert_error("response")
                self.assertEqual(self.response.read_count, 0)

    def test_chunked_audio_enforces_bound_even_without_content_length(self):
        self.response = _PCMResponse(b"\0" * 18)
        self.opener.open.return_value = self.response
        with mock.patch.object(fish_tts, "MAX_AUDIO_BYTES", 16):
            self.assert_error("response")
        self.assertTrue(self.response.closed)

    def test_valid_content_length_is_accepted(self):
        self.opener.open.return_value = _PCMResponse(headers={"Content-Length": "96"})
        self.assertTrue(self.generate().startswith(b"RIFF"))

    def test_cancellation_before_request_has_no_network_side_effect(self):
        self.assert_error("cancelled", is_cancelled=lambda: True)
        self.build.assert_not_called()

    def test_cancellation_while_reading_discards_audio_and_closes_response(self):
        cancelled = False

        def stop():
            nonlocal cancelled
            cancelled = True

        self.response = _PCMResponse(on_read=stop)
        self.opener.open.return_value = self.response
        self.assert_error("cancelled", is_cancelled=lambda: cancelled)
        self.assertEqual(self.response.read_count, 1)
        self.assertTrue(self.response.closed)

    def test_total_time_budget_is_checked_while_streaming_and_at_end_of_read(self):
        for ticks in ([0, 61], [0, 0, 61]):
            self.response = _PCMResponse()
            self.opener.open.return_value = self.response
            with self.subTest(ticks=ticks), mock.patch("luxai.fish_tts.time.monotonic", side_effect=ticks):
                self.assert_error("timeout")
            self.assertTrue(self.response.closed)

    def test_unknown_error_code_does_not_expose_untrusted_string(self):
        error = fish_tts.FishTTSError("private server body fake-private-key")
        self.assertEqual(error.code, "response")
        self.assertNotIn("private server body", str(error))


if __name__ == "__main__":
    unittest.main()
