## 0.9.3.d — collection transfer and real command/status views (2026-10-30)

- Paint command-tree branches and selected rows consistently with the selected theme, including Windows hover states.
- Scope exports to the selected command/folder/collection or current tab, preserving empty groups and structure on validated atomic import. Keep legacy files compatible, fresh imported IDs and disabled imports.
- Replace the inactive Agent commands button with a separate working command workspace, AI/action editor, folder controls and empty-state chat navigation.
- Replace the Tools model picker with a read-only local AI indicator. Keep model selection in Settings; distinguish lightweight readiness from actual GGUF request progress, success and failure.
- Preserve personal settings/models/commands and source-only Markdown/test cleanup.

## 0.9.3.c — clipboard attachments and editable preset menus (2026-10-30)

- Compact chat previews with individual removal, a left attachment control and right send button; paste Explorer files and clipboard images through the same bounded local attachment pipeline.
- Persist validated edits and deletions of default commands in the personal registry, with original preset identities preserved across updates. Execute explicitly customized presets through the existing confirmed command route.
- Match the supplied Luxify three-dot menu with icons, phrase actions, enable/disable, clone, copy/JSON and deletion. Add folder context controls while retaining personal commands when folders are removed.
- Preserve settings, models, personal files and GitHub-only Markdown/tests. Clipboard selection does not upload files or execute their contents.

## 0.3.9b — command workspace redesign and functioning recorder controls (2026-10-29)

- Rebuild Commands as a Luxify-style library with top tabs, nested default-command categories, a right-side create/file panel and accessible on-hover or right-click per-command actions. Remove visible global edit/delete controls from the right panel.
- Add real JSON **Import from file** / **Export to file** for user-created commands. Imported actions are allowlist-validated, disabled initially and assigned fresh IDs. Never execute imported content; export includes no API keys or private settings.
- Add persistent personal folders and collections, with a context action for moving custom commands into them. Defaults remain read-only and do not overwrite personal data on updates.
- Replace chat's visually broken nested input with a charcoal ChatGPT-style multiline composer. Attachment previews sit above the prompt, + and send arrow remain in the bottom toolbar. Shift+Enter adds a line; Enter sends.
- Fix recording Stop/Cancel being unclickable under a modal editor: use a standalone application-modal dialog with visible clickable controls, minimize the editor during capture and restore it after stop. Recorded keyboard/game-key safeguards remain unchanged.
- Remove the redundant command editor navigation rail, align the voice/keyboard/schedule/event controls and pin Save/Cancel inside the right review column. Native Windows hook behavior and visual fidelity still require smoke testing on a PC.
- Add offscreen Qt regressions and refresh the safe updater cleanup hashes. Python 3.11–3.14 are the fully supported versions; 3.15/3.16 are probes only.

## 0.3.9a — Luxify-style chat and command editor (2026-10-28)

- Compact chat composer with inline files, an attachment + control and a send arrow; cloud-delivery hints are hidden until attachments are selected.
- Separate declarative default presets into `luxai/default_commands.py` and a distinct nested UI folder. Reorganize the command sidebar and editor navigation.
- Explicit high-contrast info-icon help on hover/click.
- Remove the old eight-action ceiling for manually saved/recorded macros, preserving per-step validation and separate AI-plan safeguards. Minimize Jarvis during recording and expose a standalone Stop/Cancel overlay, then restore the editor.
- Extend regression tests and update the safe source-only cleanup catalog. Native Windows interaction still requires a user-PC smoke test.

## 0.3.9 — chat attachments and complete command editing (2026-10-28)

- Add local attachment selection, drag/drop and previews for text/code/CSV/JSON/Markdown, images, PDF and DOCX. Send only selected snapshots to the configured cloud provider; use document extraction and image OCR for local processing. Bound file counts, bytes and extracted context; never execute attached content.
- Show proposed file changes in an explicit original/diff/new-text review. Apply text and compatible same-paragraph DOCX edits only after stale-file checks, preserving recovery copies. Export PDF and structural DOCX changes as text copies; convert manual Word line breaks to normal text newlines while preserving their DOCX paragraph mapping. Reject unsupported controls in plain-text edits before writing.
- Rebuild the Commands editor with phrase chips, optional words, ordered actions, voice/hotkey/schedule/event triggers, recording, AI proposals, phrase matching and Run now. Retain the action allowlist, existing command compatibility, the eight-action limit, confirmation and chaining preferences. Triggers work only while the application runs; native Windows hooks and real devices still need target-PC validation.
- Persist sidebar collapse state without initial autosaves or committing unrelated Settings/API drafts. Remove only the Screenshot/OCR cards from Tools, retaining screen commands and automatic OCR setup.
- Complete RU/EN/RO labels while preserving user filenames, phrases, action targets and document bodies. Keep all bundled Markdown/tests GitHub-only, retaining safe historical cleanup and personal-data protection.
- Add offline attachment/extraction/edit regressions, command editor/trigger/recording tests, Qt sidebar integration and localization coverage. These do not establish physical headset, global-hotkey or live cloud-provider behavior on the user's PC.

## 0.3.8c — keep all bundled Markdown on GitHub

- Omit all bundled `.md` documentation from fresh installations and updates, including user guides, README files and release notes. Keep the source documents on GitHub; no application code depends on them.
- Remove unchanged Markdown shipped by older versions using the existing catalog of source hashes. Preserve edited copies, personal Markdown, settings, models and other user data; retain required license notices and the standalone Romanian `.txt` guide.
- Verify fresh-source cleanup, upgrade filtering, historical document cleanup and personal-file preservation.

## 0.3.8b — fluid, audio-reactive avatar and clean runtime installation

- Animate the right-hand avatar with elapsed-time motion, subpixel drawing and smooth microphone attack/release. Listening and actual Piper/Windows playback have distinct reactions; silent voice preparation does not trigger speaking. Theme/accent/background changes update the rings immediately. Hidden or disabled animation stops its timer.
- Omit repository tests, CI files and development Markdown from installed runtime copies; keep all source and development files on GitHub and retain user instructions. Clean recognized old shipped copies only when their contents match known repository versions; preserve edited or user-added files.
- Keep settings, secrets, models, recordings and personal files during updates. Reject old backup cleanup when a backup contains preserved data, even if its manifest lists that data.

## 0.3.8a — integrated design and consistent interface language

- Replace the separate native title bar with an integrated draggable header and accessible minimize/maximize/restore/close controls. Retain native resizing and minimum-size fallback. Place the microphone to the left, aligned above the history cards.
- Extend the home orb behind the full content height and to the right edge, with a natural transparent left curve. Preserve animation, themes and home-only visibility. Remove slider borders/bevels, retaining keyboard focus on the knob.
- Redesign Interface settings with segmented theme/language controls, accent swatches/custom color, real background swatches/hex selection, percentage pills, rounded switches, separators and reset. Stack controls on narrow windows without clipping; preserve auto-save and configuration compatibility.
- Render chat roles using the interface language, including existing history: Russian shows «Вы (голос)». Keep voice preferences and message bodies independent. Complete UI/dialog/model-status translations; simplify synthesis provider names to Piper and Windows.
- Remove the manual local-engine installation button. Install/update continue preparing the CPU engine automatically; the launcher now silently repairs missing/broken engines without delaying Qt. Reuse working engines without network, serialize installers, and verify native imports in child processes. GGUF model weights remain user-selected.
- Add real Qt interaction/layout/pixel/localization tests and subprocess locking/startup-repair regressions. Physical desktop behavior still needs observation on the target PC.

## 0.3.8 — multilingual commands, native games and consistent settings UI

- Normalize bounded polite requests, Romanian diacritics/inflections and spoken key names consistently across Romanian, Russian and English. Expand Discord microphone/headphones, calls, contacts and screen/dictation intents while preserving exact recipients, literal message bodies and action safeguards. Keep explicit Whisper language choices intact.
- Give Auto recognition a trilingual command context and at least three decoding beams after real Whisper Small/Piper comparisons exposed lost Romanian commands with the previous unprompted fast Auto mode. Filter excessive repetitive noise transcriptions before dispatch. Explicit Russian/English decoding preferences remain unchanged; synthetic speech results do not establish physical-headset or arbitrary-name accuracy.
- Route recognized Steam game launch/close and master-volume requests directly to typed local tools before generic cloud/chat planning. Recognize War Thunder and its speech aliases; close only verified game windows/processes, never Steam. Request graceful closure once and report success only after observing closure; game dialogs or still-running processes remain unverified.
- Apply the selected accent to the home orb, switches, branding, sliders, progress bars and existing chat entries. Starting a command also applies any pending appearance edits.
- Move ongoing task activity from beside the header microphone into the chat area; clear it when work ends. Add live percentage readouts for microphone sensitivity, speech speed/volume and transparency. Synchronize Settings section navigation with scrolling, filtering and resizing.
- Include 10–15 equivalent formulations per tested intent and language, negative/literal/compound cases, executor/routing checks, native Windows closure simulations and real Qt interaction/pixel regressions. These cover the supported RU/RO/EN command paths; physical microphones, arbitrary speech and live game behavior still depend on the target PC.
- Retain 0.3.7g's automatic updater completion, temporary rollback/legacy backup cleanup, startup Piper preparation and sidebar version display.

## 0.3.7g — updater storage cleanup, startup voice preparation and version label

- Close the new Windows updater batch automatically after success; retain readable failures and nonzero exit status. The final pause already parsed by a legacy launcher can occur once during migration.
- Keep ordinary code rollback only in temporary staging, remove recognized legacy updater backups/bootstrap files after successful updates or already-current checks, and preserve originals only for incomplete rollback recovery. Never delete unrelated files or traverse linked backup paths.
- Prepare the configured Piper reply voice on the existing speech worker at startup, including silent first synthesis and playback library imports; reuse the model for the first reply, serialize inference and respect quiet mode/cancellation. Fix the Windows fallback cancellation-token argument.
- Show the installed version below the sidebar collapse button, readable in both themes, sidebar widths and HiDPI layouts.
- Add regressions for startup speech/cache reuse, sidebar placement and updater cleanup/rollback and batch completion behavior.

## 0.3.7f — cloud API recovery and settings regression fixes

- Honor the configured API verification timeout and retry explicit HTTP 502/503/504 once at the identical endpoint within the request time budget. Never retry authentication, quota, redirect or timeout failures. Diagnose temporary service outages separately from invalid credentials.
- Require asynchronous API results to match the exact current provider/key/model/custom endpoint before saving or marking the connection verified. Preserve a genuinely tested Gemini replacement model, tolerate transient model-list outages for an explicitly configured model, and reset stale cooldowns after credential changes or successful checks.
- Refresh cloud status after key deletion and report the actual credential source consistently. Keep previous runtime configuration after a failed preferences write.
- Avoid global Qt style/translation rebuilds on ordinary Settings auto-save; still apply real theme and language changes and refresh visible dialogs.
- Retain microphone host identity after device indices change; limit truncated-name migration to legacy MME. Correct whole-word English Discord headphones on/off matching and reject prohibitions/how-to questions.
- Add transport, asynchronous UI, credential lifecycle, microphone identity, headphones and settings efficiency regressions. Real account availability and physical headset/Discord behavior still require testing on the user's Windows PC.

## 0.3.7e — compact Windows microphone picker

- Show each physical recording input through one preferred Windows audio backend (WASAPI first), rather than repeating MME/DirectSound/WASAPI/WDM-KS entries.
- Display short microphone labels similar to Discord, without changing driver names or recording endpoint metadata.
- Safely migrate identifiable legacy selections, retain unavailable devices rather than silently picking a different microphone, and suppress false settings autosaves while refreshing the device list.
- Add regression tests for backend selection, headset reconnection, MME truncation and Qt selection behavior.

## 0.3.7d — Settings auto-save safeguards

- Continue automatically applying/persisting all ordinary Settings changes without any Save button; protect in-progress API-key text from being unintentionally stored by unrelated preference changes.
- Persist API credentials only when editing finishes or after a successful explicit API test, keeping the existing encrypted Windows DPAPI storage and validation behavior.
- Update Romanian/English instructions on restarting the installed app to see the new Settings UI; add regression tests for draft-key safety and automatic persistence.

## 0.3.7c — automatic Settings persistence

- Remove the explicit “Сохранить настройки” Settings button.
- Automatically save/apply changes from actual editable Settings controls after a short debounce; flush edits when navigating away from Settings and on window close/minimize.
- Preserve existing config and service-application logic and secure key storage; do not autosave search or changing diagnostics.
- Add Qt regression tests for debounced autosave, one real config write, API key editing, navigation and close.

## 0.3.7b — Integrated OCR, remove redundant Settings controls

- Remove the built-in Tesseract OCR section, external-path picker, Browse button and OCR status row from Settings → System.
- Preserve automatic OCR setup/retry on Windows, bundled rus/eng models, OCR commands, original config values and updater support. Status remains available internally; errors can still surface via microphone status tooltip.
- Remove obsolete Settings callback and add regression tests for clean Settings UI, stable saving and working bundled OCR bootstrap.

## 0.3.7a — Home panel cleanup (mini-patch)

- Remove the three redundant Home buttons: "Проверить микрофон", "Посмотреть кнопки на экране", and "Пересказать выделенный текст".
- Keep microphone diagnostics via Settings and keep screen inspection and selection-summary functionality via existing commands.
- Remove obsolete MainWindow signal connections and diagnostics references. Preserve all four toggles, volume, mic status and level.
- Add Qt regressions for clean Home construction and settings microphone diagnostics.

## 0.3.7 — Discord voice-call name verification and home UI toggles

- Strictly match Cyrillic ASR transcriptions to complete Latin displayed names for **calls only** (e.g. "Ханзо" to "Hanzo"), while requiring the actual individual chat header to confirm the account. Other contacts and partial matches are rejected; message rules remain unchanged.
- The full 54×28 region of custom home-page ToggleSwitch controls now responds to a single click, not only the QCheckBox style indicator.
- Regression tests cover mismatched account rejection, verified name propagation and mouse clicks at multiple positions on all four switches.

## 0.3.6 — One-command Discord voice calls

- Recognize explicit Russian/Romanian/English requests to call one named Discord user without dictating opening, contact selection or phone clicks.
- Open verified DM before finding the current voice-call handset; use a two-pass pixel-accurate location and one click, then confirm ringing or active call controls from a new screenshot.
- Do not call group/video targets, a mismatched user, or an uncertain call state; no blind retries and no synthetic success claims.
- Add end-to-end mocked intent, routing and click verification tests.
- Update PROJECT_HANDOFF.md to document the new workflow.

## 0.3.5 — Discord headphones state and Steam routing

- Dedicated state-aware Discord headphones/deafen action with fresh before/after screenshots and enlarged red-slash verification when required; no blind repeat clicks.
- Preserve full natural Steam nickname queries as a single open-and-read operation rather than sending them to generic desktop planning.
- Add PROJECT_HANDOFF.md with module map, architecture, troubleshooting, tests and guidance for continuing the project in a new chat.
- Add offline regression tests for state transitions, ambiguous verification and natural voice routing.

## 0.3.1 — New icons and concise Discord requests

- Replace font symbols and emoji with bundled Lucide SVG icons across navigation, commands, settings and dialogs. Add a Jarvis window/taskbar/tray emblem, theme-aware colors, crisp HiDPI rendering and consistent control arrows. No runtime icon downloads or icon-font dependencies.
- Keep command names readable beside the new icons, and retain selections, drafts, device choices and callbacks when changing themes or languages.
- Ignore hidden Electron helper windows when choosing Discord's main window. Preserve tray restoration and ask for a window only when separate real Discord windows remain ambiguous.
- Recognize short requests such as “А ты можешь написать в дискорде пользователю Hanzo привет”. Build the verified contact/draft/send workflow automatically; ask only for a missing name or exact message and resume the same task.
- Preserve literal message content and final draft approval. A message mentioning microphone controls cannot execute those controls. Recognize “закрой микрофон в Discord” and allow its visual state verification after clarification.

## 0.3.0 — Adaptive desktop tasks and verified execution

- Introduce an adaptive task loop: choose a tool, observe its result, revise the next step and verify the requested outcome. Open applications through native Windows discovery first; a running process or an issued click is no longer enough to report completion.
- Local screenshot requests work without an AI key. Visual cloud work retains screenshot permission once per Jarvis session and the dedicated Discord recipient/message checks.
- Repair Windows callback and window-handle types, including the Discord enumeration error. Require a visible, on-screen foreground application window before confirming native opening.
- Share strict model JSON parsing, fix invalid JSON examples in visual prompts, and preserve the distinction between an action already issued and an outcome that could not be verified. An uncertain toggle is not clicked again automatically.
- Add a local CMD/PowerShell executor with parsed read-only commands, bounded output, timeouts and cancellation. The default `agent_auto_shell: true` authorizes proposed commands for the current task without repeated prompts; changing commands still need an independent read-only result check. Set `agent_auto_shell: false` for exact shell/command approval. Neither mode bypasses Windows permissions or UAC; remembered procedures do not store command authority.
- Add explicitly requested native Windows power actions and dark/light theme changes with state readback. Shutdown/restart requests use a cancellation delay and do not force applications closed. Night Light opens the supported settings page and can continue through the consented visual tool; activation requires observed toggle-state evidence.
- Store bounded task checkpoints, clarification answers and verified procedure hints in `.luxai_data/agent_memory.json`. Raw shell commands, screenshots, recordings and command approvals are not retained as reusable procedures; every task still needs fresh execution checks.

`Update.bat` installs the contents of `main`. Changes present only in a feature branch or pull request are available through it after merging.

### 0.2.0 — Post-confirmation Discord send verification

- A saved Discord composer coordinate is no longer trusted after the user reviews the send confirmation. A fresh, explicitly approved third screenshot verifies the current recipient and exact unsent draft immediately before clicking and pressing Enter; changed chats, modified drafts or ambiguous screenshots stop the send.
- Final visual verification runs on a worker thread so the Jarvis window remains responsive; cancellation of a stale macro aborts sending. Offline tests cover wrong recipients, stale windows, and mid-flight cancellation.

### 0.2.0 — Discord research / cross-app voice workflow repair

- Prevent cross-app hallucinations: a `search_web` side effect is no longer mistaken for extracted source content, and an unrelated browser screenshot cannot be treated as a Discord contact.
- Added a dedicated `discord_research_dm` macro with a real Wikipedia source, Discord Quick Switcher `Ctrl+K` username search, two verified vision-based steps and a prepared message.
- Added mandatory per-run screenshot permission and a separate recipient/message send confirmation; never reports Discord delivery without evidence.
- Added regression tests for the exact Russian voice transcript, Wikipedia query/citation, ambiguous user refusal and Enter being reserved for confirmed sends.


### 0.2.0 — Visual command planner improvement

- Added consent-gated screenshot analysis for exact visible UI element clicks (1–10 repetitions), with real virtual desktop coordinates and multi-monitor geometry.
- Added native Recycle Bin opening, separately confirmed bin emptying and safely confirmed external window closing.
- Routes direct multi-step spoken tasks through the constrained cloud macro planner, while retaining the existing reusable command wizard.
- Rejects protected windows, ambiguous/offscreen coordinates, unsupported image APIs and changing foreground windows without guessing or silently continuing.
- Added isolated, offline tests for screenshot payload formats, coordinate validation, multi-monitor geometry and destructive intent checks.

# Changes

## 0.2.0 — Voice reliability and recovery

- Microphone status now distinguishes model loading, a successfully opened input, detected speech, transcription, silence and failures. A live input meter is available on Home and in Settings.
- Wireless microphone selections remember the recording endpoint and host API across changed device indices. A missing selected headset produces an error instead of silently recording another microphone.
- Capture supports variable driver buffer sizes, native sample rates, quiet-input sensitivity, bounded buffering and stalled-stream detection. Jarvis playback is discarded before it can become queued microphone input.
- Added a four-second microphone test that works without Whisper, device refresh, microphone restart and an offline diagnostic report. No recordings, API keys or conversations are included in the report.
- Cancelled or obsolete listener signals cannot execute delayed voice commands. Diagnostic and capture threads shut down cooperatively and cannot replace an active diagnostic worker.
- File commands preserve Documents/Downloads/Desktop, understand location clauses in Romanian, English and Russian, and rename the explicitly named source rather than an unrelated last-created file.
- Local selected-text summaries follow the selected response language.
- Updates validate staged Python files and dependency syntax before replacement, use atomic copies and an updater lock, and restore prior code if application or dependency validation fails. Settings, keys, models and environments remain preserved. Pip package changes cannot be rolled back automatically; a dependency failure may require `install_windows.bat`.
- Repaired OCR tests and test isolation. Added capture, device selection, diagnostic, UI lifecycle, voice-file and update recovery regressions. Linux and Windows CI run the full suite; physical headset and audio-driver behavior still require testing on the target PC.

See the microphone troubleshooting steps in README.md or README_RO.md after updating.

### 0.2.0 — Complex voice macros follow-up

- Added a dedicated cloud JSON planner for multi-step voice-created commands instead of the single-action chat planner.
- Added a bounded `key_sequence` macro step: QWERD means five individual keyboard presses in order (2–24 letters/digits per step). Works in basic local voice recognition and can be edited visually.
- Cloud proposals are revalidated against the local safe action catalog, previewed step by step, and saved only after explicit confirmation. Unsupported destructive/system actions do not receive fabricated replacements.
- Improved recognition of Romanian command-creation phrases; existing safe single-action online macro proposals remain supported.
- Added regression tests for cloud planning, spoken key sequences, safe rejection, saved macro persistence and Windows keyboard execution.

### 0.2.0 — Speech recognition and stop-interrupt hotfix

- Wait longer before finalizing microphone input: 2.3 seconds by default, with an adjustable 1.2–4.0 second interval in Settings → Voice input. This keeps dictated instructions together across normal thinking pauses.
- Filter known false Whisper video-outro phrases such as «Спасибо за внимание» when they appear as standalone transcripts instead of treating them as user commands.
- Detect short, exact spoken «Стоп», «Stop», «oprește-te» and equivalent stop words during actual voice output, and interrupt local Piper / Windows SAPI audio without forcefully terminating Qt threads.
- Discard pending spoken replies on stop, and keep unrelated sounds or speech during playback from becoming new computer commands.
- Expand the bounded audio queue for split Windows/Bluetooth recording callbacks; add microphone/interrupt regression tests.

### 0.2.0 — Discord Whisper transcript / contact display-name hotfix

- Correct routing for the spoken transcript `Откроете Скопт ... найдите пользователя Старый Бог ... краткое содержимое` and similar complete multi-stage screenshot requests; no partial execution or generic-chat refusal.
- Support exact two-to-four-word Discord display names in the visual-review workflow, while requiring unambiguous Quick Switcher and chat-header verification.
- If the chat application cannot be recognized with confidence, reject the whole task instead of allowing a partially generated cloud macro. Maintain explicit screenshot consent and zero send actions.

### 0.2.0 — Discord screenshot macro: search-then-click phrasing

- Parse voice phrases such as `найди там пользователя старый бог нажми на него`, separating location adverbs, contact display names and the subsequent click action.
- Ensure the complete screenshot/search/screenshot/summary request takes the verified Discord visual workflow rather than an unsupported general-cloud plan; add regression tests matching the actual Whisper transcript.

### 0.2.0 — Restore Discord microphone and screenshot command priority

- Fix a regression caused by checking the generic live macro planner before longstanding native Discord microphone commands.
- Route `Сделай снимок экрана и нажми на кнопку микрофона в дискорде` through a verified, opt-in Discord screenshot/mic-button click rather than an incomplete cloud macro proposal.
- Preserve and prioritize the old `выключи микрофон в Discord` shortcut, confirmation and truthful toggle-state reporting; add mocked Linux/Windows UI and no-click-on-ambiguity regression tests.

### 0.2.0 — Restore visual desktop steps and visual-first Discord contact discovery

- Preserve complete multi-step Calculator visual button sequences, Steam Library navigation, and real-display-coordinates/right-click workflows as validated local plans, avoiding incomplete generic cloud proposals while retaining explicit screenshot permission.
- Locate individual Discord contacts from a fresh DM-list screenshot BEFORE Ctrl+K search. Fall back to the spoken username and optionally a Latin search prefix for Cyrillic speech; reject group chats and ambiguous matches.
- A visually detected name different from the dictated one requires an explicit user confirmation on the Qt main thread before clicking or composing. Verify the actual selected name again in chat header and before sending; show up to five cloud screenshot disclosures in consent.
- Add mocked end-to-end regression cases for the exact failed calculator/mouse/Steam commands, wrong-account rejection, visible Latin handles and empty search results.

### 0.2.0 — Reliable final approval for long Discord research drafts

- Stop requiring OCR-perfect matching of long percent-encoded Wikipedia URLs in a downscaled Discord screenshot. After explicit send approval, visually revalidate the exact individual DM header and live message composer, then restore the EXACT user-approved Unicode text in that composer before Enter.
- The final confirmation now explains that the current editable draft will be replaced. Never use stale composer coordinates or alter the user's clipboard. Abort on ambiguous recipient/composer, cancellation, invalid draft, native keyboard-input failure, or switched foreground/process.
- Add regression tests for the actual long-Wikipedia-URL scenario, exact text restoration, no send on ambiguity, focus change and failed native typing.

### 0.2.0 — Regression repairs for native intents and verified desktop workflows

- Make built-in Discord microphone intent matching resilient to Russian Whisper inflections (including `Выключу`) and resolve these intents **before** learned open-Discord shortcuts and generic cloud planning.
- Add a dedicated `discord_open_dm` visual workflow that must verify the actual individual chat header after a click; retry at most once from a fresh screenshot if Ctrl+K only closes the search menu. Name mismatches still require explicit approval.
- Execute multi-step display-info / mouse-move / right-click actions through the validated local executor, not the incompatible generic single-action agent. Preserve actual step-specific failure details.
- Require cloud screenshot consent once per application session (not repeatedly per image); local screenshots need no consent. Final message sending still requires confirmation.
- Implement source-backed three-fact Wikipedia research to a **verified** Notepad window, followed by select-all and copy. Also focus Notepad for ordinary cross-app literal-text macros after browser searches.
- Add regression tests for the exact user-reported voice transcripts, Discord second-click failure, stale learned shortcuts, privacy decisions, Mars facts and Notepad focus.

### 0.2.0 — Visual Discord microphone requests are idempotent

- Route the actual spoken request `Зайди в Discord и нажми на кнопку микрофона чтобы его выключить` to the screenshot-based GUI handler, even without explicit screenshot wording; never substitute Ctrl+Shift+M for a requested mouse click.
- Read the button's current visual `muted`/`unmuted`/`unknown` state before acting. Already-muted requests require zero clicks; uncertain state blocks the click. After at most one click, take a fresh screenshot and report the final state only if visibly verified.
- Preserve plain shortcut and explicit toggle workflows, one-session permission for cloud image uploads and the safety stop for window changes.
- Add mocked tests for the exact voice transcript, routing priority, no click for already-muted/unknown states, and no false success after uncertain post-click verification.

### 0.2.0 — Cloud plan revision and verified Discord search field

- Support an adaptable cloud planner: propose a full task, validate against local supported actions, and if incomplete let the provider revise it ONCE using the validator's feedback. No unsafe/partial plan executes; never claim unexecuted actions succeeded.
- Add atomic `discord_send_text` tool for unknown phrasing that requests a Discord DM. Validate that both spoken recipient and literal message originate in the user's request. Reuse screenshot-verified recipient, draft and explicit send confirmation; no blind `type_text` + `Enter`.
- Before any Discord Ctrl+K search typing, require a fresh screenshot and unique visual match for the QUICK SWITCHER popup input, with a conservative positional check to prohibit the bottom conversation composer. Abort without typing if missing/ambiguous.
- Apply the screenshot gate to both opening contacts and Wikipedia→Discord messages. Add offline tests reproducing the @Octavian wrong-composer issue, AI revision and safe message drafting.

### 0.2.0 — Closed-loop visual reasoning, verification and correction feedback

- Introduce bounded image-grounded agent: one observed decision at a time, independent control localization, validated Windows click, post-action recapture, updated planning and independent final-state screenshot verification.
- If the user says “ты не попал, давай заново” within 10 minutes of a visual goal, restart the preceding intent from a NEW screenshot instead of responding as generic small-talk or replaying guessed coordinates.
- Enforce maximum 6 GUI actions/9 observations, abort on uncertain target/window, refuse repeating failed clicks on toggles, never claim success merely because the mouse was clicked.
- Keep Discord messaging and other high-impact tasks routed through their existing dedicated tools and human confirmation; generic agent cannot execute shell, delete files, send messages, submit sensitive forms or payments.
- Add mocked regression tests for unfamiliar visual commands, user correction, before/after checks, unsafe controls and no false success claims.

### 0.2.0 — Discord background process vs real foreground GUI

- Separate installed/running-process state from Discord window visibility and focus. Enumerate verified Discord.exe top-level HWNDs (including hidden), restore tray/minimized windows, recover off-screen geometry, and confirm actual foreground before screenshots and mouse actions.
- Launch URI or installed executable only as a fallback if the visible window could not be restored. Never respond „already open” solely because Discord.exe exists.
- Interpret „он запущен но окно же не открыто” as local window recovery after a Discord task; do not resend or retype earlier messages.
- Preserve the full intent of Discord recipient-message instructions: reject incomplete open-app-only cloud plans and keep final recipient/text confirmation.
- Screen-review Quick Switcher also uses the screenshot-validated input to prevent typing into the wrong DM composer.
- Mock Windows GUI, process, offscreen and tray states in new regressions.

### 0.2.0 — Adaptive tool-first desktop actions

- Fix common non-JSON cloud vision model responses with bounded JSON extraction/format recovery and one corrective retry; uncertain verification still stops instead of claiming success.
- Fix Windows native HWND argument-width mismatches when identifying and restoring Discord windows on x64 systems.
- Add a text-first AI tool selector for app opening, local screenshot, Windows settings, bounded GUI reasoning, cloud answers and allowlisted read-only diagnostics. Do not take/upload a screenshot when a local launch or status command is sufficient.
- Implement standalone local PNG screenshots without any cloud-model requirement.
- Keep explicit existing file/website actions ahead of generic visual routing and focus the intended app window for GUI tasks. Recognize Steam webhelper and CalculatorApp GUI processes.
- Store only safe completed tool choices by hashed request, with no raw voice text or image data.
- Reject arbitrary model-proposed CMD and keep significant side-effect actions within separately confirmed workflows.
