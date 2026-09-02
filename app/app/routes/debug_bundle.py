"""Debug-Bundle endpoints — build one, list the ones on disk.

Own module for the same reason ``simu_log.py`` is one: the two modules
this would otherwise belong to (``bootstrap.py``, ``coral_test_detection.py``)
are both past the file ceiling.

The ZIP itself is served by the existing ``/media/<path>`` route — the
bundle directory sits inside the storage root — so there is no second
static handler and no second traversal surface here.
"""

from __future__ import annotations

import logging
from pathlib import Path

from flask import Blueprint, jsonify

from .. import app_state, debug_bundle

bp = Blueprint("debug_bundle", __name__)

log = logging.getLogger(__name__)


def _storage_root() -> Path:
    cfg = app_state.get_effective_config() or {}
    return Path((cfg.get("storage") or {}).get("root", "/app/storage"))


@bp.post('/api/debug/bundle')
def api_debug_bundle_create():
    """Collect config, status, telemetry, events, tuning and the log
    tail into one redacted ZIP under ``storage/debug/``."""
    try:
        out = debug_bundle.create_bundle(_storage_root())
    except Exception as e:
        log.warning("[http] debug bundle: nicht erstellt: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify(out)


@bp.get('/api/debug/bundle')
def api_debug_bundle_list():
    """Every bundle on disk, newest first."""
    items = debug_bundle.list_bundles(_storage_root())
    return jsonify({"ok": True, "items": items, "max": debug_bundle.MAX_BUNDLES})
