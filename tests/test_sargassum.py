"""NOAA SIR beach matching and Sargassum fusion tests."""

from __future__ import annotations

import io
import struct
import zlib
from datetime import UTC, date, datetime
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import respx

from carstorms.dashboard.sargassum import (
    NOAA_SIR_KMZ,
    SARGASSUM_WATCH_API,
    _decode_transparent_png,
    build_sargassum_panel,
    fetch_noaa_sir,
    fetch_sargassum_watch,
    parse_noaa_sir_kmz,
)

NOW = datetime(2026, 6, 28, 16, tzinfo=UTC)


def _kmz(risk: int = 3) -> bytes:
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark>
      <ExtendedData><SchemaData><SimpleData name="risk">{risk}</SimpleData>
      <SimpleData name="date">2026-06-28</SimpleData></SchemaData></ExtendedData>
      <LineString><coordinates>-64.7640,18.3535,0 -64.7630,18.3535,0</coordinates></LineString>
    </Placemark></Document></kml>"""
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("sir.kml", kml)
    return output.getvalue()


def _png(indices: list[list[int]], alpha: bytes = bytes([255, 0])) -> bytes:
    height, width = len(indices), len(indices[0])

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + bytes(row) for row in indices)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0))
        + chunk(b"PLTE", b"\xff\x00\x00\x00\x00\x00")
        + chunk(b"tRNS", alpha)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def test_noaa_kmz_matches_trunk_bay_and_maps_risk_score() -> None:
    result = parse_noaa_sir_kmz(
        _kmz(), product_date=date(2026, 6, 28), source_url="https://example.test/sir.kmz"
    )

    trunk = next(beach for beach in result["beaches"] if beach["id"] == "trunk")
    assert trunk["matched"] is True
    assert trunk["noaa_level"] == "high"
    assert trunk["base_score"] == 90
    assert trunk["distance_to_segment_km"] < 0.1


async def test_noaa_fetch_checks_today_then_previous_dates() -> None:
    today = NOAA_SIR_KMZ.format(day="20260628")
    yesterday = NOAA_SIR_KMZ.format(day="20260627")
    with respx.mock(assert_all_called=False) as mock:
        first = mock.get(today).mock(return_value=httpx.Response(404))
        second = mock.get(yesterday).mock(return_value=httpx.Response(200, content=_kmz(2)))
        async with httpx.AsyncClient() as client:
            result = await fetch_noaa_sir(client, NOW)

    assert first.called and second.called
    assert result is not None
    assert result["product_date"] == "2026-06-27"


def test_indexed_png_decoder_preserves_transparency() -> None:
    image = _decode_transparent_png(_png([[0, 1], [1, 0]]))

    assert image["width"] == 2
    assert image["height"] == 2
    assert image["rows"] == [bytes([0, 1]), bytes([1, 0])]
    assert image["alpha"] == bytes([255, 0])


def test_panel_applies_caricoos_cap_and_fresh_observation_override() -> None:
    sir = {
        "available": True,
        "product_date": "2026-06-28",
        "source_url": "https://example.test/sir.kmz",
        "beaches": [
            {
                "id": "trunk",
                "name": "Trunk Bay",
                "matched": True,
                "base_score": 65,
                "noaa_level": "medium",
            },
            {
                "id": "maho",
                "name": "Maho Bay",
                "matched": True,
                "base_score": 35,
                "noaa_level": "warning",
            },
        ],
    }
    caricoos = {
        "available": True,
        "run_at": NOW.isoformat(),
        "future_valid_at": "2026-06-30T12:00:00Z",
        "beaches": {
            "trunk": {"adjustment": 15, "trend": "increasing"},
            "maho": {"adjustment": -15, "trend": "decreasing"},
        },
    }
    watch = {
        "available": True,
        "observations": [
            {
                "beach_id": "maho",
                "beach_name": "Maho Bay",
                "observed_at": NOW.isoformat(),
                "no_sargassum": True,
                "condition": "No Sargassum Present",
            }
        ],
    }

    panel = build_sargassum_panel(
        {"sir": sir, "caricoos": caricoos, "watch": watch, "afai": None}, NOW
    )

    trunk = next(beach for beach in panel["beaches"] if beach["id"] == "trunk")
    maho = next(beach for beach in panel["beaches"] if beach["id"] == "maho")
    assert trunk["score"] == 80
    assert trunk["risk_level"] == "high"
    assert maho["score"] == 10
    assert maho["confidence"] == "Observed"
    assert panel["confidence"] == "High-confidence estimate"
    assert panel["source"] == "NOAA SIR"


async def test_recent_sargassum_watch_report_matches_nearest_beach() -> None:
    response = {
        "data": {
            "entries": [
                {
                    "uploaded_at": "2026-06-28T15:01:00Z",
                    "1_Date_of_Observatio": "28/06/2026",
                    "2_Time_of_Observatio": "11:00:00",
                    "3_GPS_Coordinates_of": {"latitude": 18.3535, "longitude": -64.7635},
                    "4_Site_Name_eg_Miami": "Trunk Bay",
                    "7_Photo_of_the_site_": "https://five.epicollect.net/photo.jpg",
                    "12_Condition_of_the_": "Mostly Fresh (Yellow) Specimens",
                }
            ]
        }
    }
    with respx.mock(assert_all_called=True) as mock:
        mock.get(SARGASSUM_WATCH_API).mock(return_value=httpx.Response(200, json=response))
        async with httpx.AsyncClient() as client:
            result = await fetch_sargassum_watch(client, NOW)

    observation = result["observations"][0]
    assert observation["beach_id"] == "trunk"
    assert observation["age_hours"] == 1.0
    assert observation["photos"]
