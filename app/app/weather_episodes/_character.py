"""Deterministic storm-CHARACTER classifier — composition and sequence.

`auto_class` (see `_segment.dominant_event`) answers "which single alarm
fired" from a fixed priority list. This module answers a different
question: "what did the WHOLE curve look like" — which axes actually
moved, and in what ORDER each one reached its own worst reading. Two
storms that trip the same `auto_class` (both "thunder") can still have
completely different shapes: rain building for an hour before the first
strike, versus lightning opening the show with the rain arriving late.
That difference is the whole reason this module exists, and it is
exactly the part a single dominant-event label cannot express. The two
fields are stamped side by side on every record — neither replaces the
other.

Same house rule as `_intensity.py`: arithmetic and explainable, not a
learned model. A storm's character has to read the same way in 2031 as
it did the day it was archived, so every threshold below is a fixed
constant, never a live setting the operator can retune out from under
an already-archived storm.

Two-stage rule table
---------------------
1. COMPOSITION — which of the five ``CHARACTER_FLOOR`` axes are
   "involved" at all. An axis counts as involved when its own peak
   reading crosses a floor: the episode's own stamped threshold
   snapshot when it has one (the same number ``auto_class`` was
   measured against), else the fixed floor in ``_consts.CHARACTER_FLOOR``
   — itself a mirror of this project's shipped detector defaults
   (thunder 0.2 J/kg, heavy_rain 5 mm/h, snow 0.5 cm/h, storm 60 km/h,
   fog's 1000 m ceiling). A record with NO axis past its floor (a
   threshold lowered years after archiving, or a threadbare legacy row)
   falls straight to ``mixed``.

2. SEQUENCE — only for the one pair this vocabulary distinguishes by
   timing: precipitation vs. lightning_potential. When BOTH are
   involved, the axis whose own peak SAMPLE comes first in the curve
   slice decides which of the two sequence characters applies. A tie
   (both axes peak in the very same sample — measurably rare at a
   5-minute poll cadence) falls to ``mixed``: no real ordering could be
   read off the curve, so none is claimed.

Everything else is composition-only::

    involved axes                          -> character
    -----------------------------------------------------------------
    precipitation + lightning_potential,
      precipitation peaks FIRST            -> rain_led_thunder
    precipitation + lightning_potential,
      lightning_potential peaks FIRST      -> lightning_led_rain
    lightning_potential alone              -> lightning_only
    precipitation alone                    -> rain_only
    wind_gusts_10m alone                   -> wind_only
    snowfall alone                         -> snow_only
    visibility alone                       -> fog_only
    anything else (0 axes, or a combination
      the table above does not name)       -> mixed

``totals`` is accepted for the same reason ``_intensity.intensity_score``
takes it — a future refinement may want the episode's accumulated
``precipitation_mm`` as a second vote — but the rule table above does
not read it yet; only ``peaks`` and the samples' own timestamps decide.
"""

from __future__ import annotations

from ._consts import (
    CHARACTER_FLOOR,
    CHARACTER_FOG_ONLY,
    CHARACTER_LIGHTNING_LED_RAIN,
    CHARACTER_LIGHTNING_ONLY,
    CHARACTER_MIXED,
    CHARACTER_RAIN_LED_THUNDER,
    CHARACTER_RAIN_ONLY,
    CHARACTER_SNOW_ONLY,
    CHARACTER_WIND_ONLY,
    FIELD_DIRECTION,
)
from ._thresholds import crossed

# Single-axis composition -> character, for every axis this vocabulary
# names on its own. The precipitation/lightning_potential pair is
# handled separately (_sequence_character) because it is the one
# combination whose TIMING, not just its presence, picks the slug.
_SINGLE_AXIS_CHARACTER: dict[str, str] = {
    "lightning_potential": CHARACTER_LIGHTNING_ONLY,
    "precipitation": CHARACTER_RAIN_ONLY,
    "wind_gusts_10m": CHARACTER_WIND_ONLY,
    "snowfall": CHARACTER_SNOW_ONLY,
    "visibility": CHARACTER_FOG_ONLY,
}


def _floor_for(field: str, thresholds: dict | None) -> float | None:
    """This episode's own trigger line for ``field``, or the fixed fallback.

    Preferring the stamped snapshot means a user who raises the
    heavy_rain threshold also raises what "rain involved" means for
    every episode archived AFTER that change, while an episode whose
    event was disabled — or one archived before this feature existed —
    still gets a sane answer from CHARACTER_FLOOR instead of being
    unclassifiable.
    """
    val = (thresholds or {}).get(field)
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    return CHARACTER_FLOOR.get(field)


def _involved_axes(peaks: dict, thresholds: dict | None) -> set[str]:
    """Every CHARACTER_FLOOR axis whose peak is on the alarm side of its floor."""
    out: set[str] = set()
    for field in CHARACTER_FLOOR:
        val = (peaks or {}).get(field)
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            continue
        floor = _floor_for(field, thresholds)
        if floor is None:
            continue
        spec = {"threshold": floor, "direction": FIELD_DIRECTION.get(field, "above")}
        if crossed(float(val), spec):
            out.add(field)
    return out


def _axis_peak_ts(samples: list, field: str) -> str | None:
    """ISO timestamp of this ONE axis's own worst reading in the slice.

    Mirrors ``_build._peaks``' worse-of-two-values direction handling
    but keeps the TIMESTAMP instead of the value — sequence is the
    entire point here. ISO strings compare lexically like everywhere
    else in this package (see ``_store.list_episodes``), so no datetime
    parsing is needed.
    """
    inverted = FIELD_DIRECTION.get(field) == "below"
    best_ts: str | None = None
    best_val: float | None = None
    for s in samples or []:
        if not isinstance(s, dict):
            continue
        val = (s.get("values") or {}).get(field)
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            continue
        if best_val is None or (val < best_val if inverted else val > best_val):
            best_val = val
            best_ts = s.get("ts")
    return best_ts


def _sequence_character(samples: list) -> str:
    """Decide between rain_led_thunder / lightning_led_rain.

    Called only once both axes are already known to be involved.
    """
    rain_ts = _axis_peak_ts(samples, "precipitation")
    light_ts = _axis_peak_ts(samples, "lightning_potential")
    if not rain_ts or not light_ts or rain_ts == light_ts:
        return CHARACTER_MIXED
    return CHARACTER_RAIN_LED_THUNDER if rain_ts < light_ts else CHARACTER_LIGHTNING_LED_RAIN


def classify_character(
    samples: list, peaks: dict, totals: dict | None = None, thresholds: dict | None = None
) -> str:
    """The episode's character. See the module docstring for the rule table."""
    involved = _involved_axes(peaks, thresholds)
    if not involved:
        return CHARACTER_MIXED
    if "precipitation" in involved and "lightning_potential" in involved:
        return _sequence_character(samples)
    if len(involved) == 1:
        return _SINGLE_AXIS_CHARACTER.get(next(iter(involved)), CHARACTER_MIXED)
    return CHARACTER_MIXED
