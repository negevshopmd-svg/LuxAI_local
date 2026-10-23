"""Official Piper model identifiers and verified download metadata.

UI settings can import these without loading sound drivers or the playback
runtime, which is important for application launch and offline test stubs.
"""
DEFAULT_RUSSIAN = "ru_RU-dmitri-medium"
DEFAULT_ROMANIAN = "ro_RO-mihai-medium"
DEFAULT_ENGLISH = "en_US-lessac-medium"
PIPER_REPOSITORY = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"

VOICE_PRESETS = {
    "ru": {
        "id": DEFAULT_RUSSIAN, "directory": "ru/ru_RU/dmitri/medium",
        "language": "ru_RU", "sha256": None,
    },
    "ro": {
        "id": DEFAULT_ROMANIAN, "directory": "ro/ro_RO/mihai/medium",
        "language": "ro_RO",
        "sha256": "e0608bbbd53c80267c09ece681b09f5199f54e792356684c8073738e5f15d29f",
    },
    "en": {
        "id": DEFAULT_ENGLISH, "directory": "en/en_US/lessac/medium",
        "language": "en_US",
        "sha256": "5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f",
    },
}
