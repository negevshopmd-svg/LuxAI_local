"""Optional Fish Audio speech using only its explicitly selected free model.

The voice URL identifies a voice; it is never fetched. Speech is sent only to
the fixed Fish API endpoint, with redirects disabled. Raw little-endian PCM
is bounded and wrapped locally, so callers always receive a complete WAV.
No keys, text, audio or untrusted server error bodies are logged or saved here.
"""
from __future__ import annotations

import io
import http.client
import json
import math
import re
import time
import urllib.error
import urllib.request
import wave
from collections.abc import Callable
from urllib.parse import urlsplit


DEFAULT_FISH_VOICE = "4c3eaacc1a0545cdb0295bfddf3e3785"
FREE_MODEL = "s2.1-pro-free"
TTS_ENDPOINT = "https://api.fish.audio/v1/tts"
SAMPLE_RATE = 24_000
MAX_AUDIO_BYTES = SAMPLE_RATE * 2 * 120  # Two minutes of mono 16-bit PCM.
MAX_TEXT_UTF8_BYTES = 12_000
REQUEST_TIMEOUT_SECONDS = 20
TOTAL_TIMEOUT_SECONDS = 60
_READ_SIZE = 16_384
_VOICE_ID = re.compile(r"[0-9a-fA-F]{32}")
_VOICE_PATH = re.compile(r"/(?:[a-zA-Z]{2,3}(?:-[a-zA-Z]{2})?/)?m/([0-9a-fA-F]{32})/?")
_PCM_CONTENT_TYPES = frozenset({
    "audio/pcm", "audio/x-pcm", "audio/raw", "audio/x-raw",
    "application/octet-stream",
})
_ERROR_MESSAGES = {
    "missing_key": "Fish Audio API key is not configured.",
    "invalid_key": "Fish Audio API key format is invalid.",
    "voice": "Fish Audio voice ID or URL is invalid.",
    "request": "Fish Audio speech parameters are invalid.",
    "cancelled": "Fish Audio speech was cancelled.",
    "auth": "Fish Audio rejected the API key or voice access.",
    "rate_limit": "Fish Audio request limit was reached.",
    "payment": "Fish Audio did not accept the free model request.",
    "timeout": "Fish Audio speech request timed out.",
    "network": "Fish Audio could not be reached.",
    "response": "Fish Audio returned an invalid audio response.",
    "unavailable": "Fish Audio is temporarily unavailable.",
}


class FishTTSError(ValueError):
    """A closed diagnostic code; never include a request or response body."""

    def __init__(self, code: str):
        self.code = code if code in _ERROR_MESSAGES else "response"
        super().__init__(_ERROR_MESSAGES[self.code])


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # An authenticated POST must never be replayed at another destination.
        return None


def normalize_voice_id(value: str) -> str:
    """Accept a 32-hex ID or an official https://fish.audio/[locale/]m/ID URL."""
    if not isinstance(value, str) or len(value) > 500:
        raise FishTTSError("voice")
    value = value.strip()
    if _VOICE_ID.fullmatch(value):
        return value.lower()
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.hostname != "fish.audio"
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            raise FishTTSError("voice")
        matched = _VOICE_PATH.fullmatch(parsed.path)
        if matched is None:
            raise FishTTSError("voice")
    except (ValueError, TypeError, AttributeError):
        raise FishTTSError("voice") from None
    # Query/fragment sharing metadata is discarded, never followed or sent.
    return matched.group(1).lower()


def _check_cancelled(is_cancelled: Callable[[], bool] | None) -> None:
    if is_cancelled is not None and is_cancelled():
        raise FishTTSError("cancelled")


def _http_error_code(status: int) -> str:
    if status in (401, 403):
        return "auth"
    if status == 402:
        return "payment"
    if status == 429:
        return "rate_limit"
    if status >= 500:
        return "unavailable"
    return "response"


def _read_pcm(response, deadline: float, is_cancelled: Callable[[], bool] | None) -> bytes:
    if response.status != 200:
        raise FishTTSError(_http_error_code(response.status))
    content_type = str(response.headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
    if content_type not in _PCM_CONTENT_TYPES:
        raise FishTTSError("response")
    if str(response.headers.get("Content-Encoding", "identity")).strip().lower() != "identity":
        raise FishTTSError("response")
    advertised = response.headers.get("Content-Length")
    if advertised is not None:
        try:
            advertised = int(advertised)
        except (ValueError, TypeError, OverflowError):
            raise FishTTSError("response") from None
        if not 0 < advertised <= MAX_AUDIO_BYTES or advertised % 2:
            raise FishTTSError("response")
    audio = bytearray()
    # HTTPResponse.read1 returns available chunks instead of waiting to fill
    # the entire buffer, allowing cancellation/deadline checks while streaming.
    read = getattr(response, "read1", response.read)
    while True:
        _check_cancelled(is_cancelled)
        if time.monotonic() >= deadline:
            raise FishTTSError("timeout")
        chunk = read(min(_READ_SIZE, MAX_AUDIO_BYTES + 1 - len(audio)))
        if time.monotonic() >= deadline:
            raise FishTTSError("timeout")
        if not chunk:
            break
        audio.extend(chunk)
        if len(audio) > MAX_AUDIO_BYTES:
            raise FishTTSError("response")
    _check_cancelled(is_cancelled)
    if (not audio or len(audio) % 2
            or (advertised is not None and len(audio) != advertised)):
        raise FishTTSError("response")
    return bytes(audio)


def synthesize(text: str, key: str, voice_id: str = DEFAULT_FISH_VOICE, *,
               speed: float = 1.0, language: str | None = None,
               is_cancelled: Callable[[], bool] | None = None) -> bytes:
    """Generate bounded WAV audio with the free model, without retries.

    ``is_cancelled`` is checked before networking and between response reads.
    A blocked network operation has a socket timeout; callers must also check
    cancellation immediately before playback. There is no startup request,
    paid-model option or automatic fallback to a different model.
    """
    _check_cancelled(is_cancelled)
    if not isinstance(key, str) or not key.strip():
        raise FishTTSError("missing_key")
    key = key.strip()
    if len(key) > 2048 or any(not 33 <= ord(char) <= 126 for char in key):
        raise FishTTSError("invalid_key")
    voice_id = normalize_voice_id(voice_id)
    try:
        if (not isinstance(text, str) or not text.strip()
                or len(text.encode("utf-8")) > MAX_TEXT_UTF8_BYTES or "\0" in text):
            raise FishTTSError("request")
        speed = float(speed)
        if not math.isfinite(speed) or not 0.7 <= speed <= 1.4:
            raise FishTTSError("request")
        if language is not None and language not in ("ru", "ro", "en"):
            raise FishTTSError("request")
    except (ValueError, TypeError, OverflowError, UnicodeError):
        raise FishTTSError("request") from None
    body = {
        "text": text,
        "reference_id": voice_id,
        "format": "pcm",
        "sample_rate": SAMPLE_RATE,
        "prosody": {"speed": speed},
    }
    if language is not None:
        body["language"] = language
    request = urllib.request.Request(
        TTS_ENDPOINT,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept": "audio/pcm, application/octet-stream",
            "Accept-Encoding": "identity",
            # Missing/unknown model headers default to a PAID model upstream.
            "model": FREE_MODEL,
        },
        method="POST",
    )
    deadline = time.monotonic() + TOTAL_TIMEOUT_SECONDS
    try:
        _check_cancelled(is_cancelled)
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            audio = _read_pcm(response, deadline, is_cancelled)
    except FishTTSError:
        raise
    except urllib.error.HTTPError as error:
        code = _http_error_code(error.code)
        error.close()
        raise FishTTSError(code) from None
    except (TimeoutError,):
        raise FishTTSError("timeout") from None
    except urllib.error.URLError as error:
        code = "timeout" if isinstance(error.reason, TimeoutError) else "network"
        raise FishTTSError(code) from None
    except http.client.HTTPException:
        raise FishTTSError("response") from None
    except (OSError, ValueError, TypeError):
        raise FishTTSError("network") from None
    _check_cancelled(is_cancelled)
    with io.BytesIO() as output:
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(audio)
        return output.getvalue()
