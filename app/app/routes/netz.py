"""``/api/netz/*`` — the Erkennungsnetz and its Verlaufs-Archiv.

Eight endpoints, two surfaces. Every write goes through
``SettingsStore.upsert_camera`` (an additive merge onto the stored
camera dict), never through a wholesale write of settings.json.

The reads are all projections of ``thresholds.resolve_effective``: the
value AND the layer that produced it, so the panel can show which force
last moved each axis instead of showing one layer and claiming it is the
answer.
"""

from __future__ import annotations

import contextlib
import logging
from datetime import datetime

from flask import Blueprint, jsonify, request, send_file

from .. import app_state, net_archive
from ..net_archive import PAGE_SIZE
from ..thresholds._apply import clamp_e, effective_e, push_for, rails
from ..thresholds._learner import preview
from . import _netz_helpers as H

bp = Blueprint("netz", __name__)
log = logging.getLogger(__name__)


@bp.get("/api/netz/state")
def api_netz_state():
    """Axes, E, thresholds, provenance, evidence, proposal, rails."""
    cam_id = request.args.get("cam") or ""
    if not cam_id:
        chips = H.camera_chips()
        if not chips:
            return jsonify({"ok": False, "error": "Keine Kamera konfiguriert"}), 404
        cam_id = chips[0]["id"]
    state = H.net_state(cam_id)
    if state is None:
        return jsonify({"ok": False, "error": "Kamera nicht gefunden"}), 404
    return jsonify({"ok": True, **state})


@bp.patch("/api/netz/<cam_id>/axes")
def api_netz_axes(cam_id):
    """Commit staged axes. One call for all of them — the staging bar's
    „Übernehmen" is a single write, not one per vertex."""
    payload = request.get_json(force=True, silent=True) or {}
    axes = payload.get("axes")
    if not isinstance(axes, dict) or not axes:
        return jsonify({"ok": False, "error": "axes muss ein Objekt sein"}), 400
    cam = H.camera(cam_id)
    if cam is None:
        return jsonify({"ok": False, "error": "Kamera nicht gefunden"}), 404
    before = {lab: effective_e(cam, lab) for lab in axes}
    written = H.apply_axes(cam_id, axes, pin=True)
    _archive_manual(cam_id, cam, before, written)
    _reload_runtimes()
    log.info("[det] Netz-Achsen gesetzt: cam=%s %s", cam_id, sorted(written))
    return jsonify({"ok": True, "written": written, "state": H.net_state(cam_id)})


def _archive_manual(cam_id: str, cam: dict, before: dict, written: dict) -> None:
    """One record per dragged axis — same list, same detail sheet.

    That is what makes „Netz zu diesem Zeitpunkt wiederherstellen"
    possible for a hand-set value and not only for a learned one.
    """
    state = H.net_state(cam_id) or {}
    net_state = {a["label"]: a for a in state.get("axes") or []}
    # Microseconds, matching `_motion._build_event_meta`'s event_id shape.
    # A second-resolution stamp collides when two commits land inside the
    # same second — the later record then OVERWRITES the earlier one and
    # "Netz zu diesem Zeitpunkt wiederherstellen" silently restores the
    # wrong moment.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    for i, (label, info) in enumerate(sorted(written.items())):
        with contextlib.suppress(Exception):
            net_archive.record_net_change(
                app_state.storage_root,
                event_id=f"netz-{stamp}-{i:02d}-{label}",
                cam_id=cam_id,
                cam_name=cam.get("name") or cam_id,
                label=label,
                e_before=before.get(label, 50),
                e_after=info["E"],
                push_before=push_for(label, before.get(label, 50)),
                push_after=info["push"],
                net_state=net_state,
                rails=rails(),
            )


def _reload_runtimes() -> None:
    """A threshold the pipeline does not yet read is a threshold that
    silently did nothing for the rest of the day."""
    with contextlib.suppress(Exception):
        rebuild = getattr(app_state, "rebuild_runtimes", None)
        if callable(rebuild):
            rebuild()


@bp.get("/api/netz/<cam_id>/preview")
def api_netz_preview(cam_id):
    """The drag pill's third line — consequence before commit."""
    cam = H.camera(cam_id)
    if cam is None:
        return jsonify({"ok": False, "error": "Kamera nicht gefunden"}), 404
    label = request.args.get("label") or ""
    if not label:
        return jsonify({"ok": False, "error": "label fehlt"}), 400
    e_value = clamp_e(request.args.get("e"))
    try:
        result = preview(app_state.storage_root, cam, label, e_value)
    except Exception as e:
        log.debug("[det] Netz-Vorschau fehlgeschlagen: %s", e)
        result = {"has_corpus": False}
    return jsonify({"ok": True, "label": label, "E": e_value, **result})


@bp.post("/api/netz/<cam_id>/reset")
def api_netz_reset(cam_id):
    """E = 50 and unpin, for one axis or all of them."""
    payload = request.get_json(force=True, silent=True) or {}
    label = payload.get("label")
    labels = [label] if isinstance(label, str) and label else []
    if H.camera(cam_id) is None:
        return jsonify({"ok": False, "error": "Kamera nicht gefunden"}), 404
    reset = H.reset_axes(cam_id, labels)
    _reload_runtimes()
    log.info("[det] Netz zurückgesetzt: cam=%s %s", cam_id, reset)
    return jsonify({"ok": True, "reset": reset, "state": H.net_state(cam_id)})


@bp.post("/api/netz/<cam_id>/auto")
def api_netz_auto(cam_id):
    """The one on/off in the whole panel: „Automatik"."""
    payload = request.get_json(force=True, silent=True) or {}
    cam = H.camera(cam_id)
    if cam is None:
        return jsonify({"ok": False, "error": "Kamera nicht gefunden"}), 404
    app_state.settings.upsert_camera({**cam, "net_auto": bool(payload.get("enabled", True))})
    return jsonify({"ok": True, "state": H.net_state(cam_id)})


# ── Archiv ────────────────────────────────────────────────────────────


@bp.get("/api/netz/archive")
def api_netz_archive():
    page = net_archive.list_records(
        app_state.storage_root,
        cam=request.args.get("cam") or None,
        label=request.args.get("label") or None,
        only_open=request.args.get("open") in ("1", "true", "yes"),
        offset=max(0, int(request.args.get("offset") or 0)),
        limit=min(200, int(request.args.get("limit") or PAGE_SIZE)),
    )
    return jsonify({"ok": True, **page})


@bp.get("/api/netz/archive/<eid>")
def api_netz_archive_one(eid):
    rec = net_archive.get_record(app_state.storage_root, eid)
    if rec is None:
        return jsonify({"ok": False, "error": "Datensatz nicht gefunden"}), 404
    return jsonify({"ok": True, "record": rec})


@bp.get("/api/netz/archive/<eid>/frame.jpg")
def api_netz_archive_frame(eid):
    """The archive's OWN copy of the frame.

    Deliberately not a redirect to the event's snapshot: at 14 days the
    event is gone and this is the only picture left of the moment.
    """
    path = net_archive.frame_path(app_state.storage_root, eid)
    if not path.is_file():
        return jsonify({"ok": False, "error": "Kein Bild zu diesem Datensatz"}), 404
    return send_file(path, mimetype="image/jpeg", conditional=True)


@bp.post("/api/netz/archive/<eid>/restore")
def api_netz_archive_restore(eid):
    """Put the net back to where it stood at this moment.

    Restoring PINS every axis it touches: the operator made a deliberate
    choice about the whole shape, and the learner must not start
    unpicking it one axis at a time overnight.
    """
    rec = net_archive.get_record(app_state.storage_root, eid)
    if rec is None:
        return jsonify({"ok": False, "error": "Datensatz nicht gefunden"}), 404
    cam_id = rec.get("cam_id") or ""
    if H.camera(cam_id) is None:
        return jsonify({"ok": False, "error": "Kamera nicht mehr vorhanden"}), 404
    axes = {
        label: int(info.get("E", 50))
        for label, info in (rec.get("net_state") or {}).items()
        if isinstance(info, dict)
    }
    if not axes:
        return jsonify({"ok": False, "error": "Datensatz trägt keinen Netz-Zustand"}), 400
    written = H.apply_axes(cam_id, axes, pin=True)
    _reload_runtimes()
    log.info("[det] Netz wiederhergestellt aus %s: cam=%s", eid, cam_id)
    return jsonify({"ok": True, "written": written, "state": H.net_state(cam_id)})
