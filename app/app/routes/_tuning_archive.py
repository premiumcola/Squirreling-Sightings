"""The Verlauf side of ``PATCH /api/cameras/<id>/detection-tuning``.

Its own module rather than a fourth helper inside cameras.py: that file
sits at ~460 lines against a 500-line ceiling, and the archive is an
orthogonal concern to the range-validation that fills the rest of the
route. Everything about WHAT a record looks like lives in
``net_archive/_tuning.py``; this is only the glue that knows about
``app_state`` and must never let an archive failure fail a save.
"""

from __future__ import annotations

import logging

from .. import app_state, net_archive

log = logging.getLogger(__name__)


def archive_tuning_change(cam_id: str, cam: dict, before: dict) -> int:
    """One archive record per camera-wide field that actually moved.

    Until this existed, ``PATCH /api/netz/<cam>/axes`` archived every
    per-class threshold drag and the camera-tuning route archived
    nothing — so half of what the Erkennungsprofil can change had no
    history, and the archive looked complete anyway.

    Returns how many records were written; 0 when nothing changed, which
    is the common case for a save that only re-sends what was on screen.
    """
    try:
        changes = net_archive.tuning_changes(before, cam)
        if not changes:
            return 0
        return net_archive.record_tuning_changes(
            app_state.storage_root,
            cam_id=cam_id,
            cam_name=cam.get("name") or cam_id,
            changes=changes,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("[det] Verlauf-Eintrag für %s nicht geschrieben: %s", cam_id, exc)
        return 0
