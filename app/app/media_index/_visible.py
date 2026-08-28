"""The set of events the Mediathek shows — computed once, used twice.

The bug this replaces: the Timelapse badge counted ``*.mp4`` files under
``storage/timelapse/<cam>/`` while the grid counted ``tl_*`` manifests
under ``storage/motion_detection/<cam>/``. Two directories, two
producers, nothing reconciling them — so "Timelapse 3" sat above a grid
with one tile. The motion badge had the mirror defect: it derived
``Bewegung`` as ``event_count - objects``, and ``event_count`` included
the timelapse manifests, inventing a motion event that never existed.

Both the badge route and the grid route now call
:func:`visible_media_events` and count the same list. They cannot
disagree, because there is no second list to disagree with. Anything on
disk that is not in that list is drift, and drift is reported by the
integrity check rather than silently counted.
"""

from __future__ import annotations

from datetime import datetime

from ..camera_runtime._recording._stages import (
    DEFAULT_CLIP_MAX_S,
    annotate_stage,
    is_pending,
)
from ._types import has_real_media, is_timelapse_event

#: ``list_events`` takes a slice; every caller here needs the whole set
#: before it can filter or count. A camera tree larger than this has
#: bigger problems than the constant.
ALL_EVENTS = 1_000_000

OBJECT_LABELS = ("person", "cat", "bird", "car", "dog", "squirrel")
TRACKED_LABELS = frozenset(OBJECT_LABELS) | {"motion"}


def visible_media_events(
    store,
    size_of,
    camera_id: str,
    *,
    label=None,
    labels=None,
    start=None,
    end=None,
    clip_max_s: int = DEFAULT_CLIP_MAX_S,
    now: datetime = None,
):
    """Every event ``camera_id`` should show, newest first.

    An event is visible when it points at media that is really on disk
    and non-empty (:func:`~._types.media_state`), or when it is a clip
    still being produced — the recording stub carries null media fields
    for the whole minute the re-encode runs, which is exactly the window
    the operator wants to watch.

    The store scan runs unfiltered and the media test is applied here so
    a single pass over the camera tree answers both "which items" and
    "how many".
    """
    now = now or datetime.now()
    raw = store.list_events(
        camera_id,
        label=label,
        labels=labels,
        start=start,
        end=end,
        limit=ALL_EVENTS,
        offset=0,
        media_only=False,
    )
    visible = []
    for obj in raw:
        pending = is_pending(obj)
        if not (pending or has_real_media(obj, size_of)):
            continue
        if pending:
            annotate_stage(obj, now, clip_max_s)
        visible.append(obj)
    return visible


def _primary_label(event: dict):
    """The one bucket an event is counted under, so the filter pills sum
    to the archive size instead of the inflated multi-label total."""
    labels = event.get("labels") or []
    for lab in labels:
        if lab in OBJECT_LABELS:
            return lab
    if "motion" in labels or not labels:
        return "motion"
    return None


def camera_stats(index, visible, name_hint: str = "") -> dict:
    """The Mediathek camera card, derived entirely from ``visible``.

    ``event_count`` counts motion events only and ``timelapse_count``
    counts timelapse events only — both from the same list the grid
    renders. ``label_counts['motion']`` is authoritative; the frontend no
    longer subtracts object counts from a total that never matched.
    """
    camera_id = index.camera_id
    resolved_name = name_hint or camera_id
    label_counts: dict = {}
    event_count = 0
    timelapse_count = 0
    latest_snap_url = None
    latest_object_snap_url = None
    for event in visible:
        if resolved_name == camera_id:
            resolved_name = event.get("camera_name") or camera_id
        if is_timelapse_event(event):
            timelapse_count += 1
            continue
        event_count += 1
        rel = event.get("snapshot_relpath")
        if rel and index.size_of(rel):
            if not latest_snap_url:
                latest_snap_url = f"/media/{rel}"
            if not latest_object_snap_url and any(
                lab in OBJECT_LABELS for lab in (event.get("labels") or [])
            ):
                latest_object_snap_url = f"/media/{rel}"
        primary = _primary_label(event)
        if primary in TRACKED_LABELS:
            label_counts[primary] = label_counts.get(primary, 0) + 1
    return {
        "id": camera_id,
        "camera_id": camera_id,
        "name": resolved_name,
        "size_mb": round(index.counted_bytes / 1024 / 1024, 1),
        "jpg_count": index.media_file_count,
        "event_count": event_count,
        "timelapse_count": timelapse_count,
        "latest_snap_url": latest_snap_url,
        "latest_object_snap_url": latest_object_snap_url,
        "label_counts": label_counts,
    }
