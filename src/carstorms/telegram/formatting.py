"""Render an :class:`EventUpdate` into a Telegram HTML message.

Every message leads with the threat level, flags whether it is NEW or an UPDATE to
an existing event, explains what is happening and its bearing on St. John, and
always ends with concrete recommended actions plus source attribution.
"""

from __future__ import annotations

import html
from datetime import UTC, datetime, timedelta, timezone

from carstorms.config import Settings
from carstorms.models import ChangeType, EventUpdate, HazardEvent, SourceName

AST = timezone(timedelta(hours=-4))  # Atlantic Standard Time (USVI, no DST)

TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1024

_BADGES: dict[ChangeType, str] = {
    ChangeType.NEW: "🆕 NEW",
    ChangeType.ESCALATION: "⬆️ ESCALATING",
    ChangeType.DEESCALATION: "⬇️ EASING",
    ChangeType.UPDATE: "🔄 UPDATE",
    ChangeType.HEARTBEAT: "⏱ STILL ACTIVE",
    ChangeType.ALL_CLEAR: "✅ ALL CLEAR",
    ChangeType.CLOSED: "✅ ALL CLEAR",
}

_SOURCE_LABELS: dict[SourceName, str] = {
    SourceName.NWS: "NWS San Juan",
    SourceName.NHC: "NOAA NHC",
    SourceName.USGS: "USGS",
    SourceName.OPENMETEO: "Open-Meteo",
    SourceName.WQP: "EPA Water Quality Portal",
    SourceName.AIRNOW: "EPA AirNow",
    SourceName.AVWX: "NWS Aviation Weather",
    SourceName.WAPA: "WAPA outage viewer",
    SourceName.MANUAL: "CarStorms operator",
}


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def fmt_ast(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(AST).strftime("%a %d %b, %H:%M AST")


def render(
    update: EventUpdate,
    event: HazardEvent,
    settings: Settings,
    *,
    max_len: int = TELEGRAM_TEXT_LIMIT,
    now: datetime | None = None,
) -> str:
    """Build the HTML message body, trimming the (least critical) description to
    fit ``max_len`` while always preserving the recommended actions."""
    now = now or datetime.now(UTC)
    badge = _BADGES.get(update.change_type, "🔄 UPDATE")
    header = f"{update.level.emoji} <b>{_esc(update.level.label.upper())}</b> · {badge}"
    title = f"<b>{_esc(update.headline or event.title)}</b>"

    meta_lines: list[str] = []
    if update.distance_km is not None:
        meta_lines.append(f"📍 ~{int(update.distance_km)} km from {_esc(settings.location_name)}")
    if update.eta is not None:
        meta_lines.append(f"🕒 Expected around {fmt_ast(update.eta)}")
    meta = "\n".join(meta_lines)

    actions = ""
    if update.recommendation:
        actions = "<b>✅ What to do</b>\n" + _esc(update.recommendation)

    footer = (
        f"<i>Source: {_SOURCE_LABELS.get(event.source, event.source.value)} · "
        f"{fmt_ast(now)} · {_esc(settings.location_name)}</i>"
    )

    def assemble(body: str) -> str:
        parts = [header, title]
        if body:
            parts.append(_esc(body))
        if meta:
            parts.append(meta)
        if actions:
            parts.append(actions)
        parts.append(footer)
        return "\n\n".join(parts)

    text = assemble(update.body)
    if len(text) <= max_len:
        return text

    # Too long: trim the description to fit, keeping everything else intact.
    overhead = len(assemble(""))
    available = max(0, max_len - overhead - 1)
    trimmed = update.body[:available].rstrip()
    if trimmed:
        trimmed = trimmed.rsplit(" ", 1)[0] + "…"
    return assemble(trimmed)
