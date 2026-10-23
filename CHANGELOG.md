
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
