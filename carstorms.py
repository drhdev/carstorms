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

        return alert_radius_km, wind_threshold_kt, locations

    except Exception as e:
        raise RuntimeError(f"Failed to load config: {e}")

# ----------------------------------------
# Load values from config
# ----------------------------------------

ALERT_RADIUS_KM, WIND_THRESHOLD_KT, LOCATIONS = load_config()

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
    datefmt="%Y-%m-%d %H:%M:%S"
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

def analyze_proximity(coords, times):
    results = []
    for loc_name, loc_coords in LOCATIONS.items():
        closest = None
        min_distance = float('inf')
        for (lon, lat), timestamp in zip(coords, times):
            dist = geodesic((lat, lon), loc_coords).km
            if dist < min_distance:
                min_distance = dist
                closest = (timestamp, dist)
        if closest and closest[1] <= ALERT_RADIUS_KM:
            local_time = (closest[0] - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M AST")
            results.append({
                "location": loc_name,
                "closest_time": local_time,
                "distance_km": round(closest[1])
            })
    return results

# ----------------------------------------
# Main Execution
# ----------------------------------------

def main():
    output = {
        "name": "carstorms.py",
        "description": "Checks active tropical storms and hurricanes from NOAA and evaluates whether defined locations may be affected. Includes forecast proximity, strength, and category explanations.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        "message": "No active dangerous storms near monitored locations.",
        "locations_monitored": list(LOCATIONS.keys()),
        "alert_radius_km": ALERT_RADIUS_KM,
        "storms": []
    }

    kml_root = fetch_active_storms_kml()
    if not kml_root:
        output["status"] = "error"
        output["message"] = "Failed to fetch or parse active storm data."
    else:
        ns = {'kml': 'http://www.opengis.net/kml/2.2'}
        for placemark in kml_root.findall('.//kml:Placemark', ns):
            try:
                name_tag = placemark.find('kml:name', ns)
                if name_tag is None or not name_tag.text:
                    continue

                name = name_tag.text.strip()
                desc = placemark.find('kml:description', ns)
                description_text = desc.text if desc is not None else ""
                coord_text = placemark.find('.//kml:coordinates', ns)
                when_tags = placemark.findall('.//kml:when', ns)

                if not coord_text or not when_tags:
                    continue

                coords = [tuple(map(float, c.split(',')[:2])) for c in coord_text.text.strip().split()]
                times = [datetime.fromisoformat(w.text.replace("Z", "+00:00")) for w in when_tags]

                wind_kt = None
                for line in description_text.splitlines():
                    if "Maximum sustained winds" in line:
                        try:
                            wind_kt = int(line.split()[3])
                            break
                        except Exception:
                            continue

                if wind_kt is None or wind_kt < WIND_THRESHOLD_KT:
                    continue

                wind_kmh = knots_to_kmh(wind_kt)
                category_text = classify_storm(wind_kmh)
                locations = analyze_proximity(coords, times)

                if LOCATIONS and not locations:
                    continue

                output["storms"].append({
                    "name": name,
                    "wind_kt": wind_kt,
                    "wind_kmh": wind_kmh,
                    "category_description": category_text,
                    "locations": locations
                })

            except Exception as e:
                logger.error(f"Error processing placemark: {e}")
                continue

        if output["storms"]:
            output["message"] = f"{len(output['storms'])} active dangerous storm(s) found."

    try:
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)
        logger.info(f"Updated {OUTPUT_JSON} with {len(output['storms'])} active dangerous systems.")
    except Exception as e:
        logger.error(f"Failed to write output JSON: {e}")

if __name__ == "__main__":
    main()