"""Recordings that overlap a storm episode's window.

The archive stores a curve, not video. What makes an episode readable
years later is the footage that happens to sit inside its window, so
this module answers one question: *which recordings overlap
``[started_at - pre_min, ended_at + post_min]``?*

Four existing stores are consulted, none of them touched:

* weather sightings (``storage/weather/<cam>/<event>/*.json``) — split
  into the storm-purpose group (event timelapses), the alert clips and
  the sun timelapses;
* the daily timelapse MP4s (``storage/timelapse/<cam>/*.mp4``);
* motion events (``EventStore``).

Everything is read-only and every source is optional: a missing weather
service costs its groups and a ``degraded`` marker, never an error. The
distinction the UI needs is "no footage" (an empty payload, HTTP 200)
versus "could not look" (a marker), and it is made here rather than in
the client.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from ..weather_service._consts import EVENT_LABEL_DE, _safe_dt
from ._footage_sources import motion_candidates, timelapse_candidates, weather_candidates

log = logging.getLogger(__name__)

# Group keys, in the order the client renders them. `_other` in the UI
# is the union of `timelapse` + `motion`; the split is kept here so a
# future renderer can separate them again without a backend change.
GROUP_KEYS: tuple[str, ...] = (
    "event_timelapse",
    "weather_clips",
    "sun_timelapse",
    "timelapse",
    "motion",
)

# Event-timelapse triggers surface as their own display kinds (the
# weather service rewrites `event_type` to the trigger name on read).
EVENT_TL_KINDS: frozenset = frozenset(
    {"event_timelapse", "thunder_rising", "front_passing", "storm_front"}
)
SUN_TL_KINDS: frozenset = frozenset({"sun_timelapse", "sun_timelapse_rise", "sun_timelapse_set"})

KIND_LABEL_DE: dict[str, str] = {
    "event_timelapse": "Gewitter-Zeitraffer",
    "thunder_rising": "Aufziehendes Gewitter",
    "front_passing": "Front im Durchzug",
    "storm_front": "Sturmfront",
    "sun_timelapse": "Sonnen-Zeitraffer",
    "sun_timelapse_rise": "Sonnenaufgang",
    "sun_timelapse_set": "Sonnenuntergang",
    "timelapse": "Zeitraffer",
    "motion": "Bewegung",
}

# Nobody scrolls past this many incidental clips; the client caps its own
# display at 12 and offers "alle N anzeigen" against the same list.
MAX_ITEMS_PER_GROUP = 200


def kind_label(kind: str) -> str:
    return KIND_LABEL_DE.get(kind) or EVENT_LABEL_DE.get(kind) or kind


def _group_of(kind: str) -> str:
    if kind in EVENT_TL_KINDS:
        return "event_timelapse"
    if kind in SUN_TL_KINDS:
        return "sun_timelapse"
    if kind in ("timelapse", "motion"):
        return kind
    return "weather_clips"


def episode_window(rec: dict) -> tuple:
    """``(start, end)`` of the record's stored slice, margins included.

    The margins are part of what was archived, so a clip filmed during
    the build-up belongs to the episode as much as one filmed at its
    peak. Returns ``(None, None)`` when the record has no usable
    timestamps.
    """
    start = _safe_dt(rec.get("started_at") or "")
    end = _safe_dt(rec.get("ended_at") or "")
    if start is None or end is None:
        return None, None
    try:
        pre = max(0.0, float(rec.get("pre_min") or 0))
        post = max(0.0, float(rec.get("post_min") or 0))
    except (TypeError, ValueError):
        pre = post = 0.0
    return start - timedelta(minutes=pre), end + timedelta(minutes=post)


def _overlap_s(a0, a1, b0, b1) -> float:
    lo = max(a0, b0)
    hi = min(a1, b1)
    return max(0.0, (hi - lo).total_seconds())


def _time_label(start: datetime, end: datetime) -> str:
    """``14:12`` for a moment, ``14:12–14:40`` for a real span."""
    head = start.strftime("%H:%M")
    if (end - start).total_seconds() < 120:
        return head
    return "{}–{}".format(head, end.strftime("%H:%M"))


def _event_tl_enabled(cameras: list) -> bool:
    """True when at least one camera can produce a Gewitter-Zeitraffer."""
    for cam in cameras or []:
        weather = (cam or {}).get("weather") or {}
        if weather.get("enabled") and (weather.get("event_timelapse") or {}).get("enabled"):
            return True
    return False


def build_footage_index(
    storage_root, *, weather_service=None, store=None, cameras=None, since=None, until=None
):
    """Scan the media stores for ONE window. Returns ``(candidates, degraded)``.

    ``since`` / ``until`` are the outer bounds of the episode windows the
    caller is about to answer for. They are not a nicety: without them
    every source degenerates into a full-archive walk, which is what
    made the list route cost seconds. The bounds are passed INTO each
    reader (so the pruning happens at the filesystem, not after) and
    applied again here, because a reader may pad its own query to catch
    recordings stamped at the far end of their span.
    """
    cams = list(cameras or [])
    cam_names = {c.get("id"): c.get("name") or c.get("id") for c in cams if c.get("id")}
    candidates: list = []
    degraded: list = []
    if weather_service is None:
        degraded.append("weather_service_unavailable")
    else:
        try:
            candidates.extend(weather_candidates(weather_service, since=since, until=until))
        except Exception as e:
            log.warning("[weather] episode footage: sighting scan failed: %s", e)
            degraded.append("weather_service_unavailable")
    try:
        candidates.extend(timelapse_candidates(storage_root, cam_names))
    except OSError as e:
        log.warning("[weather] episode footage: timelapse scan failed: %s", e)
    if store is not None and cam_names:
        candidates.extend(motion_candidates(store, list(cam_names), cam_names, since, until))
    if not _event_tl_enabled(cams):
        degraded.append("event_timelapse_disabled")
    return _within(candidates, since, until), degraded


def _within(candidates: list, since, until) -> list:
    """Drop candidates that cannot overlap ``[since, until]`` at all."""
    if since is None and until is None:
        return candidates
    return [
        c
        for c in candidates
        if (until is None or c["start"] <= until) and (since is None or c["end"] >= since)
    ]


def _item(cand: dict, overlap: float) -> dict:
    kind = cand["kind"]
    item = {
        "kind": kind,
        "kind_label": kind_label(kind),
        "cam_id": cand["cam_id"],
        "cam_name": cand["cam_name"],
        "time_label": _time_label(cand["start"], cand["end"]),
        "thumb_url": cand.get("thumb_url") or "",
        "video_url": cand.get("video_url") or "",
        "missing_media": bool(cand.get("missing_media")),
        "overlap_s": round(overlap, 1),
        "span": {
            "start": cand["start"].isoformat(timespec="seconds"),
            "end": cand["end"].isoformat(timespec="seconds"),
        },
    }
    extra = cand.get("extra") or {}
    for key, value in extra.items():
        item.setdefault(key, value)
    return item


def _hero_item(cand: dict, overlap: float) -> dict:
    """Slim projection of one candidate for the episode's stamped hero
    pointer — kind/label/thumb/video/time only, deliberately NOT the
    full `_item()` shape (`extra`, `span`, `overlap_s`). This rides
    inside the append-only episode ledger forever (see
    ``_store.append_footage_count``'s ``hero`` param), unlike
    ``_item()``'s payload, which is built fresh on every footage-route
    hit and never stored — a slice of `extra` (an api_snapshot, say)
    would grow the ledger on every re-scan for no reader that needs it.
    """
    return {
        "kind": cand["kind"],
        "kind_label": kind_label(cand["kind"]),
        "cam_name": cand.get("cam_name") or cand.get("cam_id") or "",
        "time_label": _time_label(cand["start"], cand["end"]),
        "thumb_url": cand.get("thumb_url") or "",
        "video_url": cand.get("video_url") or "",
    }


def episode_hero(candidates: list, rec: dict) -> dict | None:
    """The single best-overlap PLAYABLE candidate for ``rec``'s window.

    "Playable" excludes anything ``missing_media`` or without both a
    thumbnail and a video URL — a hero the merged grid cannot actually
    show a picture of is worse than no hero (it would fall back to the
    curve-only card anyway, just later and less honestly). ``None``
    means exactly that fallback case, the same "absent, never a lie"
    contract ``footage_count`` already has.

    Computed alongside (never instead of) ``episode_footage``'s grouped
    payload, from the same already-fetched ``candidates`` list — an
    in-memory second pass, not a second store read. The result is what
    ``_store.append_footage_count`` stamps into the ledger next to
    ``footage_count`` as ``hero``, so the merged grid's card
    (``library/_weather_readers.episode_candidates`` copies the whole
    folded record into ``extra``) reads it for free from data it
    already has — no per-card footage fetch. See that module's
    docstring for the cost model this avoids: the grid can show 30
    episode cards on one page, and a request per card would mean 30
    requests per paint.
    """
    start, end = episode_window(rec)
    if start is None:
        return None
    best = None
    best_overlap = 0.0
    for cand in candidates:
        if cand.get("missing_media") or not cand.get("thumb_url") or not cand.get("video_url"):
            continue
        overlap = _overlap_s(start, end, cand["start"], cand["end"])
        if overlap <= 0:
            continue
        if best is None or overlap > best_overlap:
            best, best_overlap = cand, overlap
    return _hero_item(best, best_overlap) if best is not None else None


def episode_footage(candidates: list, degraded: list, rec: dict) -> dict:
    """The payload for one episode: grouped items, total, degraded flags."""
    start, end = episode_window(rec)
    groups: dict = {key: [] for key in GROUP_KEYS}
    if start is None:
        return {"groups": groups, "total": 0, "degraded": list(degraded)}
    for cand in candidates:
        overlap = _overlap_s(start, end, cand["start"], cand["end"])
        if overlap <= 0:
            continue
        groups[_group_of(cand["kind"])].append(_item(cand, overlap))
    total = 0
    for items in groups.values():
        items.sort(key=lambda it: (-it["overlap_s"], it["span"]["start"]))
        del items[MAX_ITEMS_PER_GROUP:]
        total += len(items)
    return {"groups": groups, "total": total, "degraded": list(degraded)}
