"""Tests for the dashboard: astronomy, panel transforms, build isolation, server."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import respx

from carstorms.config import Settings
from carstorms.dashboard.advisory import build_activity_advisory
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


def _activity_inputs(*, storm: bool = False, wave: float = 0.4, wave_period: float = 8.0) -> tuple[dict, dict]:
    times = [f"2026-06-25T{hour:02d}:00" for hour in range(6, 18)]
    count = len(times)
    forecast = {
        "hourly": {
            "time": times,
            "temperature_2m": [27.0] * count,
            "apparent_temperature": [29.0] * count,
            "relative_humidity_2m": [68.0] * count,
            "precipitation_probability": [15.0] * count,
            "precipitation": [0.0] * count,
            "weather_code": ([95] * count) if storm else ([1] * count),
            "wind_speed_10m": [10.0] * count,
            "wind_gusts_10m": [18.0] * count,
            "uv_index": [4.0] * count,
            "visibility": [24000.0] * count,
        }
    }
    marine = {
        "hourly": {
            "time": times,
            "wave_height": [wave] * count,
            "wave_period": [wave_period] * count,
            "swell_wave_height": [wave] * count,
            "swell_wave_period": [9.0] * count,
            "sea_surface_temperature": [28.0] * count,
        }
    }
    return forecast, marine


def _advisory(*, storm: bool = False, wave: float = 0.4, wave_period: float = 8.0, sargassum: str = "low") -> dict:
    forecast, marine = _activity_inputs(storm=storm, wave=wave, wave_period=wave_period)
    return build_activity_advisory(
        forecast,
        marine,
        {"available": True, "us_aqi": 28},
        {"available": True, "level": sargassum},
        {"available": True, "items": []},
        {"available": True, "items": []},
        datetime(2026, 6, 25, 12, tzinfo=UTC),
    )


def _score(panel: dict, key: str, period: int = 0) -> int:
    return next(item["score"] for item in panel["periods"][period]["all"] if item["key"] == key)


def test_activity_advisory_scores_calm_day_and_period_meals() -> None:
    panel = _advisory()
    assert panel["available"] is True
    assert len(panel["periods"]) == 2
    assert _score(panel, "snorkel") >= 80
    names = [[item["name"] for item in period["all"]] for period in panel["periods"]]
    assert "Long breakfast outdoors" in names[0]
    assert "Long lunch / early dinner" in names[1]
    assert panel["methodology"]


def test_activity_advisory_lightning_applies_safety_caps() -> None:
    panel = _advisory(storm=True)
    assert _score(panel, "hike") <= 10
    assert _score(panel, "snorkel") <= 15
    assert _score(panel, "wellness") > _score(panel, "hike")
    assert "Thunderstorms" in panel["periods"][0]["safety_note"]


def test_activity_advisory_rough_seas_and_sargassum_are_specific() -> None:
    calm = _advisory()
    rough = _advisory(wave=1.8, sargassum="elevated")
    assert _score(rough, "snorkel") <= 25
    assert _score(rough, "swim") <= 20
    assert _score(rough, "beach") < _score(calm, "beach")
    assert _score(rough, "tennis") == _score(calm, "tennis")


def test_activity_advisory_long_period_swell_reduces_water_scores() -> None:
    short_period = _advisory(wave=0.8, wave_period=7)
    long_period = _advisory(wave=0.8, wave_period=14)
    assert _score(long_period, "snorkel") < _score(short_period, "snorkel")
    assert "@ 14s" in long_period["periods"][0]["summary"]


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


def test_sargassum_panel_indicator(settings: Settings) -> None:
    builder = DashboardBuilder(settings)
    # No data -> unavailable but still offers the USF link.
    assert builder._panel_sargassum(None)["available"] is False
    data = {
        "table": {
            "columnNames": ["time", "latitude", "longitude", "AFAI"],
            "rows": [
                ["2026-06-25T12:00:00Z", 18.4, -64.8, 0.0015],
                ["2026-06-25T12:00:00Z", 18.3, -64.7, None],  # cloud-masked
                ["2026-06-25T12:00:00Z", 18.35, -64.75, -0.001],
            ],
        }
    }
    panel = builder._panel_sargassum(data)
    assert panel["available"] is True
    assert panel["level"] == "moderate"  # peak AFAI 0.0015 -> moderate
    assert panel["afai_peak"] == 0.0015
    assert panel["observed_at"].endswith("-04:00")


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


def test_power_panel_reports_exact_ongoing_duration(settings: Settings) -> None:
    builder = DashboardBuilder(settings)
    data = {
        "outages": [
            {
                "outagePoint": {"lat": 18.33, "lng": -64.74},
                "customersOutNow": 20,
                "outageStartTime": "2026-06-25T08:00:00-04:00",
            }
        ],
        "summary": {"updateTime": "2026-06-25T11:55:00-04:00"},
    }
    panel = builder._panel_power(data, None, datetime(2026, 6, 25, 16, tzinfo=UTC))
    timeline = panel["st_john_timeline"]
    assert timeline["available"] is True
    assert timeline["status"] == "outage"
    assert timeline["since"] == "2026-06-25T08:00:00-04:00"
    assert timeline["since_precision"] == "reported"
    assert timeline["duration"] == {"hours": 4.0, "days": 0.17, "weeks": 0.02}


def test_power_panel_reports_uninterrupted_since_and_last_failure(settings: Settings) -> None:
    builder = DashboardBuilder(settings)
    history = [
        {
            "value": 0,
            "status": "ok",
            "sampled_at": "2026-06-25T11:00:00-04:00",
            "raw": {},
        },
        {
            "value": 12,
            "status": "outage",
            "sampled_at": "2026-06-25T09:00:00-04:00",
            "raw": {"active_outage_starts": ["2026-06-25T07:45:00-04:00"]},
        },
        {
            "value": 0,
            "status": "ok",
            "sampled_at": "2026-06-25T10:00:00-04:00",
            "raw": {},
        },
        {
            "value": 12,
            "status": "outage",
            "sampled_at": "2026-06-25T08:00:00-04:00",
            "raw": {"active_outage_starts": ["2026-06-25T07:45:00-04:00"]},
        },
    ]
    data = {
        "outages": [],
        "summary": {"updateTime": "2026-06-25T12:00:00-04:00"},
    }
    panel = builder._panel_power(data, history, datetime(2026, 6, 25, 16, tzinfo=UTC))
    timeline = panel["st_john_timeline"]
    assert timeline["status"] == "uninterrupted"
    assert timeline["since"] == "2026-06-25T10:00:00-04:00"
    assert timeline["duration"]["hours"] == 2.0
    assert timeline["last_outage"]["duration"]["hours"] == 2.2
    assert timeline["last_outage"]["start_precision"] == "reported"
    assert timeline["last_outage"]["end_precision"] == "first_confirmed"


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
