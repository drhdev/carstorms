"""Typed application configuration, loaded from environment variables / .env.

All settings use the ``CARSTORMS_`` prefix, e.g. ``CARSTORMS_DIRECTUS_TOKEN``.
Secrets never live in the repository — see ``.env.example``.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CARSTORMS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Monitored location: St. John, US Virgin Islands -----------------
    location_name: str = "St. John, USVI"
    latitude: float = 18.335
    longitude: float = -64.735
    timezone_name: str = "America/St_Thomas"  # Atlantic Standard Time, no DST
    # NWS office/grid/zone covering St. John (verified via api.weather.gov).
    nws_office: str = "SJU"
    nws_grid_x: int = 277
    nws_grid_y: int = 120
    nws_zones: list[str] = Field(default_factory=lambda: ["VIZ001"])
    # St. Thomas reference point (same NWS zone VIZ001; airport & ferries live here).
    st_thomas_name: str = "St. Thomas, USVI"
    st_thomas_latitude: float = 18.343
    st_thomas_longitude: float = -64.931

    # --- Extension sources (public safety, utilities, beaches, travel) ----
    # EPA Water Quality Portal — beach Enterococcus (no key required). WQP is an
    # archive (uploads lag by months), so we backfill a wide window for the
    # measurement archive but only raise an advisory from a genuinely fresh sample.
    beach_threshold_cfu: float = 70.0  # USVI single-sample standard
    beach_lookback_days: int = 180
    beach_advisory_max_age_days: int = 10
    # EPA AirNow — air quality / Saharan dust (requires a free API key to enable).
    airnow_api_key: str = ""
    airnow_distance_miles: int = 75
    # Aviation Weather — STT airport (no key); FAA NOTAM closures need credentials.
    airport_icao: str = "TIST"
    airport_name: str = "Cyril E. King Airport (STT)"
    faa_client_id: str = ""
    faa_client_secret: str = ""
    # WAPA power outages — undocumented outage-viewer JSON (no key). St. John power
    # outages at or above this many customers raise an alert.
    wapa_outage_base: str = "http://www.outageviewer.viwapa.vi:7575"
    wapa_alert_min_customers: int = 25
    # National Park Service (VIIS) — park hours, weather blurb, alerts, events.
    # Requires a free key from https://www.nps.gov/subjects/developer/get-started.htm
    nps_api_key: str = ""
    nps_park_code: str = "viis"

    # --- Hazard detection thresholds -------------------------------------
    # A tropical cyclone whose forecast track passes within this distance of
    # St. John is considered potentially relevant.
    tropical_alert_radius_km: float = 400.0
    # Earthquakes are queried within this radius and above this magnitude.
    earthquake_radius_km: float = 500.0
    earthquake_min_magnitude: float = 2.5
    # Local felt/tsunami-relevant quake distance for raising the level.
    earthquake_near_km: float = 200.0

    # --- Update / messaging policy ---------------------------------------
    # Minimum gap between non-escalation messages for one event.
    min_message_interval_minutes: int = 30
    # Heartbeat cadence while a threat is active, by level band.
    heartbeat_warning_minutes: int = 90  # level >= WARNING (3)
    heartbeat_watch_minutes: int = 360  # level == WATCH (2)
    # An event with no fresh observation for this long is auto-closed.
    event_stale_close_minutes: int = 720

    # --- Adaptive polling cadence ----------------------------------------
    poll_interval_calm_seconds: int = 900  # 15 min when nothing is active
    poll_interval_active_seconds: int = 180  # 3 min when a threat is active

    # --- Directus --------------------------------------------------------
    directus_url: str = "https://directus.lanxys.net"
    directus_token: str = ""
    directus_collection_prefix: str = "carstorm_"
    directus_timeout_seconds: float = 20.0

    # --- Telegram --------------------------------------------------------
    telegram_bot_token: str = ""
    telegram_channel_id: str = ""  # @channelname or -100xxxxxxxxxx
    telegram_timeout_seconds: float = 20.0

    # --- Dashboard -------------------------------------------------------
    dashboard_enabled: bool = True
    dashboard_refresh_seconds: int = 300
    tide_station_id: str = "9751381"  # NOAA CO-OPS Lameshur Bay, St. John
    ndbc_buoy_id: str = "41052"  # NDBC buoy south of St. John (observed when fresh)
    ndbc_max_age_hours: int = 6  # ignore buoy data older than this

    # --- Runtime ---------------------------------------------------------
    dry_run: bool = False
    health_host: str = "0.0.0.0"
    health_port: int = 8080
    http_timeout_seconds: float = 25.0
    http_user_agent: str = "carstorms/1.0 (St. John USVI hazard warnings; stjohnproject)"
    log_level: str = "INFO"
    log_json: bool = True

    @property
    def directus_enabled(self) -> bool:
        return bool(self.directus_token)

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_channel_id)

    @property
    def airnow_enabled(self) -> bool:
        return bool(self.airnow_api_key)

    @property
    def faa_notam_enabled(self) -> bool:
        return bool(self.faa_client_id and self.faa_client_secret)

    @property
    def nps_enabled(self) -> bool:
        return bool(self.nps_api_key)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
