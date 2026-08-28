"""Media library, storage stats, thumbnail backfill, orphan purge.

Migrated from server.py during R01.4. The fix-thumbnails background
task keeps its module-level state (`_thumb_task`, `_fix_thumbs_lock`)
inside this blueprint — it's bp-private and replacing the singleton
during a config reload would lose progress on an in-flight job.

Counting lives in :mod:`app.media_index`, not here. The badge route and
the grid route call the same ``visible_media_events`` and count the same
list, so they cannot drift apart the way the file-glob badge and the
manifest-counting grid did.
"""

from __future__ import annotations

import json as _json
import logging
import threading as _threading_fix
from datetime import datetime as _dt

import cv2
from flask import Blueprint, jsonify, request

from .. import app_state
from ..camera_runtime._recording._stages import DEFAULT_CLIP_MAX_S
from ..media_index import (
    build_report,
    camera_stats,
    register_timelapse_events,
    scan_camera,
    visible_media_events,
)

bp = Blueprint("media", __name__)


_thumb_task = {"running": False, "done": 0, "total": 0, "errors": 0, "recent": []}
_fix_thumbs_lock = _threading_fix.Lock()

_integrity_task = {"running": False, "report": None, "error": None, "finished_at": None}
_integrity_lock = _threading_fix.Lock()


def _clip_max_s() -> int:
    try:
        return int(
            (app_state.get_effective_config().get("processing") or {}).get(
                "clip_max_duration_s", DEFAULT_CLIP_MAX_S
            )
        )
    except (TypeError, ValueError, AttributeError):
        return DEFAULT_CLIP_MAX_S


def _cam_visible(cam_id: str, **filters):
    """``(index, visible)`` for ``cam_id`` — the one pair both the badge
    route and the grid route work from.

    The lookup is ``index.size_lookup``, not the bare index and not a
    bare ``stat``: the badge answered from the walked trees and the grid
    stat()ed anything, so a manifest pointing outside
    ``motion_detection/`` / ``timelapse/`` counted in one and not the
    other. Same lookup, same list, same numbers.
    """
    storage_root = app_state.storage_root
    index = scan_camera(storage_root, cam_id)
    visible = visible_media_events(
        app_state.store,
        index.size_lookup(storage_root),
        cam_id,
        clip_max_s=_clip_max_s(),
        **filters,
    )
    return index, visible


def _cam_stats_dict(cam_id: str, name_hint: str = "") -> dict:
    """Camera card numbers for ``cam_id``.

    Both halves come from the shared index: sizes from the single walk,
    counts from ``visible_media_events`` — the exact list
    ``/api/camera/<id>/media`` renders. There is no second count to
    diverge from.
    """
    index, visible = _cam_visible(cam_id)
    return camera_stats(index, visible, name_hint=name_hint)


@bp.get('/api/media/storage-stats')
def api_media_storage_stats():
    storage_root = app_state.storage_root
    active_cams = app_state.get_effective_config().get("cameras", [])
    active_ids = {c["id"] for c in active_cams}

    result = [_cam_stats_dict(c["id"], name_hint=c.get("name", c["id"])) for c in active_cams]

    # Archived: media folders for cameras no longer in active config.
    # Both trees are scanned so a camera whose id changed (rename / new
    # IP) still surfaces instead of looking like an empty camera.
    archived = []
    for name in sorted(
        {
            d.name
            for tree in ("motion_detection", "timelapse")
            if (storage_root / tree).is_dir()
            for d in (storage_root / tree).iterdir()
            if d.is_dir() and d.name not in active_ids
        }
    ):
        stats = _cam_stats_dict(name)
        if stats["jpg_count"] or stats["event_count"] or stats["timelapse_count"]:
            archived.append(stats)

    return jsonify({"cameras": result, "archived": archived})


@bp.post('/api/media/rescan')
def api_media_rescan():
    store = app_state.store
    effective = app_state.get_effective_config()
    cam_ids = [c["id"] for c in effective.get("cameras", [])]
    logging.getLogger(__name__).info("[MediaRescan] scanning cam_ids: %s", cam_ids)
    public_base = (effective.get("server", {}).get("public_base_url") or "").rstrip("/")
    try:
        count = store.scan_media_files(cam_ids, public_base_url=public_base)
        # The old rescan walked motion_detection/ only, so a timelapse
        # mp4 could never be registered no matter how often the button
        # was pressed — the badge counted it, the grid could not show
        # it, and "Neu scannen" was structurally unable to close the gap.
        tl_count = register_timelapse_events(app_state.storage_root, store, public_base)
        return jsonify({"ok": True, "registered": count + tl_count, "timelapse": tl_count})
    except Exception:
        import traceback

        return jsonify({"ok": False, "error": traceback.format_exc()}), 500


@bp.post('/api/media/integrity')
def api_media_integrity():
    """Read-only integrity report — reports, never repairs.

    Mutates nothing: no unlink, no write, no registration, and since
    the report stopped reaching through the EventStore, no directory
    creation either. Findings carry the relative path so the operator
    acts deliberately; several categories (.raw fallbacks, in-flight
    recording stubs) are files that must NOT be deleted, which is why
    there is no bulk-cleanup counterpart to this endpoint.

    POST, and on a background thread, because it walks every media tree
    of every camera — ``timelapse_frames`` can be gigabytes of jpgs, and
    running that on the request worker blocked it for minutes. Poll
    ``GET /api/media/integrity/status`` for the result, the same shape
    fix-thumbnails uses.
    """
    storage_root = app_state.storage_root
    cameras = app_state.get_effective_config().get("cameras", [])
    log_i = logging.getLogger(__name__)
    with _integrity_lock:
        if _integrity_task["running"]:
            return jsonify({"ok": True, "already_running": True})
        _integrity_task.update(running=True, report=None, error=None, finished_at=None)

    def _worker():
        try:
            report = build_report(storage_root, None, cameras)
            error = None
        except Exception as e:
            log_i.warning("[storage] Integritätsprüfung fehlgeschlagen: %s", e)
            report, error = None, str(e)
        with _integrity_lock:
            _integrity_task.update(
                running=False,
                report=report,
                error=error,
                finished_at=_dt.now().isoformat(timespec="seconds"),
            )

    _threading_fix.Thread(target=_worker, daemon=True).start()
    return jsonify({"ok": True, "already_running": False})


@bp.get('/api/media/integrity/status')
def api_media_integrity_status():
    """Progress / result of the background integrity run."""
    with _integrity_lock:
        return jsonify(
            {
                "ok": _integrity_task["error"] is None,
                "running": _integrity_task["running"],
                "error": _integrity_task["error"],
                "finished_at": _integrity_task["finished_at"],
                "report": _integrity_task["report"],
            }
        )


@bp.post('/api/media/fix-thumbnails')
def api_media_fix_thumbnails():
    """Scan all motion_detection event JSONs; for each event with video_relpath
    but no (valid) snapshot file on disk, extract the middle frame of the mp4
    and save it next to the video. Runs in a background thread; progress via
    GET /api/media/fix-thumbnails/status."""
    storage_root = app_state.storage_root
    log_t = logging.getLogger(__name__)
    events_root = storage_root / "motion_detection"
    todo: list = []
    if events_root.exists():
        for jf in events_root.rglob("*.json"):
            try:
                ev = _json.loads(jf.read_text(encoding="utf-8"))
                vid_rel = ev.get("video_relpath")
                if not vid_rel:
                    continue
                snap_rel = ev.get("snapshot_relpath")
                snap_ok = bool(snap_rel) and (storage_root / snap_rel).exists()
                if not snap_ok:
                    todo.append((jf, ev))
            except Exception:
                continue

    with _fix_thumbs_lock:
        if _thumb_task["running"]:
            return jsonify({"ok": True, "already_running": True, **_thumb_task})
        _thumb_task["total"] = len(todo)
        _thumb_task["done"] = 0
        _thumb_task["errors"] = 0
        _thumb_task["recent"] = []
        _thumb_task["running"] = True

    public_base = (
        app_state.get_effective_config().get("server", {}).get("public_base_url") or ""
    ).rstrip("/")

    def _worker():
        for jf, ev in todo:
            err = False
            try:
                vid_rel = ev.get("video_relpath") or ""
                vid_path = storage_root / vid_rel
                if not vid_path.exists():
                    err = True
                    continue
                cap = cv2.VideoCapture(str(vid_path))
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                # Seek to ~1/3 of the clip — the first frame of motion clips is
                # often a dark/gray warm-up frame.
                if total_frames > 3:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames // 3)
                ok, frame = cap.read()
                cap.release()
                if not ok or frame is None:
                    log_t.warning("[fix-thumbs] no readable frame in %s", vid_path.name)
                    err = True
                    continue
                # Downscale to max 640px wide so thumbs stay small on disk
                tw = frame.shape[1]
                if tw > 640:
                    scale = 640 / tw
                    frame = cv2.resize(frame, (640, int(frame.shape[0] * scale)))
                snap_path = vid_path.with_suffix(".jpg")
                if not cv2.imwrite(str(snap_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82]):
                    log_t.warning("[fix-thumbs] imwrite failed for %s", snap_path.name)
                    err = True
                    continue
                snap_rel = snap_path.relative_to(storage_root).as_posix()
                snap_url = (
                    f"{public_base}/media/{snap_rel}" if public_base else f"/media/{snap_rel}"
                )
                ev["snapshot_relpath"] = snap_rel
                ev["snapshot_url"] = snap_url
                ev["thumb_url"] = snap_url
                jf.write_text(_json.dumps(ev, ensure_ascii=False, indent=2), encoding="utf-8")
                log_t.info("[fix-thumbs] %s -> %s", vid_path.name, snap_path.name)
                with _fix_thumbs_lock:
                    _thumb_task["recent"].append(vid_path.name)
                    if len(_thumb_task["recent"]) > 50:
                        _thumb_task["recent"].pop(0)
            except Exception as e:
                log_t.warning("[fix-thumbs] error on %s: %s", jf.name, e)
                err = True
            finally:
                with _fix_thumbs_lock:
                    _thumb_task["done"] += 1
                    if err:
                        _thumb_task["errors"] += 1
        with _fix_thumbs_lock:
            _thumb_task["running"] = False

    _threading_fix.Thread(target=_worker, daemon=True).start()
    return jsonify({"ok": True, "total": len(todo), "already_running": False})


@bp.get('/api/media/fix-thumbnails/status')
def api_media_fix_thumbnails_status():
    with _fix_thumbs_lock:
        return jsonify(dict(_thumb_task))


@bp.post('/api/media/purge-orphans')
def api_media_purge_orphans():
    try:
        removed = app_state.store.purge_orphans()
        return jsonify({"ok": True, "removed": removed})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.post('/api/media/cleanup')
def api_media_cleanup():
    """ "Jetzt bereinigen" — the attended sweep.

    Pressing this with an explicit ``retention_days`` is also the
    confirmation the nightly sweep waits for before it may act on a
    narrower window than the one it last enforced. The operator is
    looking at the number on screen; the unattended timer is not.
    """
    from ..maintenance import config_retention_days, resolve_retention_days
    from ..storage_retention import acknowledge_window, nightly_window

    payload = request.get_json(force=True) or {}
    override = payload.get("retention_days")
    retention = resolve_retention_days(override)
    if override is None:
        # An empty field posts {}, and a click on a number the operator
        # never typed is not a confirmation of it. Without this the
        # attended path ran the narrowed window immediately while the
        # unattended one was still deferring it — the button was a way
        # around its own guard. Fall back to the same deferral: pressing
        # the button confirms nothing, so it may delete no more than the
        # nightly sweep already would.
        retention = nightly_window(retention, config_retention_days())
    try:
        removed = app_state.store.cleanup_old(retention)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    if override is not None:
        acknowledge_window(retention)
    return jsonify({"ok": True, "removed": removed, "retention_days": retention})


@bp.get('/api/camera/<cam_id>/media')
def api_camera_media(cam_id):
    settings = app_state.settings
    label = request.args.get('label')
    labels_raw = request.args.get('labels')
    labels = [l.strip() for l in labels_raw.split(',') if l.strip()] if labels_raw else None
    start = request.args.get('start')
    end = request.args.get('end')
    # type=int returns None on parse failure so a bogus ?limit=foo no
    # longer 500s — falls back to the configured media_limit_default.
    cfg_default = app_state.get_effective_config().get("storage", {}).get("media_limit_default", 24)
    limit = request.args.get('limit', type=int) or cfg_default
    offset = request.args.get('offset', type=int) or 0
    _index, visible = _cam_visible(cam_id, label=label, labels=labels, start=start, end=end)
    total_count = len(visible)
    items = visible[offset : offset + limit]
    for item in items:
        review = settings.get_review(f"{cam_id}:{item['event_id']}")
        if review:
            item["review"] = review
    return jsonify({"items": items, "total_count": total_count})


@bp.get('/api/event/<event_id>')
def api_event_get(event_id: str):
    """Cross-camera event lookup for Telegram deep-links. Returns enough
    metadata for the frontend hash router to switch to the right cam +
    open the lightbox. 404 when nothing matches."""
    store = app_state.store
    payload = store.find_event_anywhere(event_id) if store else None
    if not payload:
        return jsonify({"error": "not found"}), 404
    return jsonify(
        {
            "event_id": payload.get("event_id"),
            "camera_id": payload.get("camera_id"),
            "top_label": payload.get("top_label") or payload.get("primary_label"),
            "time": payload.get("time"),
            "video_relpath": payload.get("video_relpath"),
            "snapshot_relpath": payload.get("snapshot_relpath"),
        }
    )
