# LuxAI_local

## 0.3.7f: cloud connection and settings reliability

API checks now use the configured timeout and retry HTTP 502/503/504 once against the same provider. HTTP 503 means the service is temporarily unavailable; it does not prove an API key is invalid. A successful check is tied to the exact key, endpoint and model tested, and a verified Gemini replacement model is saved before reporting success. Temporary model-list failures can still test the explicitly configured Gemini model.

Settings auto-save no longer rebuilds the entire interface for unrelated edits. Microphone selection retains its driver identity after reconnection, and English Discord “unmute/undeafen” commands no longer match their opposite. Close Jarvis, run `Update.bat`, then `run_windows.bat`. A persistent provider outage still requires the service to recover; creating more keys does not fix HTTP 503.

Voice-controlled Jarvis assistant for Windows 10/11 (64-bit).

## 0.3.7e: compact microphone picker (mini-patch)

Settings → Voice input now lists microphones once instead of repeating MME, DirectSound, WASAPI and WDM-KS representations. On Windows, LuxAI prefers the WASAPI input endpoints, falling back to another available recording host API when needed; descriptions use simple names like Discord. Existing selected-device names are matched to the new visible entry when uniquely identifiable. Real device names, host APIs and indices remain intact internally for voice recording, including reconnect handling. A device list refresh does not accidentally trigger settings auto-save. Click **Обновить устройства** or restart Jarvis after `Update.bat` to reload the simplified list.

## 0.3.7d: reliable hands-free Settings persistence (mini-patch)

Settings continue to auto-save without a bottom Save button. Ordinary edits are applied and written to `config.json` after a 550 ms pause, including when you navigate away from Settings or close Jarvis. Draft API secrets are **not** saved because another preference changed while you were still typing: they are committed when editing finishes, or after a successful explicit API key test. Restart Jarvis after running `Update.bat` from this repository's `main`; an already-running older process will continue to display its old controls until restarted. Regression tests: `tests/test_patch_037d_settings_autosave.py`.

## 0.3.7c: automatic Settings save, no Save button (mini-patch)

Settings are now saved to `config.json` **automatically** whenever a real editable control changes: checkboxes, dropdowns, sliders, text and numeric fields. A short 550 ms debounce coalesces typing and slider changes rather than writing on every keystroke. Pending changes are committed when leaving the Settings page or closing/minimizing Jarvis. The old bottom blue **“Сохранить настройки”** button has been removed.

Changes are applied using the existing live `MainWindow.apply_settings` path (appearance, voice, mic, autostart and Home controls). API secrets are saved only when the key field finishes editing or after the existing explicit API test, not per keypress. Settings search and live microphone diagnostics never count as edits. The existing config data and the rest of the application are unchanged.

Install through `Update.bat` after merging to `main`. Regression tests: `tests/test_patch_037c_settings_autosave.py`.

## 0.3.7b: integrated OCR, cleaner Settings (mini-patch)

The redundant "Встроенный Tesseract OCR" setting, external executable picker and OCR installation status row are removed from **Settings → System**. OCR is already integrated and still installs/checks itself automatically at startup or during `Update.bat`, using the bundled Russian and English recognition models. Existing OCR commands, OCR-dependent visual tools, user configuration and automatic recovery are preserved.

Existing optional `tesseract_path` configuration remains compatible but no longer needs a visible text field. Update through `Update.bat` after this patch is merged into main.

## 0.3.7a: Home panel cleanup (mini-patch)

The Home (“Главная”) control panel no longer displays the three extra buttons for microphone testing, viewing on-screen buttons or summarizing selected text. Those tools are **not deleted**: microphone diagnostics remain in Settings; screen inspection and selected-text summary remain accessible through existing voice commands and tools. Prefix mode, quiet mode, avatar animation, always-on-top, volume and microphone meters remain untouched.

Install this minor patch with `Update.bat` once merged to main.

## 0.3.7: first-attempt Discord name matching and reliable control toggles

Discord voice calls now handle a **strict, full-name Cyrillic speech transcription to Latin displayed nickname** (for example Russian ASR "Ханзо" vs the Discord display "Hanzo" or "Khanzo"). This exception is **only for calling**; it never broadens message sending or accepts approximate/fuzzy names. The actual open one-to-one DM header must still be verified before accessing the phone button. Ambiguous and unrelated users remain blocked.

All four custom Qt switches on the home control panel (prefix, quiet mode, avatar animation, always on top) now accept the **first click anywhere on their entire painted 54×28 surface**, including the right-hand knob. This fixes QCheckBox's smaller default indicator-only hit-test. Tests cover the actual mouse event delivery and preservation of config state.

Run `Update.bat` after merging to `main`; see `tests/test_037_discord_alias_home_switch.py`.

## 0.3.6: natural Discord voice calls

Say **“Позвони пользователю Hanzo в Discord”**, **“Sună-l pe Hanzo în Discord”**, or **“Call Hanzo on Discord”**. Jarvis now understands this as one voice-call request: it opens/activates Discord, finds and verifies the individual DM contact, identifies the voice PHONE handset (not the adjacent video-camera button) in the current DM header using a fresh native-resolution zoom, clicks it at most once, and checks the actual ringing/connected call UI before reporting success.

If the DM, button or state cannot be verified, Jarvis stops without blindly retrying or inventing a successful call. Requires a vision-capable cloud AI and the existing screenshot consent. A live call is only initiated when the user explicitly requests it. See `luxai/discord_call_visual.py` and `tests/test_036_discord_call.py`. Upgrading with the existing `Update.bat` works after merging to `main`.

## 0.3.5: verified Discord headphones, Steam intent routing and project handoff

Natural “Выключи наушники в дискорде” uses a dedicated state-aware headphones/deafen action. Jarvis reads the current bottom account bar icon (including the red diagonal slash), clicks at most once if the requested state differs, and checks a fresh screenshot. If the broad screenshot is unclear, a new full-resolution close-up verifies the change instead of triggering a second click.

“Открой Steam и скажи какой у меня там никнейм” is routed as one complete task to the existing consented Steam self-profile reader, ahead of generic desktop planning.

The repository now contains [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md): complete architecture, file map, commands, test/release process and instructions for continuing in another chat. Update with `Update.bat` after this release is merged.

## 0.3.4: Discord mic accuracy and desktop controls

Microphone buttons in customized Discord are localized again using a fresh, enlarged native-resolution crop. The click lands slightly below the icon's detected center, within the same mic button, and the resulting state is checked. Uncertain positions are rejected.

Voice requests for W, Q, allowed hotkeys and mouse actions are routed to Windows input rather than an online planning response. Opening a Discord user's conversation uses verified search and chat-header checks. The adaptive agent can also run input actions that are explicitly part of the user's request.

Local input runs against a foreground external window. Sending screenshots to cloud AI and consequential actions still follow the existing safeguards.

Upgrade normally with `Update.bat`.

## 0.3.3: natural Steam nickname requests

Say **“Можешь зайти в Steam и сказать, какой у меня ник?”** (or **“Can you open Steam and tell me my nickname?”**). Jarvis automatically activates/opens the installed Steam desktop window, obtains the usual screenshot-analysis consent, inspects the signed-in account bar, zooms the identified name at native resolution and checks the answer before reporting it. You no longer have to dictate the intermediate screenshot steps. Friends, chat participants, unrelated profile pages and invisible/background windows are rejected; no Steam account changes or messages are performed. Requires a configured vision-capable online AI and permission to send the window images. The existing `Update.bat` installs this version directly from `main`.

## 0.3.2: sharper screenshots and precise mouse targeting

When an explicitly approved visual action needs a mouse click, Jarvis now uses a clearer screenshot and a second fresh, magnified full-resolution screenshot of the target region. It maps the result back to physical desktop pixels, including multi-monitor layouts with negative coordinates, and checks the target window is unchanged and not covered before clicking. If the two image analyses disagree, it cancels the click rather than guessing; actions still require post-click verification.

To upgrade, close Jarvis, run `Update.bat` and restart with `run_windows.bat`. This updater obtains `main` directly; no GitHub Release or ZIP is required.

## 0.3.1: new icons and natural Discord requests

The interface includes local Lucide SVG icons, a new Jarvis emblem, and icons that adapt to dark/light themes and high-DPI displays. The icon pack works offline; its source revision and ISC license are bundled in `luxai/assets/icons/lucide/`.

Say **“Send Hanzo a Discord message: hello”** or **“А ты можешь написать в дискорде пользователю Hanzo привет”**. Jarvis builds the window/contact/draft/send workflow; missing recipient or message details are clarified without asking you to dictate clicks. It verifies the contact and requests final approval for the actual draft before sending. Hidden Discord/Electron helper windows no longer count as extra visible app windows.

## 0.3.0: adaptive desktop tasks

Jarvis chooses a next tool, observes the actual result, adjusts its next step and verifies the outcome. A request such as **“Open Discord”** uses native Windows application discovery first, without taking a screenshot or requiring a cloud model. Opening is confirmed from a visible foreground window, rather than the existence of `Discord.exe`. **“Take a screenshot”** saves a local image in `Pictures/LuxAI` without an AI key.

For unfamiliar tasks, enable the configured cloud AI. It can plan application actions, request visual inspection, research information and propose local CMD/PowerShell commands. Local execution validates each proposal. By default, `agent_auto_shell: true` authorizes commands for the current task without repeated confirmation, while retaining bounded execution and read-only result checks for changing commands. Set `agent_auto_shell: false` in `config.json` to request approval for each command outside the parsed read-only set. This authorization comes from your configuration, is scoped to the current task and does not bypass Windows permissions or UAC. Existing Discord send confirmation remains in place. Cloud screenshot analysis asks permission once per Jarvis session; local captures need no upload permission.

Explicit requests to shut down, restart, sleep, lock or change the Windows dark/light theme use dedicated local operations. Shutdown/restart has a cancellation delay and does not force applications closed. The native **Night Light** operation opens Windows settings. With visual AI enabled and session screenshot permission, Jarvis can continue through the interface and verify the toggle; opening the page alone never confirms activation. Ambiguous **“night mode”** requests are clarified.

Task checkpoints, answers and verified procedure hints are kept locally in `.luxai_data/agent_memory.json`. A remembered procedure guides the next task and still needs fresh checks; it does not preserve shell approval. Raw commands, screenshots and recordings are not saved as reusable procedure data. Jarvis distinguishes a verified result from an action issued without confirmation, so an uncertain click is not automatically repeated.

Close Jarvis before updating. `Update.bat` downloads `main`; a change available only in a feature branch or pull request reaches the updater after merging. See [CHANGELOG.md](CHANGELOG.md) for the changes.

## 0.2.0: microphone and wireless headset checks

Close Jarvis, run `Update.bat`, and reopen it with `run_windows.bat`. Version 0.2.0 adds an actual capture-status indicator, live microphone level, device refresh, an independent microphone test, and diagnostic export. See [CHANGELOG.md](CHANGELOG.md) for the reliability fixes.

If Jarvis appears enabled but does not hear you:

1. Open **Settings → Voice input** and click **Refresh devices** after connecting your headset. Select its **recording/input endpoint**, commonly named **Headset / Hands-Free**, rather than the stereo playback endpoint. USB wireless headsets can use a different name; choose the endpoint shown as an input in Windows Sound settings.
2. Click **Test microphone** and speak for four seconds. This measures input without loading Whisper or saving a recording. The meter should move. No sound means checking the headset's Mute switch, Windows input level, and **Settings → Privacy → Microphone → Allow desktop apps to access your microphone** (Windows 10); Windows 11 uses **Privacy & security → Microphone**. Another app may hold the device exclusively.
3. If the test receives sound, select the correct recognition language (**Română** for Romanian), save settings, and use **Restart microphone**. The status first reports model loading and shows capture as active only after the driver opens. Initial model download/loading can take minutes; the input test can wait for an in-progress model operation to stop.
4. Increase **Microphone sensitivity** moderately for quiet input. This changes speech detection, not Windows gain. Lower Windows microphone gain if the test reports clipping.
5. If a failure persists, use **Save diagnostics**. The report lists runtime/dependency versions and device status and retains the last microphone-test result; it excludes API keys, conversations, recordings and personal model paths. Device names can identify your headset. A command-line report is also available: `.venv\Scripts\python.exe -m luxai.diagnostics`; append `--microphone --device INDEX` only to explicitly test an input.

The on/off switch expresses your requested setting; the status and meter show actual capture. A working input test confirms audio capture, not Whisper accuracy. Windows 10/11 wireless drivers, headset firmware and Bluetooth profiles still need checking on the actual PC.

## Install on a new computer

1. Download and extract the full repository ZIP.
2. Double-click `install_windows.bat`. It detects an installed 64-bit Python **3.11 or newer** (including 3.12, 3.13, 3.14 and stable 3.15). When none is found, it downloads the **official, digitally signed Python 3.11 fallback** from python.org for the current Windows user. It creates `.venv` and installs `requirements.txt`.
3. After installation reports success, double-click `run_windows.bat`.

An internet connection is required for the initial Python/package downloads and integrated Tesseract OCR. Newer Python versions depend on third-party Windows wheels. The installer chooses the newest *stable* locally available Python, rather than an alpha/beta interpreter, and attempts to install packages and import LuxAI before reporting success. If something fails, it preserves that environment as `.venv.old-*`, retries an older installed Python version, and ultimately offers the official Python 3.11 fallback. Details are logged in `logs/install_windows.log`. On Python 3.14+, the optional WebRTC VAD package is skipped (the microphone uses its built-in RMS fallback). **Python 3.15 is stable as of October 2026**, but LuxAI's speech backend (`faster-whisper` -> `ctranslate2`) currently lacks compatible Windows wheels on 3.15; CI confirms detection and probes dependency availability. The installer will automatically fall back to an older Python (normally 3.14) if 3.15 dependencies are unavailable. **Python 3.16 is an alpha preview** and is not production-ready; it is detected but requires its own third-party wheels before it can run the full application. Python 3.16 is tested on a best-effort, non-blocking CI job, never advertised as fully supported merely because the interpreter starts. OCR is optional, but the Python libraries and successful import check are required.

**Do not copy `.venv` between computers.** It records absolute Python paths. If you already copied it, `install_windows.bat` detects the incompatible environment, renames it to `.venv.old-...` for backup and creates a working environment automatically. `run_windows.bat` offers to repair a missing/broken environment.

If installation fails, send the error message together with `logs/install_windows.log`. Running the installer again is safe; it reuses valid environments and existing installed packages.

Before sharing, leave out `.venv`, `.venv.old-*`, `config.json` with personal paths, `.luxai_secrets`, `.luxai_data`, and any API keys. Do not share private speech models or credentials without permission.

## Update

After installation, use `Update.bat` to download new versions from GitHub. The updater preserves user configuration, local models and secrets. On a new PC without Python, use the installer before the updater.

## Windows 11 startup troubleshooting

LuxAI supports 64-bit Windows 10 and 11 with a functional Python 3.11–3.14 environment (later versions can use the installer fallback). It is tested automatically on Windows Server GitHub runners; actual Windows 11 hardware, audio drivers and permissions may differ.

If double-clicking `run_windows.bat` appears to do nothing, run `diagnose_windows.bat` from the same folder. This starts Jarvis with a visible console and preserves errors in `logs/startup_error.log`. If an import, Qt startup, or configuration error prevents launch, a Windows error dialog points to that file. For dependency or virtual environment problems, run `install_windows.bat` and check `logs/install_windows.log`.

On another computer, always extract a fresh ZIP without a copied `.venv`. Avoid sharing the original `config.json`, which can contain machine-specific model paths and personal settings. Never share API keys, secrets, or complete diagnostic logs without checking for private file paths or credentials.

## Interface languages

Open **Settings → Interface → Interface language** and choose **Русский**, **English**, or **Română**, then press **Save settings**. Menu labels, settings, home controls, command editor and tool panels switch immediately without restarting the program. The preference is saved as `ui_language` in the local `config.json` and restored on next launch.

Interface language is separate from **Voice input → Recognition language** (the existing `language` setting). Changing interface text does **not** change Whisper transcription, spoken answers, custom command phrases, API keys, or user-entered fields. Free-form agent responses, user-provided command names and third-party error messages remain in their original language.

## Local model and multilingual speech troubleshooting

The built-in keyboard/mouse commands and quick conversation replies work without a local GGUF library. The offline GGUF **chat model** is optional. If your app previously displayed `No module named 'llama_cpp'`, update to the latest version and run `install_local_ai.bat` to attempt installing the official prebuilt CPU wheel into **LuxAI's own .venv**. This helper does not compile native code and reports clearly if no wheel is available for your Python version. The main installer still does not require the large GGUF backend. Choose a different supported Python environment or cloud model if a wheel is unavailable. Do not copy a .venv between computers.

Under **Settings → Voice Output**, select **Jarvis reply language**: Automatic (follows voice recognition), Русский, English or Română. This controls response text and Piper speech. Selecting Mihai or Lessac in **Assistant voice** also selects Romanian or English reply language. The interface language and microphone language remain independent; switching interface labels alone does not change the spoken language. Normal greetings (including “Hello, Jarvis”) work without a local LLM or API key. Some legacy macro/tool responses can still contain untranslated Russian text; these should be updated independently rather than inaccurately translated or spoken using a mismatched model.

## Local models, Romanian microphone accuracy, stability

Place GGUF files in `LuxAI_Local/models/` (subfolders are supported). Open **Settings → AI Provider → Models in models folder** and choose a model; use **Refresh model list** after copying files. The selector shows all .gguf files, disables invalid/incomplete entries, and restores a previously selected model if the same unique filename was moved from another PC. Previously selected external model paths are still supported. Saving settings persists this selection.

The model status under the selector reports invalid files or the optional `llama-cpp-python` dependency missing. Run `install_local_ai.bat` after `install_windows.bat` when using local GGUF chat. It does not magically make a huge model fit in RAM. **GGUF chat now runs in an isolated CPU subprocess** instead of loading native llama.cpp into the Qt/audio process. This protects the main app from many native GGUF crashes, but the local model is loaded per request and therefore replies may be slower; try a smaller quantized model if RAM is limited.

For better Romanian transcription choose **Settings → Voice input → Recognition language: Română**, recognition model **Medium** (if sufficient RAM/CPU, approximately 1.5 GB initial download), and accuracy **Balanced** or **More accurate**. The Small model requires fewer resources. On supported systems, audio capture now falls back from 16 kHz to the device's own sample rate and resamples to 16 kHz for Whisper. The mic uses Romanian vocabulary hints and a stronger beam on Romanian speech. Actual recognition accuracy still depends on recording quality and microphone position.

Shutdown and microphone restarts now use cooperative cancellation instead of unsafe QThread termination. Native faults are additionally logged under `logs/fatal_error.log` where Python's crash handler can capture them, while `logs/startup_error.log` contains ordinary startup Python exceptions. If unexplained exits continue, run `diagnose_windows.bat` and inspect both logs. Review logs for private paths before sharing.

## Automatic local GGUF engine setup (Windows)

`llama-cpp-python` is the native library that opens local `.gguf` AI models. A model file alone cannot provide local chat. **The updated `install_windows.bat` installs this library automatically**, after the main requirements, using only the official precompiled CPU wheel (no C++ compiler needed). The `Update.bat` updater also checks and repairs the library, **even when it says LuxAI code is already up to date**. The main application remains usable if no compatible wheel is available; look in `logs/local_ai_install.log` for that error.

For an existing installation, close Jarvis, run `Update.bat`, then reopen the app. If the backend still shows missing, run `install_local_ai.bat` to retry with a visible console. The helper installs into `LuxAI_Local/.venv`, not the global Python on the computer. Once the module is verified, select a GGUF under **Settings → AI Provider → Models**. A model can still fail to load when the file is incomplete or RAM is insufficient. Installation alone is not a guarantee that every model runs.

## Python 3.11-3.14 detection and package updates

`install_windows.bat` checks for all installed stable 64-bit Python **3.11, 3.12, 3.13 and 3.14**, shows which are present, and prefers the newest supported one when creating a new `.venv`. An already working `.venv` is normally preserved. If Python is absent, setup can use the signed official Python fallback.

Each installer run rechecks **all direct packages in `requirements.txt`**, including packages already installed, and upgrades to the newest compatible stable releases allowed by their requirements and Python version. It uses `pip check` afterwards to detect package requirement conflicts. `Update.bat` uses the same upgrade policy even when the GitHub source revision is already current. The optional GGUF engine is also checked for a newer compatible prebuilt CPU wheel. These operations change only `LuxAI_Local/.venv`, **not global Python installations**. Internet access is needed to check current package availability.

The newest package release is not always compatible with every Python version or every other library. The installer uses dependency constraints, Python markers, import checks and Windows CI tests rather than blindly forcing the newest number. If a library cannot be updated, inspect `logs/install_windows.log` or `logs/local_ai_install.log`.

## Romanian GGUF Unicode, reliable API keys, and cloud status

Local GGUF messages use **UTF-8 in both directions**, including Windows systems whose default character set cannot encode Romanian `ș`, `ț` or Cyrillic. After updating, say a phrase containing Romanian diacritics to confirm the chat no longer returns `'charmap' codec can't encode character`.

API keys are encrypted using the current Windows account's Data Protection API (DPAPI). New keys are saved in **`%LOCALAPPDATA%\LuxAI_Local\secrets`** instead of the copy of LuxAI on the Desktop, so extracting or updating LuxAI elsewhere does not lose the key. Old readable keys in `.luxai_secrets` are migrated automatically for the same Windows user. After clicking **Save settings**, LuxAI verifies the saved key can be decrypted. If not, it keeps the entered text and reports the error. DPAPI cannot decrypt a key created under another Windows account; each user must save their own key.

Open **Tools / Instrumente / Дополнения** to see Cloud AI status. A **green** indicator means a real authenticated test request has succeeded with the selected provider and model during the current session. Yellow means configured but not yet checked (or disabled); red means a missing key or failed check. Use **Check cloud AI** to run another test. A test may consume a small amount of the provider's quota. Never confuse having a stored key with confirmed live connectivity.

## Complex voice-created commands (0.2.0)

Say **"Создай команду"** or **"Creează o nouă comandă"**, provide a trigger phrase and describe the complete sequence: "open Notepad then wait 2 seconds then press Q W E R D". The wizard first parses supported commands locally; otherwise a configured cloud AI provider proposes a structured multi-action macro. The proposal is never executed while being designed. Jarvis previews the actual steps and saves them only after your explicit confirmation. A saved macro runs locally later, without needing another cloud call.

Macros support up to 8 steps, and the new keyboard-sequence step can press 2–24 English letters or digits individually, with a short gap between presses. Existing keyboard shortcuts, safe mouse actions, delays, apps and browser actions may be combined. The sequence `qwerd` means five key presses, not typing that word into a text field. It can also be edited through **Commands → Actions**.

Cloud macro plans pass a strict local action allowlist and parameter validation. Arbitrary shell commands, bulk deletion, emptying the Recycle Bin, password handling and unsupported instructions cannot be automatically generated. The wizard refuses incomplete/invalid plans instead of silently saving only the first recognizable clause. Advanced cloud interpretation requires an enabled provider and working API key; simple local commands and saved macros run offline.

## Consent-based cloud visual desktop macros

LuxAI can build reusable voice macros and also execute direct spoken multi-step requests involving mouse, keyboard, files, windows and real desktop geometry. The **visual_click** action takes a semantic control name and an explicit 1–10 click count, captures the *foreground external Windows application* after an affirmative screenshot-sharing prompt, sends a downscaled image to the configured vision-capable cloud AI, validates the returned normalized coordinates against the actual captured window, and only then clicks. Nothing is clicked when the provider does not support images, the element cannot be uniquely found or the foreground window changes. DPI/window decorations and fast-changing screens can limit accuracy. A cloud screenshot may include private information; review the approval dialog before sharing. Screenshots are not stored with macro definitions.

For Recycle Bin commands, LuxAI offers native **open_recycle_bin**, explicit **empty_recycle_bin** with a separate irreversible-deletion confirmation and the Windows OS dialog, and **close_window** with confirmation. The AI cannot bypass the approval checks, write arbitrary scripts, read credentials, or auto-delete arbitrary desktop files. A direct complex voice request first previews every proposed step, and a saved macro requires explicit confirmation before it is created. Some cloud providers/models do not support image input, so selecting a vision-capable model such as an appropriate Gemini or OpenAI model is required for visual clicks. Live visual features require Windows, a visible external target window, and internet access.

## Research and send a sourced Discord direct message safely

The dedicated `discord_research_dm` action handles complex speech such as “find information about Adolf Hitler, find Discord user Ronci and send it”. Instead of opening a browser search result and then blindly clicking in whichever application happens to have focus, LuxAI fetches a short **real Wikipedia TextExtracts** summary with a source link, switches to the installed Discord desktop app, invokes its documented **Ctrl+K / @username Quick Switcher**, and locates the matching result and DM editor through live screenshot analysis. It drafts the cited text and **requires separate explicit approval before pressing Enter**. The application never claims it verified delivery.

A screenshot can expose private conversations. User approval is required before sharing up to three screenshots with the selected vision-capable cloud provider. The third is captured after the final send confirmation to verify the current DM header and the entire unsent message again. Sending runs off the UI thread and is cancelled if verification is ambiguous or the target window changed. If search results are ambiguous, user text was misheard, source lookup fails, or the expected DM composer is not visible, no message is sent. A captured chat title is not treated as a password / login screen. Names and article subjects are locally revalidated; other cloud-generated plans are rejected for this intent. Windows, Discord desktop and a working vision-capable AI provider are required. Not every cloud model accepts images. No login credentials or Discord tokens are used.

## Discord visual screenshots and summary via a single voice command

A full chained request to open Discord, take a screenshot, find a named user, take another screenshot and summarize it is now treated as **one ordered multi-step action**, before generic Windows UI button inspection. With explicit consent, LuxAI launches/focuses the verified Discord desktop process, saves a local initial window screenshot, searches for the exact Discord username using Ctrl+K, checks the DM header in a new visual capture, saves the resulting screenshot and summarizes visible content in Russian through the user's chosen vision-capable provider. It **does not send messages**. The two screenshots are saved under `Pictures/LuxAI`.

Consent describes up to three image transmissions (Quick Switcher search, DM header check, final image summary). The first window capture stays local; any ambiguous username/AI match stops the operation. Cloud access is required for visual analysis. If unavailable, a complete multi-step task fails clearly instead of executing a single unrelated screen-inspection or click action. Only Windows and Discord desktop are supported for this particular workflow.

### Whisper variations and Discord multiword display names

Long Russian requests can now retain multiword contact display names (for example, `Старый Бог`) and recognize the specific mishearing `Скопт` as a possible Discord reference only when a full screenshot-and-chat workflow is present. An explicit preview confirms Discord and the complete person name; a different unrecognized application name causes a clear error rather than launching a guessed app or answering as a generic chatbot. Users must authorize visual analysis, and an ambiguous match never triggers blind clicks or sends a message.

### Restore native Discord microphone controls before generic macro planning

Known local commands retain priority over the live macro generator. `Выключи микрофон в Discord` continues to use the existing confirmed Discord Ctrl+Shift+M toggle. `Сделай снимок экрана и нажми на кнопку микрофона в дискорде` now uses a dedicated opt-in visual operation: verify the real Discord process and focused window, save one screenshot under Pictures/LuxAI, ask the selected image-capable cloud AI to locate the unique Discord mic control, then click that control once after revalidating foreground/window and coordinates. A missing/ambiguous target is not clicked. No messages are sent, and a toggle is not claimed to have produced a known mic state.
