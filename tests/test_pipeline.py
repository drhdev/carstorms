"""Tests for event correlation (threading) and the messaging policy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from carstorms.config import Settings
from carstorms.models import (
    AlertLevel,
    ChangeType,
    EventStatus,
    HazardEvent,
    HazardObservation,
    HazardType,
    SourceName,
)
from carstorms.pipeline import evaluate, evaluate_close

NOW = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)


def make_obs(
    level: AlertLevel,
    *,
    hazard: HazardType = HazardType.TROPICAL_CYCLONE,
    status: EventStatus = EventStatus.ACTIVE,
    sid: str = "x",
    headline: str = "headline",
) -> HazardObservation:
    return HazardObservation(
        source=SourceName.NHC,
        source_event_id=sid,
        hazard_type=hazard,
        level=level,
        status=status,
        title="title",
        headline=headline,
        latitude=18.0,
        longitude=-65.0,
    )


def make_prior(
    obs: HazardObservation,
    *,
    current: AlertLevel,
    peak: AlertLevel | None = None,
    last_message_at: datetime | None = NOW,
    matching_hash: bool = True,
    status: EventStatus = EventStatus.ACTIVE,
    last_updated: datetime = NOW,
) -> HazardEvent:
    return HazardEvent(
        id=1,
        event_key=obs.event_key,
        hazard_type=obs.hazard_type,
        title=obs.title,
        status=status,
        current_level=current,
        peak_level=peak or current,
        source=obs.source,
        source_event_id=obs.source_event_id,
        first_seen=NOW - timedelta(hours=6),
        last_updated=last_updated,
        last_message_at=last_message_at,
        last_data_hash=obs.data_hash() if matching_hash else "different",
    )


def test_new_event_always_notifies(settings: Settings) -> None:
    result = evaluate(make_obs(AlertLevel.ADVISORY), None, NOW, settings)
    assert result.update.change_type is ChangeType.NEW
    assert result.update.is_new_event is True
    assert result.update.should_notify is True


def test_escalation_always_notifies(settings: Settings) -> None:
    obs = make_obs(AlertLevel.WARNING)
    prior = make_prior(obs, current=AlertLevel.WATCH, last_message_at=NOW)
    result = evaluate(obs, prior, NOW, settings)
    assert result.update.change_type is ChangeType.ESCALATION
    assert result.update.should_notify is True
    assert result.event.peak_level is AlertLevel.WARNING


def test_unchanged_event_is_suppressed(settings: Settings) -> None:
    obs = make_obs(AlertLevel.WARNING)
    prior = make_prior(obs, current=AlertLevel.WARNING, last_message_at=NOW)
    result = evaluate(obs, prior, NOW, settings)
    assert result.update.change_type is ChangeType.UPDATE
    assert result.update.should_notify is False


def test_heartbeat_due_for_active_warning(settings: Settings) -> None:
    obs = make_obs(AlertLevel.WARNING)
    old = NOW - timedelta(minutes=settings.heartbeat_warning_minutes + 5)
    prior = make_prior(obs, current=AlertLevel.WARNING, last_message_at=old)
    result = evaluate(obs, prior, NOW, settings)
    assert result.update.change_type is ChangeType.HEARTBEAT
    assert result.update.should_notify is True


def test_earthquake_does_not_heartbeat(settings: Settings) -> None:
    obs = make_obs(AlertLevel.WARNING, hazard=HazardType.EARTHQUAKE)
    old = NOW - timedelta(hours=6)
    prior = make_prior(obs, current=AlertLevel.WARNING, last_message_at=old)
    result = evaluate(obs, prior, NOW, settings)
    assert result.update.change_type is ChangeType.UPDATE
    assert result.update.should_notify is False


def test_harmless_thunderstorm_only_announced_once(settings: Settings) -> None:
    obs = make_obs(AlertLevel.INFORMATIONAL, hazard=HazardType.THUNDERSTORM, sid="thunderstorm")
    first = evaluate(obs, None, NOW, settings)
    assert first.update.should_notify is True
    prior = make_prior(obs, current=AlertLevel.INFORMATIONAL, last_message_at=NOW)
    second = evaluate(obs, prior, NOW, settings)
    assert second.update.should_notify is False


def test_cancel_is_all_clear(settings: Settings) -> None:
    obs = make_obs(AlertLevel.WARNING, hazard=HazardType.FLASH_FLOOD, status=EventStatus.AFTERMATH)
    prior = make_prior(
        obs, current=AlertLevel.WARNING, peak=AlertLevel.WARNING, last_message_at=NOW
    )
    result = evaluate(obs, prior, NOW, settings)
    assert result.update.change_type is ChangeType.ALL_CLEAR
    assert result.update.should_notify is True


def test_evaluate_close_only_when_stale(settings: Settings) -> None:
    obs = make_obs(AlertLevel.WARNING, hazard=HazardType.FLOOD)
    fresh = make_prior(obs, current=AlertLevel.WARNING, peak=AlertLevel.WARNING, last_updated=NOW)
    assert evaluate_close(fresh, NOW, settings) is None

    stale_time = NOW - timedelta(minutes=settings.event_stale_close_minutes + 10)
    stale = make_prior(
        obs,
        current=AlertLevel.WARNING,
        peak=AlertLevel.WARNING,
        last_updated=stale_time,
    )
    result = evaluate_close(stale, NOW, settings)
    assert result is not None
    assert result.event.is_active is False
    assert result.update.change_type is ChangeType.CLOSED
    assert result.update.should_notify is True
