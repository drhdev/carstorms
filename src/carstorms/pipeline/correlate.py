"""Correlate observations into continuous events and build the resulting update.

An observation threads onto the prior event with the same ``event_key``; the
change is classified (new / escalation / de-escalation / all-clear / update) and a
fresh :class:`HazardEvent` state is produced. The notify decision is delegated to
:mod:`carstorms.pipeline.decide`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from carstorms.config import Settings
from carstorms.content.recommendations import recommendation_text
from carstorms.models import (
    AlertLevel,
    ChangeType,
    EventStatus,
    EventUpdate,
    HazardEvent,
    HazardObservation,
)
from carstorms.pipeline.decide import should_notify


@dataclass(slots=True)
class EvaluationResult:
    event: HazardEvent
    update: EventUpdate


def classify_change(obs: HazardObservation, prior: HazardEvent | None) -> ChangeType:
    if prior is None:
        return ChangeType.NEW
    # A source that flips an active event into aftermath (e.g. NWS Cancel) is an
    # all-clear regardless of the headline's residual level.
    if obs.status is EventStatus.AFTERMATH and prior.status is EventStatus.ACTIVE:
        return ChangeType.ALL_CLEAR
    if obs.level > prior.current_level:
        return ChangeType.ESCALATION
    if obs.level < prior.current_level:
        return ChangeType.DEESCALATION
    return ChangeType.UPDATE


def _build_event(
    obs: HazardObservation,
    prior: HazardEvent | None,
    now: datetime,
    change_type: ChangeType,
) -> HazardEvent:
    peak = obs.level if prior is None else AlertLevel(max(int(obs.level), int(prior.peak_level)))
    status = obs.status
    if change_type is ChangeType.ALL_CLEAR:
        status = EventStatus.AFTERMATH
    return HazardEvent(
        id=prior.id if prior else None,
        event_key=obs.event_key,
        hazard_type=obs.hazard_type,
        title=obs.title,
        status=status,
        current_level=obs.level,
        peak_level=peak,
        source=obs.source,
        source_event_id=obs.source_event_id,
        latitude=obs.latitude,
        longitude=obs.longitude,
        distance_km=obs.distance_km,
        affects_st_john=obs.affects_st_john,
        island=obs.island,
        is_active=True,
        summary=obs.headline,
        first_seen=prior.first_seen if prior else now,
        last_updated=now,
        last_message_at=prior.last_message_at if prior else None,
        last_data_hash=obs.data_hash(),
        closed_at=None,
    )


def evaluate(
    obs: HazardObservation,
    prior: HazardEvent | None,
    now: datetime,
    settings: Settings,
) -> EvaluationResult:
    """Thread one observation onto its event and decide whether to notify."""
    change_type = classify_change(obs, prior)
    event = _build_event(obs, prior, now, change_type)
    hash_changed = prior is None or prior.last_data_hash != obs.data_hash()

    notify, change_type = should_notify(
        prior=prior,
        event=event,
        change_type=change_type,
        hash_changed=hash_changed,
        now=now,
        settings=settings,
    )

    update = EventUpdate(
        event_key=obs.event_key,
        level=obs.level,
        previous_level=prior.current_level if prior else None,
        status=event.status,
        change_type=change_type,
        is_new_event=prior is None,
        headline=obs.headline or obs.title,
        body=obs.body,
        recommendation=obs.recommendation
        or recommendation_text(obs.hazard_type, obs.level, change_type),
        distance_km=obs.distance_km,
        eta=obs.eta,
        data_hash=obs.data_hash(),
        image_urls=obs.image_urls,
        should_notify=notify,
        raw_payload=obs.raw,
    )
    if notify:
        event.last_message_at = now
    return EvaluationResult(event=event, update=update)


def evaluate_close(
    prior: HazardEvent,
    now: datetime,
    settings: Settings,
) -> EvaluationResult | None:
    """Close an event that is no longer present in any feed.

    Returns ``None`` while the event is merely quiet (so we do not prematurely
    declare an all-clear); once it is stale it is closed, with an all-clear
    message only for hazards that warranted one.
    """
    last = prior.last_updated or prior.first_seen or now
    age_minutes = (now - last).total_seconds() / 60
    if age_minutes < settings.event_stale_close_minutes:
        return None

    closed = prior.model_copy(
        update={
            "status": EventStatus.CLOSED,
            "current_level": AlertLevel.INFORMATIONAL,
            "is_active": False,
            "closed_at": now,
            "last_updated": now,
        }
    )
    notify, change_type = should_notify(
        prior=prior,
        event=closed,
        change_type=ChangeType.CLOSED,
        hash_changed=True,
        now=now,
        settings=settings,
    )
    if notify:
        closed.last_message_at = now
    update = EventUpdate(
        event_key=prior.event_key,
        level=AlertLevel.INFORMATIONAL,
        previous_level=prior.current_level,
        status=EventStatus.CLOSED,
        change_type=change_type,
        is_new_event=False,
        headline=f"All clear: {prior.title}",
        body=f"The {prior.title} threat has ended for {settings.location_name}.",
        recommendation=recommendation_text(
            prior.hazard_type, prior.peak_level, ChangeType.ALL_CLEAR
        ),
        data_hash="closed",
        should_notify=notify,
    )
    return EvaluationResult(event=closed, update=update)
