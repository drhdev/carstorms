"""Deterministic 'what to do' guidance for every hazard type and threat level.

Advice is curated from public NWS, Ready.gov and VITEMA (Virgin Islands Territorial
Emergency Management Agency) guidance and framed for St. John, USVI. It is fully
offline and predictable — no model is in the life-safety path.
"""

from __future__ import annotations

from carstorms.models import AlertLevel, ChangeType, HazardType

# A small shared footer for serious levels pointing at official channels.
_OFFICIAL = (
    "Follow official instructions from VITEMA and local authorities; monitor WTJX and NWS San Juan."
)

# Hazard families share advice. Each family maps a *minimum* level to bullets;
# the most specific band at or below the event level is used.
_FAMILIES: dict[str, dict[AlertLevel, list[str]]] = {
    "tropical_cyclone": {
        AlertLevel.INFORMATIONAL: [
            "A tropical system is being monitored — no action needed yet, just stay aware.",
            "Review your hurricane plan and check that supplies are not expired.",
        ],
        AlertLevel.WATCH: [
            "Tropical storm/hurricane conditions are possible — begin preparing now.",
            "Fill water containers and fuel vehicles; charge phones and power banks.",
            "Secure boats, outdoor furniture and loose objects; know your evacuation route.",
            "Assemble a go-bag: documents, medication, cash, water and 3+ days of food.",
        ],
        AlertLevel.WARNING: [
            "Conditions are expected within ~36 hours — finish all preparations today.",
            "If you live in a flood- or surge-prone or low-lying coastal area, leave for higher ground or a shelter.",
            "Bring in or tie down anything the wind can lift; protect windows.",
            "Stay off the water and away from the coast.",
            _OFFICIAL,
        ],
        AlertLevel.EMERGENCY: [
            "Take protective action NOW. If ordered to evacuate, go immediately.",
            "Shelter in an interior room on the lowest safe floor away from windows.",
            "Do not go outside during the eye (the calm is temporary); wait for the all-clear.",
            _OFFICIAL,
        ],
        AlertLevel.CATASTROPHIC: [
            "Life-threatening conditions. Evacuate now if you can do so safely, or shelter in the strongest interior space available.",
            "Expect prolonged loss of power, water and communications; treat all flood water as dangerous.",
            _OFFICIAL,
        ],
    },
    "thunderstorm": {
        AlertLevel.INFORMATIONAL: [
            "Thunderstorms are possible — keep an eye on the sky if you have outdoor plans.",
        ],
        AlertLevel.ADVISORY: [
            "When thunder roars, go indoors — lightning is the main risk.",
            "Secure light outdoor items and avoid open water and exposed ridgelines.",
        ],
        AlertLevel.WARNING: [
            "Move indoors immediately and stay away from windows.",
            "Damaging winds, hail or frequent lightning are likely — avoid the coast and high ground.",
            "Unplug sensitive electronics; do not shelter under trees.",
        ],
        AlertLevel.EMERGENCY: [
            "Severe storm in progress — shelter in a sturdy interior room now.",
            "Stay off roads; downed lines and flooding are likely.",
            _OFFICIAL,
        ],
    },
    "flood": {
        AlertLevel.ADVISORY: [
            "Minor flooding possible in low-lying and poor-drainage areas — avoid flooded roads.",
        ],
        AlertLevel.WATCH: [
            "Flooding is possible — move vehicles and valuables to higher ground.",
            "Be ready to relocate if water starts to rise; know an alternate route.",
        ],
        AlertLevel.WARNING: [
            "Flooding is occurring or imminent — move to higher ground now.",
            "Turn Around, Don't Drown: never walk or drive through flood water.",
            "Stay away from streams, drainage ditches (guts) and culverts.",
            _OFFICIAL,
        ],
        AlertLevel.EMERGENCY: [
            "Flash-flood emergency — seek higher ground immediately; do not wait.",
            "If trapped in a building, go to the highest floor; avoid closed attics.",
            _OFFICIAL,
        ],
    },
    "marine": {
        AlertLevel.INFORMATIONAL: [
            "Elevated seas or surf possible — check conditions before any boating or swimming.",
        ],
        AlertLevel.ADVISORY: [
            "Hazardous seas, surf or rip currents — inexperienced mariners and swimmers should stay ashore.",
            "Swim only at guarded beaches; if caught in a rip current, swim parallel to shore.",
        ],
        AlertLevel.WARNING: [
            "Dangerous marine conditions — remain in port and stay out of the water.",
            "Secure vessels; high surf can sweep people off rocks, docks and jetties.",
            _OFFICIAL,
        ],
    },
    "earthquake": {
        AlertLevel.INFORMATIONAL: [
            "A minor earthquake was recorded nearby — no action needed; aftershocks are possible.",
        ],
        AlertLevel.ADVISORY: [
            "If shaking is felt: Drop, Cover and Hold On until it stops.",
            "Check for hazards (gas smell, damaged structures) before moving around.",
        ],
        AlertLevel.WATCH: [
            "Be prepared for aftershocks — Drop, Cover and Hold On when shaking starts.",
            "If you are near the coast and feel strong or long shaking, move inland and to higher ground in case of a tsunami.",
        ],
        AlertLevel.WARNING: [
            "Strong earthquake — expect aftershocks and possible damage.",
            "If near the coast, move to high ground immediately; do not wait for an official tsunami alert.",
            "Stay out of damaged buildings; check for injuries and gas leaks.",
            _OFFICIAL,
        ],
        AlertLevel.EMERGENCY: [
            "Major earthquake — Drop, Cover and Hold On; after shaking stops, evacuate damaged buildings.",
            "Coastal areas: a tsunami may follow within minutes — go to high ground inland NOW.",
            _OFFICIAL,
        ],
    },
    "tsunami": {
        AlertLevel.WATCH: [
            "Tsunami watch — stay alert and be ready to move away from the coast.",
            "Gather essentials and monitor official channels for escalation.",
        ],
        AlertLevel.WARNING: [
            "Tsunami warning — move immediately to high ground or inland, away from all beaches and harbours.",
            "Go on foot if possible; do not return until officials declare it safe.",
            _OFFICIAL,
        ],
        AlertLevel.EMERGENCY: [
            "Tsunami imminent — evacuate to high ground NOW. Minutes matter.",
            "Do not go to the shore to watch; a tsunami is a series of waves and the first is rarely the largest.",
            _OFFICIAL,
        ],
    },
    "heat": {
        AlertLevel.ADVISORY: [
            "Hot and humid — drink water often, limit midday exertion and never leave anyone in a parked car.",
            "Check on elderly neighbours and those without air conditioning.",
        ],
        AlertLevel.WARNING: [
            "Dangerous heat — stay in cool/shaded areas, hydrate, and watch for heat-illness signs.",
            "Reschedule strenuous outdoor activity to early morning or evening.",
        ],
    },
    "water_quality": {
        AlertLevel.ADVISORY: [
            "Avoid swimming at the affected beach for ~48 h, especially after heavy rain.",
            "Stay away from water near guts, drains and storm-water outfalls; pick a beach meeting the bacteria standard.",
        ],
        AlertLevel.WATCH: [
            "Bacteria levels are well above the safe limit — do not swim at the affected beach.",
            "Keep children and pets out of the water; rinse off thoroughly after any contact.",
        ],
    },
    "air_quality": {
        AlertLevel.ADVISORY: [
            "Air is unhealthy for sensitive groups (Saharan dust likely) — limit prolonged outdoor exertion.",
            "People with asthma, heart or lung conditions should keep medication handy.",
        ],
        AlertLevel.WATCH: [
            "Unhealthy air — everyone should reduce prolonged or heavy outdoor exertion.",
            "Keep windows closed, run AC on recirculate; sensitive groups stay indoors.",
        ],
        AlertLevel.WARNING: [
            "Very unhealthy air — avoid outdoor activity.",
            "Sensitive groups stay indoors; wear an N95 outdoors if you must go out.",
            _OFFICIAL,
        ],
        AlertLevel.EMERGENCY: [
            "Hazardous air quality — everyone stay indoors with windows closed.",
            "Seek medical help for any breathing difficulty.",
            _OFFICIAL,
        ],
    },
    "sargassum": {
        AlertLevel.ADVISORY: [
            "Sargassum buildup likely on windward beaches; expect a strong odor.",
            "Avoid wading through large mats — decomposing seaweed releases hydrogen-sulfide gas; sensitive groups stay upwind.",
        ],
        AlertLevel.WATCH: [
            "Heavy sargassum inundation expected on affected beaches.",
            "Avoid affected beaches; people with respiratory conditions should keep well away from decaying mats.",
        ],
    },
    "power": {
        AlertLevel.INFORMATIONAL: [
            "A localized power outage has been reported; WAPA is aware.",
        ],
        AlertLevel.ADVISORY: [
            "Outage expected or in progress — charge devices and prepare for interruptions.",
            "Protect refrigerated medication; have flashlights and stored water ready.",
        ],
        AlertLevel.WATCH: [
            "Large unplanned outage in progress.",
            "Keep fridges/freezers closed; treat dark traffic signals as 4-way stops.",
            "Report outages to WAPA: 340-774-3552.",
        ],
        AlertLevel.WARNING: [
            "Widespread or prolonged outage — conserve water (pumps may be affected).",
            "Check on vulnerable neighbours; run generators outdoors only.",
            _OFFICIAL,
        ],
    },
    "water_outage": {
        AlertLevel.ADVISORY: [
            "WAPA water-service notice — store water and conserve.",
            "If a boil-water advisory is in effect, boil water 1 minute before drinking/cooking, or use bottled water.",
        ],
        AlertLevel.WATCH: [
            "Widespread water outage or boil-water advisory in effect.",
            "Use bottled or boiled water for drinking, cooking and brushing teeth until cleared.",
            _OFFICIAL,
        ],
    },
    "airport": {
        AlertLevel.INFORMATIONAL: [
            "Cyril E. King (STT) is operating normally — no action needed.",
        ],
        AlertLevel.ADVISORY: [
            "Reduced visibility/ceilings at STT may cause delays.",
            "Confirm your flight status with the airline and arrive at least 3 hours early.",
        ],
        AlertLevel.WATCH: [
            "Significant disruption likely at STT — expect delays or cancellations.",
            "Confirm with your airline, consider rebooking, and keep travel documents handy.",
        ],
        AlertLevel.WARNING: [
            "STT airport closure or major disruption.",
            "Do not travel to the airport until your flight is confirmed; follow airline and VIPA guidance.",
            _OFFICIAL,
        ],
    },
    "ferry": {
        AlertLevel.ADVISORY: [
            "Reduced or delayed ferry service between Red Hook (STT) and Cruz Bay (STJ).",
            "Allow extra time and check the latest schedule before travelling.",
        ],
        AlertLevel.WATCH: [
            "Ferry route(s) between Red Hook and Cruz Bay suspended or heavily disrupted.",
            "Plan around it; confirm alternatives (car barge) and avoid tight connections to STT flights.",
        ],
        AlertLevel.WARNING: [
            "All STT↔STJ ferry service suspended.",
            "Do not rely on the ferry; follow VIPA and operator announcements.",
            _OFFICIAL,
        ],
    },
    "health": {
        AlertLevel.ADVISORY: [
            "Follow the Department of Health guidance for this advisory.",
            "Protect vulnerable people and seek care if symptoms develop.",
        ],
        AlertLevel.WATCH: [
            "A health advisory is in effect — take the recommended precautions.",
            _OFFICIAL,
        ],
        AlertLevel.WARNING: [
            "Serious public-health threat — follow DOH/CDC instructions closely.",
            _OFFICIAL,
        ],
    },
    "public_safety": {
        AlertLevel.ADVISORY: [
            "Stay alert and follow guidance from VITEMA and local authorities.",
        ],
        AlertLevel.WATCH: [
            "A public-safety watch is in effect — be prepared to act.",
            _OFFICIAL,
        ],
        AlertLevel.WARNING: [
            "Follow official safety instructions immediately.",
            _OFFICIAL,
        ],
        AlertLevel.EMERGENCY: [
            "Life-threatening situation — follow emergency instructions and evacuate if told to.",
            _OFFICIAL,
        ],
    },
    "generic": {
        AlertLevel.INFORMATIONAL: [
            "Stay informed and monitor official channels for updates.",
        ],
        AlertLevel.WATCH: [
            "Review your emergency plan and supplies; be ready to act.",
        ],
        AlertLevel.WARNING: [
            "Take protective action appropriate to the hazard and follow official guidance.",
            _OFFICIAL,
        ],
        AlertLevel.EMERGENCY: [
            "Act now to protect life and property; follow evacuation or shelter orders.",
            _OFFICIAL,
        ],
    },
}

# Which family handles each hazard type.
_HAZARD_FAMILY: dict[HazardType, str] = {
    HazardType.TROPICAL_CYCLONE: "tropical_cyclone",
    HazardType.SEVERE_THUNDERSTORM: "thunderstorm",
    HazardType.THUNDERSTORM: "thunderstorm",
    HazardType.WIND: "thunderstorm",
    HazardType.FLASH_FLOOD: "flood",
    HazardType.FLOOD: "flood",
    HazardType.MARINE: "marine",
    HazardType.HIGH_SURF: "marine",
    HazardType.RIP_CURRENT: "marine",
    HazardType.EARTHQUAKE: "earthquake",
    HazardType.TSUNAMI: "tsunami",
    HazardType.HEAT: "heat",
    HazardType.WATER_QUALITY: "water_quality",
    HazardType.AIR_QUALITY: "air_quality",
    HazardType.SARGASSUM: "sargassum",
    HazardType.POWER_OUTAGE: "power",
    HazardType.WATER_OUTAGE: "water_outage",
    HazardType.AIRPORT: "airport",
    HazardType.FERRY: "ferry",
    HazardType.HEALTH: "health",
    HazardType.PUBLIC_SAFETY: "public_safety",
    HazardType.OTHER: "generic",
}

# Travel disruption is likely once a tropical system reaches watch level; nudge
# visitors to move plans early while flights/ferries are still running.
_TRAVEL_NOTE = (
    "Travelling? Expect airport and ferry disruptions — confirm flights early and "
    "consider moving plans before conditions deteriorate."
)

_ALL_CLEAR = [
    "The threat has passed or been cancelled for St. John.",
    "Hazards may remain: watch for downed lines, debris, flooded roads and weakened trees.",
    "Do not return to evacuated areas until authorities confirm it is safe.",
]


def recommend(
    hazard_type: HazardType,
    level: AlertLevel,
    change_type: ChangeType = ChangeType.UPDATE,
) -> list[str]:
    """Return ordered recommended-action bullets for an event state."""
    if change_type in (ChangeType.ALL_CLEAR, ChangeType.CLOSED, ChangeType.DEESCALATION):
        if change_type is ChangeType.DEESCALATION and level >= AlertLevel.WATCH:
            pass  # still meaningful threat — fall through to level advice
        else:
            return list(_ALL_CLEAR)

    family = _HAZARD_FAMILY.get(hazard_type, "generic")
    bands = _FAMILIES[family]
    # Pick the most specific band at or below the event level.
    chosen: list[str] | None = None
    for band_level in sorted(bands, reverse=True):
        if level >= band_level:
            chosen = bands[band_level]
            break
    if chosen is None:
        chosen = _FAMILIES["generic"][AlertLevel.INFORMATIONAL]
    bullets = list(chosen)
    if hazard_type is HazardType.TROPICAL_CYCLONE and level >= AlertLevel.WATCH:
        bullets.append(_TRAVEL_NOTE)
    return bullets


def recommendation_text(
    hazard_type: HazardType,
    level: AlertLevel,
    change_type: ChangeType = ChangeType.UPDATE,
) -> str:
    """Recommended actions as a single newline-bulleted string."""
    return "\n".join(f"• {line}" for line in recommend(hazard_type, level, change_type))
