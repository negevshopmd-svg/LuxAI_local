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
