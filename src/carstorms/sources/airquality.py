"""EPA AirNow — air quality (incl. Saharan dust) for the USVI.

Requires a free AirNow API key; the source is only built when the key is set.
Every reading is archived; an advisory is raised only when AQI reaches "Unhealthy
for Sensitive Groups" (101) or worse, so ordinary clear days stay silent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import httpx

from carstorms.content.levels import air_quality_level
from carstorms.models import (
    AlertLevel,
    HazardObservation,
    HazardType,
    Island,
    Measurement,
    SourceName,
)
from carstorms.sources.base import HazardSource, get_json

OBSERVATION_URL = "https://www.airnowapi.org/aq/observation/latLong/current/"
AST = timezone(timedelta(hours=-4))


class AirQualitySource(HazardSource):
    name = SourceName.AIRNOW
    min_interval_seconds = 1800  # AirNow updates hourly

    async def _fetch(self, client: httpx.AsyncClient) -> list[HazardObservation]:
        data = await get_json(
            client,
            OBSERVATION_URL,
            params={
                "format": "application/json",
                "latitude": self.settings.st_thomas_latitude,
                "longitude": self.settings.st_thomas_longitude,
                "distance": self.settings.airnow_distance_miles,
                "API_KEY": self.settings.airnow_api_key,
            },
        )
        if not isinstance(data, list) or not data:
            return []

        measurements: list[Measurement] = []
        worst_aqi = -1
        worst: dict[str, Any] | None = None
        for obs in data:
            aqi = obs.get("AQI")
            if not isinstance(aqi, int):
                continue
            parameter = str(obs.get("ParameterName", "")).replace(".", "").lower() or "aqi"
            sampled_at = self._sampled_at(obs)
            measurements.append(
                Measurement(
                    source=SourceName.AIRNOW,
                    metric=f"aqi_{parameter}",
                    value=float(aqi),
                    unit="AQI",
                    island=Island.USVI,
                    station=str(obs.get("ReportingArea", "USVI")),
                    station_name=str(obs.get("ReportingArea", "")),
                    latitude=obs.get("Latitude"),
                    longitude=obs.get("Longitude"),
                    status=str((obs.get("Category") or {}).get("Name", "")),
                    sampled_at=sampled_at,
                    raw=obs,
                )
            )
            if aqi > worst_aqi:
                worst_aqi = aqi
                worst = obs

        self.last_measurements = measurements
        if worst is None:
            return []

        level = air_quality_level(worst_aqi)
        if level < AlertLevel.ADVISORY:
            return []  # Good / Moderate — archive only, no alert

        category = str((worst.get("Category") or {}).get("Name", "Unhealthy"))
        parameter = str(worst.get("ParameterName", "PM2.5"))
        area = str(worst.get("ReportingArea", self.settings.st_thomas_name))
        dust = " (often Saharan dust here)" if parameter.upper().startswith("PM") else ""
        return [
            HazardObservation(
                source=SourceName.AIRNOW,
                source_event_id="usvi",
                hazard_type=HazardType.AIR_QUALITY,
                level=level,
                title=f"Air quality: {category}",
                headline=f"Air quality {category} — AQI {worst_aqi} ({parameter})",
                body=(
                    f"{area}: {parameter} air quality index {worst_aqi} — {category}{dust}. "
                    "Saharan dust events raise fine-particle levels across the territory."
                ),
                latitude=worst.get("Latitude"),
                longitude=worst.get("Longitude"),
                island=Island.USVI,
                raw=worst,
            )
        ]

    @staticmethod
    def _sampled_at(obs: dict[str, Any]) -> datetime | None:
        date = obs.get("DateObserved", "").strip()
        hour = obs.get("HourObserved")
        if not date or not isinstance(hour, int):
            return None
        try:
            local = datetime.strptime(date, "%Y-%m-%d").replace(hour=hour, tzinfo=AST)
        except ValueError:
            return None
        return local.astimezone(UTC)
