"""The two read-only config endpoints: /api/bootstrap and /api/config."""

from __future__ import annotations

from flask import jsonify

from ... import app_state
from ...io_utils import path_exists_cached
from .._secrets import redact_camera
from ._blueprint import bp


@bp.get('/api/bootstrap')
def api_bootstrap():
    return jsonify(app_state.settings.bootstrap_state())


@bp.get('/api/config')
def api_config():
    settings = app_state.settings
    base_cfg = app_state.base_cfg
    c = app_state.get_effective_config()
    proc = c.get("processing", {}) or {}
    bird_cfg = proc.get("bird_species", {}) or {}
    bird_model_path = bird_cfg.get("model_path")
    bird_cpu_path = bird_cfg.get("cpu_model_path")
    bird_labels_path = bird_cfg.get("labels_path")
    # P30 · model paths live in /app/models and don't change at
    # runtime, so the LRU-cached existence check skips the syscall
    # on the second-and-later /api/config hit (the dashboard polls
    # this endpoint every few seconds).
    bird_model_available = any(
        p and path_exists_cached(p) for p in (bird_model_path, bird_cpu_path)
    )
    # Wildlife block — must mirror the four fields surfaced by
    # /api/settings/app, otherwise hydrateAppSettings reads
    # proc.wildlife_enabled as undefined → false and flips the toggle
    # back ~2 s after the user enables it (loadAll re-fetches /api/config
    # after the POST). Same auto-discover fallback as /api/settings/app
    # so both endpoints stay in sync on a fresh install where the user
    # hasn't pinned a model_path yet.
    wl_cfg = proc.get("wildlife", {}) or {}
    wl_model_path = wl_cfg.get("model_path")
    wl_cpu_path = wl_cfg.get("cpu_model_path")
    wl_labels_path = wl_cfg.get("labels_path")
    wl_model_available = any(p and path_exists_cached(p) for p in (wl_model_path, wl_cpu_path))
    wl_labels_available = bool(wl_labels_path and path_exists_cached(wl_labels_path))
    if not wl_model_available:
        from ...detectors import discover_wildlife_paths

        disc = discover_wildlife_paths()
        if disc:
            wl_model_path = disc.get("model_path") or wl_model_path
            wl_model_available = True
            if not wl_labels_available and disc.get("labels_path"):
                wl_labels_path = disc["labels_path"]
                wl_labels_available = True
    srv = c.get("server", {}) or {}
    return jsonify(
        {
            "app": c.get("app", {}),
            "server": {
                "public_base_url": srv.get("public_base_url", ""),
                # Standortdaten — von der Wetter-UI gelesen, vom Wetter-Service
                # für Sonnenstand-Berechnung genutzt.
                "location": srv.get("location") or {"lat": None, "lon": None, "elevation": None},
            },
            "default_discovery_subnet": srv.get("default_discovery_subnet", "192.168.1.0/24"),
            # Redacted: no camera password, no `user:pass@` in any URL.
            # This endpoint is unauthenticated, plain HTTP, and polled
            # by live-update.js on every dashboard tick.
            "cameras": [redact_camera(cam) for cam in c.get("cameras", [])],
            "weather": c.get("weather") or {},
            "coral": {
                "mode": proc.get("detection", {}).get("mode", "none"),
                "bird_species_enabled": bool(bird_cfg.get("enabled")),
            },
            "processing": {
                "detection": proc.get("detection", {}),
                "bird_species_enabled": bool(bird_cfg.get("enabled")),
                "bird_model_available": bird_model_available,
                "bird_labels_available": bool(
                    bird_labels_path and path_exists_cached(bird_labels_path)
                ),
                "bird_model_path": bird_model_path,
                "wildlife_enabled": bool(wl_cfg.get("enabled", False)),
                "wildlife_model_available": wl_model_available,
                "wildlife_labels_available": wl_labels_available,
                "wildlife_model_path": wl_model_path,
            },
            # Secrets are never shipped to the browser — only "is one
            # stored?". Holds for the camera list above too. See
            # routes/_secrets for the full contract.
            "telegram": {
                "enabled": bool(c.get("telegram", {}).get("enabled")),
                "chat_id": c.get("telegram", {}).get("chat_id", ""),
                "token_set": bool(c.get("telegram", {}).get("token")),
                # hydrateTelegram() checks the matching format radio off
                # this and the Verbindung form used to echo it back on
                # save. Omitting it meant `tg.format || 'photo'` read
                # 'photo' forever, so every connection save silently
                # reset a 'video' or 'text' choice.
                "format": c.get("telegram", {}).get("format", "photo"),
            },
            "mqtt": {
                "enabled": bool(c.get("mqtt", {}).get("enabled")),
                "base_topic": c.get("mqtt", {}).get("base_topic", "tam-spy"),
                "host": c.get("mqtt", {}).get("host", ""),
                "port": c.get("mqtt", {}).get("port", 1883),
                "username": c.get("mqtt", {}).get("username", ""),
                "password_set": bool(c.get("mqtt", {}).get("password")),
            },
            "storage": {
                "root": str(base_cfg.get("storage", {}).get("root", "/app/storage")),
                "retention_days": settings.data.get("storage", {}).get("retention_days")
                or base_cfg.get("storage", {}).get("retention_days", 14),
                "media_limit_default": settings.data.get("storage", {}).get("media_limit_default")
                or base_cfg.get("storage", {}).get("media_limit_default", 24),
                "auto_cleanup_enabled": bool(
                    settings.data.get("storage", {}).get("auto_cleanup_enabled", False)
                ),
            },
        }
    )
