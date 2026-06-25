"""Lightweight great-circle distance (haversine), dependency-free.

Replaces the old ``geopy.distance.geodesic`` usage. For the distances that matter
here (a storm track or quake epicentre relative to St. John) the haversine error
versus the geodesic is well under 0.5%, which is irrelevant against forecast
uncertainty — and it keeps the runtime free of native build dependencies.
"""

from __future__ import annotations

import math

from carstorms.models import Island

EARTH_RADIUS_KM = 6371.0088


def usvi_island(lat: float, lon: float) -> Island | None:
    """Classify a USVI coordinate by island. St. Croix (lat < 18) is out of scope."""
    if lat < 18.0:
        return None  # St. Croix
    return Island.ST_JOHN if lon > -64.82 else Island.ST_THOMAS


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def nearest_approach_km(
    target: tuple[float, float],
    track: list[tuple[float, float]],
) -> float | None:
    """Closest distance (km) from ``target`` to any point on a lat/lon track."""
    if not track:
        return None
    lat, lon = target
    return min(haversine_km(lat, lon, plat, plon) for plat, plon in track)


def destination_point(
    lat: float, lon: float, bearing_deg: float, distance_km: float
) -> tuple[float, float]:
    """Point reached travelling ``distance_km`` from (lat, lon) on ``bearing_deg``."""
    delta = distance_km / EARTH_RADIUS_KM
    theta = math.radians(bearing_deg)
    phi1 = math.radians(lat)
    lambda1 = math.radians(lon)
    phi2 = math.asin(
        math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta)
    )
    lambda2 = lambda1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2),
    )
    return math.degrees(phi2), (math.degrees(lambda2) + 540) % 360 - 180


def project_track(
    lat: float,
    lon: float,
    bearing_deg: float,
    speed_kt: float,
    hours: tuple[int, ...] = (0, 6, 12, 18, 24, 36, 48),
) -> list[tuple[float, float]]:
    """Project a storm's path assuming it holds its current heading and speed.

    A coarse stand-in for the official forecast track (whose true geometry lives
    in NHC GIS files); good enough to judge whether a system is approaching.
    """
    speed_kmh = speed_kt * 1.852
    return [destination_point(lat, lon, bearing_deg, speed_kmh * h) for h in hours]
