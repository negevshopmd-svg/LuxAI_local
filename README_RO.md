# LuxAI Local 0.2.0 (Windows 10/11, 64-bit)

Asistent vocal pentru Windows, cu recunoaștere locală și servicii AI opționale:
- microfon pornit la lansare (poate fi oprit din interfață)
- cuvânt de activare configurabil: „Jarvis”
- detectarea limbii automată (română/rusă/engleză, în funcție de modelul Whisper)
- răspuns vocal local
- captură de ecran, OCR opțional și control desktop cu confirmare

## Important
Recunoașterea Whisper, sinteza Piper și OCR rulează local după descărcarea componentelor necesare. Modelul GGUF pentru conversații este opțional; comenzile rapide nu îl cer. Dacă activezi AI cloud, cererile sunt trimise furnizorului ales și pot consuma cotă. Descărcările inițiale și vremea folosesc internetul. Testul de microfon nu salvează și nu trimite înregistrări.

## Instalare

1. Extrage întregul proiect și rulează `install_windows.bat`. Instalatorul caută Python stabil x64 compatibil; mediile Python 3.11–3.14 sunt verificate de CI. Poate instala versiunea oficială de rezervă dacă este necesar.
2. Nu copia `.venv` de pe alt calculator. Instalatorul creează mediul propriu și verifică bibliotecile înainte să raporteze succesul.
3. Opțional, pune un model GGUF multilingv în `models/` și selectează-l din Setări. Motorul `llama-cpp-python` este verificat de instalator; un model poate avea cerințe de RAM prea mari pentru calculatorul tău.
4. Prima utilizare a Whisper poate necesita descărcarea modelului `small`/`medium`. Pentru utilizare complet offline, descarcă modelul în prealabil și indică folderul local prin setările din `config.json` (`whisper_model_path`).
5. Pornește cu `run_windows.bat`.

## Componente
- `faster-whisper`: recunoaștere vocală locală; detectare automată a limbii.
- `llama-cpp-python`: model lingvistic local GGUF.
- `piper-tts`: sinteză vocală locală în română, rusă și engleză; vocile se descarcă la prima folosire.
- `mss`, `Pillow`, `pytesseract`: captură și OCR opțional.
- `pyautogui`: mouse/tastatură.

## Accelerare AMD
Proiectul folosește implicit CPU pentru compatibilitate. Accelerarea AMD depinde de build-ul `llama-cpp-python`/Vulkan instalat și nu este garantată de instalarea standard. Începe cu un model cuantizat mic, potrivit memoriei disponibile. Modelele mari și recunoașterea vocală pe CPU pot răspunde mai lent.

## Siguranță
- Comenzile de sistem sunt allowlist; nu execută shell arbitrar generat de AI.
- Acțiunile obișnuite pot rula imediat. Oprirea calculatorului, scripturile și operațiile riscante cer confirmare; poți activa confirmări și pentru comenzile obișnuite.
- Nu folosi automatizare pentru parole, plăți sau alte acțiuni sensibile.
- OCR Tesseract este instalat automat la `Update.bat` sau `install_windows.bat` într-un folder privat `.luxai_data/ocr/`, împreună cu limbile rusă și engleză. Nu trebuie setată manual calea din `config.json`. Prima instalare necesită internet și poate necesita acordul pentru instalatorul Windows. Aplicația verifică automat OCR la pornire și reîncearcă instalarea dacă este necesar.

## Limite de verificare
Captura și OCR nu oferă înțelegere vizuală completă. Testele automate verifică logica, instalarea și interfața; microfonul fizic, profilul Bluetooth și driverele trebuie verificate pe calculatorul folosit.

## Actualizarea 0.2.0: microfon și căști wireless

Închide Jarvis complet, rulează `Update.bat`, apoi pornește-l cu `run_windows.bat`. Noua versiune adaugă indicator de semnal, stări reale de captură, test de microfon fără Whisper, reîmprospătarea dispozitivelor, repornirea microfonului și salvarea diagnosticului. Modificările sunt descrise în [CHANGELOG.md](CHANGELOG.md).

Dacă apare pornit, dar nu te aude:

1. Deschide **Setări → Intrare vocală → Actualizează dispozitivele**. Pentru căști Bluetooth alege intrarea **Headset / Hands-Free**, nu ieșirea stereo. Pentru căști wireless USB, alege microfonul pe care îl vezi și la intrările de sunet Windows.
2. Apasă **Testează microfonul** și vorbește patru secunde. Nu se încarcă un model AI și nu se salvează înregistrarea. Dacă indicatorul nu se mișcă, verifică butonul Mute, nivelul intrării și permisiunea pentru aplicații desktop: Windows 10 **Settings → Privacy → Microphone**; Windows 11 **Settings → Privacy & security → Microphone**. Închide aplicațiile care folosesc exclusiv microfonul.
3. Dacă testul primește sunet, alege **Română** la limba recunoașterii, salvează setările și apasă **Repornește microfonul**. Încărcarea sau descărcarea inițială Whisper poate dura câteva minute. Indicatorul arată „primește sunet” numai după deschiderea fluxului audio. Un test solicitat în timpul încărcării așteaptă oprirea operației curente.
4. Pentru voce slabă mărește moderat **Sensibilitatea microfonului**. Pentru semnal prea puternic, redu amplificarea microfonului în Windows.
5. **Salvează diagnosticul** dacă problema rămâne. Raportul include dispozitivele, versiunile și ultimul test de microfon; nu include chei API, conversații, înregistrări sau căile modelelor personale. Numele dispozitivelor pot identifica modelul căștilor.

Comutatorul indică setarea cerută; mesajul și nivelul indică starea reală. Testele automate nu pot confirma microfonul fizic și driverele de pe calculatorul tău. La o eroare de actualizare, codul anterior este restaurat automat când este posibil; bibliotecile modificate parțial pot necesita `install_windows.bat`.

## Comenzi vocale complexe cu AI cloud

În versiunea 0.2.0, generatorul de comenzi are un planificator separat pentru macrocomenzi. Spune **„Создай команду”** sau **„Creează o nouă comandă”**, dictează fraza care o va activa, apoi descrie toți pașii (în ordine). De exemplu: **„deschide Notepad, apoi așteaptă 2 secunde, apoi apasă Q W E R D”**. Dacă interpretorul local nu recunoaște întreaga descriere, planificatorul cloud configurat în Setări poate propune acțiuni aprobate. Urmărește previzualizarea pas cu pas și spune „да” / „yes” pentru salvare sau „нет” / „no” pentru a descrie altfel.

O comandă salvată poate avea până la **8 pași**, cu până la **24 de apăsări individuale** într-o singură acțiune „secvență de taste”. Comenzile disponibile includ tastatură, combinații aprobate, mouse, pauze, programe și site-uri. Secvența „qwerd” apasă Q, W, E, R, D *pe rând*, nu introduce un text în câmp. Poți edita și secvența în interfața Comenzi.

Agentul cloud oferă doar propuneri; fiecare pas este validat local și nu se execută la creare. Cererile distructive (de exemplu golirea Coșului de reciclare), scripturile shell, operațiile pe parole și alte acțiuni în afara listei nu sunt generate automat. AI-ul cloud trebuie activat și cheia sa API trebuie să funcționeze. Comenzile locale simple și comenzile deja salvate funcționează fără cloud.

## Dacă Jarvis întrerupe propozițiile sau vorbește prea mult

În **Setări → Intrare vocală → Pauză înainte de încheierea frazei** poți ajusta cât așteaptă Whisper după ultima parte vorbită. Valoarea implicită este **2,3 secunde**; încearcă **3–3,5 secunde** dacă faci pauze când descrii o comandă mai lungă. Setarea nu face aplicația să asculte la nesfârșit: limitele de durată și regulile de securitate rămân active.

Dacă Whisper inventează un mesaj scurt precum „Спасибо за внимание”, LuxAI îl ignoră în loc să îl trateze ca instrucțiune. Când Jarvis **vorbește**, spune clar **„стоп” / „stop” / „oprește-te”** în microfon și redarea Piper sau Windows SAPI va fi oprită; răspunsurile vocale încă neîncepute sunt eliminate din coadă. Monitorizarea acestei comenzi funcționează în timpul redării audio, nu în timpul descărcării sau generării vocii. Folosește căști pentru a reduce ecoul; performanța depinde de microfon și zgomotul de fundal.

## Comenzi vizuale prin AI cloud (captură + coordonate reale)

LuxAI poate acum să combine comenzi Windows și acțiuni asupra elementelor vizibile, precum „deschide Coșul de reciclare”, „apasă de două ori pe butonul de descărcare”, „așteaptă două secunde” și „închide fereastra”. Pentru un control vizual, folosește **Setări → AI online** cu o cheie validă și un model care acceptă imagini (de exemplu, un model compatibil OpenAI/Gemini). Nu toate modelele/providerii oferă analiză vizuală.

Înainte de trimiterea unei capturi, Jarvis cere **permisiunea expresă**, deoarece fereastra poate conține informații personale. Capturează doar fereastra activă externă, verifică titlul/procesul și trimite o fotografie redusă la providerul ales de utilizator. Modelul întoarce poziția aproximativă normalizată; LuxAI o transformă în coordonate absolute folosind rezoluția reală a desktopului și validează punctul. Pentru a preveni clicuri greșite, acțiunea e anulată dacă fereastra s-a schimbat, butonul nu e localizat sau e un dialog protejat. Coordonatele nu sunt alese dintr-o hartă fixă. Fiecare acțiune poate executa **1–10 clicuri** la solicitarea utilizatorului.

Poți spune o comandă directă cu mai mulți pași sau poți crea o comandă vocală reutilizabilă. Pentru Coșul de reciclare, LuxAI folosește operații native Windows, fără să caute pictograma pe desktop. Golirea Coșului șterge ireversibil elementele și necesită confirmare explicită la rulare; Windows poate cere încă o confirmare. Macrocomenzile nu au acces automat la CMD/PowerShell ori la parole. Capturile nu sunt salvate în bibliotecă și nu sunt transmise fără aprobare. Dacă microfonul este în uz și Jarvis devine fereastra activă, activează mai întâi fereastra programului țintă. Ține cont că aplicații cu DPI special, interfețe schimbătoare sau ferestre protejate pot să nu permită localizarea sigură.

## Cercetare și pregătire mesaje Discord prin voce

LuxAI nu mai confundă un rezultat Google din browser cu un utilizator din Discord. Dacă spui „Найди информацию про Adolf Hitler, потом в Discord пользователю ронси отправь информацию”, un flux special caută **un rezumat real din Wikipedia în rusă**, păstrează linkul sursei, găsește aplicația Discord instalată și deschide **Quick Switcher (Ctrl+K, @utilizator)**. Cu acordul tău transmite până la trei capturi ale ferestrei Discord modelului cloud vizual: prima pentru utilizator, a doua pentru editorul de mesaje și a treia, după confirmarea trimiterii, pentru a verifica din nou destinatarul și întregul text nesent. Scrie un **draft**, dar nu îl expediază automat.

Înainte de trimitere, aplicația arată destinatarul, textul și sursa și cere o confirmare suplimentară. Confirmarea expediază prin Enter, dar **nu poate garanta livrarea**. Dacă un utilizator are nume asemănător sau nu apare în rezultatele Discord, Jarvis se oprește, fără clicuri aleatorii. Capturile pot conține conversații private; sunt trimise numai după aprobarea explicită. Sunt necesare aplicația Discord pentru Windows, conexiune la internet și un model cloud capabil să proceseze imagini. Dacă nu reușește să găsească destinatarul, deschide Discord și verifică numele exact, inclusiv literele recunoscute de microfon. Testele automate nu pot verifica contul Discord personal.

## Discord: capturi de ecran, găsirea unui utilizator și rezumat

O comandă vocală precum „жарис открой дискорд потом сделай снимок экрана дискорда после этого найди пользователя октавиан после этого сделай снимок экрана после сделай краткий пересказ этого снимок экрана” este tratată ca **o singură operație cu pași ordonați**, nu ca „arată butoanele ferestrei active”. LuxAI deschide aplicația Discord desktop dacă nu este deja deschisă, salvează local o captură a ferestrei, caută utilizatorul exact prin Quick Switcher (Ctrl+K), verifică vizual identitatea conversației, salvează a doua captură și oferă un rezumat în rusă al informațiilor clar vizibile pe aceasta. **Nu trimite mesaje**.

Înainte de pornire, solicită acordul pentru a transmite până la trei imagini ale Discord către furnizorul AI configurat (rezultatul căutării, verificarea antetului conversației și sumarizarea capturii). Captura inițială este salvată doar local. Fișierele .jpg se păstrează în `Pictures/LuxAI`. Sunt necesare Windows, Discord desktop și AI cloud cu analiză de imagini. Dacă nu poate confirma exact numele utilizatorului sau conținutul capturii, oprește acțiunea fără clicuri suplimentare și fără rezumate inventate. Nu poate confirma conținutul sau identitatea în absența unui test pe contul tău.

### Recunoașterea vocală a contactelor Discord

Comenzile de tipul „Откроете Скопт, потом сделайте снимок экрана, найдите пользователя Старый Бог, после этого в переписке сделайте снимок экрана и сделайте краткое содержимое” sunt păstrate integral, în loc să fie împărțite și trimise chatbotului. Parserul acceptă acum varianta recunoscută greșit „Скопт” numai în contextul clar al unui flux Discord cu captură și conversație și solicită confirmarea că destinația este Discord. Numele afișate formate din mai multe cuvinte (de exemplu „Старый Бог”) rămân un singur destinatar, verificat în captură; dacă apar mai multe rezultate similare, Jarvis nu alege arbitrar și nu trimite mesaje. Dacă aplicația nu poate fi identificată, Jarvis anunță explicit problema fără a executa parțial comanda.

### Corecție pentru „найди там пользователя”

Comanda vocală „жарис открой дискорд сделай снимок экрана найди там пользователя старый бог нажми на него потом сделай еще один снимок экрана потом сделай ей краткое расскажи краткое содержание чата” este recunoscută ca un singur flux Discord. Parserul acceptă adverbe după „найди” (de ex. „там”), păstrează numele „старый бог” fără să includă „нажми на него” în acesta și trimite acțiunea către fluxul verificat vizual, nu către un plan AI incomplet. Capturile către AI necesită în continuare acord, iar fluxul nu trimite mesaje.

### Prioritatea comenzilor existente și microfonul Discord

Comenzile locale cunoscute trebuie executate înaintea planificatorului de macrocomenzi. „Выключи микрофон в Discord” continuă să folosească fluxul existent de confirmare și combinația de taste Ctrl+Shift+M (toggle, nu garanție că microfonul se oprește). Pentru comanda „Сделай снимок экрана и нажми на кнопку микрофона в дискорде”, aplicația folosește un flux separat: confirmare, captură a ferestrei procesului Discord, salvare locală în Pictures/LuxAI, transmiterea unei singure imagini către AI-ul vizual ales și clic numai dacă butonul microfonului este recunoscut fără ambiguitate. Comanda nu este transmisă planificatorului generic; dacă verificarea eșuează, nu se execută niciun clic. Nu trimite mesaje. Clicul schimbă starea microfonului și nu poate garanta oprirea sa.
