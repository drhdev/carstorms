"""Tiny dependency-free health endpoint for Coolify / Docker health checks."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from carstorms.logging import get_logger

log = get_logger(__name__)


class HealthState:
    """Shared, thread-safe view of the worker's health."""

    def __init__(self, max_age_seconds: float) -> None:
        self._lock = threading.Lock()
        self._started_at = time.time()
        self._last_cycle_at: float | None = None
        self._last_cycle_ok = False
        self._cycles = 0
        self._max_age = max_age_seconds

    def mark_cycle(self, ok: bool) -> None:
        with self._lock:
            self._last_cycle_at = time.time()
            self._last_cycle_ok = ok
            self._cycles += 1

    def is_healthy(self) -> bool:
        with self._lock:
            if self._last_cycle_at is None:
                # Allow a grace period after startup before the first cycle lands.
                return time.time() - self._started_at < self._max_age
            return time.time() - self._last_cycle_at < self._max_age

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": "ok" if self.is_healthy() else "stale",
                "started_at": self._started_at,
                "last_cycle_at": self._last_cycle_at,
                "last_cycle_ok": self._last_cycle_ok,
                "cycles": self._cycles,
            }


def _make_handler(state: HealthState) -> type[BaseHTTPRequestHandler]:
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path not in ("/healthz", "/health", "/"):
                self.send_response(404)
                self.end_headers()
                return
            healthy = state.is_healthy()
            body = json.dumps(state.snapshot()).encode("utf-8")
            self.send_response(200 if healthy else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:  # silence default stderr logging
            return

    return HealthHandler


class HealthServer:
    def __init__(self, host: str, port: int, state: HealthState) -> None:
        self._server = ThreadingHTTPServer((host, port), _make_handler(state))
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> None:
        self._thread.start()
        log.info("health.started", address=self._server.server_address)

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
