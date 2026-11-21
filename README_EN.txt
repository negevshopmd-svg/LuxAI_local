LUXAI LOCAL (JARVIS) 0.4.3e — UPDATE 2026-11-21

0.4.3e: Fixes from the fifth audit (18 points). Jarvis now downloads the film sound itself, with full
HTTPS certificate checks for every piece of the film. Captions keep working after «Back» in the
browser, for films with shifted timestamps and after a page reload. The extension (1.3.0) records
nothing while captions are off. Reminders with «tomorrow forecast» / «seara» / «un sfert de oră» are
read correctly; «minus 5 minutes» is refused. «Prepare ahead» is now 3 minutes by default, and at
most one minute while paused.
IMPORTANT: after the update, click «Reload» on the Jarvis extension in chrome://extensions.

0.4.3d: Scroll bars no longer have a dark stripe behind them, and the section icons in the
extension settings no longer have a square background.

0.4.3c: Fixes from the fourth audit (19 points). The Chrome extension (1.2.0) sends nothing to
Jarvis while captions are off, prefers the tab you are looking at and starts correctly on a new
episode in the same player. The film sound goes through a local filter that allows no connection
to this PC or the home network. New setting «Prepare ahead» (10/3/1 min). The reminder
«at 08:00 tomorrow to call Ana» gets the right label. When the program chosen for captions starts
later, the capture switches to it by itself.
IMPORTANT: after the update, click «Reload» on the Jarvis extension in chrome://extensions.

0.4.3b: Fixes from the third audit (29 points). The Chrome extension now has a secret pairing key
with Jarvis (other extensions or programs cannot talk to it), follows one player, stops when the tab
closes and handles pause and buffering. Reminders «at 08:00 … 5 minutes» and «PM» in the text are
read correctly; pasting no longer pastes something copied in between.
IMPORTANT: after the update, click «Reload» on the Jarvis extension in chrome://extensions.

0.4.3a: Captions no longer stop on «COMError … Catastrophic failure» (a momentary Windows audio
error, e.g. when Chrome restarts its audio part). The capture restarts by itself, finds the
program again after a restart, and falls back to all PC sound if it cannot. Details go to
logs\captions_error.log.

0.4.3: When captions start, Jarvis asks whether to install the Chrome extension (Yes / Later /
Don't ask again). «Yes» opens a guide: Chrome opens, the chrome://extensions address and the
folder path are copied for you, and the window turns green as soon as the extension works.
Jarvis remembers that the extension is installed.

0.4.2z: Captions in advance for films in the browser. With the Jarvis extension for Chrome/Edge,
the part of the film already loaded is recognised and translated BEFORE it plays, and every line
word appears exactly when it is spoken in the film (also after seeking). Install once: Extensions → Live captions → Chrome
extension → Install…, then in Chrome turn on «Developer mode», click «Load unpacked» and choose
the browser_extension folder. Does not work with protected video (Netflix, Disney+ etc.);
there the normal live captions stay.

0.4.2y: Live captions have a new «Hybrid» mode (the default): the text and its translation
appear ~1-2 seconds after the words, while the person is still talking, then a precise model
corrects the line. Before, the translation came only at the end of a phrase (up to ~6 s).
Quiet speech (a video with low volume) is no longer lost. Settings → Recognition model now
also offers Whisper Large-v3.

0.4.2x: The documentation on GitHub is cleaned up: old, outdated guides were removed and
README.md and PROJECT_HANDOFF.md were rewritten for the current version. The program itself is unchanged.

0.4.2w: Fixes from the second audit (50 points). Pasting from the clipboard history can no
longer land in another window; long spoken answers are read from the start;
«remind me in -5 minutes» is refused and the reminder text is no longer lost;
GIFs keep their real length; the window no longer freezes on the clipboard, notifications,
downloads cleanup or administrator mode. Updates are safer: removed files and libraries
come back when something fails, and Jarvis does not start during an update.
Each Jarvis copy now has its own administrator task and its own autostart.

0.4.2v: Internal code simplified (the microphone loop and the agent loop are split into
small parts), no change in behaviour.

0.4.2u: install_windows.bat works again («The property 'Count' cannot be found»).
Updates are digitally signed, finish by themselves after an interruption, and libraries
change only when the project's requirements change.

0.4.2t: The update no longer fails with «Access is denied … Onest.ttf»: the update window
kept the app's font open. It now uses a temporary copy.

0.4.2s: Update.bat of 0.4.2r did not start the verified download («The system cannot find
the path specified»). If you have it, run once in the Jarvis folder:
.venv\Scripts\python.exe Update.py

0.4.2r: Fixed the findings of the 19 November audit: the clipboard no longer causes native
errors, dictation never types into another window, video conversion keeps frame times,
alarms are not lost, reminders keep their message, translation keeps punctuation and no
longer freezes the window, Telegram does not hang, one Jarvis per folder, the update
closes Jarvis safely, checks the updater against GitHub's hash, restores libraries on
failure and tells the truth about the restore.

0.4.2q: The Discord microphone works without the cloud in Russian Discord too: the button is
«Заглушить», the headphones «Откл. звук»; Jarvis reads and presses them directly.

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
