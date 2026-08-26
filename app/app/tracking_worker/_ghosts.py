"""L07 · the ghost-track filter.

Drops tracks the IoU matcher held together across frames but that the
live pipeline would never have notified on — the "stone labelled
Person 23 %" class. A track survives when its best score reached the
per-label spawn threshold, or when the camera's confirmation window
would have promoted it anyway (the faint-but-persistent squirrel at
dusk).
"""

from __future__ import annotations

import logging

from ._consts import DEFAULT_CONFIRM_N, DEFAULT_CONFIRM_SECONDS, DEFAULT_MIN_SCORE
from ._samples import confirmed_in_window

log = logging.getLogger(__name__)

# TODO: re-index existing events to retroactively drop ghost tracks
# from pre-L07 sidecars. Needs an admin endpoint that iterates
# storage/motion_detection/<cam>/<date>/*.tracks.json, re-applies
# prune_ghost_tracks with each cam's CURRENT config, and rewrites
# the sidecar. Out of scope for the initial L07 commit — only NEW
# clips get the cleanup until that ships.


def _coerce_float(value, fallback: float) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return fallback


def confirm_window_defaults(cam_cfg: dict) -> tuple[dict, int, float]:
    """``(confirmation_window block, default_n, default_seconds)`` for a
    camera. The ``global`` sub-block sets the fallback used for labels
    with no entry of their own; an absent block leaves the wizard
    defaults in place."""
    cw_cfg = (cam_cfg or {}).get("confirmation_window") or {}
    global_cw = cw_cfg.get("global") or {}
    n = int(global_cw.get("n", DEFAULT_CONFIRM_N))
    secs = float(global_cw.get("seconds", DEFAULT_CONFIRM_SECONDS))
    return cw_cfg, n, secs


def window_for_label(cw_cfg: dict, label: str, default_n: int, default_secs: float):
    """``(n, seconds)`` the confirmation window uses for ``label``."""
    cw = cw_cfg.get(label) or {"n": default_n, "seconds": default_secs}
    return int(cw.get("n", default_n)), float(cw.get("seconds", default_secs))


def spawn_threshold_fn(cam_cfg: dict, detection_cfg: dict):
    """Build the per-label spawn-threshold lookup, mirroring the live path:

        1. cam_cfg.label_thresholds[label]   (non-zero)
        2. cam_cfg.detection_min_score       (non-zero)
        3. detection_cfg["min_score"]        (global default)

    The per-camera ``track_spawn_min_score`` (non-zero) is a FLOOR on
    top of that — ``max(per-label, per-cam-floor)`` is the threshold a
    track must clear, same rule ``resolve_track_thresholds`` applies
    cam-wide."""
    label_thresholds = (cam_cfg or {}).get("label_thresholds") or {}
    cam_dms = _coerce_float((cam_cfg or {}).get("detection_min_score"), 0.0)
    global_dms = _coerce_float((detection_cfg or {}).get("min_score"), DEFAULT_MIN_SCORE)
    if not global_dms:
        global_dms = DEFAULT_MIN_SCORE
    cam_spawn_floor = _coerce_float((cam_cfg or {}).get("track_spawn_min_score"), 0.0)

    def _effective(label: str) -> float:
        per_label = None
        raw = label_thresholds.get(label)
        try:
            if raw is not None:
                candidate = float(raw)
                if candidate > 0:
                    per_label = candidate
        except (TypeError, ValueError):
            per_label = None
        if per_label is None:
            per_label = cam_dms if cam_dms > 0 else global_dms
        return max(per_label, cam_spawn_floor)

    return _effective


def prune_ghost_tracks(state, *, cam_cfg: dict, detection_cfg: dict, camera_id: str) -> int:
    """Drop ghost tracks from ``state.closed`` in place; return the drop
    count so the caller can summarise. Idempotent."""
    if not state.closed:
        return 0
    effective_for = spawn_threshold_fn(cam_cfg, detection_cfg)
    cw_cfg, default_n, default_secs = confirm_window_defaults(cam_cfg)

    survivors = []
    dropped = 0
    for tr in state.closed:
        lbl = tr.label or "unknown"
        effective = effective_for(lbl)
        best = float(tr.best_score or 0.0)
        if best >= effective:
            survivors.append(tr)
            continue
        # Below spawn threshold — confirmation window override. A
        # consistently-seen-but-faint subject that the confirmer would
        # have promoted in the live path is NOT a ghost; keep it.
        n, secs = window_for_label(cw_cfg, lbl, default_n, default_secs)
        if confirmed_in_window(tr.samples, n, secs):
            survivors.append(tr)
            continue
        log.info(
            "[tracking] cam=%s GHOST dropped: tid=%s label=%s best=%.2f < spawn=%.2f",
            camera_id,
            tr.track_id,
            lbl,
            best,
            effective,
        )
        dropped += 1

    if dropped:
        state.closed = survivors
    return dropped
