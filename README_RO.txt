LUXAI LOCAL 0.4.4a — ACTUALIZARE 2026-11-27
(Același ghid în rusă: README_RU.txt, în engleză: README_EN.txt.)

0.4.4a: Cercul de acțiuni arată nou: butoane rotunde pe un inel, colorate pe grupe (comenzile tale, căutare,
fereastră, media), butonul de sub mouse crește lin și strălucește, iar în centru apare numele lui întreg.
Comenzile au iconița potrivită (site, aplicație, joc…), etichetele încap pe două rânduri, iar cercul se
deschide cu o animație scurtă. Același aspect îl are și cercul convertorului.

0.4.3z: Fereastra de actualizare arată acum doar cât descarcă actualizarea însăși. Înainte număra tot traficul
PC-ului, așa că o descărcare Steam în paralel părea o actualizare de 2 GB.

0.4.3y: Insula de stare știe mai mult. Jocuri: iconița și numele jocului (din Steam — cu bannerul lui), cât
timp ești în joc și cât azi; la pornire se deschide singură pentru 4 s, la ieșire spune „Ai jucat 1 h 05 min”.
Steam: ce se descarcă sau se instalează, procentul, GB, viteza și cât a mai rămas; „Instalat” la final.
Discord: când ești în apel — unde / cu cine, cât durează, butoane pentru microfon, căști și volumul Discord
(mai tare / mai încet). Setări noi „Ce să arate și ce e mai important”: pentru fiecare sursă alegi Oprit /
Scăzut / Normal / Ridicat / Mereu primul — de exemplu poți lăsa doar Discord.

0.4.3x: Plugin nou — „Insula de stare” (Extensii → Desktop), ca Dynamic Island de pe iPhone. O bandă neagră
sus (sau jos) pe ecran care arată ce se întâmplă acum: ce face Jarvis și ce răspunde, cronometrul cu timpul
rămas, muzica sau video-ul care cântă (cu copertă și timp), volumul când îl schimbi, pauzele, dictarea,
subtitrările și, dacă vrei, notificările. Treci cu mouse-ul — se deschide un card cu butoane (pauză / următorul,
+1 min la cronometru, „Gata” la pauză, oprește alarma) și acțiuni rapide (microfon, mod silențios, subtitrări,
captură de ecran, Jarvis). Multe setări: formă de insulă sau decupaj, sus/jos, monitorul, mărimea, fundalul,
culorile, animația. Ctrl+Alt+I o deschide și o fixează. Actualizarea instalează o mică bibliotecă Windows
pentru muzică (~300 KB).

0.4.3w: Subtitrări live mult mai exacte. Modelul precis corectează acum FIECARE rând (înainte multe rânduri
rămâneau ciorne), citind într-o singură trecere toate frazele terminate între timp. Măsurat pe vorbire de
test în timp real: greșeli în rusă 11,4% → 4,5%, în română 19,5% → 6,7%, engleză 2,2% → 1,9%; cuvinte
pierdute de 3–4 ori mai puține; primele cuvinte apar cu ~0,7–1 s mai devreme. Româna păstrează acum
diacriticele. Subtitrările filmelor nu mai fixează o limbă greșită dacă filmul începe cu muzică.

0.4.3v: Plugin nou — „Cerc de acțiuni” (Extensii → Control PC și casă). Apasă Ctrl+Alt+C: lângă cursor
se deschide un cerc cu comenzile tale (dintr-un clic), căutarea textului selectat, acțiuni pentru
fereastra activă (minimizează, maximizează, deasupra tuturor, închide) și media (pauză/redă, piesa
următoare, fără sunet). Alegi cu mouse-ul, cu săgețile și Enter sau cu cifrele 1–9; Esc îl închide.
În setări alegi ce comenzi apar și câte elemente are cercul (4–12).

0.4.3u: Plugin nou — „Asistent de text” (Extensii → Text și clipboard). Selectează text în orice program
și apasă Ctrl+Alt+T: lângă cursor apar acțiunile 1 Corectează · 2 Îmbunătățește · 3 Scurtează ·
4 Tradu · 5 Răspunde la mesaj și un câmp pentru cererea ta („fă-l mai politicos”). Rezultatul se poate
edita; Ctrl+Enter îl pune în locul textului selectat. Traducerea merge offline; celelalte folosesc AI-ul
din cloud dacă e conectat, altfel modelul local (fără internet, ~8–10 s).

0.4.3t: AI-ul local funcționează din nou. Actualizarea motorului (llama-cpp-python 0.3.38) nu pornește
pe unele procesoare (eroarea „instrucțiune ilegală”), deși verificarea spunea că e în regulă. Jarvis
pornește acum efectiv motorul la verificare; o versiune care nu merge pe PC-ul tău e ținută minte și
înlocuită automat cu ultima care merge (0.3.36).

0.4.3s: Trei corecturi după reverificarea versiunii 0.4.3r. Dacă PC-ul a dormit sau Jarvis a fost închis
câteva zile, Jarvis spune în chat ce comenzi programate au fost ratate (nu le mai rulează târziu — de
exemplu o oprire a PC-ului programată seara nu se face dimineața). Prima configurare OCR găsește un
Tesseract funcțional chiar dacă primul găsit e deteriorat. Curățarea „Descărcări” nu mai poate muta un
fișier nou apărut cu același nume.

0.4.3r: Corecturile celui de-al șaptelea audit (47 de puncte). Printre ele: „tradu …” nu mai taie începutul
textului; un memento de la 23:59 nu se mai pierde la miezul nopții; două comenzi cu aceeași frază sunt
semnalate la salvare; subtitrările live nu mai rămân în urmă pe un PC lent; filmările portret din telefon
nu mai ies rotite; un update întrerupt nu mai lasă cod nou cu biblioteci vechi; vocea Fish se oprește
imediat la „stop”. Extensia (1.12.0) pornește subtitrările și cu sunetul încărcat deja în pagină.
IMPORTANT: după actualizare, în chrome://extensions apasă „Reîncarcă” la extensia Jarvis.

0.4.3q: Extensia (1.11.1) nu mai dă eroarea „Failed to execute 'postMessage' … origin ('null')” pe
site-uri cu cadre izolate (de exemplu chatgpt.com).
IMPORTANT: după actualizare, în chrome://extensions apasă „Reîncarcă” la extensia Jarvis, apoi
„Elimină toate” la erorile vechi.

0.4.3p: Corecturile celui de-al șaselea audit (14 puncte). Update.bat reinstalează acum fișierele
programului care lipsesc sau sunt deteriorate, chiar dacă versiunea e la zi. „Amintește-mi la 6 seara
să verific trenul de la 19:45” sună la 18:00; „2 ore și jumătate” durează 2,5 ore. Extensia (1.11.0)
prinde și pistele audio AAC fragmentate, nu mai pornește filmul cu răspunsul de la locul vechi după
o derulare și repornește video-ul după o schimbare de sursă.
IMPORTANT: după actualizare, în chrome://extensions apasă „Reîncarcă” la extensia Jarvis.

0.4.3o: Teste noi pentru cele 7 module care nu aveau niciunul. Au găsit două greșeli, acum reparate:
cercul convertorului se bloca la săgeți când nu avea nicio opțiune, iar zona selectată pe ecran
ieșea cu un pixel mai mare.

0.4.3n: Citirea notificărilor spune acum o dată de ce tace: de exemplu „Nu citesc notificările cât timp
Discord folosește microfonul (apel)” — cu opțiunea „Tăcere în timpul apelurilor” pornită, un canal
vocal Discord ținea toate notificările doar pentru „ce a venit”, fără niciun mesaj.

0.4.3m: Subtitrările nu se mai dublează (aceeași frază recunoscută de două ori apare o singură dată).
Când sari în film (sau YouTube trece la alt minut), video-ul așteaptă puțin, de obicei 3–4 s, cel
mult 8 s, până e gata prima frază de acolo. Extensia (1.10.0) atinge alte site-uri decât YouTube
doar cât timp subtitrările sunt pornite.
IMPORTANT: după actualizare, în chrome://extensions apasă „Reîncarcă” la extensia Jarvis.

0.4.3l: Subtitrările pentru YouTube sunt mai ușoare și mai rapide. Extensia (1.9.0) trimite lui Jarvis
doar sunetul nou (de ~6 ori mai puțin trafic), nu mai ține pe pauză reclamele și video-urile scurte,
iar filmul pornește după câteva secunde, nu după jumătate de minut. Setare nouă „Așteaptă
subtitrările”: doar la început (implicit), niciodată, sau și în timpul filmului.
IMPORTANT: după actualizare, în chrome://extensions apasă „Reîncarcă” la extensia Jarvis.

0.4.3k — Cu extensia 1.8.0, Jarvis pregătește în avans traducerile și la reluarea unui clip. Poate aștepta până la un minut la pornire și până la 15 secunde când se termină rezerva. Apasă din nou Play ca să continui imediat.

0.4.3j: În fila activă, Jarvis poate aștepta până la 7 secunde la început ca să pregătească
prima replică. Poți apăsa din nou Play ca să sari peste așteptare. Frazele următoare sunt
traduse imediat ce sunt recunoscute. Reîncarcă extensia Jarvis 1.7.0 și reîmprospătează fila video.

0.4.3i: Jarvis poate pregăti până la un minut de subtitrări din audio-ul deja încărcat pe YouTube.
În modul „Precis” folosește modelul mai puternic atunci când are suficient avans. YouTube decide cât
audio încarcă. Reîncarcă extensia Jarvis 1.6.0 și reîmprospătează fila cu videoclipul.

0.4.3h: Jarvis pregătește și traduce în avans sunetul pe care YouTube l-a încărcat deja în browser.
Textul pregătit apare la momentul rostirii. Dacă audio-ul din avans lipsește, continuă subtitrarea live.
Reîncarcă extensia Jarvis 1.5.0 în pagina de extensii și reîmprospătează fila YouTube.

0.4.3g: Subtitrările pregătite recunosc surse fără extensie, inclusiv după „Înapoi”, și închid
conexiunile întrerupte. Mementourile acceptă „a.m.”, „p.m.” și durate precum „two and a half hours”.
Pentru YouTube, Jarvis transcrie live sunetul redat de browser, inclusiv în playerele încorporate.
După actualizare, reîncarcă extensia Jarvis 1.4.0 din chrome://extensions sau edge://extensions.

0.4.3f: Dacă Fish Audio refuză cheia (greșită/expirată), nu mai are credit sau nu răspunde, Jarvis
nu mai tace („Vocea nu este disponibilă”): citește cu vocea locală și spune o dată în chat de ce.
Pentru vocea Fish din nou, pune o cheie nouă în Setări → Sinteza vorbirii.

0.4.3e: Corecturile celui de-al cincilea audit (18 puncte). Sunetul filmelor e descărcat acum
de Jarvis însuși, cu verificarea completă a certificatului HTTPS pentru fiecare bucată a filmului.
Subtitrările merg și după „Înapoi” în browser, la filme cu timpul decalat și la reîncărcarea
paginii. Extensia (1.3.0) nu înregistrează nimic cât timp subtitrările sunt oprite. Mementourile
„tomorrow forecast” / „seara” / „un sfert de oră” sunt înțelese corect; „minus 5 minute” e refuzat.
„Pregătește înainte” e acum 3 minute implicit, iar pe pauză cel mult un minut.
IMPORTANT: după actualizare, în chrome://extensions apasă „Reîncarcă” la extensia Jarvis.

0.4.3d: Bara de derulare nu mai are o bandă închisă în spate, iar iconițele secțiunilor din
setările extensiilor nu mai au pătrat de fundal.

0.4.3c: Corecturile celui de-al patrulea audit (19 puncte). Extensia pentru Chrome (1.2.0) nu mai
trimite nimic lui Jarvis cât timp subtitrările sunt oprite, preferă fila la care te uiți și
pornește corect alt episod în același player. Sunetul filmelor trece printr-un filtru local care
nu lasă conexiuni spre acest PC sau rețeaua de acasă. Setare nouă „Pregătește înainte” (10/3/1 min).
Mementoul „at 08:00 tomorrow to call Ana” are acum eticheta corectă. Dacă programul ales pentru
subtitrări pornește mai târziu, captura trece singură pe el.
IMPORTANT: după actualizare, în chrome://extensions apasă „Reîncarcă” la extensia Jarvis.

0.4.3b: Corecturile celui de-al treilea audit (29 de puncte). Extensia pentru Chrome are acum o
cheie secretă de asociere cu Jarvis (alte extensii sau programe nu mai pot vorbi cu el), urmărește
un singur player, se oprește când închizi fila și ține cont de pauză și buffering. Mementourile
„la 08:00 … 5 minute” și „PM” din text sunt înțelese corect; lipirea nu mai pune ce s-a copiat între
timp. IMPORTANT: după actualizare, în chrome://extensions apasă „Reîncarcă” la extensia Jarvis.

0.4.3a: Subtitrările nu se mai opresc la eroarea „COMError … Разрушительный сбой”
(o eroare de moment a sunetului Windows, de ex. când Chrome își repornește partea audio).
Captura se reia singură, regăsește programul după repornire, iar dacă nu merge trece pe tot
sunetul PC-ului. Detaliile se scriu în logs\captions_error.log.

0.4.3: Când pornești subtitrările, Jarvis întreabă dacă vrei extensia pentru Chrome (Da / Mai
târziu / Nu mai întreba). La „Da” se deschide un ghid: Chrome se deschide, adresa
chrome://extensions și calea dosarului se copiază singure, iar fereastra devine verde
imediat ce extensia funcționează. Jarvis ține minte că extensia e instalată.

0.4.2z: Subtitrări din timp pentru filme în browser. Cu extensia Jarvis pentru Chrome/Edge,
partea de film deja încărcată e recunoscută și tradusă ÎNAINTE să fie redată, iar fiecare
cuvânt apare exact când e rostit în film (și după derulare). Instalare, o singură dată: Extensii → Subtitrări
live → Extensia pentru Chrome → Instalează…, apoi în Chrome pornește „Modul dezvoltator”,
apasă „Încarcă extensia neîmpachetată” și alege dosarul browser_extension. Nu merge cu
video protejat (Netflix, Disney+ etc.); acolo rămân subtitrările live obișnuite.

0.4.2y: Subtitrările live au modul nou „Hibrid” (implicit): textul și traducerea apar în
~1–2 secunde în timp ce omul vorbește, apoi un model precis corectează rândul. Înainte
traducerea apărea abia la finalul frazei (până la ~6 s). Vorbirea încetă (video cu volum mic)
nu se mai pierde. În Setări → Modelul de recunoaștere există acum și Whisper Large-v3.

0.4.2x: Documentația de pe GitHub e curățată: ghidurile vechi și neactuale au fost șterse,
README.md și PROJECT_HANDOFF.md sunt rescrise pentru versiunea de acum. Programul nu s-a schimbat.

0.4.2w: Corecturile celui de-al doilea audit (50 de puncte). Lipirea din istoricul clipboard
nu mai poate ajunge în altă fereastră; răspunsurile vocale lungi se citesc de la început;
«amintește-mi peste -5 minute» e refuzat, iar mesajul mementoului nu se mai pierde;
GIF-urile păstrează durata reală; fereastra nu mai îngheață la clipboard, notificări,
curățarea descărcărilor sau modul administrator. Actualizarea e mai sigură: fișierele
șterse și bibliotecile revin dacă ceva eșuează, iar Jarvis nu pornește în timpul ei.
Fiecare copie Jarvis are acum propria sarcină de administrator și propria pornire automată.

0.4.2v: Codul intern e simplificat (bucla microfonului și cea a agentului împărțite în
părți mici), fără schimbări de comportament.

0.4.2u: install_windows.bat merge din nou (eroarea „The property 'Count' cannot be found”).
Actualizările sunt semnate digital, se reiau singure după o întrerupere, iar bibliotecile
se schimbă doar când se schimbă cerințele proiectului.

0.4.2t: Actualizarea nu mai eșuează cu „Access is denied … Onest.ttf”: fereastra de
actualizare ținea deschis fontul aplicației. Acum folosește o copie temporară.

0.4.2s: Update.bat din 0.4.2r nu pornea descărcarea verificată („The system cannot find
the path specified”). Dacă îl ai, rulează o dată în folderul Jarvis:
.venv\Scripts\python.exe Update.py

0.4.2r: Reparate constatările raportului de audit din 19 noiembrie: clipboardul nu mai
provoacă erori native, dictarea nu mai scrie în altă fereastră, conversia video păstrează
timpii, alarmele nu se mai pierd, mementourile păstrează mesajul, traducerea păstrează
punctuația și nu mai blochează fereastra, Telegram nu se mai blochează, un singur Jarvis
per folder, actualizarea închide Jarvis sigur, verifică updaterul după hash-ul GitHub,
readuce bibliotecile la eșec și spune adevărul despre restaurare.

0.4.2q: Microfonul Discord merge fără cloud și în Discord-ul în rusă: butonul se numește
„Заглушить”, căștile „Откл. звук” — Jarvis le citește și le apasă direct.

0.4.2p: Butoanele Discord (microfon, căști) sunt căutate mai răbdător; dacă nu se găsesc,
Jarvis scrie local în logs\discord_buttons.txt ce vede, ca să putem repara.

0.4.2o: Comenzile arată ca în Luxify: iconițele reale ale programelor (Chrome,
Telegram, Word, Discord, Steam) și grupul separat „Control Discord” — 35 de comenzi
pe care Jarvis le face singur, fără cloud: oprește/pornește microfonul și căștile,
răspunde sau respinge un apel, canale, servere, căutare, mențiuni și altele.
Microfonul și căștile Discord se citesc și se apasă direct (accesibilitatea
Windows), fără capturi de ecran; captura prin AI cloud e doar de rezervă.
Fișierele .gitattributes, .gitignore și manifest.example.json rămân doar pe GitHub.

0.4.2n: Update.bat merge din nou (în 0.4.2l consola Windows tăia comenzile).
Dacă Update.bat dă erori „'ho' is not recognized”, rulează o dată în folderul Jarvis:
.venv\Scripts\python.exe Update.py

0.4.2m: Butonul de reîmprospătare de la „Ce ascult” (subtitrări) nu mai are fundal negru.

0.4.2l: Update.bat și install_windows.bat au o fereastră frumoasă în stilul lui
Jarvis: ce se face acum, cât timp a rămas, viteza internetului, cât s-a descărcat.
Jarvis se închide singur la pornirea actualizării.

0.4.2k: Update.bat instalează singur traducătorul offline. În chat (și cu vocea):
„tradu în engleză: …”, „переведи на румынский: …”, „cum se spune … în rusă” —
traduce traducătorul offline în ~0,4 s, fără internet.

0.4.2j: Toată traducerea merge doar offline, pe acest PC (subtitrări, citire cu voce,
notificări, „Tradu” din clipboard) — traducerea prin cloud a fost scoasă. Înțelege
și ucraineană, germană, franceză, spaniolă, italiană, portugheză, poloneză.

0.4.2i: Traducător offline (NLLB, ~640 MB în models\): subtitrările, citirea cu
voce și notificările se traduc în ~0,5 s pe frază, fără internet; Gemini rămâne
doar de rezervă.

0.4.2h: Subtitrările detectează singure limba (engleză, română, rusă), nu mai inventează
text și, cu traducerea pornită, arată doar traducerea.

0.4.2g: Barele de derulare sunt subțiri și rotunde, ca în Luxify.

0.4.2f: Setări → Sistem: „Pornește Jarvis ca administrator” — o sarcină programată
creată o singură dată; apoi Jarvis pornește cu drepturi de administrator fără întrebări.

0.4.2e: Dacă un program (de ex. Discord) e pornit ca administrator, Jarvis spune
clar de ce nu poate citi din el și cum se rezolvă.

0.4.2d: Citirea cu voce pornește de două ori mai repede, fără pauze între bucăți;
din Discord textul selectat se citește și prin UI Automation dacă Ctrl+C nu merge.

0.4.2c: La Subtitrări live, în „Ce ascult” apar acum toate programele deschise
(și Google Chrome), nu doar cele care cântă chiar în acel moment.

0.4.2b: Logo-ul e acum vectorial — clar și fără pixeli la orice mărime.

0.4.2a: Logo nou pentru Jarvis (alb pe pătratul în culoarea temei) în locul
robotului — în aplicație, bara de activități, tray și Task Manager.

0.4.2: Când Jarvis ascultă, avatarul are o animație proprie: sfera devine rotundă
și liniștită, iar din ea pleacă unde ca un sonar. Când vorbește, se umflă după voce.

0.4.1z: În Task Manager apare „Jarvis” cu iconița lui, nu „Python”. run_windows.bat
pornește prin .venv\Scripts\Jarvis.exe (creat automat; dacă nu se poate, ca înainte).

0.4.1y: Iconiță nouă și clară pentru Avatarul vizual: o sferă cu o steluță.

0.4.1x: Avatarul arată din nou ca înainte; rămâne doar turtirea la marginea
ecranului (nu mai e tăiat) și faptul că nu mai dispare.

0.4.1w: La marginea ecranului avatarul se turtește de margine ca în Luxify (nu mai
e tăiat); culori mai apropiate de Luxify; nu mai dispare când schimbi aplicația
sau faci o captură de ecran.

0.4.1v: Setările pluginurilor se salvează singure după fiecare schimbare — nu mai
trebuie apăsat „Salvează”. Cheile și tokenurile se salvează când termini de scris.

0.4.1u: Avatarul intră acum în colțul ecranului și se lipește de ambele margini;
în modul mini se ascunde pe jumătate la margine și pe trei sferturi în colț, ca în Luxify.

0.4.1t: Avatarul vizual e ca în Luxify: o sferă vie deasupra ferestrelor, care
„respiră”, reacționează la vocea lui Jarvis / sunetul PC-ului / microfon și își
schimbă culoarea după stare (execută, vorbește, eroare, microfon oprit...).

0.4.1s: Fontul Fuzzy Bubbles nu are litere rusești, de aceea textul rusesc apărea
cu alt font. Acum literele lipsă vin din Pangolin (același stil, scris de mână),
deci tot programul arată la fel.

0.4.1r: Subtitrările apar din mers, cât vorbește omul (textul crește la ~1 s),
fraze de cel mult 5 s; setare nouă „Viteza recunoașterii” (instant / rapid și
precis / ca la comenzile vocale).

0.4.1q: Subtitrări live ca în Luxify: o bandă deasupra ferestrelor cu textul a ce
se aude pe PC (tot sunetul sau doar un program), recunoaștere locală, traducere
opțională prin AI, mărime/opacitate/rânduri, „arată/ascunde subtitrările” cu vocea.

0.4.1p: Istoricul clipboard-ului e ca în Luxify: text cu formatare și imagini,
Alt+Win+V deschide lista lângă cursor (Enter lipește, Shift+Enter fără formatare),
fixare, excepții pentru managerele de parole, AI (traducere, corectare, pe scurt),
salvat criptat pe acest PC. Cu vocea: „lipește precedentul”.

0.4.1o: Apelul în Discord pornește mult mai repede: după ce se deschide chatul,
Jarvis apasă scurtătura Discord Ctrl+' și verifică o singură dată că sună.

0.4.1n: Discord rapid: scurtăturile Discord prin voce (apel, servere, canale,
necitite, mesaje directe, Ctrl+K, fixate, membri...), „verifică Discord” arată
microfonul, căștile, apelul și chatul deschis; microfonul/căștile se comută cu
Ctrl+Shift+M / Ctrl+Shift+D cu verificare pe ecran.

0.4.1m: Pauzele sunt ca în Luxify: ochi (20-20-20), întinderi și apă, fiecare cu
intervalul ei; un card în colț cu „Gata / Mai târziu / Sar”; statistica zilei;
nu deranjează în jocuri, apeluri, ore de liniște și „Nu deranja” din Windows.

0.4.1l: la derularea cu clic pe rotiță, cursorul arată direcția (▲ sau ▼),
ca în Windows; nu mai rămâne niciun cerc fix pe ecran.

0.4.1k: derulare fără rotiță: bare de derulare late și vizibile; clic pe rotiță
și miști mouse-ul (ca în browser); tragi fundalul paginii cu butonul stâng;
PageUp / PageDown / Home / End.

0.4.1j: editorul de comenzi („Новая команда”) se deschide în fereastra Jarvis,
nu separat; săgeata din antet te duce înapoi la listă.

0.4.1i: În chatul cu AI poți atașa și dosare („+” → „Папку…”, trage-l sau
lipește-l): Jarvis trimite structura și textul fișierelor text/cod, fără
fișiere secrete (.env, chei) și fără .git/node_modules. Atașamentele PDF
merg din nou.

0.4.1h: Citirea cu voce și citirea notificărilor traduc textul în altă limbă
în limba lui Jarvis și citesc imediat traducerea (pe bucăți, fără să aștepte
tot textul). Numele aplicației din notificare rămâne neschimbat. Traduce
AI-ul cloud din setări; fără el, modelul local.

0.4.1g: la pornire Jarvis verifică singur AI-ul din cloud și pe cel local;
în „Дополнения” ambele apar cu verde când funcționează. Vocea Fish Audio
începe să vorbească imediat (în flux), fără să aștepte tot răspunsul, și este
pregătită de la pornire fără să trimită text.

0.4.1f: reparații după o verificare reală. Citirea textului selectat, istoricul
clipboard-ului, inserțiile rapide și convertorul merg acum și cu tastatura în
rusă. Notificările se citesc implicit din toate aplicațiile (nu doar mesagerii).
Dictarea nu mai scrie fraze inventate când nu vorbești.
Telegram Desktop: activează în Setări → Notificări „Folosește notificările Windows”,
altfel Telegram nu trimite notificări pe care Jarvis să le poată citi.

0.4.1e: Citirea notificărilor. Activează „Озвучка уведомлений” în Extensii:
Jarvis citește cu voce notificările noi (implicit mesageriile și e-mailul).
Tace cât PC-ul e blocat, în orele de liniște, în jocuri pe tot ecranul și
în apeluri. Spune „ce a venit” pentru cele ratate sau „nu deranja” pentru o oră.
Textul rămâne doar în memorie, nu se scrie pe disc și nu se trimite nicăieri.

0.4.1d: Convertor ca în Luxify. Activează-l în Extensii, selectează fișiere în
Explorer sau pe desktop (sau copiază o imagine) și apasă Ctrl+Alt+X: lângă
cursor apare un cerc cu acțiuni (format, comprimare, micșorare, rotire,
decupare, PDF, MP3/M4A/WAV/FLAC/OGG/OPUS, MP4, GIF, fără sunet). Alege cu
mouse-ul, săgețile sau cifrele. Originalul nu se schimbă.

0.4.1c: Cronometre și alarme. Activează „Таймеры и будильники” în Extensii,
apoi spune „Jarvis, pune un cronometru de 10 minute”, „trezește-mă la 7:30”,
„cât a mai rămas” sau „anulează cronometrul”. Alarmele rămân și după repornire;
la final apare o fereastră cu „Amână” și „Stop”, plus sunet și voce.

0.4.1b: PC Control funcționează. Creează un bot în Telegram la @BotFather
(/newbot), lipește tokenul în Extensii → PC Control, trimite /start botului,
copiază ID-ul primit în „ID Telegram proprietar”, activează și salvează.
Botul arată dosarele tale de comenzi ca butoane și răspunde doar ție.
Dacă același bot e folosit în Luxify, oprește-l acolo sau fă un bot separat.

0.4.1a: setările pluginurilor se deschid în pagina Extensii (nu într-o fereastră
separată), cu secțiuni, „Cum funcționează”, „Resetează tot” și „Salvează”,
ca în Luxify. Dictarea are și un câmp „Проверка” pentru test.

0.4.1: Dictarea inteligentă funcționează. Apasă de două ori Ctrl din dreapta
(sau combinația ta), vorbește, și textul se scrie unde e cursorul. Spune
„virgulă”, „punct”, „rând nou” sau „șterge ultimul cuvânt”. Opțional pornește
cu vocea: „Jarvis, scrie …”. Activeaz-o în Extensii → Умная диктовка.

0.4.0: buton nou „Расширения / Extensii” în bara din stânga. Pagina are
22 de pluginuri pe 5 teme, căutare, vizualizare Plăci/Listă și setări pentru
fiecare plugin. Funcționează deja: Citire cu voce, Istoric clipboard,
Inserții rapide, Pauze, Taste media, Convertor imagini, Capturi de ecran și
Curățenie în Descărcări. Celelalte sunt marcate „Скоро” (în curând).

0.3.9g: setări inspirate din Luxify, cu rânduri compacte și comutatoare.
În Intrare vocală poți alege ascultare continuă sau o tastă ținută apăsată
cât vorbești (Windows), fraze pentru prefix/silențios/oprirea microfonului
și toleranță conservatoare pentru comenzile salvate. Parafrazarea acceptă
variante locale de exprimare, fără cerere în cloud. Fraza de oprire
anulează acțiunile rămase în lanț. Interfața oferă fontul Onest inclus.
Resetarea vocii cere confirmare și schimbă numai preferințele acelei secțiuni.
Actualizări afișează versiunea, verifică GitHub și oferă actualizatorul Windows.
Dacă o activezi, verificarea automată se face la prima deschidere a Setărilor pe sesiune.
Instalarea închide Jarvis înainte de a porni actualizatorul.
Închide Jarvis → Update.bat → run_windows.bat. Datele personale se păstrează.

0.3.9.e: voce Jarvis prin Fish Audio, opțională.
În Setări → Sinteză vocală alege Fish Audio și introdu cheia API Fish.
Vocea rusească ДЖАРВИС este presetată. Poți lipi linkul sau ID-ul altei voci
și asculta proba. Cont/cheie: https://fish.audio/app/api-keys/
Cheia se păstrează criptat în Windows, separat de cheia pentru AI-ul din chat;
nu intră în config.json. Este acceptată și variabila FISH_API_KEY.
Fish necesită internet și primește textul care trebuie rostit.
Se folosește numai modelul s2.1-pro-free, oferit acum gratuit în limitele
serviciului. Nu se trece automat la modele plătite. Proba de pe site folosește
Drama 3, deci modelul gratuit poate suna diferit. Piper rămâne implicit și local.
Nu se generează audio Fish la pornire. Volumul, viteza și oprirea funcționează
și cu Fish. Închide Jarvis → Update.bat → run_windows.bat.
Datele personale, setările, comenzile și modelele sunt păstrate.

0.9.3.d: săgeți și rânduri de comenzi afișate corect cu tema Windows.
Exportă comanda, dosarul sau colecția selectată; fără selecție, fila curentă.
Importul păstrează structura și grupurile goale, folosește ID-uri noi și
lasă comenzile dezactivate inițial. Comenzile agentului au filă funcțională
cu editor, dosare și import/export. În Suplimente apare numai starea AI-ului
local; alegerea modelului rămâne în Setări. Un model disponibil este
«pregătit», iar funcționarea se confirmă numai după un răspuns GGUF real.
Închide Jarvis, rulează Update.bat, apoi run_windows.bat.
Datele personale, setările, comenzile și modelele sunt păstrate.

0.9.3.c: chat cu miniaturi și carduri compacte de fișiere, eliminare
individuală, + jos stânga și Trimite jos dreapta. Ctrl+V atașează fișiere
copiate din Explorer și imagini din clipboard; textul se lipește normal.
Lipirea este locală; AI cloud primește atașamentele numai la Trimite.
Comenzile de bază se pot redacta, salva, dezactiva și șterge; modificările
se păstrează la repornire și actualizare. Meniul cu trei puncte include
fraze obligatorii/opționale, clonare, copiere, JSON și ștergere.
Ștergerea unui folder personal păstrează comenzile lui.
Închide Jarvis, rulează Update.bat, apoi run_windows.bat.
Setările, modelele și fișierele personale sunt păstrate; Markdown și
testele proiectului rămân numai pe GitHub.

0.3.9b: interfață de comenzi cu panou de creare, foldere, colecții,
import/export JSON în dreapta. Editează comenzi din meniul lor contextual,
nu din panoul drept. Chatul are atașamente deasupra textului, buton + jos
stânga și Trimite jos dreapta. Enter trimite, Shift+Enter adaugă rând nou.
Editorul are două coloane cu Salvează/Anulează în dreapta.
Înregistrarea folosește un dialog modal independent, cu Stop/Anulează
clicabile, iar ferestrele se restaurează după captură.

0.3.9a: chat compact cu buton + și atașamente integrate; comenzile de
bază au folder separat. Editorul are informații vizibile la hover sau clic.
Înregistrarea minimizează Jarvis, arată un panou Stop/Anulează și restaurează
fereastra după oprire. Comenzile personale nu mai au limita fixă de opt pași,
dar acțiunile sunt validate și operațiile riscante cer confirmare.

0.3.9: FIȘIERE ÎN CHAT ȘI EDITOR COMPLET DE COMENZI
Apasă Atașează sau trage fișiere în chat, scrie cererea și apasă Trimite.
Sunt acceptate texte, cod, CSV, JSON, Markdown, PDF, DOCX și fotografii:
cel mult 8 fișiere, 10 MB fiecare și 20 MB în total per mesaj.
Selectarea și previzualizarea sunt locale. Cu AI cloud activ, Trimite partajează
fișierele selectate cu furnizorul configurat. Imaginile cer un model cu suport
vizual; local se folosesc textul documentelor și OCR, fără analiză vizuală locală.

Modificările propuse se verifică înainte de Aplică sau Salvează o copie.
Textul și modificările DOCX compatibile, cu aceeași structură de paragrafe,
pot fi aplicate după verificarea originalului, cu rezervă în .luxai_data/file_edits.
Modificările PDF ori DOCX care schimbă structura se exportă ca o copie text;
originalul rămâne păstrat. Codul atașat este citit, nu executat.

Editorul Comenzi include fraze, cuvinte opționale, voce, combinații de taste,
programări, evenimente pentru aplicații/căști, înregistrare de acțiuni Windows
și propuneri de pași prin AI. Verificarea frazei nu execută nimic; Execută acum
rulează varianta verificată. Poți folosi acțiuni ordonate, confirmare și
înlănțuire. Programările, evenimentele și tastele globale cer Jarvis pornit.
Înregistrarea literelor/cifrelor necesită activare explicită și este limitată
la Dota 2, Counter-Strike 2, War Thunder și Undertale.
Înregistrarea și comenzile native Windows trebuie verificate pe calculatorul țintă.

Meniul lateral își păstrează starea restrânsă. Cardurile Captură/OCR dispar din
Instrumente; comenzile existente și pregătirea automată OCR rămân disponibile.
Documentele .md și testele rămân pe GitHub. Fișierele personale, setările,
modelele, licențele necesare și acest ghid .txt sunt păstrate.
Închide Jarvis, rulează Update.bat, apoi run_windows.bat.

0.3.8c: DOCUMENTATIA MARKDOWN RAMANE PE GITHUB
Instalarea exclude toate fisierele .md livrate de proiect. Ele raman pe GitHub; Jarvis nu are nevoie de ele pentru functionare. Update.bat elimina si copiile vechi nemodificate. Notele personale, documentele modificate, setarile si modelele sunt pastrate. Licentele necesare si acest ghid .txt raman instalate.
Inchide Jarvis, ruleaza Update.bat, apoi run_windows.bat.

0.3.8b: AVATAR FLUID SI INSTALARE CURATA
Avatarul foloseste tema/accentul/fundalul ales si reactioneaza lin la microfon si la redarea efectiva a vocii. Pregatirea silentioasa nu apare ca vorbire. Animatia se opreste cand este ascunsa sau dezactivata.
Testele, fisierele CI si notele de dezvoltare raman pe GitHub si sunt excluse din instalare. Instructiunile utilizatorului raman instalate. Update.bat elimina doar copii vechi recunoscute si nemodificate; pastreaza fisierele personale, setarile, cheile si modelele.
Inchide Jarvis, ruleaza Update.bat, apoi run_windows.bat.

0.3.8a: DESIGN INTEGRAT SI INTERFATA UNIFORMA
Antet integrat cu butoane de fereastra; microfonul mai in stanga, deasupra istoricului. Cercurile ajung la marginile ferestrei fara rama dreptunghiulara. Glisoare fara bordura nativa.
Setari Interfata cu butoane tema/limba, culori accent/fundal, selector personalizat/codhex, procente, comutatoare rotunjite si resetare. Controalele se adapteaza ferestrelor inguste. Autorii mesajelor respecta limba interfetei; in rusa apare Вы (голос). Vocile se numesc Piper si Windows.
Motorul AI local se instaleaza prin instalare/update si se repara automat in fundal la pornire. Butonul manual este eliminat. Modelul GGUF ramane ales de tine, separat de motor.
Instalare: inchide Jarvis, ruleaza Update.bat, apoi run_windows.bat.

0.3.8: COMENZI MULTILINGVE, JOCURI SI INTERFATA
Comenzile RO/RU/EN accepta mai multe formulari politicoase si variante cu/fara diacritice. War Thunder foloseste instrumente locale de pornire/inchidere, cu verificarea ferestrelor si proceselor jocului; Steam ramane deschis. Un joc care cere confirmare sau continua sa ruleze nu este declarat inchis. Testele includ 10-15 formulari per intentie si limba testata, plus negatii si cereri compuse. Recunoasterea vorbirii depinde si de microfon, model si limba Whisper.
Culoarea aleasa se aplica sferei si controalelor. Activitatea este afisata temporar in chat si dispare la terminare. Glisoarele arata procente, iar sectiunea activa din Setari urmareste derularea.
Auto foloseste context trilingv si recunoastere mai precisa, verificate cu Whisper Small si voci sintetice RO/RU/EN. Zgomotul excesiv repetitiv este ignorat. Numele proprii pot ramane dificile; alege Romana pentru vorbire romaneasca si incearca Medium daca Small pierde cuvinte.

RAMAN INCLUSE: UPDATE FARA BACKUPURI PERMANENTE, VOCE SI VERSIUNE
Noul Update.bat se inchide automat dupa succes. Copiile de revenire sunt temporare; backupurile vechi recunoscute ale updaterului se sterg automat. Originalele raman numai daca restaurarea esueaza. Fisierele personale si directoarele legate nu sunt sterse.
Vocea Piper selectata se pregateste silentios pe firul audio la pornire si este refolosita la prima replica. O voce noua necesita descarcarea initiala. Versiunea este afisata sub butonul de restrangere a meniului.
Instalare: inchide Jarvis, ruleaza Update.bat, apoi run_windows.bat. Prima actualizare pornita cu vechiul batch poate cere inca Enter; urmatoarele se inchid automat dupa succes. Erorile raman vizibile.

0.3.7f: CORECTII API SI STABILITATE
Verificarea API respecta timpul ales si repeta o singura data erorile temporare 502/503/504 la acelasi furnizor. HTTP 503 nu inseamna automat cheie gresita. Rezultatele vechi nu mai valideaza setari schimbate intre timp; modelul Gemini verificat este salvat corect. Salvarea automata nu mai redeseneaza intreaga interfata la fiecare editare. Microfonul isi pastreaza identitatea dupa reconectare, iar unmute/undeafen in Discord functioneaza in sensul cerut.
Instalare: inchide Jarvis, ruleaza Update.bat, apoi run_windows.bat. O intrerupere persistenta la furnizor necesita revenirea serviciului.

0.3.7c: SALVARE AUTOMATA A SETARILOR
Butonul albastru «Сохранить настройки» a fost eliminat. Orice modificare a setarilor (comutatoare, liste, glisoare, text) se salveaza si se aplica automat, cu o mica pauza pentru a evita scrierea repetata in timp ce tastezi. Cand pleci din Setari ori inchizi Jarvis, modificarile in asteptare sunt salvate imediat. Cheile API se salveaza dupa finalizarea editarii sau dupa verificarea cheii, nu la fiecare litera. Testele includ paginarea si inchiderea.
Instalare: inchide Jarvis, ruleaza Update.bat si apoi run_windows.bat.

0.3.7b: OCR INTEGRAT, FARA SETARI SUPLIMENTARE
Am eliminat din pagina Setari -> Sistem sectiunea «Встроенный Tesseract OCR», campul pentru calea tesseract.exe, butonul «Обзор» si mesajul de stare de sub sectiune. OCR ramane integrat in Jarvis si se verifica/instaleaza automat, inclusiv modelele rus + eng, la pornire si prin Update.bat. Comenzile OCR nu sunt eliminate. Configuratia locala existenta ramane compatibila.
Pentru instalare: inchide Jarvis, ruleaza Update.bat si apoi run_windows.bat.

0.3.7a: MINI-PATCH PENTRU PAGINA PRINCIPALA
Au fost eliminate doar cele trei butoane suplimentare din «Главная»: «Проверить микрофон», «Посмотреть кнопки на экране», «Пересказать выделенный текст». Functiile nu sunt sterse: testarea microfonului ramane in Setari, iar celelalte doua instrumente raman disponibile prin comenzile Jarvis. Panoul pastreaza comutatoarele, volumul si informatia microfonului.
Instalare: inchide Jarvis, ruleaza Update.bat si redeschide run_windows.bat.

0.3.7: APEL DISCORD DIN PRIMA SI BUTOANELE DIN PANOU
Când recunoașterea vocală scrie «Ханзо», iar numele real de pe Discord este «Hanzo», Jarvis acceptă doar transliterarea complet identică pentru apelurile vocale, apoi verifică în continuare numele real din antetul conversației. Nu schimbă regulile de trimitere a mesajelor și nu acceptă nume asemănătoare.
Cele patru comutatoare din panoul principal răspund acum la primul clic pe întreaga suprafață vizibilă, inclusiv în jumătatea dreaptă. Testele includ evenimente reale de mouse Qt.
Pentru instalare: închide Jarvis, rulează Update.bat, apoi run_windows.bat.

0.3.6: APELURI VOCALE DISCORD DINTR-O COMANDA
Comanda «Позвони Hanzo в Discord» sau «Suna-l pe Hanzo in Discord» deschide automat conversatia privata verificata si apasa o singura data pe telefonul pentru apel vocal, nu pe camera video. Dupa clic, verificarea citeste dintr-o imagine noua starea «apeleaza» sau «apel activ». Daca nu poate confirma destinatarul, pozitia sau starea apelului, nu repeta clicul. Necesita AI online cu imagini si acordul existent pentru capturi.
Instalare: inchide Jarvis, ruleaza Update.bat, apoi run_windows.bat.

0.3.5: CONFIRMAREA CASTILOR DISCORD, STEAM SI GHID PROIECT
Comenzile pentru castile Discord folosesc acum verificarea starii (pictograma barata/nebarata), o singura apasare si o captura noua; daca este neclar, se verifica zona marita. Comanda «Открой Steam и скажи какой у меня там никнейм» este pastrata ca o singura cerere de deschidere si citire a propriului cont. PROJECT_HANDOFF.md documenteaza intregul proiect pentru continuarea in alt chat.
Instalare: inchide Jarvis, ruleaza Update.bat, apoi run_windows.bat.

0.3.4: MICROFON DISCORD SI CONTROL TASTATURA / MOUSE
Pentru microfonul Discord, Jarvis face o captura marita suplimentara si corecteaza pozitia clicului in interiorul butonului. Daca localizarea nu este sigura, nu apasa. Comenzile simple de taste si mouse folosesc direct instrumentele locale Windows, fara planificator AI.
Click pe un utilizator Discord este rutat prin verificarea numelui contactului. Se pastreaza aprobarea pentru capturi trimise online si pentru actiuni cu consecinte importante.
Instalare: inchide Jarvis, ruleaza Update.bat, apoi run_windows.bat.

0.3.3: NUMELE CONTULUI STEAM, FĂRĂ COMENZI PAS CU PAS
Poți spune «Можешь зайти в Steam и сказать какой у меня ник?». Jarvis deschide sau activează automat Steam, cere acordul pentru analiza capturilor de ecran, citește numele utilizatorului conectat din bara contului și îl verifică pe o a doua imagine mărită. Nu citește numele prietenilor sau ale altor utilizatori. Nu este nevoie să dictezi «fă screenshot». Ai nevoie de un AI online cu funcții vizuale și cheie API. Pentru instalare, închide Jarvis, rulează Update.bat și pornește run_windows.bat.

0.3.2: CAPTURI MAI CLARE ȘI CLICURI MAI PRECISE
Captura pentru comenzi vizuale are calitate mai bună. Înainte de clic, Jarvis face o a doua captură la rezoluția reală, mărită pe zona butonului, apoi convertește poziția la coordonatele fizice ale ecranului. Sunt gestionate ferestre mutate, mai multe monitoare și scalarea DPI. Dacă localizările nu coincid sau butonul este acoperit, nu apasă. După clic verifică rezultatul, fără să declare succes doar pentru că a trimis un clic.
Actualizează prin Update.bat din folderul existent, cu Jarvis închis.

0.3.1: PICTOGRAME NOI ȘI COMENZI DISCORD NATURALE
Pictogramele SVG Lucide sunt incluse în proiect și funcționează offline, pe teme deschise/întunecate și ecrane HiDPI. Jarvis are o emblemă nouă pentru fereastră și bara de sistem. Licența ISC este în luxai/assets/icons/lucide/.
Poți spune „Scrie-i lui Hanzo în Discord salut”. Jarvis pregătește singur pașii, verifică destinatarul și arată textul pentru aprobarea finală. Dacă lipsește numele sau mesajul, întreabă și continuă sarcina. Ferestrele ascunse de serviciu nu mai sunt numărate ca ferestre Discord suplimentare vizibile.


Repository: https://github.com/negevshopmd-svg/LuxAI_local

Închide Jarvis, rulează Update.bat din folderul instalat, apoi run_windows.bat.
Actualizatorul descarcă branch-ul main; nu necesită un Release, un tag sau un ZIP
atașat manual. O modificare disponibilă doar într-un PR nu este încă publicată.

Setările, cheile, modelele și mediul .venv sunt păstrate. Copiile de revenire
sunt temporare. La o eroare se încearcă restaurarea automată a codului. Bibliotecile pip
modificate parțial nu pot fi restaurate automat; rulează install_windows.bat
dacă mesajul de eroare cere repararea mediului.

Ghidul complet și istoricul versiunilor sunt pe GitHub:
https://github.com/negevshopmd-svg/LuxAI_local/blob/main/README.md
https://github.com/negevshopmd-svg/LuxAI_local/blob/main/CHANGELOG.md
Nu publica chei sau date personale.

0.3.0 adaugă planificarea pe pași cu observare și verificare: aplicațiile se
deschid mai întâi prin Windows, iar capturile locale nu cer AI. Implicit,
agent_auto_shell: true autorizează CMD/PowerShell pentru sarcina curentă fără
confirmări repetate, cu limite de execuție și verificarea modificărilor prin
citire. Pentru confirmare manuală, setează agent_auto_shell: false în
config.json. Permisiunile Windows și UAC se aplică în continuare.
Capturile către cloud cer acord o dată pe sesiune. Confirmarea trimiterii
mesajelor Discord rămâne separată.

Sunt disponibile operații dedicate pentru cereri explicite de alimentare și
tema Windows. Lumina de noapte deschide Setări Windows, fără să pretindă că
filtrul a fost activat. Pașii și procedurile verificate se păstrează local în
.luxai_data/agent_memory.json; aprobările CMD nu sunt învățate.
