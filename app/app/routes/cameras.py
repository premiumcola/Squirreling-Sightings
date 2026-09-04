"""Camera CRUD, settings/cameras, settings/app, and settings/backups.

Migrated from server.py during R01.3. Camera-save and camera-delete
both touch live runtimes via `app_state.restart_single_camera` /
`app_state.rebuild_runtimes`, which server.py publishes at boot (R01.6).
Settings/app save also calls `rebuild_runtimes` for config changes that
affect runtime behaviour.
"""

from __future__ import annotations

import logging
import time as _time

from flask import Blueprint, jsonify, request

log = logging.getLogger(__name__)

from .. import app_state
from ..camera_runtime import CameraRuntime
from ._camera_helpers import (
    _CONN_FIELDS,
    _auto_detect_device_info,
)
from ._tuning_archive import archive_tuning_change
from ._secrets import (
    merge_camera_secrets,
    redact_camera,
    strip_url_password,
)

bp = Blueprint("cameras", __name__)


@bp.get('/api/cameras')
def api_cameras():
    runtimes = app_state.runtimes
    cams = []
    for cam in app_state.get_effective_config().get("cameras", []):
        rt = runtimes.get(cam["id"])
        s = (
            rt.status()
            if rt
            else {
                "id": cam["id"],
                "name": cam.get("name", cam["id"]),
                "location": cam.get("location", ""),
                "enabled": cam.get("enabled", True),
                "armed": cam.get("armed", True),
                "status": "disabled",
                "today_events": 0,
            }
        )
        # snap_url / stream_url are dashboard-display-only derived URLs.
        # They MUST use a distinct key so they are never confused with the persisted
        # upstream snapshot_url / rtsp_url (which live in settings.json).
        s["snap_url"] = f"/api/camera/{cam['id']}/snapshot.jpg"
        s["stream_url"] = f"/api/camera/{cam['id']}/stream.mjpg"
        s["stream_url_hd"] = f"/api/camera/{cam['id']}/stream_hd.mjpg"
        # Persisted connection fields, minus the secret. The URLs keep
        # their key names (the dashboard chrome, the discovery host
        # de-dupe and the sun-timelapse vendor check all read them) but
        # lose the `:password` from the userinfo, and the password
        # itself becomes a boolean. This endpoint is polled every 3 s
        # over unauthenticated plain HTTP — see routes/_secrets.
        # The save path puts the credentials back (merge_camera_secrets),
        # so a quick-action spread of this record still round-trips.
        s["snapshot_url"] = strip_url_password(cam.get("snapshot_url", ""))
        s["rtsp_url"] = strip_url_password(cam.get("rtsp_url", ""))
        s["username"] = cam.get("username", "")
        s["password_set"] = bool(cam.get("password"))
        # Identity colour override from cam-edit's Allgemein tab. The
        # projection is key-by-key, so a field it forgets is a field the
        # frontend never sees: `getCameraColor` prefers `c.color` and
        # falls back to the name-derived auto-tone, so omitting it here
        # made every saved colour invisible everywhere. "" = no
        # override, which is the fallback the picker's Auto button writes.
        s["color"] = cam.get("color", "")
        s["object_filter"] = cam.get("object_filter", [])
        s["telegram_enabled"] = cam.get("telegram_enabled", True)
        s["mqtt_enabled"] = cam.get("mqtt_enabled", True)
        # Outdoor/indoor flag — the Mediathek camera filter's outdoor
        # scope check (library._feed._outdoor_scope_ok) reads this from
        # state.config.cameras, but state.cameras (this endpoint) is the
        # cam-edit hydration fallback, so it has to carry the field too —
        # same lesson as `color` in test_camera_color_reaches_ui.py.
        s["outdoor"] = cam.get("outdoor", True)
        s["whitelist_names"] = cam.get("whitelist_names", [])
        # Unified per-camera schedule. Migration in SettingsStore guarantees
        # the new shape; the legacy recording_schedule_* fields no longer
        # exist in the persisted config.
        s["schedule"] = cam.get("schedule") or {
            "enabled": False,
            "from": "21:00",
            "to": "06:00",
            "actions": {"record": True, "telegram": True, "hard": True},
        }
        # Audio opt-in. Projected key-by-key like every field above, so a
        # field this loop forgets is a field the cam-edit form never sees
        # (the `color` lesson in test_camera_color_reaches_ui.py). The
        # save direction needs nothing extra: upsert_camera runs the
        # payload through CAMERA_SCHEMA, which type-checks and coerces
        # `record_audio` like any other bool.
        s["record_audio"] = bool(cam.get("record_audio", False))
        s["bottom_crop_px"] = cam.get("bottom_crop_px", 0)
        s["motion_sensitivity"] = cam.get("motion_sensitivity", 0.5)
        s["detection_min_score"] = float(cam.get("detection_min_score") or 0.0)
        s["motion_enabled"] = cam.get("motion_enabled", True)
        s["detection_trigger"] = cam.get("detection_trigger", "motion_and_objects")
        s["post_motion_tail_s"] = float(cam.get("post_motion_tail_s") or 0.0)
        s["alarm_profile"] = cam.get("alarm_profile") or ""
        # L1 · per-camera tracker overrides — the cam-edit Erkennung
        # tab's "Objekt-Tracking" inputs read these. Missing the keys
        # here means the form always shows 0 even after a save (the
        # frontend's `parseFloat(undefined) || 0` collapses to 0),
        # so the user-entered values appeared to never persist. 0 /
        # None remain the "use module default" sentinel — surfaced as
        # 0 in the input so the placeholder hint still wins.
        s["track_spawn_min_score"] = float(cam.get("track_spawn_min_score") or 0.0)
        s["track_continue_min_score"] = float(cam.get("track_continue_min_score") or 0.0)
        s["track_miss_grace_seconds"] = float(cam.get("track_miss_grace_seconds") or 0.0)
        s["track_iou_match_threshold"] = float(cam.get("track_iou_match_threshold") or 0.0)
        # L07 · expose to the cam-edit form. Default True so legacy
        # cameras without the field read as enabled on first hydrate.
        s["track_filter_ghosts"] = cam.get("track_filter_ghosts") is not False
        # The Simulieren panel's MODUS control seeds itself from this. It
        # used to hardcode "off", so opening the simulator on a camera that
        # actually runs 2x2 showed — and then ran — a DIFFERENT pipeline
        # than production, silently. The operator caught it: "wenn ich in
        # den Simulator geh, dann ist das 2x2 nicht an, obwohl die ja so
        # läuft".
        s["roi_mode"] = cam.get("roi_mode") or "off"
        s["zones"] = cam.get("zones", [])
        s["masks"] = cam.get("masks", [])
        s["resolution"] = cam.get("resolution", "auto")
        s["frame_interval_ms"] = cam.get("frame_interval_ms", 350)
        s["snapshot_interval_s"] = cam.get("snapshot_interval_s", 3)
        s["timelapse"] = cam.get("timelapse", {})
        s["weather"] = cam.get("weather") or {"enabled": False}
        # Recent-detection feed for the live-tile object-icon red glow.
        # Filter to entries within the last 10 s; the dashboard polls
        # this endpoint every 3 s so a fresh detection lights the chip
        # on the very next tick and decays naturally as entries age
        # out of the window. Older entries stay in the runtime deque
        # until the deque's maxlen evicts them; only the filter here
        # controls the visible glow window.
        now_epoch = _time.time()
        recent: list[dict] = []
        if rt is not None and getattr(rt, "recent_detections", None):
            for lbl, ts in list(rt.recent_detections):
                age = now_epoch - ts
                if 0 <= age <= 10.0:
                    recent.append({"label": lbl, "age_s": round(age, 2)})
        s["recent_detections"] = recent
        cams.append(s)
    return jsonify({"cameras": cams})


@bp.get('/api/settings/cameras')
def api_settings_cameras():
    return jsonify(
        {"cameras": [redact_camera(c) for c in app_state.settings.data.get("cameras", [])]}
    )


@bp.post('/api/settings/cameras')
def api_settings_cameras_save():
    settings = app_state.settings
    runtimes = app_state.runtimes
    _runtime_cfgs = app_state._runtime_cfgs
    payload = request.get_json(force=True) or {}
    if not payload.get("id"):
        return jsonify({"ok": False, "error": "id fehlt"}), 400
    old_id = payload["id"]
    old_cfg = settings.get_camera(old_id) or {}
    # Guard: never persist dashboard-display URLs as the upstream connection fields.
    # These get into the payload when quick-actions spread state.cameras objects.
    for field in ("snapshot_url", "rtsp_url"):
        val = payload.get(field, "")
        if val.startswith("/api/camera/"):
            # Retain the existing persisted value; display-only URLs must not overwrite it.
            preserved = old_cfg.get(field, "")
            payload[field] = preserved
    # Fold the secrets back on before anything reads them. The browser
    # is handed credential-free URLs and a `password_set` boolean, so a
    # save carries neither the password nor the userinfo — an omitted
    # `password` means "unchanged", "" means "clear". Must run BEFORE
    # _auto_detect_device_info (it logs into the camera) and before the
    # _CONN_FIELDS diff below, which would otherwise see the stripped
    # URL as a change and restart the camera on every partial save.
    merge_camera_secrets(payload, old_cfg)
    # Reolink auto-detect: fill empty manufacturer/model from the camera
    # itself before persisting. No-op when the user typed values manually
    # or the camera doesn't respond. The returned list flags which fields
    # were filled so the UI can show an "automatisch erkannt" hint.
    auto_detected = _auto_detect_device_info(payload)
    try:
        # Same rail as the detection-tuning route: a POST carrying the
        # whole camera dict could set label_thresholds["person"] to 0.95
        # and blind a security camera with no dialog anywhere.
        if isinstance(payload.get("label_thresholds"), dict):
            from ..thresholds._apply import clamp_person_label_threshold

            payload["label_thresholds"] = clamp_person_label_threshold(
                payload, payload["label_thresholds"]
            )
        new_id = settings.upsert_camera(payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422
    # If the canonical id changed underneath us (manufacturer / model /
    # name / rtsp_url edit triggered storage_migration), the runtime
    # under the OLD id is now orphaned — drop it before binding a fresh
    # one under the NEW id. Without this, every cam-edit save quietly
    # broke the Telegram bot's cam picker for an hour until something
    # else triggered a rebuild_runtimes.
    enabled_now = payload.get("enabled", True)
    id_renamed = old_id != new_id
    # Only keys the client actually sent count as a change. `payload.get(f)`
    # returned None for an omitted key and so read as "differs from stored"
    # → restart_single_camera on every partial save (the failure the comment
    # in camedit/index.js documents). Omission means "unchanged", matching
    # upsert_camera's dict.update merge.
    conn_changed = any(f in payload and payload[f] != old_cfg.get(f) for f in _CONN_FIELDS)
    if id_renamed:
        existing = runtimes.pop(old_id, None)
        if existing:
            existing.stop()
        _runtime_cfgs.pop(old_id, None)
        if enabled_now:
            app_state.restart_single_camera(new_id, reason="rebound after migration")
    elif conn_changed or (new_id not in runtimes and enabled_now):
        app_state.restart_single_camera(new_id, reason="rebound after edit")
    return jsonify(
        {
            "ok": True,
            "camera": redact_camera(settings.get_camera(new_id)),
            "reloaded": conn_changed or id_renamed,
            "id": new_id,
            "id_renamed_from": old_id if id_renamed else None,
            "auto_detected": auto_detected,
        }
    )


@bp.post('/api/camera/<cam_id>/reload')
def api_camera_reload(cam_id: str):
    settings = app_state.settings
    runtimes = app_state.runtimes
    store = app_state.store
    # Stop existing runtime for this camera only
    existing = runtimes.pop(cam_id, None)
    if existing:
        existing.stop()
    # Reload config and start fresh runtime for this camera
    cfg = app_state.get_effective_config()
    cam_cfg = settings.get_camera(cam_id)
    if cam_cfg and cam_cfg.get("enabled", True):
        rt = CameraRuntime(
            cam_id,
            app_state.get_camera_cfg,
            cfg,
            store,
            app_state.telegram_service,
            mqtt=app_state.mqtt_service,
            cat_registry=app_state.cat_registry,
            person_registry=app_state.person_registry,
        )
        runtimes[cam_id] = rt
        rt.start()
    return jsonify({"ok": True, "cam_id": cam_id})


@bp.delete('/api/settings/cameras/<cam_id>')
def api_settings_cameras_delete(cam_id):
    settings = app_state.settings
    runtimes = app_state.runtimes
    store = app_state.store
    # Count existing events so the frontend can warn the user
    cam_dir = store.events_dir / cam_id
    event_count = len(list(cam_dir.glob("*.json"))) if cam_dir.exists() else 0
    deleted = settings.delete_camera(cam_id)
    if not deleted:
        return jsonify({"ok": False, "error": "Kamera nicht gefunden"}), 404
    # Stop the running thread
    rt = runtimes.pop(cam_id, None)
    if rt:
        rt.stop()
    return jsonify({"ok": True, "event_count": event_count})


@bp.post('/api/camera/<cam_id>/arm')
def api_camera_arm(cam_id):
    settings = app_state.settings
    payload = request.get_json(force=True, silent=True) or {}
    cam = settings.get_camera(cam_id)
    if not cam:
        return jsonify({"ok": False, "error": "camera not found"}), 404
    cam["armed"] = bool(payload.get("armed", True))
    try:
        settings.upsert_camera(cam)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422
    mqtt = app_state.mqtt_service
    if mqtt is not None:
        mqtt.publish(f"camera/{cam_id}/armed", {"armed": cam["armed"]}, retain=True)
    return jsonify({"ok": True, "camera": redact_camera(cam)})


# SIMU-05g · partial-update endpoint for the Debug-tab clusters, and
# (since the Netz-Kamera-Feinschliff move) the same camera-wide loop
# settings that used to live on the Erkennung tab's own form. Accepts
# ONLY this subset of camera fields and pushes them straight into the
# live LiveTracker (no restart) plus persists via upsert_camera.
# Returns the EFFECTIVE threshold set after the merge so the frontend
# can confirm what's now active.
#
# track_miss_grace_seconds' floor is 0.0, not 1.0 — 0 is the "use the
# system default" sentinel every caller (hydrateErkennungFields,
# discovery.js's collector, the Netz tuning panel) already treats as
# valid and common; a camera that never customised it saves 0.
_TUNING_FLOAT_FIELDS = {
    "track_iou_match_threshold": (0.0, 0.95),
    "track_miss_grace_seconds": (0.0, 30.0),
    "track_continue_min_score": (0.0, 0.95),
    "track_spawn_min_score": (0.0, 0.95),
    "track_block_contain": (0.0, 1.0),
    "motion_sensitivity": (0.1, 1.0),
    "wildlife_motion_sensitivity": (0.0, 3.0),
    "roi_min_net_disp_frac": (0.0, 0.2),
    "post_motion_tail_s": (0.0, 15.0),
    "frame_interval_ms": (100.0, 2000.0),
}
_TUNING_ENUM_FIELDS = {
    "roi_mode": ("off", "roi", "2x2", "3x3"),
}
_TUNING_BOOL_FIELDS = ("track_filter_ghosts",)
#: Everything this route can move. The Verlauf snapshot is taken over
#: exactly these keys, and only for the ones the request actually carries.
_ARCHIVED_TUNING_FIELDS = (
    *_TUNING_FLOAT_FIELDS,
    *_TUNING_ENUM_FIELDS,
    *_TUNING_BOOL_FIELDS,
)


@bp.patch('/api/cameras/<cam_id>/detection-tuning')
def api_camera_detection_tuning(cam_id):
    settings = app_state.settings
    runtimes = app_state.runtimes
    cam = settings.get_camera(cam_id)
    if not cam:
        return jsonify({"ok": False, "error": "camera not found"}), 404
    payload = request.get_json(force=True, silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "payload must be an object"}), 400
    # Snapshot BEFORE the validators start writing into `cam` — get_camera
    # hands back the stored dict, and every branch below mutates it in
    # place. Only the keys the request carries: a field nobody touched can
    # then never turn up as a "change".
    _before = {f: cam.get(f) for f in _ARCHIVED_TUNING_FIELDS if f in payload}
    # Validate the float-range fields. Reject out-of-range with 400
    # so the frontend's slider never ships a value the backend would
    # silently clamp.
    for field, (lo, hi) in _TUNING_FLOAT_FIELDS.items():
        if field not in payload:
            continue
        try:
            val = float(payload[field])
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": f"{field}: must be a number"}), 400
        if val < lo or val > hi:
            return (
                jsonify({"ok": False, "error": f"{field}: out of range [{lo},{hi}]"}),
                400,
            )
        cam[field] = round(val, 4)
    # frame_interval_ms is a millisecond count, not a fractional threshold —
    # the loop above already range-validated and stored it as a rounded
    # float; re-cast to int so the schema type stays consistent with
    # every other reader of this key.
    if "frame_interval_ms" in payload:
        cam["frame_interval_ms"] = int(round(cam["frame_interval_ms"]))
    for field, allowed in _TUNING_ENUM_FIELDS.items():
        if field not in payload:
            continue
        val = str(payload[field] or "").lower()
        if val not in allowed:
            return (
                jsonify({"ok": False, "error": f"{field}: must be one of {allowed}"}),
                400,
            )
        cam[field] = val
    for field in _TUNING_BOOL_FIELDS:
        if field in payload:
            cam[field] = bool(payload[field])
    # Enforce the floor ≤ spawn invariant the tracker assumes.
    spawn_v = float(cam.get("track_spawn_min_score") or 0.0)
    floor_v = float(cam.get("track_continue_min_score") or 0.0)
    if spawn_v > 0 and floor_v > spawn_v:
        cam["track_continue_min_score"] = round(spawn_v, 4)
    # label_thresholds is a per-class map (label → float). Range-
    # validate per entry; we accept any string key (the tracker
    # already ignores classes not in object_filter or Coral output).
    if "label_thresholds" in payload:
        lt = payload.get("label_thresholds") or {}
        if not isinstance(lt, dict):
            return jsonify({"ok": False, "error": "label_thresholds: must be object"}), 400
        cleaned: dict[str, float] = {}
        for k, v in lt.items():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                return jsonify(
                    {"ok": False, "error": f"label_thresholds[{k}]: must be number"}
                ), 400
            if fv < 0.0 or fv > 0.95:
                return (
                    jsonify({"ok": False, "error": f"label_thresholds[{k}]: out of range"}),
                    400,
                )
            cleaned[str(k)] = round(fv, 4)
        # A security camera's person spawn may not be raised past the
        # floor by a route that shows no confirmation dialog. The Netz's
        # own writes go through clamp_manual_e; these two do not.
        from ..thresholds._apply import clamp_person_label_threshold

        cleaned = clamp_person_label_threshold(cam, cleaned)
        cam["label_thresholds"] = cleaned
    if "object_filter" in payload:
        of = payload.get("object_filter") or []
        if not isinstance(of, list):
            return jsonify({"ok": False, "error": "object_filter: must be list"}), 400
        cam["object_filter"] = [str(c) for c in of]
    if "excluded_classes" in payload:
        ec = payload.get("excluded_classes") or []
        if not isinstance(ec, list):
            return jsonify({"ok": False, "error": "excluded_classes: must be list"}), 400
        cam["excluded_classes"] = sorted({str(c) for c in ec})
    try:
        settings.upsert_camera(cam)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 422
    archive_tuning_change(cam_id, cam, _before)
    # Live-apply to the running tracker — no restart needed. LiveTracker
    # carries its own threshold cache; resolve_track_thresholds reads
    # from cfg on every call, so the per-tick threshold reads pick up
    # the new label_thresholds immediately. Configure() pushes the
    # tracker-level thresholds (spawn/floor/grace/iou/containment) in one
    # shot.
    runtime = runtimes.get(cam_id)
    if runtime is not None and hasattr(runtime, "_tracker"):
        try:
            from ..tracker_core import resolve_track_thresholds

            tracks = resolve_track_thresholds(lambda _cid: cam, cam_id)
            runtime._tracker.configure(
                spawn_default=tracks.spawn,
                floor=tracks.floor,
                grace_seconds=tracks.grace_seconds,
                iou_threshold=tracks.iou,
                block_contain=tracks.block_contain,
            )
            # DetectionSetup is resolved ONCE at runtime construction, on
            # the premise that every camera-config change restarts the
            # runtime. THIS ROUTE IS THE EXCEPTION — live-applying without
            # a restart is its whole purpose. Without this rebuild the
            # loop keeps the old object_filter, label_thresholds,
            # bottom_crop_px and roi_mode while the response below reports
            # the new ones under "effective": the panel would show an
            # applied setting the alarm path never received.
            from ..detect_setup import build_detection_setup

            runtime.detect_setup = build_detection_setup(
                cam_id,
                cam,
                roi_mode=runtime._effective_roi_mode(),
                global_cfg=runtime.global_cfg,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("[detection-tuning] %s live-apply failed: %s", cam_id, exc)
    return jsonify(
        {
            "ok": True,
            "effective": {
                "track_iou_match_threshold": cam.get("track_iou_match_threshold"),
                "track_miss_grace_seconds": cam.get("track_miss_grace_seconds"),
                "track_continue_min_score": cam.get("track_continue_min_score"),
                "track_spawn_min_score": cam.get("track_spawn_min_score"),
                "track_block_contain": cam.get("track_block_contain"),
                "label_thresholds": cam.get("label_thresholds") or {},
                "object_filter": cam.get("object_filter") or [],
                "excluded_classes": cam.get("excluded_classes") or [],
                "frame_interval_ms": cam.get("frame_interval_ms"),
                "motion_sensitivity": cam.get("motion_sensitivity"),
                "post_motion_tail_s": cam.get("post_motion_tail_s"),
                "track_filter_ghosts": cam.get("track_filter_ghosts") is not False,
                "roi_mode": cam.get("roi_mode") or "off",
                "wildlife_motion_sensitivity": cam.get("wildlife_motion_sensitivity"),
                "roi_min_net_disp_frac": cam.get("roi_min_net_disp_frac"),
            },
        }
    )
