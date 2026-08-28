"""Settings-backup browsing and per-camera connection restore.

Carved out of routes/cameras.py, which stood at 886 lines against a
500-line ceiling. Backups are their own concern — they read
``settings.json.bak*`` rather than the live config, and they are the one
place a credential is deliberately SHOWN (masked) rather than hidden,
because the operator has to recognise which backup they are about to
restore from.
"""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify, request

from .. import app_state
from ._camera_helpers import _RESTORE_CONN_FIELDS, _list_backup_files, _read_backup
from ._secrets import mask_url_password

bp = Blueprint("camera_backups", __name__)


@bp.get('/api/settings/backups')
def api_settings_backups_list():
    """List available settings backups for the recovery UI. Each entry
    summarises the snapshot (mtime, size, total cams) and — when ?cam_id=…
    is supplied — flags whether that backup contains the cam and whether
    its connection fields are usable."""
    cam_id = request.args.get("cam_id") or ""
    items = []
    for p in _list_backup_files():
        try:
            st = p.stat()
        except OSError:
            continue
        data = _read_backup(p)
        n_cameras = len((data or {}).get("cameras", []) or [])
        has_cam = False
        has_connection = False
        if cam_id and isinstance(data, dict):
            for c in data.get("cameras", []) or []:
                if c.get("id") == cam_id:
                    has_cam = True
                    has_connection = bool(c.get("rtsp_url") and c.get("username"))
                    break
        items.append(
            {
                "filename": p.name,
                "mtime_iso": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                "size": st.st_size,
                "n_cameras": n_cameras,
                "has_cam": has_cam,
                "has_connection": has_connection,
            }
        )
    return jsonify({"items": items})


@bp.get('/api/settings/backups/<filename>/cam/<cam_id>')
def api_settings_backup_cam(filename: str, cam_id: str):
    """Return the connection fields for `cam_id` from the named backup, with
    the password masked so the preview can show what the user is about to
    restore without leaking the secret."""
    if "/" in filename or "\\" in filename or filename.startswith(".."):
        return jsonify({"ok": False, "error": "invalid filename"}), 400
    candidates = [p for p in _list_backup_files() if p.name == filename]
    if not candidates:
        return jsonify({"ok": False, "error": "backup not found"}), 404
    data = _read_backup(candidates[0])
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "backup not parseable"}), 400
    for c in data.get("cameras", []) or []:
        if c.get("id") == cam_id:
            return jsonify(
                {
                    "ok": True,
                    "cam_id": cam_id,
                    "name": c.get("name", ""),
                    "rtsp_url_masked": mask_url_password(c.get("rtsp_url", "")),
                    "snapshot_url_masked": mask_url_password(c.get("snapshot_url", "")),
                    "username": c.get("username", ""),
                    "password_set": bool(c.get("password")),
                }
            )
    return jsonify({"ok": False, "error": "cam not in this backup"}), 404


@bp.post('/api/settings/cameras/<cam_id>/restore-connection')
def api_settings_cam_restore_connection(cam_id: str):
    """Restore connection-only fields for one camera from a named backup.

    Touches exactly the four fields in _RESTORE_CONN_FIELDS — every other
    field on the cam (zones, schedule, profiles…) and every other camera
    is left alone. Triggers restart_single_camera so the cam comes back
    online without a full reload."""
    settings = app_state.settings
    payload = request.get_json(force=True) or {}
    filename = (payload.get("filename") or "").strip()
    if "/" in filename or "\\" in filename or filename.startswith("..") or not filename:
        return jsonify({"ok": False, "error": "invalid filename"}), 400
    if not settings.get_camera(cam_id):
        return jsonify({"ok": False, "error": "cam not configured"}), 404
    candidates = [p for p in _list_backup_files() if p.name == filename]
    if not candidates:
        return jsonify({"ok": False, "error": "backup not found"}), 404
    data = _read_backup(candidates[0])
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "backup not parseable"}), 400
    src = next((c for c in data.get("cameras", []) or [] if c.get("id") == cam_id), None)
    if not src:
        return jsonify({"ok": False, "error": "cam not in this backup"}), 404
    if not src.get("rtsp_url"):
        return jsonify({"ok": False, "error": "backup has empty rtsp_url for this cam"}), 400
    current = settings.get_camera(cam_id) or {}
    patch = {f: src.get(f, "") for f in _RESTORE_CONN_FIELDS}
    merged = {**current, **patch}
    try:
        settings.upsert_camera(merged)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 422
    app_state.restart_single_camera(cam_id)
    return jsonify(
        {
            "ok": True,
            "cam_id": cam_id,
            "restored_fields": list(_RESTORE_CONN_FIELDS),
            "from": filename,
        }
    )
