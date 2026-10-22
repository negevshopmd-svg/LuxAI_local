"""Direct real-weather forecast (Open-Meteo) independent of Gemini quotas.

Never asks an LLM to invent temperatures. HTTPS requests only to known
Open-Meteo domains. The model does not receive API credentials or location
data for this action. Network failures are returned as errors, not forecasts.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import re
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

OPEN_METEO_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
CITY_VARIANTS = (
    "кишин", "кишн", "chisin", "chișin", "chişin", "kishin", "kishinev",
)
CHISINAU = (47.0105, 28.8638, "Кишинёв")
WEATHER_RE = re.compile(
    r"\b(?:погод[аыуеой]|прогноз|weather|meteo|vreme[ai]?)\b", re.I
)
TOMORROW_RE = re.compile(r"\b(?:завтра|tomorrow|mâine|maine)\b", re.I)
TODAY_RE = re.compile(r"\b(?:сегодня|today|astăzi|astazi|azi)\b", re.I)
WMO_RU = {
    0: "ясно", 1: "преимущественно ясно", 2: "переменная облачность",
    3: "пасмурно", 45: "туман", 48: "изморозь",
    51: "слабая морось", 53: "морось", 55: "сильная морось",
    56: "переохлаждённая морось", 57: "переохлаждённая морось",
    61: "слабый дождь", 63: "дождь", 65: "сильный дождь",
    66: "ледяной дождь", 67: "сильный ледяной дождь",
    71: "слабый снег", 73: "снег", 75: "сильный снег",
    77: "снежная крупа", 80: "кратковременный дождь",
    81: "ливни", 82: "сильные ливни", 85: "снегопад",
    86: "сильный снегопад", 95: "гроза",
    96: "гроза с градом", 99: "сильная гроза с градом",
}


def is_weather_question(text: str) -> bool:
    return bool(WEATHER_RE.search(str(text or "")))


def _city_name(text: str) -> str:
    """Read named city in Russian; if absent use user's configured city."""
    content = str(text or "").casefold()
    if any(word in content for word in CITY_VARIANTS):
        return "Кишинёв"
    # Match a geographic "в <city>" after phrases about weather.
    cities = re.findall(
        r"\b(?:в|во|для|in|în)\s+([\wÀ-ÿА-Яа-яЁё -]{2,48})",
        content, re.I,
    )
    if cities:
        name = cities[-1].strip(" .,?!")
        name = re.split(r"\s+(?:сегодня|завтра|будет|сейчас|утром|вечером)\b", name)[0].strip()
        if name and name not in {"городе", "моем городе", "город", "городе кишинёве"}:
            return name.title()
    return "Кишинёв"


def parse_weather_request(text: str, default_city="Кишинёв"):
    if not is_weather_question(text):
        return None
    city = _city_name(text)
    if city == "Кишинёв" and not any(s in str(text).casefold() for s in CITY_VARIANTS):
        city = default_city or city
    day_offset = 1 if TOMORROW_RE.search(text) else 0
    return {"city": city, "days": day_offset}


def _get_json(url: str, *, timeout=7):
    allowed = {
        "api.open-meteo.com",
        "geocoding-api.open-meteo.com",
    }
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in allowed:
        raise ValueError("Недопустимый адрес погодного сервиса")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "JarvisLocalAssistant/Weather-v1", "Accept": "application/json"},
    )
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            raise urllib.error.HTTPError(request.full_url, code, "Redirect blocked", headers, fp)
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        if response.status != 200:
            raise OSError(f"Open-Meteo HTTP {response.status}")
        return json.loads(response.read(128 * 1024))


def _coordinates(city: str):
    if city.casefold() in {"кишинёв", "кишинев", "chisinau", "chișinău", "chisinău"}:
        return CHISINAU
    query = urllib.parse.urlencode({
        "name": city, "count": 5, "language": "ru", "format": "json",
    })
    payload = _get_json(OPEN_METEO_GEOCODE + "?" + query)
    places = payload.get("results") or []
    if not places:
        raise ValueError(f"Город «{city}» не найден в погодном сервисе")
    first = places[0]
    return float(first["latitude"]), float(first["longitude"]), str(first["name"])


def get_weather_report(text: str, *, default_city="Кишинёв") -> str | None:
    requested = parse_weather_request(text, default_city=default_city)
    if not requested:
        return None
    city = requested["city"]
    offset = requested["days"]
    lat, lon, city_label = _coordinates(city)
    query = urllib.parse.urlencode({
        "latitude": round(lat, 5),
        "longitude": round(lon, 5),
        "daily": (
            "weather_code,temperature_2m_min,temperature_2m_max,"
            "precipitation_probability_max,wind_speed_10m_max"
        ),
        "timezone": "auto",
        "forecast_days": 3,
    })
    data = _get_json(OPEN_METEO_FORECAST + "?" + query)
    dates = data.get("daily", {})
    zone = ZoneInfo(data.get("timezone", "Europe/Chisinau"))
    date = (datetime.now(zone).date() + timedelta(days=offset)).isoformat()
    try:
        pos = dates["time"].index(date)
        low = dates["temperature_2m_min"][pos]
        high = dates["temperature_2m_max"][pos]
        probability = dates["precipitation_probability_max"][pos]
        code = dates["weather_code"][pos]
        wind = dates.get("wind_speed_10m_max", [None] * len(dates["time"]))[pos]
    except (KeyError, ValueError, TypeError, IndexError) as error:
        raise ValueError("Нет проверенных данных прогноза для нужной даты") from error

    if not all(isinstance(x, (int, float)) for x in (low, high, probability, code)):
        raise ValueError("Прогноз содержит неполные данные")
    condition = WMO_RU.get(int(code), "переменная погода")
    tag = "Завтра" if offset else "Сегодня"
    result = (
        f"{tag}, {date}, в городе {city_label}: {condition}. "
        f"Температура от {round(low)} до {round(high)} °C. "
        f"Вероятность осадков до {round(probability)}%."
    )
    if isinstance(wind, (int, float)):
        result += f" Ветер до {round(wind)} км/ч."
    return result + " Источник: Open-Meteo (актуальный прогноз)."
