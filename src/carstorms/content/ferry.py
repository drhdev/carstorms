"""St. John ferry timetable and next-departure computation.

No operator publishes a machine-readable schedule, and the published timetables
are very stable, so the schedule is curated here (reviewed monthly) rather than
scraped from a brittle HTML page. ``next_departures`` returns the next sailing in
each direction for all three routes given the current St. John local time.

Sources: stjohnticketing.com, dpw.vi.gov/ferries, viport.com (reviewed 2026-06).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

SCHEDULE_REVIEWED = "2026-06-01"

_MON_FRI = frozenset({0, 1, 2, 3, 4})


@dataclass(frozen=True, slots=True)
class Departure:
    at: str  # "HH:MM" St. John local time
    days: frozenset[int] | None = None  # None = daily; else weekday ints (0=Mon)


@dataclass(frozen=True, slots=True)
class FerryRoute:
    key: str
    name: str
    toward_st_john: list[Departure] = field(default_factory=list)
    toward_st_thomas: list[Departure] = field(default_factory=list)


def _hourly(start: int, end: int) -> list[Departure]:
    """On-the-hour departures from ``start`` to ``end`` (inclusive), 24h clock."""
    return [Departure(f"{h:02d}:00") for h in range(start, end + 1)]


# --- Curated schedule -------------------------------------------------------
ROUTES: list[FerryRoute] = [
    FerryRoute(
        key="redhook",
        name="Red Hook (STT) - Cruz Bay",
        # Red Hook -> Cruz Bay: hourly on the hour, plus early/late extras.
        toward_st_john=[
            Departure("05:30", _MON_FRI),
            Departure("06:30"),
            Departure("07:30"),
            Departure("08:30"),
            *_hourly(6, 23),
            Departure("23:30"),
        ],
        # Cruz Bay -> Red Hook: hourly on the hour.
        toward_st_thomas=_hourly(6, 23),
    ),
    FerryRoute(
        key="downtown",
        name="Charlotte Amalie (STT) - Cruz Bay",
        toward_st_john=[Departure("10:00"), Departure("15:00"), Departure("17:30")],
        toward_st_thomas=[Departure("08:45"), Departure("11:15"), Departure("15:45")],
    ),
    FerryRoute(
        key="carbarge",
        name="Red Hook - Cruz Bay car barge",
        # Vehicle barge — approximate, roughly hourly across the day.
        toward_st_john=_hourly(6, 18),
        toward_st_thomas=_hourly(6, 18),
    ),
]


def _next(departures: list[Departure], now: datetime) -> datetime | None:
    """Earliest departure at or after ``now`` (searches up to a week ahead)."""
    for offset in range(8):
        day = (now + timedelta(days=offset)).date()
        weekday = day.weekday()
        slots = sorted(d.at for d in departures if d.days is None or weekday in d.days)
        for slot in slots:
            hour, minute = (int(x) for x in slot.split(":"))
            candidate = datetime.combine(day, time(hour, minute), tzinfo=now.tzinfo)
            if candidate >= now:
                return candidate
    return None


def next_departures(now: datetime) -> list[dict[str, object]]:
    """Next sailing in each direction for every route, given local (AST) ``now``."""
    result: list[dict[str, object]] = []
    for route in ROUTES:
        result.append(
            {
                "key": route.key,
                "name": route.name,
                "to_st_john": _next(route.toward_st_john, now),
                "to_st_thomas": _next(route.toward_st_thomas, now),
            }
        )
    return result
