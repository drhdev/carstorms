"""Hazard-specific severity scales and their mapping onto :class:`AlertLevel`.

The Saffir-Simpson helpers are a modernised port of the original ``carstorms.py``
``CATEGORY_SCALE`` / ``knots_to_kmh`` / ``classify_storm`` logic.
"""

from __future__ import annotations

from dataclasses import dataclass

from carstorms.models import AlertLevel


def knots_to_kmh(knots: float) -> int:
    return round(knots * 1.852)


def kmh_to_knots(kmh: float) -> int:
    return round(kmh / 1.852)


@dataclass(frozen=True)
class CycloneCategory:
    min_kt: int
    name: str
    description: str


# Ordered strongest first (matches the original lookup style).
SAFFIR_SIMPSON: tuple[CycloneCategory, ...] = (
    CycloneCategory(
        137,
        "Category 5 Hurricane",
        "Catastrophic — most buildings destroyed; area uninhabitable for weeks/months.",
    ),
    CycloneCategory(
        113,
        "Category 4 Hurricane",
        "Catastrophic — long power/water outages; severe structural damage.",
    ),
    CycloneCategory(
        96,
        "Category 3 Hurricane",
        "Devastating — major damage; widespread, long outages (major hurricane).",
    ),
    CycloneCategory(
        83,
        "Category 2 Hurricane",
        "Extensive — large trees uprooted; major roof and siding damage.",
    ),
    CycloneCategory(
        64,
        "Category 1 Hurricane",
        "Very dangerous — roof/tree damage; near-total power loss likely.",
    ),
    CycloneCategory(
        34, "Tropical Storm", "Strong winds, dangerous seas, heavy rain and possible flooding."
    ),
    CycloneCategory(
        0, "Tropical Depression", "Organising system with heavy rain; flooding possible."
    ),
)


def classify_cyclone(wind_kt: float) -> CycloneCategory:
    for cat in SAFFIR_SIMPSON:
        if wind_kt >= cat.min_kt:
            return cat
    return SAFFIR_SIMPSON[-1]


def cyclone_level(wind_kt: float, distance_km: float | None, radius_km: float) -> AlertLevel:
    """Map a cyclone's intensity and proximity to St. John onto AlertLevel.

    Intensity sets a ceiling; proximity decides how much of it applies. A
    Category 5 four states away is still only informational here; the same storm
    bearing down on the island is catastrophic.
    """
    cat = classify_cyclone(wind_kt)
    if cat.min_kt >= 137:
        intensity_ceiling = AlertLevel.CATASTROPHIC
    elif cat.min_kt >= 96:
        intensity_ceiling = AlertLevel.EMERGENCY
    elif cat.min_kt >= 64:
        intensity_ceiling = AlertLevel.WARNING
    elif cat.min_kt >= 34:
        intensity_ceiling = AlertLevel.WATCH
    else:
        intensity_ceiling = AlertLevel.ADVISORY

    if distance_km is None:
        proximity = AlertLevel.INFORMATIONAL
    elif distance_km <= 75:
        proximity = AlertLevel.CATASTROPHIC
    elif distance_km <= 150:
        proximity = AlertLevel.EMERGENCY
    elif distance_km <= 250:
        proximity = AlertLevel.WARNING
    elif distance_km <= radius_km:
        proximity = AlertLevel.WATCH
    else:
        proximity = AlertLevel.INFORMATIONAL

    return AlertLevel(min(int(intensity_ceiling), int(proximity)))


def earthquake_level(
    magnitude: float,
    distance_km: float,
    *,
    tsunami_flag: bool = False,
    near_km: float = 200.0,
) -> AlertLevel:
    """Map an earthquake's magnitude and distance to St. John onto AlertLevel."""
    if tsunami_flag:
        return AlertLevel.EMERGENCY

    if magnitude >= 7.0:
        base = AlertLevel.EMERGENCY
    elif magnitude >= 6.0:
        base = AlertLevel.WARNING
    elif magnitude >= 5.0:
        base = AlertLevel.WATCH
    elif magnitude >= 4.0:
        base = AlertLevel.ADVISORY
    else:
        base = AlertLevel.INFORMATIONAL

    # Distant quakes are rarely felt on St. John; damp the level with range.
    if distance_km > near_km * 2:
        base = AlertLevel(max(AlertLevel.INFORMATIONAL, base - 2))
    elif distance_km > near_km:
        base = AlertLevel(max(AlertLevel.INFORMATIONAL, base - 1))

    return base


def beach_level(cfu: float, threshold: float) -> AlertLevel:
    """Beach Enterococcus result -> level. At/above the standard = swim advisory."""
    if cfu >= threshold * 4:
        return AlertLevel.WATCH  # grossly elevated
    if cfu >= threshold:
        return AlertLevel.ADVISORY
    return AlertLevel.INFORMATIONAL


def air_quality_level(aqi: int) -> AlertLevel:
    """US EPA AQI band -> level."""
    if aqi >= 301:  # Hazardous
        return AlertLevel.EMERGENCY
    if aqi >= 201:  # Very Unhealthy
        return AlertLevel.WARNING
    if aqi >= 151:  # Unhealthy
        return AlertLevel.WATCH
    if aqi >= 101:  # Unhealthy for Sensitive Groups
        return AlertLevel.ADVISORY
    return AlertLevel.INFORMATIONAL  # Good / Moderate


def airport_level(flight_category: str, *, closed: bool = False) -> AlertLevel:
    """STT airport status from METAR flight category (+ NOTAM closure flag)."""
    if closed:
        return AlertLevel.WARNING
    cat = (flight_category or "").upper()
    if cat == "LIFR":
        return AlertLevel.WATCH
    if cat == "IFR":
        return AlertLevel.ADVISORY
    return AlertLevel.INFORMATIONAL  # VFR / MVFR
