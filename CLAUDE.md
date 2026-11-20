# CLAUDE.md — read this first, every session

LuxAI Local («Jarvis»): a Windows 10/11 desktop voice assistant (Python 3.11, PySide6).
Repo: https://github.com/negevshopmd-svg/LuxAI_local · Dev checkout: `C:\Users\vlad\Desktop\LuxAI_local_repo`
· The user's installed copy: `C:\Users\vlad\Desktop\LuxAI_Local` (updated only through `Update.bat`).
Architecture and module map: **PROJECT_HANDOFF.md**. History of every version: **CHANGELOG.md**.

## Talking to the user
- Reply in **Romanian** (the user writes Romanian, sometimes without diacritics). Code, comments,
  commits and CHANGELOG are in English.
- The app UI is trilingual RU / RO / EN. Every new user-visible text needs all three
  (`_tr3(ru, en, ro, language)` in extensions, `tr("русский")` + a line in `luxai/ui_i18n.py` in main).

## Release workflow — EVERY change, in this order
1. Implement; run the related tests (`.venv` of the install: `C:\Users\vlad\Desktop\LuxAI_Local\.venv\Scripts\python.exe`,
   with `PYTHONUTF8=1`; plain `python` here has no pytest/PySide6).
2. Bump `version.txt` (0.4.2w → 0.4.2x → …).
3. `CHANGELOG.md` (new section on top) **and all three** `README_RO.txt`, `README_RU.txt`, `README_EN.txt`:
   the version must be in the FIRST line of each, plus a short note for the user.
4. `python tests/build_runtime_manifest.py`, `git add -A`.
5. Full suite: `PYTHONUTF8=1 <venv python> tests/run_suite.py` (≈1650 tests, ~2.5 min, run in background). Must be 0 failures.
6. `git add -A`, then **`<venv python> tests/sign_release.py`** — mandatory; signs `release_manifest.json`
   (Ed25519, key DPAPI-encrypted in `%USERPROFILE%\.luxai_release\signing_key.bin`, never in the repo).
7. Commit on branch `claude/0.4.0-extensions` ending with
   `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, push, then fast-forward `main`
   (`git push origin claude/0.4.0-extensions:main`).
8. Update the user's copy: `cmd //c 'C:\Users\vlad\Desktop\LuxAI_Local\Update.bat < NUL'`
   (it closes Jarvis itself), then `run_windows.bat`, then check Jarvis really runs
   (`Get-Process Jarvis` — an elevated Jarvis hides its command line).

## Hard rules
- **Never** put API keys, bot tokens, personal paths, logs or user data in git, config.json or logs.
  Secrets live only in Windows DPAPI (`luxai/secure_keys.py`). The user's email is private.
- Do not read or expose the Telegram/Luxify tokens; do not copy Luxify code or assets (only the look is "inspired").
- Never send or type messages in the user's Discord (testing UI state is fine, sending is not).
- `.bat` files: **ASCII only, CRLF** (`.gitattributes`); `for /f` strips quotes → use `call`.
- `.ps1` files: UTF-8 **with BOM**, PowerShell 5.1, StrictMode → wrap "maybe one item" results in `@()`;
  stderr of a native exe is fatal under `ErrorActionPreference Stop`.
- Dev-only files (all `*.md`, `tests/`, `.github/`, `.gitattributes`, `.gitignore`) stay on GitHub;
  `Update.py::is_development_file` keeps them off the user's PC.
- config.json and `*.pyc` are NOT tracked (the user's config is preserved by the updater).
- Write patch scripts with the Write tool, not bash heredocs: heredocs mangle backslashes
  (`\n`, `\\`, `\b` became control characters once — audit #10).

## Lessons from the two audits (2026-11-19: 44 findings, 2026-11-20: 50 findings)
Most bugs came from testing only the happy path with mocks. Before calling a change done, ask:
- **What if it fails exactly here?** (half-applied update, disk full, file locked, UAC declined,
  network gone). State + files + libraries must be changed as ONE transaction and restored together.
- **What if it runs twice at once?** (two updates, launcher during update, two Jarvis copies, two
  installations on one PC, a burst of clipboard events). Use the same OS lock / mutex / generation number.
- **Is this on the Qt UI thread?** Disk I/O with retries, clipboard OLE, SQLite, UAC waits, PNG encoding,
  folder scans, model loading → worker (`luxai/background.py`: `LatestWorker` coalesces, `SerialQueue`
  keeps order) and a Signal back to the GUI.
- **Can the target change?** Re-check the foreground window right before Ctrl+V / typing.
- **Is the input hostile?** negative/Unicode-minus numbers, NaN, huge values, lists where strings are
  expected (config is validated by `main.validate_config`).
- **Probe for real**, not only with mocks: real clipboard, real files through the converter, a real update
  through `Update.bat`. Say plainly in the reply what was NOT tested live.
- Fix the cause and look at the whole place, not just the reported line (half-fixes reappeared as «Parțial»).
- No function above complexity 40.

## Graphify (code graph of this repository)
The user connected Graphify (MCP tools `mcp__…__graphify_*`, repository `negevshopmd-svg/LuxAI_local`, indexed
from GitHub `main` — push first, then the index follows). Use it before editing instead of wide greps:
- `graphify_impact` (`include_risk=true`) on the symbol you change → callers/callees and hotspot files;
- `graphify_callers`, `graphify_tests_for` → who breaks and which tests to run;
- `graphify_file_neighbors` → what a file imports and who imports it; `query_graph` for «where does X happen?».
Check `freshness.commit` in the answer: it describes the indexed commit, not the working tree.
Visual module map (130 modules, zones, imports, tests): https://claude.ai/artifact/YCQ7u1eEcAmt3h5xxmjMQx
Most imported (change carefully): `fast_intents` (22 modules), `icons` (19), `secure_keys` (18), `api_providers` (17),
`visual_click` (15); biggest files: `main.py` (5.3k lines), `luxai/extensions_runtime.py` (4.0k),
`luxai/ui_extension_settings.py` (2.0k), `Update.py` (1.8k).

## Where things are (short)
- Start: `run_windows.bat` → `launch_windows.py` (single-instance mutex, refuses during an update,
  finishes an interrupted update via `Update.py --resume` under the updater lock) → `main.py`.
- Update: `Update.bat` → `scripts/fetch_updater.py` (exact commit, git hash, signature) → `Update.py`
  (signed archive, staging + journal, transaction incl. removed files, package snapshot/restore,
  setup window `scripts/setup_ui.ps1`).
- Install/repair: `install_windows.bat` → `scripts/install_windows.ps1`.
- Admin mode: per-installation scheduled task `LuxAI Jarvis (admin) <id>` (name in
  `.luxai_data/admin_task.txt`), autostart value `LuxAI_Jarvis_<id>`.
- Extensions (plugins): catalog `luxai/extensions_catalog.py`, behaviour `luxai/extensions_runtime.py`.
- Offline translator: `luxai/offline_translate.py` (NLLB-200 600M, CTranslate2 int8, pinned revision).
- Live captions: `luxai/live_captions.py` («Hybrid»: fast draft + precise correction). Film captions in
  advance: `luxai/film_captions.py` + `browser_extension/` (Chrome/Edge MV3, bridge 127.0.0.1:47321).
  Chrome 137+ cannot load unpacked extensions from the command line — test with Edge and a temporary profile.
- CPU only (the AMD GPU is not usable by CTranslate2); one Whisper pass costs nearly the same for any
  length (30 s window): base ≈0.4 s, small ≈1.2 s, turbo ≈4.4 s, large-v3 ≈6.1 s on the Ryzen 7 5800X.
