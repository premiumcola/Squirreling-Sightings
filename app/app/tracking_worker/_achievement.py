"""Tracks-derived aggregates merged back into the event JSON.

The worker has no access to the live confirmer's runtime state, so
"would this have confirmed?" is re-derived purely from the sample
stream — the same sliding window :mod:`._samples` gives the ghost
prune, so the sidecar and the achievement block can never disagree.

Strictly additive: fields already on the event (inference_avg_ms and
friends, written synchronously at finalize) are never overwritten, and
every failure here is logged at INFO and swallowed — the tracks.json
we just produced must survive a broken event store.
"""

from __future__ import annotations

import logging

from ._ghosts import confirm_window_defaults, window_for_label
from ._samples import confirmed_in_window, detect_samples

log = logging.getLogger(__name__)


def aggregate_track_stats(tracks, cam_cfg: dict) -> dict:
    """Fold serialised tracks into ``{tracks_by_class, peak_score_by_class,
    confirm_hits_by_track}``. Keys with nothing to say are omitted so the
    caller can merge without clobbering."""
    cw_cfg, default_n, default_secs = confirm_window_defaults(cam_cfg)
    tracks_by_class: dict[str, int] = {}
    peak_score_by_class: dict[str, float] = {}
    confirm_hits: list[dict] = []

    for tr in tracks or []:
        lbl = tr.get("label") or "unknown"
        tracks_by_class[lbl] = tracks_by_class.get(lbl, 0) + 1
        best = float(tr.get("best_score") or 0.0)
        if best > peak_score_by_class.get(lbl, 0.0):
            peak_score_by_class[lbl] = best
        samples = tr.get("samples") or []
        span_seconds = 0.0
        if len(samples) >= 2:
            span_seconds = round(
                float(samples[-1].get("t", 0)) - float(samples[0].get("t", 0)),
                2,
            )
        n, secs = window_for_label(cw_cfg, lbl, default_n, default_secs)
        confirm_hits.append(
            {
                "track_id": tr.get("track_id"),
                "label": lbl,
                "hit_count": len(detect_samples(samples)),
                "span_seconds": span_seconds,
                "confirmed": confirmed_in_window(samples, n, secs),
            }
        )

    out: dict = {}
    if tracks_by_class:
        out["tracks_by_class"] = tracks_by_class
    # Round peaks to 4 decimals so the JSON stays compact and the
    # frontend can compare against per-class thresholds cleanly.
    if peak_score_by_class:
        out["peak_score_by_class"] = {k: round(v, 4) for k, v in peak_score_by_class.items()}
    if confirm_hits:
        out["confirm_hits_by_track"] = confirm_hits
    return out


def update_event_achievement(store, camera_id: str, event_id: str, tracks, cam_cfg: dict) -> None:
    """Merge the aggregates into the event JSON's achievement block."""
    try:
        ev = store.get_event(camera_id, event_id) or {}
        if not ev:
            return
    except Exception as e:
        log.info("[tracking] event=%s achievement read skipped: %s", event_id, e)
        return
    ach = dict(ev.get("achievement") or {})
    ach.update(aggregate_track_stats(tracks, cam_cfg))
    ev["achievement"] = ach
    try:
        store.update_event(camera_id, event_id, ev)
    except Exception as e:
        log.info("[tracking] event=%s achievement write skipped: %s", event_id, e)
