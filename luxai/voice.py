import queue, re, time
import numpy as np
import sounddevice as sd
import pyttsx3

def speak(text, enabled=True):
    if not enabled or not text:
        return
    # Keep spoken output short; avoid speaking stack traces/long OCR.
    text = re.sub(r"\s+", " ", str(text)).strip()
    if len(text) > 700:
        text = text[:700] + "…"
    try:
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
        engine.stop()
    except Exception:
        pass

class VoiceListener:
    """Local chunk-based listener. Prefix is checked on recognized text."""
    def __init__(self, model_path="small", prefix_enabled=True, prefix="Jarvis", language="auto"):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(model_path, device="cpu", compute_type="int8")
        self.prefix_enabled = prefix_enabled
        self.prefix = (prefix or "Jarvis").strip().lower()
        self.language = None if language == "auto" else language
        self._stop = False

    def stop(self):
        self._stop = True

    def listen(self):
        sample_rate = 16000
        seconds = 4
        block = int(sample_rate * seconds)
        q = queue.Queue()
        def callback(indata, frames, time_info, status):
            if not self._stop:
                q.put(indata.copy())
        with sd.InputStream(samplerate=sample_rate, channels=1, dtype="float32",
                            blocksize=block, callback=callback):
            while not self._stop:
                try:
                    audio = q.get(timeout=0.5).reshape(-1)
                except queue.Empty:
                    continue
                if float(np.max(np.abs(audio))) < 0.012:
                    continue
                segments, info = self.model.transcribe(audio, language=self.language,
                    beam_size=1, vad_filter=True, condition_on_previous_text=False)
                text = " ".join(s.text.strip() for s in segments).strip()
                if not text:
                    continue
                if self.prefix_enabled:
                    # Require the wake word at the beginning of the recognized chunk.
                    norm = text.lower().strip(" ,.!?:;")
                    prefix = self.prefix
                    if not norm.startswith(prefix.lower()):
                        continue
                    text = norm[len(prefix):].lstrip(" ,.!?:;")
                    if not text:
                        continue
                yield text
