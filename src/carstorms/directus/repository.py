"""Typed read/write helpers mapping domain models onto ``carstorm_*`` records."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from carstorms.directus.client import DirectusClient
from carstorms.models import EventUpdate, HazardEvent, ManualAlert, Measurement, SentMessage
from carstorms.sources.base import SourceResult


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _now() -> datetime:
    return datetime.now(UTC)


def _canon_ts(value: datetime | str | None) -> str:
    """Normalize a timestamp (datetime or stored string) to minute-precision UTC,
    so dedup keys match regardless of how Directus echoes the timestamp back."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return str(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M")


def _measurement_key(
    source: str, metric: str, station: str, sampled_at: datetime | str | None
) -> str:
    return f"{source}:{metric}:{station}:{_canon_ts(sampled_at)}"


class DirectusRepository:
    """High-level access to the hazard archive."""

    def __init__(self, client: DirectusClient, prefix: str) -> None:
        self.client = client
        self.events = f"{prefix}events"
        self.updates = f"{prefix}event_updates"
        self.messages = f"{prefix}messages"
        self.runs = f"{prefix}source_runs"
        self.measurements = f"{prefix}measurements"
        self.manual_alerts = f"{prefix}manual_alerts"

    async def get_active_events(self) -> dict[str, HazardEvent]:
        items = await self.client.get_items(
            self.events,
            params={"filter[is_active][_eq]": "true", "limit": 500},
        )
        return {item["event_key"]: HazardEvent.model_validate(item) for item in items}

    async def upsert_event(self, event: HazardEvent) -> HazardEvent:
        record = self._event_record(event)
        if event.id is None:
            created = await self.client.create_item(self.events, record)
            event.id = created.get("id")
        else:
            await self.client.update_item(self.events, event.id, record)
        return event

    async def insert_update(
        self, event_id: int | None, update: EventUpdate, now: datetime | None = None
    ) -> int | None:
        now = now or _now()
        record = {
            "event": event_id,
            "event_key": update.event_key,
            "level": int(update.level),
            "previous_level": int(update.previous_level)
            if update.previous_level is not None
            else None,
            "status": update.status.value,
            "change_type": update.change_type.value,
            "is_new_event": update.is_new_event,
            "headline": update.headline,
            "body": update.body,
            "recommendation": update.recommendation,
            "distance_km": update.distance_km,
            "eta": _iso(update.eta),
            "data_hash": update.data_hash,
            "raw_payload": update.raw_payload,
            "created_at": _iso(now),
        }
        created = await self.client.create_item(self.updates, record)
        return created.get("id")

    async def insert_message(
        self,
        event_id: int | None,
        update_id: int | None,
        message: SentMessage,
        now: datetime | None = None,
    ) -> int | None:
        now = now or _now()
        record = {
            "event": event_id,
            "event_update": update_id,
            "event_key": message.event_key,
            "channel": message.channel,
            "telegram_message_id": message.telegram_message_id,
            "level": int(message.level),
            "change_type": message.change_type.value,
            "text": message.text,
            "parse_mode": message.parse_mode,
            "image_urls": message.image_urls,
            "recommendation": message.recommendation,
            "delivery_status": message.delivery_status,
            "error": message.error,
            "sent_at": _iso(now),
        }
        created = await self.client.create_item(self.messages, record)
        return created.get("id")

    async def get_manual_alerts(self) -> list[ManualAlert]:
        """Active operator-curated overrides."""
        items = await self.client.get_items(
            self.manual_alerts,
            params={"filter[is_active][_eq]": "true", "limit": 200},
        )
        return [ManualAlert.model_validate(item) for item in items]

    async def archive_measurements(
        self, measurements: list[Measurement], now: datetime | None = None
    ) -> int:
        """Store new timestamped readings, skipping ones already archived.

        Deduplicates on (source, metric, station, sampled_at) so polling more
        often than the data changes does not bloat the archive."""
        if not measurements:
            return 0
        now = now or _now()
        sources = {m.source.value for m in measurements}
        oldest = min((m.sampled_at for m in measurements if m.sampled_at), default=None)
        existing = await self._existing_measurement_keys(sources, oldest)

        inserted = 0
        for m in measurements:
            key = _measurement_key(m.source.value, m.metric, m.station, m.sampled_at)
            if key in existing:
                continue
            await self.client.create_item(
                self.measurements,
                {
                    "source": m.source.value,
                    "metric": m.metric,
                    "value": m.value,
                    "unit": m.unit,
                    "island": m.island.value if m.island else None,
                    "station": m.station,
                    "station_name": m.station_name,
                    "latitude": m.latitude,
                    "longitude": m.longitude,
                    "status": m.status,
                    "sampled_at": _iso(m.sampled_at),
                    "raw": m.raw,
                    "created_at": _iso(now),
                },
            )
            existing.add(key)
            inserted += 1
        return inserted

    async def _existing_measurement_keys(
        self, sources: set[str], since: datetime | None
    ) -> set[str]:
        params: dict[str, object] = {
            "fields": "source,metric,station,sampled_at",
            "limit": 2000,
            "filter[source][_in]": ",".join(sorted(sources)),
        }
        if since is not None:
            params["filter[sampled_at][_gte]"] = _iso(since - timedelta(days=1))
        rows = await self.client.get_items(self.measurements, params=params)
        return {
            _measurement_key(
                str(row.get("source")),
                str(row.get("metric")),
                str(row.get("station")),
                row.get("sampled_at"),
            )
            for row in rows
        }

    async def insert_source_run(self, result: SourceResult, now: datetime | None = None) -> None:
        now = now or _now()
        await self.client.create_item(
            self.runs,
            {
                "source": result.source.value,
                "status": result.status,
                "http_status": result.http_status,
                "observations_count": len(result.observations),
                "duration_ms": result.duration_ms,
                "error": result.error,
                "fetched_at": _iso(now),
            },
        )

    @staticmethod
    def _event_record(event: HazardEvent) -> dict[str, object]:
        return {
            "event_key": event.event_key,
            "hazard_type": event.hazard_type.value,
            "title": event.title,
            "status": event.status.value,
            "current_level": int(event.current_level),
            "peak_level": int(event.peak_level),
            "source": event.source.value,
            "source_event_id": event.source_event_id,
            "latitude": event.latitude,
            "longitude": event.longitude,
            "distance_km": event.distance_km,
            "affects_st_john": event.affects_st_john,
            "island": event.island.value if event.island else None,
            "is_active": event.is_active,
            "summary": event.summary,
            "first_seen": _iso(event.first_seen),
            "last_updated": _iso(event.last_updated),
            "last_message_at": _iso(event.last_message_at),
            "last_data_hash": event.last_data_hash,
            "closed_at": _iso(event.closed_at),
        }
