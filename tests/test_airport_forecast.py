"""Independent STT airport forecast model tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import respx

from carstorms.config import Settings
from carstorms.dashboard.airport import build_airport_panel
from carstorms.dashboard.builder import FLIGHTAWARE_AIRPORT_URL, DashboardBuilder

NOW = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)


def _metar(category: str = "VFR") -> list[dict]:
    return [
        {
            "fltCat": category,
            "obsTime": int(NOW.timestamp()),
            "wspd": 10,
            "wgst": None,
            "rawOb": "TIST 281153Z 10010KT 10SM FEW030 29/24 A3002",
        }
    ]


def _taf(*, thunderstorm: bool = False) -> list[dict]:
    return [
        {
            "issueTime": "2026-06-28T11:42:00Z",
            "rawTAF": "TAF TIST test",
            "fcsts": [
                {
                    "timeFrom": int(NOW.timestamp()),
                    "timeTo": int(NOW.timestamp()) + 21600,
                    "wspd": 12,
                    "wgst": 30 if thunderstorm else None,
                    "visib": "2" if thunderstorm else "6+",
                    "wxString": "TSRA" if thunderstorm else "VCSH",
                    "clouds": [{"cover": "BKN", "base": 700 if thunderstorm else 3500}],
                }
            ],
        }
    ]


def _faa(*, local_ground_stop: bool = False) -> dict:
    events = []
    if local_ground_stop:
        events.append(
            {
                "airportId": "STT",
                "groundStop": {"impactingCondition": "thunderstorms"},
                "groundDelay": None,
                "airportClosure": None,
                "arrivalDelay": None,
                "departureDelay": None,
            }
        )
    return {"events": events, "operations_plan": {}, "fetched_at": NOW.isoformat()}


def _flight_data() -> dict:
    return {
        "enabled": True,
        "data": {
            "departures": [
                {
                    "fa_flight_id": "AAL1-test",
                    "ident": "AAL1",
                    "ident_iata": "AA1",
                    "operator": "AAL",
                    "aircraft_type": "A319",
                    "scheduled_out": "2026-06-28T14:00:00Z",
                    "estimated_out": "2026-06-28T14:45:00Z",
                    "destination": {"code_iata": "MIA", "city": "Miami"},
                },
                {
                    "fa_flight_id": "DAL2-test",
                    "ident": "DAL2",
                    "ident_iata": "DL2",
                    "operator": "DAL",
                    "aircraft_type": "B752",
                    "scheduled_out": "2026-06-28T15:00:00Z",
                    "estimated_out": "2026-06-28T15:00:00Z",
                    "destination": {"code_iata": "ATL", "city": "Atlanta"},
                },
                {
                    "fa_flight_id": "UAL3-test",
                    "ident": "UAL3",
                    "operator": "UAL",
                    "aircraft_type": "B737",
                    "scheduled_out": "2026-06-28T16:00:00Z",
                    "cancelled": True,
                    "destination": {"code_iata": "EWR", "city": "Newark"},
                },
            ],
            "arrivals": [
                {
                    "fa_flight_id": "JBU4-test",
                    "ident": "JBU4",
                    "ident_iata": "B64",
                    "operator": "JBU",
                    "aircraft_type": "A320",
                    "scheduled_in": "2026-06-28T13:00:00Z",
                    "estimated_in": "2026-06-28T14:00:00Z",
                    "origin": {"code_iata": "JFK", "city": "New York"},
                }
            ],
            "scheduled_departures": [],
            "scheduled_arrivals": [],
        },
    }


def test_weather_only_forecast_is_available_but_limited() -> None:
    panel = build_airport_panel(_metar(), _taf(), _faa(), {"enabled": False}, NOW)

    assert panel["available"] is True
    assert panel["risk"]["label"] == "low"
    assert panel["risk"]["confidence"] == "limited"
    assert panel["operations"]["available"] is False
    assert panel["crowd"]["available"] is False
    assert panel["methodology"]["crowd_model"].endswith("not a live TSA wait time.")


def test_local_faa_ground_stop_and_storm_cannot_be_averaged_away() -> None:
    panel = build_airport_panel(
        _metar("IFR"),
        _taf(thunderstorm=True),
        _faa(local_ground_stop=True),
        {"enabled": False},
        NOW,
    )

    assert panel["risk"]["score"] >= 95
    assert panel["risk"]["label"] == "severe"
    assert panel["faa"]["local_events"][0]["type"] == "ground stop"
    assert panel["weather"]["score"] >= 80


def test_live_flights_add_delay_statistics_and_crowd_forecast() -> None:
    panel = build_airport_panel(_metar(), _taf(), _faa(), _flight_data(), NOW)

    operations = panel["operations"]
    assert operations["available"] is True
    assert operations["total_flights"] == 4
    assert operations["known_delay_flights"] == 3
    assert operations["delayed_flights"] == 2
    assert operations["cancelled_flights"] == 1
    assert operations["average_delay_minutes"] == 35
    assert panel["crowd"]["available"] is True
    assert panel["crowd"]["peak"]["estimated_passengers"] > 0
    assert panel["risk"]["confidence"] == "high"
    assert panel["next_flights"][0]["ident"] == "B64"
    assert panel["next_flights"][1]["delay_minutes"] == 45


def test_faa_gateway_event_uses_actual_flight_routes() -> None:
    faa = {
        "events": [
            {
                "airportId": "MIA",
                "groundDelay": {"impactingCondition": "thunderstorms", "avgDelay": 45},
            }
        ],
        "operations_plan": {},
        "fetched_at": NOW.isoformat(),
    }
    panel = build_airport_panel(_metar(), _taf(), faa, _flight_data(), NOW)

    assert panel["faa"]["network_events"][0]["airport"] == "MIA"
    assert any("connection airport MIA" in reason for reason in panel["risk"]["reasons"])


def test_runway_crosswind_contributes_to_weather_risk() -> None:
    metar = _metar()
    metar[0].update({"wdir": 190, "wspd": 25, "wgst": 25})
    panel = build_airport_panel(metar, _taf(), _faa(), {"enabled": False}, NOW)

    assert panel["weather"]["crosswind_component_kt"] == 25.0
    assert panel["weather"]["score"] >= 75


async def test_flightaware_fetch_is_server_side_and_rate_limited(settings: Settings) -> None:
    settings.flightaware_api_key = "secret-test-key"
    settings.airport_flight_refresh_seconds = 900
    builder = DashboardBuilder(settings)
    url = FLIGHTAWARE_AIRPORT_URL.format(icao=settings.airport_icao)

    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(url, params={"max_pages": 1}).mock(
            return_value=httpx.Response(200, json={"departures": []})
        )
        async with httpx.AsyncClient() as client:
            first = await builder._fetch_flightaware(client, NOW)
            second = await builder._fetch_flightaware(client, NOW + timedelta(minutes=5))

    assert route.call_count == 1
    assert route.calls[0].request.headers["x-apikey"] == "secret-test-key"
    assert first == second
    assert first["enabled"] is True
