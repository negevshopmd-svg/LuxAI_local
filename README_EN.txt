LUXAI LOCAL (JARVIS) 0.4.2p — UPDATE 2026-11-19

0.4.2p: Discord buttons (microphone, headphones) are searched more patiently; when they
are not found, Jarvis writes what it sees to logs\discord_buttons.txt (local only).

0.4.2o: Commands look like Luxify: real program icons (Chrome, Telegram, Word,
Discord, Steam) and a separate «Manage Discord» group — 35 commands Jarvis runs by
itself, without the cloud: mute/unmute the microphone and headphones, answer or
decline a call, channels, servers, search, mentions and more. The Discord
microphone and headphones are now read and pressed directly (Windows accessibility),
without screenshots; a cloud screenshot is only the fallback.
.gitattributes, .gitignore and manifest.example.json stay on GitHub only.

0.4.2n: Update.bat works again (in 0.4.2l the Windows console cut its commands).
If Update.bat prints «'ho' is not recognized», run once in the Jarvis folder:
.venv\Scripts\python.exe Update.py

0.4.2m: The refresh button next to «What to listen to» (captions) has no black square.

0.4.2l: Update.bat and install_windows.bat show a Jarvis-style window: what is done
now, time left, internet speed, amount downloaded. A running Jarvis is closed first.

0.4.2k: Update.bat installs the offline translator. In the chat and by voice:
«translate to Romanian: …», «переведи на английский: …», «how do you say … in
Russian» — translated in ~0.4 s without internet.

0.4.2j: All translation is offline, on this PC (captions, read aloud,
notifications, clipboard «Translate»). Also understands Ukrainian, German, French,
Spanish, Italian, Portuguese and Polish.

0.4.2i: Offline NLLB translator (~640 MB in models\): ~0.5 s per phrase.

0.4.2h: Live captions detect the language (English, Romanian, Russian), do not
invent text, and show only the translation when translation is on.

0.4.2f: Settings → System: «Run Jarvis as administrator» — to read text from and
press keys in programs started as administrator.

0.4.2: The visual avatar listens and speaks differently; new Jarvis logo.


INSTALL
1. Download the archive from GitHub and extract it to any folder.
2. Run install_windows.bat — a setup window opens (Python, libraries, OCR, local
   AI, offline translator). Nothing to click.
3. Run run_windows.bat.

UPDATE
Run Update.bat in the Jarvis folder. An open Jarvis is closed by itself. The window
shows the steps, time and speed; at the end — «Launch Jarvis».
Settings, keys, models and the .venv folder are kept. Rollback copies are temporary.

WHERE THINGS ARE
config.json — settings; .luxai_data — your commands, history, OCR; .luxai_secrets —
keys (encrypted by Windows); models — models (never removed by an update).

Full version history: CHANGELOG.md on GitHub
https://github.com/negevshopmd-svg/LuxAI_local
Do not publish keys or personal data.
