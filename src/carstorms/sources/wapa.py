"""WAPA (Virgin Islands Water & Power Authority) power outages.

Reads the outage-viewer's undocumented static JSON (the same files the public map
loads) — no key required. Outages are classified by island from their coordinates;
St. John outages at or above ``wapa_alert_min_customers`` raise an alert, and both
St. John and St. Thomas customer-out totals are archived to ``carstorm_measurements``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import httpx

from carstorms.content.levels import power_outage_level
from carstorms.geo import usvi_island
from carstorms.models import (
    HazardObservation,
    HazardType,
    Island,
    Measurement,
    SourceName,
)
from carstorms.sources.base import HazardSource, get_json

OUTAGES_PATH = "/data/outages.json"
SUMMARY_PATH = "/data/outageSummary.json"


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = re.sub(r"(\.\d{6})\d+", r"\1", str(value))  # trim over-long fractions
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


class _IslandTally:
    __slots__ = ("areas", "count", "crew", "out")

    def __init__(self) -> None:
        self.out = 0
        self.count = 0
        self.areas: set[str] = set()
        self.crew = False


class WAPAOutageSource(HazardSource):
    name = SourceName.WAPA
    min_interval_seconds = 600  # WAPA refreshes roughly every few minutes

    async def _fetch(self, client: httpx.AsyncClient) -> list[HazardObservation]:
        base = self.settings.wapa_outage_base.rstrip("/")
        outages = await get_json(client, f"{base}{OUTAGES_PATH}")
        summary: dict[str, Any] = {}
        try:
            summary = await get_json(client, f"{base}{SUMMARY_PATH}")
        except Exception:  # summary is optional context
            summary = {}
        sampled_at = _parse_dt(summary.get("updateTime")) or datetime.now(UTC)

        tallies: dict[Island, _IslandTally] = {
            Island.ST_THOMAS: _IslandTally(),
            Island.ST_JOHN: _IslandTally(),
        }
        for outage in outages or []:
            point = outage.get("outagePoint") or {}
            lat, lng = point.get("lat"), point.get("lng")
            if lat is None or lng is None:
                continue
            island = usvi_island(float(lat), float(lng))
            if island not in tallies:  # skip St. Croix / unclassified
                continue
            tally = tallies[island]
            tally.out += int(outage.get("customersOutNow") or 0)
            tally.count += 1
            for street in (outage.get("streetsAffected") or [])[:3]:
                tally.areas.add(str(street).title())
            if outage.get("crewAssigned"):
                tally.crew = True

        self.last_measurements = [
            Measurement(
                source=SourceName.WAPA,
                metric="outage_customers",
                value=float(tally.out),
                unit="customers",
                island=island,
                status="outage" if tally.out > 0 else "ok",
                sampled_at=sampled_at,
                raw={"outage_count": tally.count, "crew_assigned": tally.crew},
            )
            for island, tally in tallies.items()
        ]

        # Alert only for St. John (this is a St. John channel); St. Thomas totals
        # are archived and shown on the dashboard.
        sj = tallies[Island.ST_JOHN]
        if sj.out < self.settings.wapa_alert_min_customers:
            return []

        areas = ", ".join(sorted(sj.areas)[:5])
        body_parts = [
            f"{sj.out} customers without power across {sj.count} outage(s) on St. John.",
        ]
        if areas:
            body_parts.append(f"Areas affected: {areas}.")
        body_parts.append("Crews assigned." if sj.crew else "No crews assigned yet.")
        if isinstance(summary.get("customersOutNow"), int):
            body_parts.append(f"Territory-wide: {summary['customersOutNow']} customers out.")

        return [
            HazardObservation(
                source=SourceName.WAPA,
                source_event_id="power:st_john",
                hazard_type=HazardType.POWER_OUTAGE,
                level=power_outage_level(sj.out),
                title="Power outage - St. John",
                headline=f"WAPA power outage: {sj.out} customers out on St. John",
                body=" ".join(body_parts),
                latitude=self.settings.latitude,
                longitude=self.settings.longitude,
                island=Island.ST_JOHN,
                affects_st_john=True,
                effective=sampled_at,
                raw={"customers_out": sj.out, "outage_count": sj.count},
            )
        ]
