"""Declarative ``carstorm_*`` collection schema, created idempotently via the API.

On startup we ensure every collection and field exists. The store is designed as a
durable reference archive for all hazards — from a passing thunderstorm to a major
hurricane — with a strict 1 event -> N updates -> N messages relationship.
"""

from __future__ import annotations

from typing import Any

from carstorms.directus.client import DirectusClient
from carstorms.logging import get_logger

log = get_logger(__name__)

_PK_FIELD: dict[str, Any] = {
    "field": "id",
    "type": "integer",
    "meta": {"hidden": True, "interface": "input", "readonly": True},
    "schema": {"is_primary_key": True, "has_auto_increment": True},
}


def _f(field: str, ftype: str, **schema: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {"field": field, "type": ftype, "meta": {}, "schema": {}}
    if schema:
        spec["schema"].update(schema)
    return spec


def build_schema(prefix: str) -> list[dict[str, Any]]:
    """Return the ordered collection specs (parents before children)."""
    events = f"{prefix}events"
    updates = f"{prefix}event_updates"
    messages = f"{prefix}messages"
    runs = f"{prefix}source_runs"
    measurements = f"{prefix}measurements"
    manual_alerts = f"{prefix}manual_alerts"
    notices = f"{prefix}notices"

    return [
        {
            "collection": events,
            "meta": {"icon": "warning", "note": "One row per real-world hazard event."},
            "fields": [
                _f("event_key", "string", is_unique=True),
                _f("hazard_type", "string"),
                _f("title", "string"),
                _f("status", "string"),
                _f("current_level", "integer"),
                _f("peak_level", "integer"),
                _f("source", "string"),
                _f("source_event_id", "string"),
                _f("latitude", "float"),
                _f("longitude", "float"),
                _f("distance_km", "float"),
                _f("affects_st_john", "boolean"),
                _f("island", "string"),
                _f("is_active", "boolean"),
                _f("summary", "text"),
                _f("first_seen", "timestamp"),
                _f("last_updated", "timestamp"),
                _f("last_message_at", "timestamp"),
                _f("last_data_hash", "string"),
                _f("closed_at", "timestamp"),
                _f("metadata", "json"),
            ],
            "relations": [],
        },
        {
            "collection": updates,
            "meta": {"icon": "history", "note": "Every evaluation/state change for an event."},
            "fields": [
                _f("event", "integer"),
                _f("event_key", "string"),
                _f("level", "integer"),
                _f("previous_level", "integer"),
                _f("status", "string"),
                _f("change_type", "string"),
                _f("is_new_event", "boolean"),
                _f("headline", "text"),
                _f("body", "text"),
                _f("recommendation", "text"),
                _f("distance_km", "float"),
                _f("eta", "timestamp"),
                _f("data_hash", "string"),
                _f("raw_payload", "json"),
                _f("created_at", "timestamp"),
            ],
            "relations": [{"field": "event", "related_collection": events}],
        },
        {
            "collection": messages,
            "meta": {"icon": "send", "note": "Every Telegram message sent (or attempted)."},
            "fields": [
                _f("event", "integer"),
                _f("event_update", "integer"),
                _f("event_key", "string"),
                _f("channel", "string"),
                _f("telegram_message_id", "bigInteger"),
                _f("level", "integer"),
                _f("change_type", "string"),
                _f("text", "text"),
                _f("parse_mode", "string"),
                _f("image_urls", "json"),
                _f("recommendation", "text"),
                _f("delivery_status", "string"),
                _f("error", "text"),
                _f("sent_at", "timestamp"),
            ],
            "relations": [
                {"field": "event", "related_collection": events},
                {"field": "event_update", "related_collection": updates},
            ],
        },
        {
            "collection": runs,
            "meta": {"icon": "monitoring", "note": "Per-source poll telemetry for reliability."},
            "fields": [
                _f("source", "string"),
                _f("status", "string"),
                _f("http_status", "integer"),
                _f("observations_count", "integer"),
                _f("duration_ms", "integer"),
                _f("error", "text"),
                _f("fetched_at", "timestamp"),
            ],
            "relations": [],
        },
        {
            "collection": measurements,
            "meta": {
                "icon": "science",
                "note": "Timestamped readings (beach bacteria, AQI, outages, …).",
            },
            "fields": [
                _f("source", "string"),
                _f("metric", "string"),
                _f("value", "float"),
                _f("unit", "string"),
                _f("island", "string"),
                _f("station", "string"),
                _f("station_name", "string"),
                _f("latitude", "float"),
                _f("longitude", "float"),
                _f("status", "string"),
                _f("sampled_at", "timestamp"),
                _f("raw", "json"),
                _f("created_at", "timestamp"),
            ],
            "relations": [],
        },
        {
            "collection": manual_alerts,
            "meta": {
                "icon": "campaign",
                "note": "Operator-curated overrides (ferry, WAPA, VITEMA/DOH, …).",
            },
            "fields": [
                _f("hazard_type", "string"),
                _f("island", "string"),
                _f("level", "integer"),
                _f("title", "string"),
                _f("body", "text"),
                _f("recommendation", "text"),
                _f("source_label", "string"),
                _f("image_url", "string"),
                _f("is_active", "boolean"),
                _f("expires", "timestamp"),
                _f("created_at", "timestamp"),
            ],
            "relations": [],
        },
        {
            "collection": notices,
            "meta": {
                "icon": "event",
                "note": "Curated island events / notices for the dashboard.",
            },
            "fields": [
                _f("title", "string"),
                _f("body", "text"),
                _f("category", "string"),  # event | notice
                _f("location", "string"),
                _f("url", "string"),
                _f("starts_at", "timestamp"),
                _f("ends_at", "timestamp"),
                _f("is_active", "boolean"),
            ],
            "relations": [],
        },
    ]


async def ensure_schema(client: DirectusClient, prefix: str) -> None:
    """Create any missing collections, fields and relations. Safe to re-run."""
    for spec in build_schema(prefix):
        collection = spec["collection"]
        if not await client.collection_exists(collection):
            await client.create_collection(
                {
                    "collection": collection,
                    "meta": spec["meta"],
                    "schema": {},
                    "fields": [_PK_FIELD],
                }
            )
            log.info("directus.collection_created", collection=collection)

        created_fields: set[str] = set()
        for field_spec in spec["fields"]:
            if not await client.field_exists(collection, field_spec["field"]):
                await client.create_field(collection, field_spec)
                created_fields.add(field_spec["field"])
                log.info("directus.field_created", collection=collection, field=field_spec["field"])

        # Only register a relation for a foreign-key field we just created, so
        # re-running never produces duplicate relations.
        for relation in spec["relations"]:
            if relation["field"] in created_fields:
                await client.create_relation(
                    {
                        "collection": collection,
                        "field": relation["field"],
                        "related_collection": relation["related_collection"],
                    }
                )
