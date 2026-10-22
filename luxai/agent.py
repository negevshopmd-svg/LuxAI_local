import json, os, re, subprocess, webbrowser, datetime
from pathlib import Path
from luxai.screen import capture_screen, read_screen_text

class LocalAgent:
    def __init__(self, config):
        self.config = dict(config)
        self.llm = None
        self.loaded_path = None

    def update_config(self, config):
        self.config = dict(config)

    def _load_llm(self):
        path = self.config.get("llm_model_path", "")
        if not path or not Path(path).is_file():
            return None
        if self.llm is not None and self.loaded_path == path:
            return self.llm
        from llama_cpp import Llama
        self.llm = Llama(model_path=path, n_ctx=2048, n_threads=max(2, (os.cpu_count() or 4)-2), n_batch=256, verbose=False)
        self.loaded_path = path
        return self.llm

    def _open_application(self, app):
        """Try common Windows launch methods; return True only when launch was requested successfully."""
        import shutil
        import os
        import glob

        uri_schemes = {
            "telegram": "tg://resolve",
            "discord": "discord://",
            "spotify": "spotify:",
        }
        if app in uri_schemes:
            try:
                os.startfile(uri_schemes[app])
                return True
            except (OSError, AttributeError):
                pass

        executable_names = {
            "telegram": ["Telegram.exe"],
            "discord": ["Discord.exe"],
            "chrome": ["chrome.exe"],
            "firefox": ["firefox.exe"],
            "edge": ["msedge.exe"],
            "spotify": ["Spotify.exe"],
        }
        for exe in executable_names.get(app, []):
            found = shutil.which(exe)
            if found:
                try:
                    subprocess.Popen([found], close_fds=True)
                    return True
                except OSError:
                    pass

        local = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        candidates = {
            "telegram": [
                os.path.join(local, "Telegram Desktop", "Telegram.exe"),
                os.path.join(program_files, "Telegram Desktop", "Telegram.exe"),
                os.path.join(program_files_x86, "Telegram Desktop", "Telegram.exe"),
            ],
            "discord": [
                os.path.join(local, "Discord", "Update.exe"),
                os.path.join(local, "Discord", "app-*", "Discord.exe"),
            ],
            "chrome": [
                os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(local, "Google", "Chrome", "Application", "chrome.exe"),
            ],
            "firefox": [
                os.path.join(program_files, "Mozilla Firefox", "firefox.exe"),
                os.path.join(program_files_x86, "Mozilla Firefox", "firefox.exe"),
            ],
            "edge": [
                os.path.join(program_files, "Microsoft", "Edge", "Application", "msedge.exe"),
                os.path.join(program_files_x86, "Microsoft", "Edge", "Application", "msedge.exe"),
            ],
            "spotify": [
                os.path.join(local, "Microsoft", "WindowsApps", "Spotify.exe"),
                os.path.join(local, "Spotify", "Spotify.exe"),
            ],
        }
        for pattern in candidates.get(app, []):
            for path in glob.glob(pattern):
                args = [path, "--processStart", "Discord.exe"] if app == "discord" and path.lower().endswith("update.exe") else [path]
                try:
                    if os.path.isfile(path):
                        subprocess.Popen(args, close_fds=True)
                        return True
                except OSError:
                    continue

        start_menu_dirs = [
            os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
            os.path.join(program_files, r"Microsoft\Windows\Start Menu\Programs"),
            os.path.join(program_files_x86, r"Microsoft\Windows\Start Menu\Programs"),
        ]
        needles = {
            "telegram": ("telegram",),
            "discord": ("discord",),
            "chrome": ("chrome", "google chrome"),
            "firefox": ("firefox",),
            "edge": ("edge", "microsoft edge"),
            "spotify": ("spotify",),
        }.get(app, (app,))
        for folder in start_menu_dirs:
            for shortcut in glob.glob(os.path.join(folder, "**", "*.lnk"), recursive=True):
                if any(n in os.path.basename(shortcut).lower() for n in needles):
                    try:
                        os.startfile(shortcut)
                        return True
                    except OSError:
                        pass
        return False

    def _simple_action(self, text, confirm_callback):
        t = text.lower().strip()
        if any(x in t for x in ["what time", "time is it", "cat e ceasul", "cât e ceasul", "который час", "сколько времени"]):
            return datetime.datetime.now().strftime("Ora locală: %H:%M")
        # Short, natural responses to greetings; no model needed.
        normalized = re.sub(r"[!?,.\s]+", " ", t).strip()
        greetings = {
            "привет", "здравствуй", "здравствуйте", "доброе утро", "добрый день",
            "добрый вечер", "хай", "hello", "hi", "hey", "salut", "bună",
            "buna", "bună ziua", "buna ziua", "bună dimineața", "buna dimineata",
            "bună seara", "buna seara",
        }
        if normalized in greetings:
            if any(word in normalized for word in ("привет", "здравствуй", "здравствуйте", "доброе", "добрый", "хай")):
                return "Привет! Я Nexora. Чем помочь?"
            if normalized in {"hello", "hi", "hey"}:
                return "Hi! I'm Nexora. How can I help?"
            return "Salut! Sunt Nexora. Cu ce te pot ajuta?"
        # App-launch intents in Romanian, Russian and English.
        app_aliases = {
            "telegram": ["telegram", "телеграм", "телеграмм"],
            "discord": ["discord", "дискорд"],
            "chrome": ["chrome", "google chrome", "гугл хром"],
            "firefox": ["firefox", "файрфокс"],
            "edge": ["microsoft edge", "edge", "эдж"],
            "spotify": ["spotify", "спотифай"],
        }
        open_verbs = ["open", "launch", "start", "run", "deschide", "pornește", "porneste",
                      "открой", "запусти", "включи", "abrir"]
        if any(v in t for v in open_verbs):
            for app, aliases in app_aliases.items():
                if any(alias in t for alias in aliases):
                    if not confirm_callback(f"Deschide {app.capitalize()}"):
                        return "Acțiune anulată."
                    if self._open_application(app):
                        return f"Am deschis {app.capitalize()}."
                    return f"Nu am găsit {app.capitalize()} instalat. Verifică meniul Start sau instalarea aplicației."
        if any(x in t for x in ["open notepad", "deschide notepad", "открой блокнот"]):
            if confirm_callback("Deschide Notepad"):
                subprocess.Popen(["notepad.exe"])
                return "Am deschis Notepad."
            return "Acțiune anulată."
        if any(x in t for x in ["open calculator", "deschide calculator", "открой калькулятор"]):
            if confirm_callback("Deschide Calculator"):
                subprocess.Popen(["calc.exe"])
                return "Am deschis Calculator."
            return "Acțiune anulată."
        if any(x in t for x in ["open explorer", "deschide explorer", "открой проводник"]):
            if confirm_callback("Deschide File Explorer"):
                subprocess.Popen(["explorer.exe"])
                return "Am deschis File Explorer."
            return "Acțiune anulată."
        if any(x in t for x in ["open browser", "deschide browser", "открой браузер"]):
            if confirm_callback("Deschide browserul implicit"):
                webbrowser.open("about:blank")
                return "Am deschis browserul implicit."
            return "Acțiune anulată."
        if any(x in t for x in ["read screen", "citește ecranul", "прочитай экран"]):
            try:
                p = capture_screen()
                txt = read_screen_text(p, self.config.get("tesseract_path", ""))
                return ("Text detectat: " + txt[:1800]) if txt.strip() else "Nu am detectat text. Verifică instalarea Tesseract."
            except Exception as e:
                return f"Nu am putut citi ecranul: {e}"
        return None

    def handle(self, text, confirm_callback=lambda _: False):
        action = self._simple_action(text, confirm_callback)
        if action is not None:
            return action
        llm = self._load_llm()
        if llm is None:
            return ("Nu este selectat niciun model AI local. Apasă «Alege model AI (.gguf)» și selectează un model. "
                    "Comenzile de bază pentru aplicații pot funcționa și fără model.")
        prompt = (
            "Ești Nexora, asistentul desktop local al utilizatorului. Vorbește ca Nexora, nu te prezenta ca un model AI generic. "
            "Răspunde direct și natural, de obicei în 1-2 propoziții scurte. La un salut simplu, răspunde cu un salut scurt și întreabă cum poți ajuta. "
            "Nu povesti raționamentul intern, nu descrie analiza pe care o faci, nu repeta mesajul utilizatorului și nu spune lucruri precum «Okay, the user said...». "
            "Afișează numai răspunsul final pentru utilizator; nu include blocuri <think> sau comentarii despre instrucțiuni. "
            "Răspunde numai în limba utilizatorului. Nu adăuga traduceri sau explicații între paranteze decât dacă sunt cerute. "
            "Nu inventa fapte și nu pretinde că ai executat acțiuni pe care nu le-ai făcut. Nu genera comenzi shell. "
            f"Utilizator: {text}\nNexora:"
        )
        result = llm(prompt, max_tokens=120, temperature=0.3, stop=["Utilizator:", "Пользователь:", "User:", "<|im_end|>"])
        answer = result["choices"][0]["text"].strip()
        # Defensively remove explicit reasoning tags if a model emits them anyway.
        answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.IGNORECASE | re.DOTALL).strip()
        answer = re.sub(r"^<think>.*?(?:</think>|$)", "", answer, flags=re.IGNORECASE | re.DOTALL).strip()
        return answer or "Sunt aici. Cu ce te pot ajuta?"
