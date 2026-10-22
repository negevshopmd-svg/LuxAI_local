"""Read and control the real Windows default playback volume using Core Audio.

Do not infer a percentage from model responses. Verify the actual endpoint
volume after setting it. Audio output may have a separate device volume:
this module operates on Windows default playback endpoint only.
"""
from __future__ import annotations

import sys


def _endpoint_volume():
    from pycaw.pycaw import AudioUtilities
    speakers = AudioUtilities.GetSpeakers()
    endpoint = getattr(speakers, "EndpointVolume", None)
    if endpoint is not None:
        return endpoint
    # Backwards compatibility with earlier pycaw releases.
    from ctypes import POINTER, cast
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import IAudioEndpointVolume
    return cast(
        speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None),
        POINTER(IAudioEndpointVolume),
    )


def windows_volume(value: int | None = None) -> int:
    """Return observed percentage; if setting, confirm actual endpoint level.

    Raises an explicit error instead of returning the requested level when the
    operating system or device rejects the change.
    """
    if sys.platform != "win32":
        raise OSError("Управление системной громкостью работает только на Windows.")
    import comtypes
    if value is not None and (type(value) is not int or not 0 <= value <= 100):
        raise ValueError("Громкость должна быть от 0 до 100%.")

    comtypes.CoInitialize()
    try:
        endpoint = _endpoint_volume()
        if endpoint is None:
            raise OSError("Windows не нашёл активное устройство вывода звука.")
        if value is not None:
            endpoint.SetMasterVolumeLevelScalar(value / 100.0, None)
        actual = float(endpoint.GetMasterVolumeLevelScalar())
    finally:
        comtypes.CoUninitialize()
    if not 0.0 <= actual <= 1.0:
        raise OSError("Windows вернул неправильную громкость.")
    observed = round(actual * 100)
    if value is not None and abs(observed - value) > 1:
        raise OSError(
            f"Запрошено {value}%, но Windows сообщает {observed}%."
        )
    return observed
