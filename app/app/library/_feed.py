"""Merge every library source into one time-sorted, paginated feed.

``list_library_items`` is the Stage-3 read model behind ``GET
/api/library`` (``routes/library.py``): the Mediathek (motion clips)
and the Wetter-Ereignisse (sightings, recaps, manual events, storm
episodes) are being merged into ONE browsable list, default "everything
mixed", newest first. This module owns the cross-source sort + page,
not the per-source reads — those already live in ``._motion_reader``
and ``._weather_readers``, plus ``weather_episodes._footage_sources``
for sightings and daily timelapse MP4s.

Windowing
---------
The archive is years deep — weather history alone is a 3-year rolling
window before episode-archiving, and judged/pinned motion events are
kept indefinitely — so a page cannot be produced by reading everything
and sorting. Instead the query window starts narrow (``hi`` down to
``hi - 1 day``) and widens outward in the steps below until either
``limit`` items have been found or the earliest step is exhausted:
quadrupling from a day reaches roughly 11 years in 7 steps, comfortably
past every retention window this app has, while the common case — the
newest page, where everything requested sits in the last day or two —
costs one or two reader calls instead of a guess at "the right window".
A flat doubling would need twice as many steps to reach the same floor;
a base larger than 4 was rejected because the FIRST step still has to
stay cheap for a quiet camera with nothing in the last 24h — overshooting
there defeats the point of widening instead of reading everything at
once (see ``weather_episodes._footage_sources``'s own padding-constant
comments for the same kind of tradeoff, on a different axis).

Not every source benefits from a narrower window the way motion does —
see ``._weather_readers``'s module docstring for which ones always pay
a full read regardless of the bound. Those are fetched exactly ONCE per
request (below, as ``flat``) and then filtered/widened in memory like
any other already-loaded list, rather than being re-invoked on every
widen step for no saving.

Pagination
----------
Newest-first across heterogeneous sources needs a cursor that survives
ties (two items with the identical timestamp, one from each of two
different stores). The sort key is ``(start, item_id)`` where
``item_id`` is each source's own natural id — stable across a re-fetch
by a later, wider window, unlike a positional offset would be. The
opaque ``next_cursor`` returned to the client encodes exactly that pair;
``before=<cursor>`` on the next call resumes strictly after it, so a
caller that pages all the way through sees every item exactly once even
though nothing here assumes the underlying stores are immutable between
page 1 and page 2 (a mutation shifts what page 2 WOULD have started at,
not what a resumed cursor already anchors past).
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from datetime import datetime, timedelta

from ._motion_reader import motion_candidates
from ._weather_readers import episode_candidates, manual_event_candidates, recap_candidates

# `weather_candidates` / `timelapse_candidates` are deliberately NOT
# imported at module level here. `weather_episodes._footage_sources`
# imports `library._motion_reader` at ITS module load time, so an eager
# import in the other direction here would close a cycle: whichever of
# the two packages happens to load first would find the other's names
# not bound yet (a `from partially initialized module` ImportError).
# Deferred imports inside `_flat_candidates` / `_windowed_candidates`
# break it the same way `_weather_readers.episode_candidates` already
# does for the same reason.

log = logging.getLogger(__name__)

#: The feed's full kind vocabulary — what a ``kinds`` filter may name.
KINDS: tuple[str, ...] = ("motion", "sighting", "recap", "manual", "episode", "timelapse")

#: Window widths (days) tried outward from ``hi``, narrowest first.
_WINDOW_STEPS_DAYS: tuple[int, ...] = (1, 4, 16, 64, 256, 1024, 4096)

#: Absolute stop so a pathological cursor (or a genuinely empty
#: library) cannot spin through widen steps forever. No footage in this
#: app predates the year 2000.
_FLOOR = datetime(2000, 1, 1)


def _overlaps(item: dict, lo: datetime, hi: datetime) -> bool:
    return item["end"] >= lo and item["start"] <= hi


def _item_id(item: dict) -> str:
    """Stable per-item id: de-dup key across widen steps AND the
    pagination tie-break. Prefers each reader's own natural id (already
    living in ``extra``) so the cursor keeps meaning the same item even
    if a later, wider window re-fetches it."""
    extra = item.get("extra") or {}
    natural = (
        extra.get("event_id")
        or extra.get("sighting_id")
        or extra.get("recap_id")
        or extra.get("manual_event_id")
        or extra.get("id")  # episode record's own id
        or item.get("video_url")
        or item.get("thumb_url")
        or item["start"].isoformat()
    )
    return "{}:{}".format(item["kind"], natural)


def _sort_key(item: dict):
    return (item["start"], _item_id(item))


def _encode_cursor(item: dict) -> str:
    raw = json.dumps([item["start"].isoformat(timespec="seconds"), _item_id(item)])
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str):
    """``(start, item_id)`` from an opaque cursor, or ``(None, None)``
    on anything malformed — a bad cursor degrades to "first page"
    rather than 500ing, the same tolerance ``/api/camera/<id>/media``
    already gives a bogus ``limit``/``offset``."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        start_iso, item_id = json.loads(raw)
        start = datetime.fromisoformat(start_iso)
        if not isinstance(item_id, str) or not item_id:
            return None, None
        return start, item_id
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError):
        return None, None


def _category_of(item: dict) -> set:
    kind = item["kind"]
    extra = item.get("extra") or {}
    if kind == "sighting":
        et = extra.get("event_type")
        return {et} if et else set()
    if kind == "manual":
        cats = extra.get("categories")
        return set(cats) if isinstance(cats, list) else set()
    if kind == "episode":
        cls = extra.get("user_class") or extra.get("auto_class")
        return {cls} if cls else set()
    return set()


def _matches_categories(item: dict, categories) -> bool:
    # Categories only constrain the three weather-classified kinds —
    # it is not a concept motion/recap/timelapse have, so they pass
    # through unfiltered rather than being blanket-excluded.
    if not categories or item["kind"] not in ("sighting", "manual", "episode"):
        return True
    return bool(_category_of(item) & set(categories))


def _cam_scoped_ok(item: dict, camera_ids) -> bool:
    if not camera_ids:
        return True
    cam_id = item.get("cam_id") or ""
    # Cross-camera kinds (recap/manual/episode) carry cam_id="" and are
    # never hidden by a camera filter — there is no single camera to
    # match against.
    return not cam_id or cam_id in camera_ids


def _resolve_cameras(cameras, camera_ids):
    """``(cam_ids, cam_names)`` for the motion/sighting/timelapse readers.

    ``camera_ids`` (an explicit filter) wins over the active-config
    camera list when given, so a request naming an archived camera id
    still queries it — the same permissiveness
    ``/api/camera/<cam>/media`` already has for any single cam_id in
    its URL. ``cam_names`` still prefers the config's display name when
    the id is also a known active camera.
    """
    cam_names = {c.get("id"): c.get("name") or c.get("id") for c in cameras or [] if c.get("id")}
    if camera_ids:
        cam_ids = list(camera_ids)
    else:
        cam_ids = [c.get("id") for c in cameras or [] if c.get("id")]
    return cam_ids, cam_names


def _public_item(item: dict) -> dict:
    return {
        "kind": item["kind"],
        "id": _item_id(item),
        "cam_id": item.get("cam_id") or "",
        "cam_name": item.get("cam_name") or "",
        "start": item["start"].isoformat(timespec="seconds"),
        "end": item["end"].isoformat(timespec="seconds") if item.get("end") else None,
        "video_url": item.get("video_url") or "",
        "thumb_url": item.get("thumb_url") or "",
        "missing_media": bool(item.get("missing_media")),
        "extra": item.get("extra") or {},
    }


def _flat_candidates(
    want, weather_service, storage_root, cam_names, camera_ids, categories
) -> list:
    """Everything from the un-windowed sources, fetched once, filtered
    to camera + category here since their own readers don't take those
    knobs (see ``._weather_readers``)."""
    out: list = []
    if "recap" in want:
        out.extend(recap_candidates(weather_service))
    if "manual" in want:
        out.extend(manual_event_candidates(weather_service))
    if "episode" in want:
        out.extend(episode_candidates(storage_root))
    if "timelapse" in want and storage_root is not None:
        from ..weather_episodes._footage_sources import timelapse_candidates

        out.extend(timelapse_candidates(storage_root, cam_names))
    return [
        it for it in out if _cam_scoped_ok(it, camera_ids) and _matches_categories(it, categories)
    ]


def _windowed_candidates(
    want,
    store,
    weather_service,
    cam_ids,
    cam_names,
    camera_ids,
    label,
    labels,
    categories,
    lo,
    hi,
    degraded,
) -> list:
    """The two sources that ARE cheaper over a narrower window."""
    out: list = []
    if "motion" in want and store is not None and cam_ids:
        out.extend(
            motion_candidates(
                store, cam_ids, cam_names, since=lo, until=hi, label=label, labels=labels
            )
        )
    if "sighting" in want and weather_service is not None:
        from ..weather_episodes._footage_sources import weather_candidates

        try:
            sightings = weather_candidates(weather_service, since=lo, until=hi)
        except Exception as e:
            log.warning("[weather] library feed: sighting scan failed: %s", e)
            if "weather_service_unavailable" not in degraded:
                degraded.append("weather_service_unavailable")
        else:
            out.extend(
                it
                for it in sightings
                if _cam_scoped_ok(it, camera_ids) and _matches_categories(it, categories)
            )
    return out


def list_library_items(
    *,
    store=None,
    weather_service=None,
    storage_root=None,
    cameras=None,
    kinds=None,
    camera_ids=None,
    label=None,
    labels=None,
    categories=None,
    before=None,
    limit=30,
) -> dict:
    """One merged, newest-first page across whichever ``kinds`` are asked for.

    Returns ``{"items": [...], "next_cursor": str | None, "degraded": [...]}``.
    ``next_cursor`` is ``None`` once no more items exist (or, past
    ``_WINDOW_STEPS_DAYS``'s reach, are no longer being looked for — see
    the module docstring). ``degraded`` names sources that failed to
    read rather than being silently dropped, mirroring
    ``weather_episodes.build_footage_index``'s own convention.
    """
    want = (set(kinds) if kinds else set(KINDS)) & set(KINDS)
    cam_ids, cam_names = _resolve_cameras(cameras, camera_ids)

    cursor_start, cursor_id = _decode_cursor(before) if before else (None, None)
    hi = cursor_start if cursor_start is not None else datetime.now()

    degraded: list = []
    flat = _flat_candidates(want, weather_service, storage_root, cam_names, camera_ids, categories)

    matched: dict[str, dict] = {}
    eligible: list = []
    lo = hi
    for days in _WINDOW_STEPS_DAYS:
        lo = hi - timedelta(days=days)
        window = [it for it in flat if _overlaps(it, lo, hi)]
        window.extend(
            _windowed_candidates(
                want,
                store,
                weather_service,
                cam_ids,
                cam_names,
                camera_ids,
                label,
                labels,
                categories,
                lo,
                hi,
                degraded,
            )
        )
        for it in window:
            matched[_item_id(it)] = it
        eligible = [
            it
            for it in matched.values()
            if cursor_start is None or _sort_key(it) < (cursor_start, cursor_id)
        ]
        if len(eligible) > limit or lo <= _FLOOR:
            break

    eligible.sort(key=_sort_key, reverse=True)
    page = eligible[:limit]
    next_cursor = _encode_cursor(page[-1]) if len(eligible) > limit and page else None
    return {
        "items": [_public_item(it) for it in page],
        "next_cursor": next_cursor,
        "degraded": degraded,
    }
