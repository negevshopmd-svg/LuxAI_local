LUXAI LOCAL 0.3.9.e — ACTUALIZARE 2026-10-30

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
https://github.com/negevshopmd-svg/LuxAI_local/blob/main/README_RO.md
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
