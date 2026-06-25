"""Tests for the extension sources: beaches, air quality, airport, manual."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import respx

from carstorms.config import Settings
from carstorms.models import AlertLevel, HazardType, Island, SourceName
from carstorms.sources import build_sources
from carstorms.sources.airport import METAR_URL, AirportStatusSource
from carstorms.sources.airquality import OBSERVATION_URL, AirQualitySource
from carstorms.sources.beaches import RESULT_URL, STATION_URL, BeachWaterQualitySource, usvi_island
from carstorms.sources.manual import ManualAlertSource
from carstorms.sources.wapa import OUTAGES_PATH, SUMMARY_PATH, WAPAOutageSource

# --- Beaches (EPA Water Quality Portal) ------------------------------------

_STATIONS = {
    "type": "FeatureCollection",
    "features": [
        {  # St. John
            "properties": {
                "MonitoringLocationIdentifier": "A",
                "MonitoringLocationName": "Cruz Bay",
            },
            "geometry": {"coordinates": [-64.75, 18.33]},
        },
        {  # St. Thomas
            "properties": {
                "MonitoringLocationIdentifier": "B",
                "MonitoringLocationName": "Brewers Bay",
            },
            "geometry": {"coordinates": [-64.93, 18.34]},
        },
        {  # St. Thomas
            "properties": {
                "MonitoringLocationIdentifier": "C",
                "MonitoringLocationName": "Krum Bay",
            },
            "geometry": {"coordinates": [-64.90, 18.33]},
        },
        {  # St. Croix — out of scope, must be skipped
            "properties": {
                "MonitoringLocationIdentifier": "X",
                "MonitoringLocationName": "Frederiksted",
            },
            "geometry": {"coordinates": [-64.88, 17.71]},
        },
    ],
}


def _beach_csv() -> str:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    stale = (datetime.now(UTC) - timedelta(days=200)).strftime("%Y-%m-%d")
    header = "MonitoringLocationIdentifier,ActivityStartDate,ResultMeasureValue,ResultMeasure/MeasureUnitCode"
    rows = [
        f"A,{today},120,MPN/100mL",  # recent exceedance -> advisory + measurement
        f"B,{today},<10,MPN/100mL",  # non-detect -> measurement only
        f"C,{stale},150,MPN/100mL",  # stale exceedance -> measurement only (too old to advise)
    ]
    return "\n".join([header, *rows])


def test_usvi_island_classification() -> None:
    assert usvi_island(18.33, -64.75) is Island.ST_JOHN
    assert usvi_island(18.34, -64.93) is Island.ST_THOMAS
    assert usvi_island(17.71, -64.88) is None  # St. Croix


async def test_beaches_archive_and_advisory(settings: Settings) -> None:
    with respx.mock:
        respx.get(STATION_URL).mock(return_value=httpx.Response(200, json=_STATIONS))
        respx.get(RESULT_URL).mock(return_value=httpx.Response(200, text=_beach_csv()))
        async with httpx.AsyncClient() as client:
            result = await BeachWaterQualitySource(settings).poll(client)

    # Every in-scope station is archived; only the fresh exceedance advises.
    assert len(result.measurements) == 3
    assert {m.status for m in result.measurements} == {"exceedance", "non_detect"}
    assert len(result.observations) == 1
    obs = result.observations[0]
    assert obs.hazard_type is HazardType.WATER_QUALITY
    assert obs.island is Island.ST_JOHN
    assert obs.level is AlertLevel.ADVISORY
    assert obs.event_key == "wqp:A"


# --- Air quality (AirNow) ---------------------------------------------------


def _airnow(pm25_aqi: int) -> list[dict]:
    return [
        {
            "DateObserved": "2026-06-25",
            "HourObserved": 14,
            "ReportingArea": "St. Thomas",
            "Latitude": 18.34,
            "Longitude": -64.93,
            "ParameterName": "PM2.5",
            "AQI": pm25_aqi,
            "Category": {"Number": 3, "Name": "Unhealthy for Sensitive Groups"},
        },
        {
            "DateObserved": "2026-06-25",
            "HourObserved": 14,
            "ReportingArea": "St. Thomas",
            "ParameterName": "O3",
            "AQI": 40,
            "Category": {"Number": 1, "Name": "Good"},
        },
    ]


async def test_airquality_alerts_when_unhealthy() -> None:
    settings = Settings(_env_file=None, airnow_api_key="key")  # type: ignore[call-arg]
    with respx.mock:
        respx.get(OBSERVATION_URL).mock(return_value=httpx.Response(200, json=_airnow(165)))
        async with httpx.AsyncClient() as client:
            result = await AirQualitySource(settings).poll(client)
    assert len(result.measurements) == 2
    assert len(result.observations) == 1
    assert result.observations[0].hazard_type is HazardType.AIR_QUALITY
    assert result.observations[0].level is AlertLevel.WATCH  # AQI 165 -> Unhealthy


async def test_airquality_silent_when_moderate() -> None:
    settings = Settings(_env_file=None, airnow_api_key="key")  # type: ignore[call-arg]
    with respx.mock:
        respx.get(OBSERVATION_URL).mock(return_value=httpx.Response(200, json=_airnow(55)))
        async with httpx.AsyncClient() as client:
            result = await AirQualitySource(settings).poll(client)
    assert len(result.measurements) == 2  # archived
    assert result.observations == []  # but no alert


# --- Airport (Aviation Weather METAR) --------------------------------------


async def test_airport_alerts_on_ifr(settings: Settings) -> None:
    metar = [
        {
            "icaoId": "TIST",
            "fltCat": "IFR",
            "rawOb": "TIST ...",
            "wspd": 12,
            "visib": 2,
            "obsTime": 1_700_000_000,
        }
    ]
    with respx.mock:
        respx.get(METAR_URL).mock(return_value=httpx.Response(200, json=metar))
        async with httpx.AsyncClient() as client:
            result = await AirportStatusSource(settings).poll(client)
    assert len(result.observations) == 1
    assert result.observations[0].hazard_type is HazardType.AIRPORT
    assert result.observations[0].level is AlertLevel.ADVISORY
    assert result.observations[0].island is Island.ST_THOMAS


async def test_airport_silent_on_vfr(settings: Settings) -> None:
    metar = [{"icaoId": "TIST", "fltCat": "VFR", "rawOb": "TIST ...", "obsTime": 1_700_000_000}]
    with respx.mock:
        respx.get(METAR_URL).mock(return_value=httpx.Response(200, json=metar))
        async with httpx.AsyncClient() as client:
            result = await AirportStatusSource(settings).poll(client)
    assert result.observations == []


# --- Manual override channel ------------------------------------------------


async def test_manual_alerts_become_observations(live_settings: Settings) -> None:
    url = f"{live_settings.directus_url}/items/carstorm_manual_alerts"
    payload = {
        "data": [
            {
                "id": 1,
                "hazard_type": "ferry",
                "island": "st_john",
                "level": 2,
                "title": "Ferry service suspended",
                "body": "Red Hook-Cruz Bay ferries are suspended due to high seas.",
                "recommendation": "Use the car barge; avoid tight flight connections.",
                "is_active": True,
                "expires": None,
            },
            {  # expired -> skipped
                "id": 2,
                "hazard_type": "public_safety",
                "island": "usvi",
                "level": 1,
                "title": "Old notice",
                "is_active": True,
                "expires": "2020-01-01T00:00:00Z",
            },
        ]
    }
    with respx.mock:
        respx.get(url).mock(return_value=httpx.Response(200, json=payload))
        async with httpx.AsyncClient() as client:
            result = await ManualAlertSource(live_settings).poll(client)
    assert len(result.observations) == 1
    obs = result.observations[0]
    assert obs.hazard_type is HazardType.FERRY
    assert obs.level is AlertLevel.WATCH
    assert obs.island is Island.ST_JOHN
    assert obs.recommendation.startswith("Use the car barge")
    assert obs.event_key == "manual:1"


# --- WAPA power outages -----------------------------------------------------


def _outage(lat: float, lng: float, out: int) -> dict:
    return {
        "outageRecID": f"x-{lat}-{lng}",
        "outagePoint": {"lat": lat, "lng": lng},
        "customersOutNow": out,
        "streetsAffected": ["Some Road"],
        "crewAssigned": False,
    }


async def test_wapa_aggregates_by_island_and_alerts_st_john(settings: Settings) -> None:
    base = settings.wapa_outage_base.rstrip("/")
    outages = [
        _outage(18.33, -64.74, 30),  # St. John -> 30 out (>= threshold -> alert)
        _outage(18.34, -64.93, 8),  # St. Thomas -> archived only
        _outage(17.74, -64.72, 7),  # St. Croix -> ignored
    ]
    summary = {
        "customersOutNow": 45,
        "customersServed": 54673,
        "updateTime": "2026-06-25T08:00:00-04:00",
    }
    with respx.mock:
        respx.get(f"{base}{OUTAGES_PATH}").mock(return_value=httpx.Response(200, json=outages))
        respx.get(f"{base}{SUMMARY_PATH}").mock(return_value=httpx.Response(200, json=summary))
        async with httpx.AsyncClient() as client:
            result = await WAPAOutageSource(settings).poll(client)

    by_island = {m.island: m.value for m in result.measurements}
    assert by_island[Island.ST_JOHN] == 30
    assert by_island[Island.ST_THOMAS] == 8  # St. Croix excluded
    assert len(result.observations) == 1
    obs = result.observations[0]
    assert obs.hazard_type is HazardType.POWER_OUTAGE
    assert obs.level is AlertLevel.ADVISORY
    assert obs.event_key == "wapa:power:st_john"


async def test_wapa_no_alert_below_threshold(settings: Settings) -> None:
    base = settings.wapa_outage_base.rstrip("/")
    with respx.mock:
        respx.get(f"{base}{OUTAGES_PATH}").mock(
            return_value=httpx.Response(200, json=[_outage(18.33, -64.74, 5)])
        )
        respx.get(f"{base}{SUMMARY_PATH}").mock(return_value=httpx.Response(200, json={}))
        async with httpx.AsyncClient() as client:
            result = await WAPAOutageSource(settings).poll(client)
    assert result.observations == []  # below threshold, archived only
    assert any(m.island is Island.ST_JOHN and m.value == 5 for m in result.measurements)


# --- Source gating ----------------------------------------------------------


def test_build_sources_gating() -> None:
    base = build_sources(Settings(_env_file=None))  # type: ignore[call-arg]
    names = {s.name for s in base}
    assert SourceName.WQP in names
    assert SourceName.AVWX in names
    assert SourceName.AIRNOW not in names  # no key
    assert SourceName.MANUAL not in names  # no Directus

    full = build_sources(
        Settings(_env_file=None, airnow_api_key="k", directus_token="t")  # type: ignore[call-arg]
    )
    full_names = {s.name for s in full}
    assert SourceName.AIRNOW in full_names
    assert SourceName.MANUAL in full_names
