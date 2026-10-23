"""Visible UI strings for Russian, English and Romanian.

Speech recognition / voice commands remain separately configured. This module
never translates user input, saved command titles, messages or API values.
"""
from __future__ import annotations

import re

from PySide6.QtWidgets import (
    QAbstractButton, QComboBox, QGroupBox, QLabel, QLineEdit,
    QSpinBox, QDoubleSpinBox, QTextEdit, QTreeWidget, QWidget,
)

LANGUAGES = (("Русский", "ru"), ("English", "en"), ("Română", "ro"))
VALID_LANGUAGES = frozenset(("ru", "en", "ro"))


def normalize_language(value):
    return value if value in VALID_LANGUAGES else "ru"


_DATA = r"""Главная|||Home|||Acasă
Команды|||Commands|||Comenzi
Дополнения|||Tools|||Instrumente
Настройки|||Settings|||Setări
Свернуть|||Collapse|||Restrânge
Локальный режим|||Local mode|||Mod local
Включить или выключить микрофон|||Turn microphone on or off|||Activează sau dezactivează microfonul
История команд|||Command history|||Istoricul comenzilor
Здесь появятся распознанные команды и ответы Jarvis.|||Recognized commands and Jarvis replies will appear here.|||Comenzile recunoscute și răspunsurile Jarvis vor apărea aici.
Панель управления|||Control panel|||Panou de control
Режим префикса|||Wake-word mode|||Mod cuvânt de activare
Тихий режим|||Quiet mode|||Mod silențios
Анимация аватара|||Avatar animation|||Animația avatarului
Окно поверх|||Always on top|||Fereastră deasupra celorlalte
Громкость|||Volume|||Volum
Посмотреть кнопки на экране|||View on-screen buttons|||Vezi butoanele de pe ecran
Пересказать выделенный текст|||Summarize selected text|||Rezumă textul selectat
Ваши команды|||Your commands|||Comenzile tale
Готовые команды выполняются мгновенно. Двойной щелчок запускает выбранную команду.|||Ready-made commands run instantly. Double-click to run a selected command.|||Comenzile predefinite se execută imediat. Dublu clic pentru a executa comanda selectată.
Название команды|||Command name|||Numele comenzii
Состояние|||Status|||Stare
Поиск команд|||Search commands|||Caută comenzi
Новая команда|||New command|||Comandă nouă
Создать голосом|||Create by voice|||Creează prin voce
Изменить выбранную|||Edit selected|||Editează selecția
Выключить команду|||Disable command|||Dezactivează comanda
Включить команду|||Enable command|||Activează comanda
Удалить выбранную|||Delete selected|||Șterge selecția
Выполнить сейчас|||Run now|||Execută acum
Изменения сохраняются между обновлениями.|||Changes are kept across updates.|||Modificările se păstrează după actualizări.
Приложения|||Applications|||Aplicații
Игры Steam|||Steam games|||Jocuri Steam
Файлы|||Files|||Fișiere
Мои команды|||My commands|||Comenzile mele
Выученные команды|||Learned commands|||Comenzi învățate
Удалить команду?|||Delete command?|||Ștergi comanda?
Ошибка|||Error|||Eroare
Инструменты, доступные локально на этом компьютере.|||Tools available locally on this computer.|||Instrumente disponibile local pe acest calculator.
Снимок экрана|||Screenshot|||Captură de ecran
Сохранить снимок текущего экрана на этом компьютере.|||Save a screenshot of this computer.|||Salvează o captură a ecranului acestui calculator.
Распознавание текста (OCR)|||Text recognition (OCR)|||Recunoaștere text (OCR)
Сделать снимок и извлечь из него видимый текст.|||Capture the screen and extract visible text.|||Capturează ecranul și extrage textul vizibil.
Выбрать локальную AI-модель|||Choose local AI model|||Alege modelul AI local
Указать путь к файлу модели .gguf на компьютере.|||Select the .gguf model file on this computer.|||Alege fișierul modelului .gguf de pe calculator.
Запустить|||Run|||Execută
Общение с локальным помощником. Ваши модели и настройки остаются на компьютере.|||Chat with your local assistant. Models and settings stay on your computer.|||Discută cu asistentul local. Modelele și setările rămân pe calculator.
Jarvis появится здесь после первого сообщения.|||Jarvis will appear here after the first message.|||Jarvis va apărea aici după primul mesaj.
Напишите сообщение или команду…|||Type a message or command…|||Scrie un mesaj sau o comandă…
Отправить|||Send|||Trimite
Поиск настроек|||Search settings|||Caută setări
РАЗДЕЛЫ|||SECTIONS|||SECȚIUNI
Сбросить поиск|||Clear search|||Șterge căutarea
Сохранить настройки|||Save settings|||Salvează setările
Настройки сохраняются на этом компьютере. Изменения применяются после сохранения.|||Settings are stored on this computer. Changes take effect after saving.|||Setările sunt salvate pe acest calculator. Modificările se aplică după salvare.
Голосовой ввод|||Voice input|||Intrare vocală
Микрофон, распознавание и обращение|||Microphone, speech recognition and wake word|||Microfon, recunoaștere vocală și cuvânt de activare
Озвучка|||Voice output|||Redare vocală
Голос ассистента и громкость|||Assistant voice and volume|||Vocea asistentului și volumul
Выполнение команд|||Command execution|||Executarea comenzilor
Подтверждения и управление|||Confirmations and controls|||Confirmări și control
Интерфейс|||Interface|||Interfață
Цвета, прозрачность и оформление|||Colors, transparency and appearance|||Culori, transparență și aspect
ИИ-провайдер|||AI provider|||Furnizor AI
Локальная нейросеть и модель|||Local AI and model|||AI local și model
Синтез речи|||Speech synthesis|||Sinteză vocală
Движок речи и скорость|||Speech engine and speed|||Motor vocal și viteză
Система|||System|||Sistem
Автозапуск и сворачивание|||Autostart and minimizing|||Pornire automată și minimizare
Как Jarvis слышит вас: распознавание речи и микрофон.|||How Jarvis hears you: speech recognition and microphone.|||Cum te aude Jarvis: recunoaștere vocală și microfon.
Распознавание речи|||Speech recognition|||Recunoaștere vocală
Работает локально, без облака.|||Runs locally, without cloud access.|||Funcționează local, fără servicii cloud.
Whisper (локально)|||Whisper (local)|||Whisper (local)
Повышенная точность|||Recognition accuracy|||Precizia recunoașterii
Более точное распознавание может работать медленнее.|||Higher accuracy may run more slowly.|||Precizia mai mare poate funcționa mai lent.
Быстрее|||Faster|||Mai rapid
Сбалансированно|||Balanced|||Echilibrat
Точнее|||More accurate|||Mai precis
Язык распознавания|||Recognition language|||Limba recunoașterii
Также задаёт язык ответов ассистента.|||Also controls the language of assistant replies.|||Stabilește și limba răspunsurilor asistentului.
Авто|||Auto|||Automat
Русский|||Russian|||Rusă
По умолчанию|||Default|||Implicit
Микрофон|||Microphone|||Microfon
Выберите устройство входа.|||Select input device.|||Alege dispozitivul de intrare.
Автовключение микрофона|||Automatically enable microphone|||Activează automat microfonul
Начать прослушивание после запуска приложения.|||Start listening when the app opens.|||Pornește ascultarea la deschiderea aplicației.
Обращение (префикс)|||Wake word (prefix)|||Cuvânt de activare (prefix)
Реагировать только после имени Jarvis.|||Respond only after the name Jarvis.|||Răspunde doar după numele Jarvis.
Варианты обращения|||Wake-word variants|||Variante de activare
Несколько вариантов через запятую.|||Separate variants with commas.|||Separă variantele prin virgule.
Голос, которым звучат ответы Jarvis.|||Voice used for Jarvis replies.|||Vocea folosită pentru răspunsurile Jarvis.
Голосовой ответ|||Spoken replies|||Răspunsuri vocale
Озвучивать текст ответа.|||Read replies aloud.|||Citește răspunsurile cu voce tare.
Голос ассистента|||Assistant voice|||Vocea asistentului
Список локально установленных моделей Piper.|||Locally installed Piper voices.|||Vocile Piper instalate local.
Дмитрий — русский (по умолчанию)|||Dmitri — Russian (default)|||Dmitri — rusă (implicit)
0–100%, применяется к озвучке.|||0–100%, applies to spoken output.|||0–100%, se aplică răspunsurilor vocale.
Прослушать пример|||Preview voice|||Ascultă exemplul
Обычные голосовые действия выполняются сразу. Сон, выключение, скрипты и опасные действия требуют разрешения.|||Ordinary voice actions run immediately. Sleep, shutdown, scripts and risky actions require approval.|||Comenzile vocale obișnuite se execută imediat. Repausul, oprirea, scripturile și acțiunile riscante necesită confirmare.
Подтверждать также обычные действия|||Confirm ordinary actions too|||Confirmă și acțiunile obișnuite
Необязательная настройка: спрашивать разрешение даже для открытия приложений, сайтов и документов. Опасные действия всегда требуют подтверждения.|||Optional: request permission even to open apps, websites and documents. Risky actions always require confirmation.|||Opțional: solicită permisiune și pentru deschiderea aplicațiilor, site-urilor și documentelor. Acțiunile riscante necesită întotdeauna confirmare.
Слова «да»|||Yes words|||Cuvinte pentru „da”
Варианты голосового подтверждения через запятую.|||Voice confirmation variants separated by commas.|||Variante de confirmare vocală separate prin virgule.
Слова «нет»|||No words|||Cuvinte pentru „nu”
Варианты голосового отказа через запятую.|||Voice rejection variants separated by commas.|||Variante de refuz vocal separate prin virgule.
Автоотмена подтверждения|||Confirmation timeout|||Expirarea confirmării
Отмена, если нет ответа в течение заданного времени.|||Cancel if there is no answer within the selected time.|||Anulează dacă nu se răspunde în timpul stabilit.
Связка команд|||Command connectors|||Legături între comenzi
Разделите две простые команды одним из этих выражений.|||Separate two simple commands with one of these phrases.|||Separă două comenzi simple cu una dintre aceste expresii.
Вид окна и оформление.|||Window appearance and styling.|||Aspectul și stilul ferestrei.
Оформление|||Appearance|||Aspect
Тёмное или светлое окно.|||Dark or light window.|||Fereastră întunecată sau luminoasă.
Тёмное|||Dark|||Întunecat
Светлое|||Light|||Luminos
Цвет темы|||Theme color|||Culoarea temei
Акцент кнопок и навигации.|||Accent color for buttons and navigation.|||Culoare de accent pentru butoane și navigare.
Синий|||Blue|||Albastru
Фиолетовый|||Purple|||Violet
Зелёный|||Green|||Verde
Розовый|||Pink|||Roz
Прозрачность|||Transparency|||Transparență
0–35% окна приложения.|||0–35% window transparency.|||0–35% transparența ferestrei.
Анимации|||Animations|||Animații
Отображение анимированного аватара.|||Show animated avatar.|||Afișează avatarul animat.
Поверх остальных окон|||Always on top|||Deasupra celorlalte ferestre
Оставлять Jarvis видимым поверх приложений.|||Keep Jarvis above other applications.|||Păstrează Jarvis deasupra altor aplicații.
Язык интерфейса|||Interface language|||Limba interfeței
Меняет только интерфейс. Язык распознавания и озвучивания настраивается отдельно.|||Changes the interface only. Speech recognition and voice language are configured separately.|||Modifică doar interfața. Recunoașterea și limba vocii se configurează separat.
Онлайн-ИИ разбирает сложные команды, локальный агент проверяет и выполняет действия.|||Online AI interprets complex commands; the local agent validates and executes actions.|||AI online interpretează comenzile complexe; agentul local verifică și execută acțiunile.
Облачный помощник|||Cloud assistant|||Asistent cloud
Работает только при подключении к интернету и с вашим ключом выбранного сервиса.|||Requires internet access and your selected provider's API key.|||Necesită internet și cheia API a furnizorului ales.
Поставщик AI API|||AI API provider|||Furnizor API AI
OrcaRouter и OpenRouter — разные сервисы. Ключ должен принадлежать выбранному провайдеру.|||OrcaRouter and OpenRouter are different services. Use the key from the selected provider.|||OrcaRouter și OpenRouter sunt servicii diferite. Folosește cheia furnizorului ales.
Введите ID модели|||Enter model ID|||Introdu ID-ul modelului
Модель API|||API model|||Model API
У разных сервисов разные названия моделей. При смене сервиса будет подставлен пример.|||Model names differ between services. An example appears when changing providers.|||Numele modelelor diferă între servicii. La schimbarea furnizorului apare un exemplu.
Gemini: «Antigravity» — агент AI Studio, а не модель chat API. Нажмите «Проверить ключ»: Jarvis подберёт доступную модель из вашего проекта.|||Gemini: “Antigravity” is an AI Studio agent, not a chat API model. Use “Test key” to select an available model.|||Gemini: „Antigravity” este un agent AI Studio, nu un model chat API. Folosește „Verifică cheia” pentru a selecta un model disponibil.
Другой HTTPS endpoint|||Custom HTTPS endpoint|||Endpoint HTTPS personalizat
Только для пункта «Другой API». Ключ будет отправлен указанному вами серверу.|||Only for “Custom API”. Your key will be sent to the chosen server.|||Doar pentru „API personalizat”. Cheia va fi trimisă serverului ales.
Ключ скрыт. Не делитесь им с другими.|||Key is hidden. Do not share it.|||Cheia este ascunsă. Nu o distribui.
Проверить ключ|||Test key|||Verifică cheia
Проверить введённый или сохранённый ключ. Тест использует небольшую часть квоты API.|||Test the new or saved key. This uses a small part of the API quota.|||Verifică cheia nouă sau salvată. Testul consumă o parte mică din cota API.
API-ключ выбранного сервиса|||Selected provider API key|||Cheia API a furnizorului ales
Проверка доступна до сохранения ключа; тестовый запрос может расходовать квоту.|||You can test before saving the key; a request may consume quota.|||Poți verifica înainte de salvare; cererea poate consuma din cotă.
Время ответа облачного ИИ|||Cloud AI timeout|||Timp de răspuns AI cloud
Gemini может думать от 35 до 120 секунд. По умолчанию 60 сек. При HTTP 429 лимит аккаунта не исчезнет от увеличения времени.|||Gemini may need 35–120 seconds. Default is 60. Increasing it does not fix HTTP 429 limits.|||Gemini poate avea nevoie de 35–120 de secunde. Implicit 60. Mărirea timpului nu rezolvă limitările HTTP 429.
Получить ключ|||Get API key|||Obține cheia API
Удалить ключ|||Delete key|||Șterge cheia
У каждого поставщика собственный ключ и лимиты. Некоторые сервисы предоставляют бесплатные квоты, но это зависит от аккаунта. При включении онлайн-ИИ команда и до четырёх предыдущих реплик отправляются выбранному сервису. Никогда не публикуйте ключи в чате или на GitHub.|||Each provider has its own keys and limits. Free quotas depend on the account. With cloud AI enabled, your request and up to four earlier messages go to the provider. Never publish keys in chat or GitHub.|||Fiecare furnizor are chei și limite proprii. Cotele gratuite depind de cont. Cu AI online activat, cererea și până la patru mesaje anterioare sunt trimise furnizorului. Nu publica niciodată cheile în chat sau pe GitHub.
Резервный локальный ИИ|||Backup local AI|||AI local de rezervă
Если облачный API недоступен, запускать тяжёлую GGUF-модель. Выключите для максимальной скорости: быстрые команды работают и без неё.|||If the cloud API fails, run the heavier local GGUF model. Disable for maximum speed; quick commands still work.|||Dacă API-ul cloud nu funcționează, pornește modelul local GGUF mai greu. Dezactivează pentru viteză maximă; comenzile rapide funcționează oricum.
Модель не выбрана|||No model selected|||Niciun model selectat
Локальная модель ИИ|||Local AI model|||Model AI local
Продолжает работать без интернета, даже если онлайн API недоступен.|||Works offline even if the cloud API is unavailable.|||Funcționează fără internet chiar dacă API-ul cloud nu este disponibil.
Выбрать локальную модель .gguf|||Choose local .gguf model|||Alege modelul local .gguf
Похоже, это ключ OrcaRouter. Выберите «OrcaRouter (orcarouter.ai)» в списке провайдеров, иначе проверка может вернуть 401.|||This seems to be an OrcaRouter key. Select OrcaRouter to avoid a 401 error.|||Aceasta pare o cheie OrcaRouter. Selectează OrcaRouter pentru a evita eroarea 401.
Новый ключ введён. Нажмите «Проверить ключ», затем «Сохранить настройки».|||New key entered. Choose “Test key”, then “Save settings”.|||Cheie nouă introdusă. Apasă „Verifică cheia”, apoi „Salvează setările”.
Проверка…|||Testing…|||Verificare…
Проверка ключа и выбранной модели через API…|||Testing API key and selected model…|||Verific cheia API și modelul ales…
Локальный Piper или голос Windows (если установлен нужный язык).|||Local Piper or Windows voice (if that language is installed).|||Piper local sau voce Windows (dacă limba este instalată).
Piper — нейросеть (локально)|||Piper — neural (local)|||Piper — neural (local)
Windows SAPI (локально)|||Windows SAPI (local)|||Windows SAPI (local)
Провайдер синтеза|||Speech engine|||Motor de sinteză
Piper загружает русскую модель Дмитрий при первом запуске.|||Piper downloads the Russian Dmitri model on first use.|||Piper descarcă modelul rus Dmitri la prima utilizare.
Скорость речи|||Speech speed|||Viteza vorbirii
70–140% обычной скорости.|||70–140% of normal speed.|||70–140% din viteza normală.
Голоса Luxify / Fish Audio и облачные модели требуют отдельного доступа. В этой версии используются только установленные локальные голоса.|||Luxify / Fish Audio and cloud voices require separate access. This version uses installed local voices only.|||Vocile Luxify / Fish Audio și cele cloud necesită acces separat. Această versiune folosește doar vocile locale instalate.
Запуск вместе с Windows и работа в фоновом режиме.|||Start with Windows and run in background.|||Pornește cu Windows și rulează în fundal.
Автозапуск программы|||Start with Windows|||Pornește odată cu Windows
Запускать Jarvis при входе в Windows.|||Start Jarvis on Windows sign-in.|||Pornește Jarvis la autentificarea în Windows.
Сворачивать в трей при закрытии|||Minimize to tray on close|||Minimizează în zona de notificare la închidere
Не завершать Jarvis при закрытии главного окна.|||Keep Jarvis running when closing the main window.|||Păstrează Jarvis activ când închizi fereastra principală.
Город для прогноза погоды|||Forecast city|||Oraș pentru prognoza meteo
Open-Meteo работает без ключа Gemini. Этот город по умолчанию.|||Open-Meteo works without a Gemini key. This is the default city.|||Open-Meteo funcționează fără cheie Gemini. Acesta este orașul implicit.
Встроенный Tesseract OCR|||Built-in Tesseract OCR|||Tesseract OCR integrat
Автоматически: встроенный Tesseract-OCR (путь необязателен)|||Automatic: built-in Tesseract OCR (optional path)|||Automat: Tesseract OCR integrat (cale opțională)
Обзор|||Browse|||Răsfoiește
Устанавливается автоматически с Jarvis и Update.bat; русский и английский пакеты загружаются сами. Выбор внешнего tesseract.exe необязателен.|||Installed automatically with Jarvis and Update.bat; Russian and English OCR data download automatically. External tesseract.exe is optional.|||Instalat automat cu Jarvis și Update.bat; datele OCR rusă și engleză se descarcă automat. Un tesseract.exe extern este opțional.
Настройки применяются и сохраняются в config.json. Для смены микрофона перезапускается распознавание.|||Settings are saved in config.json. Speech recognition restarts after changing the microphone.|||Setările sunt salvate în config.json. Recunoașterea vocală repornește când schimbi microfonul.
Готово:|||Ready:|||Gata:
Недоступно:|||Unavailable:|||Indisponibil:
Новая команда|||New command|||Comandă nouă
Изменить команду|||Edit command|||Editează comanda
Назовите команду, добавьте фразы и выберите действия. Jarvis выполнит их по порядку, без ожидания ИИ.|||Name the command, add phrases and choose actions. Jarvis runs them in order without waiting for AI.|||Dă un nume comenzii, adaugă expresii și alege acțiunile. Jarvis le execută în ordine, fără să aștepte AI.
Например: Открыть мой рабочий набор|||Example: Open my work setup|||Exemplu: Deschide mediul meu de lucru
Фразы  (несколько вариантов через запятую)|||Phrases (comma-separated alternatives)|||Expresii (variante separate prin virgule)
открой мой набор, включи рабочие программы|||open my tools, start my work apps|||deschide instrumentele mele, pornește aplicațiile de lucru
Действия|||Actions|||Acțiuni
Добавить действие|||Add action|||Adaugă acțiune
Изменить|||Edit|||Editează
Выше|||Move up|||Mai sus
Ниже|||Move down|||Mai jos
Удалить|||Delete|||Șterge
Доступно до 8 действий в одной команде.|||Up to 8 actions per command.|||Până la 8 acțiuni per comandă.
Создание файлов, взаимодействие с клавиатурой и мышью требуют подтверждения. CMD и PowerShell не исполняются автоматически.|||File creation and keyboard/mouse interactions require confirmation. CMD and PowerShell are not run automatically.|||Crearea fișierelor și interacțiunile cu tastatura/mouse-ul necesită confirmare. CMD și PowerShell nu rulează automat.
Отмена|||Cancel|||Anulează
Сохранить команду|||Save command|||Salvează comanda
Старая сохранённая команда Steam: действие сохранено без изменений|||Legacy Steam command: action unchanged|||Comandă Steam veche: acțiune nemodificată
Настроить действие|||Configure action|||Configurează acțiunea
Приложение|||Application|||Aplicație
Игра Steam|||Steam game|||Joc Steam
Клавиша|||Key|||Tastă
Сочетание|||Shortcut|||Combinație de taste
Рабочий стол|||Desktop|||Desktop
Документы|||Documents|||Documente
Загрузки|||Downloads|||Descărcări
Папка|||Folder|||Dosar
Название|||Name|||Nume
Значение|||Value|||Valoare
Аудиофайл|||Audio file|||Fișier audio
Координаты X,Y|||Coordinates X,Y|||Coordonate X,Y
Действие не требует параметров.|||This action needs no parameters.|||Această acțiune nu necesită parametri.
Добавить|||Add|||Adaugă
Применить|||Apply|||Aplică
Что сделает команда. Двойной щелчок — добавить сразу.|||Choose what the command does. Double-click to add immediately.|||Alege ce face comanda. Dublu clic pentru adăugare imediată.
Пустое действие|||Empty action|||Acțiune goală
Действия не найдены. Попробуйте другой запрос.|||No actions found. Try a different search.|||Nu s-au găsit acțiuni. Încearcă altă căutare.
Выберите действие, чтобы изменить или переместить.|||Select an action to edit or move.|||Selectează o acțiune pentru editare sau mutare.
Открыть приложение|||Open application|||Deschide aplicația
Запустить игру Steam|||Launch Steam game|||Pornește jocul Steam
Создать файл|||Create file|||Creează fișier
Создать папку|||Create folder|||Creează dosar
Показать список файлов|||List files|||Listează fișierele
Сказать текущее время|||Say current time|||Spune ora curentă
Свернуть все окна|||Minimize all windows|||Minimizează toate ferestrele
Выберите файл или программу…|||Select a file or program…|||Alege un fișier sau program…
Ошибка команды|||Command error|||Eroare de comandă
Некорректное действие|||Invalid action|||Acțiune invalidă
Ошибка сохранения ключа API.|||Could not save API key.|||Nu s-a putut salva cheia API.
Настройки сохранены.|||Settings saved.|||Setări salvate.
Облачный ИИ выключен — локальный режим|||Cloud AI disabled — local mode|||AI cloud dezactivat — mod local
Онлайн-ИИ включён, но ключ выбранного провайдера не сохранён|||Online AI enabled, but the selected provider key is missing|||AI online activat, dar cheia furnizorului ales lipsește
Создание голосовой команды|||Creating voice command|||Creez comanda vocală
"""

# Every entry is a Russian source string and an English/Romanian translation.
TRANSLATIONS = {}
for _line in _DATA.splitlines():
    if not _line.strip():
        continue
    _ru, _en, _ro = _line.split("|||", 2)
    TRANSLATIONS[" ".join(_ru.split())] = (_en, _ro)

_language = "ru"


def get_ui_language():
    return _language


def set_ui_language(language):
    global _language
    _language = normalize_language(language)


def tr(source, language=None):
    """Translate only known interface phrases; preserve arbitrary user data."""
    if not isinstance(source, str):
        return source
    code = normalize_language(language if language is not None else _language)
    if code == "ru":
        return source
    prefix = re.match(r"^(\s*[◉◌●▣▤⌂☷▦▣▶＋↑↓✓✕]*\s*)", source)
    start = prefix.group(0) if prefix else ""
    # The metadata prefix is formatting; the rest is a source-language phrase.
    phrase = source[len(start):]
    normalized = " ".join(phrase.split())
    values = TRANSLATIONS.get(normalized)
    if values is None:
        return source
    return start + values[0 if code == "en" else 1]


def _translate_property(obj, attribute, getter, setter, language):
    old_original = obj.property("_i18n_original_" + attribute)
    previous = obj.property("_i18n_display_" + attribute)
    current = getter()
    if not isinstance(current, str) or not current:
        return
    # Handle dynamic label changes after the last translation without
    # mistaking translated strings for new Russian source text.
    source = old_original if old_original is not None and current == previous else current
    obj.setProperty("_i18n_original_" + attribute, source)
    output = tr(source, language)
    if current != output:
        setter(output)
    obj.setProperty("_i18n_display_" + attribute, output)


def translate_widgets(root: QWidget, language=None):
    """Reapply translated UI labels without reconstructing live widgets.

    This preserves values, signals, microphone workers and unsaved settings.
    """
    language = normalize_language(language or _language)
    for widget in [root] + root.findChildren(QWidget):
        if isinstance(widget, QAbstractButton):
            _translate_property(widget, "text", widget.text, widget.setText, language)
        elif isinstance(widget, QLabel):
            _translate_property(widget, "text", widget.text, widget.setText, language)
        elif isinstance(widget, QGroupBox):
            _translate_property(widget, "title", widget.title, widget.setTitle, language)
        if isinstance(widget, (QLineEdit, QTextEdit)):
            _translate_property(widget, "placeholder", widget.placeholderText, widget.setPlaceholderText, language)
        if isinstance(widget, QComboBox):
            for index in range(widget.count()):
                source = widget.itemData(index, 0x0100 + 18)  # Qt.UserRole + 18
                if not isinstance(source, str):
                    source = widget.itemText(index)
                    widget.setItemData(index, source, 0x0100 + 18)
                translated = tr(source, language)
                if translated != widget.itemText(index):
                    widget.setItemText(index, translated)
        if isinstance(widget, QTreeWidget):
            for column in range(widget.columnCount()):
                header = widget.headerItem()
                if header is None:
                    break
                source = header.data(column, 0x0100 + 18)
                if not isinstance(source, str):
                    source = header.text(column)
                    header.setData(column, 0x0100 + 18, source)
                header.setText(column, tr(source, language))
        if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            # Preserve digits, only translate the unit suffix.
            suffix = widget.suffix()
            if suffix.strip() == "сек":
                widget.setSuffix(" sec" if language == "en" else (" s" if language == "ro" else " сек"))
        _translate_property(widget, "tooltip", widget.toolTip, widget.setToolTip, language)
        # Only local dialogs have translated window titles, not dynamic content.
        if widget.isWindow():
            _translate_property(widget, "windowtitle", widget.windowTitle, widget.setWindowTitle, language)
