"""NHC CurrentStorms.json — active tropical cyclones and their cone graphics.

NHC provides intensity, position, motion and the forecast-cone image. The true
forecast-track geometry lives in separate GIS files; here we approximate approach
by projecting the current heading/speed, and lean on the NWS source for the
authoritative local hurricane watch/warning. Each storm keeps a stable ``id`` so
all advisories thread into one event.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from carstorms.content.levels import classify_cyclone, cyclone_level, knots_to_kmh
from carstorms.geo import haversine_km, nearest_approach_km, project_track
from carstorms.models import AlertLevel, EventStatus, HazardObservation, HazardType, SourceName
from carstorms.sources.base import HazardSource, get_json

CURRENT_STORMS_URL = "https://www.nhc.noaa.gov/CurrentStorms.json"
CONE_GRAPHIC = "https://www.nhc.noaa.gov/storm_graphics/api/{sid}_CONE_latest.png"

_CLASS_WORDS = {
    "TD": "Tropical Depression",
    "TS": "Tropical Storm",
    "HU": "Hurricane",
    "MH": "Major Hurricane",
    "STD": "Subtropical Depression",
    "STS": "Subtropical Storm",
    "PTC": "Potential Tropical Cyclone",
    "PC": "Post-Tropical Cyclone",
    "RM": "Remnants",
}


def _parse_coord(value: Any) -> float | None:
    """Parse a coordinate that may be numeric or a string like '21.5N'/'94.5W'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().upper()
    if not text:
        return None
    sign = 1.0
    if text[-1] in "NSEW":
        if text[-1] in "SW":
            sign = -1.0
        text = text[:-1]
    try:
        return sign * float(text)
    except ValueError:
        return None


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class NHCSource(HazardSource):
    name = SourceName.NHC

    async def _fetch(self, client: httpx.AsyncClient) -> list[HazardObservation]:
        data = await get_json(client, CURRENT_STORMS_URL)
        storms: list[dict[str, Any]] = list(data.get("activeStorms", []))
        target = (self.settings.latitude, self.settings.longitude)
        observations: list[HazardObservation] = []
        for storm in storms:
            obs = self._to_observation(storm, target)
            if obs is not None:
                observations.append(obs)
        return observations

    def _to_observation(
        self, storm: dict[str, Any], target: tuple[float, float]
    ) -> HazardObservation | None:
        storm_id = storm.get("id")
        if not storm_id:
            return None

        lat = _parse_coord(storm.get("latitudeNumeric", storm.get("latitude")))
        lon = _parse_coord(storm.get("longitudeNumeric", storm.get("longitude")))
        wind_kt = _to_float(storm.get("intensity"), 0.0)
        move_dir = _to_float(storm.get("movementDir"), 0.0)
        move_speed = _to_float(storm.get("movementSpeed"), 0.0)

        distance_km: float | None = None
        if lat is not None and lon is not None:
            current = haversine_km(target[0], target[1], lat, lon)
            projected = nearest_approach_km(target, project_track(lat, lon, move_dir, move_speed))
            distance_km = min(current, projected) if projected is not None else current

        level = cyclone_level(wind_kt, distance_km, self.settings.tropical_alert_radius_km)
        # Below the watch radius this storm is not relevant to St. John yet, but
        # we still surface strong systems at an informational level once they are
        # within roughly twice the radius so people see them building.
        if (
            distance_km is not None
            and distance_km > self.settings.tropical_alert_radius_km * 2
            and level <= AlertLevel.INFORMATIONAL
        ):
            return None

        classification = str(storm.get("classification", "")).upper()
        class_word = _CLASS_WORDS.get(classification, classification or "Tropical Cyclone")
        name = storm.get("name", "Unnamed")
        title = f"{class_word} {name}".strip()
        category = classify_cyclone(wind_kt)

        body_lines = [category.description]
        if lat is not None and lon is not None:
            body_lines.append(
                f"Center near {abs(lat):.1f}°{'N' if lat >= 0 else 'S'}, {abs(lon):.1f}°{'W' if lon < 0 else 'E'}."
            )
        body_lines.append(
            f"Maximum sustained winds {int(wind_kt)} kt ({knots_to_kmh(wind_kt)} km/h)."
        )
        if move_speed:
            body_lines.append(f"Moving toward {int(move_dir)}° at {int(move_speed)} kt.")
        if distance_km is not None:
            body_lines.append(
                f"Closest approach to {self.settings.location_name}: about {int(distance_km)} km."
            )

        images = [CONE_GRAPHIC.format(sid=str(storm_id).upper())]
        track_cone = storm.get("trackCone") or {}
        if isinstance(track_cone, dict) and track_cone.get("url", "").endswith(".png"):
            images.insert(0, track_cone["url"])

        last_update = storm.get("lastUpdate")
        effective = None
        if last_update:
            try:
                effective = datetime.fromisoformat(str(last_update).replace("Z", "+00:00"))
            except ValueError:
                effective = None

        return HazardObservation(
            source=SourceName.NHC,
            source_event_id=str(storm_id),
            hazard_type=HazardType.TROPICAL_CYCLONE,
            level=level,
            status=EventStatus.ACTIVE,
            title=title,
            headline=f"{title} — {category.name}",
            body="\n".join(body_lines),
            latitude=lat,
            longitude=lon,
            distance_km=distance_km,
            affects_st_john=level >= AlertLevel.WATCH,
            effective=effective,
            image_urls=images,
            raw={
                "id": storm_id,
                "name": name,
                "classification": classification,
                "intensity_kt": wind_kt,
                "pressure": storm.get("pressure"),
                "movementDir": move_dir,
                "movementSpeed": move_speed,
                "binNumber": storm.get("binNumber"),
            },
        )
