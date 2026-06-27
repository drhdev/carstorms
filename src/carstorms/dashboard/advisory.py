"""Deterministic, explainable activity advice for St. John conditions.

The scorer deliberately uses smooth 0--100 suitability curves rather than a
collection of prose-only rules.  Every activity declares its factor weights;
hazardous conditions then apply explicit safety caps.  This keeps two equally
forecast days comparable while still preventing an attractive temperature from
masking lightning, unsafe seas, or a beach-water advisory.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from statistics import fmean
from typing import Any

AST = timezone(timedelta(hours=-4))


@dataclass(frozen=True)
class Activity:
    key: str
    name: str
    emoji: str
    factors: tuple[tuple[str, float], ...]
    marine: bool = False
    strenuous: bool = False
    outdoor: bool = True


ACTIVITIES = (
    Activity("beach", "Beach time", "🏖️", (("dry", 24), ("warm", 18), ("uv", 12), ("gentle_wind", 10), ("shore", 8), ("sargassum", 23), ("air", 5))),
    Activity("swim", "Swimming in the sea", "🏊", (("swim_sea", 31), ("sea_temp", 14), ("calm_wind", 10), ("dry", 8), ("sargassum", 18), ("water_quality", 14), ("air", 5)), marine=True),
    Activity("snorkel", "Snorkeling", "🤿", (("snorkel_sea", 34), ("calm_wind", 15), ("marine_visibility", 14), ("sea_temp", 10), ("dry", 7), ("sargassum", 10), ("water_quality", 10)), marine=True),
    Activity("dive", "Scuba diving", "🫧", (("dive_sea", 30), ("boat_wind", 15), ("marine_visibility", 18), ("sea_temp", 12), ("dry", 5), ("sargassum", 5), ("water_quality", 10), ("air", 5)), marine=True),
    Activity("paddle", "Kayak / paddleboard", "🛶", (("paddle_sea", 34), ("calm_wind", 25), ("dry", 15), ("warm", 8), ("uv", 8), ("sargassum", 5), ("air", 5)), marine=True, strenuous=True),
    Activity("boat", "Boat trip", "🚤", (("boat_sea", 31), ("boat_wind", 24), ("dry", 17), ("warm", 10), ("uv", 7), ("air", 6), ("sargassum", 5)), marine=True),
    Activity("sail", "Sailing", "⛵", (("sail_wind", 36), ("sail_sea", 28), ("dry", 14), ("warm", 8), ("uv", 5), ("air", 5), ("sargassum", 4)), marine=True),
    Activity("bvi", "BVI day charter", "🇻🇬", (("boat_sea", 31), ("boat_wind", 24), ("dry", 18), ("warm", 8), ("uv", 7), ("air", 5), ("sargassum", 7)), marine=True),
    Activity("tennis", "Tennis", "🎾", (("dry", 34), ("exercise_heat", 25), ("tennis_wind", 20), ("uv", 16), ("air", 5)), strenuous=True),
    Activity("hike", "National Park hike", "🥾", (("dry", 29), ("exercise_heat", 27), ("uv", 19), ("humidity", 10), ("gentle_wind", 7), ("air", 8)), strenuous=True),
    Activity("outdoor_meal", "Long outdoor meal", "🍽️", (("dry", 32), ("warm", 23), ("gentle_wind", 16), ("humidity", 9), ("shade_uv", 8), ("air", 12))),
    Activity("wellness", "Indoor wellness", "🧘", (("indoor_weather", 55), ("air", 15), ("indoor_heat_relief", 30)), outdoor=False),
)


def build_activity_advisory(
    forecast: Any,
    marine: Any,
    air: dict[str, Any],
    sargassum: dict[str, Any],
    beaches: dict[str, Any],
    alerts: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Return morning/afternoon recommendations from source payloads."""
    if not forecast or not (forecast.get("hourly") or {}).get("time"):
        return {"available": False, "reason": "hourly forecast unavailable"}

    local_now = now.astimezone(AST)
    periods = []
    for key, label, start, end in (
        ("morning", "Morning", 6, 12),
        ("afternoon", "Afternoon", 12, 18),
    ):
        metrics = _period_metrics(
            forecast,
            marine,
            air,
            sargassum,
            beaches,
            alerts,
            local_now.date().isoformat(),
            start,
            end,
        )
        if metrics is None:
            continue
        scored = [_score_activity(activity, metrics) for activity in ACTIVITIES]
        meal_name = "Long breakfast outdoors" if key == "morning" else "Long lunch / early dinner"
        for item in scored:
            if item["key"] == "outdoor_meal":
                item["name"] = meal_name
        scored.sort(key=lambda item: (-item["score"], item["name"]))
        best = scored[:3]
        caution = sorted(
            (item for item in scored if item["score"] < 55),
            key=lambda item: (item["score"], item["name"]),
        )[:3]
        periods.append(
            {
                "key": key,
                "label": label,
                "time": f"{start}:00-{end}:00",
                "summary": _conditions_summary(metrics),
                "best": best,
                "caution": caution,
                "all": scored,
                "confidence": _confidence(metrics),
                "safety_note": _safety_note(metrics),
            }
        )
    if not periods:
        return {"available": False, "reason": "today's hourly forecast unavailable"}
    return {
        "available": True,
        "date": local_now.date().isoformat(),
        "periods": periods,
        "method": "Weighted 0-100 suitability by activity; lightning, unsafe seas, and water advisories apply safety caps.",
        "methodology": [
            "Every activity uses published factor weights totaling 100%. A weighted average produces its base score.",
            "Weather factors use continuous suitability curves, so small forecast changes cause small score changes.",
            "Lightning caps exposed activities at 10-15; active marine alerts cap water activities at 20.",
            "Rough seas, strong gusts, and beach-water advisories apply activity-specific safety caps.",
            "85-100 excellent, 70-84 good, 55-69 fair, 35-54 poor, 0-34 avoid.",
        ],
    }


def _period_metrics(
    forecast: dict[str, Any],
    marine: dict[str, Any] | None,
    air: dict[str, Any],
    sargassum: dict[str, Any],
    beaches: dict[str, Any],
    alerts: dict[str, Any],
    date: str,
    start: int,
    end: int,
) -> dict[str, Any] | None:
    hourly = forecast.get("hourly") or {}
    indices = [
        i
        for i, value in enumerate(hourly.get("time") or [])
        if str(value).startswith(date) and start <= _hour(value) < end
    ]
    if not indices:
        return None

    def vals(field: str) -> list[float]:
        source = hourly.get(field) or []
        return [float(source[i]) for i in indices if i < len(source) and source[i] is not None]

    def avg(field: str) -> float | None:
        values = vals(field)
        return round(fmean(values), 1) if values else None

    def peak(field: str) -> float | None:
        values = vals(field)
        return round(max(values), 1) if values else None

    codes = vals("weather_code")
    marine_hourly = (marine or {}).get("hourly") or {}
    marine_indices = [
        i
        for i, value in enumerate(marine_hourly.get("time") or [])
        if str(value).startswith(date) and start <= _hour(value) < end
    ]

    def marine_stat(field: str, fn: Callable[[list[float]], float] = fmean) -> float | None:
        source = marine_hourly.get(field) or []
        values = [
            float(source[i])
            for i in marine_indices
            if i < len(source) and source[i] is not None
        ]
        if not values:
            current = ((marine or {}).get("current") or {}).get(field)
            return float(current) if current is not None else None
        return round(fn(values), 1)

    beach_items = beaches.get("items") or [] if beaches.get("available") else []
    alert_items = alerts.get("items") or [] if alerts.get("available") else []
    return {
        "temp": avg("temperature_2m"),
        "feels": peak("apparent_temperature"),
        "humidity": avg("relative_humidity_2m"),
        "rain_probability": peak("precipitation_probability"),
        "precipitation": sum(vals("precipitation")),
        "uv": peak("uv_index"),
        "wind": avg("wind_speed_10m"),
        "gust": peak("wind_gusts_10m"),
        "visibility_km": _divide(avg("visibility"), 1000),
        "codes": [int(code) for code in codes],
        "thunderstorm": any(code >= 95 for code in codes),
        "wave": marine_stat("wave_height", max),
        "swell": marine_stat("swell_wave_height", max),
        "wave_period": marine_stat("wave_period", fmean),
        "sea_temp": marine_stat("sea_surface_temperature", fmean),
        "sargassum": sargassum.get("level") if sargassum.get("available") else None,
        "sargassum_known": bool(sargassum.get("available") and sargassum.get("level") != "unknown"),
        "aqi": air.get("us_aqi") if air.get("available") else None,
        "beach_advisory": any(item.get("status") == "exceedance" for item in beach_items),
        "marine_alert": any(item.get("hazard_type") in {"marine", "high_surf", "rip_current"} and item.get("level", 0) >= 2 for item in alert_items),
        "storm_alert": any(item.get("hazard_type") in {"thunderstorm", "severe_thunderstorm", "flash_flood", "flood"} and item.get("level", 0) >= 2 for item in alert_items),
        "marine_available": bool(marine_indices or (marine or {}).get("current")),
        "air_available": bool(air.get("available")),
    }


def _score_activity(activity: Activity, m: dict[str, Any]) -> dict[str, Any]:
    factors = _factors(m)
    weighted = [(key, weight, factors[key]) for key, weight in activity.factors]
    score = round(sum(weight * value[0] for _, weight, value in weighted) / sum(weight for _, weight, _ in weighted))
    caps: list[tuple[int, str]] = []
    if activity.outdoor and (m["thunderstorm"] or m["storm_alert"]):
        caps.append((10 if activity.strenuous else 15, "Lightning risk: move plans indoors"))
    if activity.marine and m["marine_alert"]:
        caps.append((20, "An active marine/surf alert overrides favorable weather"))
    wave = _effective_wave(m)
    if wave is not None:
        if activity.key == "snorkel" and wave >= 1.5:
            caps.append((25, "Rough water reduces visibility and safe entries"))
        if activity.key == "swim" and wave >= 1.8:
            caps.append((20, "Wave height is unsuitable for casual sea swimming"))
        if activity.key == "paddle" and wave >= 1.4:
            caps.append((20, "Paddling becomes difficult in this sea state"))
        if activity.key in {"boat", "sail", "bvi", "dive"} and wave >= 2.5:
            caps.append((30, "Rough passages likely; confirm with a licensed operator"))
    gust = m.get("gust")
    if gust is not None and activity.marine and gust >= 50:
        caps.append((20, "Strong gusts make small-craft plans unsafe"))
    if activity.key in {"swim", "snorkel", "dive"} and m["beach_advisory"]:
        caps.append((45, "At least one monitored beach has a water-quality advisory"))
    if caps:
        score = min(score, min(cap for cap, _ in caps))

    drivers = sorted(weighted, key=lambda item: item[1] * abs(item[2][0] - 65), reverse=True)
    positives = [value[1] for _, _, value in drivers if value[0] >= 72][:2]
    negatives = [value[1] for _, _, value in drivers if value[0] < 55][:2]
    reasons = negatives or positives or [drivers[0][2][1]]
    if caps:
        reasons = [min(caps, key=lambda item: item[0])[1], *reasons][:2]
    return {
        "key": activity.key,
        "name": activity.name,
        "emoji": activity.emoji,
        "score": max(0, min(100, score)),
        "rating": _rating(score),
        "reasons": reasons,
        "components": [
            {
                "factor": key.replace("_", " "),
                "weight_pct": weight,
                "suitability": round(value[0]),
            }
            for key, weight, value in weighted
        ],
    }


def _factors(m: dict[str, Any]) -> dict[str, tuple[float, str]]:
    rain = m.get("rain_probability")
    temp = m.get("temp")
    feels = m.get("feels") or temp
    humidity = m.get("humidity")
    uv = m.get("uv")
    wind = m.get("wind")
    gust = m.get("gust")
    wave = _effective_wave(m)
    sea_temp = m.get("sea_temp")
    aqi = m.get("aqi")
    sarg_value = m.get("sargassum")
    sarg = sarg_value if isinstance(sarg_value, str) else None

    dry = _curve(rain, ((0, 100), (20, 88), (40, 66), (60, 42), (80, 20), (100, 5)), 62)
    warm = _curve(temp, ((18, 30), (23, 80), (26, 100), (30, 94), (33, 65), (36, 25)), 70)
    uv_score = _curve(uv, ((0, 75), (3, 100), (6, 90), (8, 68), (10, 40), (12, 20)), 60)
    shade_uv = _curve(uv, ((0, 90), (5, 100), (8, 88), (11, 68), (13, 45)), 75)
    humidity_score = _curve(humidity, ((40, 95), (60, 100), (70, 88), (80, 62), (90, 35), (100, 15)), 65)
    heat = _curve(feels, ((20, 70), (25, 100), (28, 92), (31, 65), (34, 30), (38, 5)), 60)
    gentle = _curve(wind, ((0, 72), (8, 100), (18, 92), (28, 60), (40, 20)), 65)
    calm = _curve(wind, ((0, 100), (10, 95), (18, 70), (28, 30), (40, 5)), 60)
    boat_wind = _curve(wind, ((0, 82), (10, 100), (20, 90), (30, 62), (40, 25), (55, 5)), 62)
    sail_wind = _curve(wind, ((0, 20), (8, 62), (14, 94), (22, 100), (30, 78), (40, 35), (55, 5)), 58)
    tennis_wind = _curve(max(wind or 0, (gust or 0) * 0.65) if wind is not None or gust is not None else None, ((0, 100), (12, 96), (20, 70), (28, 35), (40, 5)), 62)
    shore = _curve(wave, ((0, 95), (0.5, 100), (1.0, 78), (1.5, 48), (2.0, 18), (3.0, 0)), 58)
    swim = _curve(wave, ((0, 100), (0.4, 98), (0.8, 78), (1.2, 48), (1.8, 10), (2.5, 0)), 55)
    snorkel = _curve(wave, ((0, 100), (0.3, 100), (0.7, 72), (1.0, 45), (1.5, 10), (2.0, 0)), 52)
    dive = _curve(wave, ((0, 100), (0.8, 92), (1.4, 68), (2.0, 40), (3.0, 5)), 58)
    paddle = _curve(wave, ((0, 100), (0.4, 98), (0.8, 68), (1.2, 35), (1.6, 5)), 52)
    boat = _curve(wave, ((0, 100), (0.8, 95), (1.4, 70), (2.0, 42), (3.0, 8)), 60)
    sail_sea = _curve(wave, ((0, 72), (0.5, 100), (1.1, 92), (1.8, 62), (2.5, 25), (3.5, 5)), 60)
    visibility = _curve(m.get("visibility_km"), ((1, 10), (5, 45), (10, 78), (20, 100)), 70)
    marine_visibility = round(snorkel * 0.55 + visibility * 0.45)
    sea = _curve(sea_temp, ((20, 25), (24, 70), (26, 95), (28, 100), (31, 82), (33, 55)), 72)
    air_score = _curve(aqi, ((0, 100), (50, 100), (75, 80), (100, 62), (150, 25), (200, 5)), 72)
    sarg_score = {"low": 100, "moderate": 60, "elevated": 20}.get(sarg, 68) if sarg else 68
    water_score = 25 if m.get("beach_advisory") else 95
    indoor_weather = round(45 + (100 - dry) * 0.45 + (100 - warm) * 0.10)
    indoor_heat = _curve(feels, ((20, 65), (27, 68), (30, 82), (33, 100), (38, 100)), 72)

    return {
        "dry": (dry, _rain_reason(rain)),
        "warm": (warm, _value_reason(temp, "Comfortable air temperature", "Hot air temperature", "°C", 31)),
        "uv": (uv_score, _value_reason(uv, "Manageable UV", "Strong midday UV", "", 7)),
        "shade_uv": (shade_uv, _value_reason(uv, "Comfortable in shade", "Choose a shaded table", "", 8)),
        "humidity": (humidity_score, _value_reason(humidity, "Comfortable humidity", "Muggy conditions", "%", 78)),
        "exercise_heat": (heat, _value_reason(feels, "Comfortable for exercise", "Heat stress during exertion", "°C feels-like", 30)),
        "gentle_wind": (gentle, _value_reason(wind, "Pleasant breeze", "Strong breeze", " km/h", 26)),
        "calm_wind": (calm, _value_reason(wind, "Light wind", "Wind-chopped water", " km/h", 18)),
        "boat_wind": (boat_wind, _value_reason(wind, "Comfortable boat breeze", "Strong wind for small craft", " km/h", 30)),
        "sail_wind": (sail_wind, _value_reason(wind, "Useful sailing breeze", "Sailing wind outside the ideal range", " km/h", 30)),
        "tennis_wind": (tennis_wind, _value_reason(wind, "Light court wind", "Wind affects ball control", " km/h", 18)),
        "shore": (shore, _wave_reason(m, "Gentle shore conditions", "Rough shore break", 1.1)),
        "swim_sea": (swim, _wave_reason(m, "Calm swimming water", "Rough water for casual swimmers", 1.0)),
        "snorkel_sea": (snorkel, _wave_reason(m, "Calm snorkeling water", "Waves reduce safe entries and clarity", 0.8)),
        "dive_sea": (dive, _wave_reason(m, "Good dive sea state", "Rough dive-boat conditions", 1.7)),
        "paddle_sea": (paddle, _wave_reason(m, "Smooth paddling water", "Difficult paddling sea state", 0.8)),
        "boat_sea": (boat, _wave_reason(m, "Comfortable passage", "Choppy boat passage", 1.5)),
        "sail_sea": (sail_sea, _wave_reason(m, "Useful sailing sea state", "Rough sailing sea state", 1.8)),
        "marine_visibility": (marine_visibility, "Water clarity inferred from waves and atmospheric visibility"),
        "sea_temp": (sea, _value_reason(sea_temp, "Comfortable sea temperature", "Less comfortable sea temperature", "°C", 31)),
        "air": (air_score, _value_reason(aqi, "Clean air", "Reduced air quality", " AQI", 100)),
        "sargassum": (sarg_score, "Low Sargassum signal" if sarg == "low" else f"{(sarg or 'Unknown').title()} Sargassum signal"),
        "water_quality": (water_score, "No monitored beach advisory" if water_score > 50 else "A monitored beach has a water advisory"),
        "indoor_weather": (min(100, indoor_weather), "Indoor plans gain value if showers disrupt outdoor time"),
        "indoor_heat_relief": (indoor_heat, "Air-conditioned recovery from heat and humidity"),
    }


def _curve(value: float | None, points: tuple[tuple[float, float], ...], missing: float) -> float:
    if value is None:
        return missing
    if value <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in pairwise(points):
        if value <= x1:
            return y0 + (y1 - y0) * (value - x0) / (x1 - x0)
    return points[-1][1]


def _conditions_summary(m: dict[str, Any]) -> str:
    bits = []
    if m.get("temp") is not None:
        bits.append(f"{round(m['temp'])}°C")
    if m.get("rain_probability") is not None:
        bits.append(f"{round(m['rain_probability'])}% rain")
    if m.get("wind") is not None:
        bits.append(f"{round(m['wind'])} km/h wind")
    if m.get("wave") is not None:
        period = f" @ {m['wave_period']:.0f}s" if m.get("wave_period") is not None else ""
        bits.append(f"{m['wave']:.1f} m waves{period}")
    if m.get("uv") is not None:
        bits.append(f"UV {m['uv']:.0f}")
    return " · ".join(bits)


def _confidence(m: dict[str, Any]) -> str:
    present = sum(m.get(key) is not None for key in ("temp", "rain_probability", "wind", "uv", "wave", "aqi"))
    return "high" if present >= 5 and m["sargassum_known"] else "medium" if present >= 4 else "low"


def _safety_note(m: dict[str, Any]) -> str | None:
    if m["thunderstorm"] or m["storm_alert"]:
        return "Thunderstorms: leave beaches, water, boats, ridges, and exposed trails when thunder is heard."
    if m["marine_alert"]:
        return "Active marine or surf alert: use official guidance and operator decisions over these scores."
    if m["beach_advisory"]:
        return "Water quality varies by beach; avoid swimming at locations marked Advisory."
    if (m.get("uv") or 0) >= 8:
        return "Very high UV: favor early hours, shade, reef-safe SPF 30+, and frequent water breaks."
    return None


def _rating(score: int) -> str:
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "good"
    if score >= 55:
        return "fair"
    if score >= 35:
        return "poor"
    return "avoid"


def _rain_reason(value: float | None) -> str:
    if value is None:
        return "Rain confidence unavailable"
    return f"Low rain chance ({round(value)}%)" if value < 35 else f"Showers possible ({round(value)}%)"


def _value_reason(value: float | None, good: str, bad: str, suffix: str, threshold: float) -> str:
    if value is None:
        return f"{good} (limited data)"
    label = bad if value >= threshold else good
    return f"{label} ({value:g}{suffix})"


def _effective_wave(m: dict[str, Any]) -> float | None:
    """Conservative wave height proxy that accounts for swell and long period."""
    wave = m.get("wave")
    swell = m.get("swell")
    known = [float(value) for value in (wave, swell) if value is not None]
    if not known:
        return None
    effective = max(known)
    period = m.get("wave_period")
    if period is not None and period >= 10:
        effective += min(0.4, (float(period) - 9) * 0.06)
    return round(effective, 2)


def _wave_reason(m: dict[str, Any], good: str, bad: str, threshold: float) -> str:
    effective = _effective_wave(m)
    if effective is None:
        return f"{good} (limited marine data)"
    wave = m.get("wave")
    period = m.get("wave_period")
    detail = f"{float(wave):g} m" if wave is not None else f"{effective:g} m"
    if period is not None:
        detail += f" @ {float(period):g}s"
    label = bad if effective >= threshold else good
    return f"{label} ({detail})"


def _hour(value: Any) -> int:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).hour
    except ValueError:
        return -1


def _divide(value: float | None, divisor: float) -> float | None:
    return round(value / divisor, 1) if value is not None else None
