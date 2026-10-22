# Jarvis: local executor + optional multi-provider AI planner

Jarvis uses two distinct agents:

1. **Online planner**, optional, interprets unfamiliar commands and returns structured JSON. Supported presets: **DeepSeek**, **OpenAI**, **OpenRouter**, **Groq**, **Google Gemini**, **Mistral AI**, **Together AI**, **Fireworks AI**, **xAI/Grok** and **Anthropic/Claude**. A custom **HTTPS OpenAI-compatible** `/chat/completions` endpoint is available for other providers.
2. **Local executor** independently checks the proposal and runs only an allowlisted action (or answers via the local `.gguf` model). It never copies an online model's CMD/PowerShell commands into the terminal. Frequent commands (time, Dota 2, Telegram, etc.) bypass cloud inference entirely.

**Important:** API keys cannot be used interchangeably. Choose the provider that **issued the key**. API-key prefixes are not reliable enough to identify the provider automatically. The app cannot guarantee compatibility with every API or model: nonstandard authentication/protocols and individual providers' model limits may require an adapter.

## Настройка DeepSeek

1. **Отзовите любой ключ, который уже публиковали в чате или другом месте, и создайте новый.**
2. Откройте Jarvis → **Настройки → ИИ-провайдер**.
3. В меню **Поставщик AI API** выберите **DeepSeek**.
4. Модель: **`deepseek-flash`** (быстрый вариант согласно текущим документам DeepSeek). Если в вашем аккаунте доступна другая модель, впишите её ID.
5. Вставьте **новый** ключ DeepSeek в поле **API-ключ выбранного сервиса**.
6. Включите **Облачный помощник** и нажмите **Сохранить настройки**.
7. Нажмите **Проверить API** для небольшого платного/лимитируемого тестового запроса.

DeepSeek docs: https://api-docs.deepseek.com/guides/search_fetch and https://api-docs.deepseek.com/guides/json_mode/.

## Настройка других провайдеров

Choose the service from the same list, specify a compatible model ID and enter a key **issued by that service**. Every provider has a **Получить ключ** link in settings. For an unsupported but OpenAI-compatible host, select **Другой OpenAI-совместимый HTTPS API**, enter a complete public **`https://.../chat/completions`** URL, a model ID, and its own key. The application rejects HTTP, embedded URL credentials and local/private-IP URL literals. **A custom provider receives your key and messages**, so only use a service you trust.

Claude uses its native **Messages API** rather than the OpenAI endpoint. Model IDs can change; use the model IDs available to your account.

**API costs:** ChatGPT subscriptions do not grant OpenAI API credits; DeepSeek and the other providers have separate pricing/limits. Some have free or trial quotas, but these are not guaranteed.

## Credentials and privacy

- Jarvis keeps keys **separately per provider**, encrypted with Windows DPAPI, in `.luxai_secrets/<provider>_key.dpapi`. Existing `openai_key.dpapi` keys still work.
- Keys are never included in `config.json` and are never committed to GitHub; `Update.py` preserves the secret folder.
- Optional environment variables: `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `TOGETHER_API_KEY`, `FIREWORKS_API_KEY`, `XAI_API_KEY`, `ANTHROPIC_API_KEY` and `JARVIS_CUSTOM_API_KEY`.
- To remove the selected stored key, click **Удалить ключ**. This does not unset an environment variable.
- When enabled, online planning transmits your current command plus up to four recent conversation messages to the **selected** provider. In offline mode these messages are not uploaded for online planning.
- Network failures, quotas, unsupported models and authentication errors fall back to local responses. `online_agent.log` contains only status codes/error classes, **not keys or conversations**.

## Fast local commands

- `Жарвис, сколько время?` → current local time, offline.
- `Жарвис, открой доту` → confirmed launch via `steam://rungameid/570`.
- `Жарвис, запусти Counter-Strike 2` → confirmed launch via Steam app ID 730.
- Unknown Steam game titles are resolved only via an exact match against the Steam Store API; untrusted app IDs/URLs/commands provided by an AI are never executed.

## Updating/testing

Run `Update.bat`, restart with `run_windows.bat`, choose a provider under Settings, and save. With a valid connection and key, test **Проверить API**. Without credentials, Jarvis stays local.

Offline syntax and routing checks:

```cmd
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Provider adapters are in `luxai/api_providers.py`, routing in `luxai/online_agent.py`, and Windows key storage in `luxai/secure_keys.py`.
