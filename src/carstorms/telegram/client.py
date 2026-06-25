"""Async Telegram Bot API client for broadcasting to the public channel."""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from carstorms.config import Settings
from carstorms.logging import get_logger
from carstorms.models import EventUpdate, HazardEvent, SentMessage
from carstorms.telegram.formatting import (
    TELEGRAM_CAPTION_LIMIT,
    TELEGRAM_TEXT_LIMIT,
    render,
)

log = get_logger(__name__)

_RETRYABLE = (httpx.TransportError,)


class TelegramError(RuntimeError):
    """Raised when the Telegram API returns a non-OK response."""


class TelegramClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.base_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=settings.telegram_timeout_seconds,
            headers={"User-Agent": settings.http_user_agent},
        )

    async def __aenter__(self) -> TelegramClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
        reraise=True,
    )
    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{method}"
        resp = await self._client.post(url, json=payload)
        if resp.status_code == 429:
            retry_after = int(resp.json().get("parameters", {}).get("retry_after", 1))
            log.warning("telegram.rate_limited", retry_after=retry_after)
            await asyncio.sleep(min(retry_after, 30))
            resp = await self._client.post(url, json=payload)
        if resp.status_code >= 500:
            resp.raise_for_status()  # transient — let tenacity retry
        data = resp.json()
        if not data.get("ok"):
            raise TelegramError(f"{method} failed: {data.get('description', resp.text[:200])}")
        return dict(data.get("result", {}))

    async def send_message(self, text: str) -> int | None:
        result = await self._call(
            "sendMessage",
            {
                "chat_id": self.settings.telegram_channel_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
        return result.get("message_id")

    async def send_photo(self, photo_url: str, caption: str) -> int | None:
        result = await self._call(
            "sendPhoto",
            {
                "chat_id": self.settings.telegram_channel_id,
                "photo": photo_url,
                "caption": caption,
                "parse_mode": "HTML",
            },
        )
        return result.get("message_id")

    async def get_me(self) -> dict[str, Any]:
        return await self._call("getMe", {})

    async def deliver(self, update: EventUpdate, event: HazardEvent) -> SentMessage:
        """Send a rendered warning, attaching the first official graphic when
        available and falling back to a text message if the photo is rejected."""
        channel = self.settings.telegram_channel_id
        image = update.image_urls[0] if update.image_urls else None
        photo_error: str | None = None

        if image:
            caption = render(update, event, self.settings, max_len=TELEGRAM_CAPTION_LIMIT)
            try:
                message_id = await self.send_photo(image, caption)
                return SentMessage(
                    event_key=update.event_key,
                    channel=channel,
                    telegram_message_id=message_id,
                    level=update.level,
                    change_type=update.change_type,
                    text=caption,
                    image_urls=[image],
                    recommendation=update.recommendation,
                    delivery_status="sent",
                )
            except (TelegramError, httpx.HTTPError) as exc:
                photo_error = str(exc)
                log.warning("telegram.photo_failed", event_key=update.event_key, error=photo_error)

        text = render(update, event, self.settings, max_len=TELEGRAM_TEXT_LIMIT)
        try:
            message_id = await self.send_message(text)
            return SentMessage(
                event_key=update.event_key,
                channel=channel,
                telegram_message_id=message_id,
                level=update.level,
                change_type=update.change_type,
                text=text,
                image_urls=[],
                recommendation=update.recommendation,
                delivery_status="sent",
                error=photo_error,
            )
        except (TelegramError, httpx.HTTPError) as exc:
            log.error("telegram.send_failed", event_key=update.event_key, error=str(exc))
            return SentMessage(
                event_key=update.event_key,
                channel=channel,
                level=update.level,
                change_type=update.change_type,
                text=text,
                recommendation=update.recommendation,
                delivery_status="failed",
                error=str(exc),
            )
