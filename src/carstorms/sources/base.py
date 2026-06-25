"""Shared source abstraction and resilient HTTP helpers."""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from carstorms.config import Settings
from carstorms.logging import get_logger
from carstorms.models import HazardObservation, Measurement, SourceName

log = get_logger(__name__)

_RETRYABLE = (httpx.TransportError, httpx.HTTPStatusError)


@dataclass(slots=True)
class SourceResult:
    """Outcome of one source poll — observations plus reliability telemetry."""

    source: SourceName
    observations: list[HazardObservation] = field(default_factory=list)
    measurements: list[Measurement] = field(default_factory=list)
    status: str = "ok"  # ok | error
    http_status: int | None = None
    error: str | None = None
    duration_ms: int = 0


class HazardSource(abc.ABC):
    """Base class for all hazard sources."""

    name: SourceName
    # Minimum seconds between polls (0 = every cycle). Lets slow/low-frequency
    # feeds (beaches, airport) poll less often than the adaptive cycle.
    min_interval_seconds: int = 0

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Sources that also produce timestamped readings populate this in _fetch.
        self.last_measurements: list[Measurement] = []

    @abc.abstractmethod
    async def _fetch(self, client: httpx.AsyncClient) -> list[HazardObservation]:
        """Fetch and normalize observations. May raise on failure."""

    async def poll(self, client: httpx.AsyncClient) -> SourceResult:
        """Run :meth:`_fetch`, capturing timing and errors so one bad source
        never takes the whole cycle down."""
        started = time.perf_counter()
        result = SourceResult(source=self.name)
        self.last_measurements = []
        try:
            result.observations = await self._fetch(client)
            result.measurements = self.last_measurements
        except httpx.HTTPStatusError as exc:
            result.status = "error"
            result.http_status = exc.response.status_code
            result.error = f"HTTP {exc.response.status_code} for {exc.request.url}"
            log.warning("source.http_error", source=self.name, error=result.error)
        except Exception as exc:
            result.status = "error"
            result.error = f"{type(exc).__name__}: {exc}"
            log.warning("source.error", source=self.name, error=result.error)
        finally:
            result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result


@retry(
    retry=retry_if_exception_type(_RETRYABLE),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
    reraise=True,
)
async def get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    """GET a URL and parse JSON, with exponential-backoff retries."""
    resp = await client.get(url, params=params, headers=headers)
    resp.raise_for_status()
    return resp.json()


@retry(
    retry=retry_if_exception_type(_RETRYABLE),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
    reraise=True,
)
async def get_text(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> str:
    """GET a URL and return text (e.g. CSV), with exponential-backoff retries."""
    resp = await client.get(url, params=params, headers=headers)
    resp.raise_for_status()
    return resp.text
