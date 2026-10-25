LUXAI LOCAL 0.3.7 — ACTUALIZARE

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

Setările, cheile, modelele și mediul .venv sunt păstrate. Fișierele înlocuite au
backup. La o eroare se încearcă restaurarea automată a codului. Bibliotecile pip
modificate parțial nu pot fi restaurate automat; rulează install_windows.bat
dacă mesajul de eroare cere repararea mediului.

Pentru microfon, căști wireless, instalare și diagnostic, deschide README_RO.md.
Lista modificărilor este în CHANGELOG.md. Nu publica chei sau date personale.

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
