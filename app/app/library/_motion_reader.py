"""Date-bounded, label-filterable reader for the motion event tree.

Moved here from ``weather_episodes._motion_scan`` during the Mediathek
+ Wetter-Ereignisse merge (Stage 3): a second caller — the unified
library feed (``library._feed.list_library_items``) — needed the exact
same pruning, and CLAUDE.md forbids a second copy. That module now only
re-exports ``motion_events_between`` for its existing callers; new code
imports from here directly.

``EventStore.list_events`` answers "everything for this camera, then
filter": it ``rglob``s the whole camera folder and ``json.loads`` EVERY
event file before ``start``/``end`` are applied. That is the right
shape for the media browser, which really does want the newest N of
everything, and the wrong shape for a bounded window somewhere in a
multi-year tree — an episode window is a couple of hours; a library
feed page is usually a day or two.

The layout does the pruning for us. Events live at
``motion_detection/<cam>/<YYYY-MM-DD>/<event_id>.json`` (see
``storage.event_date_subdir``), so the date bound is a DIRECTORY-NAME
comparison and no file belonging to a day outside the window is ever
opened.

Label / object-class filtering mirrors ``EventStore._filter_events``
(``storage.py``) bit-for-bit: a ``labels`` list ORs, a single ``label``
is sugar for a one-element list, and the match set also covers
``cat_name`` / ``bird_species`` because ``_filter_events`` does — a
bird-cam event's species is not always duplicated into ``labels``. This
reader still deliberately does not implement ``_filter_events``'s
``type`` / ``bird_species``-exact / ``media_only`` knobs — nothing that
calls it today needs them, and adding filters nobody asked for is how a
"shared reader" grows back into two divergent copies.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from ..weather_service._consts import _safe_dt

log = logging.getLogger(__name__)

# A date folder is exactly `YYYY-MM-DD`. Anything else under the camera
# root is either a legacy event JSON (read directly, see below) or not
# ours; neither is walked recursively.
_DATE_LEN = 10

# A motion clip is short; an event whose JSON carries no duration at
# all is still given this much forward span so it can overlap a window
# that starts a few seconds after it, rather than collapsing to a
# zero-length instant no window can ever match.
_DEFAULT_MOTION_SPAN_S = 60.0


def _is_date_dir(name: str) -> bool:
    return len(name) == _DATE_LEN and name[4] == "-" and name[7] == "-" and name[:4].isdigit()


def _in_range(value: str, lo: str, hi: str) -> bool:
    """ISO strings sort lexically, so the bound is a string compare."""
    if lo and value < lo:
        return False
    return not (hi and value > hi)


def _candidate_files(cam_dir: Path, lo: str, hi: str):
    """Event JSONs that can fall in ``[lo, hi]``, without a tree walk."""
    try:
        children = sorted(cam_dir.iterdir())
    except OSError as e:
        log.warning("[storage] motion scan cannot list %s: %s", cam_dir, e)
        return
    for child in children:
        if child.is_dir():
            # Compare on the DAY, not the full timestamp: a folder is in
            # range as soon as it shares the boundary day.
            if _is_date_dir(child.name) and _in_range(child.name, lo[:10], hi[:10]):
                yield from sorted(child.glob("*.json"))
        elif child.suffix == ".json":
            # Pre-date-folder leftovers sit in the camera root. There are
            # a handful at most and no cheap way to date them, so they
            # are always read and filtered on their `time` field.
            yield child


def _label_filter_set(label: str | None, labels: list | None) -> set | None:
    if labels:
        return set(labels)
    if label:
        return {label}
    return None


def _matches_label(obj: dict, filter_set: set | None) -> bool:
    if not filter_set:
        return True
    # Same match set `EventStore._filter_events` uses: an event's own
    # `labels` list, plus the two single-value fields a species/identity
    # classifier stamps instead of (or in addition to) `labels`.
    evt_labels = set(obj.get("labels", []))
    extras = {obj.get("cat_name"), obj.get("bird_species")} - {None}
    return bool(filter_set & (evt_labels | extras))


def motion_events_between(
    store,
    cam_id: str,
    start_iso: str,
    end_iso: str,
    *,
    label: str | None = None,
    labels: list | None = None,
) -> list:
    """Media-carrying motion events whose ``time`` falls in the window.

    Returns ``[]`` — never raises — when the store has no event tree.
    ``labels`` takes precedence over ``label`` when both are given,
    matching ``_filter_events``'s own precedence.
    """
    events_dir = getattr(store, "events_dir", None)
    if events_dir is None:
        return []
    cam_dir = Path(events_dir) / cam_id
    if not cam_dir.is_dir():
        return []
    lo = start_iso or ""
    hi = end_iso or ""
    filter_set = _label_filter_set(label, labels)
    out: list = []
    for path in _candidate_files(cam_dir, lo, hi):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.warning("[storage] malformed event JSON %s: %s", path, e)
            continue
        if not isinstance(obj, dict):
            continue
        if not (obj.get("snapshot_relpath") or obj.get("video_relpath")):
            continue
        if not _in_range(str(obj.get("time") or ""), lo, hi):
            continue
        if not _matches_label(obj, filter_set):
            continue
        out.append(obj)
    return out


def _num(value, fallback: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return fallback
    return out if out == out else fallback  # NaN guard


def motion_event_span(obj: dict, start: datetime) -> datetime:
    """End timestamp for one motion event, given its parsed start."""
    length = _num(obj.get("video_duration_s"), 0.0) or _num(obj.get("duration_s"), 0.0)
    return start + timedelta(seconds=max(_DEFAULT_MOTION_SPAN_S, length))


def motion_candidate(cam_id: str, cam_name: str, obj: dict) -> dict | None:
    """One motion event as a normalised feed candidate, or ``None`` when
    its ``time`` field doesn't parse. Shape matches every other reader
    in this package and in ``weather_episodes._footage_sources``: kind,
    cam_id, cam_name, start, end, video_url, thumb_url, missing_media,
    extra. The whole event payload rides along in ``extra`` because
    clients hand motion tiles to the existing lightbox, which speaks
    exactly the shape ``/api/camera/<id>/media`` returns.
    """
    start = _safe_dt(str(obj.get("time") or ""))
    if start is None:
        return None
    rel = obj.get("video_relpath") or obj.get("snapshot_relpath") or ""
    return {
        "kind": "motion",
        "cam_id": cam_id,
        "cam_name": cam_name,
        "start": start,
        "end": motion_event_span(obj, start),
        "video_url": "/media/{}".format(rel) if rel else "",
        "thumb_url": (
            "/media/{}".format(obj.get("snapshot_relpath")) if obj.get("snapshot_relpath") else ""
        ),
        "missing_media": not obj.get("video_relpath"),
        "extra": dict(obj),
    }


def motion_candidates(
    store,
    cam_ids: list,
    cam_names: dict,
    since: datetime | None = None,
    until: datetime | None = None,
    *,
    label: str | None = None,
    labels: list | None = None,
) -> list:
    """Motion events with media, per camera, inside ``[since, until]``,
    already shaped as feed candidates.

    Applies no padding of its own — a caller whose window semantics
    need one (e.g. ``weather_episodes._footage_sources.motion_candidates``,
    where a clip a few minutes before its stated window can still reach
    into it) adds it before calling this, exactly as that caller always
    has. ``library._feed`` widens its OWN outer window instead, which is
    an unrelated mechanism (see that module).
    """
    lo = since.isoformat(timespec="seconds") if since is not None else ""
    hi = until.isoformat(timespec="seconds") if until is not None else ""
    out: list = []
    for cam_id in cam_ids:
        try:
            events = motion_events_between(store, cam_id, lo, hi, label=label, labels=labels)
        except Exception as e:
            log.warning("[storage] motion candidates failed for %s: %s", cam_id, e)
            continue
        for obj in events:
            cand = motion_candidate(cam_id, cam_names.get(cam_id) or cam_id, obj)
            if cand is not None:
                out.append(cand)
    return out
