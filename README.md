# LuxAI_local

Voice-controlled Jarvis assistant for Windows 10/11 (64-bit).

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
