"""Open-Meteo — convective context to surface simple thunderstorms.

NWS issues formal warnings for *severe* storms; this fills the gap with a single,
low-noise heads-up when ordinary thunderstorms are in the short-term forecast. It
emits at most one rolling event (``openmeteo:thunderstorm``) at an informational or
advisory level, so a harmless afternoon storm never floods the channel.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from carstorms.models import AlertLevel, EventStatus, HazardObservation, HazardType, SourceName
from carstorms.sources.base import HazardSource, get_json
from carstorms.sources.nws import RADAR_IMAGE_URL

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
THUNDER_CODES = {95, 96, 99}  # WMO weather codes for thunderstorms
CAPE_THRESHOLD = 1500.0
PROB_THRESHOLD = 60.0
HORIZON_HOURS = 12


class OpenMeteoSource(HazardSource):
    name = SourceName.OPENMETEO

    async def _fetch(self, client: httpx.AsyncClient) -> list[HazardObservation]:
        params = {
            "latitude": self.settings.latitude,
            "longitude": self.settings.longitude,
            "hourly": "precipitation_probability,cape,wind_gusts_10m,weather_code",
            "forecast_days": 2,
            "timezone": "GMT",
        }
        data = await get_json(client, FORECAST_URL, params=params)
        hourly: dict[str, Any] = data.get("hourly") or {}
        times: list[str] = hourly.get("time") or []
        if not times:
            return []

        codes = hourly.get("weather_code") or []
        capes = hourly.get("cape") or []
        probs = hourly.get("precipitation_probability") or []
        gusts = hourly.get("wind_gusts_10m") or []

        now = datetime.now(UTC)
        horizon = now + timedelta(hours=HORIZON_HOURS)

        first_thunder: datetime | None = None
        max_cape = 0.0
        max_prob = 0.0
        max_gust = 0.0
        for i, raw_time in enumerate(times):
            ts = datetime.fromisoformat(raw_time).replace(tzinfo=UTC)
            if ts < now or ts > horizon:
                continue
            code = int(codes[i]) if i < len(codes) and codes[i] is not None else 0
            cape = float(capes[i]) if i < len(capes) and capes[i] is not None else 0.0
            prob = float(probs[i]) if i < len(probs) and probs[i] is not None else 0.0
            gust = float(gusts[i]) if i < len(gusts) and gusts[i] is not None else 0.0
            max_cape = max(max_cape, cape)
            max_prob = max(max_prob, prob)
            max_gust = max(max_gust, gust)
            is_thunder = code in THUNDER_CODES or (
                cape >= CAPE_THRESHOLD and prob >= PROB_THRESHOLD
            )
            if is_thunder and first_thunder is None:
                first_thunder = ts

        if first_thunder is None:
            return []

        hours_away = (first_thunder - now).total_seconds() / 3600
        level = AlertLevel.ADVISORY if hours_away <= 6 else AlertLevel.INFORMATIONAL

        body = (
            f"Thunderstorms possible from about {first_thunder.strftime('%H:%M')} UTC "
            f"(~{hours_away:.0f} h away). Peak instability {max_cape:.0f} J/kg, "
            f"precipitation chance up to {max_prob:.0f}%, wind gusts up to {max_gust:.0f} km/h. "
            "This is general guidance, not a severe-weather warning."
        )

        return [
            HazardObservation(
                source=SourceName.OPENMETEO,
                source_event_id="thunderstorm",
                hazard_type=HazardType.THUNDERSTORM,
                level=level,
                status=EventStatus.ACTIVE,
                title="Thunderstorms in the forecast",
                headline="Thunderstorms possible near St. John",
                body=body,
                latitude=self.settings.latitude,
                longitude=self.settings.longitude,
                affects_st_john=True,
                eta=first_thunder,
                image_urls=[RADAR_IMAGE_URL],
                raw={
                    "max_cape": max_cape,
                    "max_precip_prob": max_prob,
                    "max_gust_kmh": max_gust,
                    "first_thunder": first_thunder.isoformat(),
                },
            )
        ]
