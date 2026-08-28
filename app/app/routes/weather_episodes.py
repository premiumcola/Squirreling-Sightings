"""Storm-episode archive — list, read, label, tombstone.

A sibling of ``routes/weather.py`` rather than an addition to it: that
module is already past the 500-line ceiling, and the archive is an
orthogonal concern (a permanent store, not the live sighting pipeline).

Every route reads ``app_state.storage_root`` fresh. The archive is a
plain file, so these handlers do not need the WeatherService at all —
except for the ``pending`` hint on the list route, which comes from the
live history and is omitted when the service is down.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from .. import app_state
from ..weather_episodes import (
    USER_CLASSES,
    USER_NAME_MAX,
    USER_NOTE_MAX,
    build_footage_index,
    delete_episode,
    earliest_window_start,
    episode_footage,
    episode_footage_counts,
    get_episode,
    list_episodes,
    patch_episode,
)

bp = Blueprint("weather_episodes", __name__)

log = logging.getLogger(__name__)

# An id is `<onset-iso>_<auto_class>`; nothing longer is legitimate and
# nothing built from one ever reaches the filesystem.
_MAX_ID_LEN = 128


def _pending() -> dict | None:
    ws = app_state.weather_service
    if ws is None:
        return None
    try:
        return ws.episodes_pending()
    except Exception as e:
        log.warning("[weather] pending episode lookup failed: %s", e)
        return None


def _cameras() -> list:
    try:
        return list(app_state.get_effective_config().get("cameras") or [])
    except Exception as e:
        log.warning("[weather] camera list unavailable for footage: %s", e)
        return []


def _footage_index(root, records: list):
    """Scan the media stores once for a set of episode records."""
    return build_footage_index(
        root,
        weather_service=app_state.weather_service,
        store=app_state.store,
        cameras=_cameras(),
        since=earliest_window_start(records),
    )


def _clean_text(raw, limit: int, field: str):
    """Return ``(value, error)``. ``None`` clears the field."""
    if raw is None:
        return None, None
    if not isinstance(raw, str):
        return None, "{} must be a string or null".format(field)
    value = raw.strip()
    if not value:
        return None, None
    if len(value) > limit:
        return None, "{} exceeds {} characters".format(field, limit)
    return value, None


def _collect_patch(body: dict):
    """Validate the PATCH body. Returns ``(fields, error)``."""
    fields: dict = {}
    if "user_class" in body:
        raw = body.get("user_class")
        if raw is not None and raw not in USER_CLASSES:
            return None, "user_class must be null or one of {}".format(", ".join(USER_CLASSES))
        fields["user_class"] = raw
    for key, limit in (("user_name", USER_NAME_MAX), ("user_note", USER_NOTE_MAX)):
        if key not in body:
            continue
        value, err = _clean_text(body.get(key), limit, key)
        if err:
            return None, err
        fields[key] = value
    if not fields:
        return None, "no editable field in body (user_class, user_name, user_note)"
    return fields, None


@bp.get('/api/weather/episodes')
def api_weather_episodes_list():
    """Archived storms, newest first, WITHOUT their sample arrays.

    The curve slice is the bulk of a record — shipping it for every
    episode would make the list view megabytes. Fetch one episode by id
    to get its samples.

    Each row carries a ``footage_count`` so the list can show which
    storms were filmed without a request per row; the media stores are
    scanned exactly once for the whole list.
    """
    root = app_state.storage_root
    if root is None:
        return jsonify({"items": [], "count": 0, "pending": None})

    def _counts(records: list) -> dict:
        candidates, _degraded = _footage_index(root, records)
        return episode_footage_counts(candidates, records)

    items = list_episodes(root, footage_counts=_counts)
    return jsonify({"items": items, "count": len(items), "pending": _pending()})


@bp.get('/api/weather/episodes/<episode_id>')
def api_weather_episode_get(episode_id: str):
    """One episode including the full curve slice around it."""
    root = app_state.storage_root
    if root is None or len(episode_id) > _MAX_ID_LEN:
        return jsonify({"error": "not found"}), 404
    rec = get_episode(root, episode_id)
    if not rec:
        return jsonify({"error": "not found"}), 404
    return jsonify(rec)


@bp.get('/api/weather/episodes/<episode_id>/footage')
def api_weather_episode_footage(episode_id: str):
    """Recordings overlapping this episode's window, grouped by purpose.

    200 with empty groups means "we looked and there is nothing" — the
    calm empty state. 404 means the episode itself is unknown. A store
    that could not be read is reported in ``degraded`` rather than
    turning the whole page into an error, because the archive is a
    passive record and one dead source must not hide the other three.
    """
    root = app_state.storage_root
    if root is None or len(episode_id) > _MAX_ID_LEN:
        return jsonify({"error": "not found"}), 404
    rec = get_episode(root, episode_id)
    if not rec:
        return jsonify({"error": "not found"}), 404
    candidates, degraded = _footage_index(root, [rec])
    return jsonify(episode_footage(candidates, degraded, rec))


@bp.patch('/api/weather/episodes/<episode_id>')
def api_weather_episode_patch(episode_id: str):
    """Set user_class / user_name / user_note.

    Appends a patch record — the detector's own verdict is never
    overwritten, so a mislabel is one more append away from being
    undone.
    """
    root = app_state.storage_root
    if root is None or len(episode_id) > _MAX_ID_LEN:
        return jsonify({"error": "not found"}), 404
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "JSON object body required"}), 400
    fields, err = _collect_patch(body)
    if err:
        return jsonify({"error": err}), 400
    rec = patch_episode(root, episode_id, fields)
    if rec is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True, "episode": rec})


@bp.delete('/api/weather/episodes/<episode_id>')
def api_weather_episode_delete(episode_id: str):
    """Tombstone an episode. The base record stays on disk.

    Deleted ids are also remembered by the detection sweep, so an
    episode the user removed is not re-created on the next poll while
    its source history is still inside the rolling window.
    """
    root = app_state.storage_root
    if root is None or len(episode_id) > _MAX_ID_LEN:
        return jsonify({"error": "not found"}), 404
    if delete_episode(root, episode_id):
        return jsonify({"ok": True})
    return jsonify({"error": "not found"}), 404
