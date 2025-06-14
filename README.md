# carstorms

A python script to get data about tropical storms and hurricanes from NHC on storms in the Caribbean.

## 🌪️ Overview

`carstorms.py` is a lightweight Python script that fetches and analyzes active tropical storms and hurricanes from the [NOAA National Hurricane Center (NHC)](https://www.nhc.noaa.gov/). It checks if any dangerous systems may affect user-defined locations (e.g., St. John USVI or St. Barths), calculates the closest approach time, and classifies the storm's severity.

This tool is designed for:
- small VPS servers 
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
- requirements.txt

You can install requirements via pip:

```bash
pip install requirements.txt
```

### Clone the repository

```bash
git clone https://github.com/drhdev/carstorms.git
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
  },
  "webhook_url": "https://your-n8n-webhook-url"
}
```

- `alert_radius_km`: Alert radius in kilometers for proximity checks.
- `wind_threshold_kt`: Minimum wind speed (knots) to consider a storm dangerous.
- `locations`: Dictionary of monitored locations (name: [lat, lon]).
- `webhook_url`: (Optional) If set, the script will POST the output JSON to this URL after each run. This is ideal for integration with automation tools like n8n.

### 🌐 Webhook Integration (n8n Example)

To receive alerts in [n8n](https://n8n.io/):
1. Create a Webhook node in n8n.
2. Set the HTTP Method to **POST**.
3. Copy the webhook URL and paste it as `webhook_url` in your `carstorms.config`.
4. The script will POST the full output JSON to this webhook after each run.

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

## 🔄 Automate with Cron & Virtual Environment (Recommended for Ubuntu/Linux)

### 1. Set up a Python virtual environment in your project directory

```bash
cd ~/python/carstorms
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

- This creates and activates a virtual environment in `~/python/carstorms/venv`.
- Install dependencies inside the venv for isolation and portability.

### 2. Run the script manually using the venv

```bash
cd ~/python/carstorms
source venv/bin/activate
venv/bin/python carstorms.py
```

### 3. Run the test suite using the venv

```bash
cd ~/python/carstorms
source venv/bin/activate
venv/bin/python -m unittest test_carstorms.py -v
```

### 4. Set up a cron job to run the script every hour at 7 minutes past the hour

Edit your crontab:

```bash
crontab -e
```

Add this line:

```cron
7 * * * * cd "$HOME/python/carstorms" && ./venv/bin/python carstorms.py >> carstorms_cron.log 2>&1
```

- This will run the script at 7 minutes past every hour.
- All dependencies and the script will use the virtual environment.
- Output and errors will be appended to `carstorms_cron.log` in the project directory.

---

## 🧪 Testing & Simulation

You can run the test suite to:
- Validate all core logic and config loading.
- Simulate a hurricane scenario and see the output structure.
- Ensure the script works with your real `carstorms.config` (all tests use the real config).

To run all tests:

```bash
python3 -m unittest test_carstorms.py -v
```

- The test suite will simulate a hurricane and show the output JSON as it would be sent to your webhook.
- You can use this to verify your config, webhook integration, and output format.

---

## 📄 License

[GPLv3](https://www.gnu.org/licenses/gpl-3.0.html) – Free as in freedom.
