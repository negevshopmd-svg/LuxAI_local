"""Named AI API providers and safe OpenAI-compatible endpoint configuration.

Provider selection is explicit: API keys are not interchangeable and their
prefixes alone cannot reliably identify the service. Never auto-send a key
to a guessed endpoint.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

PROVIDERS = {
    "deepseek": {
        "label": "DeepSeek",
        "url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-flash",
        "api_keys": "https://platform.deepseek.com/api_keys",
        "json_mode": True,
    },
    "openai": {
        "label": "OpenAI",
        "url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4.1-nano",
        "api_keys": "https://platform.openai.com/api-keys",
        "json_mode": True,
    },
    "orcarouter": {
        "label": "OrcaRouter (orcarouter.ai)",
        "url": "https://api.orcarouter.ai/v1/chat/completions",
        "model": "orcarouter/auto",
        "api_keys": "https://www.orcarouter.ai/console/get-started",
        "json_mode": False,
    },
    "openrouter": {
        "label": "OpenRouter",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "model": "openai/gpt-4o-mini",
        "api_keys": "https://openrouter.ai/settings/keys",
        "json_mode": False,
    },
    "groq": {
        "label": "Groq",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "llama-3.1-8b-instant",
        "api_keys": "https://console.groq.com/keys",
        "json_mode": False,
    },
    "gemini": {
        "label": "Google Gemini",
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "model": "gemini-2.5-flash",
        "api_keys": "https://aistudio.google.com/api-keys",
        "json_mode": False,
    },
    "mistral": {
        "label": "Mistral AI",
        "url": "https://api.mistral.ai/v1/chat/completions",
        "model": "mistral-small-latest",
        "api_keys": "https://console.mistral.ai/api-keys/",
        "json_mode": False,
    },
    "together": {
        "label": "Together AI",
        "url": "https://api.together.xyz/v1/chat/completions",
        "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "api_keys": "https://api.together.ai/settings/api-keys",
        "json_mode": False,
    },
    "fireworks": {
        "label": "Fireworks AI",
        "url": "https://api.fireworks.ai/inference/v1/chat/completions",
        "model": "accounts/fireworks/models/llama-v3p3-70b-instruct",
        "api_keys": "https://fireworks.ai/account/api-keys",
        "json_mode": False,
    },
    "xai": {
        "label": "xAI / Grok",
        "url": "https://api.x.ai/v1/chat/completions",
        "model": "grok-4-fast-non-reasoning",
        "api_keys": "https://console.x.ai",
        "json_mode": False,
    },
    "anthropic": {
        "label": "Anthropic / Claude",
        "url": "https://api.anthropic.com/v1/messages",
        "model": "claude-haiku-4-5",
        "api_keys": "https://console.anthropic.com/settings/keys",
        "json_mode": False,
    },
    "custom": {
        "label": "Другой OpenAI-совместимый HTTPS API",
        "url": "",
        "model": "",
        "api_keys": "",
        "json_mode": False,
    },
}

ENV_VARS = {
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "orcarouter": "ORCAROUTER_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "together": "TOGETHER_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "xai": "XAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "custom": "JARVIS_CUSTOM_API_KEY",
}


def provider_config(provider: str) -> dict:
    if not isinstance(provider, str) or provider not in PROVIDERS:
        raise ValueError("Unknown API provider")
    return PROVIDERS[provider]


def validate_model(model: str) -> str:
    """Allow standard vendor model identifiers, never blank/control characters."""
    if not isinstance(model, str):
        raise ValueError("Invalid model identifier")
    model = model.strip()
    if not (1 <= len(model) <= 140) or not re.fullmatch(r"[A-Za-z0-9_./:+@-]+", model):
        raise ValueError("Invalid model identifier")
    return model


def validate_custom_url(url: str) -> str:
    """Only explicitly configured HTTPS chat-completions destinations are allowed.

    Reject localhost, raw/private IPs, userinfo, query strings, and redirects.
    Never silently send a key to a substituted third-party endpoint.
    """
    if not isinstance(url, str) or len(url) > 500:
        raise ValueError("Invalid API URL")
    url = url.strip()
    try:
        p = urlsplit(url)
        hostname = p.hostname
        port = p.port
    except (ValueError, AttributeError):
        raise ValueError("Invalid API URL") from None
    if p.scheme != "https" or not hostname or not p.netloc or p.username or p.password:
        raise ValueError("A custom endpoint must be HTTPS with no embedded credentials")
    if p.query or p.fragment or port not in (None, 443):
        raise ValueError("Unexpected query, fragment or port in custom API URL")
    if not p.path.rstrip("/").endswith("/chat/completions"):
        raise ValueError("Enter the full /chat/completions endpoint")
    if (
        hostname.lower() in {"localhost", "localhost.localdomain"}
        or hostname.lower().endswith((".local", ".internal", ".localhost"))
        or not re.fullmatch(r"[A-Za-z0-9.-]+", hostname)
        or "." not in hostname
        or re.fullmatch(r"[0-9.]+", hostname)
    ):
        raise ValueError("A public HTTPS host name is required")
    return url.rstrip("/")


def endpoint_for(provider: str, custom_url: str = "") -> str:
    details = provider_config(provider)
    if provider == "custom":
        return validate_custom_url(custom_url)
    return details["url"]


def model_for(provider: str, configured_model: str | None = None) -> str:
    spec = provider_config(provider)
    model = configured_model if configured_model else spec["model"]
    return validate_model(model)
