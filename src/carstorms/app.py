"""Orchestration and command-line interface.

Ties the pieces together: poll sources -> correlate into events -> decide ->
broadcast to Telegram -> archive in Directus, on an adaptive cadence (fast while a
threat is active, relaxed when calm).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import re
import signal
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from carstorms.config import Settings, get_settings
from carstorms.directus import DirectusClient, DirectusRepository, ensure_schema
from carstorms.health import HealthServer, HealthState
from carstorms.logging import configure_logging, get_logger
from carstorms.models import (
    AlertLevel,
    EventUpdate,
    HazardEvent,
    HazardObservation,
    HazardType,
    SentMessage,
    SourceName,
)
from carstorms.pipeline import EvaluationResult, evaluate, evaluate_close
from carstorms.sources import build_sources
from carstorms.sources.base import HazardSource
from carstorms.telegram import TelegramClient
from carstorms.telegram.formatting import render

log = get_logger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


def make_http_client(settings: Settings) -> httpx.AsyncClient:
    """Shared client for all hazard sources (NWS requires a User-Agent)."""
    return httpx.AsyncClient(
        timeout=settings.http_timeout_seconds,
        headers={
            "User-Agent": settings.http_user_agent,
            "Accept": "application/geo+json, application/json",
        },
        follow_redirects=True,
    )


@dataclass(slots=True)
class CycleReport:
    ok: bool
    observations: int
    notified: int
    max_level: AlertLevel
    next_interval_seconds: int


class Orchestrator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sources = build_sources(settings)
        self._last_poll: dict[str, float] = {}

    def _due_sources(self) -> list[HazardSource]:
        mono = time.monotonic()
        due: list[HazardSource] = []
        for source in self.sources:
            last = self._last_poll.get(source.name)
            if (
                last is None
                or source.min_interval_seconds == 0
                or mono - last >= source.min_interval_seconds
            ):
                self._last_poll[source.name] = mono
                due.append(source)
        return due

    async def run_cycle(
        self,
        http: httpx.AsyncClient,
        repo: DirectusRepository | None,
        telegram: TelegramClient | None,
        dry_run: bool,
    ) -> CycleReport:
        now = datetime.now(UTC)
        results = await asyncio.gather(*(source.poll(http) for source in self._due_sources()))

        if repo is not None:
            for result in results:
                try:
                    await repo.insert_source_run(result, now)
                except Exception as exc:
                    log.warning("source_run.persist_failed", source=result.source, error=str(exc))
            measurements = [m for r in results for m in r.measurements]
            if measurements:
                try:
                    stored = await repo.archive_measurements(measurements, now)
                    log.info("measurements.archived", new=stored, total=len(measurements))
                except Exception as exc:
                    log.warning("measurements.persist_failed", error=str(exc))

        # Keep the most severe observation per event_key for this cycle.
        by_key: dict[str, HazardObservation] = {}
        for result in results:
            for obs in result.observations:
                existing = by_key.get(obs.event_key)
                if existing is None or obs.level > existing.level:
                    by_key[obs.event_key] = obs

        active = await repo.get_active_events() if repo is not None else {}
        seen: set[str] = set()
        notified = 0
        max_level = AlertLevel.INFORMATIONAL
        ok = True

        for key, obs in by_key.items():
            seen.add(key)
            max_level = AlertLevel(max(int(max_level), int(obs.level)))
            result_eval = evaluate(obs, active.get(key), now, self.settings)
            try:
                if await self._dispatch(result_eval, repo, telegram, dry_run, now):
                    notified += 1
            except Exception as exc:
                ok = False
                log.error("event.dispatch_failed", event_key=key, error=str(exc))

        # Close events that have dropped out of every feed and gone stale.
        for key, prior in active.items():
            if key in seen:
                continue
            close = evaluate_close(prior, now, self.settings)
            if close is None:
                continue
            try:
                if await self._dispatch(close, repo, telegram, dry_run, now):
                    notified += 1
            except Exception as exc:
                ok = False
                log.error("event.close_failed", event_key=key, error=str(exc))

        interval = (
            self.settings.poll_interval_active_seconds
            if max_level >= AlertLevel.WATCH
            else self.settings.poll_interval_calm_seconds
        )
        log.info(
            "cycle.complete",
            observations=len(by_key),
            notified=notified,
            max_level=int(max_level),
            sources_ok=sum(1 for r in results if r.status == "ok"),
        )
        return CycleReport(ok, len(by_key), notified, max_level, interval)

    async def _dispatch(
        self,
        result: EvaluationResult,
        repo: DirectusRepository | None,
        telegram: TelegramClient | None,
        dry_run: bool,
        now: datetime,
    ) -> bool:
        """Persist the event/update and, if warranted, send and archive a message.

        Returns ``True`` if a message was sent (or printed in dry-run)."""
        event = result.event
        update = result.update
        event_id: int | None = None
        update_id: int | None = None

        if repo is not None:
            saved = await repo.upsert_event(event)
            event_id = saved.id
            update_id = await repo.insert_update(event_id, update, now)

        if not update.should_notify:
            return False

        if telegram is not None and not dry_run:
            message = await telegram.deliver(update, event)
        else:
            message = self._skipped_message(update, event)
            self._print_console(update, event)

        if repo is not None:
            await repo.insert_message(event_id, update_id, message, now)
        return True

    def _skipped_message(self, update: EventUpdate, event: HazardEvent) -> SentMessage:
        return SentMessage(
            event_key=update.event_key,
            channel=self.settings.telegram_channel_id or "dry-run",
            level=update.level,
            change_type=update.change_type,
            text=render(update, event, self.settings),
            image_urls=update.image_urls,
            recommendation=update.recommendation,
            delivery_status="skipped",
        )

    def _print_console(self, update: EventUpdate, event: HazardEvent) -> None:
        text = _TAG_RE.sub("", render(update, event, self.settings))
        banner = "─" * 60
        print(f"\n{banner}\n[WOULD SEND · {update.change_type.value.upper()}]\n{text}\n{banner}")


# --------------------------------------------------------------------------
# CLI commands
# --------------------------------------------------------------------------


async def cmd_run(settings: Settings, *, once: bool, dry_run: bool) -> int:
    orch = Orchestrator(settings)
    state = HealthState(max_age_seconds=max(settings.poll_interval_calm_seconds * 3, 900))
    server: HealthServer | None = None
    if not once:
        server = HealthServer(settings.health_host, settings.health_port, state)
        server.start()

    repo: DirectusRepository | None = None
    directus_client: DirectusClient | None = None
    telegram: TelegramClient | None = None

    if dry_run:
        log.info("run.dry_run", message="No messages will be sent and nothing will be persisted.")
    else:
        if settings.directus_enabled:
            directus_client = DirectusClient(settings)
            await ensure_schema(directus_client, settings.directus_collection_prefix)
            repo = DirectusRepository(directus_client, settings.directus_collection_prefix)
        else:
            log.warning(
                "run.no_directus", message="Directus disabled — running without state/archive."
            )
        if settings.telegram_enabled:
            telegram = TelegramClient(settings)
        else:
            log.warning("run.no_telegram", message="Telegram disabled — messages will not be sent.")

    stop = asyncio.Event()
    _install_signal_handlers(stop)

    try:
        async with make_http_client(settings) as http:
            while not stop.is_set():
                report = await orch.run_cycle(http, repo, telegram, dry_run)
                state.mark_cycle(ok=report.ok)
                if once:
                    break
                await _sleep_or_stop(stop, report.next_interval_seconds)
    finally:
        if telegram is not None:
            await telegram.aclose()
        if directus_client is not None:
            await directus_client.aclose()
        if server is not None:
            server.stop()
    return 0


async def cmd_bootstrap(settings: Settings) -> int:
    if not settings.directus_enabled:
        log.error("bootstrap.no_token", message="CARSTORMS_DIRECTUS_TOKEN is required.")
        return 1
    async with DirectusClient(settings) as client:
        await ensure_schema(client, settings.directus_collection_prefix)
    print("Directus schema ensured.")
    return 0


async def cmd_check(settings: Settings) -> int:
    print(f"Location : {settings.location_name} ({settings.latitude}, {settings.longitude})")
    print(
        f"Directus : {settings.directus_url} ({'token set' if settings.directus_enabled else 'NO TOKEN'})"
    )
    print(f"Telegram : {'configured' if settings.telegram_enabled else 'NOT configured'}")

    rc = 0
    if settings.directus_enabled:
        try:
            async with DirectusClient(settings) as client:
                await client.ping()
                await ensure_schema(client, settings.directus_collection_prefix)
            print("Directus : OK (reachable, schema ensured)")
        except Exception as exc:
            rc = 1
            print(f"Directus : FAILED — {exc}")

    if settings.telegram_enabled:
        try:
            async with TelegramClient(settings) as tg:
                me = await tg.get_me()
            print(f"Telegram : OK (@{me.get('username')})")
        except Exception as exc:
            rc = 1
            print(f"Telegram : FAILED — {exc}")

    print("\nSources:")
    async with make_http_client(settings) as http:
        orch = Orchestrator(settings)
        results = await asyncio.gather(*(s.poll(http) for s in orch.sources))
    for result in results:
        flag = "OK " if result.status == "ok" else "ERR"
        print(
            f"  [{flag}] {result.source.value:10s} "
            f"{len(result.observations)} obs, {result.duration_ms} ms"
            + (f" — {result.error}" if result.error else "")
        )
    if any(r.status != "ok" for r in results):
        rc = rc or 1
    return rc


def _demo_evaluation(settings: Settings) -> EvaluationResult:
    now = datetime.now(UTC)
    obs = HazardObservation(
        source=SourceName.NHC,
        source_event_id="demo",
        hazard_type=HazardType.TROPICAL_CYCLONE,
        level=AlertLevel.WATCH,
        title="Tropical Storm Demo",
        headline="Tropical Storm Demo — test message",
        body=(
            "This is a CarStorms test message. A tropical storm is forecast to pass "
            "within about 180 km of St. John over the next 36 hours."
        ),
        latitude=18.0,
        longitude=-65.5,
        distance_km=180.0,
        eta=now + timedelta(hours=24),
    )
    return evaluate(obs, None, now, settings)


async def cmd_send_test(settings: Settings, *, dry_run: bool) -> int:
    result = _demo_evaluation(settings)
    event, update = result.event, result.update
    if dry_run or not settings.telegram_enabled:
        Orchestrator(settings)._print_console(update, event)
        print("\n(dry-run / Telegram not configured — nothing sent)")
        return 0
    async with TelegramClient(settings) as tg:
        message = await tg.deliver(update, event)
    print(f"Sent: status={message.delivery_status} id={message.telegram_message_id}")
    return 0 if message.delivery_status == "sent" else 1


# --------------------------------------------------------------------------
# Loop helpers
# --------------------------------------------------------------------------


def _install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # pragma: no cover — non-Unix
            loop.add_signal_handler(sig, stop.set)


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="carstorms", description="St. John USVI hazard warnings.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run the warning service.")
    run.add_argument("--once", action="store_true", help="Run a single cycle and exit.")
    run.add_argument("--dry-run", action="store_true", help="Do not send or persist anything.")

    sub.add_parser("bootstrap-directus", help="Create the carstorm_* collections and exit.")
    sub.add_parser("check", help="Validate config and source/Directus/Telegram connectivity.")

    test = sub.add_parser("send-test", help="Send a sample warning to the channel.")
    test.add_argument("--dry-run", action="store_true", help="Print instead of sending.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)

    if args.command == "run":
        return asyncio.run(cmd_run(settings, once=args.once, dry_run=args.dry_run))
    if args.command == "bootstrap-directus":
        return asyncio.run(cmd_bootstrap(settings))
    if args.command == "check":
        return asyncio.run(cmd_check(settings))
    if args.command == "send-test":
        return asyncio.run(cmd_send_test(settings, dry_run=args.dry_run))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
