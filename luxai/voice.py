"""Microphone capture with safe cancellation and language-specific Whisper prompts."""
from __future__ import annotations

from collections import deque
import os
import queue
import threading

import numpy as np
import sounddevice as sd

from .voices import playback_active


ROMANIAN_PROMPT = (
    "Conversație în limba română cu asistentul vocal Jarvis. "
    "Deschide YouTube, Telegram, Discord, Steam, Dota, Google Chrome. "
    "Apasă Enter, Escape, Control, Shift, tasta Q; creează un fișier sau un dosar. "
    "Salut, Jarvis. Pornește programul. Mulțumesc."
)


def recognition_options(language: str | None, beam_size: int) -> dict:
    """Never run two consecutive VAD filters on short Romanian phrases."""
    return {
        "language": language,
        "beam_size": max(3, beam_size) if language == "ro" else beam_size,
        "best_of": 1,
        "vad_filter": False,
        "condition_on_previous_text": False,
        "initial_prompt": ROMANIAN_PROMPT if language == "ro" else None,
        "temperature": 0.0,
        "no_speech_threshold": 0.65,
    }


class VoiceListener:
    """Listen continuously without killing native PortAudio/CTranslate2 threads."""

    def __init__(self, model_path="small", prefix_enabled=True, prefix="Jarvis",
                 language="auto", microphone_device=-1, beam_size=1):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(
            model_path or "small",
            device="cpu",
            compute_type="int8",
            cpu_threads=max(2, min(6, os.cpu_count() or 4)),
            num_workers=1,
        )
        self.prefix_enabled = prefix_enabled
        self.prefix = (prefix or "Jarvis").strip()
        self.language = None if language == "auto" else language
        self.microphone_device = None if microphone_device in (-1, None, "") else int(microphone_device)
        self.beam_size = max(1, min(5, int(beam_size)))
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def _sample_rate(self) -> int:
        """Some Windows 11 drivers reject 16 kHz; try the device's native rate."""
        try:
            sd.check_input_settings(device=self.microphone_device, samplerate=16000,
                                    channels=1, dtype="float32")
            return 16000
        except Exception:
            device = sd.query_devices(self.microphone_device, "input")
            rate = int(round(float(device["default_samplerate"])))
            sd.check_input_settings(device=self.microphone_device, samplerate=rate,
                                    channels=1, dtype="float32")
            return rate

    @staticmethod
    def _resample_chunk(data: np.ndarray, source_rate: int, target_samples: int) -> np.ndarray:
        if len(data) == target_samples:
            return data
        positions = np.linspace(0, len(data), num=target_samples, endpoint=False)
        return np.interp(positions, np.arange(len(data)), data).astype(np.float32)

    def listen(self):
        output_rate = 16000
        input_rate = self._sample_rate()
        frame_ms = 30
        input_samples = max(1, int(round(input_rate * frame_ms / 1000)))
        frame_samples = output_rate * frame_ms // 1000
        frame_seconds = frame_ms / 1000
        silence_frames_needed = int(0.90 / frame_seconds)
        pre_roll_frames = int(0.42 / frame_seconds)
        max_frames = int(24 / frame_seconds)
        min_speech_frames = 3

        try:
            import webrtcvad
            vad = webrtcvad.Vad(1)
        except (ImportError, ValueError):
            vad = None

        chunks = queue.Queue(maxsize=150)
        def callback(indata, frames, time_info, status):
            if self._stop_event.is_set():
                return
            try:
                chunks.put_nowait(indata.copy().reshape(-1))
            except queue.Full:
                try:
                    chunks.get_nowait()
                    chunks.put_nowait(indata.copy().reshape(-1))
                except queue.Empty:
                    pass

        pre_roll = deque(maxlen=pre_roll_frames)
        noise_samples = deque(maxlen=80)
        parts = []
        speech_started = False
        active_frames = 0
        silence_frames = 0
        candidate_frames = 0

        with sd.InputStream(device=self.microphone_device, samplerate=input_rate,
                            channels=1, dtype="float32", blocksize=input_samples,
                            callback=callback):
            while not self._stop_event.is_set():
                try:
                    chunk = chunks.get(timeout=0.25)
                except queue.Empty:
                    continue
                if len(chunk) != input_samples:
                    continue
                chunk = self._resample_chunk(chunk, input_rate, frame_samples)
                # Do not transcribe Jarvis's own speech.
                if playback_active.is_set():
                    pre_roll.clear()
                    parts = []
                    active_frames = silence_frames = candidate_frames = 0
                    speech_started = False
                    continue
                rms = float(np.sqrt(np.mean(np.square(chunk, dtype=np.float64))))
                noise = float(np.median(noise_samples)) if noise_samples else 0.0005
                threshold = max(0.0025, noise * 2.2)
                if vad is not None:
                    pcm = np.clip(chunk * 32768.0, -32768, 32767).astype(np.int16).tobytes()
                    try:
                        detected = bool(vad.is_speech(pcm, output_rate)) and rms >= max(0.0015, noise * 1.3)
                    except (ValueError, RuntimeError):
                        detected = rms >= threshold
                else:
                    detected = rms >= threshold

                if not speech_started:
                    pre_roll.append(chunk)
                    if not detected:
                        noise_samples.append(rms)
                        candidate_frames = 0
                        continue
                    candidate_frames += 1
                    if candidate_frames < min_speech_frames:
                        continue
                    speech_started = True
                    parts = list(pre_roll)
                    active_frames = candidate_frames
                    silence_frames = 0
                else:
                    parts.append(chunk)
                    if detected:
                        active_frames += 1
                        silence_frames = 0
                    else:
                        silence_frames += 1

                if speech_started and (silence_frames >= silence_frames_needed or
                                       len(parts) >= max_frames):
                    audio = np.concatenate(parts).astype(np.float32, copy=False)
                    enough_speech = active_frames >= min_speech_frames and len(audio) >= int(0.38 * output_rate)
                    parts = []
                    pre_roll.clear()
                    speech_started = False
                    active_frames = silence_frames = candidate_frames = 0
                    if self._stop_event.is_set() or not enough_speech:
                        continue
                    try:
                        segments, _info = self.model.transcribe(
                            audio, **recognition_options(self.language, self.beam_size)
                        )
                        utterance = " ".join(segment.text.strip() for segment in segments).strip()
                        if utterance and not self._stop_event.is_set():
                            yield utterance
                    except (OSError, RuntimeError, ValueError) as exc:
                        print(f"Local transcription failed ({type(exc).__name__}): {exc}")
                        continue
