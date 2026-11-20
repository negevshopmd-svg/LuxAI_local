## 0.4.2x — Documentation cleanup (2026-11-20)

- Removed outdated developer documents: `COMMANDS.md`, `ONLINE_AI.md`, `VOICE_TOOLS.md` (0.3.x era),
  `README_RO.md` (stopped at 0.3.9g; the user guide is `README_RO.txt`), `voices/README.md` (Italian, the
  folder is created by the app) and `manifest.example.json` (the 0.1 updater example). Old copies are
  still removed from user PCs by the updater's development-file rules.
- `README.md` rewritten for the current version (install, update, features, privacy).
- `PROJECT_HANDOFF.md` rewritten: folder layout, the signed update chain, module map, threading rules,
  data locations, tests and known limits.
- New `CLAUDE.md`: working rules, the full release workflow and the lessons of both audits.
- Kept: `CHANGELOG.md` and the asset `README.md` files (font and icon licences/sources).
- No program code changed.

## 0.4.2w — Second audit report (2026-11-20)

P1
- #1 `Update.py --resume` takes the same OS lock as the updater (exit 2 while an update runs); the launcher refuses to start during an update, blocks the start when the interrupted update cannot be finished, and asks (default «No») when the pending marker is left.
- #2 Files dropped by the new version are removed inside `file_transaction` (backup first) and come back when any later step, including writing the state, fails.
- #3 Update.bat has no unsigned route any more: without `scripts/fetch_updater.py` it stops with an installation error.
- #4 Package rollback: the snapshot keeps `==` and `name @ url` lines, packages added since are uninstalled, the result is compared with the snapshot (not only pip's exit code), and failures after the library step also restore the libraries.
- #5 Each installation has its own admin task (`LuxAI Jarvis (admin) <id>`, name in `.luxai_data/admin_task.txt`) and autostart value (`LuxAI_Jarvis_<id>`); a task/value is used, ended or deleted only when it starts this folder. The old shared ones are migrated when they belong here.
- #6 Clipboard-history paste and quick inserts: the activation must succeed and the foreground is checked again right before Ctrl+V; otherwise nothing is pasted and the text stays on the clipboard.

P2
- #7 A long spoken answer is one queue item; its pieces are fed one by one with one piece prefetched.
- #8 `save_settings` does not write config.json when nothing changed. #39 rollback writes back only saved keys (never an environment key) and records the old key before writing. #46 one key read per save.
- #9/#10 Reminders: the sign stays with the duration (negative refused); «remind me …» first means the rest is the message; the message before the time is kept; «07h30» uses one clock match for time and label. #18 Snooze saves first, closes only its own window, shows the reason on failure. #37 cancel-all writes once.
- #11 A failed conversion removes its reserved output (audio, video, GIF, images, PDF). #12 GIF frame durations follow the real timestamps. #13 Audio gaps after the first frame are kept and the resampler is flushed. #29 progress once per percent.
- #14 The clipboard is read with the Win32 API on a worker (Qt's reader is the fallback). #15/#16 one worker each for saves and picture encoding, in order, a waiting job replaced by a newer one; close waits up to 8 s for the last save. #17 the saved history loads on a worker (size checked first). #24 restoring after a quick insert keeps all formats and only when the clipboard is still Jarvis's own. #31 identity before truncation, cut items marked. #35 coalescing documented.
- #19 Downloads cleanup scans and moves on a worker; the day is marked only after a run without errors. #20 the UAC wait for admin mode runs on a worker. #21 known config fields are validated (clamped or dropped, original copied aside, user told). #22 turning dictation off during transcription invalidates it and releases the state. #23 chat and notification translations share one queued worker. #25 `python main.py` goes through the launcher checks.

P3/P4
- #26 Validated trigger entries are cached by the registry fingerprint; the 1 s poll runs only for schedules/events. #27 notifications are read on a worker. #28 chat views keep the last 400 messages. #30 the translator signature covers all model files and a loaded model is replaced after a repair. #32 long document diffs are debounced. #33 one ZIP decompression, signed digests reused for the state. #34 bounded taskkill/cleanup. #36 screenshots go to the clipboard from raw pixels, the PNG is written on a worker. #38 dictation waits for modifier release with a Qt timer. #40 Telegram signals carry the bot generation. #41 idle animation at 20 fps. #42 active-window tracking by WinEvent hook. #43 the start check reuses a positive result while the venv is unchanged. #44 clipboard popup refresh coalesced, search in one pass. #45 setup window reads at most 128K characters and refreshes the log once per tick. #48 config.json and .pyc files are no longer tracked or signed. #49 window options alone no longer rebuild the style sheet; phrase normalization done once. #50 a positive Tesseract check is reused for the same executable and language data.
- Not changed: #47 (the local LLM runs in a fresh isolated process per request on purpose — a native crash cannot take the window down; no profiling showed the start-up cost to matter yet).

## 0.4.2v — Last complex functions split (2026-11-20)

- #44 completed: no function is above complexity 40 any more. `VoiceListener.listen` (51 → under 40): the «stop» channel while Jarvis talks is `_BargeInDetector` (identical to the old inline logic on 2000 random frame sequences), plus `_playback_voiced`, `_transcribe_interrupt`, `_frame_detected`, `_report_capture_issues`. `run_task` (48 → under 40): `_finish_is_verified`, `_policy_error`, `_apply_clarification`. All voice, microphone and agent tests pass; the real microphone path was not exercised live.
- Checked live: an update to 0.4.2u went through the signed path end to end (Update.py signature in fetch_updater, all 484 archive files in Update.py).

## 0.4.2u — Installer fix, signed releases, resume journal, controlled libraries (2026-11-19)

- install_windows.ps1: a function returning one or no process is not a list under Set-StrictMode, so `.Count` stopped every install since 0.4.2r («The property 'Count' cannot be found»); call sites use @(). The launch check no longer treats a warning on stderr as a broken environment.
- #8 Signed releases: Ed25519 (RFC 8032, pure Python, checked against the RFC vectors). `release_manifest.json` (SHA-256 of every file) + `release_manifest.sig`, signed with a key kept only on the maintainer's PC (tests/sign_release.py). fetch_updater.py and Update.py verify the signature, every file of the archive and refuse older versions.
- #29 Resume journal: new files are staged on the same disk, a journal is written, then files are moved; an interrupted update is finished at the next start or update.
- #7 Libraries change only when requirements.txt changes (fingerprint in the state), only missing packages are installed, never «upgrade everything»; the exact old versions are restored on failure.
- #12 One atomic writer (`luxai/atomic_io.py`) with unique temporary names for config.json, commands, triggers, experience and keys.
- #44 Split: validate_step (table of checkers, identical on 4617 cases), execute_desktop_step (handler tables), _dispatch_command (five stages), _next_macro_step, validate_generated_macro, execute_plan; all unused imports removed. Still above complexity 40: `listen` (microphone loop) and `run_task` (agent loop).

## 0.4.2t — Update no longer fails on Onest.ttf (2026-11-19)

- A friend's update failed with «[WinError 5] Access is denied … luxai\\assets\\fonts\\Onest.ttf» and was rolled back. Cause: the setup window (WPF) used the fonts straight from luxai/assets/fonts, and WPF keeps a font file open while it is shown — only when that font is actually drawn, so it hit users with the default Onest font, not those with Fuzzy Bubbles. Reproduced: with the old window `os.replace` on Onest.ttf gives WinError 5; with the new one it succeeds.
- The window copies each font it needs into a private temporary folder. Update.py runs the CURRENT window from GitHub (a copy of the installed one only as a fallback, never from the folder it rewrites). A file held open for a moment is retried for about 6 s before the update restores the previous files.

## 0.4.2s — Update.bat bootstrap fixed (2026-11-19)

- In 0.4.2r the new `for /f` line started a quoted interpreter path (".venv\Scripts\python.exe"); cmd.exe strips the outer quotes of such a command and printed «The system cannot find the path specified», so Update.bat stopped before downloading. `call` in front keeps the quotes. Checked on the real installation: verified download, update, lock and temporary file removed; a second Update.bat gets «BUSY», a lock left by a crash is ignored. An installation that already has the 0.4.2r Update.bat repairs itself by running `.venv\Scripts\python.exe Update.py` once.

## 0.4.2r — Audit report of 2026-11-19 fixed (2026-11-19)

Numbers refer to the findings of «LuxAI_Local - Raport audit 2026-11-19.md». Tests: `tests/test_audit_fixes_042r.py` plus updated older tests.

- #1 Clipboard: data is read on the Qt loop 60 ms after `dataChanged` (reading OLE data inside the notification produced 0x8001010D / 0x80010108), errors go to logs/clipboard_error.log, the signal is disconnected and late events are refused on stop. #13 Big pictures are reduced before encoding, encoded on a worker; the history has a 160 MB budget and pinned pictures 64 MB. #14 The history is saved on a worker and flushed synchronously on close; save errors are logged and the previous file stays.
- #2 Video conversion keeps the source timestamps (variable frame rate, gaps, audio offset) and checks the output duration before reporting success. #20 ICO centres any picture on a square first. #21 Output names are reserved on disk (O_EXCL), so two conversions never share a file.
- #3 Dictation types only after the target window really became the foreground window; otherwise the text goes to the clipboard with a message. #4 Every dictation session has a generation; a cancelled, disabled or closing session never inserts later.
- #5 #6 Update/install close Jarvis also when started as `pythonw launch_windows.py`, end the admin task only when it belongs to THIS folder, wait until the processes really exited and stop before replacing files if Jarvis keeps running. run_windows.bat starts the admin task only for this folder.
- #7 The package versions are recorded (pip freeze) before an update and put back if the library step fails. #8 #28 Update.bat downloads Update.py through `scripts/fetch_updater.py`: one exact commit via the GitHub API, git blob hash checked, compiled, unique file name, and a bootstrap lock tied to the Update.bat window (a compromised repository would still need signed releases, which this project does not have). #29 A durable journal marks an update in progress: the next start warns, the next update re-applies everything; files dropped from the project are removed when unchanged (hashes in the state file). #30 The final message says when the restore is NOT complete. #42 Child-process time-outs end the whole process tree and are reported as time-outs.
- #9 An expired alarm rings before it is removed; a failed removal never loses it or rings twice. #15 Reminders keep their message («in five minutes to call Ana», «at 09:30 to call Ana») and only the first clause sets the time; a clock reminder shows its label. #16 «-5 minutes» is refused; long general questions («how long is left in this video») go to the chat. #17 NaN / infinite / absurd times are dropped on load. #18 The timer list changes only after the file was written. #19 Turning the extension off silences a ringing alarm and stops delayed checks. #33 A failing extension handler answers in the chat instead of breaking the command queue.
- #10 Offline translation kept a literal U+0001 instead of the punctuation (a backslash lost in a patch); a test now rejects control characters in all sources. #25 A model that fails to load is verified/repaired in the background and retried after its files change. #26 Chat translation runs on a worker (`AsyncReply` + `chat_reply`).
- #11 A config.json with a non-object root or broken JSON is copied to config.broken-*.json and reported once. #12 One Jarvis per installation folder (named mutex; a restarting Jarvis waits up to 10 s for the old one). #32 API keys and config.json are saved together: a failed config write puts the previous keys back.
- #22 #23 #24 Telegram: any malformed answer is a TelegramError, both threads end on every exit path, `running` follows the poller, and undelivered replies are reported in the chat.
- #27 OCR installation holds an inter-process file lock. #31 Long replies are spoken to the end in pieces. #34 The launch check is read-only and imports PySide6/numpy. #35 run_windows.bat reports a failed start. #36 The settings update handoff shows why it did not start. #37 #38 A window screenshot without a window, or with no destination, is refused; the message lists only real destinations. #39 Version letters after «z» («aa») compare as newer. #40 Voice warm-up errors log the stage, library version and output device. #41 The old OCR action runs on a worker. #43 Duplicate alias definitions removed.
- #44 / annex: all correctness-type lint findings fixed (F811, F841, F541, F601, B033, B013, PLW0602, unused imports where safe); dead consent texts removed (the consent itself was and is asked by `_allow_cloud_screenshots`). Not done in this release: splitting the very complex routing functions (C901 / PLR0912 / PLR0915) and the remaining 21 imports that tests patch by name.

## 0.4.2q — Discord mic found in Russian Discord (2026-11-19)

- The diagnostics log of 0.4.2p showed the real account-bar names in the user's Russian Discord: the microphone switch is «Заглушить» and the headphones switch «Откл. звук», both UI Automation toggles. `_MIC` now also matches «заглуш» (and Romanian «amuț»), and among buttons of the same kind a real toggle switch wins over a plain button, then the lowest one (the account bar, not the call panel). The diagnostics log was deleted after reading.

## 0.4.2p — Discord button diagnostics (2026-11-19)

- The first live try of «выключи микрофон в дискорде» fell back to the screenshot path: UI Automation found no Discord mic/deafen buttons. `read_buttons` now waits up to ~3 s for Chromium to build its accessibility tree, and when the buttons are still missing it writes what it sees (element count, button names and positions, toggle support) to `logs/discord_buttons.txt` — local only — so the search can be fitted to the real Discord.

## 0.4.2o — Command library like Luxify, Discord without the cloud (2026-11-19)

- Command library: groups show the real icon of the installed program (from its .exe through the Windows shell: Chrome, Telegram, Word, Discord, Steam…) on a rounded tile, the Windows group four blue panes, a missing program a simple glyph in its colour (`luxai/app_icons.py`; icons follow the theme through `ICON_APP_ROLE` / `ICON_PAD_ROLE` in `luxai/icons.py`). Counts are right-aligned with correct plurals («1 команда», «3 команды», «20 команд», «20 de comenzi»).
- «Управление Discord» is its own top-level group (as in Luxify) with 35 built-in commands Jarvis runs locally: microphone and headphones on/off, answer / decline / jump to a call, unread / channels / servers, direct messages, back / forward, quick switcher, search, pins, inbox, members, emoji, GIF, stickers, upload, soundboard, copy link, create group, scroll, settings, shortcuts. New action `discord_key` with a fixed allow-list of targets (`command_registry.discord_targets`).
- Discord microphone / headphones (`luxai/discord_audio.py`): the account-bar buttons are read through UI Automation (name + pressed state); already-right is reported, otherwise the button is toggled directly or Discord's own Ctrl+Shift+M / Ctrl+Shift+D is pressed, and the new state is read back. Voice requests use this first; the screenshot + cloud workflow is only the fallback when the state cannot be read, and without a cloud AI the shortcut is pressed with an honest «could not read the state». The old blind Ctrl+Shift+M with a confirmation question is gone.
- README in three languages: README_RU.txt and README_EN.txt beside README_RO.txt.
- `.gitattributes`, `.gitignore` and `manifest.example.json` are development files now (kept on GitHub, removed from installations); a stray debug file `.txt` from 0.4.2l is deleted.

## 0.4.2n — Update.bat works again (2026-11-19)

- 0.4.2l put «» quotes into comments of Update.bat and install_windows.bat. GitHub archives store batch files with LF line ends, and cmd.exe (with chcp 65001) misreads a LF-only batch file that has multi-byte characters: commands were cut («echo» → «ho», «if exist» → «exist») and the update did not run. Fixed three ways: the batch files are plain ASCII again, `.gitattributes` keeps them CRLF, and Update.py now always writes .bat/.cmd files with CRLF. Tests check all three.
- If Update.bat of 0.4.2l fails on another PC, run `.venv\Scripts\python.exe Update.py` in the Jarvis folder once — it installs the fixed files.

## 0.4.2m — Refresh button without a black background (2026-11-19)

- Live captions → «Что слушать»: the refresh button next to the program list was a bare QToolButton that Windows drew with a black square. It now has the same transparent rounded look as the section reset button (grey icon, accent-tinted hover).

## 0.4.2l — Setup window for Update.bat and install_windows.bat (2026-11-19)

- Update.bat and install_windows.bat now open a Jarvis window (`scripts/setup_ui.ps1`, built-in WPF — works before Python exists) and hide the console. Ideas taken from known installers: the Visual Studio Installer step list with ticks and per-step time, Steam's live internet-speed chart with speed / downloaded figures, Discord's compact borderless branded window with a soft accent glow, Windows 11 Fluent rounded corners, shadow and thin rounded progress bar.
- Shows: what is being done right now (pip package being checked or downloaded, files applied, translator download with MB of MB), overall progress and the time left (from step weights, the measured pace and the real download speed), the real internet speed (from the network adapters) with a chart, downloaded MB, elapsed time; «Подробнее» opens the full log. In Jarvis' accent, theme, font and language (from config.json; Windows language for a first install). At the end: «Запустить Jarvis» / «Закрыть», closes by itself after 60 s (waits while the log is open); on an error: the reason, the log open, «Открыть журнал».
- A running Jarvis of this folder is closed when the update or setup starts (the elevated one through its scheduled task), so files and libraries are not locked.
- The already-up-to-date path also checks OCR and the offline translator; install_windows.bat now installs the offline translator too.
- Update.py output and the window texts are in ru/ro/en; the window cannot be closed while working (only minimised), and if the updater stops unexpectedly the window says so.

## 0.4.2k — Translator installed by Update.bat, translation in the chat (2026-11-19)

- Update.bat now installs the offline translator itself (`python -m luxai.offline_translate`, ≈640 MB once, into the preserved `models/`). The download is pinned to one commit of the model repository and `model.bin` / `tokenizer.json` are checked by SHA-256; a damaged file is deleted, never loaded. If it fails (no internet), the update still succeeds and Jarvis downloads it on first use.
- Chat and voice: «переведи на английский: …», «переведи … на румынский», «как будет по-английски кошка», «translate to Romanian: …», «tradu în rusă: …», «cum se spune … în engleză» are answered by the offline translator in ≈0.4 s, without internet, and spoken with the voice of the translation's language. Without a named language a foreign text goes into Jarvis' language (Jarvis' own language into English). Also German, French, Spanish, Italian, Portuguese, Polish and Ukrainian as targets.
- Phrases like «переведи компьютер в спящий режим» or «переведи деньги маме» stay commands: without a named language the text must be in another language than the request word.
- No stray space before punctuation in translations.

## 0.4.2j — Only the offline translator (2026-11-19)

- Every translation now runs on this PC with the offline translator: live captions, read aloud, notifications and «Перевести» in the clipboard history (which no longer needs an API key). The cloud translation (`OnlinePlanner.translate_text`) and the slow GGUF translation (`translate_locally`, `strip_thinking`) are removed, with their tests; texts in the settings now say that nothing is sent anywhere for translation.
- Source languages: Russian, Ukrainian, English, Romanian, German, French, Spanish, Italian, Portuguese, Polish (new word/letter detector; Ukrainian is no longer read as Russian, Spanish no longer as French). Targets: ru/en/ro.
- One-word phrases («Да.», «Thanks!», «Nein?») come from a small dictionary — NLLB turned «Да.» into «Da, da. Ce?»; the output length is capped and subtitle dashes are removed.
- Live captions: the spoken language is voted over several checks until sure (a Romanian video was once locked as Russian for 30 s by one check on its intro), then re-checked every ~30 s.
- Checked with the real model on every path (read aloud, notifications, clipboard: 7 source languages × 3 targets, ≈0.5 s each) and live on YouTube: English → Romanian, Romanian → English, Russian → English.

## 0.4.2i — Offline translator (2026-11-19)

- New offline translator: NLLB-200 distilled 600M (CTranslate2 int8, ≈640 MB in `models/nllb-200-600M-ct2-int8`, kept by Update.bat, downloaded once in the background the first time caption translation is used). Measured on caption phrases: ≈0.3–0.8 s per phrase, while Gemini took 8–15 s today and returned nothing for about half of them; quality is nearly the same.
- Used first for live captions, read aloud, notification translation and the clipboard «Перевести»; the online model (then the local GGUF) is only the fallback when the model is missing or a language pair is not ru/en/ro.
- Each sentence is translated separately in one batch (NLLB otherwise drops the first of two half-sentences); Romanian output uses the correct ș/ț letters. The model is loaded when captions start, so the first phrase is not late.
- Checked live on YouTube: English → Russian, Romanian → Russian, Russian → Romanian; translations appear ≈0.5–1.2 s after each phrase.
- Model licence: CC-BY-NC 4.0 (non-commercial use).

## 0.4.2h — Live captions: right language, no invented text, translation only (2026-11-19)

- The main cause of nonsense: «Язык речи» = «Как у голосовых команд» forced Russian on English/Romanian videos, so Whisper "translated" and invented text. Now the default is «Определять самому»: the spoken language is detected once and re-checked about every 30 s (detecting on every pass would double the time). Checked on real YouTube videos in English, Romanian and Russian.
- Fewer hallucinations: Silero VAD skips music and noise; segments Whisper itself is unsure of, looping text and lone fillers («you», «Спасибо.») are dropped; a phrase is never shown twice; each phrase gets the end of the previous one as context.
- «Переводить» + «Показывать оригинал» off (now the default) shows only the translation — not the growing original; «…» waits until it arrives.
- Translations go one at a time (parallel requests overloaded Gemini: 8–60 s each), stale ones are skipped, and after 6 s without an answer the original is shown instead of «…» forever.

## 0.4.2g — Round scrollbars (2026-11-18)

- Scrollbars are thin round pills like in Luxify: the handle is 6 px wide with a 3 px radius. Before, the 5 px radius on an 8 px handle was more than half its width, so Qt drew square corners. Still highlighted with the accent colour on hover.

## 0.4.2f — Run Jarvis as administrator (2026-11-18)

- New in Settings → System: «Запускать Jarvis от имени администратора». It creates one Windows scheduled task «LuxAI Jarvis (admin)» with the highest rights (Windows asks once); `run_windows.bat` and the Windows autostart then start Jarvis through it, without a prompt each time. Needed to read text from and press keys in programs started as administrator (Windows UIPI). Turning it off deletes the task. If the Windows prompt is declined, the switch returns to off.

## 0.4.2e — Clear message for apps started as administrator (2026-11-18)

- Found the Discord read-aloud cause: the running Discord was started as administrator, and Windows (UIPI) blocks keys and UI Automation from ordinary programs into such windows, so Ctrl+C sent by Jarvis never arrived. Read aloud and Discord shortcuts now detect this and say so plainly («Discord запущен от имени администратора… откройте его обычным способом») instead of a vague copy error.

## 0.4.2d — Faster read aloud, Discord selections (2026-11-18)

- Read aloud starts about twice as fast: the copied text is checked at once instead of after 150 ms, the first piece is short (about one sentence, ≤180 characters; then ≤450), and Fish playback starts with a smaller buffer. Measured F8 → first sound for a Russian text: 1.8 s → 0.9 s.
- No pauses between pieces of a long text: while one piece plays, the next one is already synthesized by Fish (kept only in memory, dropped on «стоп»).
- Without translation every piece is read in its own language (an English text with English pronunciation).
- Discord and other Electron apps: Jarvis now waits up to ~2 s for the copy, tries Ctrl+Insert if Ctrl+C did nothing, and finally reads the selection through Windows UI Automation (no clipboard needed).

## 0.4.2c — Chrome in «Что слушать» (2026-11-18)

- Live captions «Что слушать» listed only programs that had a Windows audio session at that moment; Chrome closes its sound service while silent, so it was missing. Now every open program with a window is offered too (those playing sound first), e.g. «Только программа: chrome». Capturing one program still includes all of its processes.

## 0.4.2b — Sharp logo at every size (2026-11-18)

- The logo inside the Jarvis icon is now a vector outline (traced from the master `jarvis-logo.png` with sub-pixel accuracy) instead of an embedded 256 px picture, which Qt drew without smoothing and looked pixelated at small sizes. Smooth, sharp edges from 16 px to full screen; the icon file shrank from 72 KB to 7.5 KB. On a light accent the logo turns dark as before.

## 0.4.2a — New Jarvis logo (2026-11-18)

- The robot icon is replaced by your new logo, white on the accent-coloured tile (orange with your theme) — in the app corner, the window/taskbar, the tray and Task Manager (Jarvis.exe now takes your accent colour too and is rebuilt when it changes). On a very light accent the logo turns dark automatically.
- Five layouts were compared at 256/64/32/20 px on dark and light backgrounds; white-on-accent-tile stayed the clearest everywhere. The cleaned master is `luxai/assets/icons/jarvis-logo.png`.

## 0.4.2 — Avatar: listening looks different (2026-11-18)

- While Jarvis listens, the avatar has its own animation: the orb becomes round and still (it "holds its breath", a slow attentive pulse, the core gently glows) and thin sonar waves leave it and fade out. Speaking stays as it was — the orb swells and wobbles with the voice. The states blend smoothly into each other; the settings preview shows it too.

## 0.4.1z — "Jarvis" with its icon in Task Manager (2026-11-18)

- Task Manager showed Jarvis as "Python" without an icon (it ran inside pythonw.exe). `run_windows.bat` now builds `.venv\Scripts\Jarvis.exe` when needed — the same Python interpreter with the description/product name "Jarvis" and the Jarvis icon (`luxai/jarvis_exe.py`) — and starts Jarvis through it, as one process. Every build is test-started first; if it cannot be built, pythonw.exe is used as before.
- Helper processes treat Jarvis.exe like pythonw.exe (console Python for probes and the PDF reader). An existing Windows autostart entry is updated to start Jarvis the same way.

## 0.4.1y — Clear icon for the visual avatar (2026-11-18)

- «Визуальный аватар» has its own icon: an orb of rings with a small sparkle (drawn for the project, `luxai/assets/icons/project/avatar-orb.svg`) instead of the unclear «orbit». Project icons are looked up before the Lucide set.

## 0.4.1x — Avatar keeps its original look (2026-11-18)

- The orb looks exactly as before 0.4.1w again (its bright rings and glow). Only the edge behaviour stays: at a screen edge in mini mode it is pressed flat against the edge instead of being cut off; it still never disappears when you switch apps or take a screenshot.

## 0.4.1w — Avatar at the edge like Luxify, always on screen (2026-11-18)

- At a screen edge (mini mode) the orb is no longer cut off by the screen: it stays whole and is pressed flat against the edge — flat side with rounded corners, the inner rings flattened too; in a corner against both edges. While you carry it, it is round again.
- The orb looks closer to Luxify: one hue, darker outside and brighter inside (never washed out to white), distinct rings with soft edges.
- The avatar no longer disappears when you switch apps or take a screenshot: the screenshot overlay (Win+Shift+S), Start and search are not treated as full-screen apps; only a game/video/presentation that Windows itself reports, for 2 seconds, hides it, and it comes back at once. Every second it is put back on top and on a screen, whatever another window did.

## 0.4.1v — Plugin settings save themselves (2026-11-18)

- No more «Сохранить» in plugin settings: every change (switch, slider, list, colour, key, program chips, reset) is saved by itself half a second later and applied at once. The side panel shows «Сохраняю…» → «✓ Сохраняется автоматически».
- Keys and tokens (e.g. the Telegram bot token) are saved when you finish typing them (Enter or clicking elsewhere), never half-typed.
- Leaving the page saves a change made just now, without asking; only an invalid value asks whether to leave without it.
- A value changed outside the page (the avatar dragged to a new place) is kept and not overwritten by the open page.

## 0.4.1u — Avatar goes into the corner (2026-11-18)

- The avatar now really reaches the screen edges and corners: snapping is measured from the visible orb, not from its window with the glow margin (which kept it ~40 px away), and it sticks to both edges at once in a corner.
- Mini mode tucks the orb behind the edge(s): about half shows at a side, about a quarter in a corner — like Luxify.
- The 3×3 position grid places the orb itself 12 px from the edges; the magnet distance is a little larger (80 px from the orb).

## 0.4.1t — Visual avatar like Luxify (2026-11-18)

- **Визуальный аватар** works: a living orb above all windows. It "breathes" by itself and reacts to sound — Jarvis's own voice (only this program's sound), all PC sound, the microphone, chosen programs or everything at once. Loudness only; nothing is recorded or sent.
- Colour by state: running a command (green), answering by voice (yellow), error (red, 2.5 s), microphone off / quiet mode / prefix mode (permanent). Every state has its own colour and switch; the base colour is your own or the Jarvis theme colour.
- Look and motion: size, opacity, glow, speed, intensity, amplitude, smoothness; reaction on/off, sensitivity and strength.
- Behaviour: 3×3 position picker or your own place (drag it — remembered), monitor, lock (clicks pass through), drag, stick to edges, mini mode at the edge (half hidden), above windows, hide in full-screen apps. «Основные»: on/off, start with the program, 30/60 fps.
- The settings page has a live preview cycling Ждёт → Слушает → Говорит → Выполняет команду. Voice: «покажи аватар» / «скрой аватар».
- Settings pages got colour swatches and percent sliders.

## 0.4.1s — One font everywhere (2026-11-18)

- With the «Fuzzy Bubbles» font, Russian text («Главная», «История команд»…) used to switch to Onest: Fuzzy Bubbles has no Cyrillic letters at all. Pangolin, a similar hand-written font with Cyrillic and Romanian letters (SIL OFL, bundled, no download at runtime), now fills in exactly the letters Fuzzy Bubbles lacks, so the whole interface keeps one look.
- The application font is set with the full fallback list, so widgets that draw text themselves follow it too.

## 0.4.1r — Live captions in real time (2026-11-18)

- Captions now appear while someone speaks: the text grows about every 1.2 s (≈0.3 s in «Мгновенно»), and continuous speech in videos is split into phrases of at most 5 s, cut at the quietest moment between words (nothing is lost). Before: the medium model needed ~4 s per pass and a phrase could wait up to 12 s.
- Captions use their own fast model: new setting «Скорость распознавания» — «Мгновенно» (tiny), «Быстро и точно» (small, default) or «Как у голосовых команд».
- A finished phrase is not recognised twice when only silence came after the last pass.

## 0.4.1q — Live captions like Luxify (2026-11-18)

- **Живые субтитры** work now: an always-on-top bar with the text of what plays on the PC (video, call, stream). Show it with the button «Показать субтитры» (it also turns the plugin on), an optional key, or by voice «покажи субтитры» / «скрой субтитры»; «×» on the bar hides it; drag it by the handle on the left — the place is remembered («Вернуть вниз по центру» resets it).
- «Что слушать»: all PC sound (Jarvis's own voice is muted while it speaks) or only one program (Windows process loopback — e.g. only Discord or the browser), with a refresh button for the list of programs that play sound.
- Speech language: as for voice commands, auto-detect, Russian, English, Romanian. Recognition is local (Whisper); partial text appears while someone speaks, the phrase is finished after a short pause.
- «Перевод»: finished phrases translated by the cloud AI into the program's or a chosen language, under the original (or instead of it).
- «Вид»: text size, background opacity, 1–3 lines, position. Settings page like Luxify: Субтитры, Звук и язык, Перевод, Вид, Клавиша.

## 0.4.1p — Clipboard history like Luxify (2026-11-17)

- **История буфера обмена** rebuilt after Luxify: Основное, Клавиша (Alt+Win+V by default), «Что и как долго помнить» (25–500 items, keep for 1/7/30 days or without limit, remember after restart, pictures), «Не запоминать» (program chips: KeePass, KeePassXC, Bitwarden, 1Password… plus your own), «Нейросеть».
- Remembers text with its formatting and pictures (screenshots, copied images) with thumbnails. Pinned items never age and are never pushed out.
- Window at the cursor: search, Enter pastes, Shift+Enter pastes without formatting, Ctrl+P pins, Del deletes; right click or the sparkle button — «Перевести», «Исправить ошибки», «Кратко» (cloud AI; the result goes to the clipboard and to the top of the history).
- Privacy: copies marked "not for history" by programs (password managers) and copies from listed programs are never stored, nor are Jarvis's own temporary pastes. On disk the history is encrypted with Windows DPAPI for your account.
- Voice: «вставь предыдущее» / «paste the previous one» / «lipește precedentul».

## 0.4.1o — Faster Discord calls (2026-11-17)

- «Позвони Hanzo в Discord»: after the chat with the person is opened and its header verified, Jarvis looks once at the call state and presses Discord's own "start call" shortcut (Ctrl+'), then one more look confirms the call is ringing. Before, it needed about eight AI looks (header twice, call state twice, finding the phone icon twice) — about 15 seconds. The phone-icon click stays only as a fallback when the shortcut does nothing; never a second call.

## 0.4.1n — Fast Discord control (2026-11-17)

- Discord's own keyboard shortcuts by voice/text (RU/RO/EN): answer/decline a call, back to the current call, next/previous server, channel and unread channel, direct messages ↔ last server, Ctrl+K quick switcher, search, pinned, inbox, members, emoji/GIF/stickers, upload, soundboard, copy channel link, create group, shortcut list, settings, scroll the chat. With the word "Discord" — or without it while Discord is the active window (Discord-only commands). Keys are layout independent.
- «Проверь Discord» / «с кем я в звонке»: one screenshot and one AI look report the mic, headphones, call, incoming call, the open chat and the profile on the right.
- Mic and headphones: the state is still read before and confirmed after, but the switch now uses Discord's Ctrl+Shift+M / Ctrl+Shift+D instead of clicking a tiny icon, and the extra zoom is only taken when the state is unclear — faster and never misses.
- The AI knows the user's Discord layout (account bar bottom-left: mic, headphones, settings; DMs above; call buttons top-right; profile panel on the right) and may use Discord shortcuts while reaching a visual goal.

## 0.4.1m — Breaks like Luxify (2026-11-17)

- **Перерывы** rebuilt after Luxify: three separate reminders with their own interval — eyes 20-20-20 (every 20 min), stretch (55), water (90) — counting only real activity. Being away 5+ minutes, locking or sleeping the PC counts as a break and restarts counting.
- A card appears in the screen corner without taking the focus: «Сделал», «Отложить» (10 min) or «Пропустить»; optional voice. «Сегодня» shows breaks done/skipped for today only; «Попробовать сейчас» shows a sample without touching the counters.
- «Не мешать»: quiet hours, games/full-screen windows and presentations, calls (another app uses the mic/camera), Jarvis quiet mode and Windows "Do not disturb". A delayed reminder comes once, half a minute after the game/call ends.
- Settings pages support rows that combine a choice and a switch, and info notes inside a section.

## 0.4.1l — Autoscroll pointer like in Windows apps (2026-11-17)

- Middle-click autoscroll no longer leaves a fixed ↕ circle on the screen. The mouse pointer itself shows the state, as in browsers and the Claude app: a light ▲•▼ disc at rest, a small ring with ▼ below while scrolling down and ▲ above while scrolling up.

## 0.4.1k — Scrolling without a mouse wheel (2026-11-17)

- Scroll bars are wider (14 px) and clearly visible, and turn the accent colour on hover/drag; the old 9 px dark handle was nearly invisible and hard to grab.
- Middle-click autoscroll everywhere, like in browsers: press the wheel button, move the mouse up or down (faster further away); any click or Esc stops it.
- Drag-to-scroll: press the left button on an empty background and drag, like on a phone (buttons, fields, lists and sliders behave as before).
- PageUp / PageDown / Home / End scroll the page under the cursor when you are not typing in a field.

## 0.4.1j — Command editor inside the window (2026-11-17)

- «Новая команда» and «Изменить команду» open inside the Commands page instead of a separate window, like in Luxify: the window header shows «‹ Jarvis | Команды | Новая команда», its back arrow cancels, Save returns to the list and the navigation rail stays visible.
- Recording actions still minimizes Jarvis while you work and now restores a maximized window as maximized.

## 0.4.1i — Folders in AI chat, PDF fix, all tests green (2026-11-17)

- **Folders can be attached to the AI chat**: «+» → «Папку…», drag & drop or paste a folder. Jarvis sends its structure plus the text of its text/code files (same 24 000-character budget); `.git`, `node_modules`, virtual environments and links/junctions are skipped, secret-looking files (`.env`, `.pem`, `.key`, `id_rsa`…) are listed but never read, and PDF/DOCX/images inside are listed by name. A folder snapshot is read-only.
- **PDF attachments work again with pypdf 7**: the safety limits are now set through `pypdf.overwrite_configuration`; setting the removed module constants raised «The PDF could not be read safely (DeprecationError)».
- A model-path test used this PC's real model path as a "path from another PC"; it now uses a path that cannot exist. The whole suite passes with no failures.

## 0.4.1h — Read foreign text in Jarvis' language (2026-11-17)

- **Чтение вслух**: selected text in another language (English, Romanian, Russian, German, French…) is translated into Jarvis' language first and read right away, piece by piece — the first piece starts after about a second while the rest is still translating. A "Reading language" option (Same as Jarvis / RU / RO / EN) and a switch are in the settings. Long selections are now read completely (previously speech stopped after 700 characters).
- **Озвучка уведомлений**: a notification in another language is translated into the language chosen in Jarvis before it is read; the app name stays as is. Translated text is also what «что пришло» reads.
- The cloud AI from Jarvis settings translates (only the selected/notification text); without it the local model is used; if both fail, the original is read with a short notice. The privacy note was updated accordingly.

## 0.4.1g — Instant checks and instant Fish voice (2026-11-17)

- On start Jarvis checks cloud AI and sends one tiny request to the selected local GGUF model in the background, so «Дополнения» shows both as working (green) without waiting for the first question. Nothing is loaded when local AI is off, has no model or was already confirmed.
- Fish Audio replies start playing while the audio is still downloading (first sound ≈1 s instead of waiting for the whole reply; measured 4.1 s → 1.0 s for one sentence). Stop still interrupts immediately.
- Startup warms Fish without sending text or using provider quota: audio modules, the output device at 24 kHz and one TLS handshake with api.fish.audio.

## 0.4.1f — Fixes from a real-PC check (2026-11-17)

- Read aloud, clipboard history, quick inserts and the converter failed with a Russian keyboard layout («Не удалось скопировать выделенный текст»): pyautogui maps letters through the current layout, so Ctrl+C / Ctrl+V were never sent. Shortcuts now use layout-independent virtual-key codes everywhere, including saved commands like «нажми Ctrl+S»; held Alt/Shift are released first and slow apps get up to 1.2 s to fill the clipboard.
- Notification reader: every non-system app is read by default (previously only messengers, so Codex/Claude/PowerShell toasts were silently skipped); Store apps get real names («Codex» instead of «App»); Explorer, Snipping Tool and other system toasts are ignored; apps known only by a GUID are read without a name.
- Smart dictation: silence no longer reaches Whisper (it invented «С вами был Игорь Негода.» and typed it); subtitle-credit hallucinations are filtered.
- Checked live on Windows with a Russian layout: read aloud by a real key press, clipboard history paste, quick insert, dictation typing with a new line, screenshots, converter on an Explorer selection, right-Ctrl double tap and real Windows notifications.

## 0.4.1e — Notification reader (2026-11-16)

- **Озвучка уведомлений** now works: new Windows notifications are read aloud ("Telegram: Мама — Купи хлеба"). Jarvis reads the current user's notification database read-only, starts from "now" (old notifications are never read) and keeps only the last 20 texts in memory — nothing is written to disk, logged or sent to AI.
- Luxify-like settings: read right away or only on request; per-app switches that fill in by themselves (messengers and mail on by default); Sender / With text / Full; text length; app name; links → «ссылка»; codes → «пришёл код»; several from one app as one sentence.
- Stays silent while the PC is locked, in quiet hours, in fullscreen games/video, during calls (another app uses the mic or camera; always-listening assistants are ignored), in Jarvis quiet mode, and waits while you dictate. Missed ones are kept for «что пришло».
- Voice: «что пришло», «прочитай последнее сообщение», «не читай уведомления» / «читай уведомления», «не беспокой» (an hour); optional "repeat last" key and a sample button.

## 0.4.1d — Converter like Luxify (2026-11-16)

- **Конвертер** now works through a circle at the cursor: select files in Explorer or on the desktop (or copy a picture) and press Ctrl+Alt+X; choose with the mouse, arrow keys or digits. Optional "screen area" key: draw a region and get the circle for that snapshot. "Choose files…" works from the settings page too.
- Images (Pillow): format (PNG/JPG/WebP/ICO/BMP), compress, downsize (75/50/25 %, 1920/1280 px), rotate/mirror, crop (drag a box), strip metadata, to PDF (several pages), to clipboard. Audio: MP3, M4A, WAV, FLAC, OGG (Opus), OPUS. Video: to MP4 (H.264+AAC), compress, to GIF, audio to MP3, no sound — all via the FFmpeg already bundled in PyAV, nothing to download.
- Results get new names next to the file or in a chosen folder; originals are never changed. Work runs in the background with a progress pill and a "Done" notification.
- Settings follow Luxify: Основные (with note), Клавиши, Результат, Сектора круга (two-column switch grid), Компонент для видео, Оформление; the right-hand navigation now scrolls.

## 0.4.1c — Timers and alarms (2026-11-16)

- **Таймеры и будильники** now work by voice or typed chat in RU/RO/EN: «поставь таймер на 10 минут», «таймер на полтора часа», «напомни через 20 минут выключить плиту», «разбуди в 7:30», «будильник на 7 утра», «сколько осталось», «отмени таймер», «отмени все будильники»; "set a timer for 5 minutes", "wake me up at 6 am"; «pune un cronometru de 10 minute», «trezește-mă la 7:30».
- Several timers at once, saved in `.luxai_data/timers.json` so alarms survive a restart (missed ones ring on start). When time is up: tray notification, spoken message, repeating sound for a configurable time and an always-on-top window with Snooze / Stop.
- The settings page has an «Активные» card with live countdowns, cancel buttons and quick "timer for N minutes" / "alarm at HH:MM". A saved command with the same phrase always wins; with the module off Jarvis says how to enable it instead of guessing.

## 0.4.1b — PC Control via Telegram (2026-11-16)

- **PC Control** now works: your own Telegram bot shows your command folders as buttons (under the message or as a chat keyboard) and runs saved, enabled commands by button or by text phrase.
- Security: the bot token is stored in Windows DPAPI, never in config.json; only the owner Telegram ID can run anything (before it is set, the bot only replies with the sender's ID); strangers get no answer; messages sent while Jarvis was off are skipped; agent commands are not exposed.
- "Ask before run" commands are confirmed with Run/Cancel buttons in Telegram; risky (⚠) steps still ask on the PC. Optional result notifications in Telegram and optional spoken replies on the PC. Start-with-app switch, connection check, "Open bot" and a clear message when another program (e.g. Luxify) uses the same bot.
- Settings follow the Luxify layout: Подключение, Меню в Telegram, Ответы, Основные, with a live bot-menu preview.

## 0.4.1a — Luxify-style plugin settings (2026-11-16)

- Plugin settings open inside the Extensions page instead of a separate window: «‹ Jarvis | Расширения | Plugin» in the header with a back arrow, section cards with per-section reset, segmented choices, sliders, key chips with «Назначить», and a right panel with «Как это работает», section navigation, «Сбросить всё» and «Сохранить» (enabled only with unsaved changes; leaving asks to save).
- Smart dictation settings follow the Luxify layout: Основные, Клавиша и режим, Голосом, Язык и текст, Нейросеть and a live «Проверка» box where dictation lands while Jarvis is focused, plus «Последняя диктовка» with Копировать. Dependent options are greyed out until they apply.

## 0.4.1 — Smart dictation (2026-11-16)

- **Умная диктовка** now works: double-tap the right Ctrl (or a custom shortcut), speak, and the text is typed where the cursor is. Modes: hold, or press — speak — press with automatic stop after a configurable pause.
- Optional start by voice: «Джарвис, напиши …» types the rest at once; «Джарвис, напиши» records until a pause. Start phrases are configurable.
- Local Whisper recognition (reuses the already loaded model), spoken punctuation in RU/RO/EN including new line/paragraph, quotes, brackets and «удали последнее слово»; duplicate marks from Whisper are merged. Optional AI polish sends only the text to the configured cloud provider.
- The command listener ignores the microphone while dictating, so dictated words are never executed as commands. Start/stop sounds, a non-focus-stealing status pill, a 5-second test and "copy last dictation" (kept in memory only).

## 0.4.0 — Extensions page (2026-11-16)

- Add a new **Extensions** (Расширения) button to the left navigation rail, between Addons and Jarvis AI, with its own page: Plugins / Connections tabs, Tiles / List views, a topics panel with counts, search, an "only enabled" filter and an enabled counter.
- Catalog 22 plugins in 5 topics (voice and sound, text and clipboard, desktop, PC and home control, files/screen/streams). Every plugin has a settings dialog generated from a validated schema; state is stored under `extensions` in `config.json`, invalid values fall back to defaults and secrets are never stored there.
- Working plugins: Read aloud (selected text, global key), Clipboard history (search, pin, paste at cursor; skips password/code-like texts, kept in memory only), Quick inserts (snippets with {date}/{time}), Breaks (active-time reminders that respect idle time and fullscreen apps), Media keys, Converter (PNG/JPG/WebP/ICO/PDF copies next to originals), Screenshots (screen or active window to clipboard and file) and Downloads cleanup (preview, confirmation, Recycle Bin only for old installers).
- The other 14 plugins are shown with their settings and a locked switch marked "Скоро" until their runtime exists; the page never pretends a module works.
- Plugin shortcuts use a separate RegisterHotKey listener, so they do not interfere with command shortcuts; registration errors are shown on the plugin card.

## 0.3.9g — Luxify-inspired settings and listening controls (2026-11-04)

- Load the project Fuzzy Bubbles Regular/Bold files from `assets/fonts` locally, replace the Arial selector entry and migrate saved Arial selections. Keep Onest as the Cyrillic fallback.
- Extend the compact settings rows, segmented language/listening controls, switches and section navigation to follow the supplied Luxify references. Keep existing automatic saving.
- Add Windows hold-to-talk listening with a configurable key, editable exact phrases for prefix mode, quiet mode and microphone shutdown, and a phrase that cooperatively stops the remaining command chain.
- Add conservative offline saved-command recognition tolerance and optional lexical paraphrases. Exact triggers keep priority; ambiguous or unrelated requests do not select a guessed command.
- Bundle the OFL-licensed Onest font with Russian and Romanian glyphs, offer font selection, and add a confirmation dialog for resetting voice-output preferences.
- Add an Updates section with the installed version, real GitHub version checks, last-check results, release notes and the existing Windows updater. An optional automatic check runs once per session when Settings opens; installation remains a separate action. Preserve settings, models, keys and personal commands.

## 0.3.9.e — optional Fish Audio Russian Jarvis voice (2026-10-30)

- Add Fish Audio as an optional speech provider with the user's linked Russian Jarvis voice preset and editable public voice link/ID.
- Explicitly request the current free API model `s2.1-pro-free`; never omit the model header or switch to a paid model. Require a personal Fish key and internet, and explain that spoken text is sent to Fish.
- Keep Fish credentials in the existing Windows DPAPI storage, separately from chat providers; support `FISH_API_KEY`, editing-finished key saving, removal and translated status without plaintext config keys.
- Bound requests and audio, reject redirects, sanitize errors and preserve playback volume, speed, cancellation and actual-output interruption. Startup preparation makes no Fish API call. Piper remains the default local provider.
- Continue from the maintainer's corrected `0.3.9.d` version string; preserve personal data and source-only Markdown/test cleanup.

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
