"""UI copy for cloud connection status in Russian, English and Romanian.

Success means a real chat completion request succeeded in this session, not
merely that a key exists.
"""
from __future__ import annotations

COLORS = {"online": "#3dbb77", "checking": "#c6a35f", "unchecked": "#c6a35f",
          "disabled": "#c6a35f", "offline": "#d36f6f", "missing": "#d36f6f"}


def cloud_status_text(state: str, provider: str, language: str = "ru",
                      detail: str = "") -> tuple[str, str, str]:
    language = language if language in {"ru", "en", "ro"} else "ru"
    lines = {
        "ru": {
            "online": ("●  Облачный AI работает", "{provider}: API ответил на проверку."),
            "checking": ("●  Облачный AI: проверка…", "Подключение к {provider}…"),
            "unchecked": ("●  Облачный AI: не проверен", "{provider}: ключ найден, соединение не проверено."),
            "disabled": ("●  Облачный AI выключен", "Включите облачный помощник в настройках."),
            "missing": ("●  Облачный AI: нет ключа", "Сохраните API-ключ в настройках."),
            "offline": ("●  Облачный AI недоступен", "Проверка подключения не прошла."),
        },
        "en": {
            "online": ("●  Cloud AI works", "{provider}: real API check succeeded."),
            "checking": ("●  Checking cloud AI…", "Connecting to {provider}…"),
            "unchecked": ("●  Cloud AI not verified", "{provider}: key found, connection not yet tested."),
            "disabled": ("●  Cloud AI disabled", "Enable cloud assistant in Settings."),
            "missing": ("●  Cloud AI: no API key", "Save your API key in Settings."),
            "offline": ("●  Cloud AI unavailable", "The connection test failed."),
        },
        "ro": {
            "online": ("●  AI cloud funcționează", "{provider}: verificarea API a reușit."),
            "checking": ("●  Verific AI cloud…", "Mă conectez la {provider}…"),
            "unchecked": ("●  AI cloud neverificat", "{provider}: cheia există, conexiunea nu a fost testată."),
            "disabled": ("●  AI cloud dezactivat", "Activează asistentul cloud în Setări."),
            "missing": ("●  AI cloud: lipsește cheia", "Salvează cheia API în Setări."),
            "offline": ("●  AI cloud indisponibil", "Testul conexiunii a eșuat."),
        },
    }
    title, body = lines[language].get(state, lines[language]["unchecked"])
    if state == "offline" and detail:
        return title, f"{provider}: {detail}", COLORS["offline"]
    if state == "missing" and detail:
        body = detail
    return title, body.format(provider=provider), COLORS.get(state, COLORS["unchecked"])
