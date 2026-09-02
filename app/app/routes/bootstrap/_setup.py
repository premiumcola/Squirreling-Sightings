"""First-run wizard plus settings import/export."""

from __future__ import annotations

from flask import Response, jsonify, request

from ... import app_state
from .._camera_helpers import _auto_detect_device_info
from ._blueprint import bp


@bp.post('/api/wizard/complete')
def api_wizard_complete():
    settings = app_state.settings
    payload = request.get_json(force=True) or {}
    try:
        if payload.get("app"):
            settings.update_section("app", payload["app"])
        if payload.get("server"):
            settings.update_section("server", payload["server"])
        if payload.get("telegram"):
            settings.update_section("telegram", payload["telegram"])
        if payload.get("mqtt"):
            settings.update_section("mqtt", payload["mqtt"])
        for cam in payload.get("cameras", []) or []:
            if cam.get("id"):
                # Auto-detect manuf/model on first save too — wizard
                # users typically enter creds but skip the optional
                # Reolink/RLC fields. Mutates cam in place; ignored
                # silently on non-Reolink or no-response.
                _auto_detect_device_info(cam)
                settings.upsert_camera(cam)
        settings.update_section("ui", {"wizard_completed": True})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422
    app_state.rebuild_runtimes()
    return jsonify({"ok": True, "bootstrap": settings.bootstrap_state()})


@bp.get('/api/settings/export')
def api_settings_export():
    fmt = request.args.get('format', 'json')
    text = app_state.settings.export_text(fmt)
    mimetype = 'application/x-yaml' if fmt == 'yaml' else 'application/json'
    return Response(
        text,
        mimetype=mimetype,
        headers={
            "Content-Disposition": f"attachment; filename=squirreling-sightings-settings.{fmt}"
        },
    )


@bp.post('/api/settings/import')
def api_settings_import():
    settings = app_state.settings
    payload = request.get_json(force=True) or {}
    fmt = payload.get('format', 'json')
    content = payload.get('content', '')
    try:
        settings.import_text(content, fmt)
        app_state.rebuild_runtimes()
        return jsonify({"ok": True, "bootstrap": settings.bootstrap_state()})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
