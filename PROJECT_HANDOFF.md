# LuxAI Local / Jarvis — Project Handoff and Architecture

> **Purpose:** This file is the authoritative START HERE for a new ChatGPT/Codex chat working on this repository. Read it alongside the actual source code and tests. Do not assume this handoff is newer than \`main\`: always inspect \`version.txt\`, latest commits, and CI status before editing.
>
> Repository: https://github.com/negevshopmd-svg/LuxAI_local  
> OS: Windows 10/11, 64-bit. Python + PySide6. UI and voice responses primarily Russian, with Romanian/English support.  
> Updated for the **0.3.8c work**, 2026-10-27. \`Update.bat\` installs the code merged into \`main\`, NOT an open PR.
> Do NOT include real API keys, private logs, screen captures, model binaries, user audio, or personal paths in Git history.

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
