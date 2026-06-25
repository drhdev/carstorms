"""Build the dashboard snapshot by fanning out to every panel source.

Each source is fetched concurrently and isolated: one feed failing degrades only
its card, never the page. Fetches (raw I/O) are separated from transforms (pure)
so the transforms are easy to test and resilient to missing data.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import httpx

from carstorms.config import Settings
from carstorms.content.ferry import next_departures
from carstorms.content.recommendations import recommendation_text
from carstorms.dashboard.astro import describe_weather, moon_phase, uv_risk
from carstorms.directus.repository import DirectusRepository
from carstorms.geo import haversine_km, usvi_island
from carstorms.logging import get_logger
from carstorms.models import AlertLevel, HazardType, Island
from carstorms.sources.base import get_json, get_text

log = get_logger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
TIDES_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
NHC_URL = "https://www.nhc.noaa.gov/CurrentStorms.json"
USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
METAR_URL = "https://aviationweather.gov/api/data/metar"
NDBC_URL = "https://www.ndbc.noaa.gov/data/realtime2/{buoy}.txt"
INAT_URL = "https://api.inaturalist.org/v1/observations"
# USF AFAI (floating-algae / Sargassum index) 7-day composite, hosted on NOAA ERDDAP.
SARGASSUM_URL = (
    "https://cwcgom.aoml.noaa.gov/erddap/griddap/noaa_aoml_atlantic_oceanwatch_AFAI_7D.json"
)

_MOORINGS = [
    "Maho Bay",
    "Francis Bay",
    "Waterlemon Cay",
    "Reef Bay",
    "Great Lameshur Bay",
    "Salt Pond Bay",
]

# Atlantic Standard Time (USVI is UTC-4 year-round, no daylight saving).
AST = timezone(timedelta(hours=-4))


def _ast(value: Any) -> str | None:
    """Return a St. John local-time (AST) ISO string from any input form.

    Open-Meteo / CO-OPS naive strings are already AST wall-clock (we request that
    timezone); epoch milliseconds (USGS) and UTC datetimes are converted."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=AST)
        return dt.astimezone(AST).isoformat()
    if isinstance(value, (int, float)):  # epoch milliseconds
        return datetime.fromtimestamp(value / 1000, tz=UTC).astimezone(AST).isoformat()
    text = str(value).strip().replace(" ", "T")
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    dt = dt.replace(tzinfo=AST) if dt.tzinfo is None else dt.astimezone(AST)
    return dt.isoformat()


def _dust_label(dust: Any) -> str:
    value = _to_float(dust)
    if value is None:
        return "unknown"
    if value < 20:
        return "low"
    if value < 50:
        return "moderate"
    if value < 100:
        return "elevated (Saharan dust likely)"
    return "high (Saharan dust)"


class DashboardBuilder:
    def __init__(self, settings: Settings, repo: DirectusRepository | None = None) -> None:
        self.settings = settings
        self.repo = repo

    async def build(self, http: httpx.AsyncClient) -> dict[str, Any]:
        now = datetime.now(UTC)
        results = dict(
            await asyncio.gather(
                self._safe("forecast", self._fetch_forecast(http)),
                self._safe("marine", self._fetch_marine(http)),
                self._safe("air", self._fetch_air(http)),
                self._safe("tides", self._fetch_tides(http, now)),
                self._safe("tropical", self._fetch_tropical(http)),
                self._safe("quakes", self._fetch_quakes(http, now)),
                self._safe("metar", self._fetch_metar(http)),
                self._safe("ndbc", self._fetch_ndbc(http, now)),
                self._safe("wapa", self._fetch_wapa(http)),
                self._safe("nps", self._fetch_nps(http)),
                self._safe("inat", self._fetch_inat(http)),
                self._safe("sargassum", self._fetch_sargassum(http)),
                self._safe("alerts", self._fetch_alerts()),
                self._safe("beaches", self._fetch_beaches()),
                self._safe("events", self._fetch_events()),
                self._safe("health", self._fetch_health()),
            )
        )

        panels: dict[str, Any] = {
            "alerts": self._panel_alerts(results["alerts"]),
            "forecast": self._panel_forecast(results["forecast"]),
            "uv": self._panel_uv(results["forecast"]),
            "sun_moon": self._panel_sun_moon(results["forecast"], now),
            "air_quality": self._panel_air(results["air"]),
            "marine": self._panel_marine(results["marine"], results["ndbc"]),
            "tides": self._panel_tides(results["tides"], now),
            "tropical": self._panel_tropical(results["tropical"]),
            "earthquakes": self._panel_quakes(results["quakes"]),
            "beaches": self._panel_beaches(results["beaches"]),
            "power": self._panel_power(results["wapa"]),
            "national_park": self._panel_nps(results["nps"]),
            "sargassum": self._panel_sargassum(results["sargassum"]),
            "wildlife": self._panel_wildlife(results["inat"]),
            "travel": self._panel_travel(results["metar"], results["alerts"]),
            "events": self._panel_events(results["events"]),
            "moorings": self._panel_moorings(results["marine"], results["forecast"]),
            "data_health": self._panel_health(results["health"]),
        }
        return {
            "generated_at": _ast(now),
            "location": {
                "name": self.settings.location_name,
                "latitude": self.settings.latitude,
                "longitude": self.settings.longitude,
            },
            "panels": panels,
        }

    async def _safe(self, name: str, coro: Any) -> tuple[str, Any]:
        try:
            return name, await coro
        except Exception as exc:
            log.warning("dashboard.fetch_error", panel=name, error=str(exc))
            return name, None

    # --- Fetchers ---------------------------------------------------------

    async def _fetch_forecast(self, http: httpx.AsyncClient) -> Any:
        return await get_json(
            http,
            FORECAST_URL,
            params={
                "latitude": self.settings.latitude,
                "longitude": self.settings.longitude,
                "timezone": self.settings.timezone_name,
                "forecast_days": 7,
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m,wind_gusts_10m,wind_direction_10m,uv_index",
                "hourly": "temperature_2m,precipitation_probability,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,uv_index_max,sunrise,sunset",
            },
        )

    async def _fetch_marine(self, http: httpx.AsyncClient) -> Any:
        return await get_json(
            http,
            MARINE_URL,
            params={
                "latitude": self.settings.latitude,
                "longitude": self.settings.longitude,
                "timezone": self.settings.timezone_name,
                "current": "wave_height,wave_direction,wave_period,swell_wave_height,swell_wave_period,swell_wave_direction,sea_surface_temperature",
            },
        )

    async def _fetch_air(self, http: httpx.AsyncClient) -> Any:
        return await get_json(
            http,
            AIR_URL,
            params={
                "latitude": self.settings.latitude,
                "longitude": self.settings.longitude,
                "timezone": self.settings.timezone_name,
                "current": "us_aqi,pm2_5,pm10,dust,aerosol_optical_depth,ozone,nitrogen_dioxide,uv_index",
            },
        )

    async def _fetch_tides(self, http: httpx.AsyncClient, now: datetime) -> Any:
        return await get_json(
            http,
            TIDES_URL,
            params={
                "product": "predictions",
                "application": "carstorms",
                "datum": "MLLW",
                "station": self.settings.tide_station_id,
                "time_zone": "lst_ldt",
                "interval": "hilo",
                "units": "english",
                "format": "json",
                "begin_date": now.strftime("%Y%m%d"),
                "range": 48,
            },
        )

    async def _fetch_tropical(self, http: httpx.AsyncClient) -> Any:
        return await get_json(http, NHC_URL)

    async def _fetch_quakes(self, http: httpx.AsyncClient, now: datetime) -> Any:
        return await get_json(
            http,
            USGS_URL,
            params={
                "format": "geojson",
                "latitude": self.settings.latitude,
                "longitude": self.settings.longitude,
                "maxradiuskm": self.settings.earthquake_radius_km,
                "minmagnitude": 2.5,
                "starttime": (now - timedelta(hours=24)).isoformat(),
                "orderby": "time",
            },
        )

    async def _fetch_metar(self, http: httpx.AsyncClient) -> Any:
        return await get_json(
            http, METAR_URL, params={"ids": self.settings.airport_icao, "format": "json"}
        )

    async def _fetch_ndbc(self, http: httpx.AsyncClient, now: datetime) -> Any:
        text = await get_text(http, NDBC_URL.format(buoy=self.settings.ndbc_buoy_id))
        for line in text.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            cols = line.split()
            if len(cols) < 15:
                continue
            try:
                observed = datetime(
                    int(cols[0]), int(cols[1]), int(cols[2]), int(cols[3]), int(cols[4]), tzinfo=UTC
                )
            except ValueError:
                return None
            age_h = (now - observed).total_seconds() / 3600
            if age_h > self.settings.ndbc_max_age_hours:
                return None  # stale buoy — fall back to the model

            def _num(value: str) -> float | None:
                return None if value == "MM" else float(value)

            return {
                "observed_at": _ast(observed),
                "wave_height_m": _num(cols[8]),
                "dominant_period_s": _num(cols[9]),
                "mean_direction_deg": _num(cols[11]),
                "water_temp_c": _num(cols[14]),
            }
        return None

    async def _fetch_wapa(self, http: httpx.AsyncClient) -> Any:
        base = self.settings.wapa_outage_base.rstrip("/")
        outages = await get_json(http, f"{base}/data/outages.json")
        summary: dict[str, Any] = {}
        try:
            summary = await get_json(http, f"{base}/data/outageSummary.json")
        except Exception:
            summary = {}
        return {"outages": outages, "summary": summary}

    async def _fetch_inat(self, http: httpx.AsyncClient) -> Any:
        return await get_json(
            http,
            INAT_URL,
            params={
                "lat": self.settings.latitude,
                "lng": self.settings.longitude,
                "radius": 12,  # km — covers St. John and nearby cays
                "per_page": 8,
                "order_by": "observed_on",
                "order": "desc",
                "photos": "true",
                "quality_grade": "research",
            },
            headers={"User-Agent": self.settings.http_user_agent},
        )

    async def _fetch_alerts(self) -> Any:
        if self.repo is None:
            return None
        return list((await self.repo.get_active_events()).values())

    async def _fetch_beaches(self) -> Any:
        if self.repo is None:
            return None
        return await self.repo.get_latest_measurements("enterococcus", island="st_john")

    async def _fetch_nps(self, http: httpx.AsyncClient) -> Any:
        if not self.settings.nps_enabled:
            return None
        base = "https://developer.nps.gov/api/v1"
        headers = {"X-Api-Key": self.settings.nps_api_key}
        code = self.settings.nps_park_code
        park = await get_json(
            http,
            f"{base}/parks",
            params={"parkCode": code, "fields": "operatingHours,weatherInfo"},
            headers=headers,
        )
        alerts: Any = {}
        try:
            alerts = await get_json(
                http, f"{base}/alerts", params={"parkCode": code, "limit": 10}, headers=headers
            )
        except Exception:  # alerts are optional
            alerts = {}
        return {"park": park, "alerts": alerts}

    async def _fetch_events(self) -> Any:
        if self.repo is None:
            return None
        return await self.repo.get_notices()

    async def _fetch_health(self) -> Any:
        if self.repo is None:
            return None
        return await self.repo.get_latest_source_runs()

    # --- Transforms (pure, None-safe) ------------------------------------

    @staticmethod
    def _unavailable(reason: str = "unavailable") -> dict[str, Any]:
        return {"available": False, "reason": reason}

    def _panel_alerts(self, events: Any) -> dict[str, Any]:
        if events is None:
            return self._unavailable("directus not configured")
        cards = []
        for ev in sorted(events, key=lambda e: int(e.current_level), reverse=True):
            cards.append(
                {
                    "level": int(ev.current_level),
                    "level_label": AlertLevel(ev.current_level).label,
                    "emoji": AlertLevel(ev.current_level).emoji,
                    "hazard_type": ev.hazard_type.value,
                    "title": ev.title,
                    "headline": ev.summary or ev.title,
                    "island": ev.island.value if ev.island else None,
                    "distance_km": ev.distance_km,
                    "recommendation": recommendation_text(ev.hazard_type, ev.current_level),
                }
            )
        return {"available": True, "count": len(cards), "items": cards}

    def _panel_forecast(self, j: Any) -> dict[str, Any]:
        if not j:
            return self._unavailable()
        cur = j.get("current", {})
        hourly = j.get("hourly", {})
        daily = j.get("daily", {})
        current_time = cur.get("time", "")
        times: list[str] = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])
        probs = hourly.get("precipitation_probability", [])
        codes = hourly.get("weather_code", [])
        winds = hourly.get("wind_speed_10m", [])
        next24 = []
        for i, t in enumerate(times):
            if t < current_time:
                continue
            next24.append(
                {
                    "time": _ast(t),
                    "temp": temps[i] if i < len(temps) else None,
                    "precip_prob": probs[i] if i < len(probs) else None,
                    "weather": describe_weather(codes[i] if i < len(codes) else None),
                    "wind": winds[i] if i < len(winds) else None,
                }
            )
            if len(next24) >= 24:
                break
        days = []
        for i, d in enumerate(daily.get("time", [])):
            days.append(
                {
                    "date": _ast(d),
                    "weather": describe_weather((daily.get("weather_code") or [None])[i]),
                    "temp_max": (daily.get("temperature_2m_max") or [None])[i],
                    "temp_min": (daily.get("temperature_2m_min") or [None])[i],
                    "precip_prob": (daily.get("precipitation_probability_max") or [None])[i],
                }
            )
        return {
            "available": True,
            "current": {
                "temp": cur.get("temperature_2m"),
                "feels_like": cur.get("apparent_temperature"),
                "humidity": cur.get("relative_humidity_2m"),
                "weather": describe_weather(cur.get("weather_code")),
                "wind": cur.get("wind_speed_10m"),
                "gusts": cur.get("wind_gusts_10m"),
                "wind_dir": cur.get("wind_direction_10m"),
                "time": _ast(current_time),
            },
            "hourly": next24,
            "daily": days,
        }

    def _panel_uv(self, j: Any) -> dict[str, Any]:
        if not j:
            return self._unavailable()
        now_uv = (j.get("current") or {}).get("uv_index")
        today_max = ((j.get("daily") or {}).get("uv_index_max") or [None])[0]
        return {
            "available": True,
            "now": now_uv,
            "today_max": today_max,
            "risk": uv_risk(today_max if today_max is not None else now_uv),
            "time": _ast((j.get("current") or {}).get("time")),
        }

    def _panel_sun_moon(self, j: Any, now: datetime) -> dict[str, Any]:
        daily = (j or {}).get("daily", {}) if j else {}
        sunrise = (daily.get("sunrise") or [None])[0]
        sunset = (daily.get("sunset") or [None])[0]
        return {
            "available": True,
            "sunrise": _ast(sunrise),
            "sunset": _ast(sunset),
            "moon": moon_phase(now),
        }

    def _panel_air(self, j: Any) -> dict[str, Any]:
        if not j:
            return self._unavailable()
        cur = j.get("current", {})
        aqi = cur.get("us_aqi")
        return {
            "available": True,
            "us_aqi": aqi,
            "category": _aqi_category(aqi),
            "pm2_5": cur.get("pm2_5"),
            "pm10": cur.get("pm10"),
            "dust": cur.get("dust"),
            "dust_label": _dust_label(cur.get("dust")),
            "aerosol_optical_depth": cur.get("aerosol_optical_depth"),
            "ozone": cur.get("ozone"),
            "nitrogen_dioxide": cur.get("nitrogen_dioxide"),
            "time": _ast(cur.get("time")),
        }

    def _panel_marine(self, marine: Any, ndbc: Any) -> dict[str, Any]:
        if not marine:
            return self._unavailable()
        cur = marine.get("current", {})
        out = {
            "available": True,
            "wave_height_m": cur.get("wave_height"),
            "wave_period_s": cur.get("wave_period"),
            "wave_direction_deg": cur.get("wave_direction"),
            "swell_height_m": cur.get("swell_wave_height"),
            "swell_period_s": cur.get("swell_wave_period"),
            "sea_surface_temp_c": cur.get("sea_surface_temperature"),
            "time": _ast(cur.get("time")),
            "source": "Open-Meteo (model)",
        }
        if ndbc:
            out["observed"] = ndbc
            out["observed_source"] = f"NDBC {self.settings.ndbc_buoy_id}"
        return out

    def _panel_tides(self, j: Any, now: datetime) -> dict[str, Any]:
        if not j or "predictions" not in j:
            return self._unavailable()
        upcoming = []
        for p in j["predictions"]:
            upcoming.append(
                {
                    "time": _ast(p.get("t")),
                    "type": p.get("type"),
                    "height_ft": _to_float(p.get("v")),
                }
            )
        return {"available": True, "station": self.settings.tide_station_id, "events": upcoming[:6]}

    def _panel_tropical(self, j: Any) -> dict[str, Any]:
        storms = (j or {}).get("activeStorms", []) if j else []
        items = [
            {
                "name": s.get("name"),
                "classification": s.get("classification"),
                "intensity_kt": s.get("intensity"),
                "movement": f"{s.get('movementDir')}° at {s.get('movementSpeed')} kt",
            }
            for s in storms
        ]
        return {
            "available": j is not None,
            "active": items,
            "note": "No active tropical systems."
            if not items
            else f"{len(items)} active system(s).",
        }

    def _panel_quakes(self, j: Any) -> dict[str, Any]:
        if not j:
            return self._unavailable()
        items = []
        for f in j.get("features", [])[:5]:
            props = f.get("properties", {})
            coords = (f.get("geometry") or {}).get("coordinates") or [None, None]
            distance = None
            if coords[0] is not None and coords[1] is not None:
                distance = round(
                    haversine_km(
                        self.settings.latitude, self.settings.longitude, coords[1], coords[0]
                    )
                )
            items.append(
                {
                    "magnitude": props.get("mag"),
                    "place": props.get("place"),
                    "time": _ast(props.get("time")),
                    "distance_km": distance,
                    "url": props.get("url"),
                }
            )
        return {"available": True, "count": len(items), "items": items}

    def _panel_beaches(self, rows: Any) -> dict[str, Any]:
        if rows is None:
            return self._unavailable("directus not configured")
        items = [
            {
                "station_name": r.get("station_name"),
                "island": r.get("island"),
                "value": r.get("value"),
                "unit": r.get("unit"),
                "status": r.get("status"),
                "sampled_at": _ast(r.get("sampled_at")),
            }
            for r in rows
        ]
        items.sort(key=lambda x: (x["status"] != "exceedance", str(x["station_name"])))
        latest = max((str(i["sampled_at"]) for i in items if i["sampled_at"]), default=None)
        return {"available": True, "count": len(items), "items": items, "latest_sampled_at": latest}

    def _panel_power(self, data: Any) -> dict[str, Any]:
        if not data:
            return self._unavailable()
        summary = data.get("summary") or {}
        per = {Island.ST_JOHN: {"out": 0, "count": 0}, Island.ST_THOMAS: {"out": 0, "count": 0}}
        for outage in data.get("outages") or []:
            point = outage.get("outagePoint") or {}
            lat, lng = point.get("lat"), point.get("lng")
            if lat is None or lng is None:
                continue
            island = usvi_island(float(lat), float(lng))
            if island not in per:
                continue
            per[island]["out"] += int(outage.get("customersOutNow") or 0)
            per[island]["count"] += 1
        return {
            "available": True,
            "st_john": per[Island.ST_JOHN],
            "st_thomas": per[Island.ST_THOMAS],
            "territory_out": summary.get("customersOutNow"),
            "customers_served": summary.get("customersServed"),
            "updated_at": _ast(summary.get("updateTime")),
        }

    def _panel_nps(self, data: Any) -> dict[str, Any]:
        if not data:
            return self._unavailable("NPS API key not set")
        parks = (data.get("park") or {}).get("data") or []
        park = parks[0] if parks else {}
        hours = (park.get("operatingHours") or [{}])[0]
        today = datetime.now(AST).strftime("%A").lower()
        alerts = [
            {"category": a.get("category"), "title": a.get("title"), "url": a.get("url")}
            for a in ((data.get("alerts") or {}).get("data") or [])
        ][:5]
        return {
            "available": True,
            "weather_info": park.get("weatherInfo"),
            "hours_today": (hours.get("standardHours") or {}).get(today),
            "hours_description": hours.get("description"),
            "alerts": alerts,
            "url": f"https://www.nps.gov/{self.settings.nps_park_code}/",
        }

    def _panel_wildlife(self, data: Any) -> dict[str, Any]:
        if not data:
            return self._unavailable()
        items = []
        for obs in (data.get("results") or [])[:8]:
            taxon = obs.get("taxon") or {}
            photo = taxon.get("default_photo") or {}
            items.append(
                {
                    "name": taxon.get("preferred_common_name") or taxon.get("name") or "Unknown",
                    "sci": taxon.get("name"),
                    "photo": photo.get("square_url"),
                    "observed_on": obs.get("observed_on"),
                    "place": obs.get("place_guess"),
                    "url": obs.get("uri"),
                }
            )
        explore = (
            f"https://www.inaturalist.org/observations?lat={self.settings.latitude}"
            f"&lng={self.settings.longitude}&radius=12"
        )
        return {"available": True, "count": len(items), "items": items, "source_url": explore}

    async def _fetch_sargassum(self, http: httpx.AsyncClient) -> Any:
        lat, lon = self.settings.latitude, self.settings.longitude
        d = 0.13  # ~14 km box around St. John (latitude descends in this dataset)
        subset = f"AFAI[(last)][({lat + d:.4f}):({lat - d:.4f})][({lon - d:.4f}):({lon + d:.4f})]"
        return await get_json(http, f"{SARGASSUM_URL}?{subset}")

    def _panel_sargassum(self, data: Any) -> dict[str, Any]:
        region_url = (
            "https://optics.marine.usf.edu/cgi-bin/optics_data?roi=N_ANTILLES&unfold=menu_VAS_Carib"
        )
        source_url = "https://optics.marine.usf.edu/projects/saws.html"
        note = (
            "Satellite floating-algae (Sargassum) index near St. John, past 7 days. "
            "Windward (south/east) beaches are usually affected first."
        )
        base = {"region_url": region_url, "source_url": source_url, "note": note}
        table = (data or {}).get("table") or {}
        cols = table.get("columnNames") or []
        rows = table.get("rows") or []
        if "AFAI" not in cols:
            return {"available": False, "reason": "unavailable", **base}
        ai, ti = cols.index("AFAI"), cols.index("time")
        values = [r[ai] for r in rows if r[ai] is not None]
        observed_at = _ast(rows[0][ti]) if rows else None
        if not values:
            level, peak, patches = "unknown", None, 0  # all cloud-masked
        else:
            peak = max(values)
            patches = sum(1 for v in values if v >= 0.001)
            level = "elevated" if peak >= 0.002 else "moderate" if peak >= 0.001 else "low"
        return {
            "available": True,
            "level": level,
            "afai_peak": round(peak, 5) if peak is not None else None,
            "patches": patches,
            "observed_at": observed_at,
            **base,
        }

    def _panel_travel(self, metar: Any, events: Any) -> dict[str, Any]:
        ob = metar[0] if isinstance(metar, list) and metar else {}
        obs_epoch = ob.get("obsTime")  # METAR obsTime is epoch *seconds*
        obs_dt = (
            datetime.fromtimestamp(obs_epoch, tz=UTC)
            if isinstance(obs_epoch, (int, float))
            else None
        )
        airport = {
            "icao": self.settings.airport_icao,
            "name": self.settings.airport_name,
            "flight_category": ob.get("fltCat"),
            "raw": ob.get("rawOb"),
            "obs_time": _ast(obs_dt),
        }
        ferry_alerts = []
        if isinstance(events, list):
            ferry_alerts = [
                {"title": e.title, "level": int(e.current_level)}
                for e in events
                if e.hazard_type in (HazardType.FERRY, HazardType.AIRPORT)
            ]
        ferries = [
            {
                "name": r["name"],
                "to_st_john": _ast(r["to_st_john"]),
                "to_st_thomas": _ast(r["to_st_thomas"]),
            }
            for r in next_departures(datetime.now(AST))
        ]
        return {
            "available": True,
            "airport": airport,
            "ferries": ferries,
            "disruptions": ferry_alerts,
        }

    def _panel_events(self, rows: Any) -> dict[str, Any]:
        if rows is None:
            return self._unavailable("no curated events")
        items = [
            {
                "title": r.get("title"),
                "body": r.get("body"),
                "category": r.get("category"),
                "location": r.get("location"),
                "url": r.get("url"),
                "starts_at": r.get("starts_at"),
                "ends_at": r.get("ends_at"),
            }
            for r in rows
        ]
        return {"available": True, "count": len(items), "items": items}

    def _panel_moorings(self, marine: Any, forecast: Any) -> dict[str, Any]:
        wave = ((marine or {}).get("current") or {}).get("wave_height")
        wind = ((forecast or {}).get("current") or {}).get("wind_speed_10m")
        suitability = _mooring_suitability(_to_float(wave), _to_float(wind))
        return {
            "available": True,
            "suitability": suitability,
            "wave_height_m": wave,
            "wind_kmh": wind,
            "areas": _MOORINGS,
            "note": "NPS day-use moorings; live availability is not published. Suitability is derived from swell and wind.",
        }

    def _panel_health(self, runs: Any) -> dict[str, Any]:
        if runs is None:
            return self._unavailable("directus not configured")
        now = datetime.now(UTC)
        items = []
        for source, row in runs.items():
            fetched = _parse_iso(row.get("fetched_at"))
            age_min = round((now - fetched).total_seconds() / 60) if fetched else None
            items.append(
                {
                    "source": source,
                    "status": row.get("status"),
                    "age_minutes": age_min,
                    "observations": row.get("observations_count"),
                }
            )
        return {"available": True, "items": items}


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _aqi_category(aqi: Any) -> str:
    value = _to_float(aqi)
    if value is None:
        return "unknown"
    if value <= 50:
        return "Good"
    if value <= 100:
        return "Moderate"
    if value <= 150:
        return "Unhealthy for Sensitive Groups"
    if value <= 200:
        return "Unhealthy"
    if value <= 300:
        return "Very Unhealthy"
    return "Hazardous"


def _mooring_suitability(wave_m: float | None, wind_kmh: float | None) -> str:
    if wave_m is None and wind_kmh is None:
        return "unknown"
    wave = wave_m or 0.0
    wind = wind_kmh or 0.0
    if wave <= 1.0 and wind <= 28:
        return "good"
    if wave <= 1.8 and wind <= 37:
        return "marginal"
    return "poor"
