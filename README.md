# carstorms

A python script to get data about tropical storms and hurricanes from NHC on storms in the Caribbean.

## 🌪️ Overview

`carstorms.py` is a lightweight Python script that fetches and analyzes active tropical storms and hurricanes from the [NOAA National Hurricane Center (NHC)](https://www.nhc.noaa.gov/). It checks if any dangerous systems may affect user-defined locations (e.g., St. John USVI or St. Barths), calculates the closest approach time, and classifies the storm's severity.

This tool is designed for:
- small VPS servers (1 GB RAM, 1 CPU)
- integration into monitoring workflows
- generating a structured `carstorms.json` output file
- use as a backend data source for dashboards, APIs, or alerts

## 📦 Features

- Parses NOAA's live `nhc.kmz` feed
- Filters storms based on wind threshold and proximity
- Outputs detailed storm info (wind, category, explanation, distance)
- Supports global mode (no location filtering)
- Uses a simple, editable JSON configuration file
- Writes structured JSON and rotating logs
- Resource-efficient and fast

## 📁 Output

The script generates:
- `carstorms.json` – JSON file with storm information
- `carstorms.log` – log file with warnings, fetch events, and errors

Example `carstorms.json` output:

```json
{
  "name": "carstorms.py",
  "timestamp": "2025-04-14T20:15:00+00:00",
  "status": "ok",
  "message": "1 active dangerous storm(s) found.",
  "locations_monitored": ["St. John (USVI)", "St. Barths"],
  "alert_radius_km": 150,
  "storms": [
    {
      "name": "Hurricane Tammy",
      "wind_kt": 80,
      "wind_kmh": 148,
      "category_description": "Category 1 of 5: Weak – Roof and tree damage, power outages likely.",
      "locations": [
        {
          "location": "St. Barths",
          "closest_time": "2025-04-15 02:00 AST",
          "distance_km": 108
        }
      ]
    }
  ]
}
```

---

## 🛠️ Installation

### Requirements

- Python 3.7+
- Packages:
  - `requests`
  - `geopy`

You can install requirements via pip:

```bash
pip install requests geopy
```

### Clone the repository

```bash
git clone https://github.com/yourusername/carstorms.git
cd carstorms
```

---

## ⚙️ Configuration

All settings are defined in a single JSON file: `carstorms.config`

Example:

```json
{
  "alert_radius_km": 150,
  "wind_threshold_kt": 60,
  "locations": {
    "St. John (USVI)": [18.33, -64.73],
    "St. Barths": [17.9, -62.83]
  }
}
```

### 🌍 Global mode

To track **all active systems globally**, remove or leave `"locations"` empty:

```json
"locations": {}
```

---

## 🚀 Usage

Run manually:

```bash
python3 carstorms.py
```

This updates:
- `carstorms.json`
- `carstorms.log`

---

## 🔄 Automate it

You can set up a cronjob or systemd timer to run this script periodically (e.g., hourly).  
For example:

```bash
0 * * * * /usr/bin/python3 /path/to/carstorms.py
```

---

## 📄 License

[GPLv3](https://www.gnu.org/licenses/gpl-3.0.html) – Free as in freedom.
"""
