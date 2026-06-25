"""Tests for the hazard sources using mocked HTTP responses (respx)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import respx

from carstorms.config import Settings
from carstorms.models import AlertLevel, HazardType
from carstorms.sources.nhc import CURRENT_STORMS_URL, NHCSource
from carstorms.sources.nws import ALERTS_URL, NWSSource
from carstorms.sources.openmeteo import FORECAST_URL, OpenMeteoSource
from carstorms.sources.usgs import QUERY_URL, USGSSource


def _nws_feature(event: str, severity: str, urgency: str, vtec: str) -> dict:
    return {
        "properties": {
            "id": f"urn:{vtec}",
            "event": event,
            "severity": severity,
            "urgency": urgency,
            "certainty": "Likely",
            "status": "Actual",
            "messageType": "Alert",
            "headline": f"{event} issued",
            "description": "Heavy rainfall expected.",
            "instruction": "Move to higher ground.",
            "effective": "2026-06-25T12:00:00-04:00",
            "expires": "2026-06-25T18:00:00-04:00",
            "parameters": {"VTEC": [vtec]},
        }
    }


async def test_nws_threads_watch_and_warning_into_one_event(settings: Settings) -> None:
    payload = {
        "features": [
            _nws_feature(
                "Flash Flood Watch",
                "Moderate",
                "Future",
                "/O.NEW.TJSJ.FF.A.0001.000000T0000Z-000000T0000Z/",
            ),
            _nws_feature(
                "Flash Flood Warning",
                "Severe",
                "Expected",
                "/O.NEW.TJSJ.FF.W.0002.000000T0000Z-000000T0000Z/",
            ),
        ]
    }
    with respx.mock:
        respx.get(ALERTS_URL).mock(return_value=httpx.Response(200, json=payload))
        async with httpx.AsyncClient() as client:
            observations = await NWSSource(settings)._fetch(client)

    assert len(observations) == 1
    obs = observations[0]
    assert obs.event_key == "nws:TJSJ.FF"
    assert obs.hazard_type is HazardType.FLASH_FLOOD
    assert obs.level is AlertLevel.WARNING
    assert obs.image_urls  # radar attached for precipitation hazards


async def test_usgs_filters_to_relevant_quakes(settings: Settings) -> None:
    payload = {
        "features": [
            {  # near + moderate -> kept
                "id": "near1",
                "properties": {
                    "mag": 3.5,
                    "place": "near",
                    "time": 1,
                    "tsunami": 0,
                    "title": "M 3.5",
                },
                "geometry": {"coordinates": [-64.8, 18.45, 10]},
            },
            {  # far + small -> dropped
                "id": "far1",
                "properties": {
                    "mag": 3.0,
                    "place": "far",
                    "time": 1,
                    "tsunami": 0,
                    "title": "M 3.0",
                },
                "geometry": {"coordinates": [-68.0, 16.0, 10]},
            },
            {  # notable magnitude anywhere -> kept (no detail -> no image fetch)
                "id": "big1",
                "properties": {
                    "mag": 5.2,
                    "place": "regional",
                    "time": 1,
                    "tsunami": 0,
                    "title": "M 5.2",
                },
                "geometry": {"coordinates": [-67.0, 17.0, 20]},
            },
        ]
    }
    with respx.mock:
        respx.get(QUERY_URL).mock(return_value=httpx.Response(200, json=payload))
        async with httpx.AsyncClient() as client:
            observations = await USGSSource(settings)._fetch(client)

    ids = {obs.source_event_id for obs in observations}
    assert ids == {"near1", "big1"}


async def test_nhc_parses_storm_and_attaches_cone(settings: Settings) -> None:
    payload = {
        "activeStorms": [
            {
                "id": "al012026",
                "binNumber": "AT1",
                "name": "Testy",
                "classification": "HU",
                "intensity": "80",
                "pressure": "975",
                "latitudeNumeric": 18.5,
                "longitudeNumeric": -65.5,
                "movementDir": 300,
                "movementSpeed": 10,
                "lastUpdate": "2026-06-25T12:00:00Z",
            }
        ]
    }
    with respx.mock:
        respx.get(CURRENT_STORMS_URL).mock(return_value=httpx.Response(200, json=payload))
        async with httpx.AsyncClient() as client:
            observations = await NHCSource(settings)._fetch(client)

    assert len(observations) == 1
    obs = observations[0]
    assert obs.event_key == "nhc:al012026"
    assert obs.hazard_type is HazardType.TROPICAL_CYCLONE
    assert obs.level >= AlertLevel.WATCH
    assert obs.distance_km is not None and obs.distance_km < 150
    assert any("AL012026_CONE" in url for url in obs.image_urls)


async def test_openmeteo_emits_thunderstorm(settings: Settings) -> None:
    base = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    times = [(base + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(6)]
    codes = [1, 95, 3, 1, 1, 1]  # thunderstorm at +1h
    payload = {
        "hourly": {
            "time": times,
            "weather_code": codes,
            "cape": [200, 1800, 100, 0, 0, 0],
            "precipitation_probability": [10, 70, 5, 0, 0, 0],
            "wind_gusts_10m": [20, 45, 15, 10, 10, 10],
        }
    }
    with respx.mock:
        respx.get(FORECAST_URL).mock(return_value=httpx.Response(200, json=payload))
        async with httpx.AsyncClient() as client:
            observations = await OpenMeteoSource(settings)._fetch(client)

    assert len(observations) == 1
    obs = observations[0]
    assert obs.hazard_type is HazardType.THUNDERSTORM
    assert obs.level in (AlertLevel.INFORMATIONAL, AlertLevel.ADVISORY)
    assert obs.event_key == "openmeteo:thunderstorm"


async def test_source_poll_isolates_errors(settings: Settings) -> None:
    with respx.mock:
        respx.get(CURRENT_STORMS_URL).mock(return_value=httpx.Response(500))
        async with httpx.AsyncClient() as client:
            result = await NHCSource(settings).poll(client)
    assert result.status == "error"
    assert result.observations == []
