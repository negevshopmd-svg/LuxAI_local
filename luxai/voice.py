"""Microphone capture with observable readiness and cooperative cancellation."""
from __future__ import annotations

from collections import deque
import logging
import math
import os
import queue
import threading
import time

import numpy as np
import sounddevice as sd

from .audio_devices import resolve_microphone_device
from .voices import speak, playback_active, barge_in_ready
from .voice_rules import (
    recognition_options, ROMANIAN_PROMPT, speech_pause_seconds,
    is_hallucinated_outro, is_repetitive_transcript, is_stop_speech_command,
)


class ModelLoadError(RuntimeError):
    """The selected Whisper model failed to load, rather than the microphone."""


class VoiceListener:
    """Capture audio without killing native PortAudio/CTranslate2 threads.

    Status callbacks receive (event, details); level callbacks receive raw RMS
    in [0, 1] at most ten times a second. Connect these to Qt signals; do not
    manipulate widgets from the capture thread.
    """

    def __init__(self, model_path="small", prefix_enabled=True, prefix="Jarvis",
                 language="auto", microphone_device=-1, beam_size=1,
                 microphone_name="", microphone_hostapi="", sensitivity=1.0,
                 status_callback=None, level_callback=None, speech_pause=2.3):
        self.status_callback = status_callback
        self.level_callback = level_callback
        self._stop_event = threading.Event()
        self.prefix_enabled = prefix_enabled
        self.prefix = (prefix or "Jarvis").strip()
        self.language = None if language == "auto" else language
        self.beam_size = max(1, min(5, int(beam_size)))
        self.speech_pause = speech_pause_seconds(speech_pause)
        try:
            sensitivity = float(sensitivity)
        except (TypeError, ValueError):
            sensitivity = 1.0
        self.sensitivity = max(0.25, min(4.0, sensitivity)) if math.isfinite(sensitivity) else 1.0
        # A Bluetooth index is not a stable identifier. Fail before downloading
        # a model if the selected recording endpoint is unavailable.
        self.microphone_device, self._device_info = resolve_microphone_device(
            microphone_device, microphone_name, microphone_hostapi, backend=sd,
        )
        if self.microphone_device != microphone_device and microphone_device not in (-1, None, "", "-1"):
            self._emit(
                "input_warning", device=self._device_info.get("name", ""),
                message="The selected microphone reconnected; its device index was refreshed.",
            )
        self._emit("loading_model", model=str(model_path or "small"))
        from faster_whisper import WhisperModel
        try:
            self.model = WhisperModel(
                model_path or "small", device="cpu", compute_type="int8",
                cpu_threads=max(2, min(6, os.cpu_count() or 4)), num_workers=1,
            )
        except (OSError, RuntimeError, ValueError, MemoryError) as exc:
            raise ModelLoadError(str(exc)) from exc
        self._emit("model_ready", model=str(model_path or "small"))

    def _emit(self, event, **details):
        if self.status_callback is not None:
            try:
                self.status_callback(event, details)
            except Exception:
                logging.getLogger(__name__).exception("Microphone status callback failed")

    def _level(self, rms):
        if self.level_callback is not None:
            try:
                self.level_callback(max(0.0, min(1.0, rms)))
            except Exception:
                logging.getLogger(__name__).exception("Microphone level callback failed")

    def stop(self):
        self._stop_event.set()

    def _sample_rate(self) -> int:
        """Try 16 kHz, then the native format required by headset drivers."""
        info = self._device_info or sd.query_devices(self.microphone_device, "input")
        rates = [16000, int(round(float(info["default_samplerate"]))), 48000, 44100]
        errors = []
        for rate in dict.fromkeys(rates):
            if rate <= 0:
                continue
            try:
                sd.check_input_settings(device=self.microphone_device, samplerate=rate,
                                        channels=1, dtype="float32")
                return rate
            except (ValueError, sd.PortAudioError) as exc:
                errors.append(str(exc))
        raise RuntimeError(
            "The selected microphone has no supported mono recording format. "
            "Check the headset connection and Windows recording-device settings. "
            + (errors[-1] if errors else "")
        )

    @staticmethod
    def _resample_chunk(data: np.ndarray, source_rate: int, target_samples: int) -> np.ndarray:
        if len(data) == target_samples:
            return data
        positions = np.linspace(0, len(data), num=target_samples, endpoint=False)
        return np.interp(positions, np.arange(len(data)), data).astype(np.float32)

    @staticmethod
    def _normalize_audio(audio):
        """Boost quiet recordings without clipping or changing loud input."""
        peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
        if peak <= 0.0 or peak >= 0.1:
            return audio
        return (audio * min(16.0, 0.1 / peak)).astype(np.float32, copy=False)

    def listen(self):
        output_rate = 16000
        input_rate = self._sample_rate()
        input_samples = max(1, int(round(input_rate * 0.03)))
        frame_samples = 480
        silence_frames_needed = round(self.speech_pause / 0.03)
        pre_roll_frames = 14
        # Keep longer descriptions together, instead of interrupting after
        # each small pause or forcing an arbitrary 24-second cutoff.
        max_frames = 1400
        min_speech_frames = 3
        try:
            import webrtcvad
            vad = webrtcvad.Vad(1)
        except (ImportError, ValueError):
            vad = None

        # Allow full multi-second pauses even with split wireless callbacks.
        chunks = queue.Queue(maxsize=500)
        capture = {"last_frame": time.monotonic(), "warning": "", "dropped": 0,
                   "sequence": 0, "discard_through": 0}

        def callback(indata, frames, time_info, status):
            if self._stop_event.is_set():
                return
            captured_at = time.monotonic()
            capture["last_frame"] = captured_at
            capture["sequence"] += 1
            sequence = capture["sequence"]
            if status:
                capture["warning"] = str(status)
            # Whisper may still be busy when Jarvis starts speaking. Discard
            # playback at capture time, not only when draining buffered audio.
            # Sequence numbers preserve ordering even when Windows <=3.12's
            # monotonic clock gives adjacent callbacks the same coarse tick.
            during_playback = playback_active.is_set()
            if during_playback:
                capture["discard_through"] = sequence
                if not barge_in_ready.is_set():
                    return
            item = (sequence, indata.copy().reshape(-1), during_playback)
            try:
                chunks.put_nowait(item)
            except queue.Full:
                capture["dropped"] += 1
                try:
                    chunks.get_nowait()
                except queue.Empty:
                    pass
                try:
                    chunks.put_nowait(item)
                except queue.Full:
                    pass

        pre_roll = deque(maxlen=pre_roll_frames)
        noise_samples = deque(maxlen=80)
        pending = np.empty(0, dtype=np.float32)
        parts = []
        speech_started = False
        active_frames = silence_frames = candidate_frames = 0
        last_level = 0.0
        last_nonzero = time.monotonic()
        warned_silent = False
        last_playback_discard = 0
        warned_drops = 0
        # Dedicated interrupt channel while TTS is audible. Other speech
        # during playback is never forwarded as a desktop instruction.
        interrupt_preroll = deque(maxlen=9)
        interrupt_parts = []
        interrupt_active = 0
        interrupt_silence = 0
        interrupt_started = False

        with sd.InputStream(device=self.microphone_device, samplerate=input_rate,
                            channels=1, dtype="float32", blocksize=input_samples,
                            callback=callback) as stream:
            capture["last_frame"] = time.monotonic()
            self._emit("listening", device=self._device_info.get("name", ""),
                       device_index=self.microphone_device, sample_rate=input_rate)
            while not self._stop_event.is_set():
                if not getattr(stream, "active", True):
                    raise RuntimeError("The microphone stream stopped. Reconnect your headset and restart the microphone.")
                try:
                    sequence, chunk, during_playback = chunks.get(timeout=0.25)
                except queue.Empty:
                    if time.monotonic() - capture["last_frame"] >= 5.0:
                        self._emit("input_stalled", message="The microphone driver is no longer sending audio.")
                        raise RuntimeError("No audio frames received for 5 seconds. Check the wireless headset connection and restart the microphone.")
                    continue
                if capture["warning"]:
                    self._emit("input_warning", message=capture["warning"])
                    capture["warning"] = ""
                if capture["dropped"] > warned_drops:
                    warned_drops = capture["dropped"]
                    self._emit("input_warning", message="Audio processing fell behind; older microphone frames were dropped.",
                               dropped_frames=warned_drops)
                if during_playback or playback_active.is_set() or sequence <= capture["discard_through"]:
                    pre_roll.clear()
                    parts = []
                    pending = np.empty(0, dtype=np.float32)
                    active_frames = silence_frames = candidate_frames = 0
                    speech_started = False
                    # Only active during actual TTS playback, not model loading
                    # or speech synthesis. Typical headphones reduce echo.
                    if during_playback and barge_in_ready.is_set():
                        frame = self._resample_chunk(chunk, input_rate, 480)
                        rms = float(np.sqrt(np.mean(np.square(frame, dtype=np.float64))))
                        background = float(np.percentile(noise_samples, 20)) if noise_samples else 0.0001
                        threshold = max(0.0018 / self.sensitivity, background * 3)
                        # Ignore clipping/very loud output leaking back into mic.
                        voiced = threshold <= rms <= 0.25
                        if vad is not None and voiced:
                            pcm = np.clip(frame * 32768.0, -32768, 32767).astype(np.int16).tobytes()
                            try:
                                voiced = bool(vad.is_speech(pcm, output_rate)) or rms > 0.007
                            except (ValueError, RuntimeError):
                                pass
                        if not interrupt_started:
                            interrupt_preroll.append(frame)
                            if voiced:
                                interrupt_active += 1
                                if interrupt_active >= 3:
                                    interrupt_started = True
                                    interrupt_parts = list(interrupt_preroll)
                                    interrupt_silence = 0
                            else:
                                interrupt_active = 0
                        else:
                            interrupt_parts.append(frame)
                            if voiced:
                                interrupt_active += 1
                                interrupt_silence = 0
                            else:
                                interrupt_silence += 1
                            if interrupt_silence >= 13 or len(interrupt_parts) >= 120:
                                audio = np.concatenate(interrupt_parts).astype(np.float32)
                                valid = interrupt_active >= 5 and len(audio) >= 5600
                                interrupt_preroll.clear()
                                interrupt_parts = []
                                interrupt_active = interrupt_silence = 0
                                interrupt_started = False
                                if valid and not self._stop_event.is_set() and barge_in_ready.is_set():
                                    try:
                                        detected_segments, _ = self.model.transcribe(
                                            self._normalize_audio(audio),
                                            **recognition_options(self.language, self.beam_size),
                                        )
                                        stop_text = " ".join(seg.text.strip() for seg in detected_segments).strip()
                                        if is_stop_speech_command(stop_text):
                                            yield "stop"
                                    except (OSError, RuntimeError, ValueError):
                                        logging.getLogger(__name__).debug("Stop-word recognition failed")
                    else:
                        interrupt_preroll.clear()
                        interrupt_parts = []
                        interrupt_active = interrupt_silence = 0
                        interrupt_started = False
                    continue
                interrupt_preroll.clear()
                interrupt_parts = []
                interrupt_active = interrupt_silence = 0
                interrupt_started = False
                if capture["discard_through"] != last_playback_discard:
                    # Never join a pre-playback partial sentence to later audio.
                    last_playback_discard = capture["discard_through"]
                    pre_roll.clear()
                    parts = []
                    pending = np.empty(0, dtype=np.float32)
                    active_frames = silence_frames = candidate_frames = 0
                    speech_started = False
                if not len(chunk):
                    continue
                if not np.all(np.isfinite(chunk)):
                    self._emit("input_warning", message="Invalid microphone samples were discarded.")
                    continue
                # Variable-size callbacks occur with some wireless/audio
                # drivers. Accumulate them instead of discarding every frame.
                pending = np.concatenate((pending, chunk))
                while len(pending) >= input_samples and not self._stop_event.is_set():
                    chunk, pending = pending[:input_samples], pending[input_samples:]
                    chunk = self._resample_chunk(chunk, input_rate, frame_samples)
                    rms = float(np.sqrt(np.mean(np.square(chunk, dtype=np.float64))))
                    now = time.monotonic()
                    if now - last_level >= 0.1:
                        self._level(rms)
                        last_level = now
                    if rms > 0.00001:
                        last_nonzero = now
                        warned_silent = False
                    elif not warned_silent and now - last_nonzero >= 5.0:
                        warned_silent = True
                        self._emit("input_silent", message="The microphone is sending silence. Check mute, headset input and Windows microphone permissions.")
                    # Quiet speech should not poison the noise floor until
                    # every later utterance falls below an ever-rising gate.
                    noise = float(np.percentile(noise_samples, 20)) if noise_samples else 0.0001
                    threshold = max(0.0007 / self.sensitivity, noise * 2.2)
                    if vad is not None:
                        peak = float(np.max(np.abs(chunk)))
                        gain = min(16.0, max(1.0, 0.08 / max(peak, 0.000001)))
                        pcm = np.clip(chunk * gain * 32768.0, -32768, 32767).astype(np.int16).tobytes()
                        try:
                            detected = (
                                bool(vad.is_speech(pcm, output_rate))
                                and rms >= max(0.00012 / self.sensitivity, noise * 1.15)
                            ) or rms >= max(0.006 / self.sensitivity, noise * 4.0)
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
                        self._emit("speech_started")
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
                    if speech_started and (silence_frames >= silence_frames_needed or len(parts) >= max_frames):
                        audio = np.concatenate(parts).astype(np.float32, copy=False)
                        enough_speech = active_frames >= min_speech_frames and len(audio) >= 6080
                        parts = []
                        pre_roll.clear()
                        speech_started = False
                        active_frames = silence_frames = candidate_frames = 0
                        if self._stop_event.is_set() or not enough_speech:
                            continue
                        self._emit("transcribing")
                        try:
                            segments, _info = self.model.transcribe(
                                self._normalize_audio(audio), **recognition_options(self.language, self.beam_size)
                            )
                            utterance = " ".join(segment.text.strip() for segment in segments).strip()
                            if is_hallucinated_outro(utterance) or is_repetitive_transcript(utterance):
                                self._emit("ignored_hallucination", message="Whisper noise/repetition/outro hallucination ignored.")
                            elif utterance and not self._stop_event.is_set():
                                yield utterance
                            elif not self._stop_event.is_set():
                                self._emit("no_speech", message="Sound was captured, but no words were recognized. Check recognition language and microphone sensitivity.")
                        except (OSError, RuntimeError, ValueError) as exc:
                            self._emit("transcription_error", message=f"{type(exc).__name__}: {exc}")
                            logging.getLogger(__name__).warning("Local transcription failed (%s): %s", type(exc).__name__, exc)
                        if not self._stop_event.is_set():
                            self._emit("listening", device=self._device_info.get("name", ""),
                                       device_index=self.microphone_device, sample_rate=input_rate)
