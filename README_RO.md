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
- Pentru OCR, instalează Tesseract separat și setează calea lui în `config.json`.

## Ce urmează
Acest starter oferă fundația. Analiza vizuală semantică reală necesită și un model multimodal local compatibil; deocamdată vederea e captură + OCR, nu „înțelegere vizuală” completă.
