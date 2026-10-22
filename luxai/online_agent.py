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

ALLOWED_ACTIONS = {
    "open_app", "launch_game", "steam_game", "minimize_windows",
    "search_web", "time", "reply", "none",
    "create_file", "create_folder", "list_files",
}
CACHE_ACTIONS = {"open_app", "launch_game", "minimize_windows"}
LOG_FILE = Path(__file__).resolve().parents[1] / "online_agent.log"

_SYSTEM = """You are the ONLINE PLANNER for a Windows voice assistant Jarvis.
Interpret the user's command and respond with EXACTLY ONE JSON object:
{"action": "open_app|launch_game|steam_game|minimize_windows|search_web|time|create_file|create_folder|list_files|reply|none",
 "target": "string", "reply": "string", "location": "desktop|documents|downloads"}
Rules:
- You NEVER execute anything. The LOCAL agent validates your proposal.
- Do not generate code, a terminal command, a CMD line, PowerShell, registry
  operation, file path, URL, script, or executable as a target.
- open_app target MUST be exactly one of telegram, discord, chrome, firefox,
  edge, spotify, steam, notepad, calculator, explorer.
- launch_game target MUST be dota2, cs2 or warthunder.
  Dota/Dota 2 = dota2, Counter-Strike 2 = cs2, War Thunder = warthunder.
- steam_game target is ONLY the official game title (no appid or URL). The
  local agent can verify it with the Steam store before launching.
- minimize_windows target must be empty.
- time target empty.
- create_file target is a SINGLE BASENAME (e.g. "Отчёт.txt"), not a path.
  If no name was requested use "Новый файл.txt"; only .txt/.md/.csv/.json/.log.
  Set location to desktop, documents or downloads. Never overwrite.
- create_folder target is a SINGLE folder name; default "Новая папка".
- list_files target empty and location is desktop, documents or downloads.
- Do not propose reading, deleting, overwriting or moving private files.
  No arbitrary shell commands; the local executor always asks confirmation
  before creating files and folders.
- search_web target is a short search phrase if user explicitly asks to search
  the web, not a URL.
- reply action: concise natural-language answer to conversation/questions,
  in the user's language (Russian when the input is Russian).
- Never claim a program opened until the local executor confirms success.
- If the command is ambiguous, respond with reply asking a concise question.
- Do not include thoughts or markdown code blocks.
"""


class OnlinePlanner:
    def __init__(self, config):
        self.config = dict(config)
        self._blocked_until = 0.0
        self._cache = OrderedDict()

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
        if len(target) > 100 or len(reply) > 1000:
            return None
        target = target.strip()
        if action == "open_app" and target not in {
            "telegram", "discord", "chrome", "firefox", "edge",
            "spotify", "steam", "notepad", "calculator", "explorer",
        }:
            return None
        if action == "launch_game" and target not in {"dota2", "cs2", "warthunder"}:
            return None
        if action in {"time", "minimize_windows", "reply", "none", "list_files"}:
            target = ""
        if action in {"steam_game", "search_web"}:
            if not target or not re.fullmatch(r"[^\x00-\x1f<>\r\n]{1,100}", target):
                return None
        location = result.get("location", "desktop")
        if action in {"create_file", "create_folder", "list_files"}:
            if location not in ALLOWED_LOCATIONS:
                return None
            if action in {"create_file", "create_folder"}:
                try:
                    target = safe_name(
                        target, is_folder=action == "create_folder",
                    )
                except ValueError:
                    return None
            content = result.get("content", "")
            if not isinstance(content, str) or len(content) > 4096:
                return None
            return {
                "action": action, "target": target, "reply": reply.strip(),
                "location": location, "content": content,
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

    def plan(self, text, history=()):
        provider = self._provider()
        if not self.enabled() or time.monotonic() < self._blocked_until:
            return None
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
                return None
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
            self._log(f"{provider} HTTP {exc.code}; local fallback")
            self._blocked_until = time.monotonic() + (60 if exc.code in (401, 402, 403, 429) else 20)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self._log(f"{provider} connection problem ({type(exc).__name__}); local fallback")
            self._blocked_until = time.monotonic() + 20
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            self._log(f"{provider} response issue ({type(exc).__name__}); local fallback")
            self._blocked_until = time.monotonic() + 10
        return None
