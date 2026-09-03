"""Pass 2: apply the plans, persist, and report.

Idempotent by construction: Pass 1 (:mod:`._plan`) finds nothing to do on
a settled install, so ``migrate`` short-circuits to a single INFO line
and only the backup prune runs.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ._backups import (
    _backup_settings_partial,
    _promote_or_discard_partial,
    _prune_old_settings_backups,
    _resolve_backup_keep,
)
from ._consts import _AREAS, log
from ._moves import _merge_folder, _rewrite_event_jsons
from ._plan import _plan_camera


def _noop_summary(cameras: int, pruned: int) -> dict:
    """The shape both short-circuit exits return."""
    return {
        "cameras": cameras,
        "merges": 0,
        "rewrites": 0,
        "noop": True,
        "changed": False,
        "backup_retained": False,
        "pruned": pruned,
    }


def _analyse(cams: list, storage_root: Path) -> tuple[list, bool]:
    """Pass 1: analysis only, no disk writes."""
    plans: list[dict] = []
    needs_work = False
    for cam in cams:
        plan = _plan_camera(cam, storage_root)
        plans.append(plan)
        if plan["id_changed"] or any(plan["areas"][a] for a in _AREAS):
            needs_work = True
    return plans, needs_work


def _apply_plans(cams: list, plans: list, storage_root: Path) -> tuple[int, int, int]:
    """Merge the folders, repoint the event JSONs, restamp the ids.

    Returns ``(merges, rewrites, id_changes)``.
    """
    total_merges = 0
    total_rewrites = 0
    id_changes = 0
    for cam, plan in zip(cams, plans):
        new_id = plan["new_id"]
        old_id = plan["old_id"]
        for area in _AREAS:
            sources: list[Path] = plan["areas"][area]
            if not sources:
                continue
            target = storage_root / area / new_id
            for src in sources:
                moved = _merge_folder(src, target)
                if moved > 0 or not src.exists():
                    log.info(
                        "[migration] %s: merged %s → %s (%d files)", area, src.name, new_id, moved
                    )
                    total_merges += 1
        # Rewrite event JSONs in the target motion_detection folder so any
        # stored video_relpath / snapshot_relpath that still says "<old_id>"
        # points at the new path.
        ev_dir = storage_root / "motion_detection" / new_id
        old_candidates = [old_id]
        if plan["ip_dashes"]:
            old_candidates.append(f"cam-{plan['ip_dashes']}")
        total_rewrites += _rewrite_event_jsons(ev_dir, old_candidates, new_id)
        if plan["id_changed"]:
            cam["id"] = new_id
            id_changes += 1
    return total_merges, total_rewrites, id_changes


def _persist_settings(settings_store, id_changes: int, backup_partial) -> bool:
    """Save settings.json, restoring from the partial if the save fails.

    The partial has not been promoted yet, but it is on disk under the
    ``.partial`` name and is the freshest pre-mutation snapshot we have.
    """
    if id_changes <= 0:
        return True
    try:
        settings_store.save()
        return True
    except Exception as e:
        partial_name = backup_partial.name if backup_partial else "?"
        log.error("[migration] settings.json save failed (%s) — restoring from %s", e, partial_name)
        if backup_partial and backup_partial.exists():
            try:
                shutil.copy2(str(backup_partial), str(settings_store.path))
            except Exception as e2:
                log.error("[migration] settings restore also failed: %s", e2)
        return False


def _prune_object_detection(obj_det: Path) -> bool:
    """Remove the orphaned placeholder dir, if it is empty."""
    if not (obj_det.exists() and obj_det.is_dir()):
        return False
    try:
        obj_det.rmdir()  # only succeeds when empty
    except OSError:
        return False  # not empty — leave it
    log.info("[migration] removed empty placeholder dir storage/object_detection/")
    return True


def _log_run(summary: dict, retained, pruned: int) -> None:
    """The single boot line describing what Pass 2 did."""
    if retained is not None:
        log.info(
            "[migration] processed %d cameras, %d folder merges, %d event JSONs rewritten · "
            "backup retained=1 pruned=%d (%s)",
            summary["cameras"],
            summary["merges"],
            summary["rewrites"],
            pruned,
            retained.name,
        )
    else:
        log.info(
            "[migration] processed %d cameras, %d folder merges, %d event JSONs rewritten · "
            "backup skipped (no changes) pruned=%d",
            summary["cameras"],
            summary["merges"],
            summary["rewrites"],
            pruned,
        )


def migrate(settings_store, storage_root) -> dict:
    """Run the migration once. Always safe to call — the analysis pass
    short-circuits to a single INFO line when nothing's stale.

    Returns a summary dict for the caller's log line."""
    storage_root = Path(storage_root)
    keep_n = _resolve_backup_keep(settings_store)
    cams = list(settings_store.data.get("cameras", []) or [])
    if not cams:
        # Even on a "no cameras" boot, prune any leftover history from
        # a prior config so heavy dev cycles don't pile up indefinitely.
        pruned = _prune_old_settings_backups(settings_store, keep=keep_n)
        log.info("[migration] no cameras configured — nothing to migrate. pruned=%d", pruned)
        return _noop_summary(0, pruned)

    plans, needs_work = _analyse(cams, storage_root)

    # Empty object_detection cleanup is part of "needs_work" too — the
    # whole boot-time pass should be a single observable unit.
    obj_det = storage_root / "object_detection"
    obj_det_empty_dir = obj_det.exists() and obj_det.is_dir() and not any(obj_det.iterdir())

    if not needs_work and not obj_det_empty_dir:
        # Idle boots still get the prune pass so old history shrinks
        # over time even when Pass 2 never runs.
        pruned = _prune_old_settings_backups(settings_store, keep=keep_n)
        log.info(
            "[migration] all storage paths already in canonical form — no migration needed. "
            "backup skipped (no changes) pruned=%d",
            pruned,
        )
        return _noop_summary(len(cams), pruned)

    # Pass 2 takes its tagged settings backup AS A PARTIAL first; see
    # _backups for why it is only promoted at the end.
    backup_final, backup_partial = _backup_settings_partial(settings_store)

    total_merges, total_rewrites, id_changes = _apply_plans(cams, plans, storage_root)
    settings_save_ok = _persist_settings(settings_store, id_changes, backup_partial)
    obj_det_pruned = _prune_object_detection(obj_det)

    # Did Pass 2 actually mutate state? Folder merges, event JSON
    # rewrites, settings.json id changes, and the obj_det rmdir each
    # count as a real change worth keeping a backup for. ``changed``
    # is the single condition that drives partial-backup promotion
    # AND the boot log shape — kept on the summary so callers and
    # tests share one source of truth.
    actually_changed = bool(total_merges or total_rewrites or id_changes or obj_det_pruned)
    retained = _promote_or_discard_partial(
        backup_final,
        backup_partial,
        actually_changed=actually_changed and settings_save_ok,
    )
    pruned = _prune_old_settings_backups(settings_store, keep=keep_n)

    summary = {
        "cameras": len(cams),
        "merges": total_merges,
        "rewrites": total_rewrites,
        "id_changes": id_changes,
        "obj_det_pruned": obj_det_pruned,
        "backup": str(retained) if retained else None,
        "backup_retained": retained is not None,
        "pruned": pruned,
        "changed": actually_changed,
        "save_ok": settings_save_ok,
        "noop": False,
    }
    _log_run(summary, retained, pruned)
    return summary
