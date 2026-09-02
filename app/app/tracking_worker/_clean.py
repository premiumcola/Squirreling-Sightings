"""The three post-association sweeps, in the order they must run.

Lifted out of `TrackingWorker._clean_tracks` when the clip-replay
feature needed the same cleanup from a request thread. Two callers, one
implementation: a replay that stitched differently from the sidecar it
is being compared against would report differences the settings did not
cause.
"""

from __future__ import annotations

import logging

from ._ghosts import prune_ghost_tracks
from ._static_fp import filter_static_false_positives
from ._stitch import stitch_tracklets_offline

log = logging.getLogger(__name__)


def clean_tracks(state, *, camera_id: str, cam_cfg: dict, spawn_score: float) -> None:
    """Stitch, then drop static false positives, then prune ghosts.

    Stitching goes FIRST so a real person re-assembled from fragments
    presents her combined motion to the static-FP gate and survives it.
    The ghost prune goes last because it is the only sweep a camera can
    switch off (``cam_cfg.track_filter_ghosts=False``; default on, so
    existing cameras pick the cleanup up on their next save).
    """
    n_stitched = stitch_tracklets_offline(state)
    if n_stitched:
        log.info("[tracking] stitched %d tracklet(s) (offline)", n_stitched)

    filter_static_false_positives(state, spawn_score)

    if cam_cfg.get("track_filter_ghosts") is False:
        return
    n_ghosts = prune_ghost_tracks(state, cam_cfg=cam_cfg, camera_id=camera_id)
    if n_ghosts:
        log.info(
            "[tracking] cam=%s pruned %d ghost track(s) from sidecar",
            camera_id,
            n_ghosts,
        )
