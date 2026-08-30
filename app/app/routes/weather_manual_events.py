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
    MANUAL_EVENT_CHARACTERISTIC_MAX,
    MANUAL_EVENT_NAME_MAX,
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


def _validate_body(body: dict):
    """Return ``(fields, error)``. ``fields`` carries name/category/
    characteristic/range_start/range_end/curves once every check passes."""
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        return None, "name is required"
    name = name.strip()
    if len(name) > MANUAL_EVENT_NAME_MAX:
        return None, f"name exceeds {MANUAL_EVENT_NAME_MAX} characters"
    category = body.get("category")
    if not isinstance(category, str) or category not in MANUAL_EVENT_CATEGORIES:
        return None, f"category must be one of {list(MANUAL_EVENT_CATEGORIES)}"
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
    return {
        "name": name,
        "category": category,
        "characteristic": characteristic,
        "range_start": range_start,
        "range_end": range_end,
        "curves": clean_curves,
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
