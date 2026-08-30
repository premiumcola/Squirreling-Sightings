"""SIMU log endpoints — store a debug run, list them, fetch one.

Own module rather than a third handler bolted onto
``coral_test_detection.py``, which is already past the file ceiling.

The POST is deliberately NOT "write what the client sent". The server
rebuilds the document from its own state — the same
``build_snapshot`` the clipboard fetched moments earlier — and takes only
the three browser-owned values from the request body: the next-tick
delay, the bbox hold time, and the browser's own view state. Nothing a
client says can otherwise reach the file, and the camera config in it has
already been through ``redact_camera`` on the way out of settings.
"""

from __future__ import annotations

import logging
from pathlib import Path

from flask import Blueprint, jsonify, request

from .. import app_state, simu_log
from ._debug_snapshot import build_snapshot
from ._secrets import redact_camera

bp = Blueprint("simu_log", __name__)

log = logging.getLogger(__name__)


def _storage_root() -> Path:
    cfg = app_state.get_effective_config() or {}
    return Path((cfg.get("storage") or {}).get("root", "/app/storage"))


def _num(val):
    if val is None or isinstance(val, bool):
        return None
    try:
        return int(round(float(val)))
    except (TypeError, ValueError):
        return None


def _build_run(cam: dict, cam_id: str, body: dict) -> dict:
    """The document to store: the server's own snapshot plus the three
    values only the browser holds."""
    from . import _sim_pipeline

    snap = build_snapshot(
        # redact_camera drops `password` for `password_set` and strips the
        # userinfo password out of every URL. The stored run therefore
        # never sees the secret at all, which is a stronger property than
        # scrubbing it back out afterwards — _scrub is the belt on top.
        cam=redact_camera(cam),
        cam_id=cam_id,
        tt=_sim_pipeline.trackers().get(cam_id) or {},
        runtime=app_state.runtimes.get(cam_id),
        eff_cfg=app_state.get_effective_config(),
    )
    doc = snap["doc"]
    doc["tick"]["next_ms"] = _num(body.get("next_ms"))
    doc["tick"]["hold_ms"] = _num(body.get("hold_ms"))
    doc["frontend"] = simu_log.clamp_frontend(body.get("frontend"))
    return doc


@bp.post('/api/cameras/<cam_id>/simu-log')
def api_simu_log_store(cam_id: str):
    """Record one "Debug kopieren" run.

    Fail-soft by contract: the clipboard write already happened in the
    browser before this fired, so a storage failure is reported as
    ``ok: false`` with 200 rather than as an error the UI has to handle.
    """
    cam = app_state.settings.get_camera(cam_id)
    if not cam:
        return jsonify({"ok": False, "error": "camera not found"}), 404
    body = request.get_json(force=True, silent=True) or {}
    try:
        doc = _build_run(cam, cam_id, body)
    except Exception as e:
        log.warning("[http] simu-log: Lauf für %s nicht gebaut: %s", cam_id, e)
        return jsonify({"ok": False, "error": "snapshot failed"})
    name = simu_log.store_run(_storage_root(), cam_id, doc)
    if not name:
        return jsonify({"ok": False, "error": "write failed"})
    log.info("[http] simu-log: Lauf %s für %s gespeichert", name, cam_id)
    return jsonify({"ok": True, "name": name, "url": f"/api/cameras/{cam_id}/simu-log/{name}"})


@bp.get('/api/cameras/<cam_id>/simu-log')
def api_simu_log_list(cam_id: str):
    """Stored runs, newest first — so a run can be found without a shell
    on the host."""
    return jsonify({"ok": True, "runs": simu_log.list_runs(_storage_root(), cam_id)})


@bp.get('/api/cameras/<cam_id>/simu-log/<name>')
def api_simu_log_read(cam_id: str, name: str):
    """One stored run, verbatim. ``name`` is gated by RUN_NAME_RE inside
    ``read_run`` before it is joined onto a path."""
    doc = simu_log.read_run(_storage_root(), cam_id, name)
    if doc is None:
        return jsonify({"ok": False, "error": "run not found"}), 404
    return jsonify({"ok": True, "run": doc})
