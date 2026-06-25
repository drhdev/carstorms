# CarStorms — St. John Situational Dashboard (concept)

A single web page that answers *"what do I need to know right now on St. John?"* for
residents and visitors — pulling together everything CarStorms already tracks (the
`carstorm_*` data in Directus) plus a set of free, mostly keyless live feeds, into one
glanceable, auto-refreshing view.

This is a researched concept: every panel below names a **real data source** and a
**credibility/availability** rating so we never present a fragile or stale feed as
authoritative.

---

## 1. Who it's for & design principles

- **Audience:** people on or heading to St. John (residents, day-trippers from St.
  Thomas, vacationers, boaters). Mobile-first — most will open it on a phone.
- **One page, glanceable:** a grid of cards, most-urgent first; no navigation, no
  login. Loads fast, degrades gracefully when a feed is down.
- **Honest freshness:** every card shows a "as of …" timestamp and greys out / labels
  stale data instead of showing it as current.
- **Safety on top:** active warnings always render first and most prominently, reusing
  the same threat levels and recommendations as the Telegram channel.

---

## 2. Panels (what the page should have) & data availability

Availability: **A** = official, keyless API (build now); **B** = official API needing a
key/extra work; **C** = no API → curated (manual channel) or static.

| # | Panel | What it shows | Source | Avail. | Refresh |
|---|-------|---------------|--------|:------:|---------|
| 1 | **Active alerts & next 24 h** | Live warnings + alerts expiring/onset in 24 h, with level + recommended action | `carstorm_events` (Directus) + NWS `/alerts/active` | **A** | 3–15 min |
| 2 | **Now & 24-hour forecast** | Temp, feels-like, sky, rain chance, wind/gusts, hourly strip | Open-Meteo `forecast` (hourly) + NWS gridpoint text | **A** | 15–30 min |
| 3 | **7-day outlook** | Daily hi/lo, conditions, rain probability | Open-Meteo `forecast` (daily) | **A** | 60 min |
| 4 | **UV index** | Current UV + today's max, risk band, "protect 9am–4pm" | Open-Meteo `uv_index` / `uv_index_max` (keyless) | **A** | 30 min |
| 5 | **Air quality / Saharan dust** | US AQI, PM2.5, dust concentration, health note | Open-Meteo Air-Quality API (keyless); AirNow if key set | **A** | 60 min |
| 6 | **Marine conditions** | Wave height/period/direction, swell, sea-surface temp | Open-Meteo **Marine** API (keyless); NDBC buoy **41052** observed when fresh | **A** | 30 min |
| 7 | **Tides** | Next high/low times & heights, today's curve | NOAA CO-OPS station **9751381** (Lameshur Bay) datagetter | **A** | 6 h |
| 8 | **Sun & moon** | Sunrise/sunset, day length, moon phase | Open-Meteo daily (sunrise/sunset) + computed moon phase | **A** | 6 h |
| 9 | **Tropical outlook** | Active systems + cone; NHC 7-day outlook (in season) | NHC `CurrentStorms.json` (already integrated) | **A** | 30 min |
| 10 | **Recent earthquakes** | Felt/notable quakes near USVI, last 48 h | USGS (already integrated) | **A** | 15 min |
| 11 | **Beach water quality** | Latest result per St. John beach, status + sample date | `carstorm_measurements` (EPA WQP archive) | **A** | 6 h |
| 12 | **Travel** | STT airport conditions (METAR) + ferry status | `carstorm_events` (airport METAR + manual ferry) | **A/C** | 30 min |
| 13 | **What's on (island events)** | Curated upcoming events/markets/closures | Curated via `carstorm_manual_alerts` (no events API exists) | **C** | manual |
| 14 | **Boating & moorings** | NPS day-use mooring locations/rules + today's swell/wind suitability note | Static NPS reference + Open-Meteo Marine (derived) | **C/A** | 30 min |
| 15 | **Data health** | Per-source freshness ("updated 4 min ago") | `carstorm_source_runs` (Directus) | **A** | each load |

**Notes from research**
- **Open-Meteo** alone supplies panels 2–6 and 8 with **no API key** (forecast incl.
  UV, Marine API for waves/SST, Air-Quality API for dust/AQI). This makes most of the
  dashboard buildable immediately.
- **NDBC 41052** is the St. John buoy but was last reporting ~6 weeks ago — treat it as
  *observed-when-available*, with Open-Meteo Marine as the reliable model baseline.
- **Tides** (CO-OPS 9751381) and **tropical/quake/alert/beach** data are all already
  available to us.
- **Island events** and **real-time mooring availability** have no public API; events
  are best handled by the existing operator **manual channel**, moorings by showing
  static NPS info plus a derived "good/marginal/poor" note from swell & wind.

---

## 3. Architecture (how it fits what we have)

Recommended: **serve the dashboard from the existing CarStorms worker** — it already
runs continuously, holds the Directus token server-side, and has an async `httpx`
stack. No browser CORS or exposed tokens, no second service to operate.

```
        ┌─────────────── CarStorms worker (existing) ───────────────┐
        │  poll loop (alerts) ──> Directus  (carstorm_* data)        │
        │                                                            │
        │  DashboardBuilder (new):                                   │
        │    every ~5 min, async-gather:                             │
        │      • Directus: active events, latest beach measurements, │
        │        source freshness                                    │
        │      • Open-Meteo forecast + UV + Marine + Air-Quality     │
        │      • CO-OPS tides, NDBC 41052, NHC, USGS, sun/moon       │
        │    -> build DashboardSnapshot -> cache as JSON             │
        │                                                            │
        │  HTTP server (extend the health server):                   │
        │    GET /                -> dashboard.html (static asset)   │
        │    GET /api/dashboard.json -> cached snapshot              │
        │    GET /healthz         -> (existing)                      │
        └────────────────────────────────────────────────────────────┘
```

- **`dashboard.html`** is a single self-contained file (HTML + CSS + vanilla JS, no
  build step) shipped in the package. It fetches `/api/dashboard.json` and renders the
  cards, polling every couple of minutes and showing per-card freshness.
- **Snapshot caching:** the builder refreshes on its own cadence and stores the latest
  JSON; the HTTP handler just serves the cached bytes (fast, resilient — a momentary
  feed outage keeps the last good values with an honest timestamp).
- **No new heavy dependencies:** reuse the stdlib HTTP server already used for
  `/healthz` (serve two more routes), or optionally add a tiny ASGI app if we later
  want websockets/live push. Charts via a small embedded SVG/Canvas or a CDN sparkline
  lib — kept minimal.
- **Deploy:** expose port 8080 publicly in Coolify; the dashboard lives at `/` and the
  Telegram worker keeps running in the same container. (A separate read-only container
  pointed at the same Directus is also possible if isolation is preferred.)

### New, mostly-keyless read sources to add
`dashboard/sources.py`: `forecast.py` (Open-Meteo hourly+daily+UV), `marine.py`
(Open-Meteo Marine + NDBC 41052), `airquality_om.py` (Open-Meteo Air-Quality, keyless
dust/AQI), `tides.py` (CO-OPS 9751381), `astronomy.py` (sun/moon). These are read-only
"panel providers" — they don't feed the alert pipeline, they feed the snapshot.

---

## 4. What I'd add beyond the obvious (and why)

- **UV index** — St. John sun is intense; a clear "UV 11 — burn risk in ~10 min" card
  is high-value and keyless.
- **Sea-surface temperature & swell** — matters for swimmers, snorkelers and boaters
  even with no warning in effect.
- **Tides** — essential for beaches, dinghy landings and snorkeling spots.
- **Moon phase / sun times** — practical for evening plans and fishing.
- **Data-health strip** — builds trust by being transparent about staleness.
- **Boating/mooring suitability** — derive a simple good/marginal/poor from swell +
  wind for the popular day-use moorings, since live availability isn't published.

Intentionally **not** invented: real-time mooring availability, a live "events API",
or crowd levels — none have credible feeds, so events stay curated and moorings stay
static + derived.

---

## 5. Suggested build phases

1. **Core page + keyless panels** — server snapshot + `dashboard.html`; panels 1, 2,
   3, 4, 9, 10, 11, 15 (all from data we already have or Open-Meteo/USGS/NHC).
2. **Marine & tides & sun/moon** — panels 6, 7, 8 (Open-Meteo Marine, CO-OPS, astro);
   NDBC 41052 as observed overlay.
3. **Air quality + travel + curated** — panel 5 (Open-Meteo AQ), 12 (airport/ferry),
   13 events (manual), 14 moorings (static + derived).
4. **Polish** — charts (tide curve, hourly strip, 7-day), mobile layout, dark mode,
   i18n if desired.

## 5b. Implementation status — shipped

All 15 panels are built and served by the worker at `/` (JSON at
`/api/dashboard.json`), refreshed every `CARSTORMS_DASHBOARD_REFRESH_SECONDS` (default
300s). Verified live: forecast, UV, marine (Open-Meteo Marine), tides (CO-OPS 9751381),
air quality/dust (Open-Meteo Air-Quality), sun/moon, tropical (NHC), earthquakes
(USGS), moorings (derived). The Directus-backed panels (alerts, beaches, events,
data-health) populate when a token is configured; each panel is error-isolated so one
failing feed only greys out its own card. Code: `src/carstorms/dashboard/`
(`builder.py`, `server.py`, `page.py`, `astro.py`, `state.py`). NDBC buoy 41052 is used
as an observed overlay only when fresh (it was stale at build time, so the model is the
baseline). A `carstorm_notices` Directus collection backs the curated events panel.

## 6. Open questions
- **Hosting:** serve from the existing worker container (recommended) or a separate
  read-only dashboard service?
- **Look & feel:** match the Telegram tone (clean, safety-first) — any brand colors,
  logo, or domain (e.g. a Coolify subdomain) to target?
- **Events panel:** is curating a few island events through the manual channel
  worthwhile for v1, or defer until there's an events feed to pull from?
