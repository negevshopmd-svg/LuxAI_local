"""Extensions (plugins) catalog for the 0.4.0 Extensions page.

Pure data and validation: no Qt imports, so it is importable from tests and
from the runtime. Every plugin has a stable id, a category, an icon, a tile
color, localized texts and a declarative settings schema. Persistent state
lives in ``config.json`` under ``extensions`` as
``{plugin_id: {"enabled": bool, "settings": {...}}}``; unknown ids and
invalid values are dropped on load, so a damaged config can never crash the
page. Secrets (bot tokens and similar) are NEVER part of this state.

``ready`` plugins have a working runtime in ``extensions_runtime.py``. The
others are visible with their settings but their switch is locked and marked
"Скоро" until a runtime exists: the page must never pretend a module works.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

LANGS = ("ru", "en", "ro")


def L(ru: str, en: str, ro: str) -> dict:
    return {"ru": ru, "en": en, "ro": ro}


def text(value, language: str) -> str:
    if isinstance(value, dict):
        return value.get(language) or value.get("ru") or ""
    return str(value or "")


CATEGORIES = (
    ("voice", L("Голос и звук", "Voice and sound", "Voce și sunet")),
    ("text", L("Текст и буфер обмена", "Text and clipboard", "Text și clipboard")),
    ("desktop", L("Рабочий стол", "Desktop", "Desktop")),
    ("control", L("Управление ПК и дом", "PC and home control", "Control PC și casă")),
    ("files", L("Файлы, экран и стримы", "Files, screen and streams", "Fișiere, ecran și stream-uri")),
)
CATEGORY_IDS = tuple(identifier for identifier, _ in CATEGORIES)


@dataclass(frozen=True)
class Setting:
    key: str
    kind: str  # bool | choice | int | hotkey | text | multiline | folder
    label: dict
    default: object
    hint: dict | None = None
    options: tuple = ()  # (value, label dict) for "choice"
    minimum: int = 0
    maximum: int = 0
    suffix: dict | None = None
    max_length: int = 200


@dataclass(frozen=True)
class Plugin:
    id: str
    category: str
    icon: str
    color: str
    title: dict
    description: dict
    ready: bool
    settings: tuple = field(default_factory=tuple)
    actions: tuple = ()  # (action_id, label dict) buttons in the settings dialog


def _hotkey(default, label=None):
    return Setting("hotkey", "hotkey", label or L("Клавиша", "Shortcut", "Combinație de taste"), default,
                   hint=L("Например Ctrl+Alt+V или F8. Пусто — без клавиши.",
                          "For example Ctrl+Alt+V or F8. Empty — no shortcut.",
                          "De exemplu Ctrl+Alt+V sau F8. Gol — fără combinație."))


_SPEECH_LANG = Setting(
    "language", "choice", L("Язык", "Language", "Limba"), "auto",
    options=(("auto", L("Как у ассистента", "Same as assistant", "Ca la asistent")),
             ("ru", L("Русский", "Russian", "Rusă")),
             ("ro", L("Румынский", "Romanian", "Română")),
             ("en", L("Английский", "English", "Engleză"))))

_MINUTES = L(" мин", " min", " min")
_ITEMS = L(" шт.", " items", " elem.")
_DAYS = L(" дн.", " days", " zile")
_MB = L(" МБ", " MB", " MB")

PLUGINS: tuple[Plugin, ...] = (
    # --- Voice and sound -------------------------------------------------
    Plugin(
        "smart_dictation", "voice", "mic-vocal", "#7b5cf0",
        L("Умная диктовка", "Smart dictation", "Dictare inteligentă"),
        L("Нажмите клавишу и говорите: распознанный текст печатается в любом поле, где стоит курсор. "
          "Знаки препинания голосом и правка нейросетью.",
          "Press a key and speak: the recognized text is typed into whatever field has the cursor. "
          "Spoken punctuation and AI cleanup.",
          "Apasă o tastă și vorbește: textul recunoscut se scrie în câmpul unde este cursorul. "
          "Punctuație vocală și corectare AI."),
        False,
        (_hotkey("ctrl+alt+d"),
         Setting("mode", "choice", L("Режим клавиши", "Key mode", "Mod tastă"), "toggle",
                 options=(("toggle", L("Нажать — начать, ещё раз — закончить", "Press to start, again to stop", "Apasă pentru start, din nou pentru stop")),
                          ("hold", L("Пока клавиша зажата", "While the key is held", "Cât timp tasta e apăsată")))),
         _SPEECH_LANG,
         Setting("punctuation", "bool", L("Знаки препинания голосом", "Spoken punctuation", "Punctuație vocală"), True,
                 hint=L("«запятая», «точка», «новая строка».", "“comma”, “period”, “new line”.", "„virgulă”, „punct”, „rând nou”.")),
         Setting("ai_cleanup", "bool", L("Улучшать текст нейросетью", "Polish text with AI", "Îmbunătățește textul cu AI"), False)),
    ),
    Plugin(
        "notification_reader", "voice", "bell-ring", "#f08a1c",
        L("Озвучка уведомлений", "Notification reader", "Citire notificări"),
        L("Читает вслух новые уведомления Windows: от кого и что пришло. Пропускает коды и ссылки, "
          "молчит в играх, во время звонков и в тихие часы.",
          "Reads new Windows notifications aloud: who sent what. Skips codes and links, "
          "stays silent in games, during calls and in quiet hours.",
          "Citește cu voce notificările Windows noi: cine și ce a trimis. Sare peste coduri și linkuri, "
          "tace în jocuri, în apeluri și în orele de liniște."),
        False,
        (Setting("apps", "text", L("Только эти приложения", "Only these apps", "Doar aceste aplicații"), "Telegram, Discord",
                 hint=L("Через запятую. Пусто — все приложения.", "Comma separated. Empty — all apps.", "Separate prin virgulă. Gol — toate."), max_length=300),
         Setting("skip_codes", "bool", L("Не читать коды и ссылки", "Skip codes and links", "Nu citi coduri și linkuri"), True),
         Setting("silent_games", "bool", L("Молчать в играх и на звонках", "Silent in games and calls", "Tăcere în jocuri și apeluri"), True),
         Setting("quiet_from", "int", L("Тихие часы с", "Quiet hours from", "Ore de liniște de la"), 23, minimum=0, maximum=23, suffix=L(":00", ":00", ":00")),
         Setting("quiet_to", "int", L("Тихие часы до", "Quiet hours until", "Ore de liniște până la"), 8, minimum=0, maximum=23, suffix=L(":00", ":00", ":00"))),
    ),
    Plugin(
        "read_aloud", "voice", "book-audio", "#e2457f",
        L("Чтение вслух", "Read aloud", "Citire cu voce"),
        L("Выделите текст в браузере, документе или книге и нажмите клавишу — ассистент прочитает его своим голосом.",
          "Select text in a browser, document or book and press the key — the assistant reads it in its own voice.",
          "Selectează text într-un browser, document sau carte și apasă tasta — asistentul îl citește cu vocea lui."),
        True,
        (_hotkey("ctrl+alt+r"),
         Setting("max_chars", "int", L("Максимум символов", "Maximum characters", "Caractere maxime"), 4000,
                 minimum=200, maximum=6500, suffix=L(" симв.", " chars", " car.")),
         Setting("second_press_stops", "bool", L("Повторное нажатие останавливает чтение", "Second press stops reading", "A doua apăsare oprește citirea"), True)),
        (("test", L("Прочитать пример", "Read a sample", "Citește un exemplu")),),
    ),
    Plugin(
        "live_captions", "voice", "captions", "#1f9fd6",
        L("Живые субтитры", "Live captions", "Subtitrări live"),
        L("Показывает поверх всех окон текст того, что звучит на компьютере: видео, созвон, стрим. "
          "При желании — с переводом.",
          "Shows an always-on-top strip with the text of whatever plays on the PC: video, call, stream. "
          "Optionally translated.",
          "Afișează deasupra ferestrelor textul a ceea ce se aude pe PC: video, apel, stream. "
          "Opțional cu traducere."),
        False,
        (_SPEECH_LANG,
         Setting("translate_to", "choice", L("Переводить на", "Translate to", "Tradu în"), "none",
                 options=(("none", L("Не переводить", "Do not translate", "Fără traducere")),
                          ("ru", L("Русский", "Russian", "Rusă")),
                          ("ro", L("Румынский", "Romanian", "Română")),
                          ("en", L("Английский", "English", "Engleză")))),
         Setting("position", "choice", L("Положение плашки", "Strip position", "Poziția benzii"), "bottom",
                 options=(("bottom", L("Снизу", "Bottom", "Jos")), ("top", L("Сверху", "Top", "Sus")))),
         Setting("font_size", "int", L("Размер текста", "Text size", "Mărimea textului"), 20, minimum=12, maximum=40, suffix=L(" px", " px", " px"))),
    ),
    Plugin(
        "meeting_notes", "voice", "clipboard-list", "#e5484d",
        L("Конспект видео и созвонов", "Video and call notes", "Rezumat video și apeluri"),
        L("Записывает звук компьютера и микрофон, ведёт расшифровку, а после записи составляет конспект: "
          "темы, решения, задачи и открытые вопросы.",
          "Records PC audio and the microphone, transcribes, then writes notes: "
          "topics, decisions, tasks and open questions.",
          "Înregistrează sunetul PC-ului și microfonul, transcrie, apoi face un rezumat: "
          "teme, decizii, sarcini și întrebări deschise."),
        False,
        (Setting("sources", "choice", L("Источники звука", "Audio sources", "Surse audio"), "both",
                 options=(("both", L("Компьютер и микрофон", "PC and microphone", "PC și microfon")),
                          ("system", L("Только звук компьютера", "PC audio only", "Doar sunetul PC")),
                          ("mic", L("Только микрофон", "Microphone only", "Doar microfonul")))),
         Setting("folder", "folder", L("Папка для конспектов", "Notes folder", "Dosar pentru rezumate"), "",
                 hint=L("Пусто — «Документы\\Jarvis\\Конспекты».", "Empty — “Documents\\Jarvis\\Notes”.", "Gol — „Documente\\Jarvis\\Rezumate”.")),
         Setting("keep_audio", "bool", L("Сохранять аудиозапись", "Keep the audio recording", "Păstrează înregistrarea audio"), False)),
    ),
    # --- Text and clipboard ----------------------------------------------
    Plugin(
        "text_helper", "text", "file-pen-line", "#12a3b4",
        L("Помощник текста", "Text helper", "Asistent de text"),
        L("Выделите текст в любой программе и нажмите клавишу: исправить ошибки, улучшить, сократить, "
          "перевести или ответить — и заменить одним нажатием.",
          "Select text in any app and press the key: fix mistakes, improve, shorten, "
          "translate or reply — and replace it in one click.",
          "Selectează text în orice program și apasă tasta: corectează, îmbunătățește, scurtează, "
          "traduce sau răspunde — și înlocuiește cu un clic."),
        False,
        (_hotkey("ctrl+alt+t"),
         Setting("default_action", "choice", L("Действие по умолчанию", "Default action", "Acțiune implicită"), "fix",
                 options=(("fix", L("Исправить ошибки", "Fix mistakes", "Corectează greșelile")),
                          ("improve", L("Улучшить стиль", "Improve style", "Îmbunătățește stilul")),
                          ("shorten", L("Сократить", "Shorten", "Scurtează")),
                          ("translate", L("Перевести", "Translate", "Tradu")))),
         Setting("translate_to", "choice", L("Переводить на", "Translate to", "Tradu în"), "en",
                 options=(("ru", L("Русский", "Russian", "Rusă")), ("ro", L("Румынский", "Romanian", "Română")),
                          ("en", L("Английский", "English", "Engleză"))))),
    ),
    Plugin(
        "clipboard_history", "text", "clipboard-paste", "#c47a2c",
        L("История буфера обмена", "Clipboard history", "Istoric clipboard"),
        L("Помнит последние скопированные тексты. По клавише открывается список у курсора: поиск, "
          "закрепление и вставка в одно нажатие.",
          "Remembers recently copied texts. A key opens the list at the cursor: search, "
          "pinning and one-click paste.",
          "Ține minte textele copiate recent. O tastă deschide lista lângă cursor: căutare, "
          "fixare și lipire dintr-un clic."),
        True,
        (_hotkey("ctrl+alt+v"),
         Setting("limit", "int", L("Хранить записей", "Items to keep", "Elemente păstrate"), 50, minimum=10, maximum=300, suffix=_ITEMS),
         Setting("paste_on_pick", "bool", L("Сразу вставлять выбранное", "Paste the chosen item immediately", "Lipește imediat elementul ales"), True),
         Setting("ignore_secrets", "bool", L("Не запоминать похожее на пароли и коды", "Skip things that look like passwords or codes", "Nu reține ce seamănă cu parole sau coduri"), True)),
        (("open", L("Открыть историю", "Open history", "Deschide istoricul")),
         ("clear", L("Очистить незакреплённые", "Clear unpinned", "Șterge cele nefixate"))),
    ),
    Plugin(
        "quick_inserts", "text", "zap", "#9b3fb5",
        L("Быстрые вставки", "Quick inserts", "Inserții rapide"),
        L("Готовые фрагменты текста — адрес, подпись, реквизиты, ответы-заготовки. По клавише выберите "
          "фрагмент, и он вставится там, где стоит курсор. Поддерживает {дата} и {время}.",
          "Ready text snippets — address, signature, details, canned replies. Press the key, pick a snippet "
          "and it is pasted at the cursor. Supports {date} and {time}.",
          "Fragmente de text gata — adresă, semnătură, date, răspunsuri. Apasă tasta, alege fragmentul "
          "și se lipește unde e cursorul. Suportă {data} și {ora}."),
        True,
        (_hotkey("ctrl+alt+i"),
         Setting("snippets", "multiline", L("Фрагменты", "Snippets", "Fragmente"),
                 "почта = example@mail.com\nподпись = С уважением,\\nВаше имя\nдата = Сегодня {дата}",
                 hint=L("По одному на строку: «название = текст». \\n — перенос строки.",
                        "One per line: “name = text”. \\n — line break.",
                        "Câte unul pe rând: „nume = text”. \\n — rând nou."), max_length=6000)),
        (("open", L("Открыть список", "Open the list", "Deschide lista")),),
    ),
    Plugin(
        "ask_documents", "text", "file-search-2", "#c06a3a",
        L("Спросить документы", "Ask your documents", "Întreabă documentele"),
        L("Находит файл по содержимому и отвечает по нему: «найди договор аренды и скажи сумму», "
          "«в каком файле рецепт пирога».",
          "Finds a file by its content and answers from it: “find the lease and tell me the amount”, "
          "“which file has the pie recipe”.",
          "Găsește un fișier după conținut și răspunde din el: „găsește contractul de chirie și spune suma”, "
          "„în ce fișier e rețeta de plăcintă”."),
        False,
        (Setting("folders", "multiline", L("Папки для поиска", "Folders to search", "Dosare de căutat"), "",
                 hint=L("По одной на строку. Пусто — Документы и Рабочий стол.", "One per line. Empty — Documents and Desktop.",
                        "Câte unul pe rând. Gol — Documente și Desktop."), max_length=2000),
         Setting("max_size", "int", L("Не читать файлы больше", "Skip files larger than", "Ignoră fișierele mai mari de"), 20, minimum=1, maximum=200, suffix=_MB),
         Setting("cloud", "bool", L("Разрешить отправку фрагментов в облачный AI", "Allow sending excerpts to cloud AI", "Permite trimiterea fragmentelor către AI cloud"), False)),
    ),
    # --- Desktop -----------------------------------------------------------
    Plugin(
        "visual_avatar", "desktop", "orbit", "#3b78f0",
        L("Визуальный аватар", "Visual avatar", "Avatar vizual"),
        L("Анимированный шар поверх экрана, который реагирует на голос ассистента, микрофон или системные звуки.",
          "An animated orb on top of the screen that reacts to the assistant's voice, the microphone or system sounds.",
          "O sferă animată deasupra ecranului care reacționează la vocea asistentului, microfon sau sunetele sistemului."),
        False,
        (Setting("react_to", "choice", L("Реагировать на", "React to", "Reacționează la"), "assistant",
                 options=(("assistant", L("Голос ассистента", "Assistant voice", "Vocea asistentului")),
                          ("mic", L("Микрофон", "Microphone", "Microfon")),
                          ("system", L("Звуки системы", "System sounds", "Sunetele sistemului")))),
         Setting("size", "int", L("Размер", "Size", "Mărime"), 160, minimum=80, maximum=400, suffix=L(" px", " px", " px")),
         Setting("click_through", "bool", L("Пропускать клики сквозь аватар", "Let clicks pass through", "Lasă clicurile să treacă"), True)),
    ),
    Plugin(
        "desktop_pet", "desktop", "ghost", "#a24ee8",
        L("Питомец", "Desktop pet", "Animăluț"),
        L("Маленький пиксельный друг на рабочем столе: гуляет, сидит на окнах и панели задач, "
          "радуется, когда вы говорите с ассистентом.",
          "A small pixel buddy on the desktop: walks around, sits on windows and the taskbar, "
          "cheers up when you talk to the assistant.",
          "Un mic prieten pixelat pe desktop: se plimbă, stă pe ferestre și pe bara de activități, "
          "se bucură când vorbești cu asistentul."),
        False,
        (Setting("character", "choice", L("Кто это", "Character", "Personaj"), "robot",
                 options=(("robot", L("Робот", "Robot", "Robot")), ("cat", L("Кот", "Cat", "Pisică")),
                          ("ghost", L("Привидение", "Ghost", "Fantomă")), ("jelly", L("Медуза", "Jellyfish", "Meduză")))),
         Setting("behaviour", "choice", L("Поведение", "Behaviour", "Comportament"), "walk",
                 options=(("walk", L("Гуляет", "Walks", "Se plimbă")), ("float", L("Парит", "Floats", "Plutește")),
                          ("sit", L("Сидит на месте", "Stays put", "Stă pe loc")))),
         Setting("hide_fullscreen", "bool", L("Прятать в играх и полноэкранных окнах", "Hide in games and fullscreen", "Ascunde în jocuri și ecran complet"), True)),
    ),
    Plugin(
        "status_island", "desktop", "panels-top-left", "#2a3f9e",
        L("Островок", "Status island", "Insula de stare"),
        L("Плашка у края экрана: что происходит сейчас — голос, команды, задачи агента, таймер, музыка — "
          "и быстрые действия.",
          "A pill at the screen edge showing what is happening now — voice, commands, agent tasks, timer, music — "
          "with quick actions.",
          "O bandă la marginea ecranului cu ce se întâmplă acum — voce, comenzi, sarcini, cronometru, muzică — "
          "și acțiuni rapide."),
        False,
        (Setting("edge", "choice", L("Край экрана", "Screen edge", "Marginea ecranului"), "top",
                 options=(("top", L("Сверху", "Top", "Sus")), ("bottom", L("Снизу", "Bottom", "Jos")))),
         Setting("auto_hide", "bool", L("Скрывать, когда ничего не происходит", "Hide when idle", "Ascunde când nu se întâmplă nimic"), True)),
    ),
    Plugin(
        "breaks", "desktop", "coffee", "#3aa05a",
        L("Перерывы", "Breaks", "Pauze"),
        L("Напоминает дать глазам отдых, размяться и выпить воды — считает только реальное время за "
          "компьютером и не мешает играм и звонкам.",
          "Reminds you to rest your eyes, stretch and drink water — counts only real time at the "
          "computer and does not interrupt games or calls.",
          "Îți amintește să-ți odihnești ochii, să te întinzi și să bei apă — numără doar timpul real la "
          "calculator și nu deranjează jocurile sau apelurile."),
        True,
        (Setting("interval", "int", L("Напоминать каждые", "Remind every", "Amintește la fiecare"), 50, minimum=10, maximum=240, suffix=_MINUTES),
         Setting("idle_reset", "int", L("Считать перерывом простой от", "Idle time that counts as a break", "Inactivitate considerată pauză"), 5, minimum=1, maximum=60, suffix=_MINUTES),
         Setting("eyes", "bool", L("Глаза: правило 20-20-20", "Eyes: 20-20-20 rule", "Ochi: regula 20-20-20"), True),
         Setting("water", "bool", L("Вода", "Water", "Apă"), True),
         Setting("stretch", "bool", L("Разминка", "Stretching", "Întinderi"), True),
         Setting("speak", "bool", L("Говорить напоминание вслух", "Speak the reminder", "Rostește mementoul"), False),
         Setting("skip_fullscreen", "bool", L("Не мешать в играх и полноэкранных окнах", "Do not disturb in games and fullscreen", "Nu deranja în jocuri și ecran complet"), True)),
        (("test", L("Показать напоминание сейчас", "Show a reminder now", "Arată un memento acum")),),
    ),
    # --- PC and home control ---------------------------------------------
    Plugin(
        "quick_circle", "control", "circle-dot-dashed", "#475569",
        L("Круг действий", "Action circle", "Cerc de acțiuni"),
        L("Круговое меню у курсора: ваши команды в один щелчок, действия для активного окна, медиа и поиск.",
          "A radial menu at the cursor: your commands in one click, actions for the active window, media and search.",
          "Un meniu circular lângă cursor: comenzile tale dintr-un clic, acțiuni pentru fereastra activă, media și căutare."),
        False,
        (_hotkey("ctrl+alt+c"),
         Setting("items", "int", L("Пунктов в круге", "Items in the circle", "Elemente în cerc"), 8, minimum=4, maximum=12, suffix=_ITEMS)),
    ),
    Plugin(
        "pc_control", "control", "send", "#21a366",
        L("PC Control", "PC Control", "PC Control"),
        L("Запуск ваших команд из своего Telegram-бота: папки и команды кнопками и текстом. "
          "Источник — редактор команд.",
          "Run your commands from your own Telegram bot: folders and commands as buttons and text. "
          "Source — the command editor.",
          "Rulează comenzile tale din propriul bot Telegram: dosare și comenzi ca butoane și text. "
          "Sursa — editorul de comenzi."),
        False,
        (Setting("bot_name", "text", L("Имя бота", "Bot name", "Numele botului"), "", max_length=64,
                 hint=L("Токен бота хранится в защищённом хранилище Windows, а не в config.json.",
                        "The bot token is kept in Windows protected storage, not in config.json.",
                        "Tokenul botului se păstrează în stocarea protejată Windows, nu în config.json.")),
         Setting("allowed_users", "text", L("Разрешённые пользователи Telegram", "Allowed Telegram users", "Utilizatori Telegram permiși"), "",
                 hint=L("ID через запятую. Остальным бот не отвечает.", "IDs, comma separated. The bot ignores everyone else.",
                        "ID-uri separate prin virgulă. Botul îi ignoră pe ceilalți."), max_length=300),
         Setting("confirm_sensitive", "bool", L("Подтверждать опасные команды", "Confirm sensitive commands", "Confirmă comenzile sensibile"), True)),
    ),
    Plugin(
        "media_keys", "control", "audio-lines", "#d9480f",
        L("Медиа-клавиши", "Media keys", "Taste media"),
        L("Свои сочетания клавиш для музыки и звука: пауза, следующий и предыдущий трек, громкость — "
          "работает в любом плеере и браузере.",
          "Your own shortcuts for music and sound: pause, next and previous track, volume — "
          "works in any player and browser.",
          "Combinații proprii pentru muzică și sunet: pauză, piesa următoare și anterioară, volum — "
          "funcționează în orice player și browser."),
        True,
        (Setting("play_pause", "hotkey", L("Пауза / продолжить", "Play / pause", "Redare / pauză"), "ctrl+alt+p"),
         Setting("next", "hotkey", L("Следующий трек", "Next track", "Piesa următoare"), "ctrl+alt+n"),
         Setting("previous", "hotkey", L("Предыдущий трек", "Previous track", "Piesa anterioară"), "ctrl+alt+b"),
         Setting("volume_up", "hotkey", L("Громче", "Volume up", "Volum mai tare"), ""),
         Setting("volume_down", "hotkey", L("Тише", "Volume down", "Volum mai încet"), ""),
         Setting("mute", "hotkey", L("Выключить звук", "Mute", "Fără sunet"), "")),
    ),
    Plugin(
        "smart_home", "control", "house", "#0e7490",
        L("Умный дом", "Smart home", "Casă inteligentă"),
        L("Голосом и кнопками управляет светом, розетками и сценами через Home Assistant в вашей сети.",
          "Controls lights, plugs and scenes by voice and buttons through Home Assistant on your network.",
          "Controlează lumini, prize și scene prin voce și butoane prin Home Assistant din rețeaua ta."),
        False,
        (Setting("url", "text", L("Адрес Home Assistant", "Home Assistant address", "Adresa Home Assistant"), "http://homeassistant.local:8123", max_length=200,
                 hint=L("Токен доступа хранится в защищённом хранилище Windows.", "The access token is kept in Windows protected storage.",
                        "Tokenul de acces se păstrează în stocarea protejată Windows.")),
         Setting("confirm_locks", "bool", L("Подтверждать замки и сигнализацию", "Confirm locks and alarms", "Confirmă încuietorile și alarmele"), True)),
    ),
    Plugin(
        "timers", "control", "hourglass", "#7c3aed",
        L("Таймеры и будильники", "Timers and alarms", "Cronometre și alarme"),
        L("«Поставь таймер на 10 минут», «разбуди в 7:30»: несколько таймеров сразу, напоминание голосом и "
          "уведомлением, даже если окно свёрнуто.",
          "“Set a timer for 10 minutes”, “wake me at 7:30”: several timers at once, voice and notification "
          "reminders even when the window is minimized.",
          "„Pune un cronometru de 10 minute”, „trezește-mă la 7:30”: mai multe cronometre, memento vocal și "
          "notificare chiar dacă fereastra e minimizată."),
        False,
        (Setting("sound", "bool", L("Звуковой сигнал", "Sound signal", "Semnal sonor"), True),
         Setting("snooze", "int", L("Отложить на", "Snooze for", "Amână cu"), 5, minimum=1, maximum=30, suffix=_MINUTES)),
    ),
    # --- Files, screen and streams ---------------------------------------
    Plugin(
        "converter", "files", "images", "#4e9a2f",
        L("Конвертер", "Converter", "Convertor"),
        L("Переводит картинки в PNG, JPG, WebP, ICO и PDF, сжимает и уменьшает их. "
          "Оригиналы не трогает — рядом появляются копии.",
          "Converts images to PNG, JPG, WebP, ICO and PDF, compresses and downsizes them. "
          "Originals stay untouched — copies appear next to them.",
          "Convertește imagini în PNG, JPG, WebP, ICO și PDF, le comprimă și le micșorează. "
          "Originalele rămân neatinse — copiile apar alături."),
        True,
        (Setting("format", "choice", L("Формат по умолчанию", "Default format", "Format implicit"), "png",
                 options=(("png", L("PNG", "PNG", "PNG")), ("jpg", L("JPG", "JPG", "JPG")), ("webp", L("WebP", "WebP", "WebP")),
                          ("ico", L("ICO", "ICO", "ICO")), ("pdf", L("PDF", "PDF", "PDF")))),
         Setting("quality", "int", L("Качество JPG / WebP", "JPG / WebP quality", "Calitate JPG / WebP"), 85, minimum=30, maximum=100, suffix=L(" %", " %", " %")),
         Setting("max_side", "int", L("Уменьшать до (длинная сторона)", "Downsize to (long side)", "Micșorează la (latura lungă)"), 0, minimum=0, maximum=8000,
                 suffix=L(" px", " px", " px"), hint=L("0 — не уменьшать.", "0 — keep the size.", "0 — păstrează mărimea."))),
        (("convert", L("Выбрать файлы и конвертировать", "Choose files and convert", "Alege fișiere și convertește")),),
    ),
    Plugin(
        "screenshots", "files", "scan", "#127a8f",
        L("Скриншоты", "Screenshots", "Capturi de ecran"),
        L("Снимок экрана или активного окна по клавише — сразу в буфер обмена и в файл.",
          "A screenshot of the screen or the active window on a key press — straight to the clipboard and a file.",
          "Captură a ecranului sau a ferestrei active la o tastă — direct în clipboard și într-un fișier."),
        True,
        (Setting("hotkey", "hotkey", L("Весь экран", "Whole screen", "Tot ecranul"), "ctrl+alt+s"),
         Setting("window_hotkey", "hotkey", L("Активное окно", "Active window", "Fereastra activă"), "ctrl+alt+w"),
         Setting("to_clipboard", "bool", L("Копировать в буфер обмена", "Copy to the clipboard", "Copiază în clipboard"), True),
         Setting("to_file", "bool", L("Сохранять в файл", "Save to a file", "Salvează într-un fișier"), True),
         Setting("folder", "folder", L("Папка", "Folder", "Dosar"), "",
                 hint=L("Пусто — «Изображения\\Jarvis Screenshots».", "Empty — “Pictures\\Jarvis Screenshots”.", "Gol — „Imagini\\Jarvis Screenshots”."))),
        (("capture", L("Сделать снимок экрана", "Take a screenshot", "Fă o captură")),
         ("open_folder", L("Открыть папку", "Open the folder", "Deschide dosarul"))),
    ),
    Plugin(
        "downloads_cleanup", "files", "brush", "#c99a17",
        L("Уборка загрузок", "Downloads cleanup", "Curățenie în Descărcări"),
        L("Раскладывает «Загрузки» по папкам: картинки, видео, музыка, документы, архивы, установщики. "
          "Старые установщики можно отправлять в Корзину.",
          "Sorts Downloads into folders: images, video, music, documents, archives, installers. "
          "Old installers can go to the Recycle Bin.",
          "Sortează Descărcările în dosare: imagini, video, muzică, documente, arhive, instalatoare. "
          "Instalatoarele vechi pot merge în Coșul de reciclare."),
        True,
        (Setting("folder", "folder", L("Папка загрузок", "Downloads folder", "Dosarul Descărcări"), "",
                 hint=L("Пусто — стандартная папка «Загрузки».", "Empty — the standard Downloads folder.", "Gol — dosarul standard Descărcări.")),
         Setting("min_age", "int", L("Не трогать файлы моложе", "Leave files newer than", "Nu atinge fișierele mai noi de"), 1, minimum=0, maximum=60, suffix=_DAYS),
         Setting("old_installers", "int", L("Установщики старше — в Корзину", "Installers older than — to Recycle Bin", "Instalatoare mai vechi — în Coș"), 0, minimum=0, maximum=365,
                 suffix=_DAYS, hint=L("0 — не удалять.", "0 — never delete.", "0 — nu șterge.")),
         Setting("auto", "bool", L("Убирать автоматически раз в день", "Clean automatically once a day", "Curăță automat o dată pe zi"), False)),
        (("preview", L("Показать, что будет перемещено", "Preview the changes", "Previzualizează")),
         ("run", L("Убрать сейчас", "Clean up now", "Curăță acum"))),
    ),
    Plugin(
        "streamer_helper", "files", "radio", "#d6304a",
        L("Помощник стримера", "Streamer helper", "Asistent pentru streameri"),
        L("Управление OBS голосом и командами: эфир, запись, сцены, микрофон, клипы. "
          "Чат Twitch — на островке, лентой поверх окон и вслух.",
          "Control OBS by voice and commands: live, recording, scenes, microphone, clips. "
          "Twitch chat — on the island, as an overlay and aloud.",
          "Controlează OBS prin voce și comenzi: live, înregistrare, scene, microfon, clipuri. "
          "Chatul Twitch — pe insulă, peste ferestre și cu voce."),
        False,
        (Setting("obs_host", "text", L("Адрес OBS WebSocket", "OBS WebSocket address", "Adresa OBS WebSocket"), "127.0.0.1:4455", max_length=100,
                 hint=L("Пароль хранится в защищённом хранилище Windows.", "The password is kept in Windows protected storage.",
                        "Parola se păstrează în stocarea protejată Windows.")),
         Setting("twitch_channel", "text", L("Канал Twitch", "Twitch channel", "Canal Twitch"), "", max_length=60),
         Setting("read_chat", "bool", L("Читать чат вслух", "Read chat aloud", "Citește chatul cu voce"), False)),
    ),
)

PLUGIN_BY_ID = {plugin.id: plugin for plugin in PLUGINS}
assert len(PLUGIN_BY_ID) == len(PLUGINS) == 22
assert all(plugin.category in CATEGORY_IDS for plugin in PLUGINS)

UI = {
    "page_title": L("Расширения", "Extensions", "Extensii"),
    "plugins": L("Плагины", "Plugins", "Pluginuri"),
    "connections": L("Подключения", "Connections", "Conexiuni"),
    "tiles": L("Плитки", "Tiles", "Plăci"),
    "list": L("Список", "List", "Listă"),
    "search": L("Поиск расширений…", "Search extensions…", "Caută extensii…"),
    "topics": L("Темы", "Topics", "Teme"),
    "only_enabled": L("Только включённые", "Only enabled", "Doar activate"),
    "enabled_count": L("Включено: {n} из {total}", "Enabled: {n} of {total}", "Activate: {n} din {total}"),
    "configure": L("Настроить", "Configure", "Configurează"),
    "on": L("Включён", "On", "Activat"),
    "off": L("Выключен", "Off", "Dezactivat"),
    "soon": L("Скоро", "Soon", "În curând"),
    "soon_status": L("В разработке", "In development", "În dezvoltare"),
    "soon_hint": L("Этот модуль ещё в разработке. Настройки уже сохраняются и применятся, когда он выйдет.",
                   "This module is still in development. Settings are saved and will apply once it ships.",
                   "Acest modul este încă în dezvoltare. Setările se salvează și se vor aplica la lansare."),
    "nothing": L("Ничего не найдено.", "Nothing found.", "Nu s-a găsit nimic."),
    "save": L("Сохранить", "Save", "Salvează"),
    "cancel": L("Отмена", "Cancel", "Anulează"),
    "reset": L("По умолчанию", "Defaults", "Implicite"),
    "browse": L("Обзор…", "Browse…", "Răsfoiește…"),
    "settings_of": L("Настройки: {name}", "Settings: {name}", "Setări: {name}"),
    "hotkey_error": L("Ошибка клавиши", "Shortcut error", "Eroare de combinație"),
    "connections_intro": L("Внешние сервисы, которые используют расширения. Секреты хранятся в защищённом хранилище Windows.",
                           "External services used by extensions. Secrets are kept in Windows protected storage.",
                           "Servicii externe folosite de extensii. Secretele se păstrează în stocarea protejată Windows."),
    "used_by": L("Используется: {names}", "Used by: {names}", "Folosit de: {names}"),
    "connected": L("Настроено", "Configured", "Configurat"),
    "not_connected": L("Не настроено", "Not configured", "Neconfigurat"),
}

CONNECTIONS = (
    ("telegram", "send", L("Telegram-бот", "Telegram bot", "Bot Telegram"), ("pc_control",), "bot_name"),
    ("home_assistant", "house", L("Home Assistant", "Home Assistant", "Home Assistant"), ("smart_home",), "url"),
    ("obs", "radio", L("OBS WebSocket", "OBS WebSocket", "OBS WebSocket"), ("streamer_helper",), "obs_host"),
    ("twitch", "message-square", L("Twitch", "Twitch", "Twitch"), ("streamer_helper",), "twitch_channel"),
)


def ui(key: str, language: str, **values) -> str:
    template = text(UI[key], language)
    return template.format(**values) if values else template


# --- state -----------------------------------------------------------------

def default_settings(plugin: Plugin) -> dict:
    return {setting.key: copy.deepcopy(setting.default) for setting in plugin.settings}


def validate_value(setting: Setting, value):
    """Return a safe value for ``setting`` or raise ValueError."""
    kind = setting.kind
    if kind == "bool":
        if isinstance(value, bool):
            return value
        raise ValueError("bool expected")
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("number expected")
        number = int(value)
        if not setting.minimum <= number <= setting.maximum:
            raise ValueError("out of range")
        return number
    if kind == "choice":
        allowed = {option for option, _ in setting.options}
        if value not in allowed:
            raise ValueError("unknown option")
        return value
    if kind == "hotkey":
        from luxai.command_triggers import normalize_hotkey
        return normalize_hotkey(value) if value else ""
    if kind in ("text", "multiline", "folder"):
        if not isinstance(value, str):
            raise ValueError("text expected")
        value = value.replace("\r\n", "\n")
        if kind != "multiline":
            value = value.replace("\n", " ").strip()
        if len(value) > setting.max_length:
            raise ValueError("too long")
        if "\x00" in value:
            raise ValueError("invalid character")
        return value
    raise ValueError("unknown kind")


def normalize_state(raw) -> dict:
    """Merge a stored ``extensions`` value with defaults, dropping bad data."""
    raw = raw if isinstance(raw, dict) else {}
    state = {}
    for plugin in PLUGINS:
        entry = raw.get(plugin.id)
        entry = entry if isinstance(entry, dict) else {}
        settings = default_settings(plugin)
        stored = entry.get("settings")
        if isinstance(stored, dict):
            for setting in plugin.settings:
                if setting.key in stored:
                    try:
                        settings[setting.key] = validate_value(setting, stored[setting.key])
                    except ValueError:
                        pass
        enabled = entry.get("enabled") is True and plugin.ready
        state[plugin.id] = {"enabled": enabled, "settings": settings}
    return state


def enabled_count(state: dict) -> int:
    return sum(1 for plugin in PLUGINS if state.get(plugin.id, {}).get("enabled"))


def matches(plugin: Plugin, query: str, language: str) -> bool:
    query = " ".join(str(query or "").casefold().split())
    if not query:
        return True
    haystack = " ".join(
        [text(plugin.title, code) for code in LANGS]
        + [text(plugin.description, language)]
        + [text(label, language) for identifier, label in CATEGORIES if identifier == plugin.category]
    ).casefold()
    return all(word in haystack for word in query.split())


def hotkey_conflicts(state: dict) -> dict[str, str]:
    """Map 'plugin.key' to the first other enabled owner of the same shortcut."""
    owners: dict[str, str] = {}
    conflicts: dict[str, str] = {}
    for plugin in PLUGINS:
        entry = state.get(plugin.id, {})
        if not entry.get("enabled"):
            continue
        for setting in plugin.settings:
            if setting.kind != "hotkey":
                continue
            value = entry["settings"].get(setting.key) or ""
            if not value:
                continue
            name = f"{plugin.id}.{setting.key}"
            if value in owners:
                conflicts[name] = owners[value]
            else:
                owners[value] = name
    return conflicts


_SNIPPET_LINE = re.compile(r"^\s*([^=\n]{1,60}?)\s*=\s*(.+?)\s*$")


def parse_snippets(value: str) -> list[tuple[str, str]]:
    """Parse ``name = text`` lines; ``\\n`` becomes a real line break."""
    result = []
    for line in str(value or "").splitlines():
        match = _SNIPPET_LINE.match(line)
        if match:
            result.append((match.group(1), match.group(2).replace("\\n", "\n")))
    return result[:100]
