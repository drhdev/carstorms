"""Thread-safe holder for the latest dashboard snapshot (built async, served sync)."""

from __future__ import annotations

import json
import threading
from typing import Any


class DashboardState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: dict[str, Any] = {"status": "starting"}
        self._json: bytes = json.dumps(self._snapshot).encode("utf-8")

    def update(self, snapshot: dict[str, Any]) -> None:
        payload = json.dumps(snapshot, default=str).encode("utf-8")
        with self._lock:
            self._snapshot = snapshot
            self._json = payload

    def json_bytes(self) -> bytes:
        with self._lock:
            return self._json

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot
