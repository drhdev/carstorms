"""Tests for the deterministic recommendation templates."""

from __future__ import annotations

import pytest

from carstorms.content.recommendations import recommend, recommendation_text
from carstorms.models import AlertLevel, ChangeType, HazardType


@pytest.mark.parametrize("hazard", list(HazardType))
@pytest.mark.parametrize("level", list(AlertLevel))
def test_every_hazard_and_level_has_advice(hazard: HazardType, level: AlertLevel) -> None:
    bullets = recommend(hazard, level)
    assert bullets, f"no advice for {hazard} at {level}"
    assert all(isinstance(b, str) and b for b in bullets)


def test_all_clear_overrides_with_residual_hazard_note() -> None:
    bullets = recommend(HazardType.FLOOD, AlertLevel.WARNING, ChangeType.ALL_CLEAR)
    assert any("passed" in b or "cancelled" in b for b in bullets)


def test_recommendation_text_is_bulleted() -> None:
    text = recommendation_text(HazardType.TROPICAL_CYCLONE, AlertLevel.WARNING)
    assert text.startswith("•")
    assert "\n" in text


def test_warning_includes_official_channel_pointer() -> None:
    text = recommendation_text(HazardType.TROPICAL_CYCLONE, AlertLevel.WARNING)
    assert "VITEMA" in text
