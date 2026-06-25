"""Minimal async Directus REST client (items, collections, fields, relations)."""

from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from carstorms.config import Settings
from carstorms.logging import get_logger

log = get_logger(__name__)


class DirectusError(RuntimeError):
    """Raised when a Directus request fails non-recoverably."""


_RETRYABLE = (httpx.TransportError,)


class DirectusClient:
    """Thin wrapper over the Directus REST API using a static access token."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.base_url = settings.directus_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=settings.directus_timeout_seconds,
            headers={
                "Authorization": f"Bearer {settings.directus_token}",
                "User-Agent": settings.http_user_agent,
            },
        )

    async def __aenter__(self) -> DirectusClient:
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
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
    ) -> httpx.Response:
        url = f"{self.base_url}{path}"
        resp = await self._client.request(method, url, params=params, json=json)
        # Retry on transient server errors; surface everything else.
        if resp.status_code >= 500:
            resp.raise_for_status()
        return resp

    # --- Health -----------------------------------------------------------
    async def ping(self) -> bool:
        resp = await self._request("GET", "/server/health")
        return resp.status_code == 200

    # --- Items ------------------------------------------------------------
    async def get_items(
        self, collection: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        resp = await self._request("GET", f"/items/{collection}", params=params)
        if resp.status_code >= 400:
            raise DirectusError(f"get_items {collection} -> {resp.status_code}: {resp.text[:300]}")
        return list(resp.json().get("data", []))

    async def create_item(self, collection: str, data: dict[str, Any]) -> dict[str, Any]:
        resp = await self._request("POST", f"/items/{collection}", json=data)
        if resp.status_code >= 400:
            raise DirectusError(
                f"create_item {collection} -> {resp.status_code}: {resp.text[:300]}"
            )
        return dict(resp.json().get("data", {}))

    async def update_item(
        self, collection: str, item_id: Any, data: dict[str, Any]
    ) -> dict[str, Any]:
        resp = await self._request("PATCH", f"/items/{collection}/{item_id}", json=data)
        if resp.status_code >= 400:
            raise DirectusError(
                f"update_item {collection}/{item_id} -> {resp.status_code}: {resp.text[:300]}"
            )
        return dict(resp.json().get("data", {}))

    # --- Schema -----------------------------------------------------------
    async def collection_exists(self, collection: str) -> bool:
        resp = await self._request("GET", f"/collections/{collection}")
        if resp.status_code == 200:
            return True
        if resp.status_code in (403, 404):
            return False
        raise DirectusError(
            f"collection_exists {collection} -> {resp.status_code}: {resp.text[:200]}"
        )

    async def create_collection(self, payload: dict[str, Any]) -> None:
        resp = await self._request("POST", "/collections", json=payload)
        if resp.status_code >= 400:
            raise DirectusError(
                f"create_collection {payload.get('collection')} -> {resp.status_code}: {resp.text[:300]}"
            )

    async def field_exists(self, collection: str, field: str) -> bool:
        resp = await self._request("GET", f"/fields/{collection}/{field}")
        if resp.status_code == 200:
            return True
        if resp.status_code in (403, 404):
            return False
        raise DirectusError(
            f"field_exists {collection}.{field} -> {resp.status_code}: {resp.text[:200]}"
        )

    async def create_field(self, collection: str, payload: dict[str, Any]) -> None:
        resp = await self._request("POST", f"/fields/{collection}", json=payload)
        if resp.status_code >= 400:
            raise DirectusError(
                f"create_field {collection}.{payload.get('field')} -> {resp.status_code}: {resp.text[:300]}"
            )

    async def create_relation(self, payload: dict[str, Any]) -> None:
        resp = await self._request("POST", "/relations", json=payload)
        if resp.status_code >= 400:
            # Relations are a UI nicety here; never fatal.
            log.warning(
                "directus.relation_skip",
                field=payload.get("field"),
                status=resp.status_code,
                body=resp.text[:200],
            )
