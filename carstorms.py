#!/usr/bin/env python3
# ----------------------------------------
# Script Name: carstorms.py
# Developer: drhdev
# Version: 0.5.1
# License: GPLv3
#
# Description:
# This script fetches active tropical storms and hurricanes from the NOAA National Hurricane Center /https://www.nhc.noaa.gov/),
# analyzes forecast track data, and determines if the configured locations may be affected.
# It loads settings and monitored locations from carstorms.config (JSON).
# ----------------------------------------

import json
import requests
import xml.etree.ElementTree as ET
from zipfile import ZipFile
from io import BytesIO
from geopy.distance import geodesic
from datetime import datetime, timedelta, timezone
import logging
import sys
import traceback

# ----------------------------------------
# Load configuration from JSON
# ----------------------------------------

def load_config(config_path="carstorms.config"):
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)

        alert_radius_km = int(config_data.get("alert_radius_km", 150))
        wind_threshold_kt = int(config_data.get("wind_threshold_kt", 60))
        locations = {}
        webhook_url = config_data.get("webhook_url")

        raw_locations = config_data.get("locations", {})
        if isinstance(raw_locations, dict):
            for name, coords in raw_locations.items():
                if isinstance(coords, list) and len(coords) == 2:
                    try:
                        lat, lon = float(coords[0]), float(coords[1])
                        locations[name.strip()] = (lat, lon)
                    except Exception:
                        logging.warning(f"Skipping invalid location '{name}' with coordinates: {coords}")
                else:
                    logging.warning(f"Skipping invalid format for location '{name}': {coords}")
        else:
            logging.warning("No valid 'locations' dictionary found in config.")

        logging.info(f"Loaded config: alert_radius_km={alert_radius_km}, wind_threshold_kt={wind_threshold_kt}, locations={locations}, webhook_url={webhook_url}")
        return alert_radius_km, wind_threshold_kt, locations, webhook_url

    except Exception as e:
        logging.error(f"Failed to load config: {e}")
        raise RuntimeError(f"Failed to load config: {e}")

# ----------------------------------------
# Load values from config
# ----------------------------------------

# ALERT_RADIUS_KM, WIND_THRESHOLD_KT, LOCATIONS = load_config()

LOG_FILE = "carstorms.log"
OUTPUT_JSON = "carstorms.json"
NHC_KMZ_URL = "https://www.nhc.noaa.gov/gis/kml/nhc.kmz"

CATEGORY_SCALE = [
    (252, "Category 5 of 5: Catastrophic – Most buildings destroyed, area uninhabitable."),
    (209, "Category 4 of 5: Very severe – Long power/water outages, major destruction."),
    (178, "Category 3 of 5: Severe – Widespread damage, long outages."),
    (154, "Category 2 of 5: Moderate – Large trees uprooted, major roof damage."),
    (119, "Category 1 of 5: Weak – Roof and tree damage, power outages likely."),
    (63,  "Tropical Storm – Strong wind, high seas, possible flooding.")
]

# ----------------------------------------
# Logging
# ----------------------------------------

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    filemode='w'
)

logger = logging.getLogger("carstorms")

# ----------------------------------------
# Helper Functions
# ----------------------------------------

def knots_to_kmh(knots):
    return round(knots * 1.852)

def classify_storm(wind_kmh):
    for threshold, description in CATEGORY_SCALE:
        if wind_kmh >= threshold:
            return description
    return "Below tropical storm threshold – not considered dangerous."

def fetch_active_storms_kml():
    try:
        response = requests.get(NHC_KMZ_URL, timeout=20)
        response.raise_for_status()
        kmz = ZipFile(BytesIO(response.content))
        kml_name = next((n for n in kmz.namelist() if n.endswith(".kml")), None)
        if not kml_name:
            raise ValueError("No .kml file found in KMZ.")
        kml_data = kmz.read(kml_name)
        return ET.fromstring(kml_data)
    except Exception as e:
        logger.error(f"Failed to fetch or parse KML: {e}")
        return None

def analyze_proximity(coords, times, locations, alert_radius_km):
    # Truncate coords and times to the shortest length to avoid mismatches
    min_len = min(len(coords), len(times))
    coords = coords[:min_len]
    times = times[:min_len]
    results = []
    for loc_name, loc_coords in locations.items():
        closest = None
        min_distance = float('inf')
        for (lon, lat), timestamp in zip(coords, times):
            dist = geodesic((lat, lon), loc_coords).km
            if dist < min_distance:
                min_distance = dist
                closest = (timestamp, dist)
        if closest and closest[1] <= alert_radius_km:
            local_time = (closest[0] - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M AST")
            results.append({
                "location": loc_name,
                "expected_impact_time": local_time,
                "distance_km": round(closest[1])
            })
    return results

# ----------------------------------------
# Main Execution
# ----------------------------------------

def main(config=None):
    if config is None:
        result = load_config()
        if len(result) == 4:
            alert_radius_km, wind_threshold_kt, locations, webhook_url = result
        else:
            alert_radius_km, wind_threshold_kt, locations = result
            webhook_url = None
    else:
        alert_radius_km = int(config.get("alert_radius_km", 150))
        wind_threshold_kt = int(config.get("wind_threshold_kt", 60))
        locations = config.get("locations", {})
        locations = {k: tuple(v) for k, v in locations.items()}
        webhook_url = config.get("webhook_url")
    logging.info(f"Script started with config: alert_radius_km={alert_radius_km}, wind_threshold_kt={wind_threshold_kt}, locations={locations}, webhook_url={webhook_url}")

    output = {
        "name": "carstorms.py",
        "description": "Checks active tropical storms and hurricanes from NOAA and evaluates whether defined locations may be affected. Includes forecast proximity, strength, and category explanations.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        "message": "No active dangerous storms near monitored locations.",
        "locations_monitored": list(locations.keys()),
        "alert_radius_km": alert_radius_km,
        "storms": []
    }

    kml_root = fetch_active_storms_kml()
    if not kml_root:
        output["status"] = "error"
        output["message"] = "Failed to fetch or parse active storm data."
        logging.error("Failed to fetch or parse active storm data.")
    else:
        ns = {'kml': 'http://www.opengis.net/kml/2.2'}
        placemarks = kml_root.findall('.//kml:Placemark', ns)
        logging.info(f"Found {len(placemarks)} placemarks (potential storms) in KML.")
        for placemark in placemarks:
            try:
                name_tag = placemark.find('kml:name', ns)
                if name_tag is None or not name_tag.text:
                    continue
                name = name_tag.text.strip()
                desc = placemark.find('kml:description', ns)
                description_text = desc.text if desc is not None else ""
                coord_text = placemark.find('.//kml:coordinates', ns)
                times = []
                time_span = placemark.find('.//kml:TimeSpan', ns)
                if time_span is not None:
                    begin = time_span.find('kml:begin', ns)
                    end = time_span.find('kml:end', ns)
                    if begin is not None and end is not None:
                        times = [
                            datetime.fromisoformat(begin.text.replace("Z", "+00:00")),
                            datetime.fromisoformat(end.text.replace("Z", "+00:00"))
                        ]
                else:
                    when_tags = placemark.findall('.//kml:when', ns)
                    if when_tags:
                        times = [datetime.fromisoformat(w.text.replace("Z", "+00:00")) for w in when_tags]
                try:
                    coord_strings = coord_text.text.strip().split()
                    coords = [tuple(map(float, c.split(',')[:2])) for c in coord_strings]
                    min_len = min(len(coords), len(times))
                    coords = coords[:min_len]
                    times = times[:min_len]
                except Exception as e:
                    logging.error(f"Error parsing coordinates/times for storm '{name}': {e}")
                    return
                wind_kt = None
                for line in description_text.splitlines():
                    if "Maximum sustained winds" in line:
                        try:
                            wind_kt = int(line.split()[3])
                            break
                        except Exception as e:
                            logging.warning(f"Failed to parse wind speed for storm '{name}': {e}")
                            continue
                if wind_kt is None or wind_kt < wind_threshold_kt:
                    logging.info(f"Skipping storm '{name}' with wind speed {wind_kt} (threshold: {wind_threshold_kt})")
                    continue
                wind_kmh = knots_to_kmh(wind_kt)
                category_text = classify_storm(wind_kmh)
                locations_result = analyze_proximity(coords, times, locations, alert_radius_km)
                logging.info(f"Storm '{name}': wind_kt={wind_kt}, wind_kmh={wind_kmh}, category='{category_text}', affected_locations={locations_result}")
                if locations and not locations_result:
                    logging.info(f"No monitored locations affected by storm '{name}'")
                    continue
                output["storms"].append({
                    "name": name,
                    "wind_kt": wind_kt,
                    "wind_kmh": wind_kmh,
                    "category_description": category_text,
                    "locations": locations_result
                })
                logging.info(f"Added storm '{name}' to output.")
            except Exception as e:
                logging.error(f"Error processing placemark: {e}")
                continue
        if output["storms"]:
            output["message"] = f"{len(output['storms'])} active dangerous storm(s) found."
    try:
        logging.info(f"Final output JSON: {json.dumps(output)}")
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)
        logger.info(f"Updated {OUTPUT_JSON} with {len(output['storms'])} active dangerous systems.")
        if webhook_url:
            try:
                logger.info(f"Posting output to webhook: {webhook_url}")
                logger.info(f"Payload: {json.dumps(output)}")
                resp = requests.post(webhook_url, json=output, timeout=10)
                logger.info(f"Webhook response status: {resp.status_code}")
                logger.info(f"Webhook response text: {resp.text}")
            except Exception as e:
                logger.error(f"Failed to POST to webhook: {e}")
    except Exception as e:
        logger.error(f"Failed to write output JSON: {e}")

if __name__ == "__main__":
    main()