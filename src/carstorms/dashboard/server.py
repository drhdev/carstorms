"""Threaded HTTP server: serves /healthz, the dashboard page, and its JSON.

Runs in a daemon thread (like the original health server) and reads from the
thread-safe :class:`DashboardState` that the async builder refreshes.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from carstorms.dashboard.page import DASHBOARD_HTML
from carstorms.dashboard.state import DashboardState
from carstorms.health import HealthState
from carstorms.logging import get_logger

log = get_logger(__name__)

_HTML_BYTES = DASHBOARD_HTML.encode("utf-8")


def _make_handler(health: HealthState, dashboard: DashboardState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in ("/", "/dashboard", "/index.html"):
                self._send(200, _HTML_BYTES, "text/html; charset=utf-8")
            elif path == "/api/dashboard.json":
                self._send(200, dashboard.json_bytes(), "application/json")
            elif path == "/api/airport.json":
                snapshot = dashboard.snapshot()
                airport = snapshot.get("panels", {}).get("airport")
                if not isinstance(airport, dict):
                    airport = {
                        "available": False,
                        "status": "starting",
                        "generated_at": snapshot.get("generated_at"),
                    }
                self._send(
                    200,
                    json.dumps(airport, default=str).encode("utf-8"),
                    "application/json",
                )
            elif path in ("/healthz", "/health"):
                ok = health.is_healthy()
                body = json.dumps(health.snapshot()).encode("utf-8")
                self._send(200 if ok else 503, body, "application/json")
            else:
                self._send(404, b"not found", "text/plain")

        def log_message(self, *args: Any) -> None:
            return

    return Handler


class WebServer:
    def __init__(
        self, host: str, port: int, health: HealthState, dashboard: DashboardState
    ) -> None:
        self._server = ThreadingHTTPServer((host, port), _make_handler(health, dashboard))
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> None:
        self._thread.start()
        log.info("web.started", address=self._server.server_address)

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
