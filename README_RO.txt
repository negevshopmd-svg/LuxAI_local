LUX AI — UPDATER PENTRU GITHUB PUBLIC

Repository configurat:
https://github.com/negevshopmd-svg/LuxAI_local

1. Copiază Update.py și Update.bat în folderul principal al Lux AI.
2. În GitHub, creează un Release cu tag, de exemplu v0.1.0.
3. Atașează la Release un fișier numit EXACT:
   LuxAI_local-update.zip
4. ZIP-ul trebuie să conțină fișierele actualizate direct în rădăcina arhivei,
   nu într-un folder suplimentar.
5. Rulează Update.bat. Verifică versiunea, cere confirmare și face backup
   fișierelor existente pe care urmează să le suprascrie.

IMPORTANT:
- Acesta este un updater inițial generic; testează-l întâi pe o copie a proiectului.
- Păstrează settings.json, .env, modelele și folderele de logs/downloads.
- Nu include secrete în repository-ul public.
- Nu există rollback automat complet dacă Windows blochează un fișier în timpul copierii.
- Creează un Release înainte de prima rulare; simplul commit pe branch nu este Release.
- Fișierul .luxai_update_state.json înregistrează versiunea instalată.
