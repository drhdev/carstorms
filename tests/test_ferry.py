"""Tests for the curated ferry timetable and next-departure logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from carstorms.content.ferry import ROUTES, next_departures

AST = timezone(timedelta(hours=-4))


def test_next_departures_covers_all_routes_both_directions() -> None:
    now = datetime(2026, 6, 25, 9, 5, tzinfo=AST)  # Thursday 09:05
    deps = next_departures(now)
    assert len(deps) == len(ROUTES)
    for d in deps:
        assert d["to_st_john"] is not None and d["to_st_thomas"] is not None
        assert d["to_st_john"] >= now and d["to_st_thomas"] >= now


def test_redhook_hourly_next_on_the_hour() -> None:
    now = datetime(2026, 6, 25, 9, 5, tzinfo=AST)
    by_key = {d["key"]: d for d in next_departures(now)}
    nxt = by_key["redhook"]["to_st_john"]
    assert nxt.hour == 10 and nxt.minute == 0  # just missed 09:00, next is 10:00


def test_next_departure_rolls_to_next_day() -> None:
    now = datetime(2026, 6, 25, 23, 59, tzinfo=AST)  # after last downtown sailing
    by_key = {d["key"]: d for d in next_departures(now)}
    nxt = by_key["downtown"]["to_st_john"]  # Charlotte Amalie -> Cruz Bay first is 10:00
    assert nxt.date() > now.date()
    assert nxt.hour == 10
