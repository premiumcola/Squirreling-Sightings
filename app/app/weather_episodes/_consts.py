"""Constants for the storm-episode archive.

Kept in its own module so the segmentation, scoring, record-building
and persistence modules can share them without importing each other.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Append-only ledger beside settings.json / weather_history.json.
EPISODE_FILE = "weather_episodes.jsonl"

# Record kinds in the ledger. `episode` is the immutable base record;
# `patch` carries a user edit; `delete` is a tombstone. Nothing is ever
# rewritten in place — the read side folds patches over bases.
KIND_EPISODE = "episode"
KIND_PATCH = "patch"
KIND_DELETE = "delete"
# How many recordings overlap this episode's window. Written ONCE, by
# whoever last scanned the media stores for that window — never by the
# list route. See ``_archive._stamp_footage`` for why the count lives in
# the ledger instead of being recomputed per request.
KIND_FOOTAGE = "footage"

# Episodes to count per sweep when the archive predates the stamped
# count. Three, not "all": the sweep runs on the weather poll's thread
# every 5 minutes, and a fresh deploy with a full window of storms must
# not turn one poll into a minutes-long media walk. At this rate a
# 60-storm archive is fully stamped inside 100 minutes.
FOOTAGE_BACKFILL_PER_SWEEP = 3

# Margin + settle defaults. Mirrored into WEATHER_DEFAULTS["episodes"]
# (app/app/settings/_consts.py) so the values are user-configurable and
# backfilled additively on every settings load.
# 60, not 90, on the operator's call: "nicht zu lang, ja, eine Stunde
# oder so davor jeweils und danach". It also shortens the finalisation
# delay, which is `max(settle_min, pre_min + post_min)` past an episode's
# end — 120 min at these values instead of 180, so a storm that ends at
# 14:00 is archived at 16:00 rather than 17:00.
DEFAULT_PRE_MIN = 60
DEFAULT_POST_MIN = 60
DEFAULT_SETTLE_MIN = 30

EPISODE_DEFAULTS: dict = {
    "enabled": True,
    # Minutes of samples kept BEFORE onset. The build-up is the part
    # worth studying — and the part a future classifier would have to
    # learn to recognise before the storm arrives.
    "pre_min": DEFAULT_PRE_MIN,
    # Minutes of samples kept AFTER the last threshold crossing.
    "post_min": DEFAULT_POST_MIN,
    # How long a metric must stay below its threshold before the episode
    # counts as over. Without it a pulsing storm fragments into six.
    "settle_min": DEFAULT_SETTLE_MIN,
}

# Labels the user may assign by hand. `null` clears the field.
USER_CLASSES: tuple[str, ...] = ("thunder", "heavy_rain", "storm", "hail", "harmless")

# The only fields a PATCH may touch — everything else is detector output
# and stays immutable.
PATCHABLE_FIELDS: tuple[str, ...] = ("user_class", "user_name", "user_note")

USER_NAME_MAX = 120
USER_NOTE_MAX = 2000

# Which key inside WEATHER_DEFAULTS["events"][<evt>] holds the trigger
# line. Every event uses "threshold" except fog, which is configured as
# a visibility ceiling.
EVENT_THRESHOLD_KEY: dict[str, str] = {"fog": "vis_max_m"}
DEFAULT_THRESHOLD_KEY = "threshold"

# Crossing direction per history field. "above" = value >= threshold
# (matches _detect_thunder), "below" = value < threshold (matches
# _detect_fog, where a LOW visibility is the alarm).
FIELD_DIRECTION: dict[str, str] = {
    "precipitation": "above",
    "snowfall": "above",
    "lightning_potential": "above",
    "visibility": "below",
    "wind_gusts_10m": "above",
}

# auto_class when several events fire inside one episode. Fixed order,
# not a magnitude race: a downpour with lightning in it is a
# thunderstorm, and frozen precipitation is the notable half of a
# rain/snow mix.
# `storm` sits below the precipitation events on purpose: a downpour with
# gusts in it is still a downpour, and lightning outranks everything. It
# beats `fog` because a gale is the more notable half of a windy mist.
EVENT_PRIORITY: tuple[str, ...] = ("thunder", "snow", "heavy_rain", "storm", "fog")

# Peak metrics carried on every record, whether or not they triggered.
# Wind has no configured event threshold but is what separates a squall
# from a downpour, so it is measured even though it cannot start an
# episode on its own.
#
# `visibility` is on this list too, and it is the one field where "peak"
# means MINIMUM: a low visibility is the alarm (FIELD_DIRECTION above,
# and _detect_fog). _build._peaks reads the direction rather than always
# taking a max, so the stored value is the worst reading either way.
# This list is mirrored by STORM_METRICS in web/static/js/storms/_state.js
# — a field missing here renders its pill permanently disabled there.
PEAK_FIELDS: tuple[str, ...] = (
    "lightning_potential",
    "precipitation",
    "wind_gusts_10m",
    "snowfall",
    "visibility",
)

# ── Intensity reference values — see _intensity.py for the formula ─────
# The first three mirror the severity scales already used by the live
# detectors (_detection.py: `lp / 3000.0`, `scale=20.0`, `scale=5.0`) so
# the archive and the alert path agree on what "bad" means.
INTENSITY_REFERENCE: dict[str, float] = {
    # LPI (Lynn & Yair 2010), NOT CAPE — observed thunderstorm cases run
    # 0.2–0.8 J/kg. This was 3000.0, matching the equally wrong 1000.0
    # trigger threshold, so every real storm scored ~0.0003 on this axis
    # and the intensity ranking was blind to lightning altogether.
    # 2.0 puts the operator's 2026-08-28 storm (peak ~1 J/kg) at ~0.5 —
    # "a normally strong thunderstorm", which is what they called it.
    "lightning_potential": 2.0,
    "precipitation": 20.0,  # mm/h — cloudburst
    "snowfall": 5.0,  # cm/h — heavy snowfall
    "wind_gusts_10m": 120.0,  # km/h — Beaufort 12 starts at 118
}

# Episode totals (not peaks) get their own reference scale.
INTENSITY_TOTAL_REFERENCE: dict[str, float] = {
    "precipitation_mm": 40.0,  # mm over the whole episode
}

# Longest gap between two samples that still counts as continuous when
# integrating precipitation into a total. A poll outage wider than this
# contributes its cap, not its real width, so a two-day hole cannot
# invent 500 mm of rain.
MAX_INTEGRATION_GAP_MIN = 60.0

# ── Storm character — composition + sequence of the curve itself ──────
# See _character.py for the full rule table. `auto_class` above answers
# "which single alarm fired"; `character` answers "what did the whole
# curve look like" and lives alongside it on every record, never in
# place of it.
CHARACTER_RAIN_LED_THUNDER = "rain_led_thunder"
CHARACTER_LIGHTNING_LED_RAIN = "lightning_led_rain"
CHARACTER_LIGHTNING_ONLY = "lightning_only"
CHARACTER_RAIN_ONLY = "rain_only"
CHARACTER_WIND_ONLY = "wind_only"
CHARACTER_SNOW_ONLY = "snow_only"
CHARACTER_FOG_ONLY = "fog_only"
CHARACTER_MIXED = "mixed"

# The full vocabulary. Frontend mirror: storms/_state.js's
# STORM_CHARACTERS — every slug here needs a `de` label + icon there.
CHARACTERS: tuple[str, ...] = (
    CHARACTER_RAIN_LED_THUNDER,
    CHARACTER_LIGHTNING_LED_RAIN,
    CHARACTER_LIGHTNING_ONLY,
    CHARACTER_RAIN_ONLY,
    CHARACTER_WIND_ONLY,
    CHARACTER_SNOW_ONLY,
    CHARACTER_FOG_ONLY,
    CHARACTER_MIXED,
)

# Fixed involvement floor per PEAK_FIELDS axis — an axis only counts
# as "part of this storm's shape" once its OWN peak crosses this line.
# These mirror this project's OWN shipped event defaults
# (settings/_consts.py:WEATHER_DEFAULTS["events"]) rather than whatever
# the operator has them set to today, so a storm's character does not
# silently reclassify itself years later when someone retunes a
# threshold. `_character._floor_for` prefers the episode's own stamped
# `thresholds` snapshot when one exists — this is only the fallback for
# a field whose event was disabled, unconfigured, or (for a record
# archived before this feature existed) simply never stamped.
CHARACTER_FLOOR: dict[str, float] = {
    "lightning_potential": 0.2,  # J/kg — thunder detector default
    "precipitation": 5.0,  # mm/h — heavy_rain detector default
    "snowfall": 0.5,  # cm/h — snow detector default
    "wind_gusts_10m": 60.0,  # km/h — storm detector default
    "visibility": 1000.0,  # m — fog detector default ceiling
}
