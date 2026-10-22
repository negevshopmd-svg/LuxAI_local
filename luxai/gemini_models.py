"""Discover text-generation Gemini models actually visible to a supplied API key.

The Google Gemini OpenAI-compatible endpoint supports GET /models with
Authorization: Bearer <Gemini auth key>. This is safer than guessing a model ID
or mistaking the 'Antigravity' agent name for a generative model.

The request uses only a trusted Google HTTPS host, never puts a key in the URL,
and does not allow redirects carrying credentials.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

MODELS_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/models"

# Low latency first. Availability is determined from the user's own key.
PREFERRED_MODELS = (
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
)

# Exclude embeddings, TTS, image/video models and the Antigravity agent,
# which are not regular text chat-completion models.
EXCLUDED_SEGMENTS = (
    "image", "tts", "embedding", "transcribe",
    "live", "native-audio", "realtime", "computer-use",
)


def _model_id(value):
    if not isinstance(value, str):
        return ""
    value = value.removeprefix("models/").strip()
    if not re.fullmatch(r"gemini-[A-Za-z0-9_.-]{1,100}", value, flags=re.IGNORECASE):
        return ""
    if any(part in value.lower() for part in EXCLUDED_SEGMENTS):
        return ""
    return value


def parse_model_ids(data: dict) -> list[str]:
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise ValueError("Unexpected models response")
    found = set()
    for item in data["data"][:500]:
        if not isinstance(item, dict):
            continue
        model = _model_id(item.get("id"))
        if model:
            found.add(model)
    # Keep common usable text models at top, then all other exposed models.
    return sorted(found, key=lambda item: (item not in PREFERRED_MODELS, PREFERRED_MODELS.index(item) if item in PREFERRED_MODELS else 999, item))


def list_gemini_models(api_key: str, timeout: int = 5) -> list[str]:
    api_key = str(api_key or "").strip()
    if not api_key or len(api_key) > 2048 or any(ord(ch) < 33 or ord(ch) == 127 for ch in api_key):
        raise ValueError("Invalid API key")
    request = urllib.request.Request(
        MODELS_ENDPOINT,
        headers={
            "Authorization": "Bearer " + api_key,
            "User-Agent": "JarvisLocalAssistant/2.2",
            "Accept": "application/json",
        },
        method="GET",
    )

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise urllib.error.HTTPError(
                req.full_url, code, "Redirect blocked for Gemini key", headers, fp,
            )

    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=max(3, min(int(timeout), 10))) as response:
        if response.status != 200:
            raise ValueError("Gemini models endpoint returned an unexpected status")
        raw = response.read(512 * 1024)
    return parse_model_ids(json.loads(raw))


def choose_gemini_model(available: list[str], selected: str | None) -> str | None:
    if selected in available:
        return selected
    for preferred in PREFERRED_MODELS:
        if preferred in available:
            return preferred
    return available[0] if available else None
