"""Messaging policy — timely when it matters, quiet when it doesn't.

The goal is the perspective of someone on St. John: tell me fast when a threat
appears or worsens, keep me posted while it is dangerous, and don't bury me in
noise over a passing afternoon shower.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from carstorms.config import Settings
from carstorms.models import AlertLevel, ChangeType, HazardEvent, HazardType

# Hazards with an ongoing/forecast nature get heartbeats and all-clears. A
# point-in-time earthquake does not need repeating once announced.
ONGOING_TYPES: frozenset[HazardType] = frozenset(
    {
        HazardType.TROPICAL_CYCLONE,
        HazardType.SEVERE_THUNDERSTORM,
        HazardType.THUNDERSTORM,
        HazardType.FLASH_FLOOD,
        HazardType.FLOOD,
        HazardType.MARINE,
        HazardType.HIGH_SURF,
        HazardType.RIP_CURRENT,
        HazardType.WIND,
        HazardType.HEAT,
    }
)


def _interval_ok(last_message_at: datetime | None, now: datetime, settings: Settings) -> bool:
    if last_message_at is None:
        return True
    return now - last_message_at >= timedelta(minutes=settings.min_message_interval_minutes)


def _heartbeat_due(
    event: HazardEvent, last_message_at: datetime | None, now: datetime, settings: Settings
) -> bool:
    if event.hazard_type not in ONGOING_TYPES:
        return False
    if event.current_level >= AlertLevel.WARNING:
        cadence = settings.heartbeat_warning_minutes
    elif event.current_level == AlertLevel.WATCH:
        cadence = settings.heartbeat_watch_minutes
    else:
        return False
    if last_message_at is None:
        return True
    return now - last_message_at >= timedelta(minutes=cadence)


def should_notify(
    *,
    prior: HazardEvent | None,
    event: HazardEvent,
    change_type: ChangeType,
    hash_changed: bool,
    now: datetime,
    settings: Settings,
) -> tuple[bool, ChangeType]:
    """Decide whether to send, and finalise the change type (UPDATE may become
    HEARTBEAT). Returns ``(should_notify, change_type)``."""
    last_message_at = prior.last_message_at if prior else None

    # A brand-new event always announces itself (sources already filter out
    # irrelevant low-level noise such as distant storms or sub-threshold quakes).
    if change_type is ChangeType.NEW:
        return True, ChangeType.NEW

    # Escalation is the most important signal — never throttle it.
    if change_type is ChangeType.ESCALATION:
        return True, ChangeType.ESCALATION

    if change_type in (ChangeType.ALL_CLEAR, ChangeType.CLOSED):
        notify = event.peak_level >= AlertLevel.WARNING and event.hazard_type in ONGOING_TYPES
        return notify, change_type

    if change_type is ChangeType.DEESCALATION:
        significant = prior is not None and prior.current_level >= AlertLevel.WARNING
        return (significant and _interval_ok(last_message_at, now, settings)), change_type

    # change_type is UPDATE (same level as before).
    if hash_changed and _interval_ok(last_message_at, now, settings):
        return True, ChangeType.UPDATE
    if _heartbeat_due(event, last_message_at, now, settings):
        return True, ChangeType.HEARTBEAT
    return False, ChangeType.UPDATE
