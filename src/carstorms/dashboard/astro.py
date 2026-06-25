"""Sun/moon helpers — moon phase (computed) and weather-code descriptions."""

from __future__ import annotations

import math
from datetime import UTC, datetime

_SYNODIC_MONTH = 29.530588853
# A known new moon: 2000-01-06 18:14 UTC.
_KNOWN_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=UTC)

_PHASES = [
    (0.033, "New Moon", "🌑"),
    (0.216, "Waxing Crescent", "🌒"),
    (0.283, "First Quarter", "🌓"),
    (0.466, "Waxing Gibbous", "🌔"),
    (0.533, "Full Moon", "🌕"),
    (0.716, "Waning Gibbous", "🌖"),
    (0.783, "Last Quarter", "🌗"),
    (0.966, "Waning Crescent", "🌘"),
    (1.001, "New Moon", "🌑"),
]


def moon_phase(now: datetime | None = None) -> dict[str, object]:
    """Approximate moon phase, illumination % and age in days."""
    now = now or datetime.now(UTC)
    days = (now - _KNOWN_NEW_MOON).total_seconds() / 86400.0
    age = days % _SYNODIC_MONTH
    fraction = age / _SYNODIC_MONTH  # 0 = new, 0.5 = full
    illumination = round((1 - math.cos(2 * math.pi * fraction)) / 2 * 100)
    name, emoji = next((n, e) for thr, n, e in _PHASES if fraction <= thr)
    return {
        "name": name,
        "emoji": emoji,
        "illumination_pct": illumination,
        "age_days": round(age, 1),
    }


# WMO weather interpretation codes -> short label + emoji.
WMO_CODES: dict[int, tuple[str, str]] = {
    0: ("Clear", "☀️"),
    1: ("Mainly clear", "🌤️"),
    2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁️"),
    45: ("Fog", "🌫️"),
    48: ("Rime fog", "🌫️"),
    51: ("Light drizzle", "🌦️"),
    53: ("Drizzle", "🌦️"),
    55: ("Heavy drizzle", "🌧️"),
    61: ("Light rain", "🌦️"),
    63: ("Rain", "🌧️"),
    65: ("Heavy rain", "🌧️"),
    66: ("Freezing rain", "🌧️"),
    67: ("Freezing rain", "🌧️"),
    71: ("Light snow", "🌨️"),
    73: ("Snow", "🌨️"),
    75: ("Heavy snow", "❄️"),
    80: ("Rain showers", "🌦️"),
    81: ("Rain showers", "🌧️"),
    82: ("Violent showers", "⛈️"),
    95: ("Thunderstorm", "⛈️"),
    96: ("Thunderstorm + hail", "⛈️"),
    99: ("Severe thunderstorm", "⛈️"),
}


def describe_weather(code: int | None) -> dict[str, str]:
    label, emoji = WMO_CODES.get(int(code) if code is not None else -1, ("—", "❔"))
    return {"label": label, "emoji": emoji}


def uv_risk(uv: float | None) -> str:
    if uv is None:
        return "unknown"
    if uv >= 11:
        return "extreme"
    if uv >= 8:
        return "very high"
    if uv >= 6:
        return "high"
    if uv >= 3:
        return "moderate"
    return "low"
