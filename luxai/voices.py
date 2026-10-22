"""Extensible local neural voices for LuxAI.

Put Piper voice files (.onnx and matching .onnx.json) in the voices/ directory.
No Windows system TTS is used. Add more model files to make more voices available.
"""
from __future__ import annotations

import json
import re
import base64
import subprocess
import sys
import wave
import urllib.request
from pathlib import Path

import sounddevice as sd

ROOT = Path(__file__).resolve().parents[1]
VOICES_DIR = ROOT / "voices"
CONFIG_PATH = ROOT / "config.json"


class VoiceManager:
    """Load and play local Piper neural voices, with an extensible voice catalogue."""

    def __init__(self):
        self._voice = None
        self._loaded_path = None
        self._piper_voice_class = None
        self.config = self._load_config()

    @staticmethod
    def _load_config() -> dict:
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

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

    def _download_default_voice(self) -> Path | None:
        """Install a default masculine Russian Piper voice on first use if none exists."""
        model_name = "ru_RU-dmitri-medium"
        model_path = VOICES_DIR / f"{model_name}.onnx"
        metadata_path = VOICES_DIR / f"{model_name}.onnx.json"
        if model_path.is_file() and metadata_path.is_file():
            return model_path
        VOICES_DIR.mkdir(parents=True, exist_ok=True)
        base_url = (
            "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
            "ru/ru_RU/dmitri/medium/"
        )
        for filename, destination, minimum_size in (
            (f"{model_name}.onnx", model_path, 1_000_000),
            (f"{model_name}.onnx.json", metadata_path, 100),
        ):
            if destination.is_file() and destination.stat().st_size >= minimum_size:
                continue
            temporary = destination.with_suffix(destination.suffix + ".download")
            try:
                request = urllib.request.Request(
                    base_url + filename,
                    headers={"User-Agent": "JarvisLocalAssistant/1.0"},
                )
                with urllib.request.urlopen(request, timeout=30) as response, temporary.open("wb") as out:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                if temporary.stat().st_size < minimum_size:
                    raise ValueError("Descărcarea modelului vocal este incompletă.")
                temporary.replace(destination)
            except Exception as exc:
                temporary.unlink(missing_ok=True)
                print(f"Nu am putut descărca vocea masculină implicită Piper: {exc}")
                return None
        print("Vocea masculină rusă Piper a fost instalată local.")
        return model_path

    def _select_model(self) -> Path | None:
        # Allow an explicit model path, otherwise use the configured voice name,
        # then a conventional jarvis model name, then the first installed voice.
        explicit = str(self.config.get("voice_model_path", "") or "").strip()
        if explicit:
            path = Path(explicit).expanduser()
            return path if path.is_file() else None

        voices = self.available_voices()
        selected = str(self.config.get("voice_id", "jarvis") or "jarvis").strip().lower()
        for item in voices:
            if item["id"].lower() == selected and item["ready"]:
                return Path(item["model"])
        for item in voices:
            if item["id"].lower() == "jarvis" and item["ready"]:
                return Path(item["model"])
        for item in voices:
            if item["ready"]:
                return Path(item["model"])
        # Default to a natural masculine Russian voice when the app has no voice installed.
        return self._download_default_voice()

    @staticmethod
    def _windows_speak(text: str) -> bool:
        """Fallback to installed Windows SAPI voices when Piper is unavailable."""
        if sys.platform != "win32":
            return False
        encoded = base64.b64encode(text.encode("utf-16-le")).decode("ascii")
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.SetOutputToDefaultAudioDevice(); "
            "$v=$s.GetInstalledVoices() | Where-Object {"
            "$_.VoiceInfo.Gender -eq 'Male' -and $_.VoiceInfo.Culture.Name -like 'ru-*'"
            "} | Select-Object -First 1; "
            "if (-not $v) {$v=$s.GetInstalledVoices() | Where-Object {"
            "$_.VoiceInfo.Gender -eq 'Male'"
            "} | Select-Object -First 1}; "
            "if ($v) {$s.SelectVoice($v.VoiceInfo.Name)}; "
            "$t=[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('" + encoded + "')); "
            "$s.Speak($t); $s.Dispose()"
        )
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0:
                return True
            print("Windows TTS error:", result.stderr.decode("utf-8", errors="replace")[:400])
        except Exception as exc:
            print(f"Windows TTS unavailable: {exc}")
        return False

    def speak(self, text: str) -> bool:
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        if not text:
            return False
        text = text[:700]
        model_path = self._select_model()
        if model_path is None:
            print(
                "Vocea neurală nu este instalată. Pune un model Piper .onnx și fișierul "
                "său .onnx.json în folderul 'voices'. Nu se folosește vocea Windows."
            )
            return self._windows_speak(text)

        try:
            if self._voice is None or self._loaded_path != str(model_path):
                from piper import PiperVoice
                self._piper_voice_class = PiperVoice
                self._voice = PiperVoice.load(str(model_path))
                self._loaded_path = str(model_path)

            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp:
                wav_path = Path(temp.name)
            try:
                with wave.open(str(wav_path), "wb") as wav_file:
                    self._voice.synthesize_wav(text, wav_file)
                import soundfile as sf
                audio, sample_rate = sf.read(str(wav_path), dtype="float32")
                sd.play(audio, sample_rate)
                sd.wait()
            finally:
                wav_path.unlink(missing_ok=True)
            return True
        except Exception as exc:
            print(f"Eroare la redarea vocii neurale: {exc}")
            return self._windows_speak(text)


_manager = VoiceManager()


def speak(text: str, enabled: bool = True) -> bool:
    """Public compatibility function used by the app."""
    if not enabled:
        return False
    return _manager.speak(text)


def available_voices() -> list[dict]:
    """Return installed voice models for a future voice-selection UI."""
    return _manager.available_voices()
