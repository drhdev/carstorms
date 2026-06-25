"""Tests for hazard severity scales and their AlertLevel mapping."""

from __future__ import annotations

from carstorms.content.levels import (
    air_quality_level,
    airport_level,
    beach_level,
    classify_cyclone,
    cyclone_level,
    earthquake_level,
    knots_to_kmh,
)
from carstorms.models import AlertLevel


def test_knots_to_kmh() -> None:
    assert knots_to_kmh(100) == 185
    assert knots_to_kmh(0) == 0


def test_classify_cyclone_bands() -> None:
    assert "Category 5" in classify_cyclone(140).name
    assert "Category 1" in classify_cyclone(70).name
    assert "Tropical Storm" in classify_cyclone(40).name
    assert "Tropical Depression" in classify_cyclone(25).name


def test_cyclone_level_intensity_capped_by_distance() -> None:
    # A monster storm far away is only informational here.
    assert cyclone_level(150, distance_km=900, radius_km=400) == AlertLevel.INFORMATIONAL
    # The same storm bearing down is catastrophic.
    assert cyclone_level(150, distance_km=50, radius_km=400) == AlertLevel.CATASTROPHIC
    # A tropical storm at watch distance is a watch (intensity caps it).
    assert cyclone_level(45, distance_km=200, radius_km=400) == AlertLevel.WATCH


def test_earthquake_level() -> None:
    assert earthquake_level(7.5, 100, near_km=200) == AlertLevel.EMERGENCY
    # Tsunami flag forces at least emergency regardless of distance.
    assert earthquake_level(6.0, 1000, tsunami_flag=True) == AlertLevel.EMERGENCY
    # Distant moderate quake is damped down.
    assert earthquake_level(5.0, 600, near_km=200) <= AlertLevel.INFORMATIONAL
    # A near magnitude-4 quake is an advisory.
    assert earthquake_level(4.2, 50, near_km=200) == AlertLevel.ADVISORY


def test_beach_level() -> None:
    assert beach_level(35, 70) == AlertLevel.INFORMATIONAL
    assert beach_level(95, 70) == AlertLevel.ADVISORY
    assert beach_level(400, 70) == AlertLevel.WATCH  # grossly elevated


def test_air_quality_level() -> None:
    assert air_quality_level(40) == AlertLevel.INFORMATIONAL  # Good
    assert air_quality_level(120) == AlertLevel.ADVISORY  # USG
    assert air_quality_level(175) == AlertLevel.WATCH  # Unhealthy
    assert air_quality_level(250) == AlertLevel.WARNING  # Very Unhealthy
    assert air_quality_level(350) == AlertLevel.EMERGENCY  # Hazardous


def test_airport_level() -> None:
    assert airport_level("VFR") == AlertLevel.INFORMATIONAL
    assert airport_level("IFR") == AlertLevel.ADVISORY
    assert airport_level("LIFR") == AlertLevel.WATCH
    assert airport_level("VFR", closed=True) == AlertLevel.WARNING
