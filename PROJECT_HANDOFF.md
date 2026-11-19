# LuxAI Local / Jarvis — Project Handoff and Architecture

> **Purpose:** This file is the authoritative START HERE for a new ChatGPT/Codex chat working on this repository. Read it alongside the actual source code and tests. Do not assume this handoff is newer than \`main\`: always inspect \`version.txt\`, latest commits, and CI status before editing.
>
> Repository: https://github.com/negevshopmd-svg/LuxAI_local  
> OS: Windows 10/11, 64-bit. Python + PySide6. UI and voice responses primarily Russian, with Romanian/English support.  
> Updated for the **0.3.9.e work**, 2026-10-30. \`Update.bat\` installs the code merged into \`main\`, NOT an open PR.
> Do NOT include real API keys, private logs, screen captures, model binaries, user audio, or personal paths in Git history.

## 0. Release 0.4.1t — Visual avatar

`luxai/avatar.py`: `resolve_state` (priority error > exec > speak > mic_off > quiet > prefix), `loudness`, `preset_point`, `snap_to_edges`, `LevelMeter` (voice = process loopback of Jarvis's own pid, system, mic via sounddevice, apps, all), `AvatarView` (painted wobbling rings + glow), `AvatarWindow` (frameless, lock = WindowTransparentForInput), `looks_failed`. Runtime: `_apply_avatar`, `_tick_avatar` (100 ms; flags from host `_processing`, `voices.barge_in_ready`, cfg mic/tts/prefix, home avatar `_listening`; full-screen check each second), `avatar_event("error")` called from `main._resolved_command`, `show/hide_avatar`, position saved via `update_extension_setting`. Settings: kind `color` (`ColorField`), `PositionGrid`, `@monitor`, side preview. Tests: `tests/test_visual_avatar_041t.py`.

## 0. Release 0.4.1q — Live captions

`luxai/loopback_audio.py`: `LoopbackCapture` (16 kHz mono PCM via AUTOCONVERTPCM; app = process loopback INCLUDE_TREE through `ActivateAudioInterfaceAsync`, all = default-speaker loopback; EXCLUDE_TREE of Jarvis is NOT used because it also drops programs Jarvis launched), `audio_apps()`, `app_pid()`. `luxai/live_captions.py`: `PhraseSegmenter` (energy, 0.7 s pause / 12 s max), `CaptionEngine` (partial ≈1 s, final via `dictation.transcribe`), `CaptionBar`. Runtime: `show/hide/toggle_captions`, `_start_caption_audio` (mutes while `voices.barge_in_ready`), translation via the offline queue `_queue_caption_translation` (`translation.translate_offline`), position in `extensions_meta.captions_position`, voice `handle_captions_request`; host `set_extension_enabled`. Page rows `@source`, `@tr_status`, `@position`. Tests: `tests/test_live_captions_041q.py`.

## 0. Release 0.4.1p — Clipboard history like Luxify

`luxai/clipboard_store.py`: `ClipboardHistory` (text+html / png+thumb items, dedupe by content, pins, `trim`, `prune`, DPAPI file `.luxai_data/clipboard_history.bin` with `LUXCLIP1` magic), `marked_private` (Exclude…/CanIncludeInClipboardHistory=0/Clipboard Viewer Ignore), `excluded_app`, `suppress()` (Jarvis's own temporary clipboard use; called in `selection.copy_selected_text`/`restore_clipboard` and quick-insert pastes). Runtime: `_on_clipboard`, `_remember_image`, `_paste_clip` (Shift+Enter = text only), `_clip_ai` → `OnlineAgent.transform_text` (fix/short), `_clip_translate` → offline translator, `handle_clipboard_request` («вставь предыдущее»), signal `clipboard_changed`. UI: `luxai/ui_clipboard.py` (`ClipboardPopup`), settings kind `tags` (`TagsField`, `FlowLayout`), keys `@note`, `@clip_now`, `@ai_status`, `NAV_TITLES`. Tests: `tests/test_clipboard_history_041p.py`.

## 0. Release 0.4.1o — Faster Discord calls

`call_discord_user`: verified `open_discord_contact` → one `_observe_call_state` → `press_in_discord(hwnd, "ctrl", "oem_quote")` → `_call_state_after` (one look). Only if still idle: locate the phone once and click once. Tests: `tests/test_036_discord_call.py`.

## 0. Release 0.4.1n — Fast Discord control

`luxai/discord_shortcuts.py`: `SHORTCUTS` (official Discord keys, RU/RO/EN patterns, `navigation` = usable by the visual AI), `detect_discord_shortcut` (needs "Discord" or Discord in the foreground for `FOREGROUND_ONLY_OK`; skips audio, messages, questions, negation, compound/click requests), `press_in_discord` (verified focus + VK keys), `detect_discord_status_request` / `discord_quick_status` (one capture, one vision call), `DISCORD_LAYOUT` (user's ClearVision map, added to mic/headphones/visual-reasoner prompts). `main._dispatch_command` routes them right after `protected_workflow` (manual saved commands still win). Mic/headphones press Ctrl+Shift+M/D after reading the state (click is the fallback). Visual reasoner action `discord_key`. Tests: `tests/test_discord_fast_041n.py`.

## 0. Release 0.4.1m — Breaks like Luxify

`ExtensionsRuntime._tick_breaks` (5 s) keeps `break_active` per kind (eyes/stretch/water) for real activity only (idle < 60 s); idle ≥ 5 min, a locked PC or a > 2 min tick gap resets. Due kinds queue in `_break_due`; `_break_silence` (quiet hours, quiet mode, full screen, calls, `notifications.windows_do_not_disturb`) delays them and one card shows 30 s after silence ends. `BreakCard` (no focus) answers done/later/skip; `break_stats` lives in `extensions_meta.breaks_today`. Settings view: `ROW_GROUPS`, `SECTION_NOTES`, `BASIC_ACTION_ROWS`. Tests: `tests/test_breaks_041m.py`.

## 0. Release 0.4.1k — Scroll assist

`luxai/scroll_assist.py` (`ScrollAssist.install()` in MainWindow) is an application event filter: middle-click autoscroll with an anchor marker, left-drag on empty backgrounds (never on buttons/fields/lists/sliders or the window header), and PageUp/PageDown/Home/End when not typing. Scroll handles use `$barhandle` (computed in `build_styles`). Tests: `tests/test_scroll_assist_041k.py`.

## 0. Release 0.4.1j — Embedded command editor

`CommandsPage` holds a `views` stack (library / editor). `_open_editor` embeds the existing `CommandEditor` (`set_embedded`: Qt.Widget flags, own header hidden, no window dragging) and saves on `finished(Accepted)`; `editor_title_changed` drives `MainWindow._update_commands_header`, and the header back arrow (`_header_back`) calls `editor_back()` (reject). Tests: `tests/test_embedded_editor_041j.py`.

## 0. Release 0.4.1i — Folder attachments and pypdf 7

`chat_attachments.load_folder` builds a read-only "folder" attachment (tree + text files, shared budget, depth ≤ 6, ≤ 400 entries, ≤ 8 MiB read; skips links/junctions, heavy tool folders and secret-looking names). `load_attachment(s)` route directories there. The PDF worker uses `pypdf.overwrite_configuration` when available (pypdf ≥ 7 raises DeprecationError for the old filter constants). Tests: `tests/test_folder_attachments_041i.py`.

## 0. Release 0.4.1h — Translate before reading

`luxai/translation.py` (no Qt): `text_language` for paragraphs (ru/en/ro/other), `split_chunks` (≤600 chars, sentence aligned — speech reads ≤700 per call), `translate_offline` → `luxai/offline_translate.py` (NLLB-200 600M CTranslate2 int8 in `models/nllb-200-600M-ct2-int8`, downloaded once in the background; `source_language` guesses ru/uk/en/ro/de/fr/es/it/pt/pl; targets ru/en/ro; one batch item per sentence). Since 0.4.2j it is the ONLY translator: no cloud, no GGUF translation. 0.4.2k: `Update.py` runs `python -m luxai.offline_translate` (pinned `REVISION`, SHA-256 of model.bin/tokenizer.json); chat «переведи/tradu/translate …» → `luxai/chat_translate.py` `parse_request` + `ExtensionsRuntime.handle_translate_request`, voice language via `take_reply_language` in `main.py`. `ExtensionsRuntime.read_text` translates and queues piece by piece in a worker (generation counter cancels on a second press; waits when the speech queue is ≥5). Notifications: foreign bodies are translated in a thread and arrive via `_notif_ready`; the app prefix is kept. Tests: `tests/test_translation_041h.py`.

## 0. Release 0.4.1g — Startup checks and streaming Fish

By the user's explicit request, `MainWindow._startup_ai_checks` (3 s after start) runs the cloud check and ONE tiny isolated GGUF reply when `inspect_local_ai` says "available", so the local status turns "success". Fish: `fish_tts.synthesize(on_chunk=...)` hands over PCM while downloading; `voices._PCMStreamPlayer` plays it on its own thread after a 0.25 s pre-buffer and is aborted by `stop_speaking`; the old whole-file path remains when no chunks arrive. `VoiceManager.prepare` for Fish warms modules, the 24 kHz output device and a TLS handshake (`warm_up_connection`) — still no text, key or request at startup. Tests: `tests/test_startup_checks_041g.py`, `tests/test_fish_voice_playback.py`.

## 0. Release 0.4.1f — Real-PC fixes

Never send letter shortcuts through pyautogui directly: with a Russian layout VkKeyScan("c") is -1 and nothing is sent. Use `luxai/keys.py` (`press`, `release_modifiers`); `MainWindow` calls `keys.patch_pyautogui()` so existing `pyautogui.hotkey/press` callers use virtual keys for letters/digits/F-keys. `dictation.transcribe` rejects audio with < 0.25 s voiced (`voiced_seconds`) before Whisper. Notification reader reads every non-system app by default. Tests: `tests/test_keys_layout_041f.py`.

## 0. Release 0.4.1e — Notification reader

`luxai/notifications.py` (no Qt) reads the Windows notification database (`wpndatabase.db` under LOCALAPPDATA) read-only (always close connections), primes to the newest row, parses toast XML, cleans text (links/codes), groups, checks quiet hours, lock state and mic/camera use by other apps (registry CapabilityAccessManager; python/LuxAI/Luxify ignored), and parses voice requests. `ExtensionsRuntime` polls every 2 s, keeps at most 20 texts in memory only, holds missed ones for «что пришло», and exposes `handle_text_request` (notifications, then timers) used by `MainWindow.run_command`. Tests: `tests/test_notifications_041e.py`.

## 0. Release 0.4.1d — Converter circle

`luxai/converter.py` (no Qt) holds image ops (Pillow) and audio/video ops (PyAV, bundled with faster-whisper: libmp3lame, aac, flac, libopus, libx264; GIF via Pillow). Every op writes a new uniquely named file. `luxai/ui_convert_circle.py` has `RadialMenu`, `RegionSelector` (primary screen) and `CropDialog`. `ExtensionsRuntime.start_convert_circle` reads the Explorer/desktop selection by sending Ctrl+C and restoring the clipboard, or uses a copied image; `run_conversion` works in a thread and reports via `convert_done`. Section `groups` render a two-column switch grid. Tests: `tests/test_converter_041d.py`.

## 0. Release 0.4.1c — Timers and alarms

`luxai/timers.py` (no Qt) parses RU/RO/EN timer/alarm/cancel/list requests and stores timers in `.luxai_data/timers.json` atomically. `ExtensionsRuntime.handle_timer_request` replies and manages them; `_check_timers` (1 s QTimer) rings due ones via tray, speech, repeating beeps and `RingDialog` (Snooze/Stop). `MainWindow.run_command` calls it after wizard/pending-task handling and only when no saved command matches (`_saved_command_matches`). Tests: `tests/test_timers_041c.py`.

## 0. Release 0.4.1b — PC Control (Telegram)

`luxai/telegram_control.py` owns Bot API calls (HTTPS to api.telegram.org only, no redirects, token scrubbed from errors), menus with short callback tokens and the polling/sending threads. Token: DPAPI provider "telegram" (`secure_keys`), setting kind "secret" is never stored in config. `ExtensionsRuntime._on_pc_update` enforces owner-only access (no owner → reply with sender ID only; strangers → silence), exposes only enabled non-agent saved commands and confirms `ask_before_run` in Telegram. `MainWindow.run_command_entry(entry, origin=...)` runs remote commands without switching pages; `_finish_command_group` reports results through `remote_command_finished`. Tests: `tests/test_pc_control_041b.py`.

## 0. Release 0.4.1 — Smart dictation

`luxai/dictation.py` owns recording (`Recorder`), Whisper transcription (reuses `MainWindow.dictation_model()` = the running listener's model, else loads its own once), spoken punctuation, voice-trigger parsing, right-Ctrl double-tap polling (`DoubleTapDetector`, no hooks) and typing (Unicode SendInput + real Enter). `DICTATION_ACTIVE` must stay set from the start of recording until the text is typed: `VoiceWorker`'s capture gate checks it so dictated words never reach command routing. The flow lives in `ExtensionsRuntime` (`start_dictation`/`stop_dictation`/`handle_voice_request`); `MainWindow.handle_voice` calls `handle_voice_request` after wake-word handling. Tests: `tests/test_dictation_041.py`.

## 0. Release 0.4.0 — Extensions

The navigation rail has a sixth entry, **Расширения** (`puzzle` icon). Page indices stay stable: stack index 5 is `luxai/ui_extensions.py::ExtensionsPage`; `NavigationSidebar.NAV_ORDER` only changes the visual position (after Addons). `extensions_catalog.py` (no Qt) owns the 22 plugins, 5 topics, settings schemas, validation and `normalize_state`; state lives in `config.json["extensions"]` and must never contain secrets (tokens go to DPAPI `secure_keys` when those runtimes are built). `extensions_runtime.py` runs the *ready* plugins (read_aloud, clipboard_history, quick_inserts, breaks, media_keys, converter, screenshots, downloads_cleanup) with its own `WindowsHotkeyListener`. Plugins with `ready=False` keep a locked switch marked "Скоро"; to ship one, implement it in the runtime, set `ready=True` and add tests. Clipboard history stays in memory; downloads cleanup always previews/confirms and only trashes old installers. Tests: `tests/test_extensions_040.py`.

## 0. Patch 0.3.9.e

The maintainer corrected `version.txt` from `0.9.3.d` to `0.3.9.d` in main commit `3a8bfaa`; continue with `0.3.9.e`. Fish Audio is an explicitly selected optional TTS provider (`voice_engine: fish`), separate from LLM providers. `fish_tts.py` owns the fixed HTTPS endpoint, strict public voice ID/link parsing, bounded PCM synthesis and WAV wrapping. The linked Russian Jarvis default is `4c3eaacc1a0545cdb0295bfddf3e3785`. Always send the literal `model: s2.1-pro-free` header: the documented omitted/unknown-header fallback is PAID `s2.1-pro`. Do not add paid fallbacks, startup synthesis or automatic cloud voice selection. Read current official API pricing before changing the free model; service terms and limits can change.

Fish keys use the existing Windows DPAPI path or `FISH_API_KEY`, never `config.json`, logs or chat-provider configuration. Settings accept a Fish voice link/ID and commit a secret only after editing finishes. `voices.py` retains the serial speech worker, output volume/speed and cancellation-generation protections; only real playback enables barge-in. Network responses arriving after stop must not play. Request/fixture and native Windows CI checks do not replace a live voice preview with the user's personal key; sound quality and account/voice availability require that preview. The linked website demo uses Drama 3 and can differ from the free S2.1 model.

Regenerate `runtime_cleanup_manifest.json` after final source-only tests/docs edits; verify clean-install imports and personal config/model/command preservation, full Linux/Windows CI, then merge. Piper remains the default local voice; existing data and source-only Markdown/tests behavior stays intact.

## 0. Patch 0.9.3.d

The command workspace has separate personal/agent views; persist source metadata and source-scoped empty groups without migrating or discarding older libraries. `command_transfer.py` owns bounded validated collection/file round trips, selected-scope exports, fresh disabled imported identities and atomic writes. `ui_command_tree.py` owns theme-aware branch drawing so Windows does not paint native green hover rectangles. The Addons local AI card is read-only; keep model picking in Settings. Distinguish file/backend readiness from actual worker inference success, bind health to model identity, ignore stale results and never load a model merely to show its status. Runtime health tracking must not expose private prompts or paths. Regenerate cleanup hashes after final tests/docs changes and merge only after full Linux/Windows CI.

Group names are unique across folders/collections within a tab, ignoring case. Older libraries can contain aliases because membership uses only a category string. Export disambiguates their group metadata without rewriting the source and keeps every command once, under the first exact-name group already used by the UI; import maps distinct original spellings separately. Local model health keys resolve Windows short/long paths and normalize case before comparing file metadata.

## 0. Patch 0.9.3.c

Continue from published 0.3.9b; the user explicitly requested version string `0.9.3.c`. The chat composer supports local clipboard files/images and compact previews. Keep clipboard staging cleanup limited to app-owned temporary images, never selected originals; Send remains the cloud-sharing boundary. Default command edits and tombstones belong in the personal registry, never in shipped preset definitions. Customized presets run through `_execute_registered`; untouched presets keep native routing priorities. Obsolete/deleted preset phrases must be checked by `disabled_match` before broader native/AI routes. The Commands menus follow the supplied Luxify order and folder removal preserves children. Maintain allowlist validation, confirmation, secure settings/model handling and source-only cleanup catalog regeneration after final edits.

## 0. Patch 0.3.9b

The screenshot-led Commands workspace in `luxai/ui_commands.py` now has a nested default library and a right-side toolbar with working JSON import/export and persistent user folders/collections (metadata in `luxai/command_registry.py`). User actions belong on each command's three-dot/hover/right-click menu. Imports are allowlist-validated and disabled initially. `luxai/ui_chat_composer.py` provides the expanding multiline chat prompt; `main.py::build_chat` places file previews before that prompt. The editor in `luxai/ui_command_editor.py` uses a two-column form + review layout, with buttons in the right column. RecordingOverlay is a QDialog with ApplicationModal modality: the previous QFrame could not accept clicks over a modal editor. Always preserve Windows input exclusions, secure key handling and command validation. Test native recorder and visual fidelity on an actual Windows desktop in addition to CI.

## 0. Patch 0.3.9a

`luxai/default_commands.py` now owns built-in commands, separate from persistent user entries in `.luxai_data/commands.json`. Their grouped UI is in `luxai/ui_commands.py`. The chat composer lives in `main.py::build_chat` and `luxai/ui_attachments.py`. The editor in `luxai/ui_command_editor.py` has immediate info help, a navigation rail and a standalone recording Stop/Cancel overlay. Manually created/recorded macros can exceed eight actions; the action allowlist, human review and sensitive-operation confirmations remain mandatory, and automatic cloud-generated plans have independent budgets. Verify the Windows native hooks on a real PC in addition to CI.

## 1. What this project is

LuxAI Local is a Windows desktop Jarvis assistant. It listens for voice commands; performs allowlisted Windows actions; starts local apps (including Discord and Steam); interacts with a foreground desktop window through mouse/keyboard and optional AI screenshot analysis; provides a PySide6 UI, command editor, voice diagnostics, and optional online/cloud AI planning. It also supports local GGUF-based chat as a fallback, optional Piper/TTS, Whisper speech input, screenshots/OCR, online research, and tasks with verifiable results.

**Important separation:** A language model does not itself click or know the user's current screen. A *local* tool must perform the action; another observation must prove the result. Sending a click does not mean the requested state changed. For unfamiliar tasks, the planner selects bounded tools. Never report an action as successful without appropriate evidence.

## 2. User priorities and behavior rules

- The user speaks Romanian and Russian. The Jarvis UI is mainly Russian.
- User wants natural commands, not dictated internal steps. Example: **«Открой Steam и скажи какой у меня там никнейм.»** should automatically open/focus Steam, inspect the signed-in account name, and answer. They should NOT need to say “take a screenshot” first.
- User wants fast direct keyboard and mouse commands, for example **«Нажми на клавишу W»**, **«Нажми на Q»**, clicks and hotkeys. Simple explicit allowlisted input should not be routed to generic planning and should not display repeated confirmation prompts. Use the verified foreground external window.
- User's custom Discord has the signed-in account bar at the bottom-right, not necessarily bottom-left. The mic and headphones are *different* adjacent controls; mic button coordinates in an earlier 1368×683 screenshot were approximately (1215,641). **Never hardcode these coordinates.** Read actual current screen/window geometry and use fresh high-resolution crops.
- Specific Discord requests: disable/enable microphone and disable/enable headphones (deafen); read back the resulting icon state. User reported that the headphones were successfully disabled but Jarvis incorrectly said the result was unverified.
- User wants replies **brief**, but global short-response behavior has NOT been comprehensively implemented yet. A specific nickname answer can be concise.
- Preserve other existing features and commands. Do not “simplify” by deleting original workflows or broadly loosening security rules. For screenshots uploaded to cloud, keep session consent. Messages, system changes, file deletion and command execution must retain their proper safeguards.
- Work inside the existing GitHub repo; run full CI and publish completed updates to \`main\` so \`Update.bat\` receives them. Do not declare published merely because a branch/PR exists.

## 3. Version history and current status

- **0.3.9:** Chat supports explicit attachments (text/code/CSV/JSON/Markdown, image, PDF, DOCX), local previews and asynchronous bounded reads. Only Send may share selected snapshots with configured cloud AI; local image handling is OCR, not vision. `attachment_chat.py` requests answers/reviewable edits without tools or model-selected paths. `ui_attachments.py` requires explicit edit review/apply/export; `chat_attachments.py` validates original identity/content, backs up originals and applies text or compatible same-paragraph DOCX changes. PDF/structural DOCX changes export text copies. Commands use the rebuilt grouped editor, phrase/optional-word chips, ordered actions, voice/hotkey/schedule/app/headphone triggers, Windows action recording, AI proposals, test phrase/Run now, ask-before-run and chaining; maintain the eight-action allowlist and prior command compatibility. `command_triggers.py`/`command_recording.py` own native hooks; runtime triggers require Jarvis running and real-device behavior still needs target-PC verification. MainWindow persists `ui_sidebar_collapsed` via a dedicated config save; `set_collapsed(bool)` is silent and only toggles emit `collapsed_changed`. Remove only the Screenshot/OCR Addons cards, retaining handlers/commands/setup. `i18n_skip` protects user-display text while new application-owned labels follow RU/EN/RO. All Markdown/tests remain GitHub-only; regenerate the cleanup catalog after final edits.
- **0.3.8c:** All bundled `.md` files are source-only, including README/user guides/changelog/voice instructions. No runtime code reads them. `Update.py.is_development_file` filters Markdown case-insensitively; `runtime_cleanup_manifest.json` catalogs known repository bytes so installs/upgrades remove only unchanged bundled copies. Personal/edited Markdown and Git checkouts stay untouched. Keep `luxai/assets/icons/lucide/LICENSE` and `README_RO.txt` installed. Regenerate the catalog with `python tests/build_runtime_manifest.py` after all final source/docs/test edits.
- **0.3.8b:** `OrbVisual` uses a visible/enabled 16 ms timer, monotonic elapsed time, floating-point geometry and smoothed microphone/listening/playback reactions. MainWindow connects actual `voices.barge_in_ready` through a UI-thread playback probe; silent warmup is not speech. Runtime distribution excludes tests/CI/development Markdown, retaining GitHub sources and user guidance. Cleanup uses known source hashes to preserve edits/user additions and rejects legacy backups containing protected settings/models. See updater distribution regressions and avatar animation/integration tests.
- **0.3.8a:** Design update: `ui_window_chrome.py` owns integrated native move/resize + window controls; microphone is LEFT above cards (user corrected initial right instruction). HomePage.detach_avatar reparents the original orb behind the full-height MainContent with reserved HeroSpace. `ui_preferences.py` provides responsive theme/language segments and real accent/background swatches; `ui_background` is validated optional hex. Settings use rounded switches/readouts and auto-save; no fake premium/blur controls. `ui_i18n.chat_author` renders canonical history authors without changing stored tuples or body text; UI languages remain separate from ASR/replies. Piper/Windows short labels. Manual engine button removed; launch_windows silently schedules local_ai_setup --ensure to repair only missing/broken CPU engines under OS lock. Autostart points to launch_windows.py. Engine progress is read-only and environment-bound; GGUF weights remain selected by user.
- **0.3.1:** Discord intent improvements, updated UI icons and regression fixes.
- **0.3.2:** clearer screenshots, 2-pass native high-resolution visual target detection; real physical Windows coordinates (DPI/multiple monitors) and stale-window checks.
- **0.3.3:** natural Steam self-nickname interpretation and a dedicated Steam account-bar screenshot reader.
- **0.3.4:** Discord microphone close-up targeting, direct local keyboard/mouse commands, named Discord contact navigation, extra tests.
- **0.3.8:** RU/RO/EN command normalization and intent parity, including polite/diacritic/inflected forms, Discord mic/headphones/calls/contacts and direct input. `steam_games.local_game_request` recognizes complete known-game launch/close requests; MainWindow sends these and typed system-volume requests to a preapproved local worker before generic planning. War Thunder uses Steam AppID 236390 and verified aces.exe/window identity; graceful close is checked, never force-kills Steam. Theme palette reaches orb/switches/branding/history. Header status is hidden, active progress appears transiently inside both chats. Settings percentages and scroll-synchronized section navigation are tested with Qt interaction. Pending appearance edits apply before commands. Includes all 0.3.7g features below. Corpora use 10–15 variants per tested intent/language, with negative/quoted/compound regressions; physical ASR/game behavior still requires the user's PC.
- **0.3.7g:** Successful updater exits automatically; ordinary rollback is temporary, recognized old updater backups are cleaned after success/already-current checks, failed-rollback originals remain recoverable. A legacy batch can retain its already-parsed pause once. `VoiceManager.prepare`/`warm_up_voice` prepare the selected Piper voice silently on the existing speech worker at startup; Windows SAPI remains per-reply. Sidebar reads installed `version.txt` beneath collapse in both widths. Tests: `test_speech_startup.py`, `test_voice_startup_prepare.py`, `test_sidebar_version.py`, updater regressions.
- **0.3.7f:** Cloud verification uses configured timeouts and bounded same-endpoint 502/503/504 recovery (`cloud_http.py`); 503 is a service issue, not proof of invalid credentials. API results are bound to exact key/provider/model/endpoint; health checks persist the actually tested Gemini model. Settings auto-save only updates appearance/language when needed. Key deletion/source reporting, microphone host identity and English headphones on/off parsing are corrected. Dedicated regressions in `test_cloud_http_reliability.py`, `test_cloud_check_context.py`, `test_settings_key_lifecycle.py`, `test_microphone_picker_identity.py`, `test_settings_apply_efficiency.py`, `test_headphones_intent_boundaries.py`.
- **0.3.7e:** Microphone settings list only one preferred Windows host API (WASAPI) instead of every PortAudio backend. Friendly display labels do not alter the actual selected name/host/index; safe legacy matching and scan-time signal blocking. Tests `tests/test_patch_037e_microphone_picker.py`.
- **0.3.7d:** Hardens Settings auto-save: draft API keys are excluded from unrelated preference saves and stored only after finishing editing or an explicitly successful API test. No Save button; restart Jarvis after `Update.bat` to replace an old running UI. Tests `tests/test_patch_037d_settings_autosave.py`.
- **0.3.7c:** Settings save automatically via `SettingsPanel._setup_autosave` and `QTimer` (550ms debounce). The explicit Save button is gone. `MainWindow.apply_settings` remains the single persistence/apply path; `mark_auto_saved` avoids duplicate writes, `show_page` and `closeEvent` flush pending edits. API key changes commit only when editing finishes. Tests `tests/test_patch_037c_settings_autosave.py`.
- **0.3.7b:** Settings → System no longer shows Tesseract OCR executable Browse, section or installation status. OCR is bundled/installed automatically and keeps existing config and all OCR commands; `MainWindow._ocr_setup_worker` and `ocr_setup.py` remain active. Test `tests/test_patch_037b_ocr_settings.py`.
- **0.3.7a:** HomePage removes the three extra action buttons but RETAINS all four toggles, volume and mic meters. MainWindow no longer wires removed buttons; microphone diagnostics remain in Settings; screen inspection/selected-text commands remain available. Regression test: `tests/test_patch_037a_home_cleanup.py`.
- **0.3.7:** first-attempt Discord voice calls handle strict whole-name Cyrillic speech to Latin display transliteration only within call confirmation; verified actual DM header still required. Home UI switches use full painted QCheckBox hitButton area. Tests: `tests/test_037_discord_alias_home_switch.py`.
- **0.3.6:** dedicated one-command voice calling of explicitly named Discord users with verified individual DM, voice-only phone button, exactly one click and fresh call-state confirmation; see `luxai/discord_call_visual.py` and `tests/test_036_discord_call.py`.
- **0.3.5:** planned/fixed Discord headphones (deafen) state observation using before/after screenshots plus enlarged verification; Steam nickname command priority regression and project handoff documentation. **Verify \`version.txt\` and GitHub Actions before claiming the release is merged.**

See \`CHANGELOG.md\` for other releases and \`README.md\` for current user instructions. The current source is the final arbiter if this text and code diverge.

0.3.8 ASR investigation: the friend already used Romanian/Auto, so do not diagnose this as an unchanged Russian setting. Real local Whisper Small inference on Piper-generated RO/RU/EN audio exposed short Romanian failures in unprompted beam-1 Auto. A trilingual command prompt plus minimum beam 3 improved the five selected comparison examples; beam 3 alone did not. Auto remains automatic language detection, explicit RU/EN options are preserved, and repetitive hallucinations are filtered before dispatch. Synthetic tests are not headset validation; names such as Hanzo and mixed-language titles still had failures in some synthetic samples. Do not add guessed contact aliases to compensate for uncertain audio.

## 4. Top-level repository files

| Path | Responsibility |
|---|---|
| \`main.py\` | MainWindow, PySide6 signal connections and pages, listening state, command queue/routing, direct actions, workers/results, cloud screenshot approval and verification messages. Usually the first file to trace for an incorrectly routed command. |
| \`launch_windows.py\` | Python startup wrapper, error handling, startup logs. |
| \`run_windows.bat\` | Launch application in installed virtual environment. |
| \`install_windows.bat\` | Install/repair Python environment. Calls \`scripts/install_windows.ps1\`. |
| \`scripts/install_windows.ps1\` | Windows Python discovery, fallback, dependency installation and diagnostics. |
| \`Update.bat\`, \`Update.py\` | Downloads latest GitHub \`main\` commit (archive), safely stages, validates and installs code/dependencies while preserving user data. Not a PR downloader. |
| \`requirements.txt\` | Python dependencies. |
| \`version.txt\` | Single displayed release number; bump only in a tested release. |
| \`config.json\` | Default/local configuration. May include device settings and paths; don't disclose or overwrite user settings on update. |
| \`updater_config.json\`, \`manifest.example.json\` | Update/manifest metadata examples. |
| \`README.md\`, \`README_RO.md\`, \`README_RO.txt\` | Usage, install and Romanian documentation. |
| \`COMMANDS.md\`, \`VOICE_TOOLS.md\`, \`ONLINE_AI.md\` | Action editor/voice commands, specialized voice tools and cloud setup/safety. |
| \`CHANGELOG.md\` | Historical changes. |
| \`diagnose_windows.bat\` | Visible startup debugging. |
| \`.github/workflows/routing-check.yml\` | Main multi-platform test workflow; Linux offscreen Qt + Windows Python matrix, packaging and local-model checks. |
| \`.github/workflows/ocr-windows.yml\` | Windows OCR workflow. |

## 5. The \`luxai/\` package — where to look

### Routing, tools and AI

| Files | Purpose |
|---|---|
| \`fast_intents.py\`, \`intent_routing.py\`, \`task_intents.py\` | Simple language-based command detection, application recognition, compound intents and Steam self-nickname detection. |
| \`voice_actions.py\`, \`voice_shortcuts.py\`, \`voice_rules.py\` | Parse explicit spoken keys, click, mouse moves, hotkeys, command variants; prevent ordinary chat going through local executor. |
| \`agent.py\`, \`action_catalog.py\`, \`desktop_actions.py\` | Validate/execute allowlisted local actions; important distinction between requesting input and confirming state. |
| \`desktop_agent.py\`, \`task_agent.py\`, \`adaptive_tasks.py\`, \`task_memory.py\` | Adaptive tool/planner loop, runtime capabilities, evidence, progress, checkpoints. |
| \`online_agent.py\`, \`api_providers.py\`, \`api_verification.py\`, \`model_json.py\`, \`gemini_models.py\` | Cloud provider adapters, planner API calls, JSON responses, provider key/model validation. |
| \`macro_planner.py\`, \`command_registry.py\`, \`command_wizard.py\`, \`agent_experience.py\` | Saved/learned commands, validated generated macro actions, user command creation, local experience hints. |
| \`local_shell.py\` | CMD/PowerShell allow/confirmation/verification policy; never bypass this with arbitrary mouse/keyboard actions. |

### Visual/Windows operations

| Files | Purpose |
|---|---|
| \`visual_click.py\` | Foreground window capture, physical Windows geometry (DWM), normalized-to-desktop coordinate mapping, fresh 2× screenshot crop, safe native click. |
| \`visual_reasoner.py\` | Generic bounded observe → choose → act → verify workflow, screenshots and independent final state verification. Do not use this generic verifier for sensitive Discord-specific toggles if a dedicated exact state reader exists. |
| \`screen_interact.py\`, \`screen.py\`, \`ocr_setup.py\` | Foreground HWND and process checks, UI/screenshot and OCR mechanisms. |
| \`windows_apps.py\`, \`windows_control.py\`, \`win32.py\`, \`windows_volume.py\` | Native application discovery/activation, system calls and volume controls. |
| \`selection.py\`, \`file_actions.py\`, \`websites.py\`, \`web_research.py\` | Selected text, safe filesystem actions, browser navigation/research. |
| \`discord_mic_visual.py\` | Dedicated screenshot-grounded mic toggle (not the headphone icon), bottom-account-bar crop, high-res close-up, visible mute state, one click, post-click check. |
| \`discord_headphones_visual.py\` | **0.3.5:** Dedicated headphones/deafen state. Check red slash on headphone icon; before/after screenshot plus close-up verification; never click twice merely because verification is uncertain. |
| \`discord_screen_review.py\`, \`discord_window_state.py\`, \`discord_search_guard.py\` | Ensure real foreground Discord window, validated screenshots and search. |
| \`discord_navigation.py\`, \`discord_contact_vision.py\` | Find named Discord contact, verify correct chat header. |
| \`discord_research.py\` | User-specific message research and send workflow with recipient/content safeguards. |
| \`voice_desktop.py\` | Discord microphone intent modes plus local screen reading and shortcut routines. |
| \`steam_profile_visual.py\` | Open/focus installed Steam, read signed-in nickname from top account bar, second native resolution crop and match check. Do not substitute a friend's name or a previous screenshot. |
| \`steam_games.py\` | Recognized Steam game launch and App IDs. |
| \`research_notepad.py\` | Sources → Notepad facts workflow. |

### Interface, audio and models

| Files | Purpose |
|---|---|
| `chat_attachments.py`, `attachment_documents.py` | Bounded explicit-file snapshots, text/image/PDF/DOCX extraction, validated review proposals, stale-file checks, backups and safe apply/text-copy export. Never execute attached content or accept model-selected paths. |
| `attachment_chat.py`, `ui_attachments.py` | Tool-free attachment analysis worker, provider-native image blocks/local OCR, local preview/tray and explicit edit-review dialogs. Selection is local; cloud delivery occurs only through Send. |
| `ui_command_fields.py`, `command_triggers.py`, `command_recording.py` | Wrapping phrase chips, application-runtime schedule/event/hotkey dispatch and bounded supported Windows action recording. Review recorded/generated actions before saving or running. |
| \`ui_home.py\`, \`ui_sidebar.py\`, \`ui_commands.py\`, \`ui_command_editor.py\`, \`ui_action_picker.py\`, \`ui_screen_assist.py\`, \`ui_i18n.py\`, \`styles.py\`, \`icons.py\`, \`settings_panel.py\` | PySide6 UI pages, actions, controls, translations, icons and themes. Assets: \`luxai/assets/icons/\`. |
| \`voice.py\`, \`audio_devices.py\`, \`voice_files.py\`, \`voice_presets.py\`, \`voices.py\` | Audio recording, Whisper, device selection and TTS. |
| \`local_models.py\`, \`gguf_backend.py\`, \`gguf_worker.py\`, \`local_ai_setup.py\` | Optional local GGUF engine, setup and isolated inference. |
| \`secure_keys.py\`, \`cloud_status.py\` | DPAPI-protected per-provider API credentials and cloud connection status; never commit keys. |
| \`diagnostics.py\` | Local device/runtime reporting without raw keys or conversation contents. |
| \`response_language.py\`, \`weather_service.py\` | Russian/Romanian/English response language and weather requests. |

## 6. Command execution pipeline

1. Microphone/VAD/Whisper transcribes speech (see \`voice.py\`, \`main.py\`).
2. \`MainWindow.run_command(text)\` handles queue, stop/dictation, saved command wizard and conversation state.
3. \`MainWindow._dispatch_command()\` chooses a **complete goal**: dedicated high-confidence intents first, then saved user macros / local allowlisted actions / adaptive agent as appropriate.
4. Examples:
   - \`"Нажми на Q"\` → \`voice_actions.parse_action_sequence\` → \`_run_direct_input\` → \`agent.execute_plan\` → \`desktop_actions.execute_desktop_step\`. No generic LLM for this.
   - \`"Выключи микрофон в Discord"\` → \`voice_desktop.discord_mic_visual_mode\` → \`_start_discord_mic_visual\` → \`discord_mic_visual.click_discord_microphone_by_screenshot\`.
   - \`"Выключи наушники в дискорде"\` → \`discord_headphones_visual.discord_headphones_mode\` → dedicated worker → \`set_discord_headphones\`. Read RED SLASH on headphones, not the mic.
   - \`"Открой Steam и скажи какой у меня там никнейм"\` → \`task_intents.steam_self_nickname_request\` → \`_start_steam_profile_lookup\` → \`steam_profile_visual.read_own_steam_nickname\`. It must stay ONE task even if compound.
   - Click user in Discord → \`discord_navigation.detect_discord_open_dm\` → verified contact-navigation process, independent active chat header check.
   - Other valid complex goals → \`desktop_agent.CloudTaskDecider\` + \`task_agent.run_task\`; native app open, consented visual task, research, shell and bounded input tools.
5. After an action, verify an actual observable state, not the planner's belief or that Windows accepted a click. No infinite clicking.
6. Qt signals in \`main.py\` send worker results back to the UI; do not update Qt widgets directly from a worker thread.

## 7. Discord state verification: special considerations

- Bottom-right custom theme account bar contains: user/avatar, gamepad, **microphone**, dropdown, **headphones**, dropdown, settings.
- Headphones/deafen icon often becomes red and diagonally slashed when switched off; headphone state is independent of microphone state.
- Only search the *signed-in account bar*, not people in the friends list or channels. Crop the bottom panel, then take a fresh native-pixel zoom.
- If state already equals requested state, do **not** click. If state is unknown or icon mismatch, do not guess.
- One button click maximum per command; check current screenshot after it. On uncertain broad screenshot, zoom the **new** image and reread before reporting failure; zoom is not a second click.
- When verification cannot establish the state, tell the user it could not be confirmed. Do not incorrectly claim the toggle failed; do not claim success without supporting state evidence.
- For microphone, see \`discord_mic_visual.py\` (uses a small downward click adjustment from second-pass estimate). Do NOT transfer a fixed coordinate offset to headphones.
- Local hardware/Windows/Discord themes must be tested manually: unit tests are synthetic and cannot establish accuracy on the user's live screen.

## 8. Steam troubleshooting

Reported earlier: \`"Открой Steam и скажи какой у меня там никнейм."\` mistakenly reached a generic agent result \`"The user has not requested visual work and native opening has not failed"\`. The correct interpretation is **both app activation and visual reading**. Check \`MainWindow.run_command\` for command splitting, \`_dispatch_command\` for early intent precedence, and \`task_intents.steam_self_nickname_request\`. Extend tests for exact ASR phrases. The dedicated reader must:
1. activate/open verified installed Steam, not assume process existence implies a visible window;
2. require screenshot upload session permission if a cloud vision provider is used;
3. read the signed-in user's name only from Steam's top account bar;
4. magnify from **fresh native-resolution** pixels and corroborate transcription;
5. return the real nickname only after confirmation; avoid inventing it.

Never use a random Steam community page or a friend's chat profile for the user's identity.

## 9. Testing and release checklist

- Run \`python -m unittest discover -s tests\` with correct packages installed. On headless Linux for UI tests use \`QT_QPA_PLATFORM=offscreen\`; GitHub Actions config sets up required libs.
- 0.3.9 coverage: `test_chat_attachments.py`, `test_attachment_documents.py`, `test_attachment_chat_039.py`, `test_command_editor_039.py`, `test_command_triggers_039.py`, `test_sidebar_persistence_039.py`, `test_release_039_ui.py` and `test_release_039_localization.py`. Validate fresh runtime cleanup after regenerating `runtime_cleanup_manifest.json`; new source-only tests/docs must be cataloged too. Offline/Qt tests do not replace real Windows hooks, device, recording or cloud-model validation.
- Newly relevant tests: `tests/test_patch_037c_settings_autosave.py`, `tests/test_patch_037b_ocr_settings.py`, `tests/test_patch_037a_home_cleanup.py`, `tests/test_037_discord_alias_home_switch.py`, `tests/test_036_discord_call.py`, `tests/test_035_audio_steam.py`, `tests/test_steam_profile_visual.py`, `tests/test_discord_mic_priority.py`, `tests/test_release_034.py`, `tests/test_visual_reasoner.py`, `tests/test_visual_desktop_macro.py`, `tests/test_task_routing.py`, `tests/test_voice_actions.py`.
- GitHub Actions \`.github/workflows/routing-check.yml\` exercises Linux PySide6/voice/action unit tests, Windows Python 3.11–3.14 and Windows installer/local GGUF probes. Also has Python 3.15/3.16 checks with different support guarantees.
- Verify both **passed** and **failed** job outputs; do not call a PR ready because the first job passed.
- Release procedure: branch from \`main\`; edit smallest set of files; add regression tests; update \`version.txt\`, README, CHANGELOG if used; open PR; run all required CI; merge after green; check \`main/version.txt\`, merge SHA, then verify post-merge CI where possible.
- \`Update.bat\` / \`Update.py\` downloads the latest GitHub **main**, not a branch. User closes Jarvis, runs \`Update.bat\`, then \`run_windows.bat\`. No manual ZIP needed.
- When reporting results to user, distinguish synthetic CI tests from live Windows/Discord/Steam validation. Do not claim the user's PC was controlled by CI.

## 10. Diagnostics and security

- App diagnostics: \`diagnose_windows.bat\`; startup errors in \`logs/startup_error.log\`; installer in \`logs/install_windows.log\`; optional local-model setup may write \`logs/local_ai_install.log\`.
- If tests pass but click misses on the user's screen, request fresh screenshot + visible before/after state and inspect capture/window scaling instead of arbitrarily repeating or hardcoding coordinates.
- Screenshot AI consent is per session. Local screenshots saved without cloud upload are different from sending screenshots to a third-party API.
- Distinguish explicit local keyboard/mouse permission from authorization to send messages, delete files, run arbitrary shell scripts, change security settings or bypass UAC.
- Protect \`.luxai_secrets/\`, \`.luxai_data/\`, user \`config.json\` values, \`.venv/\`, recordings and models. The updater should preserve those.
- For Discord sending, always use the dedicated recipient + text + confirmation workflow, never generic mouse/Enter to circumvent policy.
- For shell actions respect \`local_shell.py\` constraints, task-scoped approval config and independent readback.

## 11. Suggested new-chat starting prompt

> Continue the project at https://github.com/negevshopmd-svg/LuxAI_local. FIRST read PROJECT_HANDOFF.md and inspect latest \`main\` + \`version.txt\` + current CI. Preserve the current design and existing functionality. My request is [describe problem]. Trace \`main.py\` command routing to the dedicated implementation; reproduce with a regression test; make minimal fixes; run all GitHub Actions tests; merge when green, then verify \`main\` version so I can install using \`Update.bat\`. Never guess an on-screen result without a fresh observation.

Keep this document updated when components, important bugs, or release workflows change; it exists to preserve project context across chats.

## Setup window (0.4.2l)

`scripts/setup_ui.ps1` (WPF, UTF-8 BOM required for PowerShell 5.1) reads JSON lines from `-Events` (`plan`, `step`, `detail`, `log`, `bytes`, `done`; texts carry `ru`/`en` beside `text`) and measures internet speed from the network adapters. Producers: `Update.py` (`start_ui`, `ui_emit`, `ui_step`, `ui_detail`, `run_step`, `run_streamed`, `ui_finish`, `close_jarvis`) and `scripts/install_windows.ps1` (`Start-SetupWindow`, `Send-Ui`, `Stop-RunningJarvis`). The batch files skip `pause` when the window was shown (`.luxai_update_ui`, `logs\.setup_ui`). `LUXAI_NO_UI=1` keeps the console; `LUXAI_UI_SNAPSHOT=dir;sec,sec` saves PNGs for checks. Tests: `tests/test_setup_ui_042l.py`.
