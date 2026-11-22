"""Piper/Windows speech playback and optional Fish Audio free-tier synthesis.

Russian speech prefers the ru_RU-dmitri-medium neural voice even if other
Piper models are installed. Never substitute an English SAPI voice for Russian.
Voice failures are written to voice_error.log because the app uses pythonw.exe.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import subprocess
import sys
import threading
import tempfile
import time
import urllib.request
import wave
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VOICES_DIR = ROOT / "voices"
CONFIG_PATH = ROOT / "config.json"
ERROR_LOG = ROOT / "voice_error.log"
playback_active = threading.Event()
# Available only while the actual voice output is playing, not while Piper
# downloads or Fish Audio synthesizes speech. The microphone may listen for
# "stop" then.
barge_in_ready = threading.Event()
_cancel_lock = threading.Lock()
_cancel_generation = 0
_sapi_process = None


def _cancel_token() -> int:
    with _cancel_lock:
        return _cancel_generation


def _was_cancelled(token: int) -> bool:
    with _cancel_lock:
        return token != _cancel_generation


_active_stream = None  # streaming Fish playback, aborted by stop_speaking


def stop_speaking() -> None:
    """Stop audio and invalidate pending synthesis before it can start playback."""
    global _cancel_generation
    with _cancel_lock:
        _cancel_generation += 1
        process = _sapi_process
        stream = _active_stream
        barge_in_ready.clear()
    if stream is not None:
        stream.abort()
    if process is not None and process.poll() is None:
        try:
            process.terminate()
        except OSError:
            pass
    # sd.stop releases sd.wait() without terminating the audio thread.
    try:
        import sounddevice as sd
        sd.stop()
    except (ImportError, RuntimeError, OSError):
        pass



from luxai.voice_presets import (
    PIPER_REPOSITORY, VOICE_PRESETS,
)
MAX_VOICE_DOWNLOAD_BYTES = 80_000_000
MIN_MODEL_BYTES = 10_000_000



class VoiceManager:
    """Select and play voices matching the assistant's configured language."""

    def __init__(self):
        self._inference_lock = threading.RLock()
        self._voice = None
        self._loaded_path = None
        self._prepared_path = None
        self.config = self._load_config()

    @staticmethod
    def _load_config() -> dict:
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _log(message: str) -> None:
        try:
            with ERROR_LOG.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")
        except OSError:
            pass
        print(message)

    def available_voices(self) -> list[dict]:
        VOICES_DIR.mkdir(parents=True, exist_ok=True)
        found = []
        for model in sorted(VOICES_DIR.glob("*.onnx")):
            metadata = model.with_suffix(model.suffix + ".json")
            found.append({
                "id": model.stem,
                "name": model.stem.replace("_", " ").replace("-", " ").title(),
                "model": str(model),
                "metadata": str(metadata),
                "ready": metadata.is_file(),
            })
        return found

    @staticmethod
    def _model_matches_language(path: Path, language: str) -> bool:
        """Never use a Russian or English phonemizer for Romanian speech."""
        config = path.with_suffix(path.suffix + ".json")
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
            code = str(data.get("language", {}).get("code", "")).lower()
            return code.split("_", 1)[0] == language
        except (OSError, ValueError, TypeError, AttributeError):
            return False

    @staticmethod
    def _download_file(url: str, destination: Path, *, sha256: str | None,
                       minimum_size: int, maximum_size: int) -> None:
        """Bound and atomically verify a voice download before installing it."""
        temporary = destination.with_name(destination.name + ".download")
        temporary.unlink(missing_ok=True)
        total = 0
        digest = hashlib.sha256()
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "LuxAI-Jarvis/1.0"}
            )
            with urllib.request.urlopen(request, timeout=90) as response, temporary.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > maximum_size:
                        raise ValueError("Voice download exceeded permitted size")
                    digest.update(chunk)
                    handle.write(chunk)
            if total < minimum_size:
                raise ValueError("Voice model download incomplete")
            if sha256 is not None and digest.hexdigest().lower() != sha256.lower():
                raise ValueError("Voice model SHA-256 verification failed")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _download_voice(self, language: str) -> Path | None:
        """Install an official Piper voice lazily; never block startup/UI."""
        preset = VOICE_PRESETS[language]
        VOICES_DIR.mkdir(parents=True, exist_ok=True)
        model_path = VOICES_DIR / (preset["id"] + ".onnx")
        metadata_path = VOICES_DIR / (preset["id"] + ".onnx.json")
        url = PIPER_REPOSITORY + preset["directory"] + "/"
        try:
            model_ok = model_path.is_file() and model_path.stat().st_size >= MIN_MODEL_BYTES
            if not model_ok:
                self._log(f"Downloading {language} Piper voice {preset['id']} for first use...")
                self._download_file(
                    url + model_path.name, model_path,
                    sha256=preset["sha256"],
                    minimum_size=MIN_MODEL_BYTES,
                    maximum_size=MAX_VOICE_DOWNLOAD_BYTES,
                )
            if not self._model_matches_language(model_path, language):
                # A partially installed configuration may be absent, but a
                # wrong language must never be handed to the Piper engine.
                self._download_file(
                    url + metadata_path.name, metadata_path,
                    sha256=None, minimum_size=100, maximum_size=50_000,
                )
            if not self._model_matches_language(model_path, language):
                raise ValueError("Piper voice metadata has wrong language")
            self._log(f"Piper voice {preset['id']} ready ({language}).")
            return model_path
        except Exception as exc:
            self._log(f"Piper voice installation failed for {language}: {exc}")
            return None

    def _download_russian_voice(self) -> Path | None:
        return self._download_voice("ru")

    def _select_model(self, language: str) -> Path | None:
        if language not in VOICE_PRESETS:
            return None
        voices = self.available_voices()
        explicit = str(self.config.get("voice_model_path", "") or "").strip()
        if explicit:
            candidate = Path(explicit).expanduser()
            if candidate.is_file() and self._model_matches_language(candidate, language):
                return candidate
            self._log(f"Configured Piper voice missing or wrong language: {explicit}")

        selected = str(self.config.get("voice_id", "") or "").strip().lower()
        if selected:
            for voice in voices:
                if (voice["ready"] and voice["id"].lower() == selected
                        and self._model_matches_language(Path(voice["model"]), language)):
                    return Path(voice["model"])
            # When the user explicitly chooses Mihai or Lessac, install that
            # exact voice instead of silently playing another available one.
            if selected == VOICE_PRESETS[language]["id"].lower():
                return self._download_voice(language)

        # Search existing voices by actual metadata instead of guessing from
        # filename. Only download the default when no compatible one exists.
        default_id = VOICE_PRESETS[language]["id"].lower()
        matching = [
            Path(v["model"]) for v in voices if v["ready"]
            and self._model_matches_language(Path(v["model"]), language)
        ]
        for candidate in matching:
            if candidate.stem.lower() == default_id:
                return candidate
        if matching:
            return matching[0]
        return self._download_voice(language)

    def _load_piper_voice(self, model_path: Path) -> None:
        if self._voice is None or self._loaded_path != str(model_path):
            from piper import PiperVoice
            self._voice = PiperVoice.load(str(model_path))
            self._loaded_path = str(model_path)
            self._prepared_path = None

    def _synthesize(self, text: str, wav_file) -> None:
        speed = max(0.7, min(1.4, float(self.config.get("voice_speed", 1.0))))
        try:
            from piper.config import SynthesisConfig
        except ImportError:
            self._voice.synthesize_wav(text, wav_file)
        else:
            self._voice.synthesize_wav(
                text, wav_file,
                syn_config=SynthesisConfig(length_scale=1.0 / speed),
            )

    def prepare(self, settings: dict) -> bool:
        """Load and silently exercise the configured Piper voice on a worker.

        The same model instance is retained for the first spoken reply. No
        microphone, playback stream or startup announcement is opened here.
        Windows SAPI currently lives in a separate process for every reply;
        launching a throwaway process would not preload its next instance.
        """
        snapshot = dict(settings)
        if not snapshot.get("tts_enabled", True):
            return False
        engine = str(snapshot.get("voice_engine", "piper") or "piper").lower()
        if engine == "fish":
            # Startup never sends text or uses provider capacity; it only
            # warms the audio device, modules and the TLS connection.
            return self._prepare_fish()
        if engine == "windows":
            return False
        from luxai.response_language import reply_language
        language = reply_language(snapshot)
        with self._inference_lock:
            self.config = snapshot
            try:
                model_path = self._select_model(language)
                if model_path is None:
                    return False
                self._load_piper_voice(model_path)
                if self._prepared_path == str(model_path):
                    return True
                # Exercise phonemization and the first ONNX inference as well
                # as model loading. The generated samples are discarded.
                phrase = {"ru": "Готово.", "ro": "Gata.", "en": "Ready."}[language]
                with io.BytesIO() as samples:
                    with wave.open(samples, "wb") as wav_file:
                        self._synthesize(phrase, wav_file)
                # Import the playback libraries now; importing them later can
                # otherwise delay the first reply even with a loaded model.
                import soundfile  # noqa: F401
                import sounddevice  # noqa: F401
                self._prepared_path = str(model_path)
                return True
            except Exception as exc:
                self._log(f"Voice warm-up failed ({type(exc).__name__}).")
                return False

    def _windows_speak(self, text: str, language: str, cancel_token: int) -> bool:
        """Fallback to SAPI, but only if Windows has a voice for the language."""
        if sys.platform != "win32":
            return False
        encoded = base64.b64encode(text.encode("utf-16-le")).decode("ascii")
        culture = {"ru": "ru-*", "ro": "ro-*", "en": "en-*"}.get(language, "ru-*")
        volume = max(0, min(100, int(self.config.get("voice_volume", 80))))
        rate = max(-10, min(10, round((float(self.config.get("voice_speed", 1.0)) - 1.0) * 8)))
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.SetOutputToDefaultAudioDevice(); "
            "$s.Volume=" + str(volume) + "; $s.Rate=" + str(rate) + "; "
            "$all=@($s.GetInstalledVoices() | Where-Object { $_.Enabled -and "
            "$_.VoiceInfo.Culture.Name -like '" + culture + "' }); "
            "if ($all.Count -eq 0) { "
            "[Console]::Error.WriteLine('No matching Windows SAPI voice for " + language + "'); "
            "$s.Dispose(); exit 9 }; "
            "$v=$all | Where-Object { $_.VoiceInfo.Gender -eq 'Male' } | Select-Object -First 1; "
            "if (-not $v) { $v=$all | Select-Object -First 1 }; "
            "$s.SelectVoice($v.VoiceInfo.Name); "
            "$t=[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('" + encoded + "')); "
            "$s.Speak($t); $s.Dispose()"
        )
        global _sapi_process
        if _was_cancelled(cancel_token):
            return False
        try:
            process = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            with _cancel_lock:
                _sapi_process = process
                if cancel_token == _cancel_generation:
                    barge_in_ready.set()
                else:
                    process.terminate()
            try:
                _out, error = process.communicate(timeout=90)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise
            if _was_cancelled(cancel_token):
                return False
            if process.returncode == 0:
                return True
            self._log(
                "Windows SAPI unavailable for " + language + ": "
                + (error or b"").decode("utf-8", errors="replace")[:500]
            )
        except Exception as exc:
            if not _was_cancelled(cancel_token):
                self._log(f"Windows SAPI playback failed: {exc}")
        finally:
            with _cancel_lock:
                if 'process' in locals() and _sapi_process is process:
                    _sapi_process = None
                barge_in_ready.clear()
        return False

    def _play_wav(self, wav_data: bytes, cancel_token: int) -> bool:
        import soundfile as sf
        audio, sample_rate = sf.read(io.BytesIO(wav_data), dtype="float32")
        if _was_cancelled(cancel_token):
            return False
        volume = max(0.0, min(1.0, float(self.config.get("voice_volume", 80)) / 100))
        import sounddevice as sd
        with _cancel_lock:
            if cancel_token != _cancel_generation:
                return False
            sd.play(audio * volume, sample_rate)
            barge_in_ready.set()
        try:
            sd.wait()
        finally:
            barge_in_ready.clear()
        return not _was_cancelled(cancel_token)

    def _prepare_fish(self) -> bool:
        """Warm everything the first Fish reply needs, without sending text.

        Imports the decoder/audio modules, opens and closes the output device
        at Fish's sample rate and performs one TLS handshake. No request,
        key or text leaves the computer, so no provider quota is used.
        """
        from luxai import fish_tts
        try:
            import soundfile  # noqa: F401
            import sounddevice as sd
            stream_class = getattr(sd, "RawOutputStream", None)
            if stream_class is not None:
                with stream_class(samplerate=fish_tts.SAMPLE_RATE, channels=1, dtype="int16"):
                    pass
        except Exception as exc:
            try:
                import sounddevice as _sd
                device = _sd.query_devices(kind="output").get("name", "?")
                version = getattr(_sd, "__version__", "?")
            except Exception:
                device, version = "?", "?"
            self._log(f"Fish audio warm-up skipped at output-stream open ({type(exc).__name__}: {str(exc)[:160]}; "
                      f"sounddevice {version}; output device {str(device)[:80]}).")
        return fish_tts.warm_up_connection()

    def prefetch(self, text: str, language: str | None = None) -> None:
        """Synthesize the NEXT piece while the current one plays (Fish only).

        The audio stays in memory (at most 3 pieces) and is dropped when speech
        is stopped, so long texts are read without pauses between pieces.
        """
        text = re.sub(r"\s+", " ", str(text or "")).strip()[:700]
        config = self._load_config()
        if not text or str(config.get("voice_engine", "piper")).lower() != "fish" or not self._fish_usable():
            return
        language = (language or config.get("language", "ru") or "ru").lower()
        # Audit 7 #28: the voice and its speed are part of the key — a piece prepared before the user
        # changed them is never played with the old voice.
        key = (text, language) + _fish_voice_identity(config) + (_cancel_generation,)
        with _prefetch_lock:
            if key in _prefetched:
                return
            # Audit 7 #26: at most two syntheses at once; a burst no longer starts a thread per piece
            # (the piece is then synthesized when it is spoken).
            if sum(1 for slot in _prefetched.values() if not slot["done"].is_set()) >= _PREFETCH_WORKERS:
                return
            while len(_prefetched) >= 3:
                _prefetched.pop(next(iter(_prefetched)))
            slot = {"done": threading.Event(), "wav": None}
            _prefetched[key] = slot

        def work():
            from luxai import fish_tts
            from luxai.secure_keys import get_api_key
            try:
                api_key = get_api_key("fish")
                if api_key:
                    speed = max(0.7, min(1.4, float(config.get("voice_speed", 1.0))))
                    slot["wav"] = fish_tts.synthesize(
                        text, api_key, voice_id=config.get("fish_voice_id") or fish_tts.DEFAULT_FISH_VOICE,
                        speed=speed, language=language,
                        is_cancelled=lambda: key[-1] != _cancel_generation)
            except Exception:
                slot["wav"] = None
            finally:
                slot["done"].set()

        threading.Thread(target=work, daemon=True, name="JarvisFishPrefetch").start()

    def _take_prefetched(self, text: str, language: str, cancel_token: int):
        config = getattr(self, "config", None) or {}
        key = (text, language) + _fish_voice_identity(config) + (cancel_token,)
        with _prefetch_lock:
            slot = _prefetched.pop(key, None)
        if slot is None:
            return None
        # Started while the previous piece played: usually ready already. Audit 7 #27: «stop» ends the
        # wait at once (it used to block up to 30 s before the next command could speak).
        deadline = time.monotonic() + 30
        while not slot["done"].wait(0.1):
            if _was_cancelled(cancel_token) or time.monotonic() >= deadline:
                return None
        return slot["wav"]

    # How long Fish Audio is skipped after a failure (None = until the key changes). Meanwhile the local
    # Piper voice speaks, so a refused or empty key never makes Jarvis silent.
    FISH_PAUSE = {"auth": None, "payment": None, "rate_limit": 60.0, "unavailable": 60.0, "timeout": 30.0,
                  "response": 30.0, "network": 30.0}

    @staticmethod
    def _fish_fingerprint() -> str:
        import hashlib
        from luxai.secure_keys import get_api_key
        try:
            key = get_api_key("fish") or ""
        except Exception:
            key = ""
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16] if key else ""

    def _fish_usable(self) -> bool:
        """False while Fish Audio is paused after a failure (a new key ends the pause at once)."""
        pause = getattr(self, "_fish_pause", None)
        if not pause:
            return True
        fingerprint, until = pause
        if fingerprint != self._fish_fingerprint() or (until is not None and time.monotonic() >= until):
            self._fish_pause = None
            return True
        return False

    def _fish_failed(self, code: str) -> None:
        delay = self.FISH_PAUSE.get(code, 30.0)
        self._fish_pause = (self._fish_fingerprint(), None if delay is None else time.monotonic() + delay)
        _note_voice_notice("fish_" + (code if code in ("auth", "payment", "missing") else "unavailable"))

    def _fish_speak(self, text: str, language: str, cancel_token: int) -> bool:
        """Use the explicitly selected free cloud voice, preserving stop behavior."""
        from luxai import fish_tts
        from luxai.secure_keys import get_api_key

        self._fish_heard = False  # some of this piece already played (then it is not repeated locally)
        if _was_cancelled(cancel_token):
            return False
        ready = self._take_prefetched(text, language, cancel_token)
        if ready:
            return self._play_wav(ready, cancel_token)
        try:
            key = get_api_key("fish")
            if not key:
                self._log("Fish Audio key not configured; add it in speech synthesis settings.")
                self._fish_failed("missing")
                return False
            speed = max(0.7, min(1.4, float(self.config.get("voice_speed", 1.0))))
            volume = max(0.0, min(1.0, float(self.config.get("voice_volume", 80)) / 100))
            player = _PCMStreamPlayer(fish_tts.SAMPLE_RATE, volume, cancel_token, self._log)
            try:
                wav_data = fish_tts.synthesize(
                    text, key,
                    voice_id=self.config.get("fish_voice_id") or fish_tts.DEFAULT_FISH_VOICE,
                    speed=speed, language=language,
                    is_cancelled=lambda: _was_cancelled(cancel_token),
                    on_chunk=player.feed,
                )
            except BaseException:
                self._fish_heard = player.received > 0
                player.abort()
                raise
            if _was_cancelled(cancel_token):
                player.abort()
                return False
            if player.received:
                # Audio has been playing while it downloaded; let it finish.
                return player.finish()
            # The adapter validates mono PCM16 WAV metadata and bounds the
            # response before decoding, so a network reply cannot request an
            # unbounded sample allocation. No speech audio is persisted.
            return self._play_wav(wav_data, cancel_token)
        except fish_tts.FishTTSError as exc:
            if not _was_cancelled(cancel_token):
                self._log(f"Fish Audio synthesis failed ({exc.code}).")
                if exc.code != "cancelled":
                    self._fish_failed(exc.code)
        except Exception as exc:
            # HTTP/decoder exceptions may contain the user's text or key.
            # Only the exception type is suitable for the diagnostic log.
            if not _was_cancelled(cancel_token):
                self._log(f"Fish Audio playback failed ({type(exc).__name__}).")
                self._fish_failed("network")
        finally:
            barge_in_ready.clear()
        return False

    def speak(self, text: str, language: str | None = None, cancel_token: int = 0) -> bool:
        # Startup preparation and previews can reach the shared manager from
        # different workers. Piper's model and mutable config stay serialized.
        with self._inference_lock:
            return self._speak(text, language, cancel_token)

    def _speak(self, text: str, language: str | None, cancel_token: int) -> bool:
        text = re.sub(r"\s+", " ", str(text or "")).strip()[:700]
        if not text or _was_cancelled(cancel_token):
            return False
        # Settings can change while the application is running.
        self.config = self._load_config()
        language = (language or self.config.get("language", "ru") or "ru").lower()
        if language not in ("ru", "ro", "en"):
            language = "ru" if re.search(r"[а-яё]", text, flags=re.IGNORECASE) else "ro"

        voice_engine = str(self.config.get("voice_engine", "piper") or "piper").lower()
        if voice_engine == "fish":
            if self._fish_usable():
                if self._fish_speak(text, language, cancel_token):
                    return True
                if _was_cancelled(cancel_token) or getattr(self, "_fish_heard", False):
                    return False  # stopped, or part of it was already heard: never said twice
            # Fish Audio refused (key, credit) or is unreachable: the local Piper voice speaks instead.
        if voice_engine == "windows":
            if self._windows_speak(text, language, cancel_token):
                return True
            self._log(f"Windows voice unavailable for {language}; choose Piper in settings.")
            return False

        model_path = self._select_model(language)
        if _was_cancelled(cancel_token):
            return False
        if model_path is not None:
            try:
                self._load_piper_voice(model_path)
                volume = max(0.0, min(1.0, float(self.config.get("voice_volume", 80)) / 100))
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp:
                    wav_path = Path(temp.name)
                try:
                    with wave.open(str(wav_path), "wb") as wav_file:
                        self._synthesize(text, wav_file)
                    import soundfile as sf
                    audio, sample_rate = sf.read(str(wav_path), dtype="float32")
                    if _was_cancelled(cancel_token):
                        return False
                    import sounddevice as sd
                    with _cancel_lock:
                        if cancel_token != _cancel_generation:
                            return False
                        sd.play(audio * volume, sample_rate)
                        barge_in_ready.set()
                    try:
                        sd.wait()
                    finally:
                        barge_in_ready.clear()
                    return not _was_cancelled(cancel_token)
                finally:
                    wav_path.unlink(missing_ok=True)
            except Exception as exc:
                self._log(f"Piper playback failed for {model_path.name}: {exc}")

        if self._windows_speak(text, language, cancel_token):
            return True
        model_name = VOICE_PRESETS.get(language, VOICE_PRESETS["ru"])["id"]
        self._log(
            f"No working {language} voice. Check voices/{model_name}.onnx, "
            "the matching .onnx.json, sound output and voice_error.log."
        )
        return False


class _PCMStreamPlayer:
    """Play 16-bit mono PCM while it is still downloading.

    Network reads only enqueue chunks; a separate thread writes them to the
    audio device after a short pre-buffer, so slow playback never stalls the
    download and the first words sound as soon as they arrive.
    """
    PREBUFFER_SECONDS = 0.12

    def __init__(self, sample_rate, volume, cancel_token, log):
        import queue as _queue
        self.sample_rate = int(sample_rate)
        self.volume = float(volume)
        self.cancel_token = cancel_token
        self.log = log
        self.received = 0
        self._queue = _queue.Queue()
        self._pending = bytearray()
        self._thread = None
        self._stream = None
        self._aborted = threading.Event()
        self._error = None

    def feed(self, chunk: bytes):
        if self._aborted.is_set() or _was_cancelled(self.cancel_token):
            return
        self.received += len(chunk)
        if self._thread is None:
            self._pending.extend(chunk)
            if len(self._pending) >= int(self.sample_rate * 2 * self.PREBUFFER_SECONDS):
                self._start()
        else:
            self._queue.put(chunk)

    def _start(self):
        global _active_stream
        import sounddevice as sd
        self._stream = sd.RawOutputStream(samplerate=self.sample_rate, channels=1, dtype="int16")
        with _cancel_lock:
            if self.cancel_token != _cancel_generation:
                self._stream.close()
                self._stream = None
                self._aborted.set()
                return
            _active_stream = self
            self._stream.start()
            barge_in_ready.set()
        self._queue.put(bytes(self._pending))
        self._pending = bytearray()
        self._thread = threading.Thread(target=self._play, daemon=True, name="JarvisFishStream")
        self._thread.start()

    def _scaled(self, chunk: bytes) -> bytes:
        if self.volume >= 0.999:
            return chunk
        import numpy as _np
        samples = _np.frombuffer(chunk, dtype=_np.int16).astype(_np.float32) * self.volume
        return samples.astype(_np.int16).tobytes()

    def _play(self):
        try:
            while not self._aborted.is_set():
                chunk = self._queue.get()
                if chunk is None:
                    break
                if chunk:
                    self._stream.write(self._scaled(chunk))
        except Exception as exc:
            if not self._aborted.is_set():
                self._error = exc

    def finish(self) -> bool:
        """Play what is left, wait for the device to drain, then close."""
        try:
            if self._aborted.is_set() or _was_cancelled(self.cancel_token):
                return False
            if self._thread is None and self._pending:
                self._start()
                if self._thread is None:
                    return False
            self._queue.put(None)
            self._thread.join()
            if self._error is not None:
                self.log(f"Fish Audio playback failed ({type(self._error).__name__}).")
                return False
            return not self._aborted.is_set() and not _was_cancelled(self.cancel_token)
        finally:
            self._close()

    def abort(self):
        """Stop at once (Stop word / cancelled reply) and release the device."""
        self._aborted.set()
        self._queue.put(None)
        stream = self._stream
        if stream is not None:
            try:
                stream.abort()
            except Exception:
                pass
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(1.0)
        self._close()

    def _close(self):
        global _active_stream
        with _cancel_lock:
            if _active_stream is self:
                _active_stream = None
        barge_in_ready.clear()
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                if not self._aborted.is_set():
                    stream.stop()
                stream.close()
            except Exception:
                pass


_manager = VoiceManager()


def warm_up_voice(settings: dict) -> bool:
    """Prepare speech without output; call from the serial speech worker."""
    return _manager.prepare(settings)


_prefetched: dict = {}
_prefetch_lock = threading.Lock()
_PREFETCH_WORKERS = 2


def _fish_voice_identity(config) -> tuple:
    """(voice id, speed) that a Fish piece is synthesized with."""
    try:
        speed = round(max(0.7, min(1.4, float(config.get("voice_speed", 1.0)))), 3)
    except (TypeError, ValueError):
        speed = 1.0
    return (str(config.get("fish_voice_id") or ""), speed)


def prefetch(text: str, language: str | None = None) -> None:
    """Prepare the next piece of speech in the background (Fish voice)."""
    try:
        _manager.prefetch(text, language)
    except Exception:
        pass


_voice_notices: list[str] = []
_voice_notice_lock = threading.Lock()
_voice_notice_shown: dict[str, float] = {}


def _note_voice_notice(code: str) -> None:
    """Something the user should know once (e.g. «Fish Audio refused the key»), not at every reply."""
    with _voice_notice_lock:
        last = _voice_notice_shown.get(code, 0.0)
        if time.monotonic() - last < 600 and last:
            return
        _voice_notice_shown[code] = time.monotonic()
        if code not in _voice_notices:
            _voice_notices.append(code)


def take_voice_notice() -> str:
    """The oldest notice not shown yet ("" when none): fish_auth, fish_payment, fish_missing, fish_unavailable."""
    with _voice_notice_lock:
        return _voice_notices.pop(0) if _voice_notices else ""


def speak(text: str, enabled: bool = True, language: str | None = None) -> bool:
    if not enabled:
        return False
    token = _cancel_token()
    playback_active.set()
    try:
        if _was_cancelled(token):
            return False
        return _manager.speak(text, language=language, cancel_token=token)
    finally:
        barge_in_ready.clear()
        playback_active.clear()


def available_voices() -> list[dict]:
    return _manager.available_voices()
