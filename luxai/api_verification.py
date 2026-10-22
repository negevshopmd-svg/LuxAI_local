"""Check the selected provider's API key and model without saving credentials.

A tiny real inference request verifies that the supplied key can authenticate,
the chosen model is accessible and the chat-completions endpoint responds.
Results contain only predefined Russian status messages, never credentials or
response bodies. Any test may consume a small amount of the provider's quota.
"""
from __future__ import annotations

import urllib.error

from luxai.api_providers import endpoint_for, model_for
from luxai.online_agent import OnlinePlanner


def check_api_key(settings: dict, key: str) -> tuple[bool, str]:
    provider = str(settings.get("online_provider") or "openai")
    key = str(key or "").strip()
    if not key:
        return False, "API-ключ не введён. Укажите ключ выбранного провайдера."
    if any(ord(char) < 33 or ord(char) == 127 for char in key):
        return False, "Неверный формат API-ключа."

    try:
        model = model_for(provider, settings.get("online_model") or None)
        endpoint_for(provider, settings.get("online_custom_url", ""))
        timeout = max(3, min(10, int(settings.get("online_timeout", 5))))
    except (ValueError, TypeError, KeyError):
        return False, "Проверьте модель и HTTPS-адрес API в настройках."

    planner = OnlinePlanner(settings)
    messages = [
        {
            "role": "system",
            "content": (
                "Return ONLY JSON: "
                '{"action":"reply","target":"","reply":"OK"}.'
            ),
        },
        {
            "role": "user",
            "content": "Connectivity test. Reply exactly as instructed.",
        },
    ]
    try:
        result = planner._request(provider, model, key, messages, timeout)
        response = planner._extract_text(result, provider)
        parsed = planner._validate(planner._read_json_content(response))
        if parsed is not None:
            return True, "API работает: ключ принят, модель отвечает."
        # 200 confirms authentication and model access, but not structured
        # JSON compatibility needed by Jarvis's command planner.
        return False, (
            "Ключ и модель приняты, но ответ API не соответствует формату "
            "команд Jarvis. Попробуйте другую модель."
        )
    except urllib.error.HTTPError as exc:
        status = exc.code
        if status == 401:
            return False, "Ошибка 401: неверный, отозванный или просроченный API-ключ."
        if status == 403:
            return False, "Ошибка 403: нет доступа к API или выбранной модели."
        if status == 402:
            return False, "Ошибка 402: недостаточно средств или требуется оплата."
        if status == 404:
            return False, "Ошибка 404: указанная модель или API endpoint не найдены."
        if status == 429:
            return False, "Ошибка 429: исчерпана квота или превышен лимит запросов."
        if status in (400, 422):
            return False, (
                f"Ошибка {status}: модель или формат запроса не поддерживается. "
                "Проверьте выбранный API и название модели."
            )
        return False, f"Ошибка API (HTTP {status}). Проверьте настройки провайдера."
    except (urllib.error.URLError, TimeoutError, OSError):
        return False, "Нет подключения к API: проверьте интернет и адрес сервера."
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError):
        return False, "Сервер ответил, но формат ответа не поддерживается Jarvis."
