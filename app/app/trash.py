"""Soft-delete with grace period — events go into ``storage/.trash/``
on delete and stay there for ``trash.grace_days`` (default 7) before a
daily sweep hard-deletes them. Users can restore individual events or
empty the trash now via the ``/api/trash/*`` endpoints in
``routes/trash.py``.

Motion-event deletes route through ``move_to_trash`` instead of
``EventStore.delete_event``. The nightly retention sweep routes through
:func:`retire_to_trash` for the same reason: it used to be a hard
``unlink`` with no grace and no undo, which made every change to
``storage.retention_days`` irreversible the first night it took effect.
The weather-sighting / timelapse delete handlers still hard-delete.

Layout::

    storage/.trash/<cam_id>/<event_id>/
        meta.json            (trashed_at + original paths)
        <event_id>.json      (the original event manifest)
        <event_id>.jpg       (snapshot)
        <event_id>.mp4       (video)
        <event_id>.tracks.json   (optional)
        <event_id>.best.jpg      (optional)

``meta.json`` is the source of truth for restore — it carries the
relative path the JSON manifest originally lived at, so a restore
puts the files back under exactly ``storage/motion_detection/<cam>/
<date>/<event_id>.*`` even when the date subdir wouldn't otherwise
be reconstructible from the event_id alone."""

from __future__ import annotations

import contextlib
import json
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from . import app_state
from .settings._consts import TRASH_DEFAULTS

log = logging.getLogger("trash")


#: Imported, not restated: `settings/retention_migration.py` seeds the
#: same number into settings.json, and a sweep whose fallback disagreed
#: with the seeded value would purge on a different day than the panel
#: promises.
_DEFAULT_GRACE_DAYS = TRASH_DEFAULTS["grace_days"]


def trash_root_for(store_root) -> Path:
    """``.trash`` under an explicitly given storage root.

    ``EventStore`` knows its own root and must not have to reach through
    ``app_state`` to find the trash — the retention sweep runs on the
    store instance it was called on, including in tests where no boot
    singleton exists.
    """
    return Path(store_root) / ".trash"


def _trash_root() -> Path:
    return trash_root_for(app_state.store.root)


def _grace_days() -> int:
    settings = getattr(app_state, "settings", None)
    if settings is None:
        return _DEFAULT_GRACE_DAYS
    v = (settings.data.get("trash") or {}).get("grace_days", _DEFAULT_GRACE_DAYS)
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return _DEFAULT_GRACE_DAYS


def move_to_trash(cam_id: str, event_id: str) -> dict:
    """Move every file belonging to ``(cam_id, event_id)`` into the
    trash dir and write a ``meta.json`` carrying the original relative
    paths so restore can put them back. Returns the same flag dict
    shape ``EventStore.delete_event`` does, plus ``trashed:True`` on
    success — callers can substitute one for the other."""
    store = app_state.store
    cam_root = Path(store.root) / "motion_detection" / cam_id
    matches = list(cam_root.rglob(f"{event_id}.json"))
    if not matches:
        return {
            "json_deleted": False,
            "snap_deleted": False,
            "vid_deleted": False,
            "tracks_deleted": False,
            "trashed": False,
        }
    json_path = matches[0]
    try:
        event = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        event = {}
    trash_dir = _trash_root() / cam_id / event_id
    trash_dir.mkdir(parents=True, exist_ok=True)
    store_root = Path(store.root)
    flags = {
        "json_deleted": False,
        "snap_deleted": False,
        "vid_deleted": False,
        "tracks_deleted": False,
        "trashed": True,
    }
    # Manifest first — capture its relative path so restore knows
    # where to put it back.
    json_rel = str(json_path.relative_to(store_root))
    try:
        shutil.move(str(json_path), str(trash_dir / json_path.name))
        flags["json_deleted"] = True
    except Exception as e:
        log.warning("[trash] %s/%s json move failed: %s", cam_id, event_id, e)
    # Snapshot.
    if event.get("snapshot_relpath"):
        src = store_root / event["snapshot_relpath"]
        if src.exists():
            try:
                shutil.move(str(src), str(trash_dir / src.name))
                flags["snap_deleted"] = True
            except Exception as e:
                log.warning("[trash] %s/%s snap move failed: %s", cam_id, event_id, e)
    # Video + tracks sidecar + best.jpg cache.
    if event.get("video_relpath"):
        src = store_root / event["video_relpath"]
        if src.exists():
            try:
                shutil.move(str(src), str(trash_dir / src.name))
                flags["vid_deleted"] = True
            except Exception as e:
                log.warning("[trash] %s/%s vid move failed: %s", cam_id, event_id, e)
        for tp in list(cam_root.rglob(f"{event_id}.tracks.json")):
            try:
                shutil.move(str(tp), str(trash_dir / tp.name))
                flags["tracks_deleted"] = True
            except Exception:
                log.debug("[trash] %s tracks move failed", tp, exc_info=True)
        for bp in list(cam_root.rglob(f"{event_id}.best.jpg")):
            try:
                shutil.move(str(bp), str(trash_dir / bp.name))
            except Exception:
                log.debug("[trash] %s best move failed", bp, exc_info=True)
    meta = {
        "cam_id": cam_id,
        "event_id": event_id,
        "trashed_at": datetime.now().isoformat(timespec="seconds"),
        "json_rel": json_rel,
        "event": event,
    }
    (trash_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return flags


def _merge_meta(meta_path: Path, entry: dict) -> dict:
    """Fold ``entry`` into an existing ``meta.json`` instead of replacing
    it. A retention sweep can touch the same event id twice (its files
    have independent mtimes), and the second pass must not drop the
    restore paths the first one recorded."""
    meta: dict = {}
    if meta_path.exists():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                meta = loaded
        except Exception:
            log.debug("[storage] trash meta %s unreadable, rewriting", meta_path, exc_info=True)
    files = list(meta.get("files") or [])
    for rel in entry.get("files") or []:
        if rel not in files:
            files.append(rel)
    meta.update(entry)
    meta["files"] = files
    return meta


def retire_to_trash(store_root, cam_id: str, event_id: str, paths: list) -> int:
    """Move retention-expired files into the trash instead of unlinking.

    Same selection the sweep always made — one file at a time, by mtime —
    but recoverable for ``trash.grace_days`` days afterwards. Each file's
    original storage-relative path is recorded in ``meta.json`` so
    :func:`restore` can put it back exactly where it was, which matters
    for the sweep because it retires loose files (a ``.best.jpg`` whose
    manifest is newer) that no ``event`` payload describes.

    Returns the number of files actually moved. A file that cannot be
    moved stays where it is — the sweep must never destroy what it
    cannot file away.
    """
    root = Path(store_root)
    target_dir = trash_root_for(root) / cam_id / event_id
    moved: list[str] = []
    for path in paths:
        try:
            rel = Path(path).relative_to(root).as_posix()
        except ValueError:
            log.warning(
                "[storage] %s liegt ausserhalb von %s — nicht in den Papierkorb", path, root
            )
            continue
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target_dir / Path(path).name))
        except Exception as e:
            log.warning("[storage] Papierkorb-Verschiebung von %s fehlgeschlagen: %s", rel, e)
            continue
        moved.append(rel)
    if not moved:
        return 0
    meta_path = target_dir / "meta.json"
    meta = _merge_meta(
        meta_path,
        {
            "cam_id": cam_id,
            "event_id": event_id,
            "trashed_at": datetime.now().isoformat(timespec="seconds"),
            "retired_by": "retention",
            "files": moved,
        },
    )
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    return len(moved)


def _thumb_url(ev_dir: Path, cam_id: str | None, event_id: str | None) -> str | None:
    """Preview-image URL for one trashed entry, or ``None``.

    ``move_to_trash``/``retire_to_trash`` keep a file's basename when
    moving it in, so the event's own snapshot is normally still sitting
    right in the entry dir as ``<event_id>.jpg`` — no new file gets
    moved or written for this, it's read-only exposure of what's
    already there. Falls back to any other ``*.jpg`` the entry holds
    (a manifest with an unusual naming convention should still show
    *something*), but never ``*.best.jpg`` — that's a Telegram-only
    bbox-burned render (telegram_bot/_outbound/_best_frame.py), not the
    event's real snapshot, and may not even exist for most events.

    The result is served by the existing ``/media/<path:subpath>``
    route (routes/bootstrap.py), which resolves under
    ``app_state.storage_root`` — the very root ``.trash`` lives under —
    so this needs no new route and no path-traversal surface: the
    filename is always ``img.name``, never attacker- or caller-supplied
    input.
    """
    if not cam_id or not event_id:
        return None
    canonical = ev_dir / f"{event_id}.jpg"
    img = canonical if canonical.exists() else None
    if img is None:
        candidates = sorted(p for p in ev_dir.glob("*.jpg") if not p.name.endswith(".best.jpg"))
        img = candidates[0] if candidates else None
    if img is None:
        return None
    return f"/media/.trash/{cam_id}/{event_id}/{img.name}"


def list_trashed() -> list[dict]:
    """All trashed events with metadata + days-until-expiry. Sorted
    newest-first so the UI shows the most-recently-deleted on top."""
    root = _trash_root()
    if not root.exists():
        return []
    grace = _grace_days()
    now = datetime.now()
    out: list[dict] = []
    for cam_dir in sorted(d for d in root.iterdir() if d.is_dir()):
        for ev_dir in sorted(d for d in cam_dir.iterdir() if d.is_dir()):
            meta_path = ev_dir / "meta.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            trashed_at = meta.get("trashed_at") or ""
            try:
                t_dt = datetime.fromisoformat(trashed_at)
                expires_at = t_dt + timedelta(days=grace)
                days_left = max(0, int((expires_at - now).total_seconds() // 86400))
            except Exception:
                expires_at = None
                days_left = None
            cam_id = meta.get("cam_id")
            event_id = meta.get("event_id")
            out.append(
                {
                    "cam_id": cam_id,
                    "event_id": event_id,
                    "trashed_at": trashed_at,
                    "expires_at": expires_at.isoformat(timespec="seconds") if expires_at else None,
                    "days_left": days_left,
                    "thumb_url": _thumb_url(ev_dir, cam_id, event_id),
                }
            )
    out.sort(key=lambda e: e.get("trashed_at") or "", reverse=True)
    return out


def _restore_recorded_files(ev_dir: Path, store_root: Path, rels: list) -> int:
    """Put every file listed in ``meta['files']`` back at its recorded
    storage-relative path. Returns how many made it back."""
    moved = 0
    for rel in rels:
        src = ev_dir / Path(rel).name
        if not src.exists():
            continue
        target = store_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(src), str(target))
            moved += 1
        except Exception as e:
            log.warning("[storage] Wiederherstellen von %s fehlgeschlagen: %s", rel, e)
    return moved


def restore(cam_id: str, event_id: str) -> bool:
    """Move every file in the trash entry back under its original
    motion_detection path. The original date subdir is reconstructed
    from ``meta.json``'s ``json_rel`` so the restored event slots
    back into its original date partition rather than today's."""
    ev_dir = _trash_root() / cam_id / event_id
    meta_path = ev_dir / "meta.json"
    if not meta_path.exists():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    store_root = Path(app_state.store.root)
    event = meta.get("event") or {}
    # Files the retention sweep retired carry their own original
    # relpaths — they may be loose companions no `event` payload names.
    moved_back = _restore_recorded_files(ev_dir, store_root, meta.get("files") or [])
    # Snapshot + video go back to their canonical relpaths.
    for relkey in ("snapshot_relpath", "video_relpath"):
        relpath = event.get(relkey)
        if not relpath:
            continue
        src = ev_dir / Path(relpath).name
        if not src.exists():
            continue
        target = store_root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(src), str(target))
            moved_back += 1
        except Exception as e:
            log.warning("[trash] %s restore %s failed: %s", event_id, src, e)
    # JSON manifest goes back to its captured json_rel.
    json_rel = meta.get("json_rel")
    if json_rel:
        target = store_root / json_rel
        src = ev_dir / Path(json_rel).name
        if src.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(src), str(target))
                moved_back += 1
            except Exception as e:
                log.warning("[trash] %s restore json failed: %s", event_id, e)
        # Sidecars (tracks.json, best.jpg) live in the manifest's
        # parent dir — move whatever else is left next to it.
        target_dir = (store_root / json_rel).parent
        target_dir.mkdir(parents=True, exist_ok=True)
        for src in list(ev_dir.iterdir()):
            if src.name == "meta.json":
                continue
            try:
                shutil.move(str(src), str(target_dir / src.name))
            except Exception:
                log.debug("[trash] sidecar move %s failed", src, exc_info=True)
    # Drop the now-empty trash entry.
    try:
        meta_path.unlink(missing_ok=True)
        if not any(ev_dir.iterdir()):
            ev_dir.rmdir()
    except Exception:
        pass
    return moved_back > 0


def hard_delete_one(cam_id: str, event_id: str) -> bool:
    """Hard-delete a single trash entry NOW (skip the grace period).
    Used by the Papierkorb UI's per-row "Endgültig löschen" button so
    the operator doesn't have to empty the whole trash to remove a
    single mistake. Returns True iff the entry existed and was wiped."""
    ev_dir = _trash_root() / cam_id / event_id
    if not ev_dir.exists():
        return False
    try:
        shutil.rmtree(ev_dir)
    except Exception as e:
        log.warning("[trash] hard_delete_one %s/%s failed: %s", cam_id, event_id, e)
        return False
    # Tidy empty parent dirs.
    cam_dir = ev_dir.parent
    try:
        if cam_dir.exists() and not any(cam_dir.iterdir()):
            cam_dir.rmdir()
    except OSError:
        pass
    return True


def empty() -> int:
    """Hard-delete every entry currently in the trash. Returns the
    number of event dirs removed."""
    root = _trash_root()
    if not root.exists():
        return 0
    removed = 0
    for cam_dir in list(d for d in root.iterdir() if d.is_dir()):
        for ev_dir in list(d for d in cam_dir.iterdir() if d.is_dir()):
            try:
                shutil.rmtree(ev_dir)
                removed += 1
            except Exception as e:
                log.warning("[trash] empty %s failed: %s", ev_dir, e)
        try:
            cam_dir.rmdir()
        except OSError:
            pass  # not empty, leave it
    if root.exists():
        try:
            if not any(root.iterdir()):
                root.rmdir()
        except OSError:
            pass
    return removed


def cleanup_expired(grace_days: int | None = None) -> int:
    """Daily sweep: hard-delete trash entries past the grace period.

    Called from `maintenance._run_daily_cleanup`, alongside the event
    retention sweep. Also safe to invoke manually (a cron, a test, or
    the POST /api/trash/empty route's hard-delete path).

    ``grace_days`` overrides the configured period for one call. The
    unattended caller passes the window `storage_retention.nightly_window`
    cleared, so a grace period the operator LOWERED without confirming it
    doesn't hard-delete — this is the last copy of those files — while
    every attended caller keeps the plain configured value.
    """
    root = _trash_root()
    if not root.exists():
        return 0
    grace = _grace_days() if grace_days is None else max(0, int(grace_days))
    cutoff = datetime.now() - timedelta(days=grace)
    removed = 0
    for cam_dir in list(d for d in root.iterdir() if d.is_dir()):
        for ev_dir in list(d for d in cam_dir.iterdir() if d.is_dir()):
            meta_path = ev_dir / "meta.json"
            expired = False
            if not meta_path.exists():
                # No meta — stale dir from an interrupted move. Sweep.
                expired = True
            else:
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    t_dt = datetime.fromisoformat(meta.get("trashed_at") or "")
                except Exception:
                    expired = True
                else:
                    expired = t_dt < cutoff
            if expired:
                try:
                    shutil.rmtree(ev_dir)
                    removed += 1
                except Exception as e:
                    log.warning("[trash] expired sweep %s failed: %s", ev_dir, e)
        with contextlib.suppress(OSError):
            cam_dir.rmdir()
    return removed
