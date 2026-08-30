"""Global app settings — GET/POST /api/settings/app.

Carved out of routes/cameras.py (886 lines against a 500-line ceiling).
This is the app-wide section (Telegram, MQTT, processing toggles), not
the per-camera one, and it is where ``redact_secrets`` guards the bot
token and the broker password on the way out.
"""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, jsonify, request

from .. import app_state
from ._secrets import redact_secrets

bp = Blueprint("app_settings", __name__)


@bp.get('/api/settings/app')
def api_settings_app():
    settings = app_state.settings
    proc = settings.data.get("processing", {})
    eff = app_state.get_effective_config().get("processing", {}) or {}
    bird_cfg = eff.get("bird_species", {}) or {}
    wl_cfg = eff.get("wildlife", {}) or {}
    bird_model_path = bird_cfg.get("model_path")
    bird_cpu_path = bird_cfg.get("cpu_model_path")
    bird_labels_path = bird_cfg.get("labels_path")
    wl_model_path = wl_cfg.get("model_path")
    wl_cpu_path = wl_cfg.get("cpu_model_path")
    wl_labels_path = wl_cfg.get("labels_path")
    bird_model_available = any(p and Path(p).exists() for p in (bird_model_path, bird_cpu_path))
    bird_labels_available = bool(bird_labels_path and Path(bird_labels_path).exists())
    wl_model_available = any(p and Path(p).exists() for p in (wl_model_path, wl_cpu_path))
    wl_labels_available = bool(wl_labels_path and Path(wl_labels_path).exists())
    # Auto-discover the wildlife model when the configured path is missing
    # or absent on disk. Same heuristic the WildlifeClassifier itself uses,
    # so the API response and runtime stay in sync.
    if not wl_model_available:
        from ..detectors import discover_wildlife_paths

        disc = discover_wildlife_paths()
        if disc:
            wl_model_path = disc.get("model_path") or wl_model_path
            wl_cpu_path = disc.get("cpu_model_path") or wl_cpu_path
            wl_model_available = True
            if not wl_labels_available and disc.get("labels_path"):
                wl_labels_path = disc["labels_path"]
                wl_labels_available = True
    return jsonify(
        {
            "app": settings.data.get("app", {}),
            "server": settings.data.get("server", {}),
            "telegram": redact_secrets(settings.data.get("telegram"), ("token",)),
            "mqtt": redact_secrets(settings.data.get("mqtt"), ("password",)),
            "ui": settings.data.get("ui", {}),
            "processing": {
                "coral_enabled": proc.get("detection", {}).get("mode", "none") == "coral",
                "bird_species_enabled": bool(proc.get("bird_species", {}).get("enabled", False)),
                "bird_model_available": bird_model_available,
                "bird_labels_available": bird_labels_available,
                "bird_model_path": bird_model_path,
                "wildlife_enabled": bool(proc.get("wildlife", {}).get("enabled", False)),
                "wildlife_model_available": wl_model_available,
                "wildlife_labels_available": wl_labels_available,
                "wildlife_model_path": wl_model_path,
            },
        }
    )


@bp.post('/api/settings/app')
def api_settings_app_save():
    settings = app_state.settings
    payload = request.get_json(force=True) or {}
    needs_rebuild = False
    try:
        # `trash` joins the plain schema-validated sections: `trash.grace_days`
        # is read live by `trash._grace_days` and enforced by the daily
        # `cleanup_expired` sweep, but this tuple was the only save path
        # and it omitted the section — so SECTION_SCHEMAS["trash"] was
        # validating a call nobody could make. No UI control ships with
        # this; reachable-by-API is the point.
        for sec in ("app", "server", "ui", "storage", "trash"):
            if sec in payload:
                settings.update_section(sec, payload.get(sec) or {})
        if "telegram" in payload:
            # Telegram credentials change → rebuild_runtimes() picks up the
            # new bot token / chat id so the next test (and any subsequent
            # alert from a camera) uses the fresh service.
            settings.update_section("telegram", payload.get("telegram") or {})
            needs_rebuild = True
        if "mqtt" in payload:
            settings.update_section("mqtt", payload.get("mqtt") or {})
            needs_rebuild = True
        if "processing" in payload:
            proc = payload["processing"]
            sec = {
                "detection": {"mode": "coral" if proc.get("coral_enabled") else "none"},
                "bird_species": {"enabled": bool(proc.get("bird_species_enabled"))},
            }
            # Only touch wildlife if the client actually sent it — otherwise
            # saving the Coral toggles would clobber an existing wildlife
            # config that the user set up separately.
            if "wildlife_enabled" in proc:
                sec["wildlife"] = {"enabled": bool(proc.get("wildlife_enabled"))}
            settings.update_section("processing", sec)
            needs_rebuild = True
        if "weather" in payload:
            # update_section deep-merges (Phase 2 telegram fix), so partial
            # writes like {"events": {"thunder": {"threshold": 800}}} don't
            # wipe sibling keys.
            weather_payload = payload.get("weather") or {}
            settings.update_section("weather", weather_payload)
            # A retention slider save is the only "attended" moment weather
            # has (no separate "Jetzt bereinigen" button) — confirm any
            # per-category day-count it carries against the nightly
            # widening guard, mirroring api_media_cleanup's override path.
            from ..weather_service._retention import acknowledge_weather_retention_from_payload

            acknowledge_weather_retention_from_payload(weather_payload)
            needs_rebuild = True
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422
    if needs_rebuild:
        app_state.rebuild_runtimes()
    return jsonify({"ok": True, "saved": True})
