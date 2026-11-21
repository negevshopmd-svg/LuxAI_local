# LuxAI Local / Jarvis — Project handoff and architecture

> START HERE for anyone (human or AI) who works on this repository. Rules and the release
> workflow are in **CLAUDE.md**; the full history is in **CHANGELOG.md**. Always check
> `version.txt` and the latest commits first — this file describes 0.4.2x (2026-11-20).

## What it is
A Windows 10/11 (64-bit) desktop voice assistant called **Jarvis**. Python 3.11 + PySide6, its
own `.venv` inside the installation folder. Interface and replies in Russian, Romanian and English.
Local first: speech recognition (faster-whisper), voices (Piper / Windows; optional Fish Audio cloud),
offline translator (NLLB-200), OCR (Tesseract) and an optional local GGUF model all run on the PC.
An optional cloud planner (Gemini, OpenAI, DeepSeek, …, user's own key) handles unfamiliar
commands; the local Windows executor still validates and runs every action.

## Folder layout (installation = repository minus dev files)
| Path | Role |
| --- | --- |
| `run_windows.bat` | Start: checks the venv (cached), builds Jarvis.exe, uses this folder's admin task if any, else starts `launch_windows.py`. |
| `launch_windows.py` | Bootstrap with visible errors: single-instance mutex per folder, refuses to start during an update, finishes an interrupted update (`Update.py --resume`), native crash log. |
| `main.py` | `MainWindow`: chat, home, settings, command routing (`_route_*` stages), voice in/out, speech queue, cloud/local AI. ~5 000 lines. |
| `luxai/` | All modules (map below). |
| `Update.bat`, `Update.py`, `scripts/fetch_updater.py`, `scripts/release_signature.py` | Signed updater. |
| `install_windows.bat`, `scripts/install_windows.ps1`, `scripts/setup_ui.ps1` | Installer/repair and the WPF setup window shared with the updater. |
| `browser_extension/` | Chrome/Edge extension (installed on the PC): reports the playing video and its media to Jarvis. |
| `README_RO.txt` / `README_RU.txt` / `README_EN.txt` | User guide + per-version notes (installed on the PC). |
| `release_manifest.json` + `.sig` | Ed25519-signed list of every file of the release. |
| `runtime_cleanup_manifest.json` | Hashes of dev-only files, so old copies are removed from user PCs. |
| `models/`, `voices/`, `.luxai_data/`, `config.json`, `.venv/` | User data — never overwritten by updates, not in git. |

## Startup and update chain
1. `Update.bat` (ASCII, CRLF) finds Python, runs `scripts/fetch_updater.py` from the INSTALLED copy:
   GitHub API exact commit → git blob hash check → signature of the new `Update.py` → no downgrade →
   bootstrap lock. Without `fetch_updater.py` it stops (no unsigned route).
2. `Update.py` (holds `.luxai_data/updater.lock`): closes this folder's Jarvis (also the elevated one
   through its own task), downloads the zip, extracts once, **verifies every file against the signed
   manifest**, validates requirements, then one transaction: stage files + durable journal
   (`.luxai_update_journal.json`) → move into place → remove files the new version dropped →
   libraries (installed only when `requirements.txt` changed; `pip freeze` snapshot restored exactly
   on failure) → GGUF / OCR / translator (optional steps) → write `.luxai_update_state.json`.
   Any failure restores code, removed files and libraries. `.luxai_update_pending.json` marks an
   update in progress.
3. `launch_windows.py` refuses to start while the updater lock is held, finishes a left journal under
   the same lock, and asks before starting when the pending marker is still there.
4. Setup window: `Update.py`/`install_windows.ps1` write JSON-lines events (plan/step/detail/log/bytes/done
   with ro/ru/en text) that `scripts/setup_ui.ps1` shows (fonts copied to temp — WPF locks them).

## Publishing the browser extension (optional, one-click install)
Today the user installs `browser_extension/` once with «Load unpacked» (the guided window in
`luxai/ui_browser_extension.py`; Jarvis offers it when captions start). On Windows Chrome installs other
extensions silently only from the Chrome Web Store, so for a one-click install:
1. `python tests/build_extension_package.py` → `dist/jarvis-film-captions-<version>.zip`.
2. https://chrome.google.com/webstore/devconsole (Google developer account, one-time fee) → New item → upload.
3. Listing: name «Jarvis Film Captions»; summary «Lets the Jarvis desktop assistant (LuxAI Local) prepare film
   captions in advance»; category Accessibility. Single purpose: tell the Jarvis app on the same PC which
   video plays and where. Permissions: `webRequest` + all sites (find the media a page plays),
   `storage` (per-tab list in session storage). Data: no personal data collected or sent anywhere; it only
   talks to 127.0.0.1. Privacy policy: the same sentence, hosted e.g. on the GitHub repository page.
4. After approval put the store ID in `STORE_ID` in `luxai/ui_browser_extension.py`; the guide then opens the
   store page («Add to Chrome»).

## Release signing
`tests/sign_release.py` builds the manifest from the git index and signs it with the private key
(DPAPI-encrypted at `%USERPROFILE%\.luxai_release\signing_key.bin`; `--init` creates one). The public
key is built into `Update.py` and `scripts/release_signature.py`. `.bat/.cmd` are hashed with LF ends.

## Module map (`luxai/`)
- **Voice in/out:** `voice.py` (microphone loop, VAD, «stop» barge-in `_BargeInDetector`),
  `voice_rules.py`, `audio_devices.py`, `listening_controls.py`, `voices.py` (Piper/Windows/Fish,
  prefetch), `fish_tts.py`, `voice_presets.py`.
- **Understanding commands:** `fast_intents.py`, `task_intents.py`, `intent_routing.py`, `voice_desktop.py`,
  `voice_actions.py`, `voice_files.py`, `voice_shortcuts.py`, `response_language.py`.
- **Command library:** `command_registry.py` (validated, allow-listed; `fingerprint()` for caching),
  `default_commands.py`, `command_triggers.py` (hotkeys, schedules, events), `command_transfer.py`,
  `command_wizard.py`, `command_recording.py`, `action_catalog.py`, `desktop_actions.py`, `macro_planner.py`,
  UI: `ui_commands.py`, `ui_command_*.py`, `ui_action_picker.py`, `app_icons.py`.
- **Agents:** `agent.py` (local executor), `online_agent.py` + `api_providers.py` + `api_verification.py`
  + `gemini_models.py` + `cloud_http.py` (cloud planner), `task_agent.py` / `desktop_agent.py` /
  `adaptive_tasks.py` / `visual_reasoner.py` / `visual_click.py` (evidence-driven task loop),
  `task_memory.py`, `agent_experience.py`, `model_json.py`, `local_shell.py`.
- **Local AI:** `gguf_backend.py` + `gguf_worker.py` (isolated llama.cpp process per request),
  `local_ai_setup.py`, `local_ai_status.py`, `local_ai_health.py`, `local_models.py`.
- **Windows:** `win32.py`, `windows_apps.py`, `windows_control.py`, `windows_volume.py`, `keys.py`,
  `screen.py` + `ocr_setup.py` (Tesseract), `screen_interact.py` (UI Automation), `selection.py`,
  `scroll_assist.py`, `admin_mode.py` (per-folder admin task), `jarvis_exe.py`.
- **Discord / Steam / web:** `discord_audio.py` (mic/deafen via UIA, offline), `discord_shortcuts.py`,
  `discord_*` (visual, verified flows), `steam_games.py`, `steam_profile_visual.py`, `websites.py`,
  `web_research.py`, `research_notepad.py`, `weather_service.py`.
- **Extensions (plugins page):** `extensions_catalog.py` (22 plugins, settings schema),
  `extensions_runtime.py` (behaviour of the 15 working ones), UI `ui_extensions.py`, `ui_extension_settings.py`.
  Working: smart dictation (`dictation.py`), notification reader (`notifications.py`), read aloud
  (`translation.py`), live captions (`live_captions.py`, `loopback_audio.py`; «Hybrid»: fast draft + translation,
  precise correction on its own thread), film captions in advance (`film_captions.py` + the Chrome/Edge
  extension in `browser_extension/`, local bridge on 127.0.0.1:47321; the decoder connects only through the
  checking proxy `media_proxy.py`, public addresses only), clipboard history
  (`clipboard_store.py`, `clipboard_native.py`, `ui_clipboard.py`), quick inserts, visual avatar
  (`avatar.py`), breaks, PC Control via Telegram bot (`telegram_control.py`), media keys, timers and
  alarms (`timers.py`), converter (`converter.py`, `ui_convert_circle.py`), screenshots, downloads cleanup.
  «Soon»: meeting notes, text helper, ask documents, desktop pet, status island, action circle,
  smart home, streamer helper.
- **Translation:** `offline_translate.py` (NLLB-200 600M CTranslate2 int8, pinned revision + SHA-256,
  repair in background), `chat_translate.py` («translate …» in the chat).
- **Attachments:** `chat_attachments.py`, `attachment_chat.py`, `attachment_documents.py`,
  `clipboard_attachments.py`, `file_actions.py`, `ui_attachments.py`, `ui_chat_composer.py`.
- **UI shell:** `styles.py`, `icons.py` (Lucide + project SVGs), `ui_fonts.py` (Onest, Fuzzy Bubbles,
  Pangolin), `ui_home.py`, `ui_sidebar.py`, `ui_window_chrome.py`, `settings_panel.py`,
  `ui_preferences.py`, `settings_updates.py` (update check), `ui_i18n.py` (RU source → EN/RO table),
  `ui_screen_assist.py`, `cloud_status.py`, `diagnostics.py`.
- **Shared helpers:** `atomic_io.py` (unique temp + fsync + replace with retry), `background.py`
  (`LatestWorker`, `SerialQueue`), `secure_keys.py` (DPAPI keys; `saved_api_key` vs environment).

## Threading rules
Qt objects only on the GUI thread. Everything slow runs on a worker and comes back through a Signal:
clipboard reads (Win32 API), picture encoding, history load/save, notifications SQLite, translations,
downloads cleanup, UAC wait, screenshot PNG, OCR, model loading, cloud calls. Late results are
dropped by a generation number (dictation, Telegram bot, clipboard load, speech).

## Data the app keeps (never in git)
`config.json` (validated on load, original copied aside when fixed), `.luxai_data/` (commands,
timers, clipboard history encrypted with DPAPI, OCR, admin task name, updater lock), `.luxai_secrets`
/ DPAPI key files, `models/` (Whisper, GGUF, NLLB), `voices/` (Piper), `logs/`.

## Tests
`tests/` (~160 modules, ~1650 tests): `tests/run_suite.py` runs each module in its own process.
Qt tests use real widgets with mocks for Windows. `tests/build_runtime_manifest.py` refreshes the
dev-file catalog; `tests/test_runtime_distribution.py` fails until it is run after editing dev files.
`tests/test_audit_fixes_042r.py` and `tests/test_audit2_fixes_042w.py` cover the two audit reports.

## Known limits / open points
- Not testable here: real slow clipboard owners, UAC prompt, a real Telegram bot, the live microphone loop.
- The local GGUF model starts a fresh isolated process per request (deliberate crash isolation).
- Clipboard events within ~60 ms are read once (the current content) — documented in `clipboard_native.py`.
- Many functions are still long (C901 under 40 but above Ruff's default); split when you touch them.
