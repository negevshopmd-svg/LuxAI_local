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
