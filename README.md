# LuxAI_local

Voice-controlled Jarvis assistant for Windows 10/11 (64-bit).

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
