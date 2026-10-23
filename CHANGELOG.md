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
