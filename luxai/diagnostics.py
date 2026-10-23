"""Offline, shareable health checks and an explicit microphone level probe.

Collecting a report never opens the microphone, downloads models, calls an AI
service, or reads credentials. The optional probe measures and discards input
buffers; it never stores or transcribes a recording.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import math
from pathlib import Path
import platform
import sys
import threading
import time

from luxai.audio_devices import resolve_microphone_device


DEPENDENCIES = {
    "PySide6": "PySide6",
    "sounddevice": "sounddevice",
    "numpy": "numpy",
    "faster-whisper": "faster_whisper",
    "piper-tts": "piper",
    "mss": "mss",
    "Pillow": "PIL",
    "llama-cpp-python": "llama_cpp",
}
STANDARD_WHISPER_MODELS = {
    "tiny", "tiny.en", "base", "base.en", "small", "small.en",
    "medium", "medium.en", "large", "large-v1", "large-v2", "large-v3",
    "large-v3-turbo", "distil-large-v2", "distil-large-v3",
}


def _device_index(value):
    if value in (None, "", -1, "-1"):
        return None
    if isinstance(value, bool):
        raise ValueError("A microphone index must be an integer.")
    result = int(value)
    if result < 0 or (isinstance(value, float) and result != value):
        raise ValueError("A microphone index must be a nonnegative integer.")
    return result


def _error(exception: Exception) -> str:
    # Driver exceptions can embed usernames, paths and arbitrary config values.
    # Only the exception class is suitable for an exported health report.
    return type(exception).__name__


def _input_inventory(sd) -> dict:
    result = {"available": False, "default_device": None, "devices": [], "error": None}
    try:
        try:
            default = _device_index(sd.default.device[0])
        except (AttributeError, IndexError, TypeError, ValueError):
            default = None
        result["default_device"] = default
        hostapis = sd.query_hostapis()
        for index, item in enumerate(sd.query_devices()):
            channels = int(item.get("max_input_channels", 0))
            if channels <= 0:
                continue
            api_index = int(item.get("hostapi", -1))
            api = hostapis[api_index].get("name", "Unknown") if 0 <= api_index < len(hostapis) else "Unknown"
            result["devices"].append({
                "index": index,
                "name": str(item.get("name", "Unknown"))[:200],
                "hostapi": str(api)[:100],
                "input_channels": channels,
                "default_sample_rate": float(item.get("default_samplerate", 0)),
                "is_default": index == default,
            })
        result["available"] = bool(result["devices"])
    except Exception as exc:
        result["error"] = _error(exc)
    return result


def collect_diagnostics(config: dict | None = None) -> dict:
    """Return offline health metadata with no credentials or personal paths.

    ``config`` is optional and only a fixed set of recognition settings is read.
    Installed versions are metadata checks, not proof of working inference or
    a successful driver stream; ``microphone_probe`` performs that separate test.
    """
    config = config if isinstance(config, dict) else {}
    report = {
        "report_version": 1,
        "runtime": {
            "python": platform.python_version(),
            "system": platform.system(),
            "release": platform.release(),
            "architecture": platform.machine(),
            "bits": 64 if sys.maxsize > 2**32 else 32,
        },
        "dependencies": {},
        "microphone": {},
        "ocr": {"ready": False, "engine_found": False, "languages_verified": False, "error": None},
    }
    try:
        version_file = Path(__file__).resolve().parents[1] / "version.txt"
        report["application_version"] = version_file.read_text(encoding="utf-8").strip()[:80]
    except OSError:
        report["application_version"] = None

    for distribution, module in DEPENDENCIES.items():
        try:
            version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            version = None
        except Exception:
            version = None
        try:
            discoverable = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError, AttributeError):
            discoverable = False
        report["dependencies"][distribution] = {"version": version, "module_found": discoverable}

    audio_backend = None
    try:
        import sounddevice as sd
        audio_backend = sd
        report["microphone"] = _input_inventory(sd)
    except Exception as exc:
        report["microphone"] = {
            "available": False, "default_device": None, "devices": [], "error": _error(exc),
        }
    try:
        selected = _device_index(config.get("microphone_device"))
    except (TypeError, ValueError, OverflowError):
        selected = None
        report["microphone"]["selection_error"] = "Invalid microphone index"
    report["microphone"]["selected_device"] = selected
    if selected is not None or config.get("microphone_name"):
        report["microphone"]["selected_device_present"] = False
        if audio_backend is not None:
            try:
                resolved, _ = resolve_microphone_device(
                    selected, name=config.get("microphone_name", ""),
                    hostapi=config.get("microphone_hostapi", ""), backend=audio_backend,
                )
                report["microphone"]["resolved_device"] = resolved
                report["microphone"]["selected_device_present"] = True
            except Exception as exc:
                report["microphone"]["selection_error"] = _error(exc)

    model = str(config.get("whisper_model", "small"))
    language = config.get("language", "auto")
    report["recognition"] = {
        "language": language if isinstance(language, str) and language in {"auto", "ru", "ro", "en"} else "other",
        "model": model if model in STANDARD_WHISPER_MODELS and not config.get("whisper_model_path") else "local/custom",
        "prefix_enabled": bool(config.get("prefix_enabled", False)),
        "microphone_enabled": bool(config.get("microphone_enabled", True)),
    }
    try:
        sensitivity = float(config.get("microphone_sensitivity", 1.0))
        if math.isfinite(sensitivity):
            report["recognition"]["microphone_sensitivity"] = max(0.25, min(4.0, sensitivity))
    except (TypeError, ValueError, OverflowError):
        pass

    try:
        from luxai.ocr_setup import find_tesseract, language_data_ready, verify_tesseract
        binary = find_tesseract()
        report["ocr"]["engine_found"] = binary is not None
        report["ocr"]["languages_verified"] = language_data_ready()
        if binary is not None and report["ocr"]["languages_verified"]:
            ready, _ = verify_tesseract(binary)
            report["ocr"]["ready"] = bool(ready)
    except Exception as exc:
        report["ocr"]["error"] = _error(exc)
    return report


def microphone_probe(device=None, duration=3.0, level_callback=None, stop_event=None,
                     microphone_name="", microphone_hostapi="") -> dict:
    """Measure input levels without Whisper, retaining no recording.

    Only the requested device (or the actual OS default for ``None``/``-1``)
    is opened. A rate fallback stays on that same device. Capture is capped at
    ten seconds and cancellation is checked while waiting for driver buffers.
    ``level_callback`` receives RMS in the 0..1 range at most ten times/second.
    """
    result = {
        "ok": False, "device": None, "sample_rate": None, "duration_seconds": 0.0,
        "frames": 0, "peak": 0.0, "rms": 0.0, "silent": True, "clipped": False,
        "cancelled": False, "input_overflows": 0, "error": None,
    }
    cancel = stop_event if stop_event is not None else threading.Event()
    try:
        selected = _device_index(device)
        duration = float(duration)
        if not math.isfinite(duration) or duration < 0.1:
            raise ValueError("Probe duration must be at least 0.1 seconds.")
        duration = min(10.0, duration)
        result["device"] = selected
        result["requested_duration_seconds"] = duration
        if cancel.is_set():
            result["cancelled"] = True
            return result

        import numpy as np
        import sounddevice as sd
        selected, info = resolve_microphone_device(
            selected, name=microphone_name, hostapi=microphone_hostapi, backend=sd,
        )
        result["device"] = selected
        if int(info.get("max_input_channels", 0)) < 1:
            raise ValueError("The selected device has no input channels.")
        rate = 16000
        try:
            sd.check_input_settings(device=selected, samplerate=rate, channels=1, dtype="float32")
        except Exception:
            rate = int(round(float(info["default_samplerate"])))
            if rate < 8000 or rate > 384000:
                raise ValueError("The selected device has an invalid sample rate.")
            sd.check_input_settings(device=selected, samplerate=rate, channels=1, dtype="float32")
        result["sample_rate"] = rate
        state = {"frames": 0, "sum_squares": 0.0, "peak": 0.0, "clipped": False,
                 "last_level": -math.inf, "input_overflows": 0, "error": None}
        lock = threading.Lock()

        def capture(indata, frames, time_info, status):
            if cancel.is_set():
                return
            try:
                samples = np.asarray(indata, dtype=np.float64)
                if not np.all(np.isfinite(samples)):
                    raise ValueError("Non-finite audio samples")
                count = samples.size
                if not count:
                    return
                squared = float(np.sum(samples * samples))
                peak = float(np.max(np.abs(samples)))
                rms = min(1.0, math.sqrt(squared / count))
                now = time.monotonic()
                with lock:
                    state["frames"] += count
                    state["sum_squares"] += squared
                    state["peak"] = max(state["peak"], peak)
                    state["clipped"] = state["clipped"] or peak >= 0.99
                    state["input_overflows"] += int(bool(getattr(status, "input_overflow", False)))
                    notify = now - state["last_level"] >= 0.1
                    if notify:
                        state["last_level"] = now
                if notify and level_callback is not None:
                    try:
                        level_callback(rms)
                    except Exception:
                        pass
            except Exception as exc:
                with lock:
                    state["error"] = _error(exc)

        with sd.InputStream(device=selected, samplerate=rate, channels=1, dtype="float32",
                            blocksize=max(1, rate // 20), callback=capture):
            started = time.monotonic()
            while not cancel.is_set():
                with lock:
                    complete = state["frames"] >= int(rate * duration) or state["error"] is not None
                remaining = duration - (time.monotonic() - started)
                if complete or remaining <= 0:
                    break
                cancel.wait(min(0.05, remaining))
        with lock:
            frames = state["frames"]
            result.update({
                "frames": frames,
                "duration_seconds": round(frames / rate, 3),
                "peak": round(state["peak"], 6),
                "rms": round(math.sqrt(state["sum_squares"] / frames), 6) if frames else 0.0,
                "clipped": state["clipped"],
                "input_overflows": state["input_overflows"],
                "error": state["error"],
            })
        result["cancelled"] = bool(cancel.is_set())
        result["silent"] = result["rms"] < 0.0001 and result["peak"] < 0.001
        if not frames and result["error"] is None and not result["cancelled"]:
            result["error"] = "No audio frames received"
        result["ok"] = bool(frames and result["error"] is None and not result["cancelled"])
    except Exception as exc:
        result["error"] = _error(exc)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--microphone", action="store_true", help="Explicitly measure microphone levels; no recording is saved")
    parser.add_argument("--device", type=int, default=None, help="Input device index from the report; default uses OS input")
    parser.add_argument("--duration", type=float, default=3.0, help="Probe seconds (0.1 to 10; longer requests are capped)")
    args = parser.parse_args(argv)
    report = collect_diagnostics()
    if args.microphone:
        report["microphone_probe"] = microphone_probe(device=args.device, duration=args.duration)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.microphone and not report["microphone_probe"]["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
