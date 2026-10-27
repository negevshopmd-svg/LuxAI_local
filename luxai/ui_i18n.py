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


_DATA = r"""
Последовательность клавиш|||Key sequence|||Secvență de taste
По очереди нажимает 2–24 буквы или цифры, например Q,W,E,R,D|||Presses 2–24 letters or digits in order, for example Q,W,E,R,D|||Apasă în ordine 2–24 de litere sau cifre, de exemplu Q,W,E,R,D
Q,W,E,R,D — от 2 до 24 клавиш|||Q,W,E,R,D — 2 to 24 keys|||Q,W,E,R,D — de la 2 la 24 de taste
Открыть Jarvis|||Open Jarvis|||Deschide Jarvis
Выход|||Exit|||Ieșire
Главная|||Home|||Acasă
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
Устройства обновлены.|||Devices refreshed.|||Dispozitive actualizate.
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
Все действия|||All actions|||Toate acțiunile
Запуск|||Launch|||Pornire
Клавиши|||Keyboard|||Tastatură
Мышь|||Mouse|||Mouse
Программа|||Program|||Program
Звук|||Sound|||Sunet
Браузер|||Browser|||Navigator
Запустить программу|||Launch application|||Pornește aplicația
Открывает выбранное установленное приложение|||Opens the selected installed application|||Deschide aplicația instalată selectată
Запустить файл или программу|||Launch file or application|||Pornește fișierul sau aplicația
Открывает файл, вручную выбранный на вашем компьютере|||Opens the file selected from your computer|||Deschide fișierul ales de pe calculator
Открыть файл по имени|||Open a file by name|||Deschide fișier după nume
Ищет на рабочем столе, в Документах или Загрузках и открывает через Windows|||Looks on Desktop, Documents and Downloads and opens with Windows|||Caută pe Desktop, în Documente și Descărcări și deschide cu Windows
Открыть сайт|||Open website|||Deschide site
Открывает указанный HTTPS-сайт в браузере|||Opens the specified HTTPS website in a browser|||Deschide site-ul HTTPS specificat în navigator
Выполнить команду CMD|||Run CMD command|||Execută comandă CMD
Только сохранённый пользователем скрипт; подтверждение при каждом запуске|||Only manually saved scripts; confirmation each time|||Doar scripturi salvate manual; confirmare la fiecare execuție
Выполнить команду PowerShell|||Run PowerShell command|||Execută comandă PowerShell
Только сохранённая вручную команда; обязательное подтверждение|||Manually saved command only; confirmation required|||Doar comenzi salvate manual; confirmare obligatorie
Ввести текст|||Type text|||Introdu text
Печатает указанный текст в активном окне|||Types the specified text in the active window|||Tastează textul specificat în fereastra activă
Нажать клавишу или сочетание|||Press key or shortcut|||Apasă tastă sau combinație
Выбираемое сочетание из безопасного списка|||Choose a shortcut from the allowed list|||Alege combinația din lista permisă
Нажать одну клавишу|||Press one key|||Apasă o tastă
Буквы, цифры и стандартные клавиши|||Letters, digits and standard keys|||Litere, cifre și taste standard
Нажать Enter|||Press Enter|||Apasă Enter
Отправляет Enter в активное окно|||Sends Enter to the active window|||Trimite Enter în fereastra activă
Сохранить (Ctrl+S)|||Save (Ctrl+S)|||Salvează (Ctrl+S)
Отправляет Ctrl+S в активное окно|||Sends Ctrl+S to the active window|||Trimite Ctrl+S în fereastra activă
Двойной клик|||Double-click|||Dublu clic
Двойной щелчок левой кнопкой|||Double-clicks the left mouse button|||Dublu clic cu butonul stâng
Правый клик|||Right-click|||Clic dreapta
Щелчок правой кнопкой мыши|||Click right mouse button|||Clic cu butonul drept
Левый клик|||Left-click|||Clic stânga
Нажимает левую кнопку мыши|||Clicks the left mouse button|||Apasă butonul stâng al mouse-ului
Клик колесом / прокрутка|||Scroll wheel|||Rotița de derulare
Прокрутка колеса мыши|||Scrolls the mouse wheel|||Derulează cu rotița mouse-ului
Переместить курсор|||Move cursor|||Mută cursorul
Перемещает курсор к координатам экрана|||Moves cursor to screen coordinates|||Mută cursorul la coordonatele ecranului
Зажать левую кнопку|||Hold left button|||Ține apăsat butonul stâng
Удерживает кнопку 1–5 секунд и отпускает автоматически|||Holds button for 1–5 seconds then releases|||Ține apăsat 1–5 secunde și eliberează automat
Не выполняет никаких действий — разделитель шагов|||Does nothing — separator between steps|||Nu execută nimic — separator între pași
Пауза в секундах|||Wait seconds|||Pauză în secunde
Ждёт 1–30 секунд до следующего действия|||Waits 1–30 seconds before next action|||Așteaptă 1–30 de secunde înainte de acțiunea următoare
Пауза в минутах|||Wait minutes|||Pauză în minute
Ждёт 1–10 минут без блокировки окна|||Waits 1–10 minutes without freezing the window|||Așteaptă 1–10 minute fără să blocheze fereastra
Свернуть Jarvis в трей|||Minimize Jarvis to tray|||Minimizează Jarvis în zona de notificare
Скрывает окно Jarvis в системный трей|||Hides Jarvis in the system tray|||Ascunde Jarvis în zona de notificare
Произнести текст|||Speak text|||Rostește textul
Произносит указанный текст голосом Jarvis|||Speaks the specified text using Jarvis' voice|||Rostește textul folosind vocea Jarvis
Вас понял, сэр|||Understood, sir|||Am înțeles, domnule
Готовая фраза подтверждения|||Ready confirmation phrase|||Expresie predefinită de confirmare
Всё готово, сэр|||All done, sir|||Totul este gata, domnule
Готовая фраза завершения|||Ready completion phrase|||Expresie predefinită de finalizare
Воспроизвести MP3|||Play MP3|||Redă MP3
Воспроизводит выбранный MP3 через Windows Media Control|||Plays the selected MP3 using Windows media|||Redă MP3-ul selectat folosind Windows
Воспроизвести WAV|||Play WAV|||Redă WAV
Воспроизводит выбранный WAV через Windows|||Plays the selected WAV with Windows|||Redă WAV-ul selectat folosind Windows
Увеличить громкость|||Increase volume|||Crește volumul
Повышает системную громкость|||Raises system volume|||Mărește volumul sistemului
Уменьшить громкость|||Decrease volume|||Scade volumul
Понижает системную громкость|||Lowers system volume|||Reduce volumul sistemului
Громкость приложения|||Application volume|||Volumul aplicației
Устанавливает громкость выбранного приложения, если оно запущено|||Sets volume for selected running app|||Setează volumul aplicației pornite
Произнести женским голосом|||Speak with female voice|||Rostește cu voce feminină
Использует доступный женский голос Windows SAPI|||Uses available female Windows SAPI voice|||Folosește vocea feminină Windows SAPI disponibilă
Произнести мужским голосом|||Speak with male voice|||Rostește cu voce masculină
Использует настроенный голос Jarvis|||Uses configured Jarvis voice|||Folosește vocea configurată pentru Jarvis
Клик колёсиком|||Middle click|||Clic mijlociu
Нажимает среднюю кнопку мыши|||Presses the middle mouse button|||Apasă butonul mijlociu al mouse-ului
Зажать правую кнопку|||Hold right button|||Ține apăsat butonul drept
Удерживает правую кнопку 1–5 секунд|||Holds the right button 1–5 seconds|||Ține apăsat butonul drept 1–5 secunde
Включить монитор|||Turn on monitor|||Pornește monitorul
Посылает Windows запрос включения монитора|||Asks Windows to wake the monitor|||Solicită Windows să pornească monitorul
Выключить монитор|||Turn off monitor|||Oprește monitorul
Гасит дисплей, не выключая компьютер|||Turns off the display, not the PC|||Stinge ecranul fără a opri calculatorul
Заблокировать экран|||Lock screen|||Blochează ecranul
Блокирует текущую сессию Windows|||Locks current Windows session|||Blochează sesiunea Windows curentă
Спящий режим|||Sleep mode|||Mod repaus
Отправляет Windows в сон после подтверждения|||Puts Windows to sleep after confirmation|||Pune Windows în repaus după confirmare
Сворачивает открытые окна Windows|||Minimizes open Windows windows|||Minimizează ferestrele deschise
Найти в интернете|||Search the web|||Caută pe internet
Открывает результаты поиска по запросу|||Opens search results for the query|||Deschide rezultatele căutării
Открыть первый результат поиска|||Open first search result|||Deschide primul rezultat al căutării
Открывает первый найденный результат через поисковик|||Opens the first search-engine result|||Deschide primul rezultat al motorului de căutare
Создаёт новый файл без перезаписи существующего|||Creates a file without overwriting existing files|||Creează un fișier fără să suprascrie fișiere existente
Создаёт новую папку в выбранном месте|||Creates a folder in the selected location|||Creează un dosar în locația aleasă
Показать файлы|||Show files|||Afișează fișierele
Показывает имена файлов в выбранной папке|||Displays filenames in the selected folder|||Afișează numele fișierelor din dosarul ales
Называет текущее время|||Says the current time|||Spune ora curentă
Jarvis | Просмотр экрана|||Jarvis | Screen inspection|||Jarvis | Inspectare ecran
Экран и кнопки Windows|||Windows screen and buttons|||Ecranul și butoanele Windows
Снимок экрана недоступен.|||Screenshot unavailable.|||Captura ecranului nu este disponibilă.
Найденные кнопки Да / Нет|||Detected Yes / No buttons|||Butoane Da / Nu detectate
Для голосового нажатия скажите «Жарвис, нажми да» или «нажми нет». Нажимается только одна точно найденная кнопка после подтверждения. Защищённые окна и непонятные кнопки не нажимаются.|||To activate by voice, say “Jarvis, press yes” or “press no”. One clearly identified button is clicked after approval. Protected or unclear controls are never clicked.|||Pentru apăsare vocală spune „Jarvis, apasă da” sau „apasă nu”. Se apasă doar un buton clar identificat după confirmare. Controalele protejate sau neclare nu sunt apăsate.
Нажать Да|||Press Yes|||Apasă Da
Нажать Нет|||Press No|||Apasă Nu
Обновить снимок|||Refresh screenshot|||Actualizează captura
Закрыть|||Close|||Închide
Показать локальный снимок и кнопки Да/Нет активной программы. Можно также сказать: «Жарвис, покажи кнопки на экране».|||Display a local screenshot and Yes/No controls of the active app. You can also ask Jarvis to show on-screen buttons.|||Afișează captura locală și butoanele Da/Nu ale aplicației active. Îi poți cere și vocal lui Jarvis să arate butoanele.
Выделите текст в браузере или Word. Затем нажмите здесь или скажите: «Жарвис, перескажи выделенное». Jarvis копирует выделенный текст, возвращает прежний буфер обмена и делает краткий пересказ на русском.|||Select text in the browser or Word, then click here or ask Jarvis to summarize selection. Jarvis copies the selection, restores the clipboard and summarizes it in Russian.|||Selectează text în navigator sau Word, apoi apasă aici ori cere-i lui Jarvis să rezume selecția. Jarvis copiază textul, restaurează clipboardul și îl rezumă în rusă.
Jarvis спросит фразу и действие, затем сохранит команду.|||Jarvis will ask for a phrase and action, then save the command.|||Jarvis va cere o expresie și o acțiune, apoi va salva comanda.
Поиск: «открыть», «клавиши», «громкость»…|||Search: “open”, “keyboard”, “volume”…|||Caută: „deschide”, „tastatură”, „volum”…
Внимание! Это действие может изменить работу Windows. Jarvis покажет содержимое и всегда спросит разрешение перед выполнением. ИИ не сможет вставлять команды CMD сюда.|||Warning: This action may change Windows behavior. Jarvis shows the content and requires approval. AI cannot insert CMD commands here.|||Atenție! Această acțiune poate modifica Windows. Jarvis va afișa conținutul și va solicita confirmare. AI nu poate insera aici comenzi CMD.
Что найти в интернете|||What to search for|||Ce să cauți pe internet
Что искать и открыть|||What to search and open|||Ce să cauți și să deschizi
Текст для активного окна|||Text for active window|||Text pentru fereastra activă
Текст для Jarvis|||Text for Jarvis|||Text pentru Jarvis
Текст женским голосом|||Text with female voice|||Text cu voce feminină
Текст мужским голосом|||Text with male voice|||Text cu voce masculină
Команда CMD — вводить только вручную|||CMD command — enter manually only|||Comandă CMD — introdu doar manual
PowerShell — вводить только вручную|||PowerShell — enter manually only|||PowerShell — introdu doar manual
Например: 600,350|||Example: 600,350|||Exemplu: 600,350
Выберите аудиофайл|||Select audio file|||Alege fișier audio
API-ключ|||API key|||Cheie API
Выберите tesseract.exe|||Select tesseract.exe|||Alege tesseract.exe
Исполняемые файлы (*.exe)|||Executable files (*.exe)|||Fișiere executabile (*.exe)
Автоматически — по языку ответа|||Automatic — match reply language|||Automat — după limba răspunsului
✓ установлен, ↓ загрузится при первом использовании. Голос выбирается по языку ответа, а не по языку интерфейса.|||✓ installed, ↓ downloads on first use. Voice follows reply language, not interface language.|||✓ instalat, ↓ se descarcă la prima utilizare. Vocea urmează limba răspunsului, nu limba interfeței.
Автоматически — как язык распознавания|||Automatic — match recognition language|||Automat — ca limba recunoașterii
Язык ответов Jarvis|||Jarvis reply language|||Limba răspunsurilor Jarvis
Определяет язык текста и озвучивания. Не меняет язык микрофона или интерфейса.|||Sets the text and speech language. Does not change microphone or interface language.|||Stabilește limba textului și a vocii. Nu schimbă limba microfonului sau interfeței.
Модели в папке models|||Models in the models folder|||Modele din dosarul models
Все файлы .gguf в папке LuxAI_Local/models. Недостаточно просто выбрать файл: для чата также требуется llama-cpp-python.|||All .gguf files in LuxAI_Local/models. Chat also requires llama-cpp-python.|||Toate fișierele .gguf din LuxAI_Local/models. Conversația necesită și llama-cpp-python.
Обновить список моделей|||Refresh model list|||Actualizează lista modelelor
Установить локальный AI-движок (llama-cpp-python)|||Install local AI engine (llama-cpp-python)|||Instalează motorul AI local (llama-cpp-python)
Модель распознавания|||Speech recognition model|||Model de recunoaștere vocală
Успешная проверка автоматически сохраняет ключ и модель. Запрос может расходовать квоту.|||Successful testing saves the key and model automatically. The request may use API quota.|||Verificarea reușită salvează automat cheia și modelul. Cererea poate consuma din cota API.
Проверить облачный AI|||Check cloud AI|||Verifică AI cloud
Ключ и связь с API будут проверены через выбранный провайдер.|||The key and API connection will be tested with the selected provider.|||Cheia și conexiunea API vor fi verificate la furnizorul ales.
Чувствительность микрофона|||Microphone sensitivity|||Sensibilitatea microfonului
100% — обычная; увеличьте для тихого микрофона. Это не меняет громкость Windows.|||100% is normal; increase for quiet microphones. This does not change Windows volume.|||100% este normal; mărește pentru un microfon slab. Volumul Windows nu se schimbă.
Уровень микрофона|||Microphone level|||Nivelul microfonului
Говорите: шкала должна двигаться.|||Speak: the meter should move.|||Vorbește: indicatorul trebuie să se miște.
Обновить устройства|||Refresh devices|||Actualizează dispozitivele
Проверить микрофон|||Test microphone|||Testează microfonul
Перезапустить микрофон|||Restart microphone|||Repornește microfonul
Сохранить диагностику|||Save diagnostics|||Salvează diagnosticul
Не удалось сохранить диагностику.|||Could not save diagnostics.|||Diagnosticul nu a putut fi salvat.
Для беспроводной гарнитуры выберите вход Headset / Hands-Free. Разрешите доступ к микрофону для настольных приложений в Windows.|||For wireless headsets, select the Headset / Hands-Free input. Allow microphone access for desktop apps in Windows.|||Pentru căști wireless, alege intrarea Headset / Hands-Free. Permite accesul la microfon pentru aplicațiile desktop în Windows.
Недоступен|||Unavailable|||Indisponibil
Устройства обновлены. Выберите вход и сохраните настройки.|||Devices refreshed. Select an input and save settings.|||Dispozitivele au fost actualizate. Alege intrarea și salvează setările.
Микрофон выключен|||Microphone off|||Microfon oprit
Загрузка модели распознавания… Первый запуск может занять несколько минут.|||Loading speech model… First launch may take several minutes.|||Se încarcă modelul vocal… Prima pornire poate dura câteva minute.
Модель готова. Открытие микрофона…|||Model ready. Opening microphone…|||Model pregătit. Se deschide microfonul…
Микрофон принимает звук|||Microphone is receiving audio|||Microfonul primește sunet
Речь обнаружена…|||Speech detected…|||Voce detectată…
Распознавание речи…|||Transcribing speech…|||Se recunoaște vocea…
Речь не распознана. Проверьте язык и уровень сигнала.|||No speech recognized. Check the language and signal level.|||Nu s-a recunoscut vorbirea. Verifică limba și nivelul semnalului.
Ошибка распознавания|||Speech recognition error|||Eroare de recunoaștere vocală
Проблема аудиопотока|||Audio stream problem|||Problemă cu fluxul audio
Нет аудиоданных. Переподключите гарнитуру и перезапустите микрофон.|||No audio data. Reconnect the headset and restart the microphone.|||Nu sunt date audio. Reconectează căștile și repornește microfonul.
Микрофон не запущен|||Microphone could not start|||Microfonul nu a pornit
Проверка микрофона: говорите в течение четырёх секунд…|||Testing microphone: speak for four seconds…|||Test microfon: vorbește timp de patru secunde…
Ожидание завершения текущей загрузки или распознавания. Проверка начнётся после остановки микрофона.|||Waiting for the current download or transcription to finish. Testing will begin after the microphone stops.|||Se așteaptă terminarea încărcării sau recunoașterii curente. Testul începe după oprirea microfonului.
Микрофон слышит звук. Если команд нет, проверьте язык и модель Whisper.|||Microphone receives sound. If commands are missing, check the language and Whisper model.|||Microfonul primește sunet. Dacă nu apar comenzi, verifică limba și modelul Whisper.
Звука нет. Проверьте вход Headset / Hands-Free, кнопку Mute и разрешения Windows.|||No sound. Check the Headset / Hands-Free input, Mute switch and Windows permissions.|||Nu este sunet. Verifică intrarea Headset / Hands-Free, butonul Mute și permisiunile Windows.
Сигнал перегружен. Уменьшите усиление микрофона в Windows.|||Signal is clipping. Reduce microphone gain in Windows.|||Semnalul este prea puternic. Redu amplificarea microfonului în Windows.
Развернуть|||Maximize|||Maximizează
Восстановить|||Restore|||Restaurează
Свернуть окно|||Minimize window|||Minimizează fereastra
Переместить окно|||Move window|||Mută fereastra
Подтвердите действие|||Confirm action|||Confirmă acțiunea
Джарвис хочет выполнить действие:|||Jarvis wants to perform this action:|||Jarvis dorește să execute acțiunea:
Скажите «да» или «нет», либо нажмите кнопку.|||Say “yes” or “no”, or choose a button.|||Spune „da” sau „nu” ori alege un buton.
Голосовое подтверждение доступно, пока микрофон включён.|||Voice confirmation is available while the microphone is on.|||Confirmarea vocală este disponibilă cât timp microfonul este pornit.
Да|||Yes|||Da
Нет|||No|||Nu
Снимок сохранён на этом компьютере:|||Screenshot saved on this computer:|||Captura a fost salvată pe acest calculator:
Текст на экране|||On-screen text|||Textul de pe ecran
(Текст не обнаружен.)|||(No text detected.)|||(Nu s-a detectat text.)
Распознавание текста недоступно или завершилось ошибкой:|||Text recognition is unavailable or failed:|||Recunoașterea textului este indisponibilă sau a eșuat:
Изменения автоматически сохраняются на этом компьютере и применяются без кнопки сохранения.|||Changes are saved and applied automatically on this computer.|||Modificările sunt salvate și aplicate automat pe acest calculator.
Пауза перед распознаванием|||Pause before recognition|||Pauză înainte de recunoaștere
Jarvis дождётся этой паузы после вашей речи (1,2–4,0 с). Если обрывает фразы, увеличьте до 3 секунд.|||Jarvis waits for this pause after your speech (1.2–4.0 s). If phrases are cut off, increase it to 3 seconds.|||Jarvis așteaptă această pauză după vorbire (1,2–4,0 s). Dacă frazele sunt întrerupte, mărește la 3 secunde.
Для румынского языка рекомендуется Medium, если хватает памяти. Модель загружается при первом использовании.|||Medium is recommended for Romanian if enough RAM is available. Downloads on first use.|||Medium este recomandat pentru română dacă există suficientă memorie RAM. Modelul se descarcă la prima utilizare.
Dmitri — Русский|||Dmitri — Russian|||Dmitri — Rusă
Mihai — Румынский|||Mihai — Romanian|||Mihai — Română
Lessac — Английский|||Lessac — English|||Lessac — Engleză
— Модель не выбрана —|||— No model selected —|||— Niciun model selectat —
Модель не выбрана|||No model selected|||Niciun model selectat
внешняя модель|||external model|||model extern
Выберите модель GGUF|||Choose a GGUF model|||Alege un model GGUF
Модели GGUF (*.gguf)|||GGUF models (*.gguf)|||Modele GGUF (*.gguf)
Модель выбрана. Локальный движок подготавливается автоматически.|||Model selected. The local engine is prepared automatically.|||Model selectat. Motorul local se pregătește automat.
Изменения автоматически сохраняются в config.json. При смене микрофона распознавание перезапускается.|||Changes are saved automatically. Changing the microphone restarts speech recognition.|||Modificările se salvează automat. Schimbarea microfonului repornește recunoașterea vocală.
Ключ сохраняется после завершения ввода. Нажмите «Проверить ключ» для проверки.|||The key is saved after editing finishes. Select “Test key” to verify it.|||Cheia se salvează după terminarea editării. Apasă „Verifică cheia” pentru verificare.
Цвет темы, фон, прозрачность и язык. Изменения видны сразу.|||Theme color, background, transparency and language. Changes appear immediately.|||Culoarea temei, fundalul, transparența și limba. Modificările se văd imediat.
Цвет фона|||Background color|||Culoarea fundalului
Подложка окна под содержимым.|||Window background behind the content.|||Fundalul ferestrei din spatele conținutului.
По теме|||Match theme|||După temă
Свой цвет|||Custom color|||Culoare personalizată
Другой цвет|||Another color|||Altă culoare
Цвет в формате #RRGGBB|||Color in #RRGGBB format|||Culoare în format #RRGGBB
Выберите цвет|||Choose a color|||Alege o culoare
Сбросить оформление|||Reset appearance|||Resetează aspectul
Пурпурный|||Purple|||Purpuriu
Оранжевый|||Orange|||Portocaliu
Красный|||Red|||Roșu
Белый|||White|||Alb
Блокнот|||Notepad|||Notepad
Калькулятор|||Calculator|||Calculator
Проводник|||File Explorer|||Explorator de fișiere
Проводник Windows|||Windows File Explorer|||Explorator de fișiere Windows
Обзор…|||Browse…|||Răsfoiește…
Название кнопки или объекта||1 (1–10 кликов)|||Button or object name||1 (1–10 clicks)|||Numele butonului sau obiectului||1 (1–10 clicuri)
Тема статьи||пользователь Discord|||Article topic||Discord user|||Subiectul articolului||utilizator Discord
Точное имя пользователя Discord|||Exact Discord username|||Numele exact al utilizatorului Discord
Отчёт.docx|||Report.docx|||Raport.docx
Новый файл.txt|||New file.txt|||Fișier nou.txt
Новая папка|||New folder|||Dosar nou
Кнопки через UI Automation не обнаружены.|||No buttons detected through UI Automation.|||Nu s-au detectat butoane prin UI Automation.
Удалить команду «{title}»?|||Delete command “{title}”?|||Ștergi comanda „{title}”?
Модель не выбрана или файл не найден. Поместите файл .gguf в папку models.|||No model selected or model file missing. Place a .gguf in models/.|||Nu este selectat un model sau fișierul lipsește. Pune un fișier .gguf în dosarul models/.
Файл GGUF повреждён или загружен не полностью. Скачайте или скопируйте его заново.|||GGUF file is invalid or incomplete. Download/copy it again.|||Fișierul GGUF este invalid sau incomplet. Descarcă-l sau copiază-l din nou.
Локальный движок ИИ подготавливается автоматически. Обновите список моделей после завершения.|||The local AI engine is being prepared automatically. Refresh models after setup.|||Motorul AI local se pregătește automat. Actualizează lista modelelor după terminare.
Локальный движок ИИ подготавливается автоматически при запуске и обновлении. Если он недоступен, проверьте logs/local_ai_install.log и повторите Update.bat с интернетом.|||The local AI engine is prepared automatically at startup/update. If unavailable, check logs/local_ai_install.log and retry Update.bat online.|||Motorul AI local se pregătește automat la pornire și actualizare. Dacă este indisponibil, verifică logs/local_ai_install.log și repetă Update.bat cu internet.
GGUF найден, локальный движок установлен. Загрузка модели зависит от свободной памяти.|||GGUF found and local backend installed. Actual load depends on available RAM.|||Modelul GGUF a fost găsit și motorul local este instalat. Încărcarea depinde de memoria RAM disponibilă.
Движок локального ИИ подготавливается…|||Preparing the local AI engine…|||Se pregătește motorul AI local…
Движок локального ИИ готов.|||Local AI engine ready.|||Motorul AI local este pregătit.
Движок локального ИИ пока недоступен. Подключитесь к интернету и повторите Update.bat.|||The local AI engine is unavailable. Connect to the internet and run Update.bat again.|||Motorul AI local este indisponibil. Conectează-te la internet și rulează din nou Update.bat.
Движок локального ИИ подготавливается автоматически при запуске и обновлении.|||The local AI engine is prepared automatically at startup and update.|||Motorul AI local se pregătește automat la pornire și actualizare.
Выбранный голос Piper загружается при первом использовании.|||The selected Piper voice downloads on first use.|||Vocea Piper selectată se descarcă la prima utilizare.
Для голоса Windows нужен установленный языковой пакет. Piper работает локально после загрузки голоса.|||Windows voices require an installed language pack. Piper works locally after downloading the voice.|||Vocile Windows necesită un pachet de limbă instalat. Piper funcționează local după descărcarea vocii.
"""

# Every entry is a Russian source string and an English/Romanian translation.
TRANSLATIONS = {}
for _line in _DATA.splitlines():
    if not _line.strip():
        continue
    _ru, _en, _ro = _line.split("|||", 2)
    TRANSLATIONS[" ".join(_ru.split())] = (_en, _ro)

_language = "ru"

# Model health is also used by non-Qt diagnostics, whose source remains
# English. Only these exact application-owned phrases are localized here;
# arbitrary model filenames and user text are never reverse-translated.
_LEGACY_UI_SOURCES = {
    "No model selected or model file missing. Place a .gguf in models/.": "Модель не выбрана или файл не найден. Поместите файл .gguf в папку models.",
    "GGUF file is invalid or incomplete. Download/copy it again.": "Файл GGUF повреждён или загружен не полностью. Скачайте или скопируйте его заново.",
    "The local AI engine is being prepared automatically. Refresh models after setup.": "Локальный движок ИИ подготавливается автоматически. Обновите список моделей после завершения.",
    "The local AI engine is prepared automatically at startup/update. If unavailable, check logs/local_ai_install.log and retry Update.bat online.": "Локальный движок ИИ подготавливается автоматически при запуске и обновлении. Если он недоступен, проверьте logs/local_ai_install.log и повторите Update.bat с интернетом.",
    "GGUF found and local backend installed. Actual load depends on available RAM.": "GGUF найден, локальный движок установлен. Загрузка модели зависит от свободной памяти.",
}

TRANSLATIONS["Голоса со значком загрузки загрузятся при первом использовании. Голос выбирается по языку ответа, а не по языку интерфейса."] = (
    "Voices with a download icon download on first use. Voice follows reply language, not interface language.",
    "Vocile cu pictograma de descărcare se descarcă la prima utilizare. Vocea urmează limba răspunsului, nu limba interfeței.",
)


def get_ui_language():
    return _language


def set_ui_language(language):
    global _language
    _language = normalize_language(language)


_TEXT_AUTHORS = frozenset({"Tu", "You", "Вы"})
_VOICE_AUTHORS = frozenset({"Tu (voce)", "You (voice)", "Вы (голос)"})


def is_user_author(who):
    """Recognize only application-owned user labels, never an arbitrary name."""
    return who in _TEXT_AUTHORS or who in _VOICE_AUTHORS


def chat_author(who, language=None):
    """Render history roles in the interface language without editing data."""
    code = normalize_language(language if language is not None else _language)
    if who in _VOICE_AUTHORS:
        return {"ru": "Вы (голос)", "en": "You (voice)", "ro": "Tu (voce)"}[code]
    if who in _TEXT_AUTHORS:
        return {"ru": "Вы", "en": "You", "ro": "Tu"}[code]
    return str(who)


def tr(source, language=None):
    """Translate only known interface phrases; preserve arbitrary user data."""
    if not isinstance(source, str):
        return source
    source = _LEGACY_UI_SOURCES.get(source, source)
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
        if isinstance(widget, QComboBox) and widget.objectName() != "UiLanguageCombo":
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
            if suffix.strip() in ("сек", "sec", "s"):
                widget.setSuffix(" sec" if language == "en" else (" s" if language == "ro" else " сек"))
            elif suffix.strip() in ("мин", "min"):
                widget.setSuffix(" мин" if language == "ru" else " min")
            elif suffix.strip() in ("шага", "steps", "pași"):
                widget.setSuffix({"ru": " шага", "en": " steps", "ro": " pași"}[language])
        _translate_property(widget, "tooltip", widget.toolTip, widget.setToolTip, language)
        _translate_property(widget, "accessible", widget.accessibleName, widget.setAccessibleName, language)
        # Only local dialogs have translated window titles, not dynamic content.
        if widget.isWindow():
            _translate_property(widget, "windowtitle", widget.windowTitle, widget.setWindowTitle, language)
