# Lux AI Local (Windows 10)

Prototip Python pentru un asistent local, cu setările inițiale:
- microfon pornit la lansare (poate fi oprit din interfață)
- prefix activ: „Jarvis”
- detectarea limbii automată (română/rusă/engleză, în funcție de modelul Whisper)
- răspuns vocal local
- captură de ecran, OCR opțional și control desktop cu confirmare

## Important
Acesta este un prototip funcțional de bază, nu o clonă completă a Luxify Pro. Modelul lingvistic și modelul Whisper trebuie descărcate/configurate separat. Nu trimite date la servicii online, dar unele componente au nevoie de internet la instalare/descărcarea modelelor. După instalare și descărcare, funcțiile locale pot rula offline.

## Instalare

1. Instalează Python 3.11 x64.
2. Deschide folderul proiectului și rulează `install_windows.bat`.
3. Descarcă un model GGUF multilingv (de exemplu un model instruct de 3B–8B cuantizat) și selectează fișierul `.gguf` în aplicație.
4. Prima utilizare a Whisper poate necesita descărcarea modelului `small`/`medium`. Pentru utilizare complet offline, descarcă modelul în prealabil și indică folderul local prin setările din `config.json` (`whisper_model_path`).
5. Pornește cu `run_windows.bat`.

## Componente
- `faster-whisper`: recunoaștere vocală locală; detectare automată a limbii.
- `llama-cpp-python`: model lingvistic local GGUF.
- `pyttsx3`: sinteză vocală locală (vocile instalate în Windows).
- `mss`, `Pillow`, `pytesseract`: captură și OCR opțional.
- `pyautogui`: mouse/tastatură.

## Accelerare AMD
Proiectul pornește implicit cu CPU pentru compatibilitate. Accelerarea AMD depinde de build-ul `llama-cpp-python`/Vulkan instalat. Nu este garantată de instalarea standard pip. Pe GPU-ul tău cu 8 GB VRAM, începe cu un model GGUF de 3B–8B în cuantizare Q4; dacă este lent, folosește un model mai mic sau activează un build Vulkan compatibil.

## Siguranță
- Comenzile de sistem sunt allowlist; nu execută shell arbitrar generat de AI.
- Acțiunile de click/tastare sunt limitate și necesită confirmare în interfață.
- Nu folosi automatizare pentru parole, plăți sau alte acțiuni sensibile.
- OCR Tesseract este instalat automat la `Update.bat` sau `install_windows.bat` într-un folder privat `.luxai_data/ocr/`, împreună cu limbile rusă și engleză. Nu trebuie setată manual calea din `config.json`. Prima instalare necesită internet și poate necesita acordul pentru instalatorul Windows. Aplicația verifică automat OCR la pornire și reîncearcă instalarea dacă este necesar.

## Ce urmează
Acest starter oferă fundația. Analiza vizuală semantică reală necesită și un model multimodal local compatibil; deocamdată vederea e captură + OCR, nu „înțelegere vizuală” completă.
# Actualizarea 0.2.0: microfon și căști wireless

Închide Jarvis complet, rulează `Update.bat`, apoi pornește-l cu `run_windows.bat`. Noua versiune adaugă indicator de semnal, stări reale de captură, test de microfon fără Whisper, reîmprospătarea dispozitivelor, repornirea microfonului și salvarea diagnosticului. Modificările sunt descrise în [CHANGELOG.md](CHANGELOG.md).

Dacă apare pornit, dar nu te aude:

1. Deschide **Setări → Intrare vocală → Actualizează dispozitivele**. Pentru căști Bluetooth alege intrarea **Headset / Hands-Free**, nu ieșirea stereo. Pentru căști wireless USB, alege microfonul pe care îl vezi și la intrările de sunet Windows.
2. Apasă **Testează microfonul** și vorbește patru secunde. Nu se încarcă un model AI și nu se salvează înregistrarea. Dacă indicatorul nu se mișcă, verifică butonul Mute, nivelul intrării și permisiunea pentru aplicații desktop: Windows 10 **Settings → Privacy → Microphone**; Windows 11 **Settings → Privacy & security → Microphone**. Închide aplicațiile care folosesc exclusiv microfonul.
3. Dacă testul primește sunet, alege **Română** la limba recunoașterii, salvează setările și apasă **Repornește microfonul**. Încărcarea sau descărcarea inițială Whisper poate dura câteva minute. Indicatorul arată „primește sunet” numai după deschiderea fluxului audio. Un test solicitat în timpul încărcării așteaptă oprirea operației curente.
4. Pentru voce slabă mărește moderat **Sensibilitatea microfonului**. Pentru semnal prea puternic, redu amplificarea microfonului în Windows.
5. **Salvează diagnosticul** dacă problema rămâne. Raportul include dispozitivele, versiunile și ultimul test de microfon; nu include chei API, conversații, înregistrări sau căile modelelor personale. Numele dispozitivelor pot identifica modelul căștilor.

Comutatorul indică setarea cerută; mesajul și nivelul indică starea reală. Testele automate nu pot confirma microfonul fizic și driverele de pe calculatorul tău. La o eroare de actualizare, codul anterior este restaurat automat când este posibil; bibliotecile modificate parțial pot necesita `install_windows.bat`.
