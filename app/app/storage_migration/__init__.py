"""One-shot storage migration to the semantic camera-id scheme.

Idempotent: safe to call on every boot. Walks every camera in
``settings.json``, computes the new canonical id via
``camera_id.build_camera_id``, and consolidates legacy storage folders
under each of the four per-camera storage areas:

    motion_detection/  timelapse_frames/  timelapse/  weather/

After the per-camera loop:

    - event JSONs in motion_detection/<new_id>/ have their
      ``video_relpath`` / ``snapshot_relpath`` rewritten to the new id
    - settings.json's ``id`` field is updated for every renamed camera
    - settings.json is backed up to ``settings.json.bak.<timestamp>``
      before any change is persisted (extra safety net beyond the
      existing 2-deep rotation)
    - the empty ``storage/object_detection/`` placeholder is rmdir'd

Failure handling: a single failed move is logged at ERROR but never
aborts the whole run — partial progress is fine because the next boot
picks up where we stopped. A failed ``settings.save()`` triggers a
restore from the timestamped backup.

Was a single 546-line module; split at its own seams to get back under
CLAUDE.md's 500-line file and 80-line function ceilings. The import site
is unchanged — ``from .storage_migration import migrate`` still works.

  _consts.py   — areas, backup-name regex, the logger
  _naming.py   — how a legacy folder name is matched to a camera
  _moves.py    — moving files, repointing the event JSONs that name them
  _plan.py     — pass 1: what each camera needs, no disk writes
  _backups.py  — the migration's own timestamped settings backup
  _run.py      — pass 2: apply, persist, report
"""

from __future__ import annotations

from ._backups import _prune_old_settings_backups
from ._run import migrate

__all__ = ["migrate", "_prune_old_settings_backups"]
