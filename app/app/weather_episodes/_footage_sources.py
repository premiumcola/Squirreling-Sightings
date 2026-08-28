"""Read the three media stores into one normalised candidate list.

Each reader returns plain dicts carrying a real ``start`` / ``end``
datetime plus everything the client tile needs. Nothing here filters by
episode — that is ``_footage.episode_footage``'s job, and keeping the
scan separate is what lets one pass serve the whole list view.

Timestamp conventions, because they differ per store and getting them
wrong silently misplaces every tile:

* a *clip* manifest (``thunder`` / ``heavy_rain`` / ``snow`` / ``fog``)
  stamps ``started_at`` at the start of the recording and carries the
  real ``duration_s``;
* a *timelapse* manifest (event- and sun-timelapse) stamps
  ``started_at`` when the ENCODE finished — the end of the covered
  window — and carries ``window_min`` (plus ``prebuffer_min`` for the
  event timelapse's pre-roll). Its span therefore runs backwards from
  ``started_at``;
* a daily timelapse MP4 covers ``period_s`` ending at its build time;
* a motion event is a moment plus its clip length.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from ..weather_service._consts import _safe_dt
from ._motion_scan import motion_events_between

log = logging.getLogger(__name__)

_DEFAULT_MOTION_SPAN_S = 60.0
_DEFAULT_TIMELAPSE_PERIOD_S = 86400.0

# `list_sightings` paginates; the window bounds already do the pruning,
# so one page has to be able to hold what is left.
_PAGE_ALL = 100000

# A recording is stamped at ONE end of the span it covers, so a window
# query has to reach past the window to find everything that overlaps
# it. Two different pads, because the two stores lie in opposite
# directions:
#
#   motion — `time` is the START, the clip runs forwards. An event a few
#     minutes before the window can still reach into it.
#   sightings — a timelapse manifest stamps `started_at` when the ENCODE
#     finished, i.e. at the END of a window that can be a full day
#     (`window_min`), so the pad has to cover the widest such window.
_MOTION_PAD_MIN = 15
_SIGHTING_PAD_H = 36


def _iso(dt) -> str:
    return dt.isoformat(timespec="seconds") if dt is not None else ""


def _num(value, fallback: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return fallback
    return out if out == out else fallback  # NaN guard


def _manifest_span(m: dict) -> tuple:
    """``(start, end)`` for one weather-sighting manifest."""
    stamped = _safe_dt(m.get("started_at") or "")
    if stamped is None:
        return None, None
    ended = _safe_dt(m.get("ended_at") or "") if m.get("ended_at") else None
    if ended is not None and ended > stamped:
        return stamped, ended
    window_min = _num(m.get("window_min"), 0.0)
    if window_min > 0:
        covered = window_min + _num(m.get("prebuffer_min"), 0.0)
        return stamped - timedelta(minutes=covered), stamped
    return stamped, stamped + timedelta(seconds=max(0.0, _num(m.get("duration_s"), 0.0)))


def weather_candidates(weather_service, since=None, until=None) -> list:
    """Weather sightings overlapping ``[since, until]``, normalised.

    The bounds are handed to ``list_sightings`` (padded by
    ``_SIGHTING_PAD_H``, see above) so the manifest list this walks is
    the window's, not the whole archive's. Raises on read failure — the
    caller turns that into a ``degraded`` marker.
    """
    lo = since - timedelta(hours=_SIGHTING_PAD_H) if since is not None else None
    hi = until + timedelta(hours=_SIGHTING_PAD_H) if until is not None else None
    result = weather_service.list_sightings(
        since_iso=_iso(lo) or None,
        until_iso=_iso(hi) or None,
        page=0,
        page_size=_PAGE_ALL,
    )
    out: list = []
    for m in result.get("items") or []:
        start, end = _manifest_span(m)
        if start is None:
            continue
        sid = m.get("id")
        if not isinstance(sid, str) or not sid:
            continue
        out.append(
            {
                "kind": m.get("event_type") or "weather",
                "cam_id": m.get("cam_id") or "",
                "cam_name": m.get("cam_name") or m.get("cam_id") or "",
                "start": start,
                "end": end,
                "video_url": "/api/weather/sightings/{}/clip".format(sid),
                "thumb_url": "/api/weather/sightings/{}/thumb".format(sid),
                "missing_media": not m.get("clip_path"),
                "extra": {
                    "sighting_id": sid,
                    "event_type": m.get("event_type"),
                    "api_snapshot": m.get("api_snapshot"),
                    "sun_snapshot": m.get("sun_snapshot"),
                },
            }
        )
    return out


def _timelapse_sidecar(mp4: Path) -> dict:
    sidecar = mp4.with_suffix(".json")
    if not sidecar.exists():
        return {}
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("[weather] timelapse sidecar unreadable %s: %s", sidecar.name, e)
        return {}
    return data if isinstance(data, dict) else {}


def timelapse_candidates(storage_root: Path, cam_names: dict) -> list:
    """The daily / rolling timelapse MP4s, one candidate per file."""
    root = Path(storage_root) / "timelapse"
    if not root.exists():
        return []
    out: list = []
    for cam_dir in sorted(root.iterdir()):
        if not cam_dir.is_dir():
            continue
        for mp4 in sorted(cam_dir.glob("*.mp4")):
            meta = _timelapse_sidecar(mp4)
            try:
                mtime = mp4.stat().st_mtime
            except OSError:
                continue
            end = _safe_dt(str(meta.get("time") or "")) or datetime.fromtimestamp(mtime)
            period = _num(meta.get("period_s"), 0.0) or _DEFAULT_TIMELAPSE_PERIOD_S
            thumb = mp4.with_suffix(".jpg")
            rel = mp4.relative_to(storage_root).as_posix()
            out.append(
                {
                    "kind": "timelapse",
                    "cam_id": cam_dir.name,
                    "cam_name": cam_names.get(cam_dir.name) or cam_dir.name,
                    "start": end - timedelta(seconds=period),
                    "end": end,
                    "video_url": "/media/{}".format(rel),
                    "thumb_url": (
                        "/media/{}".format(thumb.relative_to(storage_root).as_posix())
                        if thumb.exists()
                        else ""
                    ),
                    "missing_media": False,
                    "extra": {"profile": meta.get("profile") or meta.get("period") or ""},
                }
            )
    return out


def _motion_span(obj: dict, start: datetime) -> datetime:
    length = _num(obj.get("video_duration_s"), 0.0) or _num(obj.get("duration_s"), 0.0)
    return start + timedelta(seconds=max(_DEFAULT_MOTION_SPAN_S, length))


def motion_candidates(store, cam_ids: list, cam_names: dict, since=None, until=None) -> list:
    """Motion events with media, per camera, inside ``[since, until]``.

    Reads via ``motion_events_between``, which prunes on the date-folder
    name — the window is hours wide and the tree is years deep, so the
    unbounded read this used to do (``list_events`` parses EVERY event
    JSON before applying its ``start``) was the whole cost of the route.

    The whole event payload rides along in ``extra`` because the client
    hands motion tiles to the existing lightbox, which speaks exactly
    the shape ``/api/camera/<id>/media`` returns.
    """
    lo = _iso(since - timedelta(minutes=_MOTION_PAD_MIN) if since is not None else None)
    hi = _iso(until)
    out: list = []
    for cam_id in cam_ids:
        try:
            events = motion_events_between(store, cam_id, lo, hi)
        except Exception as e:
            log.warning("[weather] motion scan failed for %s: %s", cam_id, e)
            continue
        for obj in events:
            start = _safe_dt(str(obj.get("time") or ""))
            if start is None:
                continue
            rel = obj.get("video_relpath") or obj.get("snapshot_relpath") or ""
            out.append(
                {
                    "kind": "motion",
                    "cam_id": cam_id,
                    "cam_name": cam_names.get(cam_id) or cam_id,
                    "start": start,
                    "end": _motion_span(obj, start),
                    "video_url": "/media/{}".format(rel) if rel else "",
                    "thumb_url": (
                        "/media/{}".format(obj.get("snapshot_relpath"))
                        if obj.get("snapshot_relpath")
                        else ""
                    ),
                    "missing_media": not obj.get("video_relpath"),
                    "extra": dict(obj),
                }
            )
    return out
