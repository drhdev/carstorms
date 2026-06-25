"""Tests for the haversine / projection helpers."""

from __future__ import annotations

from carstorms.geo import destination_point, haversine_km, nearest_approach_km, project_track


def test_haversine_known_distance() -> None:
    # St. John, USVI to San Juan, PR is roughly 100-130 km.
    d = haversine_km(18.33, -64.73, 18.47, -66.10)
    assert 120 < d < 160


def test_haversine_zero() -> None:
    assert haversine_km(18.3, -64.7, 18.3, -64.7) == 0.0


def test_destination_point_moves_north() -> None:
    lat, lon = destination_point(18.0, -65.0, bearing_deg=0, distance_km=111.0)
    assert lat > 18.9  # ~1 degree north
    assert abs(lon + 65.0) < 0.01


def test_project_track_first_point_is_origin() -> None:
    track = project_track(18.0, -65.0, bearing_deg=90, speed_kt=20)
    assert track[0] == (18.0, -65.0)
    assert len(track) == 7


def test_nearest_approach() -> None:
    track = [(20.0, -65.0), (18.4, -64.8), (16.0, -64.0)]
    d = nearest_approach_km((18.33, -64.73), track)
    assert d is not None and d < 20
    assert nearest_approach_km((18.33, -64.73), []) is None
