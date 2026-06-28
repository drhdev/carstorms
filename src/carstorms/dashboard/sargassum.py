"""Beach-level Sargassum pressure from NOAA SIR, CARICOOS and local reports."""

from __future__ import annotations

import io
import math
import struct
import zlib
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

import httpx

from carstorms.geo import haversine_km

AST = timezone(timedelta(hours=-4))

NOAA_SIR_PAGE = "https://cwcgom.aoml.noaa.gov/SIR/"
NOAA_SIR_KMZ = "https://cwcgom.aoml.noaa.gov/SIR/KMZ/sargassum_risk_{day}.kmz"
CARICOOS_PAGE = "https://www.caricoos.org/sargassum/SSOAccum/VIHR"
CARICOOS_API = "https://www.caricoos.org/api/sargassum/sso"
CARICOOS_IMAGE = (
    "https://s3.amazonaws.com/caricoos-web/ocean/sargassum/forecast/"
    "FVCOM_PRVI_MCI_v1/PR/sargassum_fvcom_mci_particles-PR-{frame:02d}.png"
)
SARGASSUM_WATCH_PAGE = "https://five.epicollect.net/project/sargassum-watch"
SARGASSUM_WATCH_API = "https://five.epicollect.net/api/export/entries/sargassum-watch"
USF_AFAI_PAGE = "https://optics.marine.usf.edu/projects/saws.html"
USF_AFAI_REGION = (
    "https://optics.marine.usf.edu/cgi-bin/optics_data?roi=N_ANTILLES&unfold=menu_VAS_Carib"
)

NOAA_SCORE = {0: 10, 1: 35, 2: 65, 3: 90}
NOAA_LEVEL = {0: "low", 1: "warning", 2: "medium", 3: "high"}

# Stable coordinate registry used for nearest-coast matching. Coordinates are
# shoreline points rather than parking lots or map-label centroids.
BEACHES: tuple[dict[str, Any], ...] = (
    {"id": "honeymoon", "name": "Honeymoon Beach", "lat": 18.3212, "lon": -64.7932},
    {"id": "salomon", "name": "Salomon Beach", "lat": 18.3240, "lon": -64.7897},
    {"id": "hawksnest", "name": "Hawksnest Bay", "lat": 18.3434, "lon": -64.7793},
    {"id": "gibney", "name": "Gibney Beach", "lat": 18.3505, "lon": -64.7696},
    {"id": "trunk", "name": "Trunk Bay", "lat": 18.3535, "lon": -64.7635},
    {"id": "cinnamon", "name": "Cinnamon Bay", "lat": 18.3561, "lon": -64.7525},
    {"id": "maho", "name": "Maho Bay", "lat": 18.3599, "lon": -64.7429},
    {"id": "francis", "name": "Francis Bay", "lat": 18.3671, "lon": -64.7400},
    {"id": "waterlemon", "name": "Waterlemon Cay", "lat": 18.3658, "lon": -64.7200},
    {"id": "haulover", "name": "Haulover Bay", "lat": 18.3482, "lon": -64.6817},
    {"id": "hansen", "name": "Hansen Bay", "lat": 18.3432, "lon": -64.6697},
    {"id": "salt_pond", "name": "Salt Pond Bay", "lat": 18.3080, "lon": -64.7061},
    {"id": "lameshur", "name": "Great Lameshur Bay", "lat": 18.3174, "lon": -64.7241},
    {"id": "reef_bay", "name": "Reef Bay", "lat": 18.3120, "lon": -64.7512},
)


async def fetch_noaa_sir(
    client: httpx.AsyncClient, now: datetime, *, max_distance_km: float = 1.5
) -> dict[str, Any] | None:
    """Download the newest NOAA daily KMZ, trying today and two prior dates."""

    now = _aware(now)
    for days_ago in range(3):
        product_date = now.date() - timedelta(days=days_ago)
        url = NOAA_SIR_KMZ.format(day=product_date.strftime("%Y%m%d"))
        response = await client.get(url)
        if response.status_code == 404:
            continue
        response.raise_for_status()
        return parse_noaa_sir_kmz(
            response.content,
            product_date=product_date,
            source_url=url,
            max_distance_km=max_distance_km,
        )
    return None


def parse_noaa_sir_kmz(
    payload: bytes,
    *,
    product_date: date,
    source_url: str,
    max_distance_km: float = 1.5,
) -> dict[str, Any]:
    """Parse NOAA SIR coastline risk segments and match registered beaches."""

    if len(payload) > 30_000_000:
        raise ValueError("NOAA SIR KMZ exceeds 30 MB safety limit")
    try:
        with ZipFile(io.BytesIO(payload)) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".kml")]
            if not names:
                raise ValueError("NOAA SIR KMZ contains no KML")
            info = archive.getinfo(names[0])
            if info.file_size > 100_000_000:
                raise ValueError("NOAA SIR KML exceeds 100 MB safety limit")
            kml = archive.read(names[0])
    except BadZipFile as exc:
        raise ValueError("invalid NOAA SIR KMZ") from exc

    root = ElementTree.fromstring(kml)
    segments: list[tuple[int, list[tuple[float, float]]]] = []
    embedded_dates: list[str] = []
    for placemark in (node for node in root.iter() if _tag(node.tag) == "Placemark"):
        risk: int | None = None
        for field in (node for node in placemark.iter() if _tag(node.tag) == "SimpleData"):
            name = str(field.attrib.get("name") or "").lower()
            if name == "risk" and field.text is not None:
                try:
                    risk = int(field.text.strip())
                except ValueError:
                    risk = None
            elif name == "date" and field.text:
                embedded_dates.append(field.text.strip())
        if risk not in NOAA_SCORE:
            continue
        for coordinates in (
            node for node in placemark.iter() if _tag(node.tag) == "coordinates" and node.text
        ):
            points = _parse_coordinates(coordinates.text or "")
            if points:
                segments.append((risk, points))

    if not segments:
        raise ValueError("NOAA SIR KML contains no risk segments")

    beaches: list[dict[str, Any]] = []
    for beach in BEACHES:
        nearest_risk: int | None = None
        nearest_distance = math.inf
        for risk, points in segments:
            distance = min(
                haversine_km(float(beach["lat"]), float(beach["lon"]), lat, lon)
                for lat, lon in points
            )
            if distance < nearest_distance:
                nearest_distance = distance
                nearest_risk = risk
        matched = nearest_risk is not None and nearest_distance <= max_distance_km
        beaches.append(
            {
                **beach,
                "matched": matched,
                "distance_to_segment_km": round(nearest_distance, 2),
                "noaa_risk_code": nearest_risk if matched else None,
                "noaa_level": NOAA_LEVEL[nearest_risk]
                if matched and nearest_risk is not None
                else "unknown",
                "base_score": NOAA_SCORE[nearest_risk]
                if matched and nearest_risk is not None
                else None,
            }
        )
    return {
        "available": any(beach["matched"] for beach in beaches),
        "product_date": product_date.isoformat(),
        "embedded_date": max(embedded_dates, default=None),
        "source_url": source_url,
        "max_distance_km": max_distance_km,
        "beaches": beaches,
    }


async def fetch_caricoos_trend(client: httpx.AsyncClient, now: datetime) -> dict[str, Any] | None:
    """Compare CARICOOS particle density now versus 48 hours ahead."""

    metadata_response = await client.get(CARICOOS_API)
    metadata_response.raise_for_status()
    metadata = metadata_response.json()
    settings = metadata.get("settings") or {}
    grid = (metadata.get("grids") or {}).get("PR") or {}
    start = _parse_datetime(settings.get("start"), UTC)
    frame_count = int(settings.get("files_per_var") or grid.get("files_per_var") or 0)
    if start is None or frame_count < 2 or not grid.get("bounds"):
        return None
    now = _aware(now)
    current_frame = max(1, min(frame_count, round((now - start).total_seconds() / 3600) + 1))
    future_frame = min(frame_count, current_frame + 48)
    if future_frame == current_frame:
        return None
    current_url = CARICOOS_IMAGE.format(frame=current_frame)
    future_url = CARICOOS_IMAGE.format(frame=future_frame)
    current_response, future_response = await _gather_get(client, current_url, future_url)
    current = _decode_transparent_png(current_response.content)
    future = _decode_transparent_png(future_response.content)
    bounds = {key: float(value) for key, value in grid["bounds"].items()}

    beaches: dict[str, dict[str, Any]] = {}
    for beach in BEACHES:
        current_density = _pixel_density(current, bounds, float(beach["lat"]), float(beach["lon"]))
        future_density = _pixel_density(future, bounds, float(beach["lat"]), float(beach["lon"]))
        adjustment = round(
            max(
                -15.0, min(15.0, 10.0 * math.log2((future_density + 0.1) / (current_density + 0.1)))
            )
        )
        beaches[str(beach["id"])] = {
            "current_density_pct": round(current_density, 2),
            "future_48h_density_pct": round(future_density, 2),
            "adjustment": adjustment,
            "trend": "increasing"
            if adjustment >= 3
            else "decreasing"
            if adjustment <= -3
            else "steady",
        }
    return {
        "available": True,
        "run_at": _iso(_parse_datetime(settings.get("time"), UTC)),
        "current_valid_at": _iso(start + timedelta(hours=current_frame - 1)),
        "future_valid_at": _iso(start + timedelta(hours=future_frame - 1)),
        "current_frame": current_frame,
        "future_frame": future_frame,
        "source_url": CARICOOS_PAGE,
        "beaches": beaches,
    }


async def fetch_sargassum_watch(client: httpx.AsyncClient, now: datetime) -> dict[str, Any]:
    since = (_aware(now) - timedelta(hours=36)).isoformat().replace("+00:00", "Z")
    response = await client.get(
        SARGASSUM_WATCH_API,
        params={
            "per_page": 500,
            "sort_order": "DESC",
            "filter_by": "uploaded_at",
            "filter_from": since,
        },
    )
    response.raise_for_status()
    entries = (response.json().get("data") or {}).get("entries") or []
    observations: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        gps = entry.get("3_GPS_Coordinates_of") or {}
        try:
            lat, lon = float(gps["latitude"]), float(gps["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        nearest = min(
            BEACHES,
            key=lambda beach: haversine_km(lat, lon, float(beach["lat"]), float(beach["lon"])),
        )
        distance = haversine_km(lat, lon, float(nearest["lat"]), float(nearest["lon"]))
        if distance > 1.0:
            continue
        observed_at = _entry_observed_at(entry)
        age_hours = (
            (_aware(now) - observed_at).total_seconds() / 3600
            if observed_at is not None
            else math.inf
        )
        if age_hours < 0 or age_hours >= 24:
            continue
        condition = str(entry.get("12_Condition_of_the_") or "Unknown")
        photos = [
            entry.get(key)
            for key in (
                "7_Photo_of_the_site_",
                "8_Photo_of_the_site_",
                "9_Photo_of_the_site_",
                "13_Photo_of_all_Sarg",
            )
            if entry.get(key)
        ]
        observations.append(
            {
                "beach_id": nearest["id"],
                "beach_name": nearest["name"],
                "observed_at": _iso(observed_at),
                "age_hours": round(age_hours, 1),
                "distance_km": round(distance, 2),
                "condition": condition,
                "site_name": entry.get("4_Site_Name_eg_Miami"),
                "photos": photos,
                "no_sargassum": "NO SARGASSUM" in condition.upper(),
            }
        )
    observations.sort(key=lambda item: item["observed_at"] or "", reverse=True)
    return {"available": True, "source_url": SARGASSUM_WATCH_PAGE, "observations": observations}


def build_sargassum_panel(data: Any, now: datetime) -> dict[str, Any]:
    """Combine sources with NOAA first, CARICOOS adjustment and fresh overrides."""

    now = _aware(now)
    bundle = data if isinstance(data, dict) else {}
    sir = bundle.get("sir") if isinstance(bundle.get("sir"), dict) else None
    caricoos = bundle.get("caricoos") if isinstance(bundle.get("caricoos"), dict) else None
    watch = bundle.get("watch") if isinstance(bundle.get("watch"), dict) else None
    afai = bundle.get("afai") if "afai" in bundle else data
    if sir and sir.get("available"):
        return _sir_panel(sir, caricoos, watch, now)
    return _afai_fallback(afai, now)


def _sir_panel(
    sir: dict[str, Any],
    caricoos: dict[str, Any] | None,
    watch: dict[str, Any] | None,
    now: datetime,
) -> dict[str, Any]:
    source_date = date.fromisoformat(str(sir["product_date"]))
    calendar_age_hours = max(0, (now.date() - source_date).days * 24)
    if calendar_age_hours < 24:
        confidence = "High-confidence estimate"
    elif calendar_age_hours < 48:
        confidence = "Forecast estimate"
    else:
        confidence = "Stale/unknown"
    observations = {
        str(item["beach_id"]): item
        for item in ((watch or {}).get("observations") or [])
        if isinstance(item, dict) and item.get("beach_id")
    }
    trends = (caricoos or {}).get("beaches") or {}
    beaches: list[dict[str, Any]] = []
    for source_beach in sir.get("beaches") or []:
        beach = dict(source_beach)
        base_score = beach.get("base_score")
        if base_score is None:
            beach.update({"score": None, "risk_level": "unknown", "confidence": "Stale/unknown"})
            beaches.append(beach)
            continue
        trend = trends.get(str(beach["id"])) if isinstance(trends, dict) else None
        adjustment = int((trend or {}).get("adjustment") or 0)
        score = max(0, min(100, int(base_score) + adjustment))
        observation = observations.get(str(beach["id"]))
        beach_confidence = confidence
        if observation:
            score = 10 if observation.get("no_sargassum") else max(score, 35)
            beach_confidence = "Observed"
        beach.update(
            {
                "score": score,
                "risk_level": _pressure_level(score),
                "confidence": beach_confidence,
                "caricoos_adjustment": adjustment,
                "caricoos_trend": (trend or {}).get("trend"),
                "observation": observation,
            }
        )
        beaches.append(beach)

    scored = [beach for beach in beaches if beach.get("score") is not None]
    scored.sort(key=lambda beach: int(beach["score"]), reverse=True)
    headline = scored[0] if scored else None
    panel_confidence = str(headline.get("confidence") or confidence) if headline else confidence
    headline_score = int(headline["score"]) if headline else None
    return {
        "available": bool(scored),
        "source": "NOAA SIR",
        "source_date": source_date.isoformat(),
        "age_hours": calendar_age_hours,
        "confidence": panel_confidence,
        "stale": calendar_age_hours >= 48,
        "score": headline_score,
        "risk_level": _pressure_level(headline_score),
        "level": _legacy_level(headline_score),
        "headline_beach": headline["name"] if headline else None,
        "beaches": beaches,
        "highest_pressure": scored[:4],
        "best_choices": sorted(scored, key=lambda beach: int(beach["score"]))[:4],
        "source_url": sir.get("source_url"),
        "region_url": NOAA_SIR_PAGE,
        "caricoos": {
            "available": bool(caricoos and caricoos.get("available")),
            "run_at": (caricoos or {}).get("run_at"),
            "future_valid_at": (caricoos or {}).get("future_valid_at"),
            "source_url": CARICOOS_PAGE,
        },
        "local_observations": (watch or {}).get("observations") or [],
        "observation_source_url": SARGASSUM_WATCH_PAGE,
        "note": (
            "Daily NOAA coastal inundation risk matched to registered beaches. CARICOOS compares "
            "regional particle density now and 48 hours ahead; its adjustment is capped at +/-15."
        ),
        "disclaimer": "Forecast estimate, not a live beach observation unless explicitly marked Observed.",
    }


def _afai_fallback(data: Any, now: datetime) -> dict[str, Any]:
    base = {
        "source": "USF AFAI fallback",
        "region_url": USF_AFAI_REGION,
        "source_url": USF_AFAI_PAGE,
        "confidence": "Fallback estimate",
        "note": "NOAA SIR unavailable; using the island-wide seven-day floating-algae index.",
        "beaches": [],
    }
    table = (data or {}).get("table") or {}
    cols = table.get("columnNames") or []
    rows = table.get("rows") or []
    if "AFAI" not in cols:
        return {"available": False, "reason": "NOAA SIR and AFAI unavailable", **base}
    ai, ti = cols.index("AFAI"), cols.index("time")
    values = [row[ai] for row in rows if row[ai] is not None]
    observed_at = _parse_datetime(rows[0][ti], UTC) if rows else None
    if not values:
        score, level, peak, patches = None, "unknown", None, 0
    else:
        peak = max(values)
        patches = sum(1 for value in values if value >= 0.001)
        score = 90 if peak >= 0.002 else 65 if peak >= 0.001 else 10
        level = _legacy_level(score)
    age_hours = round((now - observed_at).total_seconds() / 3600, 1) if observed_at else None
    return {
        "available": True,
        "score": score,
        "risk_level": _pressure_level(score) if score is not None else "unknown",
        "level": level,
        "afai_peak": round(peak, 5) if peak is not None else None,
        "patches": patches,
        "observed_at": _iso(observed_at),
        "age_hours": age_hours,
        **base,
    }


async def _gather_get(
    client: httpx.AsyncClient, first_url: str, second_url: str
) -> tuple[httpx.Response, httpx.Response]:
    import asyncio

    first, second = await asyncio.gather(client.get(first_url), client.get(second_url))
    first.raise_for_status()
    second.raise_for_status()
    return first, second


def _decode_transparent_png(payload: bytes) -> dict[str, Any]:
    """Decode the indexed, non-interlaced transparent PNG used by CARICOOS."""

    if len(payload) > 5_000_000:
        raise ValueError("CARICOOS PNG exceeds 5 MB safety limit")
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("invalid CARICOOS PNG")
    offset = 8
    width = height = bit_depth = color_type = interlace = 0
    transparency = b""
    compressed = bytearray()
    while offset + 12 <= len(payload):
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        kind = payload[offset + 4 : offset + 8]
        chunk = payload[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", chunk)
        elif kind == b"tRNS":
            transparency = chunk
        elif kind == b"IDAT":
            compressed.extend(chunk)
        elif kind == b"IEND":
            break
    if bit_depth != 8 or color_type != 3 or interlace != 0 or width * height > 5_000_000:
        raise ValueError("unsupported CARICOOS PNG format")
    stride = width
    expected_size = (stride + 1) * height
    inflater = zlib.decompressobj()
    raw = inflater.decompress(bytes(compressed), expected_size + 1)
    if len(raw) != expected_size or not inflater.eof:
        raise ValueError("invalid CARICOOS PNG payload size")
    rows: list[bytes] = []
    previous = bytearray(stride)
    position = 0
    for _ in range(height):
        filter_type = raw[position]
        position += 1
        scan = bytearray(raw[position : position + stride])
        position += stride
        reconstructed = _unfilter(scan, previous, filter_type)
        rows.append(bytes(reconstructed))
        previous = reconstructed
    return {"width": width, "height": height, "rows": rows, "alpha": transparency}


def _unfilter(scan: bytearray, previous: bytearray, filter_type: int) -> bytearray:
    result = bytearray(len(scan))
    for index, value in enumerate(scan):
        left = result[index - 1] if index else 0
        above = previous[index]
        upper_left = previous[index - 1] if index else 0
        if filter_type == 0:
            predictor = 0
        elif filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = above
        elif filter_type == 3:
            predictor = (left + above) // 2
        elif filter_type == 4:
            predictor = _paeth(left, above, upper_left)
        else:
            raise ValueError("unsupported PNG filter")
        result[index] = (value + predictor) & 0xFF
    return result


def _paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    distances = (abs(estimate - left), abs(estimate - above), abs(estimate - upper_left))
    return (left, above, upper_left)[distances.index(min(distances))]


def _pixel_density(
    image: dict[str, Any], bounds: dict[str, float], lat: float, lon: float, radius_km: float = 5.0
) -> float:
    width, height = int(image["width"]), int(image["height"])
    x = round((lon - bounds["west"]) / (bounds["east"] - bounds["west"]) * (width - 1))
    y = round((bounds["north"] - lat) / (bounds["north"] - bounds["south"]) * (height - 1))
    km_per_x = max(
        0.01, 111.32 * math.cos(math.radians(lat)) * (bounds["east"] - bounds["west"]) / width
    )
    km_per_y = max(0.01, 111.32 * (bounds["north"] - bounds["south"]) / height)
    radius_x, radius_y = math.ceil(radius_km / km_per_x), math.ceil(radius_km / km_per_y)
    alpha: bytes = image["alpha"]
    rows: list[bytes] = image["rows"]
    hits = total = 0
    for row_index in range(max(0, y - radius_y), min(height, y + radius_y + 1)):
        for column in range(max(0, x - radius_x), min(width, x + radius_x + 1)):
            dx = (column - x) * km_per_x
            dy = (row_index - y) * km_per_y
            if dx * dx + dy * dy > radius_km * radius_km:
                continue
            palette_index = rows[row_index][column]
            pixel_alpha = alpha[palette_index] if palette_index < len(alpha) else 255
            hits += int(pixel_alpha > 0)
            total += 1
    return hits / total * 100 if total else 0.0


def _parse_coordinates(text: str) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for token in text.split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            lon, lat = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        result.append((lat, lon))
    return result


def _entry_observed_at(entry: dict[str, Any]) -> datetime | None:
    raw_date = str(entry.get("1_Date_of_Observatio") or "")
    raw_time = str(entry.get("2_Time_of_Observatio") or "00:00:00")
    try:
        return datetime.combine(
            datetime.strptime(raw_date, "%d/%m/%Y").date(),
            time.fromisoformat(raw_time),
            tzinfo=AST,
        ).astimezone(UTC)
    except ValueError:
        return _parse_datetime(entry.get("uploaded_at"), UTC)


def _pressure_level(score: int | None) -> str:
    if score is None:
        return "unknown"
    if score < 25:
        return "low"
    if score < 50:
        return "warning"
    if score < 80:
        return "medium"
    return "high"


def _legacy_level(score: int | None) -> str:
    if score is None:
        return "unknown"
    return "low" if score < 30 else "moderate" if score < 70 else "elevated"


def _parse_datetime(value: Any, default_tz: timezone) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif not value:
        return None
    else:
        text_value = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text_value)
        except ValueError:
            return None
    return (
        parsed.replace(tzinfo=default_tz).astimezone(UTC)
        if parsed.tzinfo is None
        else parsed.astimezone(UTC)
    )


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(AST).isoformat() if value else None


def _tag(value: str) -> str:
    return value.rsplit("}", 1)[-1]
