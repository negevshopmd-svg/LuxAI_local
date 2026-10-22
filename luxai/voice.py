import queue
from collections import deque

import numpy as np
import sounddevice as sd

from .voices import speak


class VoiceListener:
    """Local microphone capture with lightweight WebRTC VAD and local Whisper transcription."""
    def __init__(self, model_path="small", prefix_enabled=True, prefix="Jarvis", language="auto", microphone_device=-1, beam_size=1):
        from faster_whisper import WhisperModel
        import os
        self.model = WhisperModel(
            model_path or "small",
            device="cpu",
            compute_type="int8",
            cpu_threads=max(2, min(8, os.cpu_count() or 4)),
            num_workers=1,
        )
        self.prefix_enabled = prefix_enabled
        self.prefix = (prefix or "Jarvis").strip()
        self.language = None if language == "auto" else language
        self.microphone_device = None if microphone_device in (-1, None, "") else int(microphone_device)
        self.beam_size = max(1, min(5, int(beam_size)))
        self._stop = False

    def stop(self):
        self._stop = True

    def listen(self):
        sample_rate = 16000
        frame_ms = 30  # WebRTC accepts 10, 20 or 30 ms frames.
        frame_samples = sample_rate * frame_ms // 1000
        frame_seconds = frame_ms / 1000
        silence_seconds = 1.0
        pre_roll_seconds = 0.30
        max_utterance_seconds = 20.0
        silence_frames_needed = max(1, int(silence_seconds / frame_seconds))
        pre_roll_frames = max(1, int(pre_roll_seconds / frame_seconds))
        max_frames = int(max_utterance_seconds / frame_seconds)

        # WebRTC VAD is a small CPU-efficient speech detector. If unavailable,
        # retain a simple RMS detector so microphone capture still works.
        try:
            import webrtcvad
            vad = webrtcvad.Vad(2)
            use_vad = True
        except ImportError:
            vad = None
            use_vad = False
            print("WebRTC VAD unavailable; using RMS fallback. Install requirements.txt to enable VAD.")

        q = queue.Queue(maxsize=100)

        def callback(indata, frames, time_info, status):
            if self._stop:
                return
            try:
                q.put_nowait(indata.copy().reshape(-1))
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(indata.copy().reshape(-1))
                except queue.Empty:
                    pass

        pre_roll = deque(maxlen=pre_roll_frames)
        audio_parts = []
        silence_frames = 0
        speech_started = False
        utterance_frames = 0

        with sd.InputStream(
            device=self.microphone_device,
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            blocksize=frame_samples,
            callback=callback,
        ):
            while not self._stop:
                try:
                    chunk = q.get(timeout=0.5)
                except queue.Empty:
                    continue
                if len(chunk) != frame_samples:
                    continue

                if use_vad:
                    pcm = np.clip(chunk * 32768.0, -32768, 32767).astype(np.int16).tobytes()
                    try:
                        is_speech = vad.is_speech(pcm, sample_rate)
                    except Exception:
                        is_speech = False
                else:
                    try:
                        threshold = float(__import__("os").environ.get("NEXORA_VOICE_THRESHOLD", "0.004"))
                    except (TypeError, ValueError):
                        threshold = 0.004
                    is_speech = bool(np.sqrt(np.mean(np.square(chunk))) >= threshold)

                if not speech_started:
                    pre_roll.append(chunk)
                    if is_speech:
                        speech_started = True
                        audio_parts = list(pre_roll)
                        utterance_frames = len(audio_parts)
                        silence_frames = 0
                else:
                    audio_parts.append(chunk)
                    utterance_frames += 1
                    if is_speech:
                        silence_frames = 0
                    else:
                        silence_frames += 1

                if speech_started and (
                    silence_frames >= silence_frames_needed or utterance_frames >= max_frames
                ):
                    audio = np.concatenate(audio_parts).astype(np.float32, copy=False)
                    audio_parts = []
                    pre_roll.clear()
                    silence_frames = 0
                    speech_started = False
                    utterance_frames = 0
                    if len(audio) < sample_rate // 2:
                        continue
                    try:
                        segments, _info = self.model.transcribe(
                            audio,
                            language=self.language,
                            beam_size=self.beam_size,
                            best_of=1,
                            vad_filter=True,
                            condition_on_previous_text=False,
                        )
                        text = " ".join(segment.text.strip() for segment in segments).strip()
                        if text:
                            yield text
                    except Exception as exc:
                        print(f"Local transcription failed: {exc}")
                        continue
