# CarStorms — St. John (USVI) Multi-Hazard Early-Warning System

CarStorms is a production-grade early-warning service for **St. John, U.S. Virgin
Islands**. It continuously watches authoritative, free hazard feeds, threads the
data into continuous *events*, and broadcasts **escalating warnings to a public
Telegram channel** as a threat builds and its impact on St. John becomes clearer —
from a simple afternoon thunderstorm up to a major hurricane, plus earthquakes,
floods, tsunami and dangerous-surf events.

Every message:

- leads with a clear **threat level** and whether it is **NEW** or an **UPDATE** to
  an event you've already heard about,
- explains what is happening and its bearing on St. John (distance, ETA in AST),
- always ends with concrete **recommended actions**, and
- attaches an **official graphic** (hurricane cone, ShakeMap, radar) when available.

Everything that is sent — and the events and evaluations behind it — is archived in
**Directus** (`carstorm_*` collections) so the store doubles as a durable reference
for all past hazards.

> ⚠️ **Not a substitute for official warnings.** CarStorms aggregates public data to
> help people act sooner. Always follow VITEMA, the National Weather Service and
> local authorities for life-safety decisions.

---

## Threat levels

A single scale spans every hazard type:

| Level | Name | Meaning |
|------:|------|---------|
| 🔵 0 | Informational | Awareness only (e.g. a forecast thunderstorm, a distant system being watched). |
| ⚪ 1 | Advisory | Minor hazard — be aware. |
| 🟡 2 | Watch | Conditions possible — **prepare**. |
| 🟠 3 | Warning | Conditions expected/occurring — **act**. |
| 🔴 4 | Emergency | Severe — take protective action now / evacuate. |
| 🟣 5 | Catastrophic | Extreme, life-threatening. |

## Data sources (free, authoritative)

| Source | Hazards | Key? | Role |
|--------|---------|:----:|------|
| **NWS `api.weather.gov`** (office SJU, zone VIZ001) | Severe thunderstorm, flash flood, flood, tropical storm/hurricane watch & warning, high surf, rip current, marine, tsunami | no | Primary alert backbone & local escalation (St. Thomas + St. John) |
| **NHC `CurrentStorms.json`** | Tropical cyclones | no | Storm intensity, position, motion + forecast-cone graphic |
| **USGS FDSN GeoJSON** | Earthquakes, tsunami flag | no | Regional seismicity + ShakeMap imagery |
| **Open-Meteo** | Ordinary thunderstorms | no | Low-noise convective heads-up NWS won't formally warn |
| **EPA Water Quality Portal** | Beach water quality (Enterococcus) | no | Per-beach readings archived to `carstorm_measurements`; advisory only from a fresh sample |
| **NWS Aviation Weather** (`TIST`) | STT airport conditions/closure | no¹ | METAR flight category; FAA NOTAM closure when credentials set |
| **EPA AirNow** | Air quality / Saharan dust | yes | Activates when an AirNow key is configured |
| **WAPA outage viewer** | Power outages | no | Undocumented outage-viewer JSON; St. John outages alert, both islands archived |
| **NPS API** (park `viis`) | Park hours, weather blurb, alerts, events | yes | Dashboard "National Park" panel; activates with a free NPS key |
| **USF SaWS** | Sargassum (seaweed) | no | Dashboard image panel (floating-algae density) + link to the USF regional map |
| **Ferry timetable** (curated) | STT↔STJ next departures | no | Curated published schedule (reviewed monthly); next sailing both directions, all 3 routes |
| **iNaturalist** | Recent wildlife sightings | no | Dashboard panel of recent verified observations near St. John (species, photo, link) |
| **Leaflet + OpenStreetMap** | Trail map | no | Interactive St. John trail map with curated trailheads (Reef Bay, Ram Head, …) + stats |
| **Operator overrides** (`carstorm_manual_alerts`) | Ferry, WAPA water, VITEMA/DOH, any ad-hoc | — | The reliable path for hazards with no machine feed |

¹ METAR needs no key; the optional FAA NOTAM closure check needs free FAA credentials.

> Coverage is **St. Thomas + St. John** (NWS zone VIZ001 spans both); events and
> readings are tagged by island. See [docs/EXTENSIONS.md](docs/EXTENSIONS.md) for the
> full extension concept, source credibility tiers, and what's deferred (live
> sargassum, automated scrapers for ferry/WAPA/VITEMA).

## How events stay coherent

Observations are threaded onto a stable **`event_key`** so all data for one
real-world threat is treated as the *same event*:

- **NHC** — the storm id (`nhc:al012026`), stable across every advisory.
- **NWS** — `office.phenomenon` from VTEC (`nws:TJSJ.FF`), so a *watch → warning →
  cancel* lifecycle is one escalating event, not three.
- **USGS** — the quake id (`usgs:us7000abcd`).

Each event has many **updates** and each notified update has one **message**
(`1 event → N updates → N messages`). Updates carry a `change_type`
(`new`, `escalation`, `deescalation`, `update`, `heartbeat`, `all_clear`, `closed`)
and an `is_new_event` flag, so progression vs. a genuinely new event is always clear.

## When messages are sent (timely, not spammy)

From the perspective of someone on the island — fast when it matters, quiet when it
doesn't:

- **Always:** a brand-new event, any **escalation**, and the **all-clear**.
- **Material change:** an NWS upgrade/cancel, a cone/ETA shift, a category change, a
  significant aftershock.
- **Heartbeat:** while a threat is active — Warning+ every ~90 min, Watch every ~6 h.
- **Suppressed:** a harmless thunderstorm gets a single note; unchanged data is
  de-duplicated by hash; earthquakes are announced once (no heartbeats).

The polling cadence is **adaptive**: ~3 min while a threat is active, ~15 min when calm.

---

## Directus data model

On startup CarStorms idempotently ensures these collections exist via the Directus
schema API (the token needs schema rights for auto-bootstrap):

- **`carstorm_events`** — one row per real-world event (key, hazard type, status,
  current/peak level, location, `affects_st_john`, timestamps).
- **`carstorm_event_updates`** — every evaluation/state change (level, previous level,
  `change_type`, `is_new_event`, headline, body, recommendation, distance, ETA, hash,
  raw payload).
- **`carstorm_messages`** — every Telegram message sent or attempted (text, image urls,
  telegram message id, delivery status).
- **`carstorm_source_runs`** — per-source poll telemetry (status, http status, count,
  duration) for reliability monitoring.
- **`carstorm_measurements`** — timestamped readings archive (beach Enterococcus,
  AQI, …) with station, island and value — the reference dataset for water-quality
  tests and trends.
- **`carstorm_manual_alerts`** — operator-curated overrides read back as events
  (the reliable channel for ferry/WAPA/VITEMA notices that have no API).

---

## Configuration

All settings use the `CARSTORMS_` prefix and can come from the environment or a
`.env` file. See [`.env.example`](.env.example). The essentials:

| Variable | Required | Purpose |
|----------|:--------:|---------|
| `CARSTORMS_DIRECTUS_URL` | – | Directus base URL (default `https://directus.lanxys.net`). |
| `CARSTORMS_DIRECTUS_TOKEN` | ✅ | Static token for the archive (and schema bootstrap). |
| `CARSTORMS_TELEGRAM_BOT_TOKEN` | ✅ | Bot token from @BotFather. |
| `CARSTORMS_TELEGRAM_CHANNEL_ID` | ✅ | Public channel, e.g. `@carstorms_stjohn`. |

Location, thresholds and cadences all have sensible St. John defaults and can be
overridden (see `.env.example`).

---

## Dashboard

The worker also serves a single-page **situational dashboard** for St. John at `/`
(same port as the health check, default `8080`), with a `GET /api/dashboard.json`
behind it. It refreshes every few minutes and shows, in one glance: active alerts +
next-24h, the 24h/7-day forecast, **UV index**, air quality / Saharan **dust**,
**marine** conditions (waves/swell/sea-surface temp), **tides** (Lameshur Bay),
sun & moon, tropical outlook, recent earthquakes, beach water quality, travel
(STT airport + ferry), curated island events, boating/mooring suitability, and a
data-health strip. Most panels are keyless (Open-Meteo, NOAA, USGS, NHC); the
Directus-backed panels (alerts, beaches, events, health) populate when a token is set.

```bash
uv run carstorms dashboard          # build one snapshot and print the JSON
# When the service runs (carstorms run), open http://<host>:8080/
```

See [docs/DASHBOARD.md](docs/DASHBOARD.md) for the full panel/source breakdown.

## Running

### Local (uv)

```bash
uv sync --extra dev

# Inspect every source and connectivity without sending anything:
uv run carstorms check

# Run one full cycle and print the messages it WOULD send (no secrets needed):
uv run carstorms run --once --dry-run

# Create the carstorm_* collections (needs a Directus admin token):
uv run carstorms bootstrap-directus

# Send a sample warning to the channel:
uv run carstorms send-test          # add --dry-run to only print

# Run the service (adaptive polling + /healthz on :8080):
uv run carstorms run
```

### Docker

```bash
docker compose build
docker compose up
# health: curl http://localhost:8080/healthz  (exposed inside the compose network)
```

### Deploy on Coolify v4

1. Create a **Docker Compose** resource pointing at this repository.
2. Set the environment variables (`CARSTORMS_DIRECTUS_TOKEN`,
   `CARSTORMS_TELEGRAM_BOT_TOKEN`, `CARSTORMS_TELEGRAM_CHANNEL_ID`, …) in Coolify's
   Environment UI — they are injected into [`docker-compose.yml`](docker-compose.yml).
3. Deploy. The container's `HEALTHCHECK` (`/healthz`) drives Coolify's health status;
   `restart: unless-stopped` keeps it running.

### Telegram setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. Create a **public channel** and add the bot as an **administrator** (post rights).
3. Set `CARSTORMS_TELEGRAM_CHANNEL_ID` to `@yourchannel`.

---

## Development

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run mypy src              # strict type-check
uv run pytest                # tests (fully mocked — no network)
```

CI (GitHub Actions, [`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs lint,
format-check, mypy, pytest and a Docker build on every push and PR.

### Architecture

```
src/carstorms/
  config.py            typed settings (pydantic-settings)
  models.py            domain model: HazardObservation, HazardEvent, EventUpdate, …
  geo.py               haversine + track projection
  sources/             nws, nhc, usgs, openmeteo  (httpx + tenacity retries)
  pipeline/            correlate (event threading) + decide (messaging policy)
  content/             levels (severity scales) + recommendations (action templates)
  directus/            async REST client, schema bootstrap, repository
  telegram/            send client (photo→text fallback) + HTML formatting
  health.py            /healthz server
  app.py               orchestration + CLI (run / check / bootstrap-directus / send-test)
```

## License

[GPLv3](LICENSE) — free as in freedom.
