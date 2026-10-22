"""Local speech playback using Piper models, with language-aware Windows fallback.

Russian speech prefers the ru_RU-dmitri-medium neural voice even if other
Piper models are installed. Never substitute an English SAPI voice for Russian.
Voice failures are written to voice_error.log because the app uses pythonw.exe.
"""
from __future__ import annotations

import base64
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

import sounddevice as sd

ROOT = Path(__file__).resolve().parents[1]
VOICES_DIR = ROOT / "voices"
CONFIG_PATH = ROOT / "config.json"
ERROR_LOG = ROOT / "voice_error.log"
playback_active = threading.Event()

DEFAULT_RUSSIAN = "ru_RU-dmitri-medium"
PIPER_BASE_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
    "ru/ru_RU/dmitri/medium/"
)


class VoiceManager:
    """Select and play voices matching the assistant's configured language."""

    def __init__(self):
        self._voice = None
        self._loaded_path = None
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

    def _download_russian_voice(self) -> Path | None:
        """Download Dmitri's local Russian Piper model if it is missing."""
        VOICES_DIR.mkdir(parents=True, exist_ok=True)
        model_path = VOICES_DIR / f"{DEFAULT_RUSSIAN}.onnx"
        metadata_path = VOICES_DIR / f"{DEFAULT_RUSSIAN}.onnx.json"
        files = (
            (model_path, 10_000_000),
            (metadata_path, 100),
        )
        if all(p.is_file() and p.stat().st_size >= size for p, size in files):
            return model_path
        for path, minimum_size in files:
            if path.is_file() and path.stat().st_size >= minimum_size:
                continue
            temporary = path.with_name(path.name + ".download")
            try:
                request = urllib.request.Request(
                    PIPER_BASE_URL + path.name,
                    headers={"User-Agent": "JarvisLocalAssistant/1.0"},
                )
                with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as dest:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        dest.write(chunk)
                if temporary.stat().st_size < minimum_size:
                    raise ValueError("Downloaded Russian voice model is incomplete")
                temporary.replace(path)
            except Exception as exc:
                temporary.unlink(missing_ok=True)
                self._log(f"Russian Piper download failed ({path.name}): {exc}")
                return None
        self._log("Russian Piper voice Dmitri installed.")
        return model_path

    def _select_model(self, language: str) -> Path | None:
        voices = self.available_voices()
        # An explicitly configured model remains a user choice.
        explicit = str(self.config.get("voice_model_path", "") or "").strip()
        if explicit:
            candidate = Path(explicit).expanduser()
            if candidate.is_file() and candidate.with_suffix(candidate.suffix + ".json").is_file():
                return candidate
            self._log(f"Configured Piper model not found: {explicit}")

        selected = str(self.config.get("voice_id", "") or "").strip().lower()
        if selected:
            for voice in voices:
                if voice["ready"] and voice["id"].lower() == selected:
                    if language != "ru" or voice["id"].lower().startswith("ru_"):
                        return Path(voice["model"])

        if language == "ru":
            # Never use an English model just because it appears first alphabetically.
            for voice in voices:
                if voice["ready"] and voice["id"].lower() == DEFAULT_RUSSIAN.lower():
                    return Path(voice["model"])
            for voice in voices:
                if voice["ready"] and voice["id"].lower().startswith("ru_"):
                    return Path(voice["model"])
            return self._download_russian_voice()

        prefixes = {"ro": "ro_", "en": "en_" }
        prefix = prefixes.get(language)
        if prefix:
            for voice in voices:
                if voice["ready"] and voice["id"].lower().startswith(prefix):
                    return Path(voice["model"])
        for voice in voices:
            if voice["ready"]:
                return Path(voice["model"])
        return None

    def _windows_speak(self, text: str, language: str) -> bool:
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
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=90,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0:
                return True
            self._log(
                "Windows SAPI unavailable for " + language + ": "
                + result.stderr.decode("utf-8", errors="replace")[:500]
            )
        except Exception as exc:
            self._log(f"Windows SAPI playback failed: {exc}")
        return False

    def speak(self, text: str, language: str | None = None) -> bool:
        text = re.sub(r"\s+", " ", str(text or "")).strip()[:700]
        if not text:
            return False
        # Settings can change while the application is running.
        self.config = self._load_config()
        language = (language or self.config.get("language", "ru") or "ru").lower()
        if language not in ("ru", "ro", "en"):
            language = "ru" if re.search(r"[а-яё]", text, flags=re.IGNORECASE) else "ro"

        voice_engine = str(self.config.get("voice_engine", "piper") or "piper").lower()
        if voice_engine == "windows":
            if self._windows_speak(text, language):
                return True
            self._log(f"Windows voice unavailable for {language}; choose Piper in settings.")
            return False

        model_path = self._select_model(language)
        if model_path is not None:
            try:
                if self._voice is None or self._loaded_path != str(model_path):
                    from piper import PiperVoice
                    self._voice = PiperVoice.load(str(model_path))
                    self._loaded_path = str(model_path)
                volume = max(0.0, min(1.0, float(self.config.get("voice_volume", 80)) / 100))
                speed = max(0.7, min(1.4, float(self.config.get("voice_speed", 1.0))))
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp:
                    wav_path = Path(temp.name)
                try:
                    with wave.open(str(wav_path), "wb") as wav_file:
                        try:
                            from piper.config import SynthesisConfig
                            self._voice.synthesize_wav(
                                text, wav_file,
                                syn_config=SynthesisConfig(length_scale=1.0 / speed),
                            )
                        except ImportError:
                            self._voice.synthesize_wav(text, wav_file)
                    import soundfile as sf
                    audio, sample_rate = sf.read(str(wav_path), dtype="float32")
                    sd.play(audio * volume, sample_rate)
                    sd.wait()
                    return True
                finally:
                    wav_path.unlink(missing_ok=True)
            except Exception as exc:
                self._log(f"Piper playback failed for {model_path.name}: {exc}")

        if self._windows_speak(text, language):
            return True
        self._log(
            f"No working {language} voice. Check voices/{DEFAULT_RUSSIAN}.onnx, "
            "the corresponding .onnx.json, sound output and voice_error.log."
        )
        return False


_manager = VoiceManager()


def speak(text: str, enabled: bool = True, language: str | None = None) -> bool:
    if not enabled:
        return False
    playback_active.set()
    try:
        return _manager.speak(text, language=language)
    finally:
        playback_active.clear()


def available_voices() -> list[dict]:
    return _manager.available_voices()
