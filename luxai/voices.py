"""Extensible local neural voices for LuxAI.

Put Piper voice files (.onnx and matching .onnx.json) in the voices/ directory.
No Windows system TTS is used. Add more model files to make more voices available.
"""
from __future__ import annotations

import json
import re
import wave
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
        return None

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
            return False

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
            return False


_manager = VoiceManager()


def speak(text: str, enabled: bool = True) -> bool:
    """Public compatibility function used by the app."""
    if not enabled:
        return False
    return _manager.speak(text)


def available_voices() -> list[dict]:
    """Return installed voice models for a future voice-selection UI."""
    return _manager.available_voices()
