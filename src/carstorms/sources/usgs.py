"""USGS FDSN GeoJSON — earthquakes (and tsunami flag) near St. John, USVI.

Queries recent quakes within a radius and filters to those that are notable
(M >= 4.5), felt-locally near (within ``earthquake_near_km``), or tsunami-flagged,
so the archive stays meaningful. Significant quakes get a ShakeMap intensity image.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from carstorms.content.levels import earthquake_level
from carstorms.geo import haversine_km
from carstorms.models import AlertLevel, EventStatus, HazardObservation, HazardType, SourceName
from carstorms.sources.base import HazardSource, get_json

QUERY_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
NOTABLE_MAGNITUDE = 4.5
NEAR_MIN_MAGNITUDE = 3.0
LOOKBACK_HOURS = 48


class USGSSource(HazardSource):
    name = SourceName.USGS

    async def _fetch(self, client: httpx.AsyncClient) -> list[HazardObservation]:
        starttime = (datetime.now(UTC) - timedelta(hours=LOOKBACK_HOURS)).isoformat()
        params = {
            "format": "geojson",
            "latitude": self.settings.latitude,
            "longitude": self.settings.longitude,
            "maxradiuskm": self.settings.earthquake_radius_km,
            "minmagnitude": self.settings.earthquake_min_magnitude,
            "starttime": starttime,
            "orderby": "time",
        }
        data = await get_json(client, QUERY_URL, params=params)
        observations: list[HazardObservation] = []
        for feature in data.get("features", []):
            obs = await self._to_observation(client, feature)
            if obs is not None:
                observations.append(obs)
        return observations

    async def _to_observation(
        self, client: httpx.AsyncClient, feature: dict[str, Any]
    ) -> HazardObservation | None:
        quake_id = feature.get("id")
        props: dict[str, Any] = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates") or []
        if not quake_id or len(coords) < 2:
            return None

        lon, lat = float(coords[0]), float(coords[1])
        depth = float(coords[2]) if len(coords) > 2 else 0.0
        magnitude = float(props.get("mag") or 0.0)
        tsunami_flag = bool(props.get("tsunami"))
        distance_km = haversine_km(self.settings.latitude, self.settings.longitude, lat, lon)

        notable = magnitude >= NOTABLE_MAGNITUDE
        near = distance_km <= self.settings.earthquake_near_km and magnitude >= NEAR_MIN_MAGNITUDE
        if not (notable or near or tsunami_flag):
            return None

        level = earthquake_level(
            magnitude,
            distance_km,
            tsunami_flag=tsunami_flag,
            near_km=self.settings.earthquake_near_km,
        )
        title = props.get("title") or f"M {magnitude:.1f} earthquake"
        when = props.get("time")
        effective = (
            datetime.fromtimestamp(when / 1000, tz=UTC) if isinstance(when, (int, float)) else None
        )

        body_lines = [
            f"Magnitude {magnitude:.1f}, depth {depth:.0f} km.",
            f"About {int(distance_km)} km from {self.settings.location_name}.",
            f"Location: {props.get('place', 'unknown')}.",
        ]
        if tsunami_flag:
            body_lines.append(
                "USGS has flagged possible tsunami potential — heed official tsunami alerts."
            )

        images: list[str] = []
        if notable and isinstance(props.get("detail"), str):
            shakemap = await self._shakemap_image(client, props["detail"])
            if shakemap:
                images.append(shakemap)

        return HazardObservation(
            source=SourceName.USGS,
            source_event_id=str(quake_id),
            hazard_type=HazardType.TSUNAMI if tsunami_flag else HazardType.EARTHQUAKE,
            level=level,
            status=EventStatus.ACTIVE,
            title=title,
            headline=title,
            body="\n".join(body_lines),
            latitude=lat,
            longitude=lon,
            distance_km=distance_km,
            affects_st_john=level >= AlertLevel.ADVISORY,
            effective=effective,
            image_urls=images,
            raw={
                "id": quake_id,
                "mag": magnitude,
                "depth_km": depth,
                "place": props.get("place"),
                "tsunami": int(tsunami_flag),
                "pager_alert": props.get("alert"),
                "url": props.get("url"),
            },
        )

    async def _shakemap_image(self, client: httpx.AsyncClient, detail_url: str) -> str | None:
        """Best-effort: pull the ShakeMap intensity image from the detail feed."""
        try:
            detail = await get_json(client, detail_url)
        except Exception:
            return None
        shakemaps = (detail.get("properties", {}).get("products", {}) or {}).get("shakemap") or []
        if not shakemaps:
            return None
        contents = shakemaps[0].get("contents", {}) or {}
        for key in ("download/intensity.jpg", "download/intensity.png", "download/pga.jpg"):
            entry = contents.get(key)
            if isinstance(entry, dict) and entry.get("url"):
                return str(entry["url"])
        return None
