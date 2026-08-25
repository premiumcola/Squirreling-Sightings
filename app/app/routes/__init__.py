"""Per-domain Flask blueprints carved out of server.py.

The split runs in stages (R01.2 → R01.5). At each stage, server.py
calls `register_blueprints(app)` once after the Flask app is built and
after `app_state` is wired up. Blueprints reach shared state via
`from .. import app_state` — never via `from ..server import ...`,
since that would close a circular-import loop.

The one-way exception: a handful of routes need the boot helpers
`rebuild_runtimes` / `restart_single_camera`, which still live in
server.py. Those imports are lazy (inside the route function body) to
avoid the import-time cycle. R01.6 cleans this up by relocating the
boot helpers out of server.py.
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
        bootstrap,
        cameras,
        coral,
        coral_test_detection,
        detection_cloud,
        events,
        media,
        sichtungen,
        streams,
        telegram,
        timelapse,
        timeline_stats,
        tracking,
        trash,
        weather,
    )

    app.register_blueprint(tracking.bp)
    app.register_blueprint(sichtungen.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(bootstrap.bp)
    app.register_blueprint(cameras.bp)
    app.register_blueprint(streams.bp)
    app.register_blueprint(media.bp)
    app.register_blueprint(events.bp)
    app.register_blueprint(timeline_stats.bp)
    app.register_blueprint(timelapse.bp)
    app.register_blueprint(coral.bp)
    # N14 · per-cam test-detection lives in its own module now.
    app.register_blueprint(coral_test_detection.bp)
    app.register_blueprint(weather.bp)
    app.register_blueprint(telegram.bp)
    app.register_blueprint(detection_cloud.bp)
    app.register_blueprint(trash.bp)

    # Registered after the blueprints so it covers every one of them.
    app.before_request(_reject_traversal_cam_ids)
