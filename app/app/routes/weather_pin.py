"""Pin / unpin a weather sighting — sweep-exemption toggle.

Own module for the same reason as ``routes/weather_episodes.py``:
``routes/weather.py`` is already past the 500-line file ceiling, and
this is a small, orthogonal concern (one manifest field) rather than
part of the live sighting pipeline.

The flag itself is read by ``weather_service/_retention.py``'s nightly
sweep — a pinned sighting is skipped regardless of age.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from .. import app_state

bp = Blueprint("weather_pin", __name__)

log = logging.getLogger(__name__)


@bp.post('/api/weather/sightings/<sighting_id>/pin')
def api_weather_sighting_pin(sighting_id: str):
    """Set the pin flag. Body ``{"pinned": true|false}`` sets it
    explicitly — the pin-toggle UI always sends this so a slow double
    click can't race itself into the wrong state. An empty body (or one
    without a "pinned" key) toggles relative to the manifest's current
    value instead, which is what a plain curl/test call gets for free.
    """
    ws = app_state.weather_service
    if ws is None:
        return jsonify({"error": "weather service not available"}), 503
    payload = request.get_json(silent=True) or {}
    if "pinned" in payload:
        pinned = bool(payload["pinned"])
    else:
        current = ws.get_sighting(sighting_id)
        if not current:
            return jsonify({"error": "not found"}), 404
        pinned = not bool(current.get("pinned"))
    if not ws.set_sighting_pinned(sighting_id, pinned):
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True, "pinned": pinned})
