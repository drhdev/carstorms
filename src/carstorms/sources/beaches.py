"""EPA Water Quality Portal — beach Enterococcus results for St. Thomas & St. John.

Pulls DPNR/EPA weekly beach sampling (no API key). Every reading is archived to
``carstorm_measurements`` with its station and timestamp; beaches at or above the
USVI single-sample standard (70 cfu/100 ml) raise a swim advisory.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from carstorms.content.levels import beach_level
from carstorms.models import (
    HazardObservation,
    HazardType,
    Island,
    Measurement,
    SourceName,
)
from carstorms.sources.base import HazardSource, get_json, get_text

STATION_URL = "https://www.waterqualitydata.us/data/Station/search"
RESULT_URL = "https://www.waterqualitydata.us/data/Result/search"


def usvi_island(lat: float, lon: float) -> Island | None:
    """Classify a USVI coordinate. St. Croix (lat < 18) is out of scope here."""
    if lat < 18.0:
        return None  # St. Croix
    return Island.ST_JOHN if lon > -64.82 else Island.ST_THOMAS


@dataclass(slots=True)
class _Station:
    identifier: str
    name: str
    latitude: float
    longitude: float
    island: Island


class BeachWaterQualitySource(HazardSource):
    name = SourceName.WQP
    min_interval_seconds = 6 * 3600  # WQP data changes at most weekly

    async def _fetch(self, client: httpx.AsyncClient) -> list[HazardObservation]:
        stations = await self._load_stations(client)
        if not stations:
            return []

        start = (datetime.now(UTC) - timedelta(days=self.settings.beach_lookback_days)).strftime(
            "%m-%d-%Y"
        )
        csv_text = await get_text(
            client,
            RESULT_URL,
            params={
                "statecode": "US:78",
                "characteristicName": "Enterococcus",
                "startDateLo": start,
                "mimeType": "csv",
                "dataProfile": "resultPhysChem",
                "providers": "STORET",
            },
        )

        latest = self._latest_per_station(csv_text)
        threshold = self.settings.beach_threshold_cfu
        fresh_cutoff = datetime.now(UTC) - timedelta(days=self.settings.beach_advisory_max_age_days)
        observations: list[HazardObservation] = []
        measurements: list[Measurement] = []

        for station_id, reading in latest.items():
            station = stations.get(station_id)
            if station is None:
                continue
            value, unit, sampled_at, non_detect = reading
            exceeds = value >= threshold and not non_detect
            measurements.append(
                Measurement(
                    source=SourceName.WQP,
                    metric="enterococcus",
                    value=value,
                    unit=unit or "cfu/100ml",
                    island=station.island,
                    station=station.identifier,
                    station_name=station.name,
                    latitude=station.latitude,
                    longitude=station.longitude,
                    status="exceedance" if exceeds else ("non_detect" if non_detect else "ok"),
                    sampled_at=sampled_at,
                )
            )
            # Only advise from a genuinely recent sample — WQP uploads lag months,
            # so a stale exceedance must not raise a current swim advisory.
            if not exceeds or sampled_at < fresh_cutoff:
                continue
            level = beach_level(value, threshold)
            observations.append(
                HazardObservation(
                    source=SourceName.WQP,
                    source_event_id=station.identifier,
                    hazard_type=HazardType.WATER_QUALITY,
                    level=level,
                    title=f"Beach advisory: {station.name}",
                    headline=f"Water-quality advisory — {station.name}",
                    body=(
                        f"Enterococcus measured {value:.0f} {unit or 'cfu/100ml'} on "
                        f"{sampled_at:%a %d %b} (standard is {threshold:.0f}). "
                        "Bacteria can be elevated after heavy rain near guts and outfalls."
                    ),
                    latitude=station.latitude,
                    longitude=station.longitude,
                    island=station.island,
                    affects_st_john=station.island is Island.ST_JOHN,
                    effective=sampled_at,
                    raw={"station": station.identifier, "value": value, "unit": unit},
                )
            )

        self.last_measurements = measurements
        return observations

    async def _load_stations(self, client: httpx.AsyncClient) -> dict[str, _Station]:
        data = await get_json(
            client,
            STATION_URL,
            params={
                "statecode": "US:78",
                "characteristicName": "Enterococcus",
                "mimeType": "geojson",
                "providers": "STORET",
            },
        )
        stations: dict[str, _Station] = {}
        for feature in data.get("features", []):
            props = feature.get("properties") or {}
            geom = feature.get("geometry") or {}
            coords = geom.get("coordinates") or []
            identifier = props.get("MonitoringLocationIdentifier")
            if not identifier or len(coords) < 2:
                continue
            lon, lat = float(coords[0]), float(coords[1])
            island = usvi_island(lat, lon)
            if island is None:
                continue
            stations[identifier] = _Station(
                identifier=identifier,
                name=props.get("MonitoringLocationName") or identifier,
                latitude=lat,
                longitude=lon,
                island=island,
            )
        return stations

    @staticmethod
    def _latest_per_station(csv_text: str) -> dict[str, tuple[float, str, datetime, bool]]:
        """Most recent Enterococcus reading per location.

        Returns ``(value, unit, sampled_at, non_detect)``. Values may be
        qualified (e.g. ``<10`` = below detection, treated as non-detect)."""
        latest: dict[str, tuple[float, str, datetime, bool]] = {}
        reader = csv.DictReader(io.StringIO(csv_text))
        for row in reader:
            station_id = row.get("MonitoringLocationIdentifier")
            raw_value = (row.get("ResultMeasureValue") or "").strip()
            raw_date = (row.get("ActivityStartDate") or "").strip()
            if not station_id or not raw_value or not raw_date:
                continue
            non_detect = raw_value.startswith("<")
            cleaned = raw_value.lstrip("<>").strip()
            try:
                value = float(cleaned)
                sampled_at = datetime.strptime(raw_date, "%Y-%m-%d").replace(tzinfo=UTC)
            except ValueError:
                continue
            unit = (row.get("ResultMeasure/MeasureUnitCode") or "").strip()
            current = latest.get(station_id)
            if (
                current is None
                or sampled_at > current[2]
                or (sampled_at == current[2] and value > current[0])
            ):
                latest[station_id] = (value, unit, sampled_at, non_detect)
        return latest
