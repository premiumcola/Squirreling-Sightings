"""Batch replay of every archived bird clip against today's settings.

Sibling of `routes/replay.py`, which owns the single-event replay this
one calls in a loop. The two differ in exactly one way that matters
here: a single replay is bounded to REPLAY_MAX_SAMPLES and answers on
the request thread, while a batch over hundreds of clips is minutes to
hours of inference and cannot hold a Flask worker. So this follows the
job pattern `routes/media.py` uses for the integrity check — POST
starts a daemon thread, GET polls — plus the two-flag cancel from
weather_service/_sun_tl.

The clips themselves run on the tracking worker's CPU-pinned detector,
the same one the single replay borrows, so a batch never competes with
the live cameras for the Edge TPU.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from .. import app_state
from ..replay_batch import load_report, request_cancel, snapshot, start_batch
from ..tracking_worker import singleton
from .replay import _sidecar_tracks
from .tracking import _resolve_event_video

bp = Blueprint("replay_batch", __name__)
log = logging.getLogger(__name__)


def _clean_day(raw) -> str | None:
    """A `YYYYMMDD` bound, or None. Anything else is treated as absent
    rather than 400: a malformed date narrows nothing, and the scope the
    run actually used is echoed back in the report."""
    text = str(raw or "").strip().replace("-", "")
    return text if len(text) == 8 and text.isdigit() else None


def _scope_from(body: dict) -> dict:
    """The selection this run covers. Cameras default to all, dates to
    unbounded — "every bird clip", which is what was asked for."""
    cams = body.get("cameras")
    if isinstance(cams, str):
        cams = [cams]
    cams = [str(c) for c in cams if str(c).strip()] if isinstance(cams, list) else None
    return {
        "cameras": cams or None,
        "since": _clean_day(body.get("since")),
        "until": _clean_day(body.get("until")),
    }


def _video_for(event_id: str, camera_id: str):
    """Path of an event's clip, or None. Wraps `_resolve_event_video`
    for the batch's `(event_id, camera_id) -> Path | None` shape."""
    _cam, vid = _resolve_event_video(event_id, camera_id)
    return vid


def _context(worker) -> dict:
    """Everything the run needs from the app, resolved once per run."""
    return {
        "store": app_state.store,
        "storage_root": app_state.storage_root,
        "worker": worker,
        "cam_cfg_for": app_state.get_camera_cfg,
        "resolve_video": _video_for,
        "sidecar_tracks_for": _sidecar_tracks,
    }


@bp.post('/api/replay/batch')
def api_replay_batch_start():
    """Start a batch replay.

    Body (all optional): ``{"cameras": [...], "since": "YYYYMMDD",
    "until": "YYYYMMDD"}``. Selection is bird clips only.
    """
    worker = singleton()
    if worker is None:
        return jsonify({"ok": False, "error": "Tracking-Worker nicht aktiv"}), 503
    scope = _scope_from(request.get_json(silent=True) or {})
    if not start_batch(_context(worker), scope):
        return jsonify({"ok": True, "already_running": True, **snapshot()}), 200
    log.info("[tracking] batch replay started: scope=%s", scope)
    return jsonify({"ok": True, "already_running": False, **snapshot()})


@bp.get('/api/replay/batch')
def api_replay_batch_status():
    """Progress while running, the report once done.

    Falls back to the persisted report when no run has happened in this
    process — the point of writing it to disk is that a restart does not
    lose the answer.
    """
    state = snapshot()
    report = state.get("report") or load_report(app_state.storage_root)
    return jsonify({"ok": state.get("error") is None, **state, "report": report})


@bp.post('/api/replay/batch/cancel')
def api_replay_batch_cancel():
    """Ask a running batch to stop at the next clip boundary. The rows
    already collected are still folded, persisted and reported — a
    cancelled run returns a partial answer, not nothing."""
    if not request_cancel():
        return jsonify({"ok": False, "error": "Kein Durchlauf aktiv"}), 409
    return jsonify({"ok": True, **snapshot()})
