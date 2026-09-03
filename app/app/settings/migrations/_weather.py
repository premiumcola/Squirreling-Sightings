"""Weather block backfill and the thunder LPI rescale."""

from __future__ import annotations

import logging

from .._consts import (
    EVENT_TL_DEFAULTS,
    SUN_TL_DEFAULTS,
    WEATHER_DEFAULTS,
    WEATHER_RETENTION_DEFAULTS,
)
from ._helpers import _deep_merge_defaults

log = logging.getLogger("app.settings.migrations")


def migrate_weather_defaults(data: dict) -> None:
    """Additively backfill the global weather block + per-camera flag."""
    w = data.setdefault("weather", {})
    if not isinstance(w, dict):
        w = {}
        data["weather"] = w
    _deep_merge_defaults(w, WEATHER_DEFAULTS)
    # Per-category retention (Wetter-Wartung) — setdefault-only, so a
    # real install's existing blanket `retention_days` is left exactly
    # as it is; only the new per-category keys are backfilled.
    _deep_merge_defaults(w, WEATHER_RETENTION_DEFAULTS)
    # Make sure every camera carries the opt-in flag in the new shape;
    # existing cameras with handcrafted weather dicts are left alone.
    # The sun_timelapse sub-block is added unconditionally — it's the
    # nested-default backfill the WeatherService relies on at startup.
    for cam in data.get("cameras", []):
        cw = cam.setdefault("weather", {"enabled": False})
        if not isinstance(cw, dict):
            cam["weather"] = {"enabled": False}
            continue
        cw.setdefault("enabled", False)
        sun_tl = cw.setdefault("sun_timelapse", {})
        if isinstance(sun_tl, dict):
            _deep_merge_defaults(sun_tl, SUN_TL_DEFAULTS)
        evt_tl = cw.setdefault("event_timelapse", {})
        if isinstance(evt_tl, dict):
            _deep_merge_defaults(evt_tl, EVENT_TL_DEFAULTS)


# No plausible LPI threshold is anywhere near this. The physical index
# runs 0.2–0.8 J/kg in observed thunderstorms and tops out in the low
# tens; anything at or above 100 can only have come from reading "J/kg"
# as a CAPE-like quantity.
_LPI_WRONG_SCALE_MIN = 100.0


def migrate_thunder_lpi_scale(data: dict) -> None:
    """Correct a thunder threshold left on the CAPE scale.

    `lightning_potential` is the Lightning Potential Index (Lynn & Yair
    2010), a native ICON-D2 field. Its unit is J/kg, which reads like
    CAPE and is nothing like it: observed thunderstorm cases run
    0.2–0.8 J/kg. The shipped default was 1000.0, so the thunder trigger
    could not fire for any storm that has ever existed — and on
    2026-08-28 it did not, through a thunderstorm the operator watched
    with visible lightning.

    This deliberately OVERWRITES an existing value, which the rest of
    this module never does. The justification is narrow and it matters:
    a threshold three orders of magnitude outside its own index's range
    is not a preference the operator expressed, it is a unit error, and
    leaving it in place would mean the additive-merge rule preserves a
    bug forever. The guard is conservative — only values at or above
    100 are touched, so any hand-tuned LPI number survives untouched.
    """
    events = ((data.get("weather") or {}).get("events") or {}).get("thunder")
    if not isinstance(events, dict):
        return
    try:
        current = float(events.get("threshold"))
    except (TypeError, ValueError):
        return
    if current < _LPI_WRONG_SCALE_MIN:
        return
    corrected = float(WEATHER_DEFAULTS["events"]["thunder"]["threshold"])
    events["threshold"] = corrected
    log.warning(
        "[migration] thunder-Schwelle %.1f J/kg lag auf der CAPE-Skala – "
        "korrigiert auf %.2f J/kg (LPI-Bereich 0.2–0.8)",
        current,
        corrected,
    )
