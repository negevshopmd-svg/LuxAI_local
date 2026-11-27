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
    kind: str  # bool | choice | int | hotkey | text | multiline | folder | secret | tags
    label: dict
    default: object
    hint: dict | None = None
    options: tuple = ()  # (value, label dict) for "choice"
    minimum: int = 0
    maximum: int = 0
    suffix: dict | None = None
    max_length: int = 200
    pattern: str = ""  # optional full-match regex for text values


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
_PERMANENT = L("Постоянный режим", "Permanent mode", "Mod permanent")
_ITEMS = L(" шт.", " items", " elem.")
_DAYS = L(" дн.", " days", " zile")
_MB = L(" МБ", " MB", " MB")

# Password managers: copies from these programs never enter the history.
CLIPBOARD_EXCLUDE_DEFAULT = ("KeePass", "KeePassXC", "KeeWeb", "1Password", "Bitwarden", "LastPass", "Dashlane", "Enpass",
                             "RoboForm", "Keeper", "NordPass", "Proton Pass", "pwsafe", "Buttercup", "Passwarden")

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
        True,
        (Setting("trigger", "choice", L("Чем начинать", "Start with", "Pornește cu"), "right_ctrl_double",
                 options=(("right_ctrl_double", L("Правый Ctrl ×2", "Right Ctrl ×2", "Ctrl dreapta ×2")),
                          ("hotkey", L("Своё сочетание клавиш", "Custom shortcut", "Combinație proprie"))),
                 hint=L("Правый Ctrl ×2 — быстро нажмите правый Ctrl два раза. Отдельно от клавиши голосовых команд.",
                        "Right Ctrl ×2 — tap the right Ctrl key twice quickly. Separate from the voice command key.",
                        "Ctrl dreapta ×2 — apasă rapid de două ori Ctrl din dreapta. Separat de tasta comenzilor vocale.")),
         _hotkey("ctrl+alt+d", L("Своё сочетание", "Custom shortcut", "Combinație proprie")),
         Setting("mode", "choice", L("Как пользоваться", "How to use", "Cum se folosește"), "hold",
                 options=(("hold", L("Удерживать", "Hold", "Ține apăsat")),
                          ("toggle", L("Нажал — говоришь — нажал", "Press — speak — press", "Apeși — vorbești — apeși")))),
         Setting("silence_pause", "int", L("Пауза, после которой запись кончается сама", "Silence that ends the recording",
                                            "Pauza după care înregistrarea se oprește"), 2, minimum=1, maximum=10,
                 suffix=L(" с", " s", " s"),
                 hint=L("Только для режима «нажал — говоришь — нажал».", "Only for the press — speak — press mode.",
                        "Doar pentru modul „apeși — vorbești — apeși”.")),
         Setting("voice_trigger", "bool", L("Включать голосом", "Start by voice", "Pornește prin voce"), False,
                 hint=L("«Джарвис, напиши» — запишу до паузы; «Джарвис, напиши привет» — вставлю сразу.",
                        "“Jarvis, write” — I record until a pause; “Jarvis, write hello” — I type it at once.",
                        "„Jarvis, scrie” — înregistrez până la pauză; „Jarvis, scrie salut” — scriu imediat.")),
         Setting("voice_phrases", "text", L("Фраза запуска", "Start phrase", "Fraza de pornire"), "напиши, write, scrie",
                 hint=L("Несколько через запятую — например, по одной на каждом языке.",
                        "Several, comma separated — for example one per language.",
                        "Mai multe, separate prin virgulă — de exemplu câte una pe limbă."), max_length=200),
         _SPEECH_LANG,
         Setting("punctuation", "bool", L("Знаки препинания голосом", "Spoken punctuation", "Punctuație vocală"), True,
                 hint=L("«точка», «запятая», «вопросительный знак», «новая строка», «кавычки» и «удали последнее слово».",
                        "“period”, “comma”, “question mark”, “new line”, “quotes” and “delete last word”.",
                        "„punct”, „virgulă”, „semnul întrebării”, „rând nou”, „ghilimele” și „șterge ultimul cuvânt”.")),
         Setting("sound", "bool", L("Звуковой сигнал начала и конца записи", "Start and stop sound", "Semnal sonor la început și sfârșit"), True),
         Setting("ai_cleanup", "bool", L("Улучшать текст нейросетью", "Polish text with AI", "Îmbunătățește textul cu AI"), False,
                 hint=L("Расставит знаки и исправит ошибки распознавания. Отправляется только текст (не звук) в облачный AI из настроек Jarvis; без ключа печатается как есть.",
                        "Fixes punctuation and recognition mistakes. Only the text (not audio) goes to the cloud AI from Jarvis settings; without a key it is typed as is.",
                        "Corectează punctuația și greșelile. Doar textul (nu sunetul) merge la AI-ul cloud din setările Jarvis; fără cheie se scrie așa cum e."))),
        (("test", L("Проверить диктовку (5 секунд)", "Test dictation (5 seconds)", "Testează dictarea (5 secunde)")),
         ("copy_last", L("Копировать последнюю диктовку", "Copy the last dictation", "Copiază ultima dictare"))),
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
        True,
        (Setting("read_now", "bool", L("Читать новые уведомления сразу", "Read new notifications right away",
                                       "Citește imediat notificările noi"), True,
                 hint=L("Выключено — только по просьбе: «что пришло».", "Off — only on request: “what came in”.",
                        "Oprit — doar la cerere: „ce a venit”.")),
         Setting("app_rules", "multiline", L("Программы", "Apps", "Aplicații"), "", max_length=4000),
         Setting("read_mode", "choice", L("Читать", "Read", "Citește"), "text",
                 hint=L("Отправитель — только кто написал; полностью — все строки уведомления.",
                        "Sender — only who wrote; full — every line of the notification.",
                        "Expeditor — doar cine a scris; complet — toate rândurile notificării."),
                 options=(("sender", L("Отправитель", "Sender", "Expeditor")), ("text", L("С текстом", "With text", "Cu text")),
                          ("full", L("Полностью", "Full", "Complet")))),
         Setting("max_length", "int", L("Длина текста", "Text length", "Lungimea textului"), 140, minimum=40, maximum=400,
                 suffix=L(" зн.", " ch.", " car."),
                 hint=L("Длиннее — обрезается по слову.", "Longer text is cut at a word.", "Textul mai lung se taie la un cuvânt.")),
         Setting("say_app", "bool", L("Называть программу", "Say the app name", "Spune numele aplicației"), True,
                 hint=L("«Telegram: …» в начале фразы.", "“Telegram: …” at the start.", "„Telegram: …” la început.")),
         Setting("skip_links", "bool", L("Не читать ссылки", "Don't read links", "Nu citi linkurile"), True,
                 hint=L("Вместо адреса — слово «ссылка».", "The word “link” instead of the address.", "Cuvântul „link” în loc de adresă.")),
         Setting("skip_codes", "bool", L("Не читать коды", "Don't read codes", "Nu citi codurile"), True,
                 hint=L("4–8 цифр подряд — «пришёл код», сам код не звучит: это может быть код входа.",
                        "4–8 digits in a row — “a code arrived”; the code itself is not spoken: it may be a login code.",
                        "4–8 cifre la rând — „a venit un cod”; codul nu se rostește: poate fi un cod de autentificare.")),
         Setting("group", "bool", L("Несколько сразу — одной фразой", "Several at once — one sentence", "Mai multe deodată — o frază"), True,
                 hint=L("«Telegram: 3 новых сообщения — Мама, Папа».", "“Telegram: 3 new messages — Mom, Dad”.",
                        "„Telegram: 3 mesaje noi — Mama, Tata”.")),
         Setting("translate", "bool", L("Переводить на язык Jarvis", "Translate into Jarvis' language", "Tradu în limba lui Jarvis"), True,
                 hint=L("Уведомление на другом языке сначала переводится, название программы остаётся как есть. "
                        "Переводит офлайн-переводчик на этом ПК — текст никуда не уходит.",
                        "A notification in another language is translated first; the app name stays as is. "
                        "The offline translator on this PC does it — the text goes nowhere.",
                        "O notificare în altă limbă e tradusă întâi; numele aplicației rămâne. "
                        "Traduce traducătorul offline de pe acest PC — textul nu pleacă nicăieri.")),
         Setting("quiet_enabled", "bool", L("Тихие часы", "Quiet hours", "Ore de liniște"), False,
                 hint=L("В это время не читать. Пропущенное — по «что пришло».", "Don't read during these hours. Missed ones — via “what came in”.",
                        "Nu citi în aceste ore. Cele ratate — prin „ce a venit”.")),
         Setting("quiet_from", "int", L("С", "From", "De la"), 23, minimum=0, maximum=23, suffix=L(":00", ":00", ":00")),
         Setting("quiet_to", "int", L("До", "Until", "Până la"), 8, minimum=0, maximum=23, suffix=L(":00", ":00", ":00")),
         Setting("silent_fullscreen", "bool", L("Молчать в игре и видео на весь экран", "Silent in fullscreen games and video",
                                                "Tăcere în jocuri și video pe tot ecranul"), True,
                 hint=L("И в режиме презентации.", "And in presentation mode.", "Și în modul prezentare.")),
         Setting("silent_calls", "bool", L("Молчать во время звонка", "Silent during calls", "Tăcere în timpul apelurilor"), True,
                 hint=L("Когда микрофоном или камерой пользуется другая программа.", "When another app uses the microphone or camera.",
                        "Când altă aplicație folosește microfonul sau camera.")),
         Setting("silent_quiet_mode", "bool", L("Молчать в тихом режиме Jarvis", "Silent in Jarvis quiet mode", "Tăcere în modul silențios Jarvis"), True,
                 hint=L("«Перейди в тихий режим» — уведомления тоже молчат.", "“Switch to quiet mode” — notifications stay silent too.",
                        "„Treci în modul silențios” — și notificările tac.")),
         Setting("repeat_hotkey", "hotkey", L("Повторить последнее", "Repeat the last one", "Repetă ultima"), "",
                 hint=L("По желанию: сочетание, которое повторяет последнее уведомление.", "Optional: a shortcut that repeats the last notification.",
                        "Opțional: o combinație care repetă ultima notificare."))),
        (("test", L("Прослушать пример", "Play a sample", "Ascultă un exemplu")),),
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
         Setting("second_press_stops", "bool", L("Повторное нажатие останавливает чтение", "Second press stops reading", "A doua apăsare oprește citirea"), True),
         Setting("translate", "bool", L("Переводить на язык Jarvis", "Translate into Jarvis' language", "Tradu în limba lui Jarvis"), True,
                 hint=L("Текст на другом языке сначала переводится, и Jarvis сразу читает перевод — по частям, без ожидания всего текста. "
                        "Переводит офлайн-переводчик на этом ПК — быстро и без интернета.",
                        "Text in another language is translated first and Jarvis reads the translation right away — piece by piece. "
                        "The offline translator on this PC does it — fast and without internet.",
                        "Textul în altă limbă e tradus întâi și Jarvis citește imediat traducerea — pe bucăți. "
                        "Traduce traducătorul offline de pe acest PC — rapid și fără internet.")),
         Setting("translate_to", "choice", L("Язык чтения", "Reading language", "Limba citirii"), "auto",
                 options=(("auto", L("Как у Jarvis", "Same as Jarvis", "Ca la Jarvis")),
                          ("ru", L("Русский", "Russian", "Rusă")), ("ro", L("Румынский", "Romanian", "Română")),
                          ("en", L("Английский", "English", "Engleză"))))),
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
        True,
        (Setting("show_on_start", "bool", L("Показывать при запуске программы", "Show when the program starts",
                                            "Afișează la pornirea programului"), False,
                 hint=L("Субтитры появятся сами, как только запустится Jarvis.",
                        "Captions appear by themselves as soon as Jarvis starts.",
                        "Subtitrările apar singure de îndată ce pornește Jarvis.")),
         Setting("language", "choice", L("Язык речи", "Speech language", "Limba vorbirii"), "auto",
                 hint=L("На каком языке говорят в видео или звонке.", "The language spoken in the video or call.",
                        "Limba în care se vorbește în video sau apel."),
                 options=(("auto", L("Определять самому (рекомендуется)", "Detect automatically (recommended)",
                                     "Detectează singur (recomandat)")),
                          ("ru", L("Русский", "Russian", "Rusă")), ("en", L("Английский", "English", "Engleză")),
                          ("ro", L("Румынский", "Romanian", "Română")))),
         Setting("quality", "choice", L("Скорость распознавания", "Recognition speed", "Viteza recunoașterii"), "hybrid",
                 hint=L("Гибрид: черновик с переводом появляется почти сразу, затем точная модель исправляет фразу.",
                        "Hybrid: a draft with its translation appears almost at once, then a precise model corrects the phrase.",
                        "Hibrid: o ciornă cu traducerea apare aproape imediat, apoi un model precis corectează fraza."),
                 options=(("hybrid", L("Гибрид: сразу + точно (рекомендуется)", "Hybrid: instant + accurate (recommended)",
                                       "Hibrid: instant + precis (recomandat)")),
                          ("fast", L("Мгновенно (менее точно)", "Instant (less accurate)", "Instant (mai puțin precis)")),
                          ("balanced", L("Быстро и точно", "Fast and accurate", "Rapid și precis")),
                          ("precise", L("Как у голосовых команд (медленнее)", "Same as voice commands (slower)",
                                        "Ca la comenzile vocale (mai lent)")))),
         Setting("source", "text", L("Что слушать", "What to listen to", "Ce ascult"), "", max_length=120),
         Setting("browser_films", "bool", L("Фильмы в браузере: субтитры заранее", "Browser films: captions in advance",
                                            "Filme în browser: subtitrări din timp"), True,
                 hint=L("С расширением Jarvis для Chrome: уже загруженная часть фильма распознаётся и переводится "
                        "заранее, строки появляются точно вовремя. Не работает с защищённым видео (Netflix и т. п.). "
                        "При выключенных субтитрах расширение ничего не записывает и не отправляет; раз в минуту "
                        "сообщает только, что оно установлено.",
                        "With the Jarvis extension for Chrome: the part of the film already loaded is recognised and "
                        "translated in advance, lines appear exactly on time. Does not work with protected video (Netflix etc.). "
                        "With captions off the extension records and sends nothing; once a minute it only says it is installed.",
                        "Cu extensia Jarvis pentru Chrome: partea de film deja încărcată e recunoscută și tradusă din timp, "
                        "rândurile apar exact la timp. Nu merge cu video protejat (Netflix etc.). Cu subtitrările oprite "
                        "extensia nu înregistrează și nu trimite nimic; doar o dată pe minut spune că e instalată.")),
         Setting("film_model", "choice", L("Модель для фильмов", "Model for films", "Model pentru filme"), "precise",
                 hint=L("«Точная» использует более мощную модель, когда до реплики достаточно времени. "
                        "«Быстрая» меньше нагружает ПК.",
                        "Precise uses a stronger model when enough time remains before the line. "
                        "Fast uses less CPU.",
                        "„Precis” folosește un model mai puternic când rămâne suficient timp până la replică. "
                        "„Rapid” folosește mai puțin procesorul."),
                 options=(("precise", L("Точная (large-v3-turbo)", "Precise (large-v3-turbo)", "Precis (large-v3-turbo)")),
                          ("fast", L("Быстрая (small)", "Fast (small)", "Rapid (small)")))),
         Setting("film_ahead", "choice", L("Готовить вперёд", "Prepare ahead", "Pregătește înainte"), "180",
                 hint=L("Для YouTube готовится до минуты уже загруженного звука. Объём загрузки выбирает YouTube. "
                        "Для других фильмов отдельная загрузка звука может добавить трафик; на паузе готовится до минуты.",
                        "For YouTube, Jarvis prepares up to a minute of buffered audio. YouTube controls the buffer. "
                        "For other films, the separate audio request may use extra bandwidth; on pause it prepares up to a minute.",
                        "Pentru YouTube, Jarvis pregătește până la un minut de audio deja încărcat. YouTube decide cât încarcă. "
                        "La alte filme, cererea audio separată poate folosi trafic în plus; pe pauză se pregătește până la un minut."),
                 options=(("600", L("10 минут", "10 minutes", "10 minute")),
                          ("180", L("3 минуты", "3 minutes", "3 minute")),
                          ("60", L("1 минута", "1 minute", "1 minut")))),
         Setting("film_wait", "choice", L("Ждать субтитры", "Wait for captions", "Așteaptă subtitrările"), "start",
                 hint=L("Расширение может ненадолго поставить видео на паузу, пока готовятся первые строки (до 10 с), "
                        "и после перемотки на 10 с и больше — пока не готова первая фраза (обычно 3–4 с, до 8 с). "
                        "«Также во время фильма»: короткие паузы до 8 с, если субтитры отстают.",
                        "The extension may briefly pause the video while the first lines are prepared (up to 10 s), "
                        "and after a jump of 10 s or more until the first phrase there is ready (usually 3–4 s, up to 8 s). "
                        "«Also during the film»: short holds of up to 8 s when the captions fall behind.",
                        "Extensia poate pune scurt video pe pauză cât se pregătesc primele rânduri (până la 10 s) "
                        "și după o derulare de 10 s sau mai mult, până e gata prima frază (de obicei 3–4 s, cel mult 8 s). "
                        "„Și în timpul filmului”: pauze scurte de până la 8 s când subtitrările rămân în urmă."),
                 options=(("start", L("В начале и после перемотки", "At the start and after a seek",
                                      "La început și după derulare")),
                          ("off", L("Никогда не останавливать", "Never pause the video", "Nu opri niciodată video")),
                          ("always", L("Также во время фильма", "Also during the film", "Și în timpul filmului")))),
         Setting("translate", "bool", L("Переводить", "Translate", "Tradu"), False,
                 hint=L("Под субтитрами — перевод законченных фраз.", "Under the captions — the translation of finished phrases.",
                        "Sub subtitrări — traducerea frazelor terminate.")),
         Setting("translate_to", "choice", L("Язык перевода", "Translation language", "Limba traducerii"), "app",
                 hint=L("По умолчанию — язык программы.", "By default — the program's language.", "Implicit — limba programului."),
                 options=(("app", L("Как язык программы", "Same as the program", "Ca limba programului")),
                          ("ru", L("Русский", "Russian", "Rusă")), ("en", L("Английский", "English", "Engleză")),
                          ("ro", L("Румынский", "Romanian", "Română")))),
         Setting("show_original", "bool", L("Показывать оригинал", "Show the original", "Arată originalul"), False,
                 hint=L("Выключено — на плашке только перевод.", "Off — only the translation on the bar.",
                        "Oprit — pe bandă doar traducerea.")),
         Setting("font_size", "int", L("Размер текста", "Text size", "Mărimea textului"), 26, minimum=14, maximum=48,
                 hint=L("Перевод — чуть мельче оригинала.", "The translation is a little smaller than the original.",
                        "Traducerea e puțin mai mică decât originalul.")),
         Setting("opacity", "int", L("Непрозрачность фона", "Background opacity", "Opacitatea fundalului"), 72,
                 minimum=20, maximum=100, suffix=L(" %", " %", " %"),
                 hint=L("Меньше — сквозь плашку виднее видео.", "Less — the video shows through the bar.",
                        "Mai puțin — video se vede prin bandă.")),
         Setting("lines", "choice", L("Строк текста", "Lines of text", "Rânduri de text"), "2",
                 hint=L("Старое уезжает вверх само.", "Old text scrolls up by itself.", "Textul vechi urcă singur."),
                 options=(("1", L("1", "1", "1")), ("2", L("2", "2", "2")), ("3", L("3", "3", "3")))),
         Setting("hotkey", "hotkey", L("Показать / скрыть", "Show / hide", "Arată / ascunde"), "",
                 hint=L("По желанию: сочетание, которое показывает и прячет субтитры.",
                        "Optional: a shortcut that shows and hides the captions.",
                        "Opțional: o combinație care arată și ascunde subtitrările."))),
        (("toggle", L("Показать субтитры", "Show captions", "Arată subtitrările")),
         ("reset_position", L("Вернуть вниз по центру", "Back to bottom centre", "Înapoi jos la centru")),
         ("browser_extension", L("Расширение для Chrome…", "Chrome extension…", "Extensia pentru Chrome…"))),
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
        True,
        (_hotkey("ctrl+alt+t"),
         Setting("default_action", "choice", L("Действие по умолчанию", "Default action", "Acțiune implicită"), "fix",
                 hint=L("Срабатывает по Enter в окне помощника.", "Runs on Enter in the helper window.",
                        "Rulează la Enter în fereastra asistentului."),
                 options=(("fix", L("Исправить ошибки", "Fix mistakes", "Corectează greșelile")),
                          ("improve", L("Улучшить стиль", "Improve style", "Îmbunătățește stilul")),
                          ("shorten", L("Сократить", "Shorten", "Scurtează")),
                          ("translate", L("Перевести", "Translate", "Tradu")),
                          ("reply", L("Ответить на сообщение", "Reply to the message", "Răspunde la mesaj")))),
         Setting("show_menu", "bool", L("Сначала показать меню действий", "Show the action menu first",
                                        "Arată întâi meniul de acțiuni"), True,
                 hint=L("Выключено — клавиша сразу выполняет действие по умолчанию и показывает результат.",
                        "Off — the key runs the default action at once and shows the result.",
                        "Oprit — tasta rulează direct acțiunea implicită și arată rezultatul.")),
         Setting("translate_to", "choice", L("Переводить на", "Translate to", "Tradu în"), "auto",
                 hint=L("«Авто» — на язык Jarvis; текст на этом языке — на английский.",
                        "«Auto» — into Jarvis' language; text already in it — into English.",
                        "„Auto” — în limba lui Jarvis; textul deja în ea — în engleză."),
                 options=(("auto", L("Авто", "Auto", "Auto")),
                          ("ru", L("Русский", "Russian", "Rusă")), ("ro", L("Румынский", "Romanian", "Română")),
                          ("en", L("Английский", "English", "Engleză")))),
         Setting("ai_source", "choice", L("Какой ИИ работает", "Which AI does the work", "Ce AI lucrează"), "auto",
                 hint=L("Перевод идёт офлайн-переводчиком на этом ПК. Локальная модель работает без интернета, "
                        "но медленнее.",
                        "Translation uses the offline translator on this PC. The local model works without "
                        "internet, but slower.",
                        "Traducerea folosește traducătorul offline de pe acest PC. Modelul local merge fără "
                        "internet, dar mai încet."),
                 options=(("auto", L("Облачный, если подключён, иначе локальный",
                                     "Cloud when connected, otherwise local", "Cloud dacă e conectat, altfel local")),
                          ("cloud", L("Только облачный", "Cloud only", "Doar cloud")),
                          ("local", L("Только локальная модель", "Local model only", "Doar modelul local"))))),
    ),
    Plugin(
        "clipboard_history", "text", "clipboard-paste", "#c47a2c",
        L("История буфера обмена", "Clipboard history", "Istoric clipboard"),
        L("Запоминает, что вы копируете — текст и картинки, — и открывает историю у курсора по клавише.",
          "Remembers what you copy — text and pictures — and opens the history at the cursor with a key.",
          "Ține minte ce copiezi — text și imagini — și deschide istoricul lângă cursor cu o tastă."),
        True,
        (Setting("hotkey", "hotkey", L("Открыть историю", "Open history", "Deschide istoricul"), "alt+win+v",
                 hint=L("Клавиша заработает, когда плагин включён.", "The key works while the plugin is on.",
                        "Tasta funcționează cât pluginul e pornit.")),
         Setting("keep", "choice", L("Сколько помнить", "How many to keep", "Câte păstrez"), "100",
                 hint=L("Обычных записей; старые уходят, когда приходят новые.",
                        "Ordinary items; old ones go when new ones arrive.",
                        "Elemente obișnuite; cele vechi pleacă când vin altele noi."),
                 options=tuple((n, L(f"{n} записей", f"{n} items", f"{n} elemente")) for n in ("25", "50", "100", "200", "500"))),
         Setting("max_age", "choice", L("Хранить не дольше", "Keep no longer than", "Păstrez cel mult"), "0",
                 hint=L("Старше — удаляется само.", "Older items are deleted by themselves.", "Cele mai vechi se șterg singure."),
                 options=(("0", L("Без ограничения", "No limit", "Fără limită")),
                          ("1", L("1 день", "1 day", "1 zi")), ("7", L("7 дней", "7 days", "7 zile")),
                          ("30", L("30 дней", "30 days", "30 de zile")))),
         Setting("persist", "bool", L("Помнить после перезапуска", "Remember after restart", "Păstrez după repornire"), True,
                 hint=L("На диске — только в зашифрованном виде. Выключено — история живёт, пока работает программа.",
                        "On disk only encrypted. Off — the history lives while the program runs.",
                        "Pe disc doar criptat. Oprit — istoricul trăiește cât rulează programul.")),
         Setting("images", "bool", L("Запоминать картинки", "Remember pictures", "Rețin imaginile"), True,
                 hint=L("Скриншоты и скопированные изображения — с миниатюрой в списке.",
                        "Screenshots and copied images — with a thumbnail in the list.",
                        "Capturi și imagini copiate — cu miniatură în listă.")),
         Setting("exclude_apps", "tags", L("Программы", "Programs", "Programe"), "\n".join(CLIPBOARD_EXCLUDE_DEFAULT),
                 max_length=3000),
         Setting("ignore_secrets", "bool", L("Не запоминать похожее на пароли и коды", "Skip things that look like passwords or codes",
                                             "Nu reține ce seamănă cu parole sau coduri"), True,
                 hint=L("Одно «слово» с буквами, цифрами и знаками, коды из SMS, ключи API.",
                        "A single “word” of letters, digits and symbols, SMS codes, API keys.",
                        "Un singur „cuvânt” cu litere, cifre și simboluri, coduri SMS, chei API."))),
        (("open", L("Открыть историю", "Open history", "Deschide istoricul")),
         ("clear", L("Очистить историю", "Clear history", "Golește istoricul")),
         ("clear_all", L("Удалить всё", "Delete all", "Șterge tot"))),
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
        "visual_avatar", "desktop", "avatar-orb", "#3b78f0",
        L("Визуальный аватар", "Visual avatar", "Avatar vizual"),
        L("Анимированный шар поверх экрана, который реагирует на голос ассистента, микрофон или системные звуки.",
          "An animated orb on top of the screen that reacts to the assistant's voice, the microphone or system sounds.",
          "O sferă animată deasupra ecranului care reacționează la vocea asistentului, microfon sau sunetele sistemului."),
        True,
        (Setting("size", "int", L("Размер", "Size", "Mărime"), 100, minimum=50, maximum=200, suffix=L(" %", " %", " %")),
         Setting("opacity", "int", L("Непрозрачность", "Opacity", "Opacitate"), 70, minimum=20, maximum=100, suffix=L(" %", " %", " %")),
         Setting("glow", "int", L("Свечение", "Glow", "Strălucire"), 80, minimum=0, maximum=100, suffix=L(" %", " %", " %")),
         Setting("color_mode", "choice", L("Цвет аватара", "Avatar colour", "Culoarea avatarului"), "custom",
                 options=(("theme", L("Цвет темы", "Theme colour", "Culoarea temei")), ("custom", L("Свой", "Own", "Proprie")))),
         Setting("color", "color", L("Цвет аватара", "Avatar colour", "Culoarea avatarului"), "#1f8fe0",
                 hint=L("Цвет темы меняется вместе с темой Jarvis; состояния временно его перекрывают.",
                        "The theme colour follows the Jarvis theme; states cover it for a moment.",
                        "Culoarea temei urmează tema Jarvis; stările o acoperă pentru o clipă.")),
         Setting("speed", "int", L("Скорость", "Speed", "Viteză"), 50, minimum=0, maximum=100, suffix=L(" %", " %", " %"), hint=L("Спокойно ← → живо.", "Calm ← → lively.", "Calm ← → viu.")),
         Setting("intensity", "int", L("Интенсивность", "Intensity", "Intensitate"), 30, minimum=0, maximum=100, suffix=L(" %", " %", " %")),
         Setting("amplitude", "int", L("Амплитуда", "Amplitude", "Amplitudine"), 50, minimum=0, maximum=100, suffix=L(" %", " %", " %")),
         Setting("smoothness", "int", L("Плавность", "Smoothness", "Netezime"), 100, minimum=0, maximum=100, suffix=L(" %", " %", " %")),
         Setting("react", "bool", L("Реакция на звук", "React to sound", "Reacție la sunet"), True,
                 hint=L("Выключено — аватар только «дышит».", "Off — the avatar only “breathes”.", "Oprit — avatarul doar „respiră”.")),
         Setting("sensitivity", "int", L("Чувствительность", "Sensitivity", "Sensibilitate"), 50, minimum=0, maximum=100, suffix=L(" %", " %", " %"), hint=L("Насколько тихий звук аватар замечает.", "How quiet a sound the avatar notices.", "Cât de încet sunet observă avatarul.")),
         Setting("reaction", "int", L("Интенсивность реакции", "Reaction strength", "Intensitatea reacției"), 45, minimum=0, maximum=100, suffix=L(" %", " %", " %"), hint=L("Насколько сильно аватар отвечает на замеченный звук.", "How strongly the avatar answers a sound.", "Cât de tare răspunde avatarul la sunet.")),
         Setting("state_colors", "bool", L("Смена цвета по состоянию", "Colour by state", "Culoare după stare"), True,
                 hint=L("Выключено — аватар всегда одного цвета.", "Off — the avatar always has one colour.", "Oprit — avatarul are mereu o culoare.")),
         Setting("s_exec", "bool", L("Выполняет команду", "Running a command", "Execută o comandă"), True),
         Setting("c_exec", "color", L("Выполняет команду", "Running a command", "Execută o comandă"), "#2ecf8f"),
         Setting("s_speak", "bool", L("Отвечает голосом", "Answering by voice", "Răspunde cu vocea"), True),
         Setting("c_speak", "color", L("Отвечает голосом", "Answering by voice", "Răspunde cu vocea"), "#f5b942"),
         Setting("s_error", "bool", L("Ошибка", "Error", "Eroare"), True),
         Setting("c_error", "color", L("Ошибка", "Error", "Eroare"), "#ef5350"),
         Setting("s_mic_off", "bool", L("Микрофон выключен", "Microphone off", "Microfon oprit"), True, hint=_PERMANENT),
         Setting("c_mic_off", "color", L("Микрофон выключен", "Microphone off", "Microfon oprit"), "#7c8696"),
         Setting("s_quiet", "bool", L("Тихий режим", "Quiet mode", "Mod silențios"), True, hint=_PERMANENT),
         Setting("c_quiet", "color", L("Тихий режим", "Quiet mode", "Mod silențios"), "#8f98a8"),
         Setting("s_prefix", "bool", L("Режим префикса", "Prefix mode", "Mod prefix"), True, hint=_PERMANENT),
         Setting("c_prefix", "color", L("Режим префикса", "Prefix mode", "Mod prefix"), "#40d3b5"),
         Setting("source", "choice", L("Источник", "Source", "Sursă"), "voice",
                 hint=L("На какой звук реагирует аватар.", "Which sound the avatar reacts to.", "La ce sunet reacționează avatarul."),
                 options=(("voice", L("Голос ассистента — только фразы и ответы Jarvis", "Assistant voice — only Jarvis's phrases",
                                      "Vocea asistentului — doar frazele lui Jarvis")),
                          ("system", L("Все звуки компьютера — музыка, видео, игры", "All PC sounds — music, video, games",
                                       "Toate sunetele PC-ului — muzică, video, jocuri")),
                          ("mic", L("Микрофон — ваш голос и звуки рядом", "Microphone — your voice and sounds nearby",
                                    "Microfon — vocea ta și sunetele din jur")),
                          ("apps", L("Звуки выбранных приложений", "Sounds of chosen programs", "Sunetele programelor alese")),
                          ("all", L("Все источники — и компьютер, и микрофон", "All sources — PC and microphone",
                                    "Toate sursele — PC și microfon")))),
         Setting("apps", "tags", L("Программы", "Programs", "Programe"), "",
                 hint=L("Программа, например Discord.exe", "Program, e.g. Discord.exe", "Program, de ex. Discord.exe"), max_length=600),
         Setting("position", "text", L("Положение на экране", "Position on screen", "Poziția pe ecran"), "br", max_length=24),
         Setting("monitor", "text", L("Монитор", "Monitor", "Monitor"), "0", max_length=3),
         Setting("lock", "bool", L("Закрепить положение", "Lock position", "Fixează poziția"), False,
                 hint=L("Не перетаскивается и пропускает щелчки.", "Cannot be dragged and lets clicks through.",
                        "Nu se trage și lasă clicurile să treacă.")),
         Setting("drag", "bool", L("Перетаскивание мышью", "Drag with the mouse", "Tragere cu mouse-ul"), True),
         Setting("snap", "bool", L("Прилипание к краям", "Stick to edges", "Lipire de margini"), True,
                 hint=L("Отпустили рядом с краем экрана — аватар прилипнет к нему.", "Released near a screen edge, it sticks to it.",
                        "Lăsat lângă marginea ecranului, se lipește de ea.")),
         Setting("mini", "bool", L("Мини-режим у края", "Mini mode at the edge", "Mod mini la margine"), True,
                 hint=L("У края аватар наполовину прячется за него.", "At the edge the avatar half hides behind it.",
                        "La margine avatarul se ascunde pe jumătate.")),
         Setting("on_top", "bool", L("Показывать поверх окон", "Show above windows", "Deasupra ferestrelor"), True),
         Setting("hide_fullscreen", "bool", L("Автоматически скрывать в полноэкранных приложениях",
                                              "Hide automatically in full-screen apps", "Ascunde automat în aplicații pe tot ecranul"), True),
         Setting("autostart", "bool", L("Запускать вместе с программой", "Start with the program", "Pornește odată cu programul"), True),
         Setting("fps", "choice", L("Частота кадров", "Frame rate", "Cadre pe secundă"), "60",
                 hint=L("30 — меньше нагрузка на компьютер.", "30 — less load on the PC.", "30 — mai puțină încărcare."),
                 options=(("30", L("30 к/с", "30 fps", "30 fps")), ("60", L("60 к/с", "60 fps", "60 fps"))))),
        (("reset_position", L("Вернуть на место", "Back to its place", "Înapoi la loc")),),
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
        (Setting("eyes_on", "bool", L("Глаза — правило 20-20-20", "Eyes — the 20-20-20 rule", "Ochi — regula 20-20-20"), True,
                 hint=L("Посмотреть вдаль 20 секунд.", "Look into the distance for 20 seconds.", "Privește în depărtare 20 de secunde.")),
         Setting("eyes_every", "choice", L("Глаза", "Eyes", "Ochi"), "20", options=(("10", L("каждые 10 мин", "every 10 min", "la fiecare 10 min")), ("15", L("каждые 15 мин", "every 15 min", "la fiecare 15 min")), ("20", L("каждые 20 мин", "every 20 min", "la fiecare 20 min")), ("25", L("каждые 25 мин", "every 25 min", "la fiecare 25 min")), ("30", L("каждые 30 мин", "every 30 min", "la fiecare 30 min")), ("40", L("каждые 40 мин", "every 40 min", "la fiecare 40 min")), ("45", L("каждые 45 мин", "every 45 min", "la fiecare 45 min")), ("60", L("каждые 60 мин", "every 60 min", "la fiecare 60 min")),)),
         Setting("stretch_on", "bool", L("Разминка", "Stretch", "Întinderi"), True,
                 hint=L("Встать, потянуться, пройтись пару минут.", "Stand up, stretch, walk for a couple of minutes.",
                        "Ridică-te, întinde-te, plimbă-te câteva minute.")),
         Setting("stretch_every", "choice", L("Разминка", "Stretch", "Întinderi"), "55", options=(("30", L("каждые 30 мин", "every 30 min", "la fiecare 30 min")), ("40", L("каждые 40 мин", "every 40 min", "la fiecare 40 min")), ("45", L("каждые 45 мин", "every 45 min", "la fiecare 45 min")), ("50", L("каждые 50 мин", "every 50 min", "la fiecare 50 min")), ("55", L("каждые 55 мин", "every 55 min", "la fiecare 55 min")), ("60", L("каждые 60 мин", "every 60 min", "la fiecare 60 min")), ("75", L("каждые 75 мин", "every 75 min", "la fiecare 75 min")), ("90", L("каждые 90 мин", "every 90 min", "la fiecare 90 min")), ("120", L("каждые 120 мин", "every 120 min", "la fiecare 120 min")),)),
         Setting("water_on", "bool", L("Вода", "Water", "Apă"), True,
                 hint=L("Стакан воды.", "A glass of water.", "Un pahar cu apă.")),
         Setting("water_every", "choice", L("Вода", "Water", "Apă"), "90", options=(("45", L("каждые 45 мин", "every 45 min", "la fiecare 45 min")), ("60", L("каждые 60 мин", "every 60 min", "la fiecare 60 min")), ("75", L("каждые 75 мин", "every 75 min", "la fiecare 75 min")), ("90", L("каждые 90 мин", "every 90 min", "la fiecare 90 min")), ("120", L("каждые 120 мин", "every 120 min", "la fiecare 120 min")), ("150", L("каждые 150 мин", "every 150 min", "la fiecare 150 min")), ("180", L("каждые 180 мин", "every 180 min", "la fiecare 180 min")),)),
         Setting("voice", "bool", L("Голосом", "By voice", "Prin voce"), False,
                 hint=L("Ассистент скажет напоминание вслух текущим голосом.", "The assistant says the reminder aloud in its current voice.",
                        "Asistentul rostește mementoul cu vocea curentă.")),
         Setting("pet", "bool", L("С питомцем", "With the pet", "Cu animăluțul"), True,
                 hint=L("Сработает, когда включён плагин «Питомец».", "Works when the “Desktop pet” plugin is on.",
                        "Funcționează când pluginul „Animăluț” e pornit.")),
         Setting("quiet_enabled", "bool", L("Тихие часы", "Quiet hours", "Ore de liniște"), False,
                 hint=L("В это время напоминаний нет.", "No reminders during these hours.", "Fără mementouri în aceste ore.")),
         Setting("quiet_from", "choice", L("С", "From", "De la"), "22", options=(("0", L("00:00", "00:00", "00:00")), ("1", L("01:00", "01:00", "01:00")), ("2", L("02:00", "02:00", "02:00")), ("3", L("03:00", "03:00", "03:00")), ("4", L("04:00", "04:00", "04:00")), ("5", L("05:00", "05:00", "05:00")), ("6", L("06:00", "06:00", "06:00")), ("7", L("07:00", "07:00", "07:00")), ("8", L("08:00", "08:00", "08:00")), ("9", L("09:00", "09:00", "09:00")), ("10", L("10:00", "10:00", "10:00")), ("11", L("11:00", "11:00", "11:00")), ("12", L("12:00", "12:00", "12:00")), ("13", L("13:00", "13:00", "13:00")), ("14", L("14:00", "14:00", "14:00")), ("15", L("15:00", "15:00", "15:00")), ("16", L("16:00", "16:00", "16:00")), ("17", L("17:00", "17:00", "17:00")), ("18", L("18:00", "18:00", "18:00")), ("19", L("19:00", "19:00", "19:00")), ("20", L("20:00", "20:00", "20:00")), ("21", L("21:00", "21:00", "21:00")), ("22", L("22:00", "22:00", "22:00")), ("23", L("23:00", "23:00", "23:00")),)),
         Setting("quiet_to", "choice", L("До", "Until", "Până la"), "8", options=(("0", L("00:00", "00:00", "00:00")), ("1", L("01:00", "01:00", "01:00")), ("2", L("02:00", "02:00", "02:00")), ("3", L("03:00", "03:00", "03:00")), ("4", L("04:00", "04:00", "04:00")), ("5", L("05:00", "05:00", "05:00")), ("6", L("06:00", "06:00", "06:00")), ("7", L("07:00", "07:00", "07:00")), ("8", L("08:00", "08:00", "08:00")), ("9", L("09:00", "09:00", "09:00")), ("10", L("10:00", "10:00", "10:00")), ("11", L("11:00", "11:00", "11:00")), ("12", L("12:00", "12:00", "12:00")), ("13", L("13:00", "13:00", "13:00")), ("14", L("14:00", "14:00", "14:00")), ("15", L("15:00", "15:00", "15:00")), ("16", L("16:00", "16:00", "16:00")), ("17", L("17:00", "17:00", "17:00")), ("18", L("18:00", "18:00", "18:00")), ("19", L("19:00", "19:00", "19:00")), ("20", L("20:00", "20:00", "20:00")), ("21", L("21:00", "21:00", "21:00")), ("22", L("22:00", "22:00", "22:00")), ("23", L("23:00", "23:00", "23:00")),)),
         Setting("silent_fullscreen", "bool", L("Игры и окна во весь экран", "Games and full-screen windows", "Jocuri și ferestre pe tot ecranul"), True,
                 hint=L("И презентации: напоминание подождёт, пока они не закончатся.",
                        "And presentations: the reminder waits until they end.", "Și prezentări: mementoul așteaptă să se termine.")),
         Setting("silent_calls", "bool", L("Звонки", "Calls", "Apeluri"), True,
                 hint=L("Пока микрофоном или камерой пользуется другая программа.", "While another app uses the microphone or camera.",
                        "Cât timp altă aplicație folosește microfonul sau camera.")),
         Setting("silent_quiet_mode", "bool", L("Тихий режим Jarvis", "Jarvis quiet mode", "Modul silențios Jarvis"), True,
                 hint=L("Пока включён тихий режим, напоминаний нет.", "No reminders while quiet mode is on.",
                        "Fără mementouri cât modul silențios e pornit.")),
         Setting("silent_windows_dnd", "bool", L("«Не беспокоить» Windows", "Windows “Do not disturb”", "„Nu deranja” din Windows"), True,
                 hint=L("Если Windows сообщает, что «Не беспокоить» включено, напоминание ждёт.",
                        "If Windows reports “Do not disturb”, the reminder waits.",
                        "Dacă Windows raportează „Nu deranja”, mementoul așteaptă."))),
        (("try_eyes", L("Глаза", "Eyes", "Ochi")), ("try_stretch", L("Разминка", "Stretch", "Întinderi")),
         ("try_water", L("Вода", "Water", "Apă"))),
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
        True,
        (Setting("token", "secret", L("Токен бота (BotFather)", "Bot token (BotFather)", "Tokenul botului (BotFather)"), "",
                 hint=L("Из @BotFather → /newbot. Хранится в защищённом хранилище Windows, не в config.json.",
                        "From @BotFather → /newbot. Kept in Windows protected storage, not in config.json.",
                        "De la @BotFather → /newbot. Se păstrează în stocarea protejată Windows, nu în config.json."),
                 max_length=100),
         Setting("owner_id", "text", L("Telegram ID владельца", "Owner Telegram ID", "ID Telegram proprietar"), "",
                 hint=L("Бот выполняет команды только от вас. Не знаете ID — напишите боту /start, он подскажет.",
                        "The bot runs commands only for you. Don't know your ID — send /start to the bot.",
                        "Botul rulează comenzi doar pentru tine. Nu știi ID-ul — trimite /start botului."),
                 max_length=15, pattern=r"\d{3,15}"),
         Setting("ui_mode", "choice", L("Тип интерфейса бота", "Bot interface", "Interfața botului"), "inline",
                 hint=L("Кнопки под сообщением бота или клавиатура внизу чата.", "Buttons under the bot message or a keyboard at the bottom.",
                        "Butoane sub mesajul botului sau tastatură jos în chat."),
                 options=(("inline", L("Под сообщением", "Under message", "Sub mesaj")),
                          ("keyboard", L("Клавиатура", "Keyboard", "Tastatură")))),
         Setting("ignore_unknown", "bool", L("Игнорировать сообщения без команд", "Ignore messages without commands",
                                             "Ignoră mesajele fără comenzi"), False,
                 hint=L("Обычные сообщения не считаются командами.", "Ordinary messages are not treated as commands.",
                        "Mesajele obișnuite nu sunt considerate comenzi.")),
         Setting("confirm_sensitive", "bool", L("Подтверждать команды «спросить перед запуском»", "Confirm “ask before run” commands",
                                                "Confirmă comenzile „întreabă înainte”"), True,
                 hint=L("Кнопки «Выполнить / Отмена» прямо в Telegram.", "“Run / Cancel” buttons right in Telegram.",
                        "Butoane „Rulează / Anulează” direct în Telegram.")),
         Setting("notify", "bool", L("Уведомления о выполнении команд", "Command result notifications", "Notificări despre comenzi"), True,
                 hint=L("Отправлять в Telegram текст об успехе, ошибке или недоступности команды. Независимо от голосовых ответов на ПК.",
                        "Send success, error or unavailability text to Telegram. Independent of spoken replies on the PC.",
                        "Trimite în Telegram rezultatul, eroarea sau indisponibilitatea. Independent de răspunsurile vocale pe PC.")),
         Setting("voice_replies", "bool", L("Голосовые ответы программы", "Spoken replies on the PC", "Răspunsuri vocale pe PC"), True,
                 hint=L("Озвучивать на компьютере ответы команд, запущенных из Telegram. Глобальный тихий режим имеет приоритет.",
                        "Speak replies of Telegram-started commands on the PC. Global quiet mode wins.",
                        "Rostește pe PC răspunsurile comenzilor din Telegram. Modul silențios global are prioritate.")),
         Setting("autostart", "bool", L("Запускать вместе с программой", "Start with the app", "Pornește odată cu aplicația"), True)),
        (("check", L("Проверить подключение", "Check connection", "Verifică conexiunea")),
         ("open", L("Открыть бота", "Open the bot", "Deschide botul"))),
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
        True,
        (Setting("sound", "bool", L("Звуковой сигнал", "Sound signal", "Semnal sonor"), True,
                 hint=L("Повторяющийся сигнал, пока вы не нажмёте «Стоп» или «Отложить».",
                        "A repeating signal until you press Stop or Snooze.",
                        "Un semnal repetat până apeși Stop sau Amână.")),
         Setting("ring_seconds", "int", L("Звонить не дольше", "Ring for at most", "Sună cel mult"), 60, minimum=10, maximum=300,
                 suffix=L(" с", " s", " s")),
         Setting("speak", "bool", L("Сказать вслух", "Say it aloud", "Spune cu voce"), True,
                 hint=L("«Время вышло: таймер на 10 минут», «Будильник: 07:30». Тихий режим имеет приоритет.",
                        "“Time is up: 10 minute timer”, “Alarm: 07:30”. Quiet mode wins.",
                        "„Timpul a expirat: cronometru de 10 minute”, „Alarmă: 07:30”. Modul silențios are prioritate.")),
         Setting("popup", "bool", L("Окно поверх всех окон", "Window on top of everything", "Fereastră deasupra tuturor"), True,
                 hint=L("С кнопками «Отложить» и «Стоп». Работает, даже если Jarvis свёрнут.",
                        "With Snooze and Stop buttons. Works even when Jarvis is minimized.",
                        "Cu butoanele Amână și Stop. Funcționează chiar dacă Jarvis e minimizat.")),
         Setting("snooze", "int", L("Отложить на", "Snooze for", "Amână cu"), 5, minimum=1, maximum=30, suffix=_MINUTES)),
    ),
    # --- Files, screen and streams ---------------------------------------
    Plugin(
        "converter", "files", "images", "#4e9a2f",
        L("Конвертер", "Converter", "Convertor"),
        L("Круг у курсора для выделенных файлов: картинки в PNG, JPG, WebP, ICO и PDF, сжать и уменьшить, "
          "звук и видео в нужный формат. Оригиналы не трогает.",
          "A circle at the cursor for selected files: images to PNG, JPG, WebP, ICO and PDF, compress and downsize, "
          "audio and video to the format you need. Originals stay untouched.",
          "Un cerc lângă cursor pentru fișierele selectate: imagini în PNG, JPG, WebP, ICO și PDF, comprimare, "
          "sunet și video în formatul dorit. Originalele rămân neatinse."),
        True,
        (Setting("hotkey", "hotkey", L("Круг для выделенного", "Circle for the selection", "Cerc pentru selecție"), "ctrl+alt+x",
                 hint=L("Клавиша заработает, когда плагин включён.", "The key works when the plugin is on.",
                        "Tasta funcționează când pluginul e activ.")),
         Setting("region_hotkey", "hotkey", L("Снимок области", "Screen area", "Zonă de ecran"), "",
                 hint=L("По желанию: обведите область экрана — и сразу круг действий над снимком.",
                        "Optional: draw a screen area — and get the action circle for that snapshot.",
                        "Opțional: încadrează o zonă a ecranului — și apare cercul de acțiuni pentru captură.")),
         Setting("destination", "choice", L("Куда класть", "Where to save", "Unde salvez"), "next",
                 hint=L("Готовый файл получает новое имя — исходник не меняется и не перезаписывается.",
                        "The result gets a new name — the original is never changed or overwritten.",
                        "Rezultatul primește un nume nou — originalul nu se schimbă."),
                 options=(("next", L("Рядом с файлом", "Next to the file", "Lângă fișier")),
                          ("folder", L("В папку", "To a folder", "Într-un dosar")))),
         Setting("folder", "folder", L("Папка для результатов", "Results folder", "Dosarul pentru rezultate"), "",
                 hint=L("Пусто — «Загрузки\\Jarvis Converted». Сюда же попадают снимки и картинки из буфера.",
                        "Empty — “Downloads\\Jarvis Converted”. Snapshots and clipboard pictures go here too.",
                        "Gol — „Descărcări\\Jarvis Converted”. Aici ajung și capturile și imaginile din clipboard.")),
         Setting("quality", "int", L("Качество JPG", "JPG quality", "Calitate JPG"), 85, minimum=30, maximum=100,
                 hint=L("Для «в JPG» и WebP; 85 — незаметно глазу и заметно легче.", "For JPG and WebP; 85 looks the same and is much lighter.",
                        "Pentru JPG și WebP; 85 arată la fel și e mult mai ușor.")),
         Setting("s_format", "bool", L("Формат", "Format", "Format"), True),
         Setting("s_compress", "bool", L("Сжать", "Compress", "Comprimă"), True),
         Setting("s_resize", "bool", L("Уменьшить", "Downsize", "Micșorează"), True),
         Setting("s_rotate", "bool", L("Повернуть", "Rotate", "Rotește"), True),
         Setting("s_crop", "bool", L("Обрезать", "Crop", "Decupează"), True),
         Setting("s_nometa", "bool", L("Без метаданных", "No metadata", "Fără metadate"), True),
         Setting("s_pdf", "bool", L("В PDF", "To PDF", "În PDF"), True),
         Setting("s_clipboard", "bool", L("В буфер", "To clipboard", "În clipboard"), True),
         Setting("s_mp3", "bool", L("MP3", "MP3", "MP3"), True),
         Setting("s_m4a", "bool", L("M4A", "M4A", "M4A"), True),
         Setting("s_wav", "bool", L("WAV", "WAV", "WAV"), True),
         Setting("s_flac", "bool", L("FLAC", "FLAC", "FLAC"), True),
         Setting("s_ogg", "bool", L("OGG", "OGG", "OGG"), True),
         Setting("s_opus", "bool", L("OPUS", "OPUS", "OPUS"), True),
         Setting("s_mp4", "bool", L("В MP4", "To MP4", "În MP4"), True),
         Setting("s_vcompress", "bool", L("Сжать видео", "Compress video", "Comprimă video"), True),
         Setting("s_gif", "bool", L("В GIF", "To GIF", "În GIF"), True),
         Setting("s_tomp3", "bool", L("Звук в MP3", "Audio to MP3", "Sunet în MP3"), True),
         Setting("s_mute", "bool", L("Без звука", "No sound", "Fără sunet"), True),
         Setting("circle_theme", "choice", L("Оформление круга", "Circle style", "Aspectul cercului"), "app",
                 hint=L("«Как в программе» берёт светлое или тёмное оформление Jarvis.",
                        "“Like the app” follows the Jarvis light or dark theme.",
                        "„Ca în aplicație” urmează tema Jarvis, deschisă sau închisă."),
                 options=(("app", L("Как в программе", "Like the app", "Ca în aplicație")),
                          ("dark", L("Тёмное", "Dark", "Închis")), ("light", L("Светлое", "Light", "Deschis"))))),
        (("convert", L("Выбрать файлы…", "Choose files…", "Alege fișiere…")),),
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


@dataclass(frozen=True)
class Section:
    id: str
    icon: str
    title: dict
    subtitle: dict
    keys: tuple
    groups: tuple = ()  # ((title dict, keys), ...) shown as a 2-column switch grid


CONVERTER_IMAGE_SECTORS = ("s_format", "s_compress", "s_resize", "s_rotate", "s_crop", "s_nometa", "s_pdf", "s_clipboard")
CONVERTER_AUDIO_SECTORS = ("s_mp3", "s_m4a", "s_wav", "s_flac", "s_ogg", "s_opus")
CONVERTER_VIDEO_SECTORS = ("s_mp4", "s_vcompress", "s_gif", "s_tomp3", "s_mute")

# Settings pages are grouped into cards. Plugins not listed get one generic
# "Settings" card. The "basic" (on/off) card and the actions/test card are
# always added by the page itself.
SECTIONS = {
    "visual_avatar": (
        Section("look", "palette", L("Внешний вид", "Look", "Aspect"),
                L("Размер, прозрачность, свечение и цвет аватара.", "Size, transparency, glow and colour of the avatar.",
                  "Mărimea, transparența, strălucirea și culoarea avatarului."),
                ("size", "opacity", "glow", "color")),
        Section("motion", "audio-lines", L("Анимация", "Animation", "Animație"),
                L("Как аватар «дышит» сам по себе, даже в тишине.", "How the avatar “breathes” by itself, even in silence.",
                  "Cum „respiră” avatarul singur, chiar și în liniște."),
                ("speed", "intensity", "amplitude", "smoothness")),
        Section("reaction", "volume-2", L("Реакция", "Reaction", "Reacție"),
                L("Как аватар отвечает на звук выбранного источника.", "How the avatar answers the sound of the chosen source.",
                  "Cum răspunde avatarul la sunetul sursei alese."),
                ("react", "sensitivity", "reaction")),
        Section("states", "layers", L("Цвет состояний", "State colours", "Culorile stărilor"),
                L("Когда аватар временно меняет цвет на время события.", "When the avatar changes colour for an event.",
                  "Când avatarul își schimbă culoarea pe durata unui eveniment."),
                ("state_colors", "s_exec", "s_speak", "s_error", "s_mic_off", "s_quiet", "s_prefix")),
        Section("source", "mic", L("Источник анимации", "Animation source", "Sursa animației"),
                L("На какой звук реагирует аватар.", "Which sound the avatar reacts to.", "La ce sunet reacționează avatarul."),
                ("source", "apps")),
        Section("behaviour", "app-window", L("Поведение", "Behaviour", "Comportament"),
                L("Где стоит аватар и как ведёт себя у края экрана.", "Where the avatar stands and how it behaves at the screen edge.",
                  "Unde stă avatarul și cum se poartă la marginea ecranului."),
                ("@position_grid", "@monitor", "lock", "drag", "snap", "mini", "on_top", "hide_fullscreen")),
    ),
    "live_captions": (
        Section("sound", "headphones", L("Звук и язык", "Sound and language", "Sunet și limbă"),
                L("На каком языке говорят и что слушать.", "Which language is spoken and what to listen to.",
                  "Ce limbă se vorbește și ce ascult."),
                ("language", "quality", "@source", "browser_films", "film_model", "film_ahead", "film_wait", "@browser_extension")),
        Section("translate", "globe", L("Перевод", "Translation", "Traducere"),
                L("Законченные фразы переводятся на ваш язык прямо на этом ПК.",
                  "Finished phrases are translated into your language right on this PC.",
                  "Frazele terminate sunt traduse în limba ta chiar pe acest PC."),
                ("translate", "translate_to", "show_original", "@tr_status")),
        Section("look", "sliders-horizontal", L("Вид", "Look", "Aspect"),
                L("Размер текста, прозрачность плашки, сколько строк видно.", "Text size, bar transparency, how many lines show.",
                  "Mărimea textului, transparența benzii, câte rânduri se văd."),
                ("font_size", "opacity", "lines", "@position")),
        Section("key", "keyboard", L("Клавиша", "Key", "Tastă"),
                L("Показать и скрыть субтитры одним сочетанием.", "Show and hide the captions with one shortcut.",
                  "Arată și ascunde subtitrările cu o combinație."),
                ("hotkey",)),
    ),
    "clipboard_history": (
        Section("key", "keyboard", L("Клавиша", "Key", "Tastă"),
                L("По ней у курсора открывается окно истории.", "It opens the history window at the cursor.",
                  "Deschide fereastra istoricului lângă cursor."),
                ("hotkey",)),
        Section("storage", "history", L("Что и как долго помнить", "What and how long to remember", "Ce și cât timp rețin"),
                L("Закреплённые записи не стареют и не вытесняются новыми.", "Pinned items never age and are never pushed out.",
                  "Elementele fixate nu îmbătrânesc și nu sunt înlocuite."),
                ("keep", "max_age", "persist", "images", "@clip_now")),
        Section("exclude", "shield-check", L("Не запоминать", "Do not remember", "Nu reține"),
                L("Программы, копирования из которых не попадают в историю.", "Programs whose copies never enter the history.",
                  "Programe ale căror copieri nu intră în istoric."),
                ("@note", "exclude_apps", "ignore_secrets")),
        Section("ai", "sparkles", L("Нейросеть", "AI", "AI"),
                L("«Перевести», «Исправить ошибки» и «Кратко» у текстовой записи — правой кнопкой или кнопкой со звёздочкой.",
                  "“Translate”, “Fix mistakes” and “Shorten” for a text item — right click or the sparkle button.",
                  "„Tradu”, „Corectează” și „Pe scurt” pentru un text — clic dreapta sau butonul cu steluță."),
                ("@ai_status",)),
    ),
    "pc_control": (
        Section("connection", "link", L("Подключение", "Connection", "Conexiune"),
                L("Ваш личный бот в Telegram. Он отвечает только вам.", "Your personal Telegram bot. It answers only you.",
                  "Botul tău personal din Telegram. Răspunde doar ție."),
                ("token", "@status", "owner_id")),
        Section("menu", "layout-grid", L("Меню в Telegram", "Telegram menu", "Meniul în Telegram"),
                L("Ваши папки команд становятся кнопками.", "Your command folders become buttons.",
                  "Dosarele tale de comenzi devin butoane."),
                ("ui_mode", "ignore_unknown", "confirm_sensitive")),
        Section("replies", "message-square", L("Ответы", "Replies", "Răspunsuri"),
                L("Что бот пишет и что звучит на компьютере.", "What the bot writes and what plays on the PC.",
                  "Ce scrie botul și ce se aude pe PC."),
                ("notify", "voice_replies")),
    ),
    "notification_reader": (
        Section("what", "message-square", L("Что читать", "What to read", "Ce citesc"),
                L("Сколько говорить и что пропускать.", "How much to say and what to skip.", "Cât spun și ce sar."),
                ("read_mode", "max_length", "say_app", "skip_links", "skip_codes", "group", "translate")),
        Section("quiet", "moon", L("Когда молчать", "When to stay silent", "Când tac"),
                L("Тихие часы и случаи, когда читать вслух неуместно.", "Quiet hours and moments when reading aloud is out of place.",
                  "Ore de liniște și momente când citirea nu e potrivită."),
                ("quiet_enabled", "quiet_from", "quiet_to", "silent_fullscreen", "silent_calls", "silent_quiet_mode")),
        Section("voice", "mic", L("Голос и клавиша", "Voice and key", "Voce și tastă"),
                L("Как спросить и как остановить.", "How to ask and how to stop.", "Cum întrebi și cum oprești."),
                ("repeat_hotkey",)),
    ),
    "converter": (
        Section("keys", "keyboard", L("Клавиши", "Keys", "Taste"),
                L("Круг для выделенных файлов и снимок области экрана.", "The circle for selected files and a screen-area snapshot.",
                  "Cercul pentru fișiere selectate și captura unei zone."),
                ("hotkey", "region_hotkey")),
        Section("result", "folder", L("Результат", "Result", "Rezultat"),
                L("Куда класть готовые файлы и качество JPG.", "Where results go and JPG quality.", "Unde ajung rezultatele și calitatea JPG."),
                ("destination", "folder", "quality")),
        Section("sectors", "layers", L("Сектора круга", "Circle sectors", "Sectoarele cercului"),
                L("Что показывать в круге — лишнее можно убрать.", "What the circle shows — hide what you don't need.",
                  "Ce arată cercul — ascunde ce nu-ți trebuie."),
                CONVERTER_IMAGE_SECTORS + CONVERTER_AUDIO_SECTORS + CONVERTER_VIDEO_SECTORS,
                groups=((L("Картинки", "Images", "Imagini"), CONVERTER_IMAGE_SECTORS),
                        (L("Звук", "Audio", "Sunet"), CONVERTER_AUDIO_SECTORS),
                        (L("Видео", "Video", "Video"), CONVERTER_VIDEO_SECTORS))),
        Section("appearance", "palette", L("Оформление", "Appearance", "Aspect"),
                L("Как выглядит круг.", "How the circle looks.", "Cum arată cercul."), ("circle_theme",)),
    ),
    "breaks": (
        Section("reminders", "bell", L("Напоминания", "Reminders", "Mementouri"),
                L("Включите нужные и выберите, как часто.", "Turn on the ones you need and choose how often.",
                  "Pornește-le pe cele de care ai nevoie și alege cât de des."),
                ("eyes_on", "eyes_every", "stretch_on", "stretch_every", "water_on", "water_every")),
        Section("how", "volume-2", L("Как напоминать", "How to remind", "Cum amintesc"),
                L("Плашка в углу экрана — всегда; голос и питомец — по желанию.",
                  "A card in the screen corner — always; voice and pet — optional.",
                  "Un card în colțul ecranului — mereu; vocea și animăluțul — opțional."),
                ("voice", "pet")),
        Section("quiet", "moon", L("Не мешать", "Do not disturb", "Nu deranja"),
                L("Когда напоминание подождёт.", "When a reminder waits.", "Când mementoul așteaptă."),
                ("quiet_enabled", "quiet_from", "quiet_to", "silent_fullscreen", "silent_calls", "silent_quiet_mode",
                 "silent_windows_dnd")),
    ),
    "timers": (
        Section("signal", "bell-ring", L("Сигнал", "Signal", "Semnal"),
                L("Как сообщить, что время вышло.", "How to tell you that time is up.", "Cum îți spun că a expirat timpul."),
                ("sound", "ring_seconds", "speak", "popup", "snooze")),
    ),
    "smart_dictation": (
        Section("keys", "keyboard", L("Клавиша и режим", "Key and mode", "Tastă și mod"),
                L("Чем начинать диктовку и как её заканчивать.", "How to start and finish dictation.",
                  "Cum pornești și cum oprești dictarea."),
                ("trigger", "hotkey", "mode", "silence_pause")),
        Section("voice", "audio-lines", L("Голосом", "By voice", "Prin voce"),
                L("Начать диктовку фразой, без клавиши.", "Start dictation with a phrase, no key.",
                  "Pornește dictarea cu o frază, fără tastă."),
                ("voice_trigger", "voice_phrases")),
        Section("text", "type", L("Язык и текст", "Language and text", "Limbă și text"),
                L("На каком языке говорить и что делать со знаками.", "Which language you speak and what to do with marks.",
                  "În ce limbă vorbești și ce se face cu semnele."),
                ("language", "punctuation", "sound")),
        Section("ai", "sparkles", L("Нейросеть", "AI", "AI"),
                L("Исправит знаки и ошибки распознавания, не меняя смысл.", "Fixes marks and recognition mistakes without changing meaning.",
                  "Corectează semnele și greșelile fără să schimbe sensul."),
                ("ai_cleanup",)),
    ),
}

# A setting is editable only while another setting has one of these values.
ENABLED_IF = {
    "read_aloud": {"translate_to": ("translate", (True,))},
    "notification_reader": {"quiet_from": ("quiet_enabled", (True,)), "quiet_to": ("quiet_enabled", (True,))},
    "converter": {"folder": ("destination", ("folder",))},
    "live_captions": {"translate_to": ("translate", (True,)), "show_original": ("translate", (True,))},
    "visual_avatar": dict({"sensitivity": ("react", (True,)), "reaction": ("react", (True,)),
                           "apps": ("source", ("apps",)), "drag": ("lock", (False,))},
                          **{f"s_{state}": ("state_colors", (True,)) for state in ("exec", "speak", "error", "mic_off", "quiet", "prefix")}),
    "timers": {"ring_seconds": ("sound", (True,))},
    "smart_dictation": {
        "hotkey": ("trigger", ("hotkey",)),
        "silence_pause": ("mode", ("toggle",)),
        "voice_phrases": ("voice_trigger", (True,)),
    },
}

# The on/off card goes last for these plugins (as in Luxify) and can hold
# extra settings.
BASIC_LAST = {"pc_control", "visual_avatar"}
BASIC_KEYS = {"pc_control": ("autostart",), "live_captions": ("show_on_start",), "visual_avatar": ("autostart", "fps")}

# Information shown in the basic card.
BASIC_NOTE = {
    "clipboard_history": L("Пароли из менеджеров паролей (KeePass, Bitwarden, 1Password и другие) и всё, что программы помечают "
                           "«не для истории», не запоминается. Временные вставки самого Jarvis — тоже. История хранится только "
                           "на этом компьютере, зашифрованной.",
                           "Passwords from password managers (KeePass, Bitwarden, 1Password and others) and anything programs "
                           "mark “not for history” are never remembered. Jarvis's own temporary pastes neither. The history "
                           "stays only on this PC, encrypted.",
                           "Parolele din managerele de parole (KeePass, Bitwarden, 1Password și altele) și tot ce programele "
                           "marchează „nu pentru istoric” nu se rețin. Nici lipirile temporare ale lui Jarvis. Istoricul rămâne "
                           "doar pe acest PC, criptat."),
    "notification_reader": L("Уведомления — ваша переписка. Jarvis держит в памяти только последние 20, ничего не пишет на диск "
                             "и в журналы. Перевод делается на этом ПК — текст уведомлений никуда не уходит. Пока компьютер "
                             "заблокирован, ничего не читается.",
                             "Notifications are your messages. Jarvis keeps only the last 20 in memory and writes nothing to disk "
                             "or logs. Translation happens on this PC — notification text goes nowhere. Nothing is read while "
                             "the PC is locked.",
                             "Notificările sunt mesajele tale. Jarvis păstrează doar ultimele 20 în memorie și nu scrie nimic pe "
                             "disc sau în jurnale. Traducerea se face pe acest PC — textul notificărilor nu pleacă nicăieri. Cât "
                             "PC-ul e blocat, nu se citește nimic."),
    "text_helper": L("Выделите текст в любой программе и нажмите клавишу: у курсора появятся действия (1–5) и поле для "
                     "своей команды. Ctrl+Enter заменяет выделенное результатом; перед вставкой Jarvis проверяет, что "
                     "окно то же. Перевод делается на этом ПК. Остальные действия — облачным ИИ (текст уходит только "
                     "вашему провайдеру) или локальной моделью (никуда не уходит).",
                     "Select text in any program and press the key: the actions (1–5) and a field for your own request "
                     "appear at the cursor. Ctrl+Enter replaces the selection with the result; Jarvis checks first that "
                     "it is still the same window. Translation happens on this PC. The other actions use the cloud AI "
                     "(the text goes only to your provider) or the local model (it goes nowhere).",
                     "Selectează text în orice program și apasă tasta: lângă cursor apar acțiunile (1–5) și un câmp "
                     "pentru cererea ta. Ctrl+Enter înlocuiește selecția cu rezultatul; Jarvis verifică întâi că e "
                     "aceeași fereastră. Traducerea se face pe acest PC. Celelalte acțiuni folosesc AI-ul din cloud "
                     "(textul merge doar la furnizorul tău) sau modelul local (nu pleacă nicăieri)."),
    "converter": L("Картинки — силами Pillow, звук и видео — встроенным FFmpeg (PyAV). Ничего докачивать не нужно; "
                   "OGG сохраняется с кодеком Opus.",
                   "Images via Pillow, audio and video via the built-in FFmpeg (PyAV). Nothing to download; "
                   "OGG is saved with the Opus codec.",
                   "Imaginile prin Pillow, sunetul și video prin FFmpeg inclus (PyAV). Nu trebuie descărcat nimic; "
                   "OGG se salvează cu codecul Opus."),
}

BASIC_ACTIONS = {"notification_reader": ("test",)}
# Short names in the right-hand navigation (the card keeps its full title).
NAV_TITLES = {
    ("clipboard_history", "storage"): L("Хранение", "Storage", "Stocare"),
    ("clipboard_history", "exclude"): L("Исключения", "Exclusions", "Excepții"),
}
# Several actions in ONE basic-card row: plugin -> (title, hint, action ids).
BASIC_ACTION_ROWS = {
    "breaks": (L("Попробовать сейчас", "Try it now", "Încearcă acum"),
               L("Покажу напоминание — на счёт и статистику это не влияет.",
                 "Shows a reminder — it does not affect the count or the statistics.",
                 "Arăt un memento — nu afectează numărătoarea sau statistica."),
               ("try_eyes", "try_stretch", "try_water")),
}
# Several settings in ONE row: lead key -> other keys shown before its control.
ROW_GROUPS = {
    "visual_avatar": dict({"color": ("color_mode",)},
                          **{f"s_{state}": (f"c_{state}",) for state in ("exec", "speak", "error", "mic_off", "quiet", "prefix")}),
    "breaks": {"eyes_on": ("eyes_every",), "stretch_on": ("stretch_every",), "water_on": ("water_every",),
               "quiet_enabled": ("quiet_from", "quiet_to")},
}
# Info boxes at the end of a section card.
SECTION_NOTES = {
    ("live_captions", "sound"): L("Звук распознаётся на этом компьютере и никуда не отправляется и не сохраняется. Голос самого "
                                  "Jarvis в субтитры не попадает.",
                                  "Sound is recognised on this PC and is never sent or saved. Jarvis's own voice never "
                                  "gets into the captions.",
                                  "Sunetul e recunoscut pe acest PC și nu e trimis sau salvat nicăieri. Vocea lui Jarvis "
                                  "nu ajunge în subtitrări."),
    ("live_captions", "translate"): L("И распознавание, и перевод работают на этом ПК, без интернета — ни звук, ни текст "
                                      "никуда не уходят.",
                                      "Both recognition and translation run on this PC, offline — neither sound nor text goes "
                                      "anywhere.",
                                      "Și recunoașterea, și traducerea merg pe acest PC, fără internet — nici sunetul, nici "
                                      "textul nu pleacă nicăieri."),
    ("clipboard_history", "exclude"): L("Менеджеры паролей обычно сами помечают пароль «не для истории» — такие копирования не "
                                        "запоминаются ни из какой программы. Список ниже — на всякий случай.",
                                        "Password managers usually mark a password “not for history” themselves — such copies are "
                                        "never remembered from any program. The list below is just in case.",
                                        "Managerele de parole marchează de obicei parola „nu pentru istoric” — asemenea copieri nu "
                                        "se rețin din niciun program. Lista de mai jos e pentru siguranță."),
    ("breaks", "reminders"): L("Отошли дольше чем на 5 минут, заблокировали или усыпили компьютер — это тоже перерыв: счёт начнётся заново.",
                               "Away for more than 5 minutes, locked or put the PC to sleep — that is a break too: counting starts over.",
                               "Ai lipsit peste 5 minute, ai blocat sau ai adormit PC-ul — e tot o pauză: numărătoarea începe din nou."),
    ("breaks", "how"): L("Если включён «Островок», напоминание появится и на нём. Щелчок по строке на островке — «Сделал».",
                         "If “Status island” is on, the reminder also appears there. Clicking its line means “Done”.",
                         "Dacă „Insula de stare” e pornită, mementoul apare și acolo. Un clic pe rând înseamnă „Gata”."),
    ("breaks", "quiet"): L("Отложенное напоминание придёт одно — через полминуты после того, как закончится игра, звонок или презентация.",
                           "A delayed reminder comes once — half a minute after the game, call or presentation ends.",
                           "Mementoul amânat vine o singură dată — la jumătate de minut după ce se termină jocul, apelul sau prezentarea."),
}
BASIC_KEYS["notification_reader"] = ("read_now",)
# Settings edited by a custom card instead of a form row.
HIDDEN_SETTINGS = {"notification_reader": ("app_rules",), "live_captions": ("source",), "visual_avatar": ("position", "monitor")}
VOICE_HELP = {
    "notification_reader": L("Скажите: «что пришло» — пропущенные уведомления; «прочитай последнее сообщение»; "
                             "«не читай уведомления» / «читай уведомления»; «не беспокой» — помолчать час. "
                             "Пока уведомление звучит, его остановит слово «стоп».",
                             "Say: “what came in” — missed notifications; “read the last message”; "
                             "“don't read notifications” / “read notifications”; “do not disturb” — silence for an hour. "
                             "While a notification plays, “stop” ends it.",
                             "Spune: „ce a venit” — notificările ratate; „citește ultimul mesaj”; "
                             "„nu citi notificările” / „citește notificările”; „nu deranja” — liniște o oră. "
                             "Cât timp se citește, „stop” o oprește."),
}

BASIC_TEXT = {
    "visual_avatar": (L("Включить аватар", "Turn the avatar on", "Pornește avatarul"),
                      L("Шар поверх всех окон. Голосом: «покажи аватар» / «скрой аватар».",
                        "An orb above all windows. By voice: “show the avatar” / “hide the avatar”.",
                        "O sferă deasupra ferestrelor. Cu vocea: „arată avatarul” / „ascunde avatarul”.")),
    "live_captions": (L("Субтитры", "Captions", "Subtitrări"),
                      L("Показать или скрыть плашку с текстом поверх всех окон.", "Show or hide the text bar above all windows.",
                        "Arată sau ascunde banda cu text deasupra ferestrelor.")),
    "clipboard_history": (L("История буфера обмена", "Clipboard history", "Istoric clipboard"),
                          L("Запоминает, что вы копируете, и открывает историю у курсора по клавише.",
                            "Remembers what you copy and opens the history at the cursor with a key.",
                            "Ține minte ce copiezi și deschide istoricul lângă cursor cu o tastă.")),
    "breaks": (L("Перерывы", "Breaks", "Pauze"),
               L("Напоминает дать глазам отдых, размяться и выпить воды.", "Reminds you to rest your eyes, stretch and drink water.",
                 "Îți amintește să-ți odihnești ochii, să te întinzi și să bei apă.")),
    "notification_reader": (L("Плагин", "Plugin", "Plugin"),
                            L("Новые уведомления Windows читаются вслух.", "New Windows notifications are read aloud.",
                              "Notificările Windows noi sunt citite cu voce.")),
    "converter": (L("Конвертер", "Converter", "Convertor"),
                  L("Выделите файлы в Проводнике или на рабочем столе (или скопируйте картинку) и нажмите клавишу.",
                    "Select files in Explorer or on the desktop (or copy a picture) and press the key.",
                    "Selectează fișiere în Explorer sau pe desktop (sau copiază o imagine) și apasă tasta.")),
    "timers": (L("Таймеры и будильники голосом", "Voice timers and alarms", "Cronometre și alarme vocale"),
               L("Скажите «Джарвис, поставь таймер на 10 минут», «напомни через 20 минут выключить плиту» или «разбуди в 7:30».",
                 "Say “Jarvis, set a timer for 10 minutes”, “remind me in 20 minutes to call mom” or “wake me up at 7:30”.",
                 "Spune „Jarvis, pune un cronometru de 10 minute”, „amintește-mi în 20 de minute” sau „trezește-mă la 7:30”.")),
    "pc_control": (L("Включить PC Control", "Enable PC Control", "Activează PC Control"),
                   L("Бот принимает команды, пока Jarvis запущен.", "The bot accepts commands while Jarvis runs.",
                     "Botul primește comenzi cât timp Jarvis rulează.")),
    "smart_dictation": (L("Диктовка в любое поле", "Dictation into any field", "Dictare în orice câmp"),
                        L("Нажмите клавишу, говорите — текст появится там, где стоит курсор.",
                          "Press the key, speak — the text appears where the cursor is.",
                          "Apasă tasta, vorbește — textul apare unde este cursorul.")),
}


def sections_for(plugin: Plugin) -> tuple:
    if plugin.id in SECTIONS:
        return SECTIONS[plugin.id]
    if not plugin.settings:
        return ()
    return (Section("settings", "sliders-horizontal", L("Настройки", "Settings", "Setări"),
                    L("Параметры модуля.", "Module options.", "Opțiunile modulului."),
                    tuple(setting.key for setting in plugin.settings)),)


def how_it_works(plugin: Plugin, settings: dict, language: str) -> tuple[str, str]:
    """(key chip or "", explanation) for the right-hand "How it works" box."""
    if plugin.id == "smart_dictation":
        if settings.get("trigger") == "hotkey":
            chip = "+".join(part.capitalize() for part in str(settings.get("hotkey") or "").split("+")) or "—"
        else:
            chip = text(L("Правый Ctrl ×2", "Right Ctrl ×2", "Ctrl dreapta ×2"), language)
        if settings.get("mode", "hold") == "hold":
            body = L("Удерживайте клавишу и говорите — отпустили, и текст вставится там, где стоит курсор.",
                     "Hold the key and speak — release it and the text is inserted where the cursor is.",
                     "Ține tasta și vorbește — dai drumul și textul apare unde e cursorul.")
        else:
            seconds = settings.get("silence_pause", 2)
            body = L(f"Нажмите, говорите и нажмите ещё раз — или помолчите {seconds} с. Текст вставится там, где стоит курсор.",
                     f"Press, speak and press again — or stay silent for {seconds} s. The text is inserted at the cursor.",
                     f"Apasă, vorbește și apasă din nou — sau taci {seconds} s. Textul apare unde e cursorul.")
        return chip, text(body, language)
    if plugin.id == "pc_control":
        return "", text(plugin.description, language)
    if plugin.id == "live_captions":
        chip = "+".join(part.capitalize() for part in str(settings.get("hotkey") or "").split("+") if part)
        return chip, text(L("Субтитры — текст того, что звучит на компьютере. Покажите их кнопкой, клавишей или фразой "
                            "«покажи субтитры» («включи субтитры»); спрячьте «×» на плашке или фразой «скрой субтитры». "
                            "Ручка слева — перетащить.",
                            "Captions are the text of what plays on the PC. Show them with the button, the key or by saying "
                            "“show captions”; hide them with “×” on the bar or “hide captions”. Drag the handle on the left.",
                            "Subtitrările sunt textul a ce se aude pe PC. Arată-le cu butonul, tasta sau spunând „arată "
                            "subtitrările”; ascunde-le cu „×” pe bandă sau „ascunde subtitrările”. Trage de mânerul din stânga."),
                          language)
    if plugin.id == "clipboard_history":
        chip = "+".join(part.capitalize() for part in str(settings.get("hotkey") or "").split("+") if part)
        key = chip or text(L("клавиша", "the key", "tasta"), language)
        return chip, text(L(f"Копируйте как обычно. {key} — у курсора история: Enter вставит выбранное, Shift+Enter — "
                            "без форматирования. Голосом: «вставь предыдущее».",
                            f"Copy as usual. {key} — the history at the cursor: Enter pastes the chosen item, Shift+Enter — "
                            "without formatting. By voice: “paste the previous one”.",
                            f"Copiază ca de obicei. {key} — istoricul lângă cursor: Enter lipește elementul ales, "
                            "Shift+Enter — fără formatare. Cu vocea: „lipește precedentul”."), language)
    if plugin.id == "breaks":
        return "", text(L("Считается только настоящая работа: пока вы что-то нажимаете и двигаете мышью. Пора — в углу экрана "
                          "появится плашка: «Сделал», «Отложить» или «Пропустить». В играх и звонках напоминания ждут.",
                          "Only real work counts: while you type and move the mouse. When it is time, a card appears in the "
                          "screen corner: “Done”, “Later” or “Skip”. During games and calls reminders wait.",
                          "Se numără doar lucrul real: cât apeși taste și miști mouse-ul. Când e timpul, apare un card în colț: "
                          "„Gata”, „Mai târziu” sau „Sar”. În jocuri și apeluri mementourile așteaptă."), language)
    if plugin.id == "notification_reader":
        return "", text(L("Новые уведомления Windows Jarvis читает вслух. Текст хранится только в памяти и никуда не уходит. "
                          "Спросите «что пришло» — прочитает пропущенное.",
                          "Jarvis reads new Windows notifications aloud. The text stays only in memory and goes nowhere. "
                          "Ask “what came in” to hear missed ones.",
                          "Jarvis citește cu voce notificările Windows noi. Textul rămâne doar în memorie. "
                          "Întreabă „ce a venit” ca să auzi ce ai ratat."), language)
    if plugin.id == "converter":
        chip = "+".join(part.capitalize() for part in str(settings.get("hotkey") or "").split("+"))
        return chip, text(L("Выделите файлы в Проводнике или на рабочем столе (или скопируйте картинку) и нажмите клавишу — "
                            "у курсора появится круг. Выберите действие мышью, стрелками или цифрой. Результат ляжет рядом "
                            "с файлом, исходник не меняется.",
                            "Select files in Explorer or on the desktop (or copy a picture) and press the key — a circle "
                            "appears at the cursor. Pick an action with the mouse, arrows or a digit. The result is saved "
                            "next to the file; the original is untouched.",
                            "Selectează fișiere în Explorer sau pe desktop (sau copiază o imagine) și apasă tasta — lângă "
                            "cursor apare un cerc. Alege acțiunea cu mouse-ul, săgețile sau o cifră. Rezultatul apare lângă "
                            "fișier, originalul rămâne neschimbat."), language)
    keys = [setting for setting in plugin.settings if setting.kind == "hotkey" and settings.get(setting.key)]
    chip = "+".join(part.capitalize() for part in settings[keys[0].key].split("+")) if keys else ""
    return chip, text(plugin.description, language)
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
    ("telegram", "send", L("Telegram-бот", "Telegram bot", "Bot Telegram"), ("pc_control",), "owner_id"),
    ("home_assistant", "house", L("Home Assistant", "Home Assistant", "Home Assistant"), ("smart_home",), "url"),
    ("obs", "radio", L("OBS WebSocket", "OBS WebSocket", "OBS WebSocket"), ("streamer_helper",), "obs_host"),
    ("twitch", "message-square", L("Twitch", "Twitch", "Twitch"), ("streamer_helper",), "twitch_channel"),
)


def ui(key: str, language: str, **values) -> str:
    template = text(UI[key], language)
    return template.format(**values) if values else template


# --- state -----------------------------------------------------------------

def stored_settings(plugin: Plugin):
    """Settings kept in config.json; "secret" ones live in DPAPI storage."""
    return [setting for setting in plugin.settings if setting.kind != "secret"]


def default_settings(plugin: Plugin) -> dict:
    return {setting.key: copy.deepcopy(setting.default) for setting in stored_settings(plugin)}


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
    if kind == "secret":
        value = str(value or "").strip()
        if len(value) > setting.max_length or any(ord(char) < 33 for char in value):
            raise ValueError("invalid secret")
        return value
    if kind == "color":
        value = str(value or "").strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError("colour expected")
        return value.lower()
    if kind == "tags":
        if not isinstance(value, str):
            raise ValueError("text expected")
        names = []
        for name in value.replace(",", "\n").splitlines():
            name = " ".join(name.split())[:60]
            if name and "\x00" not in name and name.casefold() not in {item.casefold() for item in names}:
                names.append(name)
        value = "\n".join(names)
        if len(value) > setting.max_length:
            raise ValueError("too long")
        return value
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
        if setting.pattern and value and not re.fullmatch(setting.pattern, value):
            raise ValueError({"ru": "неверный формат", "en": "invalid format", "ro": "format invalid"}["ru"])
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
            for setting in stored_settings(plugin):
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
