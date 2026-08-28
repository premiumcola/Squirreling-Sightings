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

from ._consts import DEFAULT_CONFIRM_N, DEFAULT_CONFIRM_SECONDS
from ._samples import confirmed_in_window

log = logging.getLogger(__name__)

# TODO: re-index existing events to retroactively drop ghost tracks
# from pre-L07 sidecars. Needs an admin endpoint that iterates
# storage/motion_detection/<cam>/<date>/*.tracks.json, re-applies
# prune_ghost_tracks with each cam's CURRENT config, and rewrites
# the sidecar. Out of scope for the initial L07 commit — only NEW
# clips get the cleanup until that ships.


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


def spawn_threshold_fn(cam_cfg: dict):
    """The per-label spawn threshold, resolved through the ONE ladder.

    P4 · this used to carry a third, hand-rolled resolution order with a
    ``0.55`` fallback where the live loop uses ``TRACK_SPAWN_SCORE``
    0.50. The consequence was concrete and invisible: ``dog`` and
    ``car`` spawned a track at 0.50 during the clip and were then pruned
    from the sidecar after it against a bar five points higher, so the
    lightbox lost tracks the live pipeline had genuinely followed.

    ``resolve_effective`` is the one place that knows the camera >
    adapted > global > default order. Reading it here means the prune
    can no longer disagree with the spawn.
    """
    from ..thresholds import resolve_effective
    from ..thresholds._apply import adapted_layer

    adapted = {}

    def _effective(label: str) -> float:
        if label not in adapted:
            adapted[label] = adapted_layer(cam_cfg, label)
        return resolve_effective(cam_cfg, None, label, adapted=adapted[label]).spawn

    return _effective


def prune_ghost_tracks(state, *, cam_cfg: dict, camera_id: str) -> int:
    """Drop ghost tracks from ``state.closed`` in place; return the drop
    count so the caller can summarise. Idempotent."""
    if not state.closed:
        return 0
    effective_for = spawn_threshold_fn(cam_cfg)
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
