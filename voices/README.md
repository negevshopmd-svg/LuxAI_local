# Voci neurali locale Piper

Aggiungi qui i modelli vocali Piper. Per ogni voce servono entrambi i file:
- `nome_voce.onnx`
- `nome_voce.onnx.json`

Il modulo `luxai/voices.py` trova automaticamente i modelli validi. Se in `config.json` imposti `"voice_id": "nome_voce"`, quella voce avrà la priorità; altrimenti cerca una voce chiamata `jarvis` e poi usa la prima voce installata.

Se non trova alcun modello valido, al primo răspuns vocal aplicația încearcă să descarce automat vocea neurală masculină rusă **ru_RU-dmitri-medium** din colecția Piper și o salvează local. Este necesară conexiune la internet pentru prima descărcare (modelul poate avea zeci de MB). După instalare, vocea funcționează local. Poți adăuga și alte voci în acest folder.

## Built-in voices by language

LuxAI automatically chooses a voice matching the **reply language**:

- Russian (`ru`): **Dmitri**, `ru_RU-dmitri-medium.onnx`
- Romanian (`ro`): **Mihai**, `ro_RO-mihai-medium.onnx`
- English (`en`): **Lessac**, `en_US-lessac-medium.onnx`

To hear a voice, select **Voice Input → Recognition Language**, then go to **Voice Output → Assistant Voice** and click **Preview Voice**. You can also choose Mihai or Lessac directly for the preview, without changing microphone recognition settings.

These official Piper voices download **only on first use**, from [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices). Mihai and Lessac each need approximately **63 MB** plus a small JSON config. An internet connection is required only for the first model download; subsequent playback works offline. New model downloads are size-bounded and SHA-256 verified. The original Russian Dmitri voice continues to work.

The UI language (`ui_language`) is separate from the answer/recognition language (`language`), so changing app labels to Romanian will not silently change the speaker or microphone settings. For reliable language selection, use `ru`, `ro`, or `en` rather than `auto` for voice recognition.
