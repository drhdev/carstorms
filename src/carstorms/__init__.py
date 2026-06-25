"""CarStorms — multi-hazard early-warning system for St. John, USVI.

Fetches authoritative free hazard feeds (NWS, NHC, USGS, Open-Meteo), threads
observations into continuous events, decides when an escalating warning is worth
sending, broadcasts it to a Telegram channel with recommended actions and official
graphics, and archives every event, update and message in Directus.
"""

__version__ = "1.0.0"
