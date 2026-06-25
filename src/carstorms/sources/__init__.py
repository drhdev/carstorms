"""Hazard data sources — free, keyless, authoritative feeds.

Each source turns a raw upstream payload into a list of normalized
:class:`~carstorms.models.HazardObservation` objects. Sources never decide
whether to notify; that is the pipeline's job.
"""

from __future__ import annotations

from carstorms.config import Settings
from carstorms.sources.airport import AirportStatusSource
from carstorms.sources.airquality import AirQualitySource
from carstorms.sources.base import HazardSource, SourceResult
from carstorms.sources.beaches import BeachWaterQualitySource
from carstorms.sources.manual import ManualAlertSource
from carstorms.sources.nhc import NHCSource
from carstorms.sources.nws import NWSSource
from carstorms.sources.openmeteo import OpenMeteoSource
from carstorms.sources.usgs import USGSSource

__all__ = [
    "AirQualitySource",
    "AirportStatusSource",
    "BeachWaterQualitySource",
    "HazardSource",
    "ManualAlertSource",
    "NHCSource",
    "NWSSource",
    "OpenMeteoSource",
    "SourceResult",
    "USGSSource",
    "build_sources",
]


def build_sources(settings: Settings) -> list[HazardSource]:
    """Instantiate the active hazard sources, gated by config/keys.

    Keyless, authoritative feeds always run; sources that need an API key or
    Directus are only included when configured.
    """
    sources: list[HazardSource] = [
        NWSSource(settings),  # weather, flood, tropical, marine, tsunami
        NHCSource(settings),  # tropical cyclones
        USGSSource(settings),  # earthquakes
        OpenMeteoSource(settings),  # simple thunderstorms
        BeachWaterQualitySource(settings),  # beach water quality (EPA WQP)
        AirportStatusSource(settings),  # STT airport (METAR + optional NOTAM)
    ]
    if settings.airnow_enabled:
        sources.append(AirQualitySource(settings))  # air quality / Saharan dust
    if settings.directus_enabled:
        sources.append(ManualAlertSource(settings))  # operator overrides
    return sources
