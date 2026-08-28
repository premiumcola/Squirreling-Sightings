"""Constants shared between settings.defaults and settings.migrations.

These are pure data — kept in their own module so neither the defaults
builder nor the migration helpers carry the other's import. SettingsStore
itself does not import from here; consumers go through the merged
runtime view (export_effective_config / runtime_*)."""

from __future__ import annotations

from ..weather_episodes._consts import EPISODE_DEFAULTS

# Default Telegram push schema. Single source of truth feeding both
# fresh installs (build_defaults) and the additive backfill on existing
# data (migrate_telegram_push_defaults).
TELEGRAM_PUSH_DEFAULTS: dict = {
    "enabled": True,
    "rate_limit_seconds": 30,
    "quiet_hours": {"start": "22:00", "end": "07:00"},
    "night_alert": {
        "enabled": True,
        "armed_only": True,
        "use_sun": True,
        "lat": None,
        "lon": None,
        # Fallback window when use_sun is off or lat/lon missing.
        "start": "22:00",
        "end": "07:00",
    },
    "labels": {
        "person": {"push": True, "threshold": 0.85},
        "cat": {"push": False, "threshold": 0.80},
        "dog": {"push": True, "threshold": 0.80},
        "bird": {"push": False, "threshold": 0.90},
        "car": {"push": True, "threshold": 0.85},
        "squirrel": {"push": True, "threshold": 0.80},
        "motion": {"push": False, "threshold": 0.0},
    },
    # Recording ticker — one line when a clip starts, one when it ends.
    # A diagnostic aid for walk-in tests ("is it recording me right now,
    # and when can I go again?"), NOT an alert: it deliberately bypasses
    # the severity matrix, push thresholds, quiet hours and schedules,
    # since those are usually the very things being tested. Per-camera
    # `recording_ticker` overrides this. Set to False once testing is
    # done — in normal operation it is two extra messages per event.
    "recording_ticker": True,
    "daily_report": {"enabled": True, "time": "22:00"},
    "highlight": {"enabled": True, "time": "19:00"},
    "system": {"enabled": True},
    "timelapse": {"enabled": True},
    # Wetter-Sichtungen Push (Phase 3). Per-event toggles control whether
    # a successful weather clip triggers a Telegram send. min_score gates
    # everything — sightings below the bar are skipped regardless.
    "weather": {
        "enabled": True,
        "min_score": 0.4,
        "events": {
            "thunder": True,
            "heavy_rain": True,
            "snow": True,
            "fog": False,  # default off — pretty rare to be interesting
            "sunset": True,
        },
        "recap_push": True,  # ein Push pro fertigem Quartals-/Jahres-Recap
    },
}


# Server.location fallback — Nuremberg (project HQ). Only applied when
# the user hasn't entered coordinates; never overwrites existing values.
SERVER_LOCATION_DEFAULTS: dict = {
    "lat": 49.4521,
    "lon": 11.0767,
    "elevation": None,
}


# Global weather defaults. Same idempotent additive-merge pattern as
# TELEGRAM_PUSH_DEFAULTS — every key the WeatherService expects is
# backfilled on each load() so a fresh install and an upgraded install
# behave identically.
WEATHER_DEFAULTS: dict = {
    "enabled": True,
    "poll_interval": 300,
    "events": {
        # lightning_potential is in J/kg from Open-Meteo's icon_d2 model.
        "thunder": {"enabled": True, "threshold": 1000.0, "cooldown_min": 30},
        "heavy_rain": {"enabled": True, "threshold": 5.0, "hysteresis": 1.0, "cooldown_min": 30},
        "snow": {"enabled": True, "threshold": 0.5, "cooldown_min": 60},
        # Gusts in km/h. 60 sits just under Beaufort 8 ("stürmischer
        # Wind", 62 km/h) so a gale is caught as it arrives, and far
        # above the 22–26 km/h that is an ordinary breezy afternoon here.
        # This event feeds the EPISODE ARCHIVE only — `_detection._detect`
        # has no `storm` branch, so it deliberately produces no weather
        # clip and no push. It exists because a squall that peaked at
        # 65 km/h on 2026-08-28 could not be archived at all: gusts were
        # charted but had no threshold behind them.
        "storm": {"enabled": True, "threshold": 60.0, "cooldown_min": 60},
        "fog": {"enabled": True, "vis_max_m": 1000, "contrast_max": 0.25, "cooldown_min": 90},
        # Sunset: triggers once per day in the dusk window.
        "sunset": {
            "enabled": True,
            "alt_min": -2,
            "alt_max": 5,
            "min_duration_min": 12,
            "cooldown_min": 720,
        },
    },
    "clip": {
        "pre_roll_s": 5,
        "post_roll_s": 5,
        "fps": 15,
        "width": 1280,
    },
    "api": {
        "base_url": "https://api.open-meteo.com/v1/forecast",
        "model": "icon_d2",
        "timezone": "Europe/Berlin",
    },
    # Global cost caps for the per-camera event-timelapse pre-roll ring
    # (the per-camera window itself lives in EVENT_TL_DEFAULTS).
    #   prebuffer_max_mb — hard ceiling per camera ring. At interval_s=8
    #     a 15-min window is 113 frames; a 2560x1440 JPEG at quality 92
    #     runs 0.6–1.5 MB, so ~90 MB typical and ~170 MB worst case. The
    #     cap evicts by bytes as well as by frame count so an unusually
    #     detailed scene cannot outgrow the budget.
    #   watch_grace_min  — how long a single "elevated risk" poll keeps
    #     the ring alive in `armed` mode. Longer than the 5-min poll
    #     interval on purpose: it is what stops a flickering forecast
    #     from repeatedly wiping a half-full ring.
    "event_timelapse": {
        "prebuffer_max_mb": 256,
        "watch_grace_min": 30,
    },
    # Storm-episode archive (app/app/weather_episodes). The weather
    # history is a rolling 30-day window; these knobs decide what gets
    # lifted out of it into the permanent archive before it rolls.
    #   pre_min / post_min — minutes of curve kept around the episode.
    #     The build-up is the part worth comparing across years.
    #   settle_min         — how long every metric must stay below its
    #     threshold before the episode counts as over. Without it a
    #     pulsing storm fragments into six separate episodes.
    # Sourced from the package that consumes them, not restated here —
    # a second copy of these numbers drifts the moment one is tuned.
    "episodes": dict(EPISODE_DEFAULTS),
}


# Keys mirror camera_runtime._consts._PROFILES and the frontend's
# _TL_PROFILES_DEF — all three lists must carry the same profile names or
# a profile is configurable somewhere and inert everywhere else.
# Shipped timelapse profile defaults. Mirror of _TL_PROFILES_DEF in
# web/static/js/camedit/timelapse-settings.js — the two disagreed on
# `custom` and the backend's copy was the wrong one.
#
# Every entry has to satisfy period_seconds >= target_seconds * FIXED_FPS
# * MIN_INTERVAL_S, or the 8 s capture floor clamps the profile and the
# operator gets a shorter video than the label promises. `custom` shipped
# 600 s / 30 s at 15 fps → 1.33 s raw interval → clamped to 8 s → 75
# frames → a FIVE-second video behind one WARNING, a silent 6× cut.
#
# The floor is what keeps the capture loop from competing with detection,
# so the floor stays and the shipped period moves: 3600 s is the shortest
# window that yields the advertised 30 s at exactly the 8 s floor
# (3600 / 8 = 450 = 30 × 15), and it is what the UI has always offered as
# the `custom` default. test_shipped_profile_defaults_are_never_clamped
# pins the invariant for all six.
TL_DEFAULT_PROFILES = {
    "daily": {"enabled": False, "target_seconds": 60, "period_seconds": 86400},
    "weekly": {"enabled": False, "target_seconds": 180, "period_seconds": 604800},
    "monthly": {"enabled": False, "target_seconds": 300, "period_seconds": 2592000},
    "quarterly": {"enabled": False, "target_seconds": 600, "period_seconds": 7776000},
    "yearly": {"enabled": False, "target_seconds": 900, "period_seconds": 31536000},
    "custom": {"enabled": False, "target_seconds": 30, "period_seconds": 3600},
}


# Per-class detection-score floor. Snapshot constant so reads from
# default_camera don't accidentally mutate the source dict if a caller
# pokes at it.
LABEL_THRESHOLD_DEFAULTS = {
    "person": 0.45,
    "cat": 0.55,
    "bird": 0.45,
    "squirrel": 0.45,
}
# N-of-M sliding-window defaults per class. Bird + squirrel run with
# smaller windows (they cross the frame in seconds; 3-of-5 would
# often miss them); person/cat get the conservative 3-of-5 floor.
CONFIRMATION_WINDOW_DEFAULTS = {
    "person": {"n": 3, "seconds": 5.0},
    "cat": {"n": 3, "seconds": 5.0},
    "bird": {"n": 2, "seconds": 4.0},
    "squirrel": {"n": 2, "seconds": 3.0},
}


# THR-1 · per-camera keys landed in one go so six follow-up packages
# don't each have to edit defaults.py. Only the keys and their defaults
# live here — the logic that reads them ships with the package that
# needs it.
#   push_thresholds — per-label Telegram push floor for THIS camera.
#     {} = fall back to the global telegram.push.labels[*].threshold.
#     A workshop cam and a bird feeder are metres vs. tens of metres
#     away from their subjects; one global person threshold cannot
#     serve both. Resolution order lives in app/app/thresholds.
#     THR-3 landed: telegram_bot/_outbound/_event_alert resolves the
#     push gate through `resolve_effective`, so this key is LIVE — it
#     is the camera layer, and the Netz panel writes exactly it.
#   hybrid_mode     — off|shadow|merge, HYB-2's TPU+CPU dual pass.
#   label_veto      — LEARN-1's per-label suppression map.
HYBRID_MODE_DEFAULT = "off"
CAMERA_THRESHOLD_KEY_DEFAULTS: dict = {
    "push_thresholds": {},
    "hybrid_mode": HYBRID_MODE_DEFAULT,
    "label_veto": {},
}

# NETZ · the four per-camera keys the Erkennungsnetz owns.
#
#   role        — "security" | "wildlife". Decides whether the person
#                 safety floor applies to the AUTOMATIC path. Default is
#                 "security", the safe direction: a camera nobody has
#                 classified is treated as one an intruder could trip.
#   net_pin     — {label: {E, ts, by}} — axes the operator dragged by
#                 hand. A pin is permanent and the learner never writes
#                 a pinned axis. No timeout: a value that silently
#                 reverts after 30 days destroys trust.
#   net_adapted — {label: {E, ts}} — what the nightly learner applied.
#                 Feeds the ladder's `adapted` layer, which ranks BELOW
#                 `camera`, so a pin physically outranks the learner.
#   net_auto    — per-camera master switch for the learner. Default on;
#                 off means it only proposes and never writes.
#
# Kept OUT of CAMERA_THRESHOLD_KEY_DEFAULTS on purpose: that map is
# applied with `cam.get(key) or default`, which would silently resurrect
# a `net_auto: false` the operator deliberately set.
NET_AUTO_DEFAULT = True
CAMERA_ROLE_DEFAULT = "security"
CAMERA_NET_KEY_DEFAULTS: dict = {
    "role": CAMERA_ROLE_DEFAULT,
    "net_pin": {},
    "net_adapted": {},
    "net_auto": NET_AUTO_DEFAULT,
}

# THR-1 · CORP-2's per-label daily cap on retained corpus samples.
# Lives in the storage section next to retention_days.
CORPUS_QUOTA_PER_LABEL_DAY_DEFAULT = 50
STORAGE_DEFAULTS: dict = {
    "corpus_quota_per_label_day": CORPUS_QUOTA_PER_LABEL_DAY_DEFAULT,
}


# Per-camera sun-timelapse defaults — both phases off until the user
# opts in. window_min is overridden at runtime by _SUN_TL_LOCKED_WINDOW_MIN
# (75 min) and persisted here as 30 only for legacy round-trips.
# E1 · interval_s 3 → 8 (defeats the Reolink snapshot-API cache that
# bursts up to 14 identical frames on a 3 s pull), fps 25 → 15
# (matches the cross-system fixed output rate so the encoder doesn't
# have to "stretch" against a dedup-shortened frame budget). See
# settings/migrations.py · _migrate_timelapse_intervals for the
# matching clamp on legacy settings.json files.
SUN_TL_DEFAULTS: dict = {
    "sunrise": {"enabled": False, "window_min": 30, "interval_s": 8, "fps": 15},
    "sunset": {"enabled": False, "window_min": 30, "interval_s": 8, "fps": 15},
}


# Per-camera event-timelapse defaults — opt-in master switch + per-trigger
# toggles. Default OFF so existing weather cameras don't suddenly start
# producing 60-min timelapses without explicit consent.
# E1 · interval_s 6 → 8, fps 24 → 15 — same rationale as SUN_TL above.
#
# prebuffer_min / prebuffer_mode — pre-roll ring buffer. A storm only
# reveals itself once it has arrived, so a forward-only capture misses
# the build-up entirely. The ring keeps the last `prebuffer_min` minutes
# and discards the rest until a trigger fires, at which point the frames
# are retained and the capture continues forward. Modes:
#   off    — no ring; forward-only (behaviour before this key existed).
#   armed  — DEFAULT. Ring spins only while the forecast shows elevated
#            risk. The triggers read 60–90 min ahead, so the watch
#            predicate normally arms hours before a trigger can fire;
#            this gets the same pre-roll at a fraction of the duty cycle.
#   always — ring spins 24/7 for every opted-in camera.
# Backfilled additively by migrate_weather_defaults, so a camera that
# predates the keys lands on 15 min / armed rather than on "no pre-roll".
EVENT_TL_DEFAULTS: dict = {
    "enabled": False,
    "window_min": 60,
    "interval_s": 8,
    "fps": 15,
    "prebuffer_min": 15,
    "prebuffer_mode": "armed",
    "triggers": {
        "thunder_rising": True,
        "front_passing": True,
        "storm_front": True,
    },
}


# Per-class severity matrix — one of "off" / "info" / "alarm" per
# supported class (person, cat, bird, squirrel, dog, car, motion).
# Replaces the four-valued alarm_profile string. The mapping below
# mirrors the previous profile semantics so an upgrade with a legacy
# alarm_profile lands on the equivalent matrix without the user having
# to redo their notification config:
#   hard:   person/car=alarm, animals=off, motion=off
#   medium: person/car=alarm, animals=info, motion=off
#   soft:   person=alarm, car=info, animals=info, motion=info
#   info:   animals=info, person/car/motion=off
ALARM_PROFILE_TO_SEVERITY = {
    "hard": {
        "person": "alarm",
        "car": "alarm",
        "cat": "off",
        "bird": "off",
        "squirrel": "off",
        "dog": "off",
        "motion": "off",
    },
    "medium": {
        "person": "alarm",
        "car": "alarm",
        "cat": "info",
        "bird": "info",
        "squirrel": "info",
        "dog": "info",
        "motion": "off",
    },
    "soft": {
        "person": "alarm",
        "car": "info",
        "cat": "info",
        "bird": "info",
        "squirrel": "info",
        "dog": "info",
        "motion": "info",
    },
    "info": {
        "person": "off",
        "car": "off",
        "cat": "info",
        "bird": "info",
        "squirrel": "info",
        "dog": "info",
        "motion": "off",
    },
}
