"""Per-camera device probes — Reolink model auto-detect + image mode.

Carved out of routes/cameras.py (886 lines against a 500-line ceiling).
These two endpoints are the only ones in the camera surface that talk to
the camera over its HTTP API rather than to settings.json.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from .. import app_state

log = logging.getLogger(__name__)

bp = Blueprint("camera_device", __name__)


@bp.post('/api/cameras/<cam_id>/probe-device-info')
def api_camera_probe_device_info(cam_id: str):
    """Manual rescan endpoint behind the cam-edit "jetzt erneut erkennen"
    button. Runs the same Reolink GetDevInfo flow as the auto-detect
    save path but on demand and without persisting — the frontend then
    asks the user whether to overwrite existing manuf/model values.
    Used when a camera is firmware-updated or physically replaced but
    keeps the same IP, where the persisted manuf/model are stale.
    """
    cam = app_state.settings.get_camera(cam_id)
    if not cam:
        return jsonify({"ok": False, "error": "camera not found"}), 404
    rtsp_url = (cam.get("rtsp_url") or "").strip()
    user = cam.get("username") or ""
    password = cam.get("password") or ""
    if not rtsp_url or not user:
        return jsonify({"ok": False, "error": "no credentials configured"}), 400
    try:
        from urllib.parse import urlparse

        host = urlparse(rtsp_url).hostname
    except Exception:
        host = None
    if not host:
        return jsonify({"ok": False, "error": "cannot parse host from rtsp_url"}), 400
    try:
        from .. import reolink_api

        token = reolink_api.login(host, user, password, timeout=4.0)
        if not token:
            return jsonify({"ok": False, "error": "login failed"}), 502
        info = reolink_api.get_device_info(host, token, timeout=4.0)
        reolink_api.logout(host, token, timeout=2.0)
    except Exception as e:
        return jsonify({"ok": False, "error": f"probe failed: {e}"}), 502
    if not info:
        return jsonify({"ok": False, "error": "no device info returned"}), 502
    return jsonify(
        {
            "ok": True,
            "manufacturer": info["manufacturer"],
            "model": info["model"],
            "firmware": info["firmware"],
            "hardware": info["hardware"],
            "current": {
                "manufacturer": cam.get("manufacturer", ""),
                "model": cam.get("model", ""),
            },
        }
    )


@bp.post('/api/cameras/<cam_id>/reolink/image-mode')
def api_camera_reolink_image_mode(cam_id: str):
    """Standalone day/night override test panel — manually triggered
    from the Verbindung tab. Hits Reolink's SetIsp + IrLights pair via
    :func:`reolink_api.set_image_mode`; not wired into the timelapse
    pipeline (that comes back in a later round once the operator has
    confirmed the toggle actually works on his cameras).

    Body: ``{"mode": "auto" | "color" | "bw"}``.
    Returns the underlying ``set_image_mode`` result plus the
    masked-back ``mode`` so the UI can echo it.
    """
    cam = app_state.settings.get_camera(cam_id)
    if not cam:
        return jsonify({"ok": False, "error": "camera not found"}), 404
    vendor = (cam.get("manufacturer") or "").strip().lower()
    if vendor != "reolink":
        return jsonify(
            {
                "ok": False,
                "error": "image-mode override is Reolink-only "
                f"(camera vendor={cam.get('manufacturer') or '?'})",
            }
        ), 400
    body = request.get_json(silent=True) or {}
    mode = str(body.get("mode") or "").strip().lower()
    if mode not in ("auto", "color", "bw"):
        return jsonify(
            {
                "ok": False,
                "error": "mode must be one of auto / color / bw",
            }
        ), 400
    # Pull host from rtsp_url (we never persist the bare host
    # separately — the URL is the source of truth). Fall back to
    # snapshot_url if rtsp_url is empty.
    src = (cam.get("rtsp_url") or cam.get("snapshot_url") or "").strip()
    if not src:
        return jsonify({"ok": False, "error": "no rtsp/snapshot URL configured"}), 400
    try:
        from urllib.parse import urlparse

        host = urlparse(src).hostname
    except Exception:
        host = None
    if not host:
        return jsonify({"ok": False, "error": "cannot parse host from camera URL"}), 400
    user = cam.get("username") or ""
    password = cam.get("password") or ""
    try:
        port = int(cam.get("reolink_http_port") or 0) or 80
    except (TypeError, ValueError):
        port = 80
    try:
        from .. import reolink_api

        result = reolink_api.set_image_mode(
            host,
            port,
            user,
            password,
            mode,
            timeout=4.0,
        )
    except Exception as e:
        return jsonify(
            {
                "ok": False,
                "error": f"image-mode call failed: {e}",
            }
        ), 502
    status_code = 200 if result.get("ok") else 502
    return jsonify(
        {
            "ok": bool(result.get("ok")),
            "mode": mode,
            "rc": result.get("rc"),
            "detail": result.get("detail", ""),
        }
    ), status_code


@bp.post('/api/cameras/<cam_id>/reveal-secret')
def api_camera_reveal_secret(cam_id: str):
    """The stored RTSP password, for the cam-edit "eye" button.

    Why this is a dedicated endpoint and not simply the password back in
    ``/api/cameras``: that collection is polled every few seconds by every
    open dashboard, so putting the secret there is what previously placed
    it in every response body, every browser cache and — beside a username
    field — in Chrome's password manager. See ``routes/_secrets.py`` for
    the full reasoning; ``redact_camera`` stays exactly as strict.

    This costs one deliberate request per reveal, carries the value in
    nothing that is cached, and never logs it. The residual exposure is
    real and worth naming: the box serves plain HTTP on the LAN with no
    authentication, so anyone who can already reach it can call this. That
    was equally true of the old behaviour — the difference is that the
    secret is no longer handed out unasked, hundreds of times an hour.
    """
    cam = app_state.settings.get_camera(cam_id) if app_state.settings else None
    if not cam:
        return jsonify({"ok": False, "error": "camera not found"}), 404
    password = cam.get("password") or ""
    log.info("[http] reveal-secret angefordert: cam=%s vorhanden=%s", cam_id, bool(password))
    resp = jsonify({"ok": True, "password": password, "password_set": bool(password)})
    # Never let a proxy, the browser cache or the back-button hold this.
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    resp.headers["Pragma"] = "no-cache"
    return resp
