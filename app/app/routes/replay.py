"""Re-run a stored clip through detection with a chosen settings set.

Sibling of `routes/tracking.py`, which owns the sidecar lifecycle and
whose `_resolve_event_video` this module reuses rather than re-deriving
the video path.

Why this is synchronous while the reindex endpoint next door enqueues:
that one is fire-and-forget — it produces a sidecar on disk and returns
``{"queued": 1}``. A replay's entire value is the ANSWER, so a caller
that got ``{"queued": 1}`` back would have to poll for a result the
worker has nowhere to put. So the work runs on the request thread and is
bounded instead (``REPLAY_MAX_SAMPLES`` decode attempts, with the
response reporting analysed-of-available).

That is safe for the live cameras for the same reason the queued jobs
are: the detection runs on the tracking worker's CPU-pinned detector
(`TrackingWorker.detector`), never on the Edge TPU the camera runtimes
own, and `CoralObjectDetector` serialises its own invokes.
"""

from __future__ import annotations

import json
import logging

from flask import Blueprint, jsonify, request

from .. import app_state
from ..replay import (
    append_replay,
    build_comparison,
    build_entry,
    list_revisions,
    replay_clip,
    resolve_replay_settings,
    revision_overrides,
)
from ..tracking_worker import singleton, tracks_path_for
from .tracking import _resolve_event_video

bp = Blueprint("replay", __name__)
log = logging.getLogger(__name__)


def _load_event(event_id: str):
    """``(camera_id, video_path, event)`` or a jsonify-able error."""
    cam_id, vid = _resolve_event_video(event_id, request.args.get("camera_id"))
    if cam_id is None or vid is None:
        return None, None, None, ("Event nicht gefunden oder ohne Video", 404)
    if not vid.exists():
        return None, None, None, ("Video-Datei fehlt", 404)
    event = app_state.store.get_event(cam_id, event_id)
    if not event:
        return None, None, None, ("Event nicht gefunden", 404)
    return cam_id, vid, event, None


def _sidecar_tracks(video_path):
    """The event's existing tracks.json, or None when it was never
    indexed.

    None and [] mean different things here: [] is "indexed, found
    nothing" and is a real baseline to diff against, while None is "no
    baseline exists". Returning [] for a missing sidecar would make
    every replay of an un-indexed clip claim its tracks had appeared.
    An unreadable sidecar is no baseline either.
    """
    path = tracks_path_for(video_path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("tracks") or []
    except Exception:
        return None


def _alarm_profile(event: dict, settings: dict, cam_cfg: dict):
    """The profile the alert preview should judge by — the one on
    record when replaying stored settings, the live one otherwise."""
    if settings.get("basis") == "provenance":
        camera = (event.get("provenance") or {}).get("camera") or {}
        if camera.get("alarm_profile"):
            return camera["alarm_profile"]
    return cam_cfg.get("alarm_profile")


def _descriptor(settings: dict) -> dict:
    """The settings descriptor minus the config itself — enough to name
    a set without shipping every knob to the browser."""
    return {k: v for k, v in settings.items() if k != "cfg"}


@bp.get('/api/camera/<cam_id>/profile-revisions')
def api_profile_revisions(cam_id):
    """The profile revisions this camera can be SIMULATED against.

    Listing only. Choosing one changes what a simulation shows and
    nothing else — the camera keeps running its own profile, and the
    only path that writes an archived net back onto a camera is the
    Erkennungsnetz's own restore endpoint.
    """
    if app_state.get_camera_cfg(cam_id) is None:
        return jsonify({"ok": False, "error": "Kamera nicht gefunden"}), 404
    return jsonify(
        {
            "ok": True,
            "camera_id": cam_id,
            "revisions": list_revisions(app_state.storage_root, cam_id),
        }
    )


@bp.get('/api/event/<event_id>/replay')
def api_event_replay_preflight(event_id):
    """What a replay WOULD run with, without running it.

    The player calls this when the details fold opens so it can label
    the two buttons and, when the stored and current sets hash the
    same, say so instead of spending a minute proving it.
    """
    cam_id, _vid, event, err = _load_event(event_id)
    if err:
        return jsonify({"ok": False, "error": err[0]}), err[1]
    cam_cfg = app_state.get_camera_cfg(cam_id) or {}
    stored = resolve_replay_settings(event, cam_cfg, "stored")
    current = resolve_replay_settings(event, cam_cfg, "current")
    return jsonify(
        {
            "ok": True,
            "camera_id": cam_id,
            "stored": _descriptor(stored),
            "current": _descriptor(current),
            "identical": stored["hash"] == current["hash"],
            "replays": event.get("replays") or [],
        }
    )


@bp.post('/api/event/<event_id>/replay')
def api_event_replay(event_id):
    """Replay the clip and return the comparison.

    Body: ``{"settings": "stored" | "current" | "factory" |
    {"tuning": {...}} | {"revision": <archive id>}, "classify": bool}``.
    ``settings`` defaults to ``"stored"`` — the case the feature exists
    for.

    ``classify`` defaults to True: the replay names the bird species it
    finds. Pass False for a cheap detector-only run — a threshold sweep
    over one clip, where every pass would reach the same species and
    the second stage is pure cost.
    """
    body = request.get_json(silent=True) or {}
    spec = body.get("settings", "stored")
    classify = bool(body.get("classify", True))
    if not isinstance(spec, dict) and spec not in ("stored", "current", "factory"):
        return jsonify(
            {"ok": False, "error": "settings muss stored, current, factory oder ein Objekt sein"}
        ), 400

    cam_id, vid, event, err = _load_event(event_id)
    if err:
        return jsonify({"ok": False, "error": err[0]}), err[1]
    worker = singleton()
    if worker is None:
        return jsonify({"ok": False, "error": "Tracking-Worker nicht aktiv"}), 503

    cam_cfg = app_state.get_camera_cfg(cam_id) or {}
    try:
        settings = resolve_replay_settings(
            event,
            cam_cfg,
            spec,
            revisions=lambda rid: revision_overrides(app_state.storage_root, cam_id, rid, cam_cfg),
        )
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    try:
        result = replay_clip(
            worker=worker,
            camera_id=cam_id,
            video_path=vid,
            storage_root=app_state.storage_root,
            cfg=settings["cfg"],
            classify=classify,
        )
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 422
    except Exception as e:
        log.error("[tracking] cam=%s replay failed: %s", cam_id, e, exc_info=True)
        return jsonify({"ok": False, "error": f"Nachsimulation fehlgeschlagen: {e}"}), 500

    comparison = build_comparison(
        event=event,
        sidecar_tracks=_sidecar_tracks(vid),
        replay=result,
        alarm_profile=_alarm_profile(event, settings, cam_cfg),
    )
    entry = build_entry(settings=settings, replay=result, comparison=comparison)
    history = append_replay(app_state.store, cam_id, event_id, entry)
    return jsonify(
        {
            "ok": True,
            "camera_id": cam_id,
            "event_id": event_id,
            "settings": _descriptor(settings),
            "frames_analysed": result["frames_analysed"],
            "frames_available": result["frames_available"],
            "truncated": result["truncated"],
            "duration_ms": result["duration_ms"],
            "detector": result["detector"],
            "comparison": comparison,
            "replays": len(history),
        }
    )
