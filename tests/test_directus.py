"""Tests for the Directus client, repository and schema bootstrap (mocked HTTP)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import respx

from carstorms.config import Settings
from carstorms.directus import DirectusClient, DirectusRepository, ensure_schema
from carstorms.models import (
    AlertLevel,
    EventStatus,
    HazardEvent,
    HazardType,
    Island,
    Measurement,
    SourceName,
)

BASE = "https://directus.example.test"


def _event() -> HazardEvent:
    now = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)
    return HazardEvent(
        event_key="nhc:al012026",
        hazard_type=HazardType.TROPICAL_CYCLONE,
        title="Hurricane Testy",
        status=EventStatus.ACTIVE,
        current_level=AlertLevel.WARNING,
        peak_level=AlertLevel.WARNING,
        source=SourceName.NHC,
        source_event_id="al012026",
        first_seen=now,
        last_updated=now,
    )


async def test_upsert_event_create_sets_id(live_settings: Settings) -> None:
    with respx.mock:
        respx.post(f"{BASE}/items/carstorm_events").mock(
            return_value=httpx.Response(200, json={"data": {"id": 7}})
        )
        async with DirectusClient(live_settings) as client:
            repo = DirectusRepository(client, "carstorm_")
            saved = await repo.upsert_event(_event())
    assert saved.id == 7


async def test_upsert_event_update_uses_patch(live_settings: Settings) -> None:
    event = _event()
    event.id = 9
    with respx.mock:
        route = respx.patch(f"{BASE}/items/carstorm_events/9").mock(
            return_value=httpx.Response(200, json={"data": {"id": 9}})
        )
        async with DirectusClient(live_settings) as client:
            repo = DirectusRepository(client, "carstorm_")
            await repo.upsert_event(event)
    assert route.called


async def test_get_active_events_parses_models(live_settings: Settings) -> None:
    record = {
        "id": 3,
        "event_key": "usgs:abc",
        "hazard_type": "earthquake",
        "title": "M 5.0",
        "status": "active",
        "current_level": 2,
        "peak_level": 3,
        "source": "usgs",
        "source_event_id": "abc",
        "is_active": True,
    }
    with respx.mock:
        respx.get(f"{BASE}/items/carstorm_events").mock(
            return_value=httpx.Response(200, json={"data": [record]})
        )
        async with DirectusClient(live_settings) as client:
            repo = DirectusRepository(client, "carstorm_")
            events = await repo.get_active_events()
    assert "usgs:abc" in events
    parsed = events["usgs:abc"]
    assert parsed.current_level is AlertLevel.WATCH
    assert parsed.hazard_type is HazardType.EARTHQUAKE


async def test_ensure_schema_is_idempotent_when_present(live_settings: Settings) -> None:
    with respx.mock:
        respx.get(url__regex=rf"{BASE}/collections/.+").mock(
            return_value=httpx.Response(200, json={"data": {}})
        )
        respx.get(url__regex=rf"{BASE}/fields/.+").mock(
            return_value=httpx.Response(200, json={"data": {}})
        )
        create_collection = respx.post(f"{BASE}/collections").mock(
            return_value=httpx.Response(200, json={})
        )
        create_field = respx.post(url__regex=rf"{BASE}/fields/.+").mock(
            return_value=httpx.Response(200, json={})
        )
        async with DirectusClient(live_settings) as client:
            await ensure_schema(client, "carstorm_")
    assert not create_collection.called
    assert not create_field.called


async def test_archive_measurements_dedups(live_settings: Settings) -> None:
    sampled = datetime(2026, 2, 24, tzinfo=UTC)
    measurements = [
        Measurement(
            source=SourceName.WQP,
            metric="enterococcus",
            value=120,
            island=Island.ST_JOHN,
            station="A",
            sampled_at=sampled,
        ),
        Measurement(
            source=SourceName.WQP,
            metric="enterococcus",
            value=10,
            island=Island.ST_THOMAS,
            station="B",
            sampled_at=sampled,
        ),
    ]
    existing = {
        "data": [
            {
                "source": "wqp",
                "metric": "enterococcus",
                "station": "A",
                "sampled_at": "2026-02-24T00:00:00+00:00",
            }
        ]
    }
    with respx.mock:
        respx.get(f"{BASE}/items/carstorm_measurements").mock(
            return_value=httpx.Response(200, json=existing)
        )
        post = respx.post(f"{BASE}/items/carstorm_measurements").mock(
            return_value=httpx.Response(200, json={"data": {"id": 1}})
        )
        async with DirectusClient(live_settings) as client:
            repo = DirectusRepository(client, "carstorm_")
            inserted = await repo.archive_measurements(measurements)
    assert inserted == 1  # station A already archived, only B is new
    assert post.call_count == 1


async def test_ensure_schema_creates_when_absent(live_settings: Settings) -> None:
    with respx.mock:
        respx.get(url__regex=rf"{BASE}/collections/.+").mock(return_value=httpx.Response(404))
        respx.get(url__regex=rf"{BASE}/fields/.+").mock(return_value=httpx.Response(404))
        create_collection = respx.post(f"{BASE}/collections").mock(
            return_value=httpx.Response(200, json={})
        )
        respx.post(url__regex=rf"{BASE}/fields/.+").mock(return_value=httpx.Response(200, json={}))
        respx.post(f"{BASE}/relations").mock(return_value=httpx.Response(200, json={}))
        async with DirectusClient(live_settings) as client:
            await ensure_schema(client, "carstorm_")
    # One create per collection in the schema.
    assert create_collection.call_count == 7
