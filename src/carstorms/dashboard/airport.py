"""Independent STT airport disruption and terminal-crowd forecast.

The model deliberately keeps observed facts (flight delays and FAA traffic
management events) separate from estimates (weather risk and passenger-arrival
pressure).  That distinction is part of the public API contract: consumers can
show a useful forecast without presenting modeled TSA pressure as a live wait
time.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta, timezone
from math import radians, sin
from typing import Any

AST = timezone(timedelta(hours=-4))

FAA_NAS_URL = "https://nasstatus.faa.gov/"
AVIATION_WEATHER_URL = "https://aviationweather.gov/"
FLIGHTAWARE_URL = "https://www.flightaware.com/commercial/aeroapi"

# Typical seats, not airline-specific cabin layouts.  The response documents
# every estimate so this table can be calibrated without changing the API.
_AIRCRAFT_SEATS = {
    "A319": 138,
    "A320": 162,
    "A20N": 186,
    "A321": 190,
    "A21N": 200,
    "B737": 150,
    "B738": 175,
    "B38M": 178,
    "B739": 179,
    "B39M": 181,
    "B752": 200,
    "BCS1": 109,
    "BCS3": 140,
    "CRJ7": 70,
    "CRJ9": 76,
    "E170": 70,
    "E175": 76,
    "AT43": 46,
    "AT45": 48,
    "AT72": 70,
    "C208": 9,
    "C402": 9,
    "BN2P": 9,
    "PC12": 9,
}

_SMALL_OPERATORS = {"KAP", "GPD", "VTE", "MWI", "SNC"}
_REGIONAL_DESTINATIONS = {
    "SJU",
    "STX",
    "EIS",
    "SBH",
    "AXA",
    "NEV",
    "SKB",
    "ANU",
    "DOM",
}

# Direct STT gateways used only when live flight data is unavailable.  This is
# intentionally a conservative network signal, not a claimed route schedule.
_STT_GATEWAY_WEIGHTS = {
    "SJU": 1.0,
    "MIA": 1.0,
    "ATL": 0.9,
    "CLT": 0.9,
    "JFK": 0.7,
    "EWR": 0.7,
    "MCO": 0.6,
    "FLL": 0.5,
    "IAD": 0.4,
    "IAH": 0.4,
    "BWI": 0.4,
}


def build_airport_panel(
    metar: Any,
    taf: Any,
    faa_nas: Any,
    flight_data: Any,
    now: datetime,
    *,
    airport_icao: str = "TIST",
    airport_iata: str = "STT",
    airport_name: str = "Cyril E. King Airport (STT)",
    load_factor: float = 0.85,
) -> dict[str, Any]:
    """Build the stable ``/api/airport.json`` payload."""

    now = _aware(now)
    metar_row = metar[0] if isinstance(metar, list) and metar else {}
    taf_row = taf[0] if isinstance(taf, list) and taf else {}
    weather = _weather_assessment(metar_row, taf_row, now)
    flights = _normalise_flights(flight_data, now, load_factor)
    faa = _faa_assessment(faa_nas, flights)
    crowd = _crowd_forecast(flights, now)
    operations = _operations_assessment(flights)
    operations["fetched_at"] = (
        flight_data.get("fetched_at") if isinstance(flight_data, dict) else None
    )
    operations["stale"] = bool(flight_data.get("stale")) if isinstance(flight_data, dict) else False

    components: dict[str, int] = {
        "weather": weather["score"],
        "faa_airspace": faa["score"],
    }
    if operations["available"]:
        components["live_operations"] = operations["score"]
        components["terminal_pressure"] = crowd["score"]
        score = round(
            operations["score"] * 0.35
            + faa["score"] * 0.25
            + weather["score"] * 0.25
            + crowd["score"] * 0.15
        )
    else:
        score = round(weather["score"] * 0.55 + faa["score"] * 0.45)

    # Direct safety/operations signals must not be diluted by calm conditions.
    if faa["local_severity"] >= 95:
        score = max(score, 95)
    if weather["score"] >= 80:
        score = max(score, 70)
    score = max(0, min(100, score))

    source_count = sum(
        (
            weather["metar_available"],
            weather["taf_available"],
            faa["available"],
            operations["available"],
        )
    )
    if operations["available"] and source_count >= 4 and not operations["stale"]:
        confidence = "high"
    elif operations["available"] and source_count >= 3:
        confidence = "medium"
    elif weather["metar_available"] or weather["taf_available"] or faa["available"]:
        confidence = "limited"
    else:
        confidence = "low"

    reasons = _ranked_reasons(weather, faa, operations, crowd)
    available = bool(source_count)
    return {
        "available": available,
        "model_version": "stt-airport-v1",
        "airport": {"iata": airport_iata, "icao": airport_icao, "name": airport_name},
        "generated_at": _iso(now),
        "risk": {
            "score": score if available else None,
            "label": _risk_label(score) if available else "unknown",
            "confidence": confidence,
            "components": components,
            "reasons": reasons,
        },
        "operations": operations,
        "crowd": crowd,
        "weather": weather,
        "faa": faa,
        "next_flights": flights[:12],
        "methodology": {
            "summary": (
                "35% live flight performance, 25% FAA airspace restrictions, 25% METAR/TAF "
                "weather and 15% modeled terminal pressure. Without licensed flight data, "
                "the score uses FAA and weather only and confidence is reduced."
            ),
            "crowd_model": (
                "Estimated seats times configured load factor, distributed from four to one hours "
                "before departure with the peak two hours before. Small regional flights receive "
                "half weight. This is not a live TSA wait time."
            ),
            "thresholds": {
                "risk": {
                    "low": "0-19",
                    "guarded": "20-39",
                    "elevated": "40-59",
                    "high": "60-79",
                    "severe": "80-100",
                },
                "crowd_passengers_per_30_min": {
                    "low": "<75",
                    "moderate": "75-149",
                    "high": "150-249",
                    "severe": "250+",
                },
                "delayed_flight": "15 minutes or more",
            },
            "load_factor": round(load_factor, 2),
        },
        "sources": [
            {
                "name": "FAA NAS Status",
                "url": FAA_NAS_URL,
                "available": faa["available"],
                "role": "Official current traffic-management events and operations plan",
            },
            {
                "name": "NWS Aviation Weather",
                "url": AVIATION_WEATHER_URL,
                "available": weather["metar_available"] or weather["taf_available"],
                "role": "Official METAR observation and TAF forecast for TIST",
            },
            {
                "name": "FlightAware AeroAPI",
                "url": FLIGHTAWARE_URL,
                "available": operations["available"],
                "role": "Licensed schedules and live flight status; optional",
            },
        ],
    }


def _weather_assessment(
    metar: dict[str, Any], taf: dict[str, Any], now: datetime
) -> dict[str, Any]:
    category = str(metar.get("fltCat") or "").upper()
    category_score = {"VFR": 5, "MVFR": 30, "IFR": 60, "LIFR": 85}.get(category, 0)
    wind = _number(metar.get("wspd")) or 0
    gust = _number(metar.get("wgst")) or 0
    wind_direction = _number(metar.get("wdir"))
    raw = str(metar.get("rawOb") or "").upper()
    observed_score = category_score
    if "TS" in raw:
        observed_score = max(observed_score, 80)
    if gust >= 30:
        observed_score = max(observed_score, 60)
    elif gust >= 24 or wind >= 22:
        observed_score = max(observed_score, 40)
    observed_crosswind = _crosswind_component(wind_direction, max(wind, gust))
    if observed_crosswind >= 25:
        observed_score = max(observed_score, 75)
    elif observed_crosswind >= 18:
        observed_score = max(observed_score, 50)
    elif observed_crosswind >= 12:
        observed_score = max(observed_score, 25)

    forecast_periods: list[dict[str, Any]] = []
    worst_forecast = 0
    for period in taf.get("fcsts", []) if isinstance(taf.get("fcsts"), list) else []:
        if not isinstance(period, dict):
            continue
        end = _from_epoch(period.get("timeTo"))
        if end and end < now:
            continue
        risk, factors = _taf_period_risk(period)
        worst_forecast = max(worst_forecast, risk)
        forecast_periods.append(
            {
                "from": _iso(_from_epoch(period.get("timeFrom"))),
                "to": _iso(end),
                "risk_score": risk,
                "factors": factors,
                "wind_kt": _number(period.get("wspd")),
                "gust_kt": _number(period.get("wgst")),
                "visibility_sm": _visibility(period.get("visib")),
                "weather": period.get("wxString"),
            }
        )

    forecast_score = worst_forecast if worst_forecast >= 80 else round(worst_forecast * 0.9)
    score = max(observed_score, forecast_score)
    obs_time = _from_epoch(metar.get("obsTime"))
    return {
        "score": min(100, score),
        "flight_category": category or None,
        "crosswind_component_kt": round(observed_crosswind, 1),
        "metar": metar.get("rawOb"),
        "metar_observed_at": _iso(obs_time),
        "metar_available": bool(metar),
        "taf": taf.get("rawTAF"),
        "taf_issued_at": _iso(_parse_dt(taf.get("issueTime"))),
        "taf_available": bool(taf),
        "forecast_periods": forecast_periods,
    }


def _taf_period_risk(period: dict[str, Any]) -> tuple[int, list[str]]:
    score = 5
    factors: list[str] = []
    wx = str(period.get("wxString") or "").upper()
    visibility = _visibility(period.get("visib"))
    wind = _number(period.get("wspd")) or 0
    gust = _number(period.get("wgst")) or 0
    direction = _number(period.get("wdir"))
    ceiling = _ceiling(period.get("clouds"))

    if "TS" in wx or "FC" in wx:
        score = max(score, 85)
        factors.append("thunderstorm risk")
    elif any(token in wx for token in ("+RA", "SQ", "SHRA")):
        score = max(score, 50)
        factors.append("heavy showers/squalls")
    elif "RA" in wx or "SH" in wx:
        score = max(score, 25)
        factors.append("showers")
    if visibility is not None:
        if visibility < 1:
            score = max(score, 90)
            factors.append("visibility below 1 mile")
        elif visibility < 3:
            score = max(score, 65)
            factors.append("visibility below 3 miles")
        elif visibility < 5:
            score = max(score, 35)
            factors.append("reduced visibility")
    if ceiling is not None:
        if ceiling < 500:
            score = max(score, 90)
            factors.append("ceiling below 500 ft")
        elif ceiling < 1000:
            score = max(score, 65)
            factors.append("ceiling below 1,000 ft")
        elif ceiling < 3000:
            score = max(score, 30)
            factors.append("low cloud ceiling")
    if gust >= 35:
        score = max(score, 75)
        factors.append(f"gusts {round(gust)} kt")
    elif gust >= 25 or wind >= 22:
        score = max(score, 45)
        factors.append(f"winds up to {round(max(gust, wind))} kt")
    crosswind = _crosswind_component(direction, max(wind, gust))
    if crosswind >= 25:
        score = max(score, 75)
        factors.append(f"crosswind component about {round(crosswind)} kt")
    elif crosswind >= 18:
        score = max(score, 50)
        factors.append(f"crosswind component about {round(crosswind)} kt")
    return score, factors or ["routine conditions"]


def _faa_assessment(data: Any, flights: list[dict[str, Any]]) -> dict[str, Any]:
    events = data.get("events", []) if isinstance(data, dict) else []
    plan = data.get("operations_plan", {}) if isinstance(data, dict) else {}
    if not isinstance(events, list):
        events = []

    route_weights: dict[str, float] = defaultdict(float)
    for flight in flights:
        airport = flight.get("other_airport")
        if airport:
            route_weights[str(airport)] += max(1.0, float(flight.get("estimated_passengers") or 1))
    if not route_weights:
        route_weights.update(_STT_GATEWAY_WEIGHTS)

    local_events: list[dict[str, Any]] = []
    network_events: list[dict[str, Any]] = []
    local_severity = 0
    weighted_network = 0.0
    total_route_weight = sum(route_weights.values()) or 1.0
    for row in events:
        if not isinstance(row, dict):
            continue
        code = str(row.get("airportId") or "").upper()
        severity, kind, detail = _faa_event(row)
        if not severity:
            continue
        item = {"airport": code, "type": kind, "severity": severity, "detail": detail}
        if code == "STT":
            local_events.append(item)
            local_severity = max(local_severity, severity)
        elif code in route_weights:
            network_events.append(item)
            weighted_network += severity * route_weights[code] / total_route_weight

    planned = _planned_gateway_events(plan, set(route_weights))
    if planned:
        weighted_network = max(weighted_network, max(p["severity"] for p in planned) * 0.45)
    score = max(local_severity, min(100, round(weighted_network)))
    return {
        "available": isinstance(data, dict) and ("events" in data or "operations_plan" in data),
        "score": score,
        "local_severity": local_severity,
        "local_events": local_events,
        "network_events": sorted(network_events, key=lambda e: e["severity"], reverse=True)[:8],
        "planned_network_events": planned[:8],
        "checked_at": data.get("fetched_at") if isinstance(data, dict) else None,
    }


def _faa_event(row: dict[str, Any]) -> tuple[int, str | None, str | None]:
    candidates = (
        ("airportClosure", 100, "airport closure"),
        ("groundStop", 95, "ground stop"),
        ("groundDelay", 80, "ground delay program"),
        ("arrivalDelay", 65, "arrival delays"),
        ("departureDelay", 65, "departure delays"),
    )
    for key, severity, label in candidates:
        event = row.get(key)
        if isinstance(event, dict):
            reason = event.get("impactingCondition") or event.get("text")
            avg = _number(event.get("avgDelay"))
            detail = label + (f" · {reason}" if reason else "")
            if avg:
                detail += f" · average {round(avg)} min"
            return severity, label, detail
    return 0, None, None


def _planned_gateway_events(plan: Any, gateways: set[str]) -> list[dict[str, Any]]:
    if not isinstance(plan, dict):
        return []
    rows = plan.get("terminalPlanned", [])
    result: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        text = f"{row.get('time', '')} {row.get('event', '')}".upper()
        matches = sorted(code for code in gateways if code in text)
        if not matches:
            continue
        severity = 55 if "GROUND STOP" in text else 45 if "DELAY PROGRAM" in text else 30
        result.append({"airports": matches, "severity": severity, "detail": " ".join(text.split())})
    return result


def _normalise_flights(data: Any, now: datetime, load_factor: float) -> list[dict[str, Any]]:
    if not isinstance(data, dict) or not data.get("enabled", False):
        return []
    payload = data.get("data")
    if not isinstance(payload, dict):
        return []

    groups = (
        ("departures", "departure"),
        ("scheduled_departures", "departure"),
        ("arrivals", "arrival"),
        ("scheduled_arrivals", "arrival"),
    )
    records: dict[str, dict[str, Any]] = {}
    for key, direction in groups:
        rows = payload.get(key, [])
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            item = _normalise_flight(row, direction, load_factor)
            if item is None:
                continue
            scheduled = _parse_dt(item["scheduled_at"])
            if scheduled and not now - timedelta(hours=3) <= scheduled <= now + timedelta(hours=30):
                continue
            flight_id = str(
                row.get("fa_flight_id") or f"{direction}:{item['ident']}:{item['scheduled_at']}"
            )
            previous = records.get(flight_id)
            if previous is None or _flight_completeness(item) > _flight_completeness(previous):
                records[flight_id] = item
    return sorted(records.values(), key=lambda f: f.get("scheduled_at") or "")


def _normalise_flight(
    row: dict[str, Any], direction: str, load_factor: float
) -> dict[str, Any] | None:
    suffix = "out" if direction == "departure" else "in"
    scheduled = _parse_dt(row.get(f"scheduled_{suffix}"))
    if scheduled is None:
        return None
    estimated = _parse_dt(row.get(f"estimated_{suffix}"))
    actual = _parse_dt(row.get(f"actual_{suffix}"))
    comparison = actual or estimated
    delay = max(0, round((comparison - scheduled).total_seconds() / 60)) if comparison else None
    cancelled = bool(row.get("cancelled"))
    operator = str(row.get("operator") or "").upper()
    aircraft = str(row.get("aircraft_type") or "").upper()
    seats, seat_source = _seat_estimate(aircraft, operator)
    passengers = round(seats * load_factor) if seats else 0
    other = row.get("destination" if direction == "departure" else "origin")
    if isinstance(other, dict):
        other_code = other.get("code_iata") or other.get("code") or other.get("code_icao")
        other_name = other.get("city") or other.get("name")
    else:
        other_code = None
        other_name = None
    return {
        "id": row.get("fa_flight_id"),
        "ident": row.get("ident_iata") or row.get("ident") or "Unknown",
        "direction": direction,
        "scheduled_at": _iso(scheduled),
        "estimated_at": _iso(estimated),
        "actual_at": _iso(actual),
        "delay_minutes": delay,
        "delayed": delay is not None and delay >= 15,
        "cancelled": cancelled,
        "diverted": bool(row.get("diverted")),
        "status": row.get("status"),
        "other_airport": str(other_code).upper() if other_code else None,
        "other_airport_name": other_name,
        "aircraft_type": aircraft or None,
        "estimated_seats": seats,
        "seat_estimate_source": seat_source,
        "estimated_passengers": passengers,
    }


def _operations_assessment(flights: list[dict[str, Any]]) -> dict[str, Any]:
    if not flights:
        return {
            "available": False,
            "score": 0,
            "total_flights": 0,
            "known_delay_flights": 0,
            "delayed_flights": 0,
            "cancelled_flights": 0,
            "average_delay_minutes": None,
            "delay_rate_pct": None,
            "provider": None,
        }
    known = [f for f in flights if f["delay_minutes"] is not None and not f["cancelled"]]
    delayed = [f for f in known if f["delayed"]]
    cancelled = [f for f in flights if f["cancelled"]]
    avg = round(sum(f["delay_minutes"] for f in known) / len(known)) if known else None
    delay_rate = round(len(delayed) / len(known) * 100) if known else None
    cancelled_rate = len(cancelled) / len(flights)
    live_score = (
        (len(delayed) / len(known) * 55 if known else 0)
        + (min(avg or 0, 90) / 90 * 25)
        + min(20, cancelled_rate * 100)
    )
    return {
        "available": True,
        "score": min(100, round(live_score)),
        "total_flights": len(flights),
        "known_delay_flights": len(known),
        "delayed_flights": len(delayed),
        "cancelled_flights": len(cancelled),
        "average_delay_minutes": avg,
        "delay_rate_pct": delay_rate,
        "provider": "FlightAware AeroAPI",
    }


def _crowd_forecast(flights: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    departures = [f for f in flights if f["direction"] == "departure" and not f["cancelled"]]
    if not departures:
        return {"available": False, "score": 0, "peak": None, "buckets": []}
    start = now.astimezone(AST).replace(
        minute=(now.astimezone(AST).minute // 30) * 30, second=0, microsecond=0
    )
    end = start + timedelta(hours=12)
    buckets: dict[datetime, float] = defaultdict(float)
    # Passenger-arrival distribution: 4h, 3.5h, 3h, 2.5h, 2h, 1.5h, 1h.
    weights = (0.04, 0.08, 0.13, 0.18, 0.27, 0.19, 0.11)
    for flight in departures:
        departure = _parse_dt(flight["scheduled_at"])
        if departure is None:
            continue
        passengers = float(flight.get("estimated_passengers") or 0)
        if flight.get("other_airport") in _REGIONAL_DESTINATIONS:
            passengers *= 0.5
        for index, weight in enumerate(weights):
            arrival = departure - timedelta(hours=4 - index * 0.5)
            arrival = arrival.astimezone(AST).replace(
                minute=(arrival.minute // 30) * 30, second=0, microsecond=0
            )
            if start <= arrival <= end:
                buckets[arrival] += passengers * weight
    rows: list[dict[str, Any]] = [
        {
            "time": _iso(moment),
            "estimated_passengers": round(value),
            "level": _crowd_label(value),
        }
        for moment, value in sorted(buckets.items())
    ]
    peak = max(rows, key=lambda row: row["estimated_passengers"], default=None)
    peak_value = int(peak["estimated_passengers"]) if peak else 0
    return {
        "available": True,
        "score": min(100, round(peak_value / 2.5)),
        "peak": peak,
        "buckets": rows,
        "window_hours": 12,
        "is_live_wait_time": False,
    }


def _ranked_reasons(
    weather: dict[str, Any], faa: dict[str, Any], operations: dict[str, Any], crowd: dict[str, Any]
) -> list[str]:
    reasons: list[tuple[int, str]] = []
    if faa["local_events"]:
        reasons.append((100, faa["local_events"][0]["detail"]))
    elif faa["network_events"]:
        event = faa["network_events"][0]
        reasons.append(
            (
                event["severity"],
                f"FAA restriction at connection airport {event['airport']}: {event['detail']}",
            )
        )
    if operations["available"]:
        if operations["cancelled_flights"]:
            reasons.append(
                (
                    90,
                    f"{operations['cancelled_flights']} cancellation(s) in the current flight window",
                )
            )
        if operations["delayed_flights"]:
            reasons.append((70, f"{operations['delayed_flights']} flight(s) delayed 15+ minutes"))
    if weather["score"] >= 40:
        reasons.append(
            (weather["score"], "TIST observation/forecast indicates operational weather risk")
        )
    if crowd.get("peak") and crowd["peak"]["level"] in {"high", "severe"}:
        reasons.append(
            (
                50,
                f"Modeled terminal pressure peaks {crowd['peak']['level']} at {_clock(crowd['peak']['time'])}",
            )
        )
    if not reasons:
        reasons.append((0, "No material disruption signal in currently available sources"))
    return [text for _, text in sorted(reasons, key=lambda item: item[0], reverse=True)[:4]]


def _seat_estimate(aircraft: str, operator: str) -> tuple[int, str]:
    if aircraft in _AIRCRAFT_SEATS:
        return _AIRCRAFT_SEATS[aircraft], "aircraft-type lookup"
    if operator in _SMALL_OPERATORS:
        return 9, "regional-operator fallback"
    if operator:
        return 160, "mainline fallback"
    return 0, "unavailable"


def _crosswind_component(direction: float | None, speed: float) -> float:
    """Return crosswind against TIST's single 10/28 runway axis."""
    if direction is None or speed <= 0:
        return 0.0
    difference = abs((direction - 100 + 180) % 360 - 180)
    difference = min(difference, 180 - difference)
    return abs(speed * sin(radians(difference)))


def _flight_completeness(item: dict[str, Any]) -> int:
    return sum(
        item.get(key) is not None
        for key in ("estimated_at", "actual_at", "delay_minutes", "aircraft_type")
    )


def _risk_label(score: int) -> str:
    if score < 20:
        return "low"
    if score < 40:
        return "guarded"
    if score < 60:
        return "elevated"
    if score < 80:
        return "high"
    return "severe"


def _crowd_label(passengers: float) -> str:
    if passengers < 75:
        return "low"
    if passengers < 150:
        return "moderate"
    if passengers < 250:
        return "high"
    return "severe"


def _ceiling(clouds: Any) -> float | None:
    if not isinstance(clouds, list):
        return None
    bases = [
        _number(cloud.get("base"))
        for cloud in clouds
        if isinstance(cloud, dict) and str(cloud.get("cover") or "").upper() in {"BKN", "OVC", "VV"}
    ]
    values = [base for base in bases if base is not None]
    return min(values) if values else None


def _visibility(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace("P", "").replace("+", "")
    try:
        return float(text)
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def _from_epoch(value: Any) -> datetime | None:
    number = _number(value)
    return datetime.fromtimestamp(number, tz=UTC) if number is not None else None


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _aware(value)
    if not value:
        return None
    if isinstance(value, (int, float)):
        return _from_epoch(value)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return _aware(parsed)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(AST).isoformat() if value else None


def _clock(value: Any) -> str:
    dt = _parse_dt(value)
    return dt.astimezone(AST).strftime("%-I:%M %p") if dt else "unknown time"
