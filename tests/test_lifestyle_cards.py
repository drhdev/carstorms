"""Wind and restaurant dashboard-card tests."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import respx

from carstorms.dashboard.restaurants import (
    GOOGLE_PLACES_SEARCH_URL,
    RESTAURANTS,
    build_restaurant_panel,
    fetch_google_restaurants,
)
from carstorms.dashboard.wind import assess_wind, build_wind_panel


def test_wind_severity_bands_and_direction() -> None:
    calm = assess_wind(10, 18, 90)
    caution = assess_wind(42, 58, 225)
    dangerous = assess_wind(72, 92, 5)
    assert calm["band"] == "green" and calm["direction"] == "E (from)"
    assert caution["band"] == "yellow"
    assert dangerous["band"] == "red" and dangerous["severity"] >= 65


def test_wind_panel_splits_today_and_applies_alert_floor() -> None:
    times = [f"2026-06-28T{hour:02d}:00" for hour in range(6, 24)]
    forecast = {
        "current": {
            "time": "2026-06-28T08:00",
            "wind_speed_10m": 14,
            "wind_gusts_10m": 24,
            "wind_direction_10m": 70,
        },
        "hourly": {
            "time": times,
            "wind_speed_10m": [18] * len(times),
            "wind_gusts_10m": [30] * len(times),
            "wind_direction_10m": [90] * len(times),
        },
    }
    alerts = {"items": [{"hazard_type": "wind", "level": 3}]}
    panel = build_wind_panel(forecast, alerts, datetime(2026, 6, 28, 12, tzinfo=UTC))
    assert panel["available"] is True
    assert [period["key"] for period in panel["periods"]] == [
        "morning",
        "afternoon",
        "evening",
    ]
    assert panel["current"]["severity"] >= 75
    assert panel["current"]["band"] == "red"


def _restaurant_panel(google_data=None, notices=None, *, power_out: int = 0) -> dict:
    return build_restaurant_panel(
        google_data,
        notices,
        {"current": {"weather_code": 1, "wind_gusts_10m": 20}},
        {"st_john": {"out": power_out}},
        {"items": []},
        datetime(2026, 6, 28, 20, tzinfo=UTC),  # Sunday, 4 PM AST
    )


def test_restaurants_fallback_is_explicitly_not_live() -> None:
    panel = _restaurant_panel()
    skinny = next(item for item in panel["items"] if item["key"] == "skinny_legs")
    miss_lucys = next(item for item in panel["items"] if item["key"] == "miss_lucys")
    extra_virgin = next(item for item in panel["items"] if item["key"] == "extra_virgin")
    assert skinny["status"] == "scheduled_open"
    assert skinny["hours_today"] == "11 AM-8 PM"
    assert skinny["source_tier"] == "published_schedule"
    assert "not live confirmation" in skinny["source_label"].lower()
    assert miss_lucys["status"] == "unconfirmed"
    assert extra_virgin["status"] == "scheduled_closed"  # opens later Sunday
    assert extra_virgin["hours_today"] == "5:30 PM-9 PM"
    assert panel["live_source_available"] is False


def test_restaurant_known_weekly_closure_is_not_unknown() -> None:
    panel = build_restaurant_panel(
        None,
        None,
        None,
        {"st_john": {"out": 0}},
        {"items": []},
        datetime(2026, 6, 27, 20, tzinfo=UTC),  # Saturday afternoon AST
    )
    lime = next(item for item in panel["items"] if item["key"] == "lime_inn")
    assert lime["status"] == "scheduled_closed_today"
    assert lime["hours_today"] == "Closed today"


def test_google_special_hours_and_verified_notice_override() -> None:
    descriptions = [
        "Monday: 11:00 AM-8:00 PM",
        "Tuesday: 11:00 AM-8:00 PM",
        "Wednesday: 11:00 AM-8:00 PM",
        "Thursday: 11:00 AM-8:00 PM",
        "Friday: 11:00 AM-8:00 PM",
        "Saturday: 11:00 AM-8:00 PM",
        "Sunday: Closed",
    ]
    google = [
        {
            "key": "skinny_legs",
            "fetched_at": "2026-06-28T19:55:00+00:00",
            "place": {
                "businessStatus": "OPERATIONAL",
                "currentOpeningHours": {
                    "openNow": False,
                    "weekdayDescriptions": descriptions,
                    "specialDays": [{"date": {"year": 2026, "month": 6, "day": 28}}],
                },
            },
        }
    ]
    google_panel = _restaurant_panel(google)
    skinny = next(item for item in google_panel["items"] if item["key"] == "skinny_legs")
    assert skinny["status"] == "closed_today"
    assert skinny["special_hours"] is True
    assert skinny["source_tier"] == "google_current_hours"

    notices = [
        {
            "category": "restaurant_closure",
            "title": "Skinny Legs closed today",
            "body": "Closed due to a power interruption.",
            "starts_at": "2026-06-28T12:00:00-04:00",
            "ends_at": "2026-06-28T23:59:00-04:00",
            "url": "https://www.skinnylegsvi.com/",
        }
    ]
    verified_panel = _restaurant_panel(google, notices)
    skinny = next(item for item in verified_panel["items"] if item["key"] == "skinny_legs")
    assert skinny["source_tier"] == "verified_same_day"
    assert skinny["status"] == "closed_today"
    assert "power interruption" in skinny["note"]


def test_restaurant_card_warns_during_wapa_outage() -> None:
    panel = _restaurant_panel(power_out=25)
    assert panel["disruption"]["level"] == "yellow"
    assert panel["disruption"]["call_ahead"] is True
    assert "WAPA" in panel["disruption"]["notes"][0]


async def test_google_places_fetches_each_curated_restaurant() -> None:
    with respx.mock:
        route = respx.post(GOOGLE_PLACES_SEARCH_URL).mock(
            return_value=httpx.Response(
                200,
                json={"places": [{"id": "demo", "displayName": {"text": "Demo"}}]},
            )
        )
        async with httpx.AsyncClient() as client:
            rows = await fetch_google_restaurants(
                client,
                api_key="test-key",
                latitude=18.335,
                longitude=-64.735,
                fetched_at=datetime(2026, 6, 28, tzinfo=UTC),
            )
    assert len(rows) == len(RESTAURANTS)
    assert route.call_count == len(RESTAURANTS)
    assert route.calls[0].request.headers["x-goog-api-key"] == "test-key"
    assert "places.attributions" in route.calls[0].request.headers["x-goog-fieldmask"]
