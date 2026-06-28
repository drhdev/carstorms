# CarStorms — Extension Concept: Public Safety, Utilities, Beaches & Travel

This document is a researched concept for extending CarStorms beyond weather/seismic
hazards to cover the rest of the things that actually disrupt life on **St. Thomas
and St. John, USVI**: power & water (WAPA), beach water-quality, air quality
(Saharan dust), sargassum, airport (STT) and ferry (STT↔STJ) status, and general
public-safety / health advisories — each with concrete recommendations.

It maps every new capability onto the existing architecture (sources → pipeline →
Directus → Telegram) and is explicit about **source credibility and reliability**, so
we never present a fragile scrape as if it were an authoritative feed.

---

## 0. Coverage change: St. Thomas + St. John

The weather backbone already covers both islands: **NWS forecast zone `VIZ001`
("St. Thomas and St. John")** is what the NWS source polls, so all official alerts
already apply territory-wide for this district. The extensions add St. Thomas
explicitly because the airport (STT) and the ferries are inherently inter-island.

Implementation:
- Keep St. John as the primary reference point; add **St. Thomas** as a second
  reference point (≈18.34, −64.93) for proximity (tropical/quake) and for tagging.
- Add an `island` tag (`st_thomas` | `st_john` | `usvi`) to events/measurements so
  beach advisories, outages, etc. can be attributed precisely.
- No NWS change needed (VIZ001 already territory-wide); optionally add the coastal
  **marine zones** (`AMZ725`/`AMZ710` area) for small-craft/surf that affect ferries.

---

## 1. Source research & credibility (the important part)

Rated **A** = official, structured, queryable API; **B** = official/aggregator data
needing light parsing; **C** = authoritative but announcement-only (HTML/social) →
needs scraping + a manual-override backstop.

| # | Capability | Best source | Tier | Endpoint / access | Cadence |
|---|-----------|-------------|:----:|-------------------|---------|
| 1 | **Beach water quality** | EPA **Water Quality Portal** (USGS/EPA + DPNR data) | **A** | `waterqualitydata.us/data/Result/search?statecode=US:78&characteristicName=Enterococcus&mimeType=geojson` | Weekly (DPNR samples 35–43 beaches: 5 STJ, 13 STT) |
| 1b | Beach advisories/closures | EPA **BEACON 2.0** + DPNR weekly "Beach Advisory" PDF | A/C | BEACON beach-action data; `dpnr.vi.gov` PDF cross-check | Weekly / as issued |
| 2 | **Air quality / Saharan dust** | EPA **AirNow API** | **A** | `airnowapi.org/aq/observation/latLong/current/?latitude=18.34&longitude=-64.93&distance=75&API_KEY=…` (free key) | Hourly |
| 3 | **Sargassum** | **NOAA CoastWatch SIR** + CARICOOS 48-hour particle trend + Sargassum Watch GPS/photos; AFAI fallback | **A** | `cwcgom.aoml.noaa.gov/SIR`; `caricoos.org/api/sargassum/sso`; `five.epicollect.net/project/sargassum-watch` | Daily / fresh observations |
| 4 | **Airport (STT) conditions** | **aviationweather.gov** METAR/TAF API | **A** | `aviationweather.gov/api/data/metar?ids=TIST&format=json` (verified live) | ~Hourly |
| 4b | **Airport closures (structured)** | **FAA NOTAM API** | **A** | `external-api.faa.gov/notamapi/v1/notams` (free client_id/secret), filter ICAO `TIST` | As issued |
| 4c | Airport status (authoritative announcements) | **VIPA** (Virgin Islands Port Authority) | **C** | `viport.com` news/status | As issued |
| 5 | **Power outages (WAPA)** | **poweroutage.us API** (WAPA = utility `1434`) | **B** | `poweroutage.us/api/getutilityoutageinfo/…` (key; free for EM depts) | 10 min |
| 5b | Power outage map (fallback) | WAPA **outage viewer** | B/C | `outageviewer.viwapa.vi` OMS backend (investigate JSON) | live |
| 6 | **Water outage / boil-water** | **WAPA advisories** + VI **DOH** | **C** | `viwapa.vi/news-information/advisory-details`; `doh.vi.gov` | As issued |
| 7 | **Ferry STT↔STJ interruptions** | **VIPA** + operators (Varlack, Transportation Services) | **C** | `viport.com/schedules-ferrycargoschedules`; `stjohnticketing.com`; `varlack-ventures.com` | As issued |
| 8 | **Public safety / health** | **VITEMA** + **VI DOH** | **C** | `vitema.vi.gov` / `@readyusvi`; `doh.vi.gov` (AlertVI/Everbridge has no public API) | As issued |

**Reliability principle.** Tier-A/B sources are polled on their natural cadence with
the same retry/telemetry the existing sources use. Tier-C sources have **no machine
API** — for those we combine (a) a resilient HTML/RSS scraper with content-hash change
detection, isolated so a parser break never harms a cycle, and (b) a **manual-override
channel** (a Directus collection a trusted operator posts to) so a ferry cancellation
or local advisory can always be broadcast and archived even when no feed exists.

---

## 2. New hazard types & how they map to the threat scale

Add to `HazardType`: `POWER_OUTAGE`, `WATER_OUTAGE`, `WATER_QUALITY`, `AIR_QUALITY`,
`SARGASSUM`, `FERRY`, `AIRPORT`, `HEALTH`, `PUBLIC_SAFETY`.

| Hazard | INFO (0) | ADVISORY (1) | WATCH (2) | WARNING (3) | EMERGENCY (4) |
|--------|----------|--------------|-----------|-------------|----------------|
| Beach water quality | beach clear | single beach > 70 cfu (no swim) | multiple beaches / territory-wide | — | — |
| Air quality (PM2.5/dust) | Good/Moderate | USG (AQI 101–150) | Unhealthy (151–200) | Very Unhealthy (201–300) | Hazardous (300+) |
| Sargassum | low risk | moderate inundation | high inundation | — | — |
| Power outage | localized | island-wide planned | large unplanned (≥ ~5% customers) | territory-wide / prolonged | — |
| Water / boil-water | notice | boil-water advisory | widespread outage | — | — |
| Airport (STT) | normal/VFR | IFR / delays | partial closure | full closure | — |
| Ferry | normal | reduced/late | route suspended | all routes suspended | — |
| Health / public safety | informational | advisory | watch | warning | emergency |

These slot directly into the existing `AlertLevel` scale and messaging policy. Beach,
air-quality and sargassum are **threshold events** keyed per beach/pollutant/island —
they notify on a threshold crossing (e.g. clear→advisory) and on clearing, then go
quiet, exactly like the current dedup logic intends.

---

## 3. New sources (one `HazardSource` each)

```
sources/
  wapa.py          POWER_OUTAGE   poweroutage.us API (or outage-viewer JSON)
  wapa_advisory.py WATER_OUTAGE   scrape viwapa.vi advisories (+ boil-water)
  beaches.py       WATER_QUALITY  EPA Water Quality Portal (per-beach enterococci)
  airquality.py    AIR_QUALITY    AirNow API (PM2.5/AQI, Saharan dust)
  sargassum.py     SARGASSUM      CariCOOS / NOAA SIR inundation risk
  airport.py       AIRPORT        aviationweather METAR/TAF + FAA NOTAM (+ VIPA)
  ferry.py         FERRY          scrape VIPA/operators (+ manual override)
  vitema.py        PUBLIC_SAFETY  scrape vitema.vi.gov / doh.vi.gov press releases
  manual.py        (any)          read carstorm_manual_alerts (operator overrides)
```

Each reuses `HazardSource`/`get_json` and emits normalized `HazardObservation`s, so the
correlation, threading, dedup, decide, Directus and Telegram layers need **no change**
— they already key on `event_key` and treat any `hazard_type` uniformly. Event keys:
`wapa:power:<island>`, `beach:<station_id>`, `airnow:pm25:<island>`,
`sargassum:<island>`, `airport:STT`, `ferry:redhook-cruzbay`, `vitema:<id>`,
`manual:<id>`.

### Graphics (official, attached as today)
- Air quality / dust → NOAA/CIMSS Saharan Air Layer image; AirNow tile.
- Sargassum → CariCOOS PR/USVI inundation map image.
- Beaches → DPNR weekly advisory graphic.
- Airport → METAR is text; attach VIPA notice where present.

---

## 4. Recommendations & "travel" advice

Add recommendation families (deterministic templates, same as today) for each new
hazard, e.g.:
- **Beach WQ advisory** → "Avoid swimming at the affected beach for ~48 h, especially
  after rain near guts/outfalls; choose a beach meeting standards."
- **Air quality / dust** → "Sensitive groups limit outdoor exertion; keep windows
  closed; have inhalers handy."
- **Sargassum** → "Expect odor and beach buildup; avoid wading through large mats
  (hydrogen-sulfide gas); sensitive groups stay upwind."
- **Power/water outage** → "Conserve water; treat/boil if advised; protect
  refrigerated medication; report outages to WAPA 340-774-3552."
- **Airport / ferry (travel)** → **early-arrival** and rebooking guidance: "Arrive at
  STT 3+ hours early; confirm your flight with the airline; expect ferry queues."
  These travel lines are also auto-appended to **tropical watch/warning** messages so
  visitors leave in time.

---

## 5. Directus additions

The existing `carstorm_events / event_updates / messages / source_runs` already
generalize to every new hazard type — no change needed for the alert flow. Add two
collections:

- **`carstorm_measurements`** — the durable, queryable archive of *readings with
  timestamps* the request calls for (beach enterococci tests, hourly AQI, outage
  customer counts, sargassum risk): `source`, `metric`, `value`, `unit`, `island`,
  `station`, `latitude`, `longitude`, `status`, `sampled_at`, `raw`. This is the
  "beach water-quality tests data with details and timestamps" reference dataset.
- **`carstorm_manual_alerts`** — operator-curated overrides for no-API categories
  (ferry cancellation, local DOH notice): `hazard_type`, `island`, `level`, `title`,
  `body`, `recommendation`, `is_active`, `expires`, `created_by`. The `manual.py`
  source reads active rows and feeds them through the normal pipeline.

---

## 6. Cadence & reliability

- Adaptive polling stays; per-source intervals: beaches **daily**, air quality
  **hourly**, sargassum **daily**, METAR **hourly**, NOTAM **~30 min**, outages
  **10 min**, scrapers (WAPA/VIPA/VITEMA) **15–30 min**.
- Scrapers are wrapped exactly like current sources (errors isolated, logged to
  `carstorm_source_runs`); a parser break degrades gracefully to the manual-override
  path rather than failing a cycle.
- API keys to obtain (all free): **AirNow**, **FAA NOTAM** (client id/secret),
  **poweroutage.us** (free tier for EM/utility; otherwise scrape the outage viewer).

---

## 7. Suggested rollout order (highest reliability/value first)

1. **Beach water quality** (WQP API) + `carstorm_measurements` — fully official, high
   demand, easy.
2. **Air quality / Saharan dust** (AirNow) — official, hourly, health-relevant.
3. **Sargassum** (CariCOOS/NOAA SIR) — official, daily.
4. **Airport STT** (aviationweather METAR + FAA NOTAM) — official.
5. **Power outages** (poweroutage.us or outage-viewer).
6. **Manual-override channel** (`carstorm_manual_alerts` + `manual.py`) — unlocks
   ferry, water/boil-water, VITEMA/DOH and any ad-hoc safety alert reliably **now**.
7. **Scrapers** (VIPA ferry/airport, WAPA water advisories, VITEMA/DOH) — best-effort
   automation layered on top of the manual backstop.

---

## 8b. Implementation status (Phase 1 — shipped)

Built and tested:
- **Beach water quality** (`sources/beaches.py`, EPA WQP) — every in-scope St. Thomas
  & St. John reading archived to `carstorm_measurements` with station + timestamp.
  **Finding:** WQP uploads lag ~months, so it is the *archive*; a swim advisory is
  raised only from a sample newer than `beach_advisory_max_age_days` (10). Real-time
  beach advisories therefore come via the manual channel (DPNR's weekly PDF).
- **Airport STT** (`sources/airport.py`) — aviationweather METAR flight category;
  optional FAA NOTAM closure check (gated on credentials).
- **Air quality / Saharan dust** (`sources/airquality.py`, AirNow) — implemented and
  gated on `CARSTORMS_AIRNOW_API_KEY`; archives AQI, alerts at "Unhealthy for
  Sensitive Groups" (101) or worse.
- **Power outages (WAPA)** (`sources/wapa.py`) — reads the outage-viewer's
  undocumented `/data/outages.json` + `/data/outageSummary.json` (no key);
  classifies outages by island from their coordinates, alerts on St. John outages
  (>= `wapa_alert_min_customers`) and archives per-island customer-out totals. Also a
  dashboard "Power (WAPA)" panel.
- **Manual-override channel** (`sources/manual.py` + `carstorm_manual_alerts`) — the
  reliable path for ferry, WAPA water, VITEMA/DOH and any ad-hoc safety/health
  alert; supports custom per-alert recommendations.
- **St. Thomas coverage** (island tagging) + **travel/early-arrival** advice in the
  recommendation templates (airport/ferry, and auto-appended to tropical watch+).
- Per-source polling cadence so the slow WQP CSV isn't re-downloaded every cycle.

Implemented dashboard extensions:
- **Beach-level Sargassum pressure** — NOAA's daily SIR KMZ is matched to registered
  beaches within 1.5 km. CARICOOS regional particle density adjusts scores by at most
  ±15 using the 48-hour trend; a GPS/photo report under 24 hours changes confidence to
  "Observed." The older island-wide AFAI aggregate is retained only as fallback.

Deferred (by design / pending decisions):
- **Automated scrapers** for VIPA (ferry/airport announcements), WAPA water/boil-water
  advisories and VITEMA/DOH — manual channel first per the chosen approach.

## 8. Decisions (resolved for Phase 1)
- No-API hazards → **manual-override channel first** (built); scrapers later.
- API keys → none yet; AirNow & FAA NOTAM sources are implemented and **gated on
  config**, activating as soon as keys are added.
- Phase 1 scope → **all Tier-A + manual channel** (shipped).
