"""Operator-curated overrides — the reliable path for no-API hazards.

Reads active rows from ``carstorm_manual_alerts`` in Directus (ferry cancellations,
WAPA water/boil-water notices, VITEMA/DOH advisories, anything ad-hoc) and flows
them through the normal pipeline so they are threaded, archived and broadcast like
any other event. Only built when Directus is configured.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from carstorms.logging import get_logger
from carstorms.models import AlertLevel, HazardObservation, HazardType, Island, SourceName
from carstorms.sources.base import HazardSource, get_json

log = get_logger(__name__)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class ManualAlertSource(HazardSource):
    name = SourceName.MANUAL

    async def _fetch(self, client: httpx.AsyncClient) -> list[HazardObservation]:
        base = self.settings.directus_url.rstrip("/")
        prefix = self.settings.directus_collection_prefix
        rows = await get_json(
            client,
            f"{base}/items/{prefix}manual_alerts",
            params={"filter[is_active][_eq]": "true", "limit": 200},
            headers={"Authorization": f"Bearer {self.settings.directus_token}"},
        )
        items = rows.get("data", []) if isinstance(rows, dict) else []
        now = datetime.now(UTC)
        observations: list[HazardObservation] = []
        for item in items:
            obs = self._to_observation(item, now)
            if obs is not None:
                observations.append(obs)
        return observations

    def _to_observation(self, item: dict[str, Any], now: datetime) -> HazardObservation | None:
        alert_id = item.get("id")
        title = item.get("title")
        if alert_id is None or not title:
            return None
        expires = _parse_dt(item.get("expires"))
        if expires is not None and expires < now:
            return None

        try:
            hazard = HazardType(str(item.get("hazard_type", "public_safety")))
        except ValueError:
            hazard = HazardType.PUBLIC_SAFETY
        try:
            island = Island(str(item.get("island", "usvi")))
        except ValueError:
            island = Island.USVI
        level = AlertLevel(int(item.get("level", AlertLevel.ADVISORY)))

        image_url = str(item.get("image_url") or "")
        source_label = str(item.get("source_label") or "VITEMA / local authorities")
        return HazardObservation(
            source=SourceName.MANUAL,
            source_event_id=str(alert_id),
            hazard_type=hazard,
            level=level,
            title=str(title),
            headline=str(title),
            body=str(item.get("body") or ""),
            recommendation=str(item.get("recommendation") or ""),
            island=island,
            affects_st_john=island in (Island.ST_JOHN, Island.USVI),
            expires=expires,
            image_urls=[image_url] if image_url else [],
            raw={"manual_alert_id": alert_id, "source_label": source_label},
        )
