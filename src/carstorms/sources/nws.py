"""NWS api.weather.gov — official alerts for St. John, USVI (office SJU).

This is the primary backbone: it carries severe thunderstorm, flash flood, flood,
tropical storm/hurricane watch & warning, high surf, rip current, marine and
tsunami alerts. No API key is required.

Alerts for the same phenomenon and office are threaded into a single event (keyed
by ``office.phenomenon``) so a *watch -> warning -> cancel* lifecycle reads as one
escalating storyline rather than three separate events.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from carstorms.models import AlertLevel, EventStatus, HazardObservation, HazardType, SourceName
from carstorms.sources.base import HazardSource, get_json

ALERTS_URL = "https://api.weather.gov/alerts/active"
# NWS San Juan (TJUA) radar — latest single frame (sendPhoto-friendly, unlike the
# animated _loop.gif) to illustrate active precipitation hazards.
RADAR_IMAGE_URL = "https://radar.weather.gov/ridge/standard/TJUA_0.gif"

# Keyword -> hazard type, longest/most-specific keys checked first.
_HAZARD_KEYWORDS: tuple[tuple[str, HazardType], ...] = (
    ("tsunami", HazardType.TSUNAMI),
    ("hurricane", HazardType.TROPICAL_CYCLONE),
    ("tropical storm", HazardType.TROPICAL_CYCLONE),
    ("tropical depression", HazardType.TROPICAL_CYCLONE),
    ("storm surge", HazardType.TROPICAL_CYCLONE),
    ("flash flood", HazardType.FLASH_FLOOD),
    ("flood", HazardType.FLOOD),
    ("severe thunderstorm", HazardType.SEVERE_THUNDERSTORM),
    ("tornado", HazardType.SEVERE_THUNDERSTORM),
    ("thunderstorm", HazardType.THUNDERSTORM),
    ("special weather", HazardType.THUNDERSTORM),
    ("high surf", HazardType.HIGH_SURF),
    ("rip current", HazardType.RIP_CURRENT),
    ("small craft", HazardType.MARINE),
    ("gale", HazardType.MARINE),
    ("marine", HazardType.MARINE),
    ("high wind", HazardType.WIND),
    ("wind", HazardType.WIND),
    ("heat", HazardType.HEAT),
)

_PRECIP_HAZARDS = {
    HazardType.SEVERE_THUNDERSTORM,
    HazardType.THUNDERSTORM,
    HazardType.FLASH_FLOOD,
    HazardType.FLOOD,
}


def classify_event(event: str) -> HazardType:
    e = event.lower()
    for keyword, hazard in _HAZARD_KEYWORDS:
        if keyword in e:
            return hazard
    return HazardType.OTHER


def level_for(event: str, severity: str, urgency: str) -> AlertLevel:
    e = event.lower()
    if "emergency" in e:
        return (
            AlertLevel.CATASTROPHIC
            if ("flash flood" in e or "tsunami" in e)
            else AlertLevel.EMERGENCY
        )
    if "warning" in e:
        if severity == "Extreme" or "tornado" in e or "tsunami" in e or urgency == "Immediate":
            return AlertLevel.EMERGENCY
        return AlertLevel.WARNING
    if "watch" in e:
        return AlertLevel.WATCH
    if "advisory" in e:
        return AlertLevel.ADVISORY
    if "statement" in e:
        return AlertLevel.INFORMATIONAL
    # Fall back on NWS severity.
    return {
        "Extreme": AlertLevel.EMERGENCY,
        "Severe": AlertLevel.WARNING,
        "Moderate": AlertLevel.ADVISORY,
        "Minor": AlertLevel.ADVISORY,
    }.get(severity, AlertLevel.INFORMATIONAL)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _primary_vtec(props: dict[str, Any]) -> tuple[str, str] | None:
    """Return (office, phenomenon) from the primary VTEC string, if any."""
    vtec_list = props.get("parameters", {}).get("VTEC") or []
    for raw in vtec_list:
        parts = raw.strip("/").split(".")
        if len(parts) >= 4:
            office, phenom = parts[2], parts[3]
            return office, phenom
    return None


class NWSSource(HazardSource):
    name = SourceName.NWS

    async def _fetch(self, client: httpx.AsyncClient) -> list[HazardObservation]:
        params_point = {"point": f"{self.settings.latitude},{self.settings.longitude}"}
        data = await get_json(client, ALERTS_URL, params=params_point)
        features: list[dict[str, Any]] = list(data.get("features", []))

        # Also pull configured land/marine zones so coastal alerts are not missed.
        if self.settings.nws_zones:
            zone_data = await get_json(
                client, ALERTS_URL, params={"zone": ",".join(self.settings.nws_zones)}
            )
            features.extend(zone_data.get("features", []))

        observations: dict[str, HazardObservation] = {}
        for feature in features:
            obs = self._to_observation(feature)
            if obs is None:
                continue
            # Thread by event_key, keeping the most severe / most recent active alert.
            existing = observations.get(obs.event_key)
            if existing is None or obs.level > existing.level:
                observations[obs.event_key] = obs
        return list(observations.values())

    def _to_observation(self, feature: dict[str, Any]) -> HazardObservation | None:
        props: dict[str, Any] = feature.get("properties") or {}
        event = props.get("event")
        if not event:
            return None
        if props.get("status") not in (None, "Actual"):
            return None  # ignore Test/Exercise/Draft

        hazard = classify_event(event)
        severity = props.get("severity", "Unknown")
        urgency = props.get("urgency", "Unknown")
        level = level_for(event, severity, urgency)

        vtec = _primary_vtec(props)
        if vtec is not None:
            office, phenom = vtec
            source_event_id = f"{office}.{phenom}"
        else:
            # No VTEC (e.g. Special Weather Statement): key by office + hazard.
            source_event_id = f"{self.settings.nws_office}.{hazard.value}"

        message_type = props.get("messageType", "Alert")
        status = EventStatus.ACTIVE
        if message_type == "Cancel":
            status = EventStatus.AFTERMATH

        onset = _parse_dt(props.get("onset")) or _parse_dt(props.get("effective"))
        now = datetime.now(UTC)
        eta = onset if (onset and onset > now) else None

        images = [RADAR_IMAGE_URL] if hazard in _PRECIP_HAZARDS else []

        return HazardObservation(
            source=SourceName.NWS,
            source_event_id=source_event_id,
            hazard_type=hazard,
            level=level,
            status=status,
            title=event,
            headline=props.get("headline") or event,
            body=(props.get("description") or "").strip(),
            instruction=(props.get("instruction") or "").strip(),
            latitude=self.settings.latitude,
            longitude=self.settings.longitude,
            affects_st_john=True,
            eta=eta,
            effective=_parse_dt(props.get("effective")),
            expires=_parse_dt(props.get("expires")) or _parse_dt(props.get("ends")),
            image_urls=images,
            raw={
                "id": props.get("id"),
                "event": event,
                "severity": severity,
                "urgency": urgency,
                "certainty": props.get("certainty"),
                "messageType": message_type,
                "areaDesc": props.get("areaDesc"),
                "senderName": props.get("senderName"),
            },
        )
