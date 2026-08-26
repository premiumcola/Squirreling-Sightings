"""Event CRUD — single-event delete, bulk delete, confirm, label edit, review.

Migrated from server.py during R01.4. Every write goes through the
`store.update_event` / `store.delete_event` API; the storage layer
handles atomic writes since B08.

FB-1 · the three surfaces here that carry a human judgement also write it
to the durable ledger (`detection_feedback`), joined to the alert record
by ``event_id``. Before this, every correction made in the web UI was
thrown away: `confirmed` has no reader in the Python code, and `labels`
is overwritten by the detector on every event, so an edited and an
auto-labelled event are indistinguishable on disk (see
`storage.JUDGEMENT_FIELDS`).
"""

from __future__ import annotations

import contextlib
import logging
import time
from datetime import datetime

from flask import Blueprint, jsonify, request

from .. import app_state, trash as _trash
from ..detection_feedback import record_verdict

bp = Blueprint("events", __name__)


def _ledger_verdict(cam_id, event_id, *, correct, source, corrected_label=None):
    """Best-effort verdict write. A ledger failure must never turn a
    successful user action into a 500 — the module's own contract is
    that every write is swallowed and logged, and this keeps the same
    promise for the exception the caller could still raise (a missing
    storage root, a bad argument)."""
    with contextlib.suppress(Exception):
        record_verdict(
            app_state.storage_root,
            event_id=event_id,
            correct=correct,
            ts=time.time(),
            corrected_label=corrected_label,
            source=source,
            cam_id=cam_id,
        )


@bp.delete('/api/camera/<cam_id>/events/<event_id>')
def api_event_delete(cam_id, event_id):
    """Soft-delete: move the event into ``storage/.trash/`` instead
    of hard-deleting. The trash entry sits for ``trash.grace_days``
    days before the daily sweep removes it. /api/trash/<id>/restore
    moves it back; /api/trash/empty hard-deletes everything now."""
    storage_root = app_state.storage_root
    # Deleting a single event is the user calling it a false alarm.
    # Recorded before the files move, so the verdict survives even a
    # partial trash move. A verdict for an event that never produced an
    # alert is inert: `judged_alerts` only joins verdicts that have an
    # alert record with the same event_id.
    _ledger_verdict(cam_id, event_id, correct=False, source="web_delete")
    result = _trash.move_to_trash(cam_id, event_id)
    # Timelapse fallback: tl_<stem> events live in storage/timelapse/<cam>/
    # and may not have an EventStore JSON yet (the migration that
    # registers them on boot can race against the user clicking delete
    # before it finishes, and old installs predate the unified
    # registration entirely). Also clean up the on-disk mp4 + sidecar +
    # thumb so the file disappears from the gallery either way.
    tl_cleaned = False
    if event_id.startswith("tl_"):
        stem = event_id[3:]
        if "/" not in stem and "\\" not in stem and ".." not in stem:
            tl_dir = storage_root / "timelapse" / cam_id
            mp4 = tl_dir / f"{stem}.mp4"
            if mp4.exists():
                mp4.unlink(missing_ok=True)
                tl_cleaned = True
                for suffix in (".json", ".jpg"):
                    companion = tl_dir / f"{stem}{suffix}"
                    if companion.exists():
                        with contextlib.suppress(Exception):
                            companion.unlink()
    if not result["json_deleted"] and not tl_cleaned:
        return jsonify({"ok": False, "error": "Event nicht gefunden"}), 404
    return jsonify({"ok": True, "tl_cleaned": tl_cleaned, **result})


@bp.post('/api/camera/<cam_id>/events/delete-bulk')
def api_event_delete_bulk(cam_id):
    """Bulk soft-delete — every successfully-moved event lands in
    the trash. Frontend URL stays the same so no client change is
    needed; the only behavioural difference is restorability."""
    payload = request.get_json(force=True, silent=True) or {}
    raw_ids = payload.get("event_ids")
    if not isinstance(raw_ids, list):
        return jsonify({"ok": False, "error": "event_ids muss eine Liste sein"}), 400
    event_ids = [eid for eid in raw_ids if isinstance(eid, str) and eid]
    if not event_ids:
        return jsonify({"ok": False, "error": "Keine event_ids angegeben"}), 400
    if len(event_ids) > 500:
        return jsonify({"ok": False, "error": "Maximal 500 Events pro Aufruf"}), 400
    deleted = 0
    failed = []
    for eid in event_ids:
        try:
            result = _trash.move_to_trash(cam_id, eid)
            if result.get("json_deleted"):
                deleted += 1
            else:
                failed.append(eid)
        except Exception:
            failed.append(eid)
    logging.getLogger(__name__).info(
        "[bulk-delete→trash] cam=%s trashed=%d failed=%d",
        cam_id,
        deleted,
        len(failed),
    )
    return jsonify({"ok": True, "deleted": deleted, "failed": failed})


@bp.post('/api/camera/<cam_id>/events/<event_id>/confirm')
def api_event_confirm(cam_id, event_id):
    store = app_state.store
    event = store.get_event(cam_id, event_id)
    if not event:
        return jsonify({"ok": False, "error": "Event nicht gefunden"}), 404
    event["confirmed"] = True
    event["confirmed_at"] = datetime.now().isoformat(timespec="seconds")
    store.update_event(cam_id, event_id, event)
    _ledger_verdict(cam_id, event_id, correct=True, source="web")
    return jsonify({"ok": True})


@bp.post('/api/camera/<cam_id>/events/<event_id>/labels')
def api_event_labels(cam_id, event_id):
    store = app_state.store
    payload = request.get_json(force=True, silent=True) or {}
    labels = payload.get("labels", [])
    event = store.get_event(cam_id, event_id)
    if not event:
        return jsonify({"ok": False, "error": "Event nicht gefunden"}), 404
    event["labels"] = labels
    # Keep top_label in sync with labels so timeline/badges/stats agree.
    # If the previous top_label was removed, fall back to first remaining label,
    # or "motion" when the user cleared the list entirely.
    prev_top = event.get("top_label")
    if not labels:
        event["top_label"] = "motion"
    elif prev_top not in labels:
        event["top_label"] = labels[0]
    store.update_event(cam_id, event_id, event)
    # Only a changed top_label is a correction. Adding a secondary label
    # leaves the detector's verdict standing — recording that as "wrong"
    # would poison the corpus with events the user never disputed.
    if event["top_label"] != prev_top:
        _ledger_verdict(
            cam_id,
            event_id,
            correct=False,
            source="web",
            corrected_label=event["top_label"],
        )
    return jsonify({"ok": True, "labels": labels, "top_label": event["top_label"]})


@bp.post('/api/camera/<cam_id>/review/<event_id>')
def api_camera_review(cam_id, event_id):
    payload = request.get_json(force=True, silent=True) or {}
    app_state.settings.set_review(f"{cam_id}:{event_id}", payload)
    return jsonify({"ok": True})
