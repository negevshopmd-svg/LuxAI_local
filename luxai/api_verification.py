"""Safely verify API credentials, chosen model, and real text generation.

For Gemini: first list models accessible by this key, then choose an actual
text-capable Gemini model instead of an AI Studio agent name such as
"Antigravity". The key is never saved or logged by the verifier.
"""
from __future__ import annotations

import urllib.error

from luxai.api_providers import endpoint_for, model_for
from luxai.cloud_http import request_timeout, TRANSIENT_STATUSES
from luxai.gemini_models import choose_gemini_model, list_gemini_models
from luxai.online_agent import OnlinePlanner


def _api_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
        if code == 401:
            return "Ошибка 401: API-ключ неверный, отозван или больше не действует."
        if code == 403:
            return "Ошибка 403: у ключа нет доступа к этому API или модели."
        if code == 402:
            return "Ошибка 402: недостаточно средств или нужна оплата."
        if code == 404:
            return "Ошибка 404: выбранная модель или адрес API не найдены."
        if code == 429:
            return "Ошибка 429: закончилась квота или превышен лимит запросов."
        if code in (400, 422):
            return (
                f"Ошибка {code}: модель или формат запроса не поддерживается. "
                "Проверьте имя модели и настройки API."
            )
        if code in (500, 502, 503, 504):
            return (
                f"Ошибка API (HTTP {code}): сервис временно недоступен или перегружен. "
                "Это не означает, что API-ключ неверный. Повторите проверку позже "
                "и проверьте состояние выбранного провайдера."
            )
        return f"Ошибка API (HTTP {code}). Проверьте настройки провайдера."
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        return "Нет подключения к API: проверьте интернет и адрес сервера."
    return "Сервер ответил, но формат ответа не поддерживается Jarvis."


def _test_messages():
    return [
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


def check_api_key_detailed(settings: dict, key: str) -> tuple[bool, str, str | None]:
    """Return (success, safe user-facing message, verified model ID).

    A non-None model ID is only offered after a successful generation request.
    Never mistake a models-list 200 response for evidence chat generation works.
    """
    provider = str(settings.get("online_provider") or "openai")
    key = str(key or "").strip()
    if not key:
        return False, "API-ключ не введён. Укажите ключ выбранного провайдера.", None
    if len(key) > 2048 or any(ord(char) < 33 or ord(char) == 127 for char in key):
        return False, "Неверный формат API-ключа.", None
    try:
        configured_model = model_for(provider, settings.get("online_model") or None)
        endpoint_for(provider, settings.get("online_custom_url", ""))
        timeout = request_timeout(settings)
    except (ValueError, TypeError, KeyError):
        return False, "Проверьте модель и HTTPS-адрес API в настройках.", None

    choices = [configured_model]
    if provider == "gemini":
        # This GET is authenticated. It separates invalid credentials from
        # invalid model IDs, which otherwise often produce HTTP 400/404.
        try:
            available = list_gemini_models(key, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in TRANSIENT_STATUSES and configured_model.startswith("gemini-"):
                # Model discovery is helpful metadata, not proof of chat
                # availability. If its gateway is down, test ONLY the user's
                # already selected model; never guess another model or host.
                # Generation must still succeed before marking this key valid.
                available = None
            else:
                return False, _api_error(exc), None
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            return False, _api_error(exc), None
        except (ValueError, TypeError, KeyError, IndexError):
            return False, "Не удалось получить список моделей Gemini. Проверьте API.", None
        if available is not None:
            if not available:
                return False, "Ключ принят, но доступных текстовых моделей Gemini не найдено.", None
            chosen = choose_gemini_model(available, configured_model)
            if chosen is None:
                return False, "Для этого ключа не найдена доступная модель Gemini.", None
            choices = [chosen]
            # If one model is disabled for the project, try one other listed model.
            backup = choose_gemini_model([m for m in available if m != chosen], None)
            if backup:
                choices.append(backup)

    planner = OnlinePlanner(settings)
    for index, model in enumerate(choices):
        try:
            result = planner._request(provider, model, key, _test_messages(), timeout)
            response = planner._extract_text(result, provider)
            parsed = planner._validate(planner._read_json_content(response))
            if parsed is not None:
                if provider == "gemini" and model != configured_model:
                    return (
                        True,
                        f"API работает. Модель «{configured_model}» недоступна; "
                        f"проверена «{model}». Модель будет сохранена автоматически.",
                        model,
                    )
                return True, f"API работает: ключ принят, модель «{model}» отвечает.", model
            return (
                False,
                "Ключ и модель приняты, но ответ API не соответствует формату "
                "команд Jarvis. Попробуйте другую модель.",
                None,
            )
        except urllib.error.HTTPError as exc:
            if (
                provider == "gemini"
                and exc.code in (400, 404)
                and index + 1 < len(choices)
            ):
                continue
            return False, _api_error(exc), None
        except (
            urllib.error.URLError, TimeoutError, OSError,
            ValueError, TypeError, KeyError, IndexError, UnicodeError,
        ) as exc:
            return False, _api_error(exc), None
    return False, "Не удалось проверить модель API.", None


def check_api_key(settings: dict, key: str) -> tuple[bool, str]:
    """Backward-compatible two-value API used by existing callers/tests."""
    passed, message, _model = check_api_key_detailed(settings, key)
    return passed, message
