"""Tests for Telegram message rendering."""

from __future__ import annotations

from datetime import UTC, datetime

from carstorms.config import Settings
from carstorms.models import (
    AlertLevel,
    ChangeType,
    EventStatus,
    EventUpdate,
    HazardEvent,
    HazardType,
    SourceName,
)
from carstorms.telegram.formatting import fmt_ast, render


def _event() -> HazardEvent:
    return HazardEvent(
        event_key="nhc:al012026",
        hazard_type=HazardType.TROPICAL_CYCLONE,
        title="Hurricane Testy",
        status=EventStatus.ACTIVE,
        current_level=AlertLevel.WARNING,
        peak_level=AlertLevel.WARNING,
        source=SourceName.NHC,
        source_event_id="al012026",
    )


def _update(body: str = "Body text.", change: ChangeType = ChangeType.NEW) -> EventUpdate:
    return EventUpdate(
        event_key="nhc:al012026",
        level=AlertLevel.WARNING,
        previous_level=AlertLevel.WATCH,
        status=EventStatus.ACTIVE,
        change_type=change,
        is_new_event=change is ChangeType.NEW,
        headline="Hurricane Testy — Category 1",
        body=body,
        recommendation="• Finish preparations\n• Follow VITEMA orders",
        distance_km=120.0,
        eta=datetime(2026, 6, 26, 0, 0, tzinfo=UTC),
        image_urls=["https://example/cone.png"],
    )


def test_render_contains_key_sections(settings: Settings) -> None:
    text = render(_update(), _event(), settings)
    assert "WARNING" in text
    assert "🆕 NEW" in text
    assert "What to do" in text
    assert "Follow VITEMA orders" in text
    assert "from St. John, USVI" in text
    assert "AST" in text


def test_render_escalation_badge(settings: Settings) -> None:
    text = render(_update(change=ChangeType.ESCALATION), _event(), settings)
    assert "ESCALATING" in text


def test_render_trims_to_caption_limit(settings: Settings) -> None:
    long_body = "rain " * 1000
    text = render(_update(body=long_body), _event(), settings, max_len=600)
    assert len(text) <= 600
    # Recommendations are preserved even when the description is trimmed.
    assert "What to do" in text
    assert "Follow VITEMA orders" in text


def test_fmt_ast_converts_from_utc() -> None:
    # 00:00 UTC is 20:00 the previous day in AST (UTC-4).
    assert fmt_ast(datetime(2026, 6, 26, 0, 0, tzinfo=UTC)) == "Thu 25 Jun, 20:00 AST"
