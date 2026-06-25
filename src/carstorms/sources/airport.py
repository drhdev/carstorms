"""STT (Cyril E. King) airport status from NWS Aviation Weather + optional FAA NOTAM.

METAR flight category is a free, keyless proxy for operating conditions; when FAA
NOTAM credentials are configured, an active aerodrome-closure NOTAM escalates to a
closure warning. An alert is raised only when conditions are degraded (IFR/LIFR) or
the field is closed — normal VFR operations stay silent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from carstorms.content.levels import airport_level
from carstorms.models import AlertLevel, HazardObservation, HazardType, Island, SourceName
from carstorms.sources.base import HazardSource, get_json

METAR_URL = "https://aviationweather.gov/api/data/metar"
NOTAM_URL = "https://external-api.faa.gov/notamapi/v1/notams"
_CLOSURE_PHRASES = ("AERODROME CLOSED", "AD CLSD", "AIRPORT CLOSED", "AD CLOSED")


class AirportStatusSource(HazardSource):
    name = SourceName.AVWX
    min_interval_seconds = 1800  # METAR updates roughly hourly

    async def _fetch(self, client: httpx.AsyncClient) -> list[HazardObservation]:
        icao = self.settings.airport_icao
        metars = await get_json(client, METAR_URL, params={"ids": icao, "format": "json"})
        metar: dict[str, Any] = metars[0] if isinstance(metars, list) and metars else {}

        flight_category = str(metar.get("fltCat", "") or "")
        closed = await self._is_closed(client) if self.settings.faa_notam_enabled else False
        level = airport_level(flight_category, closed=closed)
        if level < AlertLevel.ADVISORY and not closed:
            return []  # normal operations — no alert

        raw_ob = metar.get("rawOb", "")
        wind = metar.get("wspd")
        visibility = metar.get("visib")
        obs_time = metar.get("obsTime")
        effective = (
            datetime.fromtimestamp(obs_time, tz=UTC) if isinstance(obs_time, (int, float)) else None
        )

        if closed:
            headline = f"{self.settings.airport_name} — CLOSED"
            body = "An active NOTAM indicates the airport is closed. Do not travel to STT until your flight is confirmed."
        else:
            headline = f"{self.settings.airport_name} — {flight_category or 'reduced'} conditions"
            body = (
                f"Flight category {flight_category or 'unknown'} at STT; "
                f"wind {wind} kt, visibility {visibility} sm. Delays are possible. "
                f"METAR: {raw_ob}"
            )

        return [
            HazardObservation(
                source=SourceName.AVWX,
                source_event_id=icao,
                hazard_type=HazardType.AIRPORT,
                level=level,
                title=self.settings.airport_name,
                headline=headline,
                body=body,
                latitude=metar.get("lat"),
                longitude=metar.get("lon"),
                island=Island.ST_THOMAS,
                effective=effective,
                raw={"fltCat": flight_category, "closed": closed, "rawOb": raw_ob},
            )
        ]

    async def _is_closed(self, client: httpx.AsyncClient) -> bool:
        """Best-effort: detect an active aerodrome-closure NOTAM for STT."""
        try:
            data = await get_json(
                client,
                NOTAM_URL,
                params={"icaoLocation": self.settings.airport_icao, "responseFormat": "geoJson"},
                headers={
                    "client_id": self.settings.faa_client_id,
                    "client_secret": self.settings.faa_client_secret,
                },
            )
        except Exception:  # NOTAM is optional; never fail the airport check on it.
            return False
        blob = str(data).upper()
        return any(phrase in blob for phrase in _CLOSURE_PHRASES)
