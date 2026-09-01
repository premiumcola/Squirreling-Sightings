"""Manual weather events — user-saved chart ranges.

A sibling of ``routes/weather.py`` rather than an addition to it: that
module is already past the file ceiling (see ``routes/weather_episodes.py``
for the same reasoning, which set this precedent). A manual event is a
named time window, assigned to one of the app's existing weather-event
categories, plus the curve keys and free-text "characteristic" the
operator entered to justify that categorisation — no clip, nothing else
in the live sighting pipeline needs it, so it earns its own small module.
"""

from __future__ import annotations

import logging
from datetime import datetime

from flask import Blueprint, jsonify, request

from .. import app_state
from ..weather_service._consts import HISTORY_FIELDS
from ..weather_service._manual_events import (
    MANUAL_EVENT_CATEGORIES,
    MANUAL_EVENT_CATEGORIES_MAX,
    MANUAL_EVENT_CHARACTERISTIC_MAX,
    MANUAL_EVENT_NAME_MAX,
    MANUAL_EVENT_PHASES,
)

bp = Blueprint("weather_manual_events", __name__)

log = logging.getLogger(__name__)

#: An id is `manual_<yyyymmddThhmmss>_<6-hex>`; nothing longer is
#: legitimate and nothing built from one ever reaches the filesystem.
_MAX_ID_LEN = 64


def _parse_iso(raw) -> str | None:
    """Return the ISO string unchanged if it parses, else None."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        datetime.fromisoformat(raw)
    except ValueError:
        return None
    return raw


def _validate_categories(body: dict):
    """Return ``(categories, error)`` for either request shape.

    The save form sends a ``categories`` list (an event is genuinely more
    than one thing — a thunderstorm that also brings heavy rain); a
    caller that still sends the original single ``category`` string is
    accepted unchanged and read as a one-element list. ``categories``
    wins when a body carries both.
    """
    raw = body.get("categories")
    if raw is None:
        single = body.get("category")
        if single is None:
            return None, f"category must be one of {list(MANUAL_EVENT_CATEGORIES)}"
        raw = [single]
    if not isinstance(raw, list) or not raw:
        return None, "categories must be a non-empty list"
    if len(raw) > MANUAL_EVENT_CATEGORIES_MAX:
        return None, f"categories must not exceed {MANUAL_EVENT_CATEGORIES_MAX} entries"
    clean: list[str] = []
    for c in raw:
        if not isinstance(c, str) or c not in MANUAL_EVENT_CATEGORIES:
            return None, f"category must be one of {list(MANUAL_EVENT_CATEGORIES)}"
        if c not in clean:
            clean.append(c)
    return clean, None


def _validate_annotations(body: dict, range_start: str, range_end: str):
    """Return ``(annotations, error)`` for the chart markers a saved
    manual event may carry — one entry per (curve, timestamp, phase) the
    operator placed while drawing on the zoomed chart (see
    weather/_chart-annotations.js). Optional; defaults to an empty list.

    Any invalid entry fails the WHOLE body, same pattern
    ``_validate_categories``/``_validate_body`` already use for
    curves/categories — this is data the operator is deliberately
    curating for later use, so a malformed entry must surface as an
    error, never silently vanish.
    """
    raw = body.get("annotations")
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, "annotations must be a list"
    lo = datetime.fromisoformat(range_start)
    hi = datetime.fromisoformat(range_end)
    clean: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            return None, "each annotation must be an object"
        curve = entry.get("curve")
        if not isinstance(curve, str) or curve not in HISTORY_FIELDS:
            return None, f"annotation curve must be one of {list(HISTORY_FIELDS)}"
        ts = _parse_iso(entry.get("ts"))
        if not ts:
            return None, "annotation ts must be an ISO timestamp"
        if not (lo <= datetime.fromisoformat(ts) <= hi):
            return None, "annotation ts must fall within the saved range"
        phase = entry.get("phase")
        if phase not in MANUAL_EVENT_PHASES:
            return None, f"annotation phase must be one of {list(MANUAL_EVENT_PHASES)}"
        clean.append({"curve": curve, "ts": ts, "phase": phase})
    return clean, None


def _validate_body(body: dict):
    """Return ``(fields, error)``. ``fields`` carries name/categories/
    characteristic/range_start/range_end/curves/annotations once every
    check passes."""
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        return None, "name is required"
    name = name.strip()
    if len(name) > MANUAL_EVENT_NAME_MAX:
        return None, f"name exceeds {MANUAL_EVENT_NAME_MAX} characters"
    categories, err = _validate_categories(body)
    if err:
        return None, err
    characteristic = body.get("characteristic")
    if characteristic is None:
        characteristic = ""
    elif not isinstance(characteristic, str):
        return None, "characteristic must be a string"
    characteristic = characteristic.strip()
    if len(characteristic) > MANUAL_EVENT_CHARACTERISTIC_MAX:
        return None, f"characteristic exceeds {MANUAL_EVENT_CHARACTERISTIC_MAX} characters"
    range_start = _parse_iso(body.get("range_start"))
    range_end = _parse_iso(body.get("range_end"))
    if not range_start or not range_end:
        return None, "range_start and range_end must be ISO timestamps"
    if datetime.fromisoformat(range_end) <= datetime.fromisoformat(range_start):
        return None, "range_end must be after range_start"
    curves = body.get("curves")
    if not isinstance(curves, list) or not curves:
        return None, "curves must be a non-empty list"
    clean_curves = []
    for c in curves:
        if not isinstance(c, str) or c not in HISTORY_FIELDS:
            return None, f"curves must be a subset of {list(HISTORY_FIELDS)}"
        if c not in clean_curves:
            clean_curves.append(c)
    annotations, err = _validate_annotations(body, range_start, range_end)
    if err:
        return None, err
    return {
        "name": name,
        "categories": categories,
        "characteristic": characteristic,
        "range_start": range_start,
        "range_end": range_end,
        "curves": clean_curves,
        "annotations": annotations,
    }, None


@bp.get('/api/weather/manual-events')
def api_manual_events_list():
    ws = app_state.weather_service
    if ws is None:
        return jsonify({"items": []})
    return jsonify({"items": ws.list_manual_events()})


@bp.post('/api/weather/manual-events')
def api_manual_events_create():
    ws = app_state.weather_service
    if ws is None:
        return jsonify({"error": "weather service not available"}), 503
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "JSON object body required"}), 400
    fields, err = _validate_body(body)
    if err:
        return jsonify({"error": err}), 400
    manifest = ws.create_manual_event(**fields)
    return jsonify({"ok": True, "item": manifest}), 201


@bp.delete('/api/weather/manual-events/<event_id>')
def api_manual_events_delete(event_id: str):
    ws = app_state.weather_service
    if ws is None or len(event_id) > _MAX_ID_LEN:
        return jsonify({"error": "not found"}), 404
    if ws.delete_manual_event(event_id):
        return jsonify({"ok": True})
    return jsonify({"error": "not found"}), 404
