"""Resolve the per-field trigger lines from the configured weather events.

There is exactly one threshold system in this project — the one the live
detectors already fire on, stored under ``settings.weather.events``. The
archive reads the same numbers through ``HISTORY_FIELD_TO_EVENT`` rather
than growing a parallel set, so a user who raises the thunder threshold
also changes what counts as a thunder EPISODE.
"""

from __future__ import annotations

from ..weather_service import HISTORY_FIELD_TO_EVENT
from ._consts import DEFAULT_THRESHOLD_KEY, EVENT_THRESHOLD_KEY, FIELD_DIRECTION, log


def _default_events_cfg() -> dict:
    """WEATHER_DEFAULTS["events"], imported late.

    Module-level would drag app.settings (and therefore SettingsStore)
    into every importer of this leaf package for a dict of four numbers.
    """
    try:
        from ..settings._consts import WEATHER_DEFAULTS

        return WEATHER_DEFAULTS.get("events") or {}
    except Exception as e:  # pragma: no cover - defensive
        log.warning("[weather] episode thresholds: defaults unavailable: %s", e)
        return {}


def resolve_thresholds(events_cfg: dict | None) -> dict:
    """Map each history field to the trigger it is measured against.

    Returns ``{field: {"event": str, "threshold": float, "direction": str}}``
    for every field whose event is enabled and carries a usable numeric
    threshold. A disabled event contributes nothing: the user has said
    that condition is not an event on this install, and the archive
    follows that. Already-archived episodes are unaffected — the ledger
    is append-only.
    """
    cfg = events_cfg if isinstance(events_cfg, dict) else {}
    defaults = _default_events_cfg()
    out: dict = {}
    for field, evt in HISTORY_FIELD_TO_EVENT.items():
        ev_cfg = cfg.get(evt)
        if not isinstance(ev_cfg, dict):
            ev_cfg = defaults.get(evt) or {}
        if not ev_cfg.get("enabled", True):
            continue
        key = EVENT_THRESHOLD_KEY.get(evt, DEFAULT_THRESHOLD_KEY)
        raw = ev_cfg.get(key)
        if raw is None:
            raw = (defaults.get(evt) or {}).get(key)
        try:
            threshold = float(raw)
        except (TypeError, ValueError):
            continue
        out[field] = {
            "event": evt,
            "threshold": threshold,
            "direction": FIELD_DIRECTION.get(field, "above"),
        }
    return out


def crossed(value, spec: dict) -> bool:
    """True when ``value`` is on the alarm side of ``spec``'s threshold."""
    if not isinstance(value, (int, float)):
        return False
    thr = spec.get("threshold")
    if thr is None:
        return False
    if spec.get("direction") == "below":
        return float(value) < float(thr)
    return float(value) >= float(thr)
