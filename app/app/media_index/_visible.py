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
from ..labels import COUNTED_LABELS, OBJECT_LABELS, primary_label
from ._types import has_real_media, is_timelapse_event

#: ``list_events`` takes a slice; every caller here needs the whole set
#: before it can filter or count. A camera tree larger than this has
#: bigger problems than the constant.
ALL_EVENTS = 1_000_000


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
    return filter_visible(raw, size_of, clip_max_s=clip_max_s, now=now)


def filter_visible(events, size_of, *, clip_max_s: int = DEFAULT_CLIP_MAX_S, now: datetime = None):
    """The visibility rule applied to manifests already in memory.

    The integrity report parses every manifest anyway; routing it back
    through ``store.list_events`` made it read and parse the same JSON a
    second time — and, before ``camera_dir``, made a read-only report
    create the very directories it then reported. It shares this
    function instead, so there is still exactly one definition of
    "visible".

    ``events`` is assumed newest-first (``list_events`` sorts); callers
    passing an unsorted dict sort it themselves.
    """
    now = now or datetime.now()
    visible = []
    for obj in events:
        pending = is_pending(obj)
        if not (pending or has_real_media(obj, size_of)):
            continue
        if pending:
            annotate_stage(obj, now, clip_max_s)
        visible.append(obj)
    return visible


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
        # Exactly one bucket per event, and never None: a `["fox"]`
        # event used to match no object label and no "motion" either, so
        # it fell out of label_counts entirely and rendered a tile with
        # no badge above it. `primary_label` ends in a motion fallback
        # for precisely that case.
        primary = primary_label(event.get("labels"))
        if primary in COUNTED_LABELS:
            label_counts[primary] = label_counts.get(primary, 0) + 1
    # Raw timelapse frames are walked (they are in MEDIA_TREES) but were
    # not in COUNTED_TREES, so a yearly profile's ~4 GB of jpgs per camera
    # sat on the disk and appeared nowhere in the storage overview. Report
    # them inside the total AND on their own line: they are the largest
    # single thing the operator can switch off, so a lump sum would hide
    # exactly the number worth acting on.
    frames_bytes = index.tree_bytes.get("timelapse_frames", 0)
    return {
        "id": camera_id,
        "camera_id": camera_id,
        "name": resolved_name,
        "size_mb": round((index.counted_bytes + frames_bytes) / 1024 / 1024, 1),
        "timelapse_frames_mb": round(frames_bytes / 1024 / 1024, 1),
        "jpg_count": index.media_file_count,
        "event_count": event_count,
        "timelapse_count": timelapse_count,
        "latest_snap_url": latest_snap_url,
        "latest_object_snap_url": latest_object_snap_url,
        "label_counts": label_counts,
    }
