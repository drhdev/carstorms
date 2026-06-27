"""Popular St. John restaurant hours with explicit source-confidence tiers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any

import httpx

AST = timezone(timedelta(hours=-4))
GOOGLE_PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_FIELD_MASK = ",".join(
    (
        "places.id",
        "places.displayName",
        "places.businessStatus",
        "places.currentOpeningHours",
        "places.websiteUri",
        "places.googleMapsUri",
        "places.nationalPhoneNumber",
        "places.attributions",
    )
)

Hours = tuple[str, str] | None


@dataclass(frozen=True)
class Restaurant:
    key: str
    name: str
    area: str
    query: str
    official_url: str
    phone: str
    schedule: tuple[Hours, ...] | None
    schedule_note: str = ""
    schedule_reviewed_on: str = "2026-06-28"


_DAILY_11_20 = (("11:00", "20:00"),) * 7
_DAILY_14_21 = (("14:00", "21:00"),) * 7
_DAILY_09_21 = (("09:00", "21:00"),) * 7
_DINNER_17_21: Hours = ("17:00", "21:00")

RESTAURANTS = (
    Restaurant("skinny_legs", "Skinny Legs", "Coral Bay", "Skinny Legs Coral Bay St John USVI", "https://www.skinnylegsvi.com/", "340-779-4982", _DAILY_11_20),
    Restaurant("longboard", "The Longboard", "Cruz Bay", "The Longboard St John USVI", "https://www.thelongboardstjohn.com/location/the-longboard-st-john/", "340-715-2210", _DAILY_14_21, "Kitchen hours; bar usually continues to 10 PM."),
    Restaurant("lime_inn", "The Lime Inn", "Cruz Bay", "The Lime Inn St John USVI", "https://thelimeinn.com/contact", "340-776-6425", (("15:00", "21:00"),) * 5 + (None, ("15:00", "21:00"))),
    Restaurant("sun_dog", "Sun Dog Cafe", "Cruz Bay", "Sun Dog Cafe St John USVI", "https://www.sundogcafe.com/", "340-693-8340", _DAILY_09_21),
    Restaurant("ocean_362", "Ocean 362", "Cruz Bay", "Ocean 362 St John USVI", "https://ocean362.com/", "340-776-0001", (_DINNER_17_21, None, None, _DINNER_17_21, _DINNER_17_21, _DINNER_17_21, _DINNER_17_21)),
    Restaurant("extra_virgin", "Extra Virgin Bistro", "Cruz Bay", "Extra Virgin Bistro St John USVI", "https://www.extravirginbistro.com/", "340-715-1864", (("17:30", "21:00"),) * 5 + (None, ("17:30", "21:00"))),
    Restaurant("miss_lucys", "Miss Lucy's", "Friis Bay", "Miss Lucy's Restaurant St John USVI", "https://misslucysrestaurant.com/", "340-693-5244", None, "Seasonal operation: same-day confirmation is required."),
)


async def fetch_google_restaurants(
    http: httpx.AsyncClient,
    *,
    api_key: str,
    latitude: float,
    longitude: float,
    fetched_at: datetime,
) -> list[dict[str, Any]]:
    async def fetch_one(restaurant: Restaurant) -> dict[str, Any]:
        response = await http.post(
            GOOGLE_PLACES_SEARCH_URL,
            headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": GOOGLE_FIELD_MASK},
            json={
                "textQuery": restaurant.query,
                "languageCode": "en",
                "regionCode": "VI",
                "includedType": "restaurant",
                "strictTypeFiltering": False,
                "maxResultCount": 1,
                "locationBias": {
                    "circle": {
                        "center": {"latitude": latitude, "longitude": longitude},
                        "radius": 20000.0,
                    }
                },
            },
        )
        response.raise_for_status()
        places = (response.json() or {}).get("places") or []
        return {
            "key": restaurant.key,
            "place": places[0] if places else None,
            "fetched_at": fetched_at.isoformat(),
        }

    results = await asyncio.gather(
        *(fetch_one(restaurant) for restaurant in RESTAURANTS), return_exceptions=True
    )
    output: list[dict[str, Any]] = []
    for restaurant, result in zip(RESTAURANTS, results, strict=True):
        if isinstance(result, BaseException):
            output.append({"key": restaurant.key, "error": str(result)})
        else:
            output.append(result)
    return output


def build_restaurant_panel(
    google_data: Any,
    notices: Any,
    forecast: dict[str, Any] | None,
    power: dict[str, Any],
    alerts: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    local_now = now.astimezone(AST)
    google_by_key = {
        str(item.get("key")): item
        for item in google_data or []
        if isinstance(item, dict) and item.get("place")
    }
    items = []
    for restaurant in RESTAURANTS:
        item = _fallback_item(restaurant, local_now)
        google = google_by_key.get(restaurant.key)
        if google:
            item.update(_google_item(restaurant, google, local_now))
        override = _notice_override(restaurant, notices, local_now)
        if override:
            item.update(override)
        items.append(item)

    disruption = _disruption_assessment(forecast, power, alerts)
    return {
        "available": True,
        "date": local_now.date().isoformat(),
        "time": local_now.isoformat(),
        "items": items,
        "live_source_available": bool(google_by_key),
        "disruption": disruption,
        "policy": (
            "Verified same-day notice > Google current/special hours > official published schedule. "
            "Published hours are never presented as proof that a venue opened today."
        ),
    }


def _fallback_item(restaurant: Restaurant, now: datetime) -> dict[str, Any]:
    hours = restaurant.schedule[now.weekday()] if restaurant.schedule else None
    if restaurant.schedule is None:
        status, label = "unconfirmed", "Same-day check needed"
        hours_text = "Seasonal / unavailable"
    elif hours is None:
        status, label = "scheduled_closed_today", "Scheduled closed today"
        hours_text = "Closed today"
    else:
        open_now = _within(now.timetz().replace(tzinfo=None), hours)
        status = "scheduled_open" if open_now else "scheduled_closed"
        label = "Scheduled open" if open_now else "Scheduled closed now"
        hours_text = _format_hours(hours)
    return {
        "key": restaurant.key,
        "name": restaurant.name,
        "area": restaurant.area,
        "status": status,
        "status_label": label,
        "hours_today": hours_text,
        "source_tier": "published_schedule",
        "source_label": "Official published schedule - not live confirmation",
        "checked_at": None,
        "schedule_reviewed_on": restaurant.schedule_reviewed_on,
        "official_url": restaurant.official_url,
        "maps_url": None,
        "phone": restaurant.phone,
        "note": restaurant.schedule_note,
        "special_hours": False,
    }


def _google_item(
    restaurant: Restaurant, google: dict[str, Any], now: datetime
) -> dict[str, Any]:
    place = google.get("place") or {}
    opening = place.get("currentOpeningHours") or {}
    descriptions = opening.get("weekdayDescriptions") or []
    today_text = _today_description(descriptions, now)
    if ":" in today_text:
        today_text = today_text.split(":", 1)[1].strip()
    business_status = place.get("businessStatus")
    if business_status and business_status != "OPERATIONAL":
        status, label = "closed", business_status.replace("_", " ").title()
    elif opening.get("openNow") is True:
        status, label = "open_now", "Open now"
    elif opening.get("openNow") is False:
        status = "closed_today" if today_text.lower() == "closed" else "closed_now"
        label = "Closed today" if status == "closed_today" else "Closed now"
    else:
        status, label = "unconfirmed", "Hours listed; live status unavailable"
    special = any(_google_date(day.get("date")) == now.date().isoformat() for day in opening.get("specialDays") or [])
    return {
        "status": status,
        "status_label": label,
        "hours_today": today_text or "Hours not supplied",
        "source_tier": "google_current_hours",
        "source_label": "current/special hours",
        "checked_at": google.get("fetched_at"),
        "official_url": place.get("websiteUri") or restaurant.official_url,
        "maps_url": place.get("googleMapsUri"),
        "phone": place.get("nationalPhoneNumber") or restaurant.phone,
        "special_hours": special,
        "attributions": place.get("attributions") or [],
        "next_open": opening.get("nextOpenTime"),
        "next_close": opening.get("nextCloseTime"),
    }


def _notice_override(
    restaurant: Restaurant, notices: Any, now: datetime
) -> dict[str, Any] | None:
    aliases = {restaurant.key.replace("_", " "), restaurant.name.lower()}
    for notice in notices if isinstance(notices, list) else []:
        if str(notice.get("category") or "").lower() not in {
            "restaurant_status",
            "restaurant_closure",
        }:
            continue
        text = f"{notice.get('title') or ''} {notice.get('body') or ''}".lower()
        if not any(alias in text for alias in aliases):
            continue
        starts = _parse_dt(notice.get("starts_at"))
        ends = _parse_dt(notice.get("ends_at"))
        if starts and now < starts.astimezone(AST):
            continue
        if ends and now > ends.astimezone(AST):
            continue
        closed = "closed" in text or "not open" in text
        return {
            "status": "closed_today" if closed else "verified_update",
            "status_label": "Closed today" if closed else "Verified same-day update",
            "hours_today": "Closed today" if closed else "See same-day notice",
            "source_tier": "verified_same_day",
            "source_label": "Operator verified from official post or phone call",
            "checked_at": (starts or now).isoformat(),
            "note": str(notice.get("body") or notice.get("title") or ""),
            "status_url": notice.get("url"),
        }
    return None


def _disruption_assessment(
    forecast: dict[str, Any] | None,
    power: dict[str, Any],
    alerts: dict[str, Any],
) -> dict[str, Any]:
    notes = []
    severity = "green"
    st_john = power.get("st_john") or {}
    if int(st_john.get("out") or 0) > 0:
        severity = "yellow"
        notes.append("WAPA reports a St. John outage; affected venues may close or become cash-only.")
    current = (forecast or {}).get("current") or {}
    code = int(current.get("weather_code") or 0)
    gust = float(current.get("wind_gusts_10m") or 0)
    if code >= 95 or gust >= 60:
        severity = "red"
        notes.append("Thunderstorm or severe gust conditions can cause sudden closures and early kitchens.")
    alert_levels = [
        int(item.get("level") or 0)
        for item in (alerts.get("items") or [])
        if item.get("hazard_type") in {"power_outage", "severe_thunderstorm", "wind", "flood"}
    ]
    if max(alert_levels, default=0) >= 3:
        severity = "red"
        notes.append("An active warning can override published restaurant hours.")
    return {
        "level": severity,
        "notes": notes,
        "call_ahead": severity != "green",
    }


def _within(value: time, hours: tuple[str, str]) -> bool:
    start = time.fromisoformat(hours[0])
    end = time.fromisoformat(hours[1])
    return start <= value < end


def _format_hours(hours: tuple[str, str]) -> str:
    return f"{_clock(hours[0])}-{_clock(hours[1])}"


def _clock(value: str) -> str:
    parsed = time.fromisoformat(value)
    suffix = "AM" if parsed.hour < 12 else "PM"
    hour = parsed.hour % 12 or 12
    minute = f":{parsed.minute:02d}" if parsed.minute else ""
    return f"{hour}{minute} {suffix}"


def _google_date(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    try:
        return f"{int(value['year']):04d}-{int(value['month']):02d}-{int(value['day']):02d}"
    except (KeyError, TypeError, ValueError):
        return None


def _today_description(descriptions: list[Any], now: datetime) -> str:
    """Find today by label; Google orders descriptions according to locale."""
    target = now.strftime("%A").lower()
    for description in descriptions:
        text = str(description)
        label = text.split(":", 1)[0].strip().lower()
        if label == target or label[:3] == target[:3]:
            return text
    return ""


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=AST)
