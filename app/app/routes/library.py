"""GET /api/library — the unified Mediathek + Wetter-Ereignisse feed.

Stage 3 of the section merge: this route is purely additive. Every
existing separate list endpoint (``/api/camera/<cam>/media``,
``/api/weather/sightings``, ``/api/weather/recaps``,
``/api/weather/manual-events``, ``/api/weather/episodes``) stays
exactly as it is — the unified card renderer and the actual frontend
section merge are later stages, not this one.

Response shape::

    {
      "items": [
        {
          "kind": "motion" | "sighting" | "recap" | "manual" |
                  "episode" | "timelapse",
          "id": "<opaque, stable per item>",
          "cam_id": "", "cam_name": "",
          "start": "2026-08-31T12:00:00",
          "end": "2026-08-31T12:01:00" | null,
          "video_url": "", "thumb_url": "",
          "missing_media": false,
          "extra": {...source-specific fields, see library._weather_readers
                     and library._motion_reader for exactly what each
                     kind carries...}
        }, ...
      ],
      "next_cursor": "<opaque>" | null,
      "degraded": ["weather_service_unavailable", ...]
    }

Paginate by passing the previous response's ``next_cursor`` back as
``?before=``; ``next_cursor: null`` means the last page was reached (or
the widen loop gave up — see ``library._feed``'s module docstring).

``since``/``until`` (Stage 7 — the Wetterdaten-chart drag-zoom) clip the
page to an explicit window instead of however far the widen loop
happens to reach on its own; naive local-wall-clock ISO timestamps
(``2026-08-31T12:00:00``), same format every other timestamp in this
app uses, parsed leniently via ``_safe_dt`` — an unparsable value is
dropped rather than 400ing, same tolerance ``kinds``/cursor already
get. Both bounds are inclusive: an item touching the edge is in.

``GET /api/library/facets`` (the relevance-pruned, live-counted filter
bar) takes the same filter params minus ``before``/``limit`` — see
``library._facets.count_library_facets`` for the exact response shape
and the faceted-counting rule each dimension follows.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from .. import app_state
from ..library import KINDS, count_library_facets, list_library_items
from ..weather_service._consts import _safe_dt

bp = Blueprint("library", __name__)

#: Mirrors `MAX_SIGHTINGS_PAGE_SIZE`'s reasoning (routes/weather.py) — a
#: library spanning years must never turn "give me a page" into
#: "give me everything".
MAX_LIMIT = 200
DEFAULT_LIMIT = 30


def _csv_arg(name: str) -> list[str] | None:
    raw = request.args.get(name)
    if not raw:
        return None
    values = [v.strip() for v in raw.split(',') if v.strip()]
    return values or None


@bp.get('/api/library')
def api_library_list():
    kinds = _csv_arg('kinds')
    if kinds is not None:
        # Unknown kind names are dropped rather than 400ing — the same
        # tolerance the label/labels filters elsewhere in this codebase
        # give a typo'd query string.
        kinds = [k for k in kinds if k in KINDS] or None
    limit = request.args.get('limit', type=int) or DEFAULT_LIMIT
    limit = min(max(limit, 1), MAX_LIMIT)

    cameras = app_state.get_effective_config().get("cameras", [])
    result = list_library_items(
        store=app_state.store,
        weather_service=app_state.weather_service,
        storage_root=app_state.storage_root,
        cameras=cameras,
        kinds=kinds,
        camera_ids=_csv_arg('camera_ids'),
        label=request.args.get('label') or None,
        labels=_csv_arg('labels'),
        categories=_csv_arg('categories'),
        since=_safe_dt(request.args.get('since') or ''),
        until=_safe_dt(request.args.get('until') or ''),
        before=request.args.get('before') or None,
        limit=limit,
    )
    return jsonify(result)


def _effective_labels() -> list[str] | None:
    """``labels`` wins over the singular ``label`` when both are given —
    same precedence ``_motion_reader._label_filter_set`` already
    applies, mirrored here so the facets endpoint reads the identical
    query params ``/api/library`` itself does."""
    labels = _csv_arg('labels')
    if labels:
        return labels
    label = request.args.get('label') or None
    return [label] if label else None


@bp.get('/api/library/facets')
def api_library_facets():
    kinds = _csv_arg('kinds')
    if kinds is not None:
        kinds = [k for k in kinds if k in KINDS] or None

    cameras = app_state.get_effective_config().get("cameras", [])
    result = count_library_facets(
        store=app_state.store,
        weather_service=app_state.weather_service,
        storage_root=app_state.storage_root,
        cameras=cameras,
        kinds=kinds,
        camera_ids=_csv_arg('camera_ids'),
        labels=_effective_labels(),
        categories=_csv_arg('categories'),
        since=_safe_dt(request.args.get('since') or ''),
        until=_safe_dt(request.args.get('until') or ''),
    )
    return jsonify(result)
