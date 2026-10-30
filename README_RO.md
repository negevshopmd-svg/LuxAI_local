# LuxAI Local 0.9.3.c (Windows 10/11, 64-bit)

## 0.9.3.c: atașamente prin Ctrl+V și comenzi de bază editabile (2026-10-30)

Chatul afișează miniaturi foto și carduri compacte de fișiere deasupra textului, cu eliminare individuală. Butonul **+** rămâne jos în stânga, iar **Trimite** în dreapta. Poți lipi cu **Ctrl+V** fișiere copiate din Explorer și imagini copiate în clipboard; textul obișnuit se lipește ca text. Lipirea creează doar previzualizări locale. Cu AI cloud activ, fișierele se partajează cu furnizorul configurat abia la **Trimite**.

Comenzile de bază pot fi redactate, salvate, dezactivate și șterse. Modificările persistă în biblioteca personală și se păstrează la repornire și actualizare. Meniul cu trei puncte urmează referința Luxify: deschidere, adăugare frază obligatorie/opțională, activare/dezactivare, clonare, copiere, copiere JSON și ștergere. Eliminarea unui folder personal păstrează comenzile din el. Datele copiate sau importate rămân validate și nu sunt executate automat.

Închide Jarvis, rulează `Update.bat`, apoi `run_windows.bat`. Setările, modelele și fișierele personale rămân păstrate; Markdown și testele proiectului rămân pe GitHub.

## 0.3.9b: corecții după testele de interfață (2026-10-29)

- **Chat:** casetă compactă gri-închis, cu mesaje pe mai multe rânduri, atașamente **deasupra textului** și butoanele **+** și **Trimite** la baza casetei. Enter trimite, Shift+Enter inserează un rând nou.
- **Comenzi:** butoane de creare a comenzilor/folderelor/colecțiilor și import/export JSON în **dreapta**. Comenzile predefinite se află într-un arbore separat; acțiunile de deschidere, editare, duplicare, activare și ștergere apar la hover, clic dreapta sau butonul cu trei puncte al comenzii, nu în bara din dreapta.
- **Foldere:** persistă între actualizări; poți muta comenzile personale în ele din meniul contextual. Importul validează comenzile și le dezactivează inițial, fără execuție automată; exportul conține numai comenzile personale.
- **Editor:** două coloane, cu verificarea și **Salvează/Anulează** în dreapta, fără bara laterală suplimentară inutilă. Declanșatoarele de voce și tastatură sunt pe același rând.
- **Înregistrare:** panoul Stop/Anulează este acum un dialog modal independent, nu un panou blocat de dialogul editorului; ferestrele se minimizează în timpul capturării și se restaurează la oprire.

Acestea sunt schimbări reale de layout și funcționalitate. Capturile Luxify reprezintă referințe vizuale, nu codul sursă sau inventarul complet al produsului respectiv; funcționarea hook-urilor globale trebuie verificată și pe PC-ul tău.

## 0.3.9a: interfață chat și comenzi apropiată de Luxify (2026-10-28)

Chatul folosește o singură casetă cu **+** în stânga jos, fișiere atașate în interior și butonul de trimitere în dreapta. Mesajul despre partajarea în cloud apare când există atașamente. Comenzile de bază sunt într-un modul separat, `luxai/default_commands.py`, și într-un folder **Comenzi implicite**; cele personale rămân separate și se păstrează la actualizare. Panoul de gestionare este reorganizat. Editorul are bară de navigare și pictograme de informație care afișează explicații la hover sau clic.

Comenzile personale și înregistrarea nu mai au limita fixă de 8 acțiuni. La pornirea înregistrării, ferestrele Jarvis sunt minimizate, iar un panou separat **Stop și adaugă / Anulează** rămâne accesibil. După oprire, editorul revine. Fiecare acțiune rămâne validată, iar operațiile riscante necesită confirmare. Funcționarea hook-urilor native și aspectul exact trebuie verificate pe PC-ul utilizatorului.

## 0.3.9: fișiere în chat și editor complet de comenzi — 2026-10-28

Apasă **Atașează** sau trage fișierele în chat, scrie cererea și apasă **Trimite**. Sunt acceptate texte, cod, CSV, JSON, Markdown, PDF, DOCX și fotografii. Selectarea și previzualizarea sunt locale. Dacă AI cloud este activ, trimiterea partajează fișierele selectate cu furnizorul configurat; analiza imaginilor necesită un model care acceptă imagini. Procesarea locală folosește textul documentelor și OCR pentru imagini, fără analiză vizuală locală. Limite: 8 fișiere, 10 MB fiecare și 20 MB în total per mesaj.

Pentru modificări cerute, Jarvis propune o variantă de verificat. Compară originalul, diferențele și textul nou înainte de **Aplică** sau **Salvează o copie**. Fișierele text și modificările DOCX compatibile, cu aceeași structură de paragrafe, pot fi aplicate după verificarea că originalul nu s-a schimbat; copia de rezervă rămâne în `.luxai_data/file_edits`. Modificările PDF sau DOCX care schimbă structura se exportă ca o copie text, fără rescrierea originalului. Codul atașat este citit, nu executat.

Editorul **Comenzi** grupează frazele, cuvintele opționale, declanșatoarele și acțiunile ordonate. Poți adăuga voce, combinație de taste, programare ori evenimente de pornire a aplicațiilor/conectare a căștilor. Înregistrează acțiuni Windows acceptate sau cere AI să propună pași, apoi verifică-i. Înregistrarea literelor/cifrelor necesită activare explicită și funcționează doar în Dota 2, Counter-Strike 2, War Thunder și Undertale. **Verificarea frazei** nu execută nimic; **Execută acum** rulează varianta verificată. Sunt disponibile până la 8 acțiuni, confirmarea întregii comenzi și înlănțuirea. Programările, evenimentele și tastele globale funcționează numai cât timp Jarvis rulează. Înregistrarea și comenzile native Windows necesită verificare pe calculatorul țintă.

Meniul lateral își păstrează starea restrânsă. Cardurile Captură de ecran și OCR au fost eliminate din **Instrumente**; comenzile existente și instalarea automată OCR rămân disponibile. Interfața RU/EN/RO păstrează exact numele personale, frazele și conținutul documentelor.

Închide Jarvis, rulează `Update.bat`, apoi `run_windows.bat`. Setările, modelele și fișierele personale sunt păstrate. Toate fișierele `.md` livrate și testele rămân doar pe GitHub; ghidul `README_RO.txt` și licențele necesare rămân instalate.

## 0.3.8c: documentația Markdown rămâne doar pe GitHub

Toate fișierele `.md` livrate de proiect, inclusiv README, ghidurile și istoricul versiunilor, sunt excluse din instalare și rămân pe GitHub. Jarvis nu are nevoie de ele pentru funcționare. `Update.bat` elimină și copiile nemodificate livrate de versiunile vechi. Documentele personale, copiile modificate, setările și modelele sunt păstrate. Licențele necesare și ghidul `README_RO.txt` rămân instalate.

Închide Jarvis, rulează `Update.bat`, apoi `run_windows.bat`.

## 0.3.8b: avatar fluid și instalare curată

Avatarul din dreapta se mișcă fluid și folosește tema, accentul și fundalul ales. Inelele reacționează la nivelul microfonului și afișează un val distinct în timpul redării vocii. Pregătirea silențioasă a vocii nu declanșează reacția de vorbire. Animația se oprește când este dezactivată sau pagina nu este vizibilă.

Instalarea exclude testele, fișierele CI și documentația de dezvoltare; acestea rămân pe GitHub. Instrucțiunile pentru utilizator rămân instalate. Update-ul curăță copiile vechi recunoscute numai dacă nu au fost modificate și păstrează fișierele personale, setările, cheile și modelele. Închide Jarvis, rulează `Update.bat`, apoi `run_windows.bat`.

## 0.3.8a: design integrat și setări reorganizate

Bara Windows separată este înlocuită de un antet cu mutare, redimensionare și butoane de minimizare/maximizare/închidere. Microfonul este mai în stânga, deasupra istoricului. Cercurile din dreapta ajung la marginile ferestrei, cu margine stângă curbată și transparentă. Glisoarele nu mai au rama nativă.

Setările Interfeței au butoane pentru temă și limbă, mostre de culori pentru accent/fundal, selector personalizat și cod hexazecimal, procente, comutatoare rotunjite și resetare. În ferestre înguste, controalele se așază sub explicații. Autorii mesajelor urmează limba interfeței, inclusiv în istoricul existent: în rusă apare **Вы (голос)**. Preferințele vocale rămân separate. Furnizorii se numesc **Piper** și **Windows**.

Motorul AI local este pregătit automat de instalator/update și reparat în fundal la pornire dacă lipsește. Butonul manual a fost eliminat. Motorul este separat de modelul `.gguf`, ales potrivit memoriei disponibile. Închide Jarvis, rulează `Update.bat`, apoi `run_windows.bat`.

## 0.3.8: comenzi multilingve, jocuri și interfață corectată

Comenzile românești, rusești și englezești acceptă mai multe formulări politicoase, forme verbale și variante cu/fără diacritice. War Thunder și celelalte jocuri Steam recunoscute folosesc direct instrumentele locale pentru pornire și închidere. Închiderea verifică ferestrele/procesele jocului și păstrează Steam deschis; dacă jocul cere confirmare sau rămâne pornit, rezultatul nu este declarat reușit. Testele includ 10–15 formulări pentru fiecare intenție și limbă testată, plus negații și cereri compuse. Acuratețea vorbirii depinde în continuare de microfon, modelul Whisper și limba recunoașterii, separată de limba interfeței.

Culoarea aleasă se aplică și sferei, comutatoarelor și celorlalte controale. Activitatea curentă apare temporar în chat și dispare după terminare. Glisoarele afișează procentele, iar meniul secțiunilor din Setări urmărește derularea.

Recunoașterea Auto folosește context trilingv și o căutare mai precisă. Acest lucru a îmbunătățit comenzile românești scurte în probe locale Whisper Small cu vorbire sintetizată RO/RU/EN, cu un mic cost de timp. Transcrierile excesiv de repetitive produse de zgomot sunt ignorate. Numele proprii și titlurile în altă limbă pot fi recunoscute diferit; pentru vorbire românească poți alege explicit Română și modelul Medium dacă Small pierde cuvinte.

Rămân incluse toate îmbunătățirile actualizatorului și vocii. După un update reușit, noul `Update.bat` se închide automat. Fișierele necesare revenirii în caz de eroare sunt temporare și dispar după terminare. Backupurile vechi recunoscute ca aparținând updaterului și copia sa de pornire se șterg automat după succes, inclusiv dacă versiunea era deja actuală. Fișierele fără legătură cu updaterul sunt păstrate. Numai o restaurare eșuată păstrează originalele pentru recuperare.

Vocea Piper aleasă este încărcată și pregătită în fundal imediat la pornirea Jarvis, fără salut automat sau înregistrare. Prima replică folosește aceeași instanță pregătită. La prima instalare a unei voci lipsite, descărcarea rămâne necesară; motorul Windows SAPI păstrează comportamentul existent. Versiunea instalată apare cu text mic sub „Свернуть”, inclusiv în meniul restrâns.

Închide Jarvis, rulează `Update.bat`, apoi `run_windows.bat`. Prima trecere de la fișierul batch vechi poate cere încă Enter la pauza deja citită de Windows; următoarele actualizări reușite se închid automat. Erorile rămân vizibile pentru diagnosticare.

## Patch 0.3.7f: conexiune API și setări stabile

Verificarea API respectă timpul de așteptare ales și repetă o singură dată cererile cu HTTP 502/503/504, către același furnizor. HTTP 503 indică indisponibilitatea temporară a serviciului; nu dovedește că cheia este greșită. Rezultatele vechi nu mai pot valida o altă cheie, adresă sau model schimbat între timp. Dacă testul Gemini găsește un model funcțional, îl salvează înainte să afișeze conexiunea ca activă.

Salvarea automată nu mai redesenează întreaga interfață la modificări fără legătură cu aspectul. Se păstrează identitatea microfonului după reconectare, iar „unmute/undeafen” în Discord nu mai este interpretat invers. Închide Jarvis, rulează `Update.bat`, apoi `run_windows.bat`. Dacă furnizorul continuă să răspundă cu 503, trebuie să își revină serviciul; o cheie nouă nu repară această eroare.

## Patch 0.3.7e: microfoane fără dubluri

Lista din **Setări → Intrare vocală → Microfon** afișează fiecare intrare audio o singură dată, cu nume simplu, similar Discord. Nu mai repetă variantele MME, DirectSound, WASAPI și WDM-KS. În Windows folosește prioritar WASAPI, cu alternativă dacă aceasta lipsește. Se păstrează selectarea microfonului existent când identitatea poate fi recunoscută fără ambiguitate. Scanarea listei nu salvează accidental setările. Închide Jarvis, rulează `Update.bat`, apoi `run_windows.bat`.



## Patch 0.3.7d: setări salvate automat

Orice modificare obișnuită din **Setări** se salvează și se aplică automat după o pauză scurtă (550 ms), fără butonul „Сохранить настройки”. Modificările nesalvate se aplică și la navigarea spre altă pagină ori la închiderea Jarvis. Cheile API sunt salvate numai după terminarea editării sau după un test API reușit, nu cât timp încă tastezi. Pentru a vedea interfața nouă, **închide complet Jarvis**, rulează `Update.bat`, apoi pornește-l cu `run_windows.bat`. O fereastră rămasă deschisă continuă să afișeze interfața versiunii vechi.



Asistent vocal pentru Windows, cu recunoaștere locală și servicii AI opționale:
- microfon pornit la lansare (poate fi oprit din interfață)
- cuvânt de activare configurabil: „Jarvis”
- detectarea limbii automată (română/rusă/engleză, în funcție de modelul Whisper)
- răspuns vocal local
- captură de ecran, OCR opțional și control desktop cu confirmare

## 0.3.1: pictograme noi și comenzi Discord naturale

Pictogramele din meniuri, comenzi, setări și dialoguri folosesc acum SVG-uri Lucide incluse în proiect, cu aceeași formă pe Windows 10/11 și culori adaptate temei. Jarvis are și o emblemă nouă pentru fereastră și bara de sistem. Pachetul funcționează offline; licența ISC și sursa sunt în `luxai/assets/icons/lucide/`.

Poți spune **„Scrie-i lui Hanzo în Discord salut”** sau **„А ты можешь написать в дискорде пользователю Hanzo привет”**. Jarvis construiește pașii de deschidere, alegere a contactului, pregătire și trimitere. Dacă lipsește numele sau mesajul, întreabă și continuă sarcina. Destinatarul este verificat, iar textul pregătit este arătat pentru aprobarea finală. Ferestrele ascunse de serviciu ale Discord nu mai sunt tratate ca aplicații suplimentare deschise.

## 0.3.0: sarcini adaptive și verificarea rezultatului

Jarvis alege un instrument, observă rezultatul real, ajustează pasul următor și verifică dacă cererea a fost îndeplinită. **„Deschide Discord”** caută și deschide aplicația prin Windows înainte de a folosi capturi; nu cere AI cloud. Deschiderea este confirmată după găsirea unei ferestre vizibile în prim-plan, nu doar a procesului `Discord.exe`. **„Fă o captură de ecran”** salvează local în `Pictures/LuxAI`, fără cheie API.

Pentru sarcini necunoscute activează AI-ul cloud configurat. El poate propune acțiuni în aplicații, analiză vizuală, cercetare și comenzi locale CMD/PowerShell. Executorul local verifică fiecare propunere. Implicit, `agent_auto_shell: true` autorizează comenzile necesare sarcinii curente fără confirmări repetate; execuția rămâne limitată, iar comenzile care modifică starea cer verificarea rezultatului prin citire. Pentru aprobare manuală la fiecare comandă din afara listei de citire, setează `agent_auto_shell: false` în `config.json`. Autorizarea vine din setarea ta, se aplică sarcinii curente și nu ocolește permisiunile Windows sau UAC. Trimiterea mesajelor Discord își păstrează confirmarea separată. Pentru capturi trimise către AI se cere acord o singură dată pe sesiune Jarvis; capturile locale nu cer acord pentru încărcare.

Cererile explicite de oprire, repornire, repaus, blocare și schimbare a temei Windows folosesc operații locale dedicate. Oprirea și repornirea au un interval pentru anulare și nu forțează închiderea aplicațiilor. Pentru **Lumina de noapte**, instrumentul nativ deschide pagina din Setări Windows. Cu AI vizual activ și acordul de sesiune pentru capturi, Jarvis poate continua prin interfață și verifică starea butonului; deschiderea paginii singură nu confirmă activarea filtrului. Pentru **„modul de noapte”** întreabă dacă dorești tema întunecată, Lumina de noapte sau repaus.

Pașii, răspunsurile la întrebări și procedurile cu rezultat verificat se păstrează local în `.luxai_data/agent_memory.json`. Procedura reținută ajută la următoarea cerere, dar rezultatul se verifică din nou. Aprobările CMD, comenzile brute, capturile și înregistrările nu devin proceduri reutilizabile. Dacă un clic s-a executat, dar efectul nu poate fi confirmat, Jarvis anunță acest lucru și nu repetă automat clicul.

Închide Jarvis înainte de actualizare. `Update.bat` descarcă branch-ul `main`; modificările aflate doar într-un branch sau PR ajung în actualizator după integrare. Detaliile sunt în [CHANGELOG.md](CHANGELOG.md).

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
- `llama-cpp-python`: motor pentru rularea modelelor locale GGUF.
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

### Testele de control vizual și găsirea contactelor Discord (octombrie 2026)

Comenzile cu Calculator (deschide + pauză + 1–6 clicuri pe cifre/operatori), Steam (Bibliotecă) și informații despre ecran + deplasare mouse la coordonate exacte + clic dreapta sunt acum recunoscute ca secvențe complete validate local, nu ca răspunsuri incomplete ale planificatorului cloud. Clicurile vizuale implică o captură nouă, acord explicit pentru transmiterea imaginii și verificarea ferestrei înainte de acționare. Comenzile necunoscute folosesc în continuare planificatorul general; nu sunt inventate coordonate.

Pentru fluxul Wikipedia → Discord, Jarvis analizează mai întâi captura listei de conversații. Dacă persoana nu este vizibilă, încearcă Ctrl+K cu textul dictat și, pentru un nume dictat în chirilică, o căutare suplimentară cu un prefix latin. Nu presupune că un nume latin (de exemplu `RONfsy`) corespunde automat celui dictat (`ронси`). Dacă numele vizibil diferă, cere **o confirmare distinctă a identității** înainte de orice clic sau completare a mesajului. După aceasta, verifică din nou antetul conversației și la trimitere verifică încă o dată destinatarul și textul integral. Într-un traseu cu căutări alternative pot fi transmise până la cinci capturi furnizorului AI, numai cu acordul utilizatorului. Nicio expediere fără confirmarea finală.

### Corecție verificare finală Discord (linkuri Wikipedia lungi)

La ultimul pas Wikipedia → Discord, mesajele cu URL-uri lungi codificate procentual puteau fi respinse de AI-ul vizual chiar dacă au fost introduse în editor. După aprobarea explicită a mesajului, Jarvis face o captură proaspătă și verifică exact **numele din antetul conversației individuale** și localizarea editorului de mesaje. Nu mai cere AI-ului să citească fiecare caracter al linkului din imagine. După verificarea vizuală, selectează conținutul editorului și îl **înlocuiește** prin tastare Unicode nativă cu textul exact pe care utilizatorul l-a aprobat, apoi cere sistemului să execute Enter. Această înlocuire este explicată în dialogul final. Nu accesează clipboardul. Dacă identitatea, editorul, fereastra activă sau tastarea nu pot fi verificate, nu apasă Enter. Livrarea nu poate fi garantată fără verificare în Discord.

### Comenzi vocale Discord, verificarea acțiunilor și capturi fără confirmări repetate

Comenzile locale au prioritate în fața scurtăturilor învățate: inclusiv `Выключу микрофон в дискорде` este recunoscut ca cerere de comutare a microfonului, nu doar de deschidere a Discord. Comanda `Нажми в Дискорд на пользователя Старый Бог` caută un utilizator vizibil, apoi prin Ctrl+K dacă este necesar, și verifică dacă antetul conversației individuale s-a deschis. Dacă primul clic doar închide căutarea, o nouă captură identifică utilizatorul înainte de un al doilea clic. Nu introduce și nu trimite mesaje.

Capturile salvate **local** nu necesită confirmări. Pentru trimiterea de capturi către AI-ul extern, se cere consimțământ o singură dată **per sesiune Jarvis**; dacă accepți, toate acțiunile vizuale ulterioare din acea sesiune pot trimite imagini furnizorului AI configurat. Consimțământul expiră la închiderea aplicației. Trimiterea mesajelor Discord și acțiunile cu risc păstrează propriile confirmări.

Secvența „размер экрана → перемести мышь на координаты 400,300 → подожди 2 секунды → правая кнопка мыши” folosește executorul local verificat al sistemului. Pentru „Найди в интернете три факта про Марс, открой Блокнот, напиши их, выдели весь текст и скопируй” există un flux separat: cere extrase textuale din Wikipedia, selectează trei propoziții complete fără inventarea faptelor, focalizează explicit procesul Notepad înainte de tastare și folosește Ctrl+A/Ctrl+C doar după verificarea ferestrei. Dacă sursa nu conține trei propoziții potrivite, operația se oprește explicând limita.

Comenzile de tip „caută în browser, deschide Notepad și tastează un text literal” verifică acum că Notepad, nu pagina browserului, deține fereastra activă înainte de tastare.

### Discord: «нажми на кнопку микрофона чтобы его выключить»

Formularea „Зайди в Discord и нажми на кнопку микрофона чтобы его выключить” este o comandă **vizuală** chiar dacă nu este menționat „снимок экрана”. Jarvis localizează butonul real din colțul stânga-jos al ferestrei Discord, citește starea dintr-o captură nouă și **nu apasă** dacă microfonul apare deja dezactivat. Dacă apare activ, apasă o singură dată și analizează o altă captură pentru confirmare. Dacă imaginea nu permite distingerea stării, se oprește fără un clic riscant. Nu folosește Ctrl+Shift+M pentru această comandă.

Comenzile „нажми на кнопку ... чтобы включить” folosesc aceeași verificare inversă. Comenzile care cer doar „нажми на кнопку микрофона” fără stare explicită păstrează comportamentul de **toggle** cu verificare ulterioară. Comanda simplă „выключи микрофон в Discord”, fără cerința de clic vizual, păstrează scurtătura existentă cu avertisment că poate comuta în ambele direcții.

### Planificare adaptivă și Discord fără clicuri presupuse

LuxAI nu mai presupune că o comandă necunoscută trebuie să aibă o rețetă fixă scrisă în cod. AI-ul cloud poate alege o secvență din catalogul acțiunilor disponibile. Dacă propune o secvență incompletă sau nesigură, primește feedback de la validator și **mai poate încerca o singură dată** să o corecteze. Niciun pas respins nu este executat. Acest lucru este planificare adaptivă la execuție, **nu antrenarea autonomă a modelului** sau instalarea unor capabilități arbitrare.

Comenzile Discord de tipul „нажми в Дискорде на пользователя Ханзу, потом напиши ему привет и нажми Enter” pot fi interpretate de model ca o singură acțiune `discord_send_text`, dacă numele și textul propuse există în transcrierea utilizatorului. Jarvis caută mai întâi contactul vizibil, apoi folosește căutarea Discord dacă e necesar. **Înainte de a scrie orice text în căutare**, trebuie să vadă pe o captură nouă fereastra Ctrl+K și să localizeze câmpul popup, nu editorul conversației. Dacă popup-ul nu apare, textul nu se tastează. După deschiderea conversației verifică antetul activ, pregătește exact mesajul dictat și cere confirmare separată înainte de trimitere. Un nume posibil confundat sau transliterat necesită aprobarea utilizatorului; nu presupune identitatea persoanei pe baza unui avatar.

Acțiunile și validările rămân limitate la catalogul aprobat. Acțiunile noi care nu au instrument implementat pot necesita încă dezvoltare. Nu se execută cod inventat de model, nu se trimite un mesaj fără verificarea și acordul final.

### Agent vizual nou: observă → raționează → acționează → verifică

Pentru cererile noi de interacțiune cu ferestre și controale grafice, Jarvis folosește un **ciclu de observare** printr-un model cloud cu suport pentru imagini: captură reală a ferestrei → alege o singură acțiune permisă → localizează controlul independent pe aceeași captură → clic o singură dată → captură nouă → decide dacă scopul este atins sau ce trebuie corectat. Păstrează un istoric scurt al încercărilor în cadrul comenzii. Un al doilea apel vizual trebuie să confirme rezultatul înainte să spună că obiectivul a fost îndeplinit. Nu repetă în orb același buton dacă primul clic pare ratat. Cel mult 6 acțiuni și 9 observații per cerere.

Feedbackul de tip „ты не попал, давай заново” reia **ultimul obiectiv vizual** (din cel mult 10 minute), folosind o captură nouă, fără a repeta coordonatele vechi. Este o corecție pe termen scurt a procesului, nu un antrenament permanent de greutăți ale rețelei.

**Protecții:** nu execută cod generat de model; nu trimite mesaje, nu șterge fișiere, nu plătește și nu interacționează cu parole prin agentul vizual general. Pentru mesaje Discord rămâne fluxul separat cu verificare de contact și confirmare înainte de trimitere. Doar aplicațiile și acțiunile din instrumentele locale controlate pot fi accesate. Capturile private pot merge la cloud doar după acordul utilizatorului, valabil până la închiderea aplicației. Dacă nu poate verifica rezultatul, se oprește și spune explicit acest lucru.

**Limitări:** identificarea din imagini depinde de modelul vizual selectat și de tema ferestrei (ex. Discord personalizat). „Gândirea” constă în planificarea următorului pas din observații și feedback, nu auto-modificarea codului sau dezvoltarea autonomă de unelte noi.

### Discord în fundal ≠ fereastră vizibilă

Un proces `Discord.exe` pornit NU mai este raportat ca „Discord deschis”. Jarvis verifică HWND-ul ferestrei reale, inclusiv când este ascuns în tray, minimizat sau are coordonate în afara desktopului virtual. Încearcă să-l restaureze și să-l focalizeze; numai după ce este vizibil în dreptunghiul ecranului și activ raportează reușita. Dacă Discord rulează doar ca proces în tray, încearcă protocolul `discord://` și re-verifică fereastra, fără să presupună succesul. Repetarea comenzii de deschidere focalizează aceeași fereastră, nu lansează o copie nouă. Comanda de corecție „он запущен но окно же не открыто” reactivează fereastra Discord dacă ultima sarcină vizuală privea Discord; **nu repetă un mesaj** din cererea precedentă.

Cererile de tip „зайди в Discord и напиши пользователю Старый Бог привет и нажми Enter” sunt recunoscute ca **intenții de mesaj**, nu reduse la lansarea aplicației. Fluxul verifică destinatarul și cere aprobare pentru text înainte să îl expedieze. Dacă un model returnează doar `open_app`, acel plan este respins ca incomplet.
