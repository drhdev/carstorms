"""Canonical domain model shared across sources, pipeline, storage and delivery.

The flow is:  raw source payload -> :class:`HazardObservation` (one snapshot of a
real-world threat) -> correlated against the stored :class:`HazardEvent` -> an
:class:`EventUpdate` describing what changed -> a Telegram :class:`SentMessage`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceName(StrEnum):
    NWS = "nws"
    NHC = "nhc"
    USGS = "usgs"
    OPENMETEO = "openmeteo"
    WQP = "wqp"  # EPA Water Quality Portal (beach water quality)
    AIRNOW = "airnow"  # EPA AirNow (air quality / Saharan dust)
    AVWX = "aviationweather"  # NWS Aviation Weather (airport METAR/NOTAM)
    WAPA = "wapa"  # Virgin Islands Water & Power Authority (power outages)
    MANUAL = "manual"  # operator-curated overrides (ferry, VITEMA, …)


class Island(StrEnum):
    ST_THOMAS = "st_thomas"
    ST_JOHN = "st_john"
    USVI = "usvi"  # territory-wide / both islands


class HazardType(StrEnum):
    TROPICAL_CYCLONE = "tropical_cyclone"
    SEVERE_THUNDERSTORM = "severe_thunderstorm"
    THUNDERSTORM = "thunderstorm"
    FLASH_FLOOD = "flash_flood"
    FLOOD = "flood"
    MARINE = "marine"
    HIGH_SURF = "high_surf"
    RIP_CURRENT = "rip_current"
    WIND = "wind"
    EARTHQUAKE = "earthquake"
    TSUNAMI = "tsunami"
    HEAT = "heat"
    # --- Public-safety, utility, environmental and travel hazards ---------
    WATER_QUALITY = "water_quality"  # beach bacteria advisories
    AIR_QUALITY = "air_quality"  # AQI / Saharan dust
    SARGASSUM = "sargassum"  # seaweed inundation
    POWER_OUTAGE = "power_outage"  # WAPA electricity
    WATER_OUTAGE = "water_outage"  # WAPA potable water / boil-water
    AIRPORT = "airport"  # STT airport disruptions
    FERRY = "ferry"  # STT<->STJ ferry interruptions
    HEALTH = "health"  # DOH health advisories
    PUBLIC_SAFETY = "public_safety"  # VITEMA / general safety
    OTHER = "other"


class AlertLevel(IntEnum):
    """Unified threat scale across every hazard type."""

    INFORMATIONAL = 0  # awareness only (forecast thunderstorm, distant system)
    ADVISORY = 1  # minor hazard, be aware
    WATCH = 2  # conditions possible — prepare
    WARNING = 3  # conditions expected/occurring — act
    EMERGENCY = 4  # severe, take protective action now / evacuate
    CATASTROPHIC = 5  # extreme, life-threatening

    @property
    def label(self) -> str:
        return _LEVEL_LABELS[self]

    @property
    def emoji(self) -> str:
        return _LEVEL_EMOJI[self]


_LEVEL_LABELS: dict[AlertLevel, str] = {
    AlertLevel.INFORMATIONAL: "Informational",
    AlertLevel.ADVISORY: "Advisory",
    AlertLevel.WATCH: "Watch",
    AlertLevel.WARNING: "Warning",
    AlertLevel.EMERGENCY: "Emergency",
    AlertLevel.CATASTROPHIC: "Catastrophic",
}

_LEVEL_EMOJI: dict[AlertLevel, str] = {
    AlertLevel.INFORMATIONAL: "🔵",
    AlertLevel.ADVISORY: "⚪",
    AlertLevel.WATCH: "🟡",
    AlertLevel.WARNING: "🟠",
    AlertLevel.EMERGENCY: "🔴",
    AlertLevel.CATASTROPHIC: "🟣",
}


class EventStatus(StrEnum):
    """Lifecycle phase of an event, independent of its severity level."""

    MONITORING = "monitoring"  # being watched, not yet a defined threat
    ACTIVE = "active"  # threat ongoing or imminent
    AFTERMATH = "aftermath"  # event passed; impacts/aftershocks still relevant
    CLOSED = "closed"  # no longer relevant


class ChangeType(StrEnum):
    NEW = "new"
    ESCALATION = "escalation"
    DEESCALATION = "deescalation"
    UPDATE = "update"
    ALL_CLEAR = "all_clear"
    HEARTBEAT = "heartbeat"
    CLOSED = "closed"


class HazardObservation(BaseModel):
    """One normalized snapshot of a real-world threat from a single source."""

    model_config = ConfigDict(frozen=False)

    source: SourceName
    source_event_id: str
    hazard_type: HazardType
    level: AlertLevel
    status: EventStatus = EventStatus.ACTIVE
    title: str
    headline: str = ""
    body: str = ""
    instruction: str = ""
    recommendation: str = ""  # source-supplied advice (overrides templates)
    latitude: float | None = None
    longitude: float | None = None
    distance_km: float | None = None
    eta: datetime | None = None
    affects_st_john: bool = True
    island: Island | None = None
    image_urls: list[str] = Field(default_factory=list)
    effective: datetime | None = None
    expires: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def event_key(self) -> str:
        """Stable identifier threading observations into the same event."""
        return f"{self.source.value}:{self.source_event_id}"

    def data_hash(self) -> str:
        """Hash of the salient fields used to detect a *meaningful* change."""
        payload = {
            "level": int(self.level),
            "status": self.status.value,
            "headline": self.headline,
            "lat": round(self.latitude, 2) if self.latitude is not None else None,
            "lon": round(self.longitude, 2) if self.longitude is not None else None,
            "eta": self.eta.isoformat() if self.eta else None,
            "expires": self.expires.isoformat() if self.expires else None,
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class HazardEvent(BaseModel):
    """Persisted event (mirrors the ``carstorm_events`` collection)."""

    id: int | None = None
    event_key: str
    hazard_type: HazardType
    title: str
    status: EventStatus
    current_level: AlertLevel
    peak_level: AlertLevel
    source: SourceName
    source_event_id: str
    latitude: float | None = None
    longitude: float | None = None
    distance_km: float | None = None
    affects_st_john: bool = True
    island: Island | None = None
    is_active: bool = True
    summary: str = ""
    first_seen: datetime | None = None
    last_updated: datetime | None = None
    last_message_at: datetime | None = None
    last_data_hash: str | None = None
    closed_at: datetime | None = None


class EventUpdate(BaseModel):
    """A decision about an event: what changed and whether to notify."""

    event_key: str
    level: AlertLevel
    previous_level: AlertLevel | None
    status: EventStatus
    change_type: ChangeType
    is_new_event: bool
    headline: str
    body: str
    recommendation: str = ""
    distance_km: float | None = None
    eta: datetime | None = None
    data_hash: str = ""
    image_urls: list[str] = Field(default_factory=list)
    should_notify: bool = False
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class SentMessage(BaseModel):
    """Record of a Telegram message that was sent (or attempted)."""

    event_key: str
    channel: str
    telegram_message_id: int | None = None
    level: AlertLevel
    change_type: ChangeType
    text: str
    parse_mode: str = "HTML"
    image_urls: list[str] = Field(default_factory=list)
    recommendation: str = ""
    delivery_status: str = "sent"  # sent | failed | skipped
    error: str | None = None


class Measurement(BaseModel):
    """A single timestamped reading for the ``carstorm_measurements`` archive.

    Captures the raw data behind environmental/utility hazards (beach bacteria
    counts, hourly AQI, outage customer counts, …) as a queryable reference set.
    """

    source: SourceName
    metric: str  # e.g. enterococcus, aqi_pm25, outage_customers
    value: float | None = None
    unit: str = ""
    island: Island | None = None
    station: str = ""
    station_name: str = ""
    latitude: float | None = None
    longitude: float | None = None
    status: str = ""  # ok | advisory | exceedance | …
    sampled_at: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ManualAlert(BaseModel):
    """Operator-curated override (mirrors ``carstorm_manual_alerts``).

    The reliable path for hazards with no machine feed — ferry cancellations,
    WAPA water/boil-water notices, VITEMA/DOH advisories — entered by a trusted
    operator and flowed through the normal pipeline.
    """

    id: int | None = None
    hazard_type: HazardType = HazardType.PUBLIC_SAFETY
    island: Island = Island.USVI
    level: AlertLevel = AlertLevel.ADVISORY
    title: str
    body: str = ""
    recommendation: str = ""
    source_label: str = "VITEMA / local authorities"
    image_url: str = ""
    is_active: bool = True
    expires: datetime | None = None
