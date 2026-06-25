"""Tests for the dashboard: astronomy, panel transforms, build isolation, server."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import respx

from carstorms.config import Settings
from carstorms.dashboard.astro import describe_weather, moon_phase, uv_risk
from carstorms.dashboard.builder import (
    FORECAST_URL,
    DashboardBuilder,
    _aqi_category,
    _mooring_suitability,
)
from carstorms.dashboard.server import WebServer
from carstorms.dashboard.state import DashboardState
from carstorms.health import HealthState
from carstorms.models import (
    AlertLevel,
    EventStatus,
    HazardEvent,
    HazardType,
    Island,
    SourceName,
)

# --- Astronomy & small helpers ---------------------------------------------


def test_moon_phase_structure() -> None:
    m = moon_phase(datetime(2026, 6, 25, tzinfo=UTC))
    assert m["name"] and m["emoji"]
    assert 0 <= int(m["illumination_pct"]) <= 100


def test_describe_weather_and_uv() -> None:
    assert describe_weather(95)["label"] == "Thunderstorm"
    assert describe_weather(None)["emoji"] == "❔"
    assert uv_risk(11) == "extreme"
    assert uv_risk(7) == "high"
    assert uv_risk(1) == "low"
    assert uv_risk(None) == "unknown"


def test_mooring_suitability() -> None:
    assert _mooring_suitability(0.5, 10) == "good"
    assert _mooring_suitability(1.5, 20) == "marginal"
    assert _mooring_suitability(2.5, 40) == "poor"
    assert _mooring_suitability(None, None) == "unknown"


def test_aqi_category() -> None:
    assert _aqi_category(40) == "Good"
    assert _aqi_category(75) == "Moderate"
    assert _aqi_category(160) == "Unhealthy"
    assert _aqi_category(None) == "unknown"


# --- Panel transforms (pure, None-safe) ------------------------------------


def test_forecast_panel_none_safe(settings: Settings) -> None:
    builder = DashboardBuilder(settings)
    assert builder._panel_forecast(None)["available"] is False
    j = {
        "current": {
            "temperature_2m": 26,
            "weather_code": 2,
            "time": "2026-06-25T08:00",
            "uv_index": 1.0,
        },
        "hourly": {
            "time": ["2026-06-25T08:00", "2026-06-25T09:00"],
            "temperature_2m": [26, 27],
            "precipitation_probability": [10, 20],
            "weather_code": [2, 3],
            "wind_speed_10m": [15, 16],
        },
        "daily": {
            "time": ["2026-06-25"],
            "weather_code": [2],
            "temperature_2m_max": [30],
            "temperature_2m_min": [25],
            "precipitation_probability_max": [40],
            "uv_index_max": [8.5],
            "sunrise": ["2026-06-25T05:45"],
            "sunset": ["2026-06-25T18:58"],
        },
    }
    forecast = builder._panel_forecast(j)
    assert forecast["available"] and forecast["current"]["temp"] == 26
    assert forecast["hourly"]
    assert builder._panel_uv(j)["today_max"] == 8.5
    assert builder._panel_uv(j)["risk"] == "very high"
    sun_moon = builder._panel_sun_moon(j, datetime(2026, 6, 25, tzinfo=UTC))
    # Emitted in St. John local time (AST, UTC-4).
    assert sun_moon["sunrise"].startswith("2026-06-25T05:45")
    assert sun_moon["sunrise"].endswith("-04:00")


def test_alerts_panel(settings: Settings) -> None:
    builder = DashboardBuilder(settings)
    assert builder._panel_alerts(None)["available"] is False
    event = HazardEvent(
        event_key="nhc:x",
        hazard_type=HazardType.TROPICAL_CYCLONE,
        title="Tropical Storm Demo",
        status=EventStatus.ACTIVE,
        current_level=AlertLevel.WATCH,
        peak_level=AlertLevel.WATCH,
        source=SourceName.NHC,
        source_event_id="x",
        island=Island.ST_JOHN,
    )
    panel = builder._panel_alerts([event])
    assert panel["count"] == 1
    item = panel["items"][0]
    assert item["level"] == int(AlertLevel.WATCH)
    assert item["recommendation"]  # template-generated advice present


def test_beaches_panel_shows_all_unshortened(settings: Settings) -> None:
    builder = DashboardBuilder(settings)
    rows = [
        {
            "station_name": f"A Very Long Beach Monitoring Location Name Number {i}",
            "island": "st_john",
            "value": 10,
            "unit": "MPN/100mL",
            "status": "ok",
            "sampled_at": "2026-06-25T00:00:00-04:00",
        }
        for i in range(55)
    ]
    panel = builder._panel_beaches(rows)
    assert panel["count"] == 55
    assert len(panel["items"]) == 55  # not capped
    # full names preserved (not truncated)
    assert panel["items"][0]["station_name"].startswith("A Very Long Beach Monitoring Location")


def test_nps_panel(settings: Settings) -> None:
    builder = DashboardBuilder(settings)
    assert builder._panel_nps(None)["available"] is False
    data = {
        "park": {
            "data": [
                {
                    "weatherInfo": "Tropical, warm year-round.",
                    "operatingHours": [{"description": "Open all year"}],
                }
            ]
        },
        "alerts": {
            "data": [{"category": "Park Closure", "title": "Trail X closed", "url": "http://x"}]
        },
    }
    panel = builder._panel_nps(data)
    assert panel["available"] is True
    assert panel["weather_info"] == "Tropical, warm year-round."
    assert panel["alerts"][0]["category"] == "Park Closure"


def test_wildlife_panel(settings: Settings) -> None:
    builder = DashboardBuilder(settings)
    assert builder._panel_wildlife(None)["available"] is False
    data = {
        "results": [
            {
                "observed_on": "2026-06-20",
                "uri": "http://x",
                "place_guess": "Cruz Bay, St John",
                "taxon": {
                    "name": "Iguana iguana",
                    "preferred_common_name": "Green Iguana",
                    "default_photo": {"square_url": "http://p.jpg"},
                },
            }
        ]
    }
    panel = builder._panel_wildlife(data)
    assert panel["available"] is True and panel["count"] == 1
    assert panel["items"][0]["name"] == "Green Iguana"
    assert panel["items"][0]["photo"] == "http://p.jpg"


def test_sargassum_panel_static(settings: Settings) -> None:
    panel = DashboardBuilder(settings)._panel_sargassum()
    assert panel["available"] is True
    assert panel["image"].endswith(".png")
    assert "usf.edu" in panel["source_url"]


def test_tropical_panel_quiet(settings: Settings) -> None:
    builder = DashboardBuilder(settings)
    panel = builder._panel_tropical({"activeStorms": []})
    assert panel["active"] == []
    assert "No active" in panel["note"]


def test_power_panel_aggregates_by_island(settings: Settings) -> None:
    builder = DashboardBuilder(settings)
    assert builder._panel_power(None)["available"] is False
    data = {
        "outages": [
            {"outagePoint": {"lat": 18.33, "lng": -64.74}, "customersOutNow": 12},  # St. John
            {"outagePoint": {"lat": 18.34, "lng": -64.93}, "customersOutNow": 8},  # St. Thomas
            {
                "outagePoint": {"lat": 17.74, "lng": -64.72},
                "customersOutNow": 99,
            },  # St. Croix (ignored)
        ],
        "summary": {
            "customersOutNow": 20,
            "customersServed": 54673,
            "updateTime": "2026-06-25T08:00:00-04:00",
        },
    }
    panel = builder._panel_power(data)
    assert panel["st_john"]["out"] == 12
    assert panel["st_thomas"]["out"] == 8
    assert panel["territory_out"] == 20
    assert panel["updated_at"].endswith("-04:00")


# --- build() resilience -----------------------------------------------------


async def test_build_isolates_panel_failures(settings: Settings) -> None:
    """One feed up, the rest failing: the page still builds, bad cards degrade."""
    builder = DashboardBuilder(settings)  # repo=None -> directus panels unavailable
    with respx.mock:
        respx.get(FORECAST_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "current": {"temperature_2m": 26, "time": "2026-06-25T08:00"},
                    "hourly": {},
                    "daily": {},
                },
            )
        )
        # All other endpoints are unmocked -> respx raises -> isolated per panel.
        async with httpx.AsyncClient() as client:
            snapshot = await builder.build(client)

    panels = snapshot["panels"]
    assert panels["forecast"]["available"] is True
    assert panels["marine"]["available"] is False
    assert panels["alerts"]["available"] is False  # no Directus
    assert "generated_at" in snapshot


# --- Web server -------------------------------------------------------------


def test_webserver_serves_routes() -> None:
    import json
    import urllib.error
    import urllib.request

    health = HealthState(max_age_seconds=900)
    dashboard = DashboardState()
    dashboard.update({"generated_at": "2026-06-25T00:00:00Z", "panels": {}})
    server = WebServer("127.0.0.1", 0, health, dashboard)
    port = server._server.server_address[1]
    server.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            assert r.status == 200
            assert "St. John" in r.read().decode("utf-8")

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/dashboard.json", timeout=5) as r:
            assert r.status == 200
            assert json.loads(r.read())["panels"] == {}

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as r:
            assert r.status in (200, 503)

        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/nope", timeout=5)
            raise AssertionError("expected 404")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        server.stop()
