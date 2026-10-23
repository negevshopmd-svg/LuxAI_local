"""Stable recording-endpoint selection without importing speech/model libraries."""
from __future__ import annotations


def resolve_microphone_device(device=-1, name="", hostapi="", *, backend=None):
    """Return ``(device_index_or_None, device_info)`` for the selected input.

    PortAudio numeric indices can change after a Bluetooth reconnect. Recover
    by the exact saved name and host API, and never silently switch to another
    microphone. ``None`` means the user explicitly selected the system default.
    """
    if backend is None:
        import sounddevice as backend
    if device in (-1, None, "", "-1"):
        requested = None
    else:
        try:
            requested = int(device)
        except (TypeError, ValueError):
            requested = str(device).strip()
    name = str(name or "").strip()

    if requested is None and not name:
        try:
            info = backend.query_devices(None, "input")
            if int(info.get("max_input_channels", 0)) <= 0:
                raise ValueError("No input channels")
        except (ValueError, TypeError, backend.PortAudioError) as exc:
            raise RuntimeError(
                "No default recording microphone is available. Connect your headset, "
                "select its recording microphone in Windows Sound settings, and allow "
                "desktop apps to access the microphone in Windows Privacy settings."
            ) from exc
        return None, dict(info)

    try:
        devices = list(backend.query_devices())
    except (ValueError, backend.PortAudioError) as exc:
        raise RuntimeError(
            "Cannot list recording devices. Check the Windows audio service and microphone permissions."
        ) from exc

    def matches_api(info):
        if hostapi in (None, ""):
            return True
        if isinstance(hostapi, int):
            return info.get("hostapi") == hostapi
        try:
            return backend.query_hostapis(info["hostapi"])["name"] == hostapi
        except (KeyError, TypeError, ValueError, backend.PortAudioError):
            return False

    saved_name = name or (requested if isinstance(requested, str) else "")
    if isinstance(requested, int) and 0 <= requested < len(devices):
        info = devices[requested]
        if (int(info.get("max_input_channels", 0)) > 0
                and (not saved_name or info.get("name") == saved_name)
                and matches_api(info)):
            return requested, dict(info)

    matches = [
        (index, info) for index, info in enumerate(devices)
        if saved_name and info.get("name") == saved_name
        and int(info.get("max_input_channels", 0)) > 0 and matches_api(info)
    ]
    if len(matches) == 1:
        index, info = matches[0]
        return index, dict(info)
    detail = (
        "Several input devices have that name" if matches
        else "The selected microphone is disconnected or is not a recording device"
    )
    raise RuntimeError(
        detail + ". Reconnect your wireless headset, refresh the microphone list "
        "in Jarvis Settings and select its microphone/input endpoint. Stereo/headphone "
        "playback endpoints cannot record your voice."
    )
