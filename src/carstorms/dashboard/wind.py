"""Explainable wind severity assessments for outdoor planning."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from statistics import fmean
from typing import Any

AST = timezone(timedelta(hours=-4))


def build_wind_panel(
    forecast: dict[str, Any] | None,
    alerts: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    if not forecast:
        return {"available": False, "reason": "wind forecast unavailable"}
    current = forecast.get("current") or {}
    alert_floor, alert_note = _alert_floor(alerts)
    current_assessment = assess_wind(
        current.get("wind_speed_10m"),
        current.get("wind_gusts_10m"),
        current.get("wind_direction_10m"),
        alert_floor=alert_floor,
        alert_note=alert_note,
    )

    local_date = now.astimezone(AST).date().isoformat()
    hourly = forecast.get("hourly") or {}
    periods = []
    for key, label, start, end in (
        ("morning", "Morning", 6, 12),
        ("afternoon", "Afternoon", 12, 18),
        ("evening", "Evening", 18, 24),
    ):
        indices = [
            index
            for index, value in enumerate(hourly.get("time") or [])
            if str(value).startswith(local_date) and start <= _hour(value) < end
        ]
        if not indices:
            continue
        speeds = _values(hourly, "wind_speed_10m", indices)
        gusts = _values(hourly, "wind_gusts_10m", indices)
        directions = _values(hourly, "wind_direction_10m", indices)
        periods.append(
            {
                "key": key,
                "label": label,
                "time": f"{start:02d}:00-{end:02d}:00",
                **assess_wind(
                    max(speeds) if speeds else None,
                    max(gusts) if gusts else None,
                    _circular_mean(directions),
                    alert_floor=alert_floor,
                    alert_note=alert_note,
                ),
            }
        )
    return {
        "available": True,
        "time": _ast(current.get("time")),
        "current": current_assessment,
        "periods": periods,
        "method": (
            "0-34 green, 35-64 yellow, 65-100 red. Severity is the higher of "
            "sustained-wind and gust impact curves; active wind watches/warnings "
            "set a minimum safety level."
        ),
    }


def assess_wind(
    speed: Any,
    gust: Any,
    direction: Any,
    *,
    alert_floor: int = 0,
    alert_note: str | None = None,
) -> dict[str, Any]:
    sustained = _float(speed)
    peak = _float(gust)
    degrees = _float(direction)
    speed_score = _curve(
        sustained,
        ((0, 0), (15, 8), (25, 20), (35, 38), (45, 55), (60, 75), (80, 95), (95, 100)),
    )
    gust_score = _curve(
        peak,
        ((0, 0), (20, 8), (30, 18), (40, 34), (55, 54), (70, 73), (90, 94), (105, 100)),
    )
    severity = max(alert_floor, round(max(speed_score, gust_score)))
    if severity < 35:
        band, label = "green", "Generally suitable"
    elif severity < 65:
        band, label = "yellow", "Use caution"
    else:
        band, label = "red", "Unsafe for exposed activities"
    return {
        "speed_kmh": round(sustained, 1) if sustained is not None else None,
        "gust_kmh": round(peak, 1) if peak is not None else None,
        "direction_deg": round(degrees) if degrees is not None else None,
        "direction": _compass(degrees),
        "severity": severity,
        "band": band,
        "label": label,
        "advice": _advice(severity),
        "alert_note": alert_note,
    }


def _alert_floor(alerts: dict[str, Any]) -> tuple[int, str | None]:
    levels = [
        int(item.get("level") or 0)
        for item in (alerts.get("items") or [])
        if item.get("hazard_type") in {"wind", "tropical_cyclone", "severe_thunderstorm"}
    ]
    level = max(levels, default=0)
    if level >= 3:
        return 75, "Active wind warning raises the minimum severity to red."
    if level == 2:
        return 55, "Active wind watch raises the minimum severity to yellow."
    if level == 1:
        return 35, "Active wind advisory raises the minimum severity to yellow."
    return 0, None


def _advice(severity: int) -> str:
    if severity < 20:
        return "Comfortable for most outdoor plans."
    if severity < 35:
        return "Breezy; secure light items and check exposed-water conditions."
    if severity < 50:
        return "Loose items and exposed coasts need caution; tennis and paddling may suffer."
    if severity < 65:
        return "Difficult for cycling, paddling and exposed hikes; reconsider small-craft plans."
    if severity < 80:
        return "Postpone exposed outdoor activities; falling branches and debris are possible."
    return "Severe wind: stay sheltered and follow official warnings."


def _curve(value: float | None, points: tuple[tuple[float, float], ...]) -> float:
    if value is None:
        return 0
    if value <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in pairwise(points):
        if value <= x1:
            return y0 + (y1 - y0) * (value - x0) / (x1 - x0)
    return points[-1][1]


def _circular_mean(values: list[float]) -> float | None:
    if not values:
        return None
    radians = [math.radians(value) for value in values]
    angle = math.degrees(
        math.atan2(fmean(math.sin(x) for x in radians), fmean(math.cos(x) for x in radians))
    )
    return angle % 360


def _compass(value: float | None) -> str:
    if value is None:
        return "unknown"
    points = (
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    )
    return f"{points[round(value / 22.5) % 16]} (from)"


def _values(hourly: dict[str, Any], field: str, indices: list[int]) -> list[float]:
    source = hourly.get(field) or []
    return [
        float(source[index])
        for index in indices
        if index < len(source) and source[index] is not None
    ]


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _hour(value: Any) -> int:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).hour
    except ValueError:
        return -1


def _ast(value: Any) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    parsed = parsed.replace(tzinfo=AST) if parsed.tzinfo is None else parsed.astimezone(AST)
    return parsed.isoformat()
