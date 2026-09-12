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
from ._splinters import prune_splinter_tracks
from ._static_fp import filter_static_false_positives
from ._stitch import stitch_tracklets_offline

log = logging.getLogger(__name__)


def clean_tracks(state, *, camera_id: str, cam_cfg: dict, spawn_score: float) -> None:
    """Stitch, drop static false positives, drop splinters, prune ghosts.

    Stitching goes FIRST so a real person re-assembled from fragments
    presents her combined motion to the static-FP gate and survives it —
    and so the splinter sweep after it judges against the ASSEMBLED
    subject, not against one of its pieces.

    The splinter sweep sits before the ghost prune for the same reason
    the static-FP sweep does: both are about what the track IS, while
    the ghost prune is about how confident the model ever was. Each of
    the last two can be switched off on its own — a camera looking down
    a long driveway may legitimately see one person at a quarter the
    height of another.
    """
    n_stitched = stitch_tracklets_offline(state)
    if n_stitched:
        log.info("[tracking] stitched %d tracklet(s) (offline)", n_stitched)

    filter_static_false_positives(state, spawn_score)

    if cam_cfg.get("track_filter_splinters") is not False:
        n_splinters = prune_splinter_tracks(state, camera_id=camera_id)
        if n_splinters:
            log.info(
                "[tracking] cam=%s pruned %d splinter track(s) from sidecar",
                camera_id,
                n_splinters,
            )

    if cam_cfg.get("track_filter_ghosts") is False:
        return
    n_ghosts = prune_ghost_tracks(state, cam_cfg=cam_cfg, camera_id=camera_id)
    if n_ghosts:
        log.info(
            "[tracking] cam=%s pruned %d ghost track(s) from sidecar",
            camera_id,
            n_ghosts,
        )
