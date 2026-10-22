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
    """Fast local speech capture: collect speech until 5 seconds of silence, then transcribe once."""
    def __init__(self, model_path="tiny", prefix_enabled=True, prefix="Jarvis", language="auto"):
        from faster_whisper import WhisperModel
        import os
        self.model = WhisperModel(
            model_path or "tiny",
            device="cpu",
            compute_type="int8",
            cpu_threads=max(2, min(8, os.cpu_count() or 4)),
            num_workers=1,
        )
        self.prefix_enabled = prefix_enabled
        self.prefix = (prefix or "Jarvis").strip()
        self.language = None if language == "auto" else language
        self._stop = False

    def stop(self):
        self._stop = True

    def listen(self):
        sample_rate = 16000
        chunk_seconds = 1
        silence_seconds = 5
        # A lower RMS threshold catches quieter microphones and normal speaking volume.
        # Keep it configurable via config.json if a particular microphone needs tuning.
        try:
            speech_threshold = float(__import__("os").environ.get("NEXORA_VOICE_THRESHOLD", "0.004"))
        except (TypeError, ValueError):
            speech_threshold = 0.004
        block = int(sample_rate * chunk_seconds)
        q = queue.Queue()

        def callback(indata, frames, time_info, status):
            if not self._stop:
                q.put(indata.copy().reshape(-1))

        with sd.InputStream(
            samplerate=sample_rate, channels=1, dtype="float32",
            blocksize=block, callback=callback
        ):
            audio_parts = []
            silence_chunks = 0
            speech_started = False
            while not self._stop:
                try:
                    chunk = q.get(timeout=0.5)
                except queue.Empty:
                    continue
                level = float(np.sqrt(np.mean(np.square(chunk)))) if len(chunk) else 0.0
                if level >= speech_threshold:
                    speech_started = True
                    silence_chunks = 0
                    audio_parts.append(chunk)
                elif speech_started:
                    audio_parts.append(chunk)
                    silence_chunks += 1

                if speech_started and silence_chunks >= silence_seconds:
                    audio = np.concatenate(audio_parts)
                    audio_parts = []
                    silence_chunks = 0
                    speech_started = False
                    if len(audio) < sample_rate // 2:
                        continue
                    try:
                        segments, info = self.model.transcribe(
                            audio,
                            language=self.language,
                            beam_size=1,
                            best_of=1,
                            vad_filter=True,
                            condition_on_previous_text=False,
                        )
                        text = " ".join(segment.text.strip() for segment in segments).strip()
                        if text:
                            yield text
                    except Exception:
                        # Keep listening after a failed transcription rather than crash the mic loop.
                        continue
