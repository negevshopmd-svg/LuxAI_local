# Jarvis: local executor + optional OpenAI planner

Jarvis keeps two separate roles:

1. **Local executor** runs the trusted Windows/Steam actions and asks for confirmation when that setting is enabled. Frequent actions (time, Dota 2, Telegram, Discord, etc.) are handled locally without using tokens or waiting for the network.
2. **Online planner** optionally interprets commands not covered by local shortcuts and returns a structured JSON proposal. The local executor checks the target against an allowlist, and never executes arbitrary AI-generated CMD or PowerShell commands.

Online replies use an OpenAI API key belonging to the user. The key is **not** included in the repository. ChatGPT Free/Plus plans do not automatically provide free API usage; API billing is separate and any promotional API credits depend on account eligibility.

## Настройка

1. Откройте Jarvis → **Настройки** → **ИИ-провайдер**.
2. Нажмите **Открыть страницу API-ключей** (https://platform.openai.com/api-keys).
3. Создайте ключ в своём аккаунте OpenAI и, если нужно, настройте API-биллинг.
4. Вставьте ключ в поле **OpenAI API-ключ**, включите **Облачный помощник** и нажмите **Сохранить настройки**.
5. Начните с **GPT-4.1 nano** для коротких и быстрых команд. Можно уменьшить таймаут до 3 секунд.

The key is encrypted for the current Windows user with DPAPI, stored in `.luxai_secrets/openai_key.dpapi`, and never written to `config.json`. The folder and logs are ignored by Git and protected by `Update.py`. To delete the stored key, press **Удалить сохранённый ключ**. An `OPENAI_API_KEY` environment variable also works and overrides the stored key.

**Privacy:** When enabled, the command and up to four recent conversation messages are sent to the OpenAI API. When disabled, commands remain local except for explicitly requested actions such as web search or first-time downloading of a Piper voice model.

## Examples

- `Жарвис, сколько время?` → fast local clock response.
- `Жарвис, открой доту` → (after confirmation, if enabled) Windows opens `steam://rungameid/570`.
- `Жарвис, запусти Counter-Strike 2` → known Steam app ID 730.
- A request to open an unfamiliar Steam game can be classified by the online planner; Jarvis then checks the exact title via the Steam Store API. The online model cannot supply the Steam ID directly.
- Commands for the desktop are allowlisted. An online response containing arbitrary shell code is rejected.

## Offline / errors

- With no key or with **Облачный помощник** off: Jarvis uses local shortcuts or the selected `.gguf` model.
- If the API is slow, unavailable or out of credit: Jarvis falls back to the local model. Requests are paused briefly after network/billing errors instead of repeatedly waiting.
- Connectivity errors and HTTP status codes appear in `online_agent.log`, without storing API keys or conversation text.
- Speech problems appear in `voice_error.log`.

Run `Update.bat` and restart using `run_windows.bat` after repository updates.

### Testing

The repository includes `tests/test_routing.py` and an automated GitHub Actions job. Run:

```cmd
.venv\Scripts\python.exe -m unittest discover -s tests -v
```
