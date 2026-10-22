# Voci neurali locale Piper

Aggiungi qui i modelli vocali Piper. Per ogni voce servono entrambi i file:
- `nome_voce.onnx`
- `nome_voce.onnx.json`

Il modulo `luxai/voices.py` trova automaticamente i modelli validi. Se in `config.json` imposti `"voice_id": "nome_voce"`, quella voce avrà la priorità; altrimenti cerca una voce chiamata `jarvis` e poi usa la prima voce installata.

La cartella può contenere più voci e sarà possibile aggiungere in futuro un selettore nell'interfaccia. I modelli vocali non sono inclusi nel repository: scegli e scarica un modello Piper compatibile con la lingua desiderata dalla raccolta ufficiale Piper.
