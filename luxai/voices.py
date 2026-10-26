"""Local speech playback using Piper models, with language-aware Windows fallback.

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
# downloads or synthesizes speech. The microphone may listen for "stop" then.
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


def stop_speaking() -> None:
    """Interrupt current Piper or SAPI playback immediately (no thread kill)."""
    global _cancel_generation
    with _cancel_lock:
        _cancel_generation += 1
        process = _sapi_process
        barge_in_ready.clear()
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
    DEFAULT_RUSSIAN, DEFAULT_ROMANIAN, DEFAULT_ENGLISH,
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
        if str(snapshot.get("voice_engine", "piper") or "piper").lower() == "windows":
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


_manager = VoiceManager()


def warm_up_voice(settings: dict) -> bool:
    """Prepare speech without output; call from the serial speech worker."""
    return _manager.prepare(settings)


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
