"""Per-domain Flask blueprints carved out of server.py.

The split runs in stages (R01.2 → R01.5). At each stage, server.py
calls `register_blueprints(app)` once after the Flask app is built and
after `app_state` is wired up. Blueprints reach shared state via
`from .. import app_state` — never via `from ..server import ...`,
since that would close a circular-import loop.

R01.6 closed the last exception: routes that need the boot helpers now
call `app_state.rebuild_runtimes()` / `app_state.restart_single_camera()`,
which server.py publishes onto app_state at boot. Nothing imports
server.py by name any more — and nothing may start again. Production
runs `python -m app.server`, so that file is owned by `__main__` and
`app.server` is absent from sys.modules; the first `from ..server import
...` therefore re-executes the entire boot block as a second module,
yielding a duplicate camera-runtime set and a second Telegram poller on
the same token (the T61 Conflict).
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _reject_traversal_cam_ids():
    """404 any request whose ``cam_id`` carries path-traversal shapes.

    Camera ids reach the filesystem directly — ``storage_root / cam_id``
    appears in media.py, timelapse.py, events.py and cameras.py. Flask's
    default converter already refuses a literal "/", but a percent-
    encoded dot segment still arrives as ".." and walks one directory up.
    On the timelapse delete route (which validates ``filename`` but not
    ``cam_id``) that is enough to unlink a file outside the timelapse
    tree, so the guard lives here rather than in any one handler: a new
    blueprint cannot reintroduce the gap by forgetting its own check.

    Deliberately NOT the full canonical grammar from
    ``_helpers.safe_cam_id`` — ``build_camera_id()`` applies no length
    cap, so a long camera name yields an id past that helper's 64-char
    ceiling and a strict gate would 404 a legitimate camera. What is
    enforced here is the security property only.
    """
    from flask import abort, request

    cam_id = (request.view_args or {}).get("cam_id")
    if isinstance(cam_id, str) and (
        "/" in cam_id or "\\" in cam_id or ".." in cam_id or "\x00" in cam_id
    ):
        log.warning("[http] rejected cam_id with traversal shape: %r", cam_id)
        abort(404)


def register_blueprints(app) -> None:
    """Register every route blueprint shipped under app/app/routes/.

    Imported from `server.py` exactly once during boot. New blueprints
    appended here follow the same rule: each one carries its own
    `/api/...` paths internally (no `url_prefix=` on the registration
    side) so the URL space remains identical to the pre-split layout.
    """
    from . import (
        admin,
        app_settings,
        bootstrap,
        camera_backups,
        camera_device,
        camera_merge,
        cameras,
        coral,
        coral_test_detection,
        detection_cloud,
        events,
        media,
        netz,
        retention_panel,
        sichtungen,
        simu_log,
        streams,
        telegram,
        telemetry,
        timelapse,
        timeline_stats,
        tracking,
        trash,
        weather,
        weather_episodes,
        weather_maintenance,
        weather_manual_events,
        weather_pin,
        weather_suntl_test,
    )

    app.register_blueprint(tracking.bp)
    app.register_blueprint(sichtungen.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(bootstrap.bp)
    app.register_blueprint(cameras.bp)
    # Carved out of cameras.py, which stood 386 lines past the file
    # ceiling. Same URL space — no url_prefix on any of them.
    app.register_blueprint(camera_backups.bp)
    app.register_blueprint(camera_device.bp)
    app.register_blueprint(camera_merge.bp)
    app.register_blueprint(app_settings.bp)
    app.register_blueprint(streams.bp)
    app.register_blueprint(media.bp)
    app.register_blueprint(events.bp)
    # NETZ · Erkennungsnetz + Verlaufs-Archiv. Own module because
    # neither cameras.py nor events.py has room, and because the net's
    # two surfaces share one helper module.
    app.register_blueprint(netz.bp)
    app.register_blueprint(timeline_stats.bp)
    app.register_blueprint(timelapse.bp)
    app.register_blueprint(coral.bp)
    # N14 · per-cam test-detection lives in its own module now.
    app.register_blueprint(coral_test_detection.bp)
    # SIMU run log — store / list / fetch one "Debug kopieren" run. Own
    # module because coral_test_detection.py is already past the ceiling.
    app.register_blueprint(simu_log.bp)
    app.register_blueprint(weather.bp)
    # Storm-episode archive — its own module because routes/weather.py
    # is already past the file ceiling.
    app.register_blueprint(weather_episodes.bp)
    # Manual weather events (user-saved chart ranges) — same reasoning.
    app.register_blueprint(weather_manual_events.bp)
    # Sighting pin/unpin toggle — same reason, own module.
    app.register_blueprint(weather_pin.bp)
    # Archive rescan + bulk thumb regen — same reason. Offline repair
    # routes, not part of the live sighting pipeline.
    app.register_blueprint(weather_maintenance.bp)
    # Ad-hoc sun-timelapse test capture (start/status/cancel) — same
    # reason, a self-contained diagnostic surface.
    app.register_blueprint(weather_suntl_test.bp)
    app.register_blueprint(telegram.bp)
    # Device-scoped inference telemetry — deliberately not folded into
    # /api/status (per-camera) nor into the two oversized coral modules.
    app.register_blueprint(telemetry.bp)
    app.register_blueprint(detection_cloud.bp)
    app.register_blueprint(trash.bp)
    # Mediathek-Verwaltung — one panel for every retention window.
    # Carries an app_context_processor, so it must be registered for
    # the maintenance partial to render its rows.
    app.register_blueprint(retention_panel.bp)

    # Registered after the blueprints so it covers every one of them.
    app.before_request(_reject_traversal_cam_ids)
