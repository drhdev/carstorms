"""Tests for Telegram delivery, including photo->text fallback (mocked HTTP)."""

from __future__ import annotations

import httpx
import respx

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
from carstorms.telegram import TelegramClient

PHOTO = r".+/sendPhoto$"
MESSAGE = r".+/sendMessage$"


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


def _update() -> EventUpdate:
    return EventUpdate(
        event_key="nhc:al012026",
        level=AlertLevel.WARNING,
        previous_level=AlertLevel.WATCH,
        status=EventStatus.ACTIVE,
        change_type=ChangeType.NEW,
        is_new_event=True,
        headline="Hurricane Testy",
        body="A hurricane is approaching.",
        recommendation="• Prepare now",
        image_urls=["https://example/cone.png"],
        should_notify=True,
    )


async def test_deliver_with_photo_success(live_settings: Settings) -> None:
    with respx.mock:
        respx.post(url__regex=PHOTO).mock(
            return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 11}})
        )
        async with TelegramClient(live_settings) as tg:
            message = await tg.deliver(_update(), _event())
    assert message.delivery_status == "sent"
    assert message.telegram_message_id == 11
    assert message.image_urls == ["https://example/cone.png"]


async def test_deliver_falls_back_to_text_when_photo_rejected(live_settings: Settings) -> None:
    with respx.mock:
        respx.post(url__regex=PHOTO).mock(
            return_value=httpx.Response(400, json={"ok": False, "description": "wrong file"})
        )
        respx.post(url__regex=MESSAGE).mock(
            return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 22}})
        )
        async with TelegramClient(live_settings) as tg:
            message = await tg.deliver(_update(), _event())
    assert message.delivery_status == "sent"
    assert message.telegram_message_id == 22
    assert message.image_urls == []  # fell back to a text message
    assert message.error is not None  # photo error retained for the record


async def test_deliver_failure_is_captured(live_settings: Settings) -> None:
    update = _update()
    update.image_urls = []
    with respx.mock:
        respx.post(url__regex=MESSAGE).mock(
            return_value=httpx.Response(400, json={"ok": False, "description": "chat not found"})
        )
        async with TelegramClient(live_settings) as tg:
            message = await tg.deliver(update, _event())
    assert message.delivery_status == "failed"
    assert "chat not found" in (message.error or "")
