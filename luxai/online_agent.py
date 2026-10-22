"""Optional online command planner for Jarvis.

The online model emits a small JSON *proposal*. It never executes commands.
LocalAgent validates proposals and uses its own fixed, allowlisted actions.
The online request is made only when explicitly enabled and configured with a
user-supplied API key. Offline or error conditions return None.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from pathlib import Path

from luxai.secure_keys import get_api_key
from luxai.api_providers import PROVIDERS, endpoint_for, model_for
from luxai.steam_games import lookup_steam_game
from luxai.file_actions import safe_name, ALLOWED_LOCATIONS
from luxai.windows_apps import normalized_name
from luxai.steam_games import GAMES

ALLOWED_ACTIONS = {
    "open_app", "launch_game", "steam_game", "minimize_windows",
    "search_web", "time", "reply", "none",
    "create_file", "create_folder", "list_files", "rename_file", "trash_file",
    "web_answer",
}
CACHE_ACTIONS = {"open_app", "launch_game", "minimize_windows"}
LOG_FILE = Path(__file__).resolve().parents[1] / "online_agent.log"

_SYSTEM = """You are GEMINI (or another CLOUD PLANNER) for a Windows assistant called Jarvis.
Your role is to understand each user's task and send a JSON plan to a LOCAL
WINDOWS EXECUTOR. The local executor, not you, performs actions with Windows.
Respond with ONLY ONE compact JSON object, not markdown or thoughts:
{"action":"open_app|steam_game|launch_game|minimize_windows|create_file|create_folder|rename_file|trash_file|list_files|search_web|web_answer|time|reply|none",
 "target":"string","reply":"string","source":"string","location":"desktop|documents|downloads","content":"string"}
Examples:
- "Открой фаерфокс" -> {"action":"open_app","target":"firefox","reply":""}
- "Открой Blender" -> {"action":"open_app","target":"Blender","reply":""}
- "Открой Undertale в Steam" -> {"action":"steam_game","target":"Undertale","reply":""}
- "Запусти андертейл" -> {"action":"steam_game","target":"Undertale","reply":""}
- "Создай файл на рабочем столе" -> {"action":"create_file","target":"Новый файл.txt","location":"desktop","reply":""}
- "Переименуй его в заметки.txt" -> {"action":"rename_file","source":"@last","target":"заметки.txt","location":"desktop","reply":""}
- "Удали созданный файл" -> {"action":"trash_file","source":"@last","target":"","location":"desktop","reply":""}
- "Какая погода завтра в Кишиневе?" -> {"action":"web_answer","target":"Какая погода завтра в Кишинёве?","reply":""}
Rules:
- open_app target is an APP NAME only. It may be any installed Windows app,
  not just a fixed list; never supply executable paths, scripts, code or flags.
  The local computer will search the Windows App Paths and Start menu itself.
- steam_game target is the game's official TITLE (Undertale, War Thunder etc).
  The LOCAL executor verifies the Steam App ID with trusted Steam Store data.
  DO NOT generate arbitrary CMD commands or raw Steam URIs. Local executor
  constructs the verified Steam launch URI.
- launch_game target may be dota2, cs2, warthunder, undertale if obvious.
- create_file / create_folder: basename only, no paths, never overwrite;
  select desktop, documents, or downloads. For no name use "Новый файл.txt".
  You may supply content for create_file only if the user dictated that content.
- rename_file: source is original basename or "@last" when user says "его",
  target is new basename. Do not invent a prior filename; if no known source
  use "@last" and local executor determines whether a previous file exists.
- trash_file: source is basename or "@last"; file moves to Recycle Bin,
  NEVER permanently deleted. Confirm with user before doing this.
- search_web means OPEN browser search results.
- web_answer means ANSWER factual, weather, news and current web questions
  using Google Search grounding (if available), without claiming it is live
  when it isn't.
- reply means ordinary conversation, NOT a claim that Windows actions ran.
  Never use reply to assert "opened", "created", "renamed", "deleted" or
  "launched" a file/app; only executor may confirm operations.
- You may not issue raw CMD, PowerShell, registry changes, arbitrary paths,
  shell operators, or executables. Let the user configure manual macros.
- Keep Russian responses Russian. If uncertain ask a short clarification.
"""


class OnlinePlanner:
    def __init__(self, config):
        self.config = dict(config)
        self._blocked_until = 0.0
        self._cache = OrderedDict()
        self.last_error = ""

    def update_config(self, config):
        updated = dict(config)
        if updated == self.config:
            return
        previous = (
            self.config.get("online_provider", "openai"),
            self.config.get("online_model"),
            self.config.get("online_custom_url"),
        )
        current = (
            updated.get("online_provider", "openai"),
            updated.get("online_model"),
            updated.get("online_custom_url"),
        )
        was_enabled = self.config.get("online_agent_enabled", False)
        self.config = updated
        if previous != current:
            self._cache.clear()
        if previous != current or was_enabled != updated.get("online_agent_enabled", False):
            self._blocked_until = 0.0

    def _provider(self):
        value = self.config.get("online_provider", "openai")
        return value if value in PROVIDERS else "openai"

    def enabled(self):
        return bool(
            self.config.get("online_agent_enabled", False)
            and get_api_key(self._provider())
        )

    @staticmethod
    def _log(message):
        # Never log prompts, bearer tokens, or API response bodies.
        try:
            with LOG_FILE.open("a", encoding="utf-8") as file:
                file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
        except OSError:
            pass

    @staticmethod
    def _validate(result):
        if not isinstance(result, dict):
            return None
        action = result.get("action")
        target = result.get("target", "")
        reply = result.get("reply", "")
        if action not in ALLOWED_ACTIONS or not isinstance(target, str) or not isinstance(reply, str):
            return None
        if len(target) > 150 or len(reply) > 1000:
            return None
        target = target.strip()
        if action == "open_app":
            try:
                target = normalized_name(target)
            except ValueError:
                return None
        if action == "launch_game" and target not in GAMES:
            return None
        if action in {"time", "minimize_windows", "reply", "none", "list_files", "trash_file"}:
            target = ""
        if action in {"steam_game", "search_web", "web_answer"}:
            if not target or not re.fullmatch(r"[^\x00-\x1f<>\r\n]{1,150}", target):
                return None
        location = result.get("location", "desktop")
        if action in {"create_file", "create_folder", "rename_file", "trash_file", "list_files"}:
            if location not in ALLOWED_LOCATIONS:
                return None
            if action in {"create_file", "create_folder", "rename_file"}:
                try:
                    target = safe_name(target, is_folder=action == "create_folder")
                except ValueError:
                    return None
            source = result.get("source", "")
            if action in {"rename_file", "trash_file"}:
                if not isinstance(source, str) or len(source) > 100:
                    return None
                if source != "@last":
                    try:
                        source = safe_name(source, is_folder=True)
                    except ValueError:
                        return None
            else:
                source = ""
            content = result.get("content", "")
            if not isinstance(content, str) or len(content) > 4096:
                return None
            return {
                "action": action, "target": target, "reply": reply.strip(),
                "source": source, "location": location,
                "content": content if action == "create_file" else "",
            }
        return {"action": action, "target": target, "reply": reply.strip()}

    @staticmethod
    def _read_json_content(text):
        """Parse a JSON-only reply, tolerating markdown fences from weaker models."""
        if isinstance(text, list):
            text = "".join(
                str(item.get("text", ""))
                for item in text if isinstance(item, dict) and item.get("type") == "text"
            )
        if not isinstance(text, str):
            raise ValueError("Empty provider response")
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
        return json.loads(text)

    @staticmethod
    def _extract_text(response, provider):
        if provider == "anthropic":
            content = response.get("content", [])
            return "".join(
                item.get("text", "")
                for item in content if isinstance(item, dict) and item.get("type") == "text"
            )
        return response["choices"][0]["message"]["content"]

    def _request(self, provider, model, api_key, messages, timeout):
        """Send to one explicitly selected provider, without cross-host redirects."""
        endpoint = endpoint_for(provider, self.config.get("online_custom_url", ""))
        if provider == "anthropic":
            payload = {
                "model": model,
                "system": _SYSTEM,
                "messages": [m for m in messages if m["role"] != "system"],
                "max_tokens": 300,
            }
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            }
        else:
            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": 300,
                "temperature": 0,
            }
            if provider in {"openai", "deepseek"}:
                payload["response_format"] = {"type": "json_object"}
            headers = {"Authorization": "Bearer " + api_key}
        headers.update({
            "Content-Type": "application/json",
            "User-Agent": "JarvisLocalAssistant/2.1",
        })
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                raise urllib.error.HTTPError(
                    req.full_url, code, "Redirect blocked for API credentials", headers, fp,
                )

        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise ValueError("Unexpected API response status")
            raw = response.read(1024 * 1024)
        return json.loads(raw)

    def _grounded_answer(self, question: str, model: str, key: str, timeout: int) -> str:
        """Ask Gemini's native Google Search grounding tool to browse.

        The OpenAI-compatible chat endpoint does not automatically search.
        This native endpoint is used for weather, news and current facts.
        """
        if self._provider() != "gemini":
            return (
                "Поиск в интернете через текущего AI-провайдера не настроен. "
                "Выберите Gemini и проверьте API-ключ, либо попросите открыть поиск."
            )
        from luxai.api_providers import validate_model
        import urllib.parse
        model = validate_model(model)
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            + urllib.parse.quote(model, safe="") + ":generateContent"
        )
        payload = {
            "contents": [{
                "parts": [{"text": (
                    "Ответь по-русски кратко на основании свежих проверяемых "
                    "результатов Google Search. Укажи конкретную дату прогноза "
                    "для вопросов о погоде. Если нет данных, скажи об этом. "
                    "Вопрос: " + question[:450]
                )}]
            }],
            "tools": [{"google_search": {}}],
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "x-goog-api-key": key,
                "Content-Type": "application/json",
                "User-Agent": "JarvisLocalAssistant/3",
            },
            method="POST",
        )

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                raise urllib.error.HTTPError(
                    req.full_url, code, "No key forwarding", headers, fp,
                )

        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(request, timeout=max(5, min(20, timeout * 2))) as response:
            result = json.loads(response.read(1024 * 1024))
        candidates = result.get("candidates", [])
        if not candidates:
            raise ValueError("Google Search returned no answer")
        answer = " ".join(
            str(part.get("text", ""))
            for part in candidates[0].get("content", {}).get("parts", [])
            if isinstance(part, dict) and "text" in part
        ).strip()
        if not answer:
            raise ValueError("No grounded text")
        grounding_meta = candidates[0].get("groundingMetadata", {})
        sources = []
        for entry in grounding_meta.get("groundingChunks", [])[:6]:
            web = entry.get("web", {}) if isinstance(entry, dict) else {}
            link = str(web.get("uri", ""))
            if link.startswith("https://") and len(link) <= 400:
                sources.append(link)
        if sources:
            answer += "\nИсточники: " + " ".join(sources[:2])
        return answer[:1200]

    def plan(self, text, history=()):
        provider = self._provider()
        if not self.enabled():
            self.last_error = "онлайн-агент выключен или API-ключ отсутствует"
            return None
        if time.monotonic() < self._blocked_until:
            self.last_error = "провайдер временно недоступен после ошибки API"
            return None
        self.last_error = ""
        key = text.strip().casefold()
        cache_key = (provider, key)
        if cache_key in self._cache:
            self._cache.move_to_end(cache_key)
            return dict(self._cache[cache_key])
        api_key = get_api_key(provider)
        if not api_key:
            return None

        timeout = max(3, min(10, int(self.config.get("online_timeout", 5))))
        messages = [{"role": "system", "content": _SYSTEM}]
        for m in list(history)[-4:]:
            if isinstance(m, dict) and m.get("role") in ("user", "assistant"):
                messages.append({
                    "role": m["role"],
                    "content": str(m.get("content", ""))[:500],
                })
        messages.append({"role": "user", "content": text[:700]})

        try:
            configured_model = self.config.get("online_model") or None
            # Older installations stored an OpenAI model without a provider.
            if provider != "openai" and configured_model in {
                "gpt-4.1-nano", "gpt-4.1-mini", "gpt-4o-mini",
            }:
                configured_model = None
            model = model_for(provider, configured_model)
            response = self._request(provider, model, api_key, messages, timeout)
            raw_text = self._extract_text(response, provider)
            proposal = self._validate(self._read_json_content(raw_text))
            if proposal is None:
                self._log(f"{provider} returned an invalid proposal; local fallback")
                self.last_error = "Gemini вернул действие в неверном формате"
                return None
            if proposal["action"] == "web_answer":
                answer = self._grounded_answer(proposal["target"], model, api_key, timeout)
                return {
                    "action": "reply", "target": "", "reply": answer,
                    "grounded": provider == "gemini",
                }
            if proposal["action"] == "steam_game":
                match = lookup_steam_game(
                    proposal["target"],
                    timeout=max(2, min(4, timeout)),
                )
                if match is None:
                    proposal = {
                        "action": "reply", "target": "",
                        "reply": (
                            "Не удалось найти игру с точным названием в Steam."
                            if re.search(r"[а-яё]", text, re.IGNORECASE)
                            else "I couldn't find that exact game title on Steam."
                        ),
                    }
                else:
                    app_id, official_name = match
                    proposal = {
                        "action": "steam_verified",
                        "target": official_name,
                        "appid": app_id,
                        "reply": "",
                    }
            if proposal["action"] in CACHE_ACTIONS:
                self._cache[cache_key] = proposal
                if len(self._cache) > 32:
                    self._cache.popitem(last=False)
            return proposal
        except urllib.error.HTTPError as exc:
            self.last_error = f"{provider}: HTTP {exc.code}"
            self._log(f"{provider} HTTP {exc.code}; local fallback")
            self._blocked_until = time.monotonic() + (60 if exc.code in (401, 402, 403, 429) else 20)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.last_error = f"{provider}: нет подключения или превышено время ожидания"
            self._log(f"{provider} connection problem ({type(exc).__name__}); local fallback")
            self._blocked_until = time.monotonic() + 20
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            self.last_error = f"{provider}: ошибка ответа модели ({type(exc).__name__})"
            self._log(f"{provider} response issue ({type(exc).__name__}); local fallback")
            self._blocked_until = time.monotonic() + 10
        return None
