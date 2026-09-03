"""The quest catalogue and the persistence shape it produces.

Persistence extends, and does not break, the existing
``achievements.json`` layout owned by ``routes/sichtungen.py``:

    {
      "robin": { "date": ..., "count": 47, ... },          # unchanged
      "quests": {
        "wintervorrat_2026": {
          "id": "wintervorrat_2026",
          "title": "Wintervorrat",
          "icon": "🐿️",
          "description": "50 Eichhörnchen-Sichtungen im Dezember",
          "target": 50,
          "progress": 23,
          "window": {"from": "...", "to": "..."},
          "criteria": {"label": "squirrel"},
          "completed_at": null,
          "notified_at": null
        },
        ...
      }
    }
"""

from __future__ import annotations


# ── Quest catalogue ────────────────────────────────────────────────────────
# Hardcoded by design — V1 has no user-editable quests. Adding a new entry
# here + a window type below is enough to ship one.
QUESTS: list[dict] = [
    # ── Kept from v1 (already realistic for a garden install). ────────
    {
        "id": "wintervorrat",
        "title": "Wintervorrat",
        "icon": "🐿️",
        "description": "50 Eichhörnchen-Sichtungen im Dezember",
        "target": 50,
        "window": "december",
        "criteria": {"label": "squirrel"},
    },
    {
        "id": "fruehlingschor",
        "title": "Frühlingschor",
        "icon": "🌸",
        "description": "10 verschiedene Vogelarten in einer Aprilwoche",
        "target": 10,
        "window": "april_rolling_week",
        "criteria": {"label": "bird", "count_distinct_species": True},
    },
    # ── Monthly diversity — achievable in central Europe with a feeder.
    {
        "id": "vogelvielfalt",
        "title": "Vogelvielfalt",
        "icon": "🐦",
        "description": "8 verschiedene Vogelarten im laufenden Monat",
        "target": 8,
        "window": "current_calendar_month",
        "criteria": {"label": "bird", "count_distinct_species": True},
    },
    # ── Weekly counter for the most-common garden visitor class. ──────
    {
        "id": "eichhoernchen_wache",
        "title": "Eichhörnchen-Wache",
        "icon": "🌰",
        "description": "12 Eichhörnchen-Sichtungen in einer Woche",
        "target": 12,
        "window": "current_rolling_week",
        "criteria": {"label": "squirrel"},
    },
    # ── Time-of-day quest — last hour before sunset. Fixed window
    # 18:00–19:00 covers the German evening golden hour from
    # late-summer through autumn; we accept that the window drifts
    # against the actual sun (the operator gets a quieter quest in
    # December as opposed to a perpetually-unachievable one). ──
    {
        "id": "goldene_stunde",
        "title": "Goldene Stunde",
        "icon": "🌅",
        "description": "15 Sichtungen in der Abendstunde (18:00–19:00) im Monat",
        "target": 15,
        "window": "current_calendar_month",
        "criteria": {"hour_in": [18]},
    },
    # ── Consistency — sightings spread across many days. ──────────────
    {
        "id": "stammgast",
        "title": "Stammgast",
        "icon": "📅",
        "description": "An 15 Tagen des Monats mindestens eine Sichtung",
        "target": 15,
        "window": "current_calendar_month",
        "criteria": {"count_distinct_days": True},
    },
    # ── Morning routine — generic 05:00–08:00 window. Replaces the
    # weather-coupled "Nebelmorgen" idea with something that works
    # without weather_history overlap. ──────────────────────────
    {
        "id": "morgenrunde",
        "title": "Morgenrunde",
        "icon": "☕",
        "description": "8 Sichtungen am frühen Morgen (05:00–08:00) im Monat",
        "target": 8,
        "window": "current_calendar_month",
        "criteria": {"hour_in": [5, 6, 7]},
    },
]
