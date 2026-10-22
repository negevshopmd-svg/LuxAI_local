import json, os, re, subprocess, webbrowser, datetime
import urllib.parse
from pathlib import Path
from luxai.screen import capture_screen, read_screen_text
from luxai.steam_games import GAMES, local_game_intent, launch_steam_game
from luxai.fast_intents import strip_wake_name, quick_reply, has_launch_verb
from luxai.file_actions import create_user_item, list_user_items, parse_file_intent, safe_name, ALLOWED_LOCATIONS
from luxai.desktop_actions import execute_desktop_step
from luxai.action_catalog import CATALOG, validate_step

class LocalAgent:
    def __init__(self, config):
        self.config = dict(config)
        self.llm = None
        self.loaded_path = None
        self.history = []
        self.max_history_messages = 10
        self.last_execution_success = False
        self.last_executed_plan = None

    def update_config(self, config):
        self.config = dict(config)

    def _load_llm(self):
        path = self.config.get("llm_model_path", "")
        if not path or not Path(path).is_file():
            return None
        if self.llm is not None and self.loaded_path == path:
            return self.llm
        from llama_cpp import Llama
        self.llm = Llama(
            model_path=path,
            n_ctx=1536,
            n_threads=max(2, min(8, (os.cpu_count() or 4) - 1)),
            n_batch=128,
            verbose=False,
        )
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
            "steam": "steam://open/main",
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
            "steam": ["Steam.exe"],
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
            "steam": [
                os.path.join(program_files_x86, "Steam", "Steam.exe"),
                os.path.join(program_files, "Steam", "Steam.exe"),
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
            "steam": ("steam",),
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

    def _response_language(self, text=""):
        """Use configured language for UI/actions, detect script when set to auto."""
        selected = str(self.config.get("language", "auto") or "auto").lower()
        if selected in ("ru", "ro", "en"):
            return selected
        if re.search(r"[а-яё]", text, re.IGNORECASE):
            return "ru"
        if re.search(r"\b(?:open|launch|hello|hey|please|start)\b", text, re.IGNORECASE):
            return "en"
        return "ro"

    def _say(self, ru, ro, en=None, text=""):
        language = self._response_language(text)
        return ru if language == "ru" else (en or ro) if language == "en" else ro

    def _simple_action(self, text, confirm_callback):
        t = text.lower().strip()
        # Respond to short greetings and thanks without loading the GGUF.
        simple = quick_reply(text, self._response_language(text))
        if simple is not None:
            return simple
        # File operations have a trusted local implementation, no AI needed.
        file_intent = parse_file_intent(text)
        if file_intent is not None:
            return self._perform_file_action(text, file_intent, confirm_callback)
        if (
            any(x in t for x in ["what time", "time is it", "cat e ceasul", "cât e ceasul"])
            or re.search(r"\b(?:сколько|скока)\s+(?:сейчас\s+)?врем(?:ени|я)\b|\bкоторый\s+час\b", t)
        ):
            return self._say("Сейчас ", "Ora este ", "It's ", text) + datetime.datetime.now().strftime("%H:%M")
        # Fast offline Steam launch for common voice commands. The game ID is
        # hardcoded here, never copied from an AI-generated CMD command.
        game = local_game_intent(text)
        if game in GAMES:
            app_id, title = GAMES[game]
            if not confirm_callback(self._say(f"Запустить {title}", f"Pornește {title}", f"Launch {title}", text)):
                return self._say("Действие отменено.", "Acțiune anulată.", "Action cancelled.", text)
            if launch_steam_game(app_id):
                self.last_execution_success = True
                self.last_executed_plan = {"action": "launch_game", "target": game}
                return self._say(
                    f"Запускаю {title} через Steam.",
                    f"Pornesc {title} prin Steam.",
                    f"Launching {title} through Steam.",
                    text,
                )
            return self._say(
                f"Не удалось запустить {title}. Проверьте установку Steam.",
                f"Nu am putut porni {title}. Verifică instalarea Steam.",
                f"Could not launch {title}. Check Steam installation.",
                text,
            )
        # App-launch intents in Romanian, Russian and English.
        app_aliases = {
            "telegram": ["telegram", "телеграм", "телеграмм", "телегу", "телеграму"],
            "discord": ["discord", "дискорд"],
            "chrome": ["chrome", "google chrome", "гугл хром"],
            "firefox": ["firefox", "файрфокс"],
            "edge": ["microsoft edge", "edge", "эдж"],
            "spotify": ["spotify", "спотифай"],
            "steam": ["steam", "стим"],
        }
        if has_launch_verb(t):
            for app, aliases in app_aliases.items():
                if any(alias in t for alias in aliases):
                    if not confirm_callback(self._say(f"Открыть {app.capitalize()}", f"Deschide {app.capitalize()}", f"Open {app.capitalize()}", text)):
                        return self._say("Действие отменено.", "Acțiune anulată.", "Action cancelled.", text)
                    if self._open_application(app):
                        self.last_execution_success = True
                        self.last_executed_plan = {"action": "open_app", "target": app}
                        return self._say(f"Открыл {app.capitalize()}.", f"Am deschis {app.capitalize()}.", f"Opened {app.capitalize()}.", text)
                    return self._say(
                        f"Не удалось найти {app.capitalize()} на компьютере.",
                        f"Nu am găsit {app.capitalize()} instalat.",
                        f"Could not find {app.capitalize()} on this computer.",
                        text,
                    )
        if any(x in t for x in ["open notepad", "deschide notepad", "открой блокнот"]):
            if confirm_callback(self._say("Открыть Notepad", "Deschide Notepad", "Open Notepad", text)):
                subprocess.Popen(["notepad.exe"])
                return self._say("Открыл Блокнот.", "Am deschis Notepad.", "Opened Notepad.", text)
            return self._say("Действие отменено.", "Acțiune anulată.", "Action cancelled.", text)
        if any(x in t for x in ["open calculator", "deschide calculator", "открой калькулятор"]):
            if confirm_callback(self._say("Открыть Calculator", "Deschide Calculator", "Open Calculator", text)):
                subprocess.Popen(["calc.exe"])
                return self._say("Открыл Калькулятор.", "Am deschis Calculator.", "Opened Calculator.", text)
            return self._say("Действие отменено.", "Acțiune anulată.", "Action cancelled.", text)
        if any(x in t for x in ["open explorer", "deschide explorer", "открой проводник"]):
            if confirm_callback(self._say("Открыть File Explorer", "Deschide File Explorer", "Open File Explorer", text)):
                subprocess.Popen(["explorer.exe"])
                return self._say("Открыл Проводник.", "Am deschis File Explorer.", "Opened File Explorer.", text)
            return self._say("Действие отменено.", "Acțiune anulată.", "Action cancelled.", text)
        if any(x in t for x in ["open browser", "deschide browser", "открой браузер"]):
            if confirm_callback(self._say("Открыть browserul implicit", "Deschide browserul implicit", "Open browserul implicit", text)):
                webbrowser.open("about:blank")
                return self._say("Открыл браузер.", "Am deschis browserul implicit.", "Opened the default browser.", text)
            return self._say("Действие отменено.", "Acțiune anulată.", "Action cancelled.", text)
        minimize_phrases = ["сверни все окна", "свернуть все окна", "minimize all windows", "minimize every window", "minimize all", "minimize windows", "minimizează toate ferestrele", "minimizeaza toate ferestrele"]
        if any(phrase in t for phrase in minimize_phrases):
            if not confirm_callback(self._say("Свернуть все окна", "Minimizează toate ferestrele deschise", "Minimize all windows", text)):
                return self._say("Хорошо, окна не тронуты.", "Bine, nu am schimbat ferestrele.", "Okay, windows left as they were.", text)
            try:
                import ctypes
                user32 = ctypes.windll.user32
                SW_MINIMIZE = 6
                minimized = 0
                callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
                def minimize_window(hwnd, _):
                    nonlocal minimized
                    if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
                        user32.ShowWindow(hwnd, SW_MINIMIZE)
                        minimized += 1
                    return True
                user32.EnumWindows(callback_type(minimize_window), 0)
                return self._say(f"Свернул окон: {minimized}.", f"Am minimizat {minimized} ferestre.", f"Minimized {minimized} windows.", text)
            except Exception as exc:
                return self._say(f"Не удалось свернуть окна: {exc}", f"Nu am putut minimiza ferestrele: {exc}", f"Could not minimize windows: {exc}", text)
        if any(x in t for x in ["read screen", "citește ecranul", "прочитай экран"]):
            try:
                p = capture_screen()
                txt = read_screen_text(p, self.config.get("tesseract_path", ""))
                return (self._say("Текст на экране: ", "Text detectat: ", "Screen text: ", text) + txt[:1800]) if txt.strip() else self._say("Текст не найден. Проверьте Tesseract.", "Nu am detectat text. Verifică instalarea Tesseract.", "No text detected. Check Tesseract.", text)
            except Exception as e:
                return self._say(f"Не удалось прочитать экран: {e}", f"Nu am putut citi ecranul: {e}", f"Could not read screen: {e}", text)
        return None

    def _perform_file_action(self, text, plan, confirm_callback):
        """Perform a constrained file operation only after user confirmation."""
        action = plan.get("action")
        location = plan.get("location", "desktop")
        if location not in ALLOWED_LOCATIONS:
            return self._say(
                "Можно работать только с рабочим столом, документами и загрузками.",
                "Pot lucra doar pe Desktop, în Documents și Downloads.",
                "I can work only on Desktop, Documents and Downloads.", text,
            )
        if action == "list_files":
            try:
                names = list_user_items(location)
                self.last_execution_success = True
                names = names[:20]
                return self._say(
                    "Файлы: " + (", ".join(names) if names else "папка пуста"),
                    "Fișiere: " + (", ".join(names) if names else "folderul este gol"),
                    "Files: " + (", ".join(names) if names else "folder is empty"),
                    text,
                )
            except (OSError, ValueError) as exc:
                return self._say(
                    f"Не могу прочитать папку: {exc}",
                    f"Nu pot citi folderul: {exc}",
                    f"Cannot list folder: {exc}", text,
                )
        if action not in ("create_file", "create_folder"):
            return None
        try:
            valid_name = safe_name(plan.get("target", ""), is_folder=action == "create_folder")
        except ValueError:
            return self._say(
                "Недопустимое имя файла или папки.",
                "Nume de fișier sau folder nepermis.",
                "Invalid file or folder name.", text,
            )
        label = "папку" if action == "create_folder" else "файл"
        if not confirm_callback(self._say(
            f"Создать {label} «{valid_name}» ({location})?",
            f"Creez {valid_name} ({location})?",
            f"Create {valid_name} ({location})?", text,
        )):
            return self._say("Действие отменено.", "Acțiune anulată.", "Action cancelled.", text)
        try:
            path = create_user_item(
                action, valid_name, location,
                content=plan.get("content", ""),
            )
            self.last_execution_success = True
            return self._say(
                f"Создано: {path.name} ({location}).",
                f"Creat: {path.name} ({location}).",
                f"Created: {path.name} ({location}).", text,
            )
        except (OSError, ValueError) as exc:
            return self._say(
                f"Не удалось создать: {exc}",
                f"Nu am putut crea: {exc}",
                f"Could not create: {exc}", text,
            )

    def remember(self, text, answer):
        self.history.extend([
            {"role": "user", "content": str(text)[:1000]},
            {"role": "assistant", "content": str(answer)[:1500]},
        ])
        self.history = self.history[-self.max_history_messages:]

    def handle_fast(self, text, confirm_callback=lambda _: False):
        self.last_execution_success = False
        self.last_executed_plan = None
        command = strip_wake_name(text, self.config.get("wake_prefix", "Jarvis"))
        if not command:
            response = self._say("Слушаю.", "Te ascult.", "I'm listening.", text)
        else:
            response = self._simple_action(command, confirm_callback)
        if response is not None:
            self.remember(text, response)
        return response

    def execute_plan(self, text, plan, confirm_callback=lambda _: False):
        """Execute only local allowlisted actions from a validated online plan."""
        self.last_execution_success = False
        if not isinstance(plan, dict):
            return None
        action = plan.get("action")
        target = plan.get("target", "")
        answer = None
        if action in ("create_file", "create_folder", "list_files"):
            result = self._perform_file_action(text, plan, confirm_callback)
            if result:
                self.remember(text, result)
            return result
        desktop_features = {
            "noop", "open_website", "type_text", "hotkey", "press_enter",
            "save_document", "mouse_double_click", "mouse_click", "mouse_scroll",
            "mouse_move", "speak_text", "speak_ready", "speak_done",
            "volume_up", "volume_down", "lock_screen",
        }
        if action in desktop_features:
            try:
                validated = validate_step(plan)
            except (TypeError, ValueError):
                return "Некорректные параметры действия."
            mandatory_approval = action in {
                "type_text", "hotkey", "press_enter", "save_document",
                "mouse_double_click", "mouse_click", "mouse_scroll",
                "mouse_move", "lock_screen",
            }
            title = CATALOG[action]["title"]
            if mandatory_approval and not confirm_callback(
                "⚠ Подтвердите действие: " + title +
                (f" — {validated['target'][:100]}" if validated["target"] else "")
            ):
                return self._say("Действие отменено.", "Acțiune anulată.", "Action cancelled.", text)
            if action == "open_website" and not confirm_callback(
                f"Открыть сайт: {validated['target']}"
            ):
                return self._say("Действие отменено.", "Acțiune anulată.", "Action cancelled.", text)
            try:
                answer = execute_desktop_step(validated)
                self.last_execution_success = True
                if answer:
                    self.remember(text, answer)
                return answer
            except Exception as exc:
                return self._say(
                    f"Не удалось выполнить «{title}»: {exc}",
                    f"Nu am putut executa «{title}»: {exc}",
                    f"Could not execute «{title}»: {exc}", text,
                )
        if action == "reply" and isinstance(plan.get("reply"), str):
            answer = plan["reply"][:700].strip() or None
        elif action == "time":
            self.last_execution_success = True
            answer = self._say("Сейчас ", "Ora este ", "It's ", text) + datetime.datetime.now().strftime("%H:%M")
        elif action == "open_app" and target in {
            "telegram", "discord", "chrome", "firefox", "edge",
            "spotify", "steam", "notepad", "calculator", "explorer",
        }:
            if not confirm_callback(self._say(f"Открыть {target}", f"Deschide {target}", f"Open {target}", text)):
                answer = self._say("Действие отменено.", "Acțiune anulată.", "Action cancelled.", text)
            else:
                builtins = {
                    "notepad": "notepad.exe",
                    "calculator": "calc.exe",
                    "explorer": "explorer.exe",
                }
                if target in builtins:
                    try:
                        subprocess.Popen([builtins[target]])
                        success = True
                    except OSError:
                        success = False
                else:
                    success = self._open_application(target)
                self.last_execution_success = bool(success)
                answer = self._say(
                    f"Открыл {target}." if success else f"Не удалось открыть {target}.",
                    f"Am deschis {target}." if success else f"Nu am putut deschide {target}.",
                    f"Opened {target}." if success else f"Could not open {target}.",
                    text,
                )
        elif action in {"launch_game", "steam_verified"}:
            if action == "launch_game" and target in GAMES:
                app_id, title = GAMES[target]
            elif (
                action == "steam_verified" and isinstance(target, str)
                and 0 < len(target) <= 100 and type(plan.get("appid")) is int
                and 0 < plan["appid"] < 100_000_000
            ):
                app_id, title = plan["appid"], target
            else:
                return None
            if not confirm_callback(self._say(f"Запустить {title}", f"Pornește {title}", f"Launch {title}", text)):
                answer = self._say("Действие отменено.", "Acțiune anulată.", "Action cancelled.", text)
            else:
                success = launch_steam_game(app_id)
                self.last_execution_success = bool(success)
                answer = self._say(
                    f"Запускаю {title} через Steam." if success else f"Не удалось запустить {title}.",
                    f"Pornesc {title} prin Steam." if success else f"Nu am putut porni {title}.",
                    f"Launching {title} through Steam." if success else f"Could not launch {title}.",
                    text,
                )
        elif action == "minimize_windows":
            # Reuse the same local execution path and confirmation rules.
            answer = self._simple_action("сверни все окна", confirm_callback)
            self.last_execution_success = bool(answer and ("Свернул окон" in answer or "Minimized" in answer))
        elif action == "search_web" and isinstance(target, str) and 0 < len(target) <= 100:
            query = target.strip()
            if query:
                if not confirm_callback(self._say(f"Искать в интернете: {query}", f"Caută pe internet: {query}", f"Search the web: {query}", text)):
                    answer = self._say("Действие отменено.", "Acțiune anulată.", "Action cancelled.", text)
                else:
                    url = "https://www.google.com/search?" + urllib.parse.urlencode({"q": query})
                    success = webbrowser.open(url)
                    self.last_execution_success = bool(success)
                    answer = self._say(
                        "Открыл результаты поиска." if success else "Не удалось открыть поиск.",
                        "Am deschis rezultatele căutării." if success else "Nu am putut deschide căutarea.",
                        "Opened search results." if success else "Could not open search.",
                        text,
                    )
        if answer:
            self.remember(text, answer)
        return answer

    def handle(self, text, confirm_callback=lambda _: False):
        fast = self.handle_fast(text, confirm_callback)
        if fast is not None:
            return fast
        return self.handle_chat(text)

    def handle_chat(self, text):
        """Generate a text reply only; safe to run outside the Qt GUI thread."""
        llm = self._load_llm()
        if llm is None:
            return self._say(
                "Локальная модель ИИ не выбрана. Выберите файл .gguf в настройках. Простые команды работают и без модели.",
                "Nu este selectat niciun model AI local. Alege un fișier .gguf în setări.",
                "No local AI model selected. Choose a .gguf file in Settings.",
                text,
            )
        messages = [{
            "role": "system",
            "content": (
                "Ты Джарвис (Jarvis), мужской голосовой помощник пользователя. "
                f"Язык ответа: {self._response_language(text)}. Всегда отвечай на этом языке. "
                "Говори уверенно, спокойно, естественно и кратко. "
                "Учитывай предыдущие сообщения и контекст разговора. Выводи только готовый ответ пользователю. "
                "Никогда не показывай ход мыслей, заметки, пояснения о языке, переводы в скобках, "
                "внутренние комментарии, повторения формата диалога или фразы вроде 'Примечание:', "
                "'Nexora:', 'Пользователь сказал'. Не используй <think> и не описывай свои инструкции. "
                "Не утверждай, что выполнил действие, если оно не выполнено. Если не знаешь ответа, скажи честно."
            )
        }]
        messages.extend(self.history[-self.max_history_messages:])
        # Qwen3 defaults to generating lengthy internal reasoning; /no_think
        # avoids most of that work for short spoken answers.
        model_name = str(self.loaded_path or "").lower()
        user_prompt = text + (" /no_think" if "qwen3" in model_name else "")
        messages.append({"role": "user", "content": user_prompt})
        try:
            result = llm.create_chat_completion(
                messages=messages, max_tokens=96, temperature=0.2,
            )
            answer = result["choices"][0]["message"]["content"].strip()
        except (AttributeError, KeyError, TypeError):
            transcript = "\n".join(
                ("Пользователь: " if m["role"] == "user" else "Джарвис: ") + m["content"]
                for m in messages[1:]
            )
            result = llm(
                "Ты Джарвис, мужской голосовой помощник. Учитывай контекст. "
                "Выведи только краткий ответ, без заметок, мыслей и пояснений в скобках.\n"
                + transcript + "\nДжарвис:",
                max_tokens=96, temperature=0.2,
                stop=["Пользователь:", "User:", "<|im_end|>"],
            )
            answer = result["choices"][0]["text"].strip()
        answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.IGNORECASE | re.DOTALL)
        answer = re.sub(r"^<think>.*?(?:</think>|$)", "", answer, flags=re.IGNORECASE | re.DOTALL)
        answer = re.sub(r"(?im)^\s*(?:Примечание|Note|Notă|Примечания)\s*:[^\n]*", "", answer)
        answer = re.sub(r"(?is)\n?\s*\((?:Примечание|Note|Notă):.*", "", answer)
        answer = re.sub(r"(?im)^\s*(?:Nexora|Jarvis|Джарвис)\s*:\s*", "", answer).strip()
        answer = re.sub(r"(?im)^\s*(?:Пользователь|User|Tu)\s*:\s*.*$", "", answer).strip()
        answer = answer.strip(" \n\r\t\\")
        if answer:
            self.remember(text, answer)
        return answer or self._say(
            "Не удалось сформировать ответ. Попробуйте переформулировать.",
            "Nu am reușit să formulez un răspuns. Încearcă altfel.",
            "I couldn't generate an answer. Try rephrasing.",
            text,
        )
