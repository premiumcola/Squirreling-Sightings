"""Camera-timelapse retention — the category that was exempt on purpose.

``storage_retention._collect_expired`` skips every ``tl_*`` id, and the
module docstring next to it says why: ``tl_<stem>.json`` is the *single*
record of an mp4 that lives under ``timelapse/``, outside the swept
tree. Deleting the record alone made the April tile vanish, come back at
the next boot (``media_index/_timelapse.register_timelapse_events``
re-registers it from the mp4) and vanish again. That exemption stays
exactly as it is — nothing here changes ``cleanup_old``.

What was missing is a sweep that can retire the whole thing: the mp4,
its thumbnail, its QA sidecar AND the manifest, together, as one trash
entry. Half of that pair is what caused the ghost tile; both halves is a
deletion the archive can actually represent, and ``trash.restore`` puts
every file back at its recorded path.

Three rules this module keeps:

* **Off unless asked.** The window ships as 0 = "nie löschen"
  (``CAMERA_TIMELAPSE_RETENTION_DAYS_DEFAULT``) and a window ≤ 0 returns
  before a cutoff is even computed. No install starts deleting timelapses
  because it upgraded — a category that has never been mortal does not
  become mortal by default.
* **Nothing is unlinked.** Files go to ``storage/.trash`` and live out
  ``trash.grace_days`` there, same as the motion sweep.
* **A judged timelapse is immortal**, on the same
  ``storage.keep_judged_events`` switch and the same id set the motion
  sweep uses.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from .storage_retention import (
    MIN_RETENTION_DAYS,
    TIMELAPSE_ID_PREFIX,
    judged_event_ids,
    keep_judged_events_enabled,
)

log = logging.getLogger(__name__)

#: Companion extensions of one timelapse stem under ``timelapse/<cam>/``:
#: the video, the thumbnail ``media_index`` links as ``snapshot_relpath``,
#: and the metadata sidecar ``camera_runtime/_timelapse`` writes. They are
#: companions of ONE recording — the same reason ``_collect_expired``
#: groups motion files by ``(camera, event_id)`` — so they are retired as
#: one entry or not at all.
_COMPANION_SUFFIXES = (".mp4", ".jpg", ".json")


def _expired_stems(cam_dir: Path, cutoff: datetime) -> list[str]:
    """Stems under one camera's timelapse dir whose mp4 predates
    ``cutoff``. The mp4 is the anchor: a stray sidecar without a video is
    not a recording and is left for the integrity report."""
    stems: list[str] = []
    for mp4 in sorted(cam_dir.glob("*.mp4")):
        try:
            if datetime.fromtimestamp(mp4.stat().st_mtime) >= cutoff:
                continue
        except OSError:
            continue
        stems.append(mp4.stem)
    return stems


def _companion_paths(cam_dir: Path, events_dir: Path, cam_id: str, stem: str) -> list[Path]:
    paths = [cam_dir / f"{stem}{suffix}" for suffix in _COMPANION_SUFFIXES]
    # The manifest lands in the camera ROOT of the event store, because
    # `event_date_subdir("tl_…")` returns None for it.
    paths.append(events_dir / cam_id / f"{TIMELAPSE_ID_PREFIX}{stem}.json")
    return [p for p in paths if p.exists()]


def sweep_camera_timelapses(store, retention_days: int, keep_judged: bool | None = None) -> int:
    """Retire camera timelapses older than ``retention_days`` — video,
    thumbnail, sidecar and ``tl_*`` manifest as one trash entry.

    Anything below :data:`~storage_retention.MIN_RETENTION_DAYS` — 0
    included, which is this row's "nie löschen" position — returns 0
    without touching the disk. The caller must apply that check BEFORE
    the widening guard: the guard's job is to defer a narrowing until
    confirmed, and it would happily hand back a previously-enforced 30
    for a row the operator has just switched off.

    Returns the number of files retired.
    """
    if retention_days < MIN_RETENTION_DAYS:
        return 0
    root = Path(store.root)
    tl_root = root / "timelapse"
    if not tl_root.is_dir():
        return 0
    if keep_judged is None:
        keep_judged = keep_judged_events_enabled()
    judged = judged_event_ids(store.events_dir) if keep_judged else set()
    cutoff = datetime.now() - timedelta(days=retention_days)
    from .trash import retire_to_trash

    retired = 0
    preserved = 0
    for cam_dir in sorted(d for d in tl_root.iterdir() if d.is_dir()):
        cam_id = cam_dir.name
        for stem in _expired_stems(cam_dir, cutoff):
            event_id = f"{TIMELAPSE_ID_PREFIX}{stem}"
            if event_id in judged:
                preserved += 1
                continue
            paths = _companion_paths(cam_dir, store.events_dir, cam_id, stem)
            if paths:
                retired += retire_to_trash(root, cam_id, event_id, paths)
    if preserved:
        log.info(
            "[timelapse] autoclean: %d bestätigte Timelapses geschützt "
            "(storage.keep_judged_events)",
            preserved,
        )
    if retired:
        log.info(
            "[timelapse] autoclean: %d Dateien älter als %d Tage in den Papierkorb "
            "verschoben (Video, Thumbnail und Mediathek-Eintrag zusammen)",
            retired,
            retention_days,
        )
    else:
        log.info("[timelapse] autoclean: nichts älter als %d Tage", retention_days)
    return retired
