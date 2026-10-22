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

    def _simple_action(self, text, confirm_callback):
        t = text.lower().strip()
        if any(x in t for x in ["what time", "time is it", "cat e ceasul", "cât e ceasul", "который час", "сколько времени"]):
            return datetime.datetime.now().strftime("Ora locală: %H:%M")
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
            "Ești Nexora AI, un AGENT desktop local care trebuie să încerce să execute cererile prin instrumentele disponibile, nu doar să ofere sfaturi. Pentru acțiuni pe care le poate efectua aplicația, folosește instrumentele și codul agentului. Instrucțiuni obligatorii: "
            "Răspunde direct, clar și concis, de regulă în 1-4 propoziții. "
            "Răspunde numai în limba în care ți-a scris utilizatorul. "
            "Nu adăuga traduceri în engleză, nu pune traduceri sau explicații între paranteze "
            "și nu repeta întrebarea. Tradu sau explică un termen doar dacă utilizatorul cere asta. "
            "Nu inventa fapte și nu pretinde că ai făcut acțiuni pe care nu le-ai executat. Dacă nu există instrument pentru o acțiune, spune clar limita. "
            "Nu genera comenzi shell. Dacă nu știi ceva, spune asta simplu.\\n"
            f"Utilizator: {text}\\nNexora AI:"
        )
        result = llm(prompt, max_tokens=160, temperature=0.3, stop=["Utilizator:", "Пользователь:", "User:"])
        return result["choices"][0]["text"].strip() or "Nu am un răspuns acum."
