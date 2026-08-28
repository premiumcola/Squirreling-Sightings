"""Date-bounded reader for the motion event tree.

``EventStore.list_events`` answers "everything for this camera, then
filter": it ``rglob``s the whole camera folder and ``json.loads`` EVERY
event file before the ``start`` argument is applied. That is the right
shape for the media browser, which really does want the newest N of
everything, and the wrong shape here — an episode window is a couple of
hours somewhere in a multi-year tree.

The layout does the pruning for us. Events live at
``motion_detection/<cam>/<YYYY-MM-DD>/<event_id>.json`` (see
``storage.event_date_subdir``), so the date bound is a DIRECTORY-NAME
comparison and no file belonging to a day outside the window is ever
opened.

This lives here rather than on ``EventStore`` because ``storage.py`` is
already 200 lines past the module ceiling; the reader is bounded to
exactly what the footage index needs (media-carrying events in a time
window) and deliberately does not re-implement the label / type /
species filters ``_filter_events`` owns.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# A date folder is exactly `YYYY-MM-DD`. Anything else under the camera
# root is either a legacy event JSON (read directly, see below) or not
# ours; neither is walked recursively.
_DATE_LEN = 10


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


def motion_events_between(store, cam_id: str, start_iso: str, end_iso: str) -> list:
    """Media-carrying motion events whose ``time`` falls in the window.

    Returns ``[]`` — never raises — when the store has no event tree.
    """
    events_dir = getattr(store, "events_dir", None)
    if events_dir is None:
        return []
    cam_dir = Path(events_dir) / cam_id
    if not cam_dir.is_dir():
        return []
    lo = start_iso or ""
    hi = end_iso or ""
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
        out.append(obj)
    return out
