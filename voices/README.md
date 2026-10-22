# Voci neurali locale Piper

Aggiungi qui i modelli vocali Piper. Per ogni voce servono entrambi i file:
- `nome_voce.onnx`
- `nome_voce.onnx.json`

Il modulo `luxai/voices.py` trova automaticamente i modelli validi. Se in `config.json` imposti `"voice_id": "nome_voce"`, quella voce avrà la priorità; altrimenti cerca una voce chiamata `jarvis` e poi usa la prima voce installata.

Se non trova alcun modello valido, al primo răspuns vocal aplicația încearcă să descarce automat vocea neurală masculină rusă **ru_RU-dmitri-medium** din colecția Piper și o salvează local. Este necesară conexiune la internet pentru prima descărcare (modelul poate avea zeci de MB). După instalare, vocea funcționează local. Poți adăuga și alte voci în acest folder.
