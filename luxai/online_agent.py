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

API_URL = "https://api.openai.com/v1/chat/completions"
ALLOWED_MODELS = {"gpt-4.1-nano", "gpt-4.1-mini", "gpt-4o-mini"}
ALLOWED_ACTIONS = {
    "open_app", "launch_game", "steam_game", "minimize_windows",
    "search_web", "time", "reply", "none",
}
CACHE_ACTIONS = {"open_app", "launch_game", "minimize_windows"}
LOG_FILE = Path(__file__).resolve().parents[1] / "online_agent.log"

_SYSTEM = """You are the ONLINE PLANNER for a Windows voice assistant Jarvis.
Interpret the user's command and respond with EXACTLY ONE JSON object:
{"action": "open_app|launch_game|steam_game|minimize_windows|search_web|time|reply|none",
 "target": "string", "reply": "string"}
Rules:
- You NEVER execute anything. The LOCAL agent validates your proposal.
- Do not generate code, a terminal command, a CMD line, PowerShell, registry
  operation, file path, URL, script, or executable as a target.
- open_app target MUST be exactly one of telegram, discord, chrome, firefox,
  edge, spotify, steam, notepad, calculator, explorer.
- launch_game target MUST be dota2 or cs2. Dota/Dota 2 = dota2.
- steam_game target is ONLY the official game title (no appid or URL). The
  local agent can verify it with the Steam store before launching.
- minimize_windows target must be empty.
- time target empty.
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
        old_model = self.config.get("online_model")
        self.config = dict(config)
        if old_model != self.config.get("online_model"):
            self._cache.clear()
        self._blocked_until = 0.0

    def enabled(self):
        return bool(self.config.get("online_agent_enabled", False) and get_api_key())

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
        if action == "launch_game" and target not in {"dota2", "cs2"}:
            return None
        if action in {"time", "minimize_windows", "reply", "none"}:
            target = ""
        if action in {"steam_game", "search_web"}:
            if not target or not re.fullmatch(r"[^\x00-\x1f<>\r\n]{1,100}", target):
                return None
        return {"action": action, "target": target, "reply": reply.strip()}

    def plan(self, text, history=()):
        if not self.enabled() or time.monotonic() < self._blocked_until:
            return None
        key = text.strip().casefold()
        if key in self._cache:
            self._cache.move_to_end(key)
            return dict(self._cache[key])
        key_value = get_api_key()
        if not key_value:
            return None

        model = str(self.config.get("online_model", "gpt-4.1-nano"))
        if model not in ALLOWED_MODELS:
            model = "gpt-4.1-nano"
        timeout = max(3, min(10, int(self.config.get("online_timeout", 5))))
        messages = [{"role": "system", "content": _SYSTEM}]
        for m in list(history)[-4:]:
            if isinstance(m, dict) and m.get("role") in ("user", "assistant"):
                messages.append({
                    "role": m["role"],
                    "content": str(m.get("content", ""))[:500],
                })
        messages.append({"role": "user", "content": text[:700]})
        body = json.dumps({
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": 160,
        }, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            API_URL,
            data=body,
            headers={
                "Authorization": "Bearer " + key_value,
                "Content-Type": "application/json",
                "User-Agent": "JarvisLocalAssistant/2.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise ValueError("Unexpected API response status")
                raw = response.read(1024 * 1024)
            result = json.loads(raw)
            content = result["choices"][0]["message"]["content"]
            proposal = self._validate(json.loads(content))
            if proposal is None:
                self._log("Planner returned an invalid proposal; local fallback")
                return None
            if proposal["action"] in CACHE_ACTIONS:
                self._cache[key] = proposal
                if len(self._cache) > 32:
                    self._cache.popitem(last=False)
            return proposal
        except urllib.error.HTTPError as exc:
            self._log(f"OpenAI HTTP {exc.code}; local fallback")
            self._blocked_until = time.monotonic() + (60 if exc.code in (401, 402, 403, 429) else 20)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self._log(f"OpenAI connection problem ({type(exc).__name__}); local fallback")
            self._blocked_until = time.monotonic() + 20
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            self._log(f"OpenAI response issue ({type(exc).__name__}); local fallback")
            self._blocked_until = time.monotonic() + 10
        return None
