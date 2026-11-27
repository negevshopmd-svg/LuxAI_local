# LuxAI Local — Jarvis

A voice assistant for **Windows 10/11 (64-bit)** that works mostly on your own PC: speech recognition,
voices, translation, OCR and an optional local AI model run locally. A cloud AI (your own key for
Gemini, OpenAI, DeepSeek and others) is optional and only plans unfamiliar commands — every action is
still checked and executed by Jarvis on Windows.

Interface and replies in **Russian, Romanian and English**.

User guides with the notes of every version (these are installed with the program):
[Română](README_RO.txt) · [Русский](README_RU.txt) · [English](README_EN.txt) ·
full history: [CHANGELOG.md](CHANGELOG.md)

## Install
1. Download this repository as a ZIP (Code → Download ZIP) and unpack it, e.g. on the Desktop.
2. Run `install_windows.bat` — it creates the program's own Python environment and downloads the
   speech, OCR and translation models (a setup window shows the progress).
3. Start Jarvis with `run_windows.bat`.

## Update
Run `Update.bat`. It closes Jarvis, downloads the latest version, **checks the signature of every
file**, and keeps your settings, keys, commands and models. If anything fails, the previous version
(files and libraries) is put back.

## What it can do
- Voice and chat commands, a command library with folders, hotkeys, schedules and events.
- Opens apps, sites, files and Steam games; controls volume, windows and the keyboard.
- Discord control without the cloud (microphone, headphones, calls, channels).
- Extensions: text helper (fix / improve / shorten / translate / reply to selected text), action circle
  (radial menu: your commands, window actions, media, search), smart
  dictation, notification reader, read aloud, live captions, clipboard history,
  quick inserts, visual avatar, breaks, PC Control from your own Telegram bot, media keys,
  timers and alarms, converter (images, audio, video, GIF), screenshots, downloads cleanup.
- Offline translator (NLLB-200) for captions, reading aloud, notifications and «translate …» in chat.

## Privacy
API keys and the Telegram token are stored only with Windows DPAPI, never in `config.json` or logs.
Do not publish keys, logs or personal files.

For developers: start with [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md) and [CLAUDE.md](CLAUDE.md).
