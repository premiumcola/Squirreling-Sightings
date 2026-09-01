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

A caller may additionally pass ``since``/``until`` (Stage 7, the
Wetterdaten-chart drag-zoom) to clip the page to an explicit window
instead of "however far back the widen loop happens to reach". ``until``
replaces "now" as the loop's fixed upper edge (``hi``) from the very
first step; ``since`` is a floor the loop's widening ``lo`` is clamped
to and, once reached, stops the search from synthesizing any wider
window — the same way ``_FLOOR`` already stops it, just caller-supplied
instead of the year-2000 absolute backstop. Both are inclusive: an item
touching the boundary is in, matching ``_weather_readers._overlaps``'s
own rule (see that module). Omitting both reproduces today's behaviour
exactly — ``hi`` stays "now" (or the pagination cursor) and the loop
widens all the way out to ``_FLOOR`` as it always has.

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


def _outdoor_scope_ok(cameras, camera_ids) -> bool:
    """Whether camera-agnostic weather content (recap/manual/episode,
    which carry ``cam_id=""``) is relevant for the active ``camera_ids``
    filter.

    True with no filter at all ("Alles gemischt" keeps showing
    everything). Otherwise True iff at least one camera in the filter
    is marked outdoor (``CAMERA_SCHEMA["outdoor"]``, default True) —
    False only when every camera the filter names is indoor (e.g. an
    indoor "Werkstatt" cam), which is the operator-reported bug this
    exists to fix: a storm episode / recap / manual weather event has
    nothing to do with an indoor-only view. An id in the filter that no
    longer resolves to a known camera (e.g. archived) defaults to
    outdoor, the same default a fresh camera schema gets — an unknown
    camera should not silently suppress weather content."""
    if not camera_ids:
        return True
    outdoor_by_id = {c.get("id"): c.get("outdoor", True) for c in (cameras or []) if c.get("id")}
    return any(outdoor_by_id.get(cid, True) for cid in camera_ids)


def _cam_scoped_ok(item: dict, camera_ids, weather_visible: bool = True) -> bool:
    if not camera_ids:
        return True
    cam_id = item.get("cam_id") or ""
    if not cam_id:
        # Cross-camera kinds (recap/manual/episode) carry cam_id="" —
        # there is no single camera to match against, so whether they
        # pass a camera filter is decided by the filter's outdoor-ness
        # instead (see `_outdoor_scope_ok`). A real cam_id below is
        # matched against the filter set exactly as before.
        return weather_visible
    return cam_id in camera_ids


def _resolve_want(kinds, label, labels) -> set:
    """The kind scope for one request.

    An explicit ``kinds`` always wins. Otherwise: ``label``/``labels``
    only ever reach ``motion_candidates`` (see ``_windowed_candidates``
    below) — no other kind has an object-detector label concept, a
    weather ``sighting`` included, whose ``event_type`` is a WEATHER
    category, not a label. Without this narrowing, a caller that asks
    for e.g. ``labels=cat`` and never names ``kinds`` got every recap /
    manual-event / episode / timelapse / sighting in the window too,
    completely unfiltered by the label just asked for — silently
    riding through ``_flat_candidates``, which has no ``labels``
    parameter at all. Restricting ``want`` to the kinds that CAN honour
    the filter (``motion`` today) is the fix.
    """
    want = (set(kinds) if kinds else set(KINDS)) & set(KINDS)
    if (label or labels) and kinds is None:
        want &= {"motion"}
    return want


def _widen_matches(
    *,
    want,
    store,
    weather_service,
    cam_ids,
    cam_names,
    camera_ids,
    label,
    labels,
    categories,
    flat,
    hi,
    since,
    degraded,
    keep_widening,
) -> dict[str, dict]:
    """Merge candidates into one ``item_id -> item`` dict, widening the
    ``[lo, hi]`` window outward one ``_WINDOW_STEPS_DAYS`` step at a
    time until ``keep_widening(matched)`` says stop, ``since``/``_FLOOR``
    is reached, or the steps run out.

    Shared by ``list_library_items`` (stops as soon as enough items for
    one page are in hand — ``keep_widening`` checks the cursor-filtered
    count against ``limit``) and ``_facets.count_library_facets``
    (``keep_widening`` always returns ``True``, so this runs to full
    exhaustion — a facet/total count needs the complete matching set,
    not just enough for a page). See the module docstring's "Windowing"
    section for why the steps are shaped the way they are.
    """
    matched: dict[str, dict] = {}
    lo = hi
    for days in _WINDOW_STEPS_DAYS:
        lo = hi - timedelta(days=days)
        since_floor = since is not None and lo <= since
        if since_floor:
            lo = since
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
        if not keep_widening(matched) or lo <= _FLOOR or since_floor:
            break
    return matched


def _eligible_items(matched: dict, cursor_start, cursor_id) -> list:
    """``matched.values()`` strictly past the pagination cursor — the
    slice both the widen loop's own stop check and the final page
    build need, computed the same way in both places."""
    return [
        it
        for it in matched.values()
        if cursor_start is None or _sort_key(it) < (cursor_start, cursor_id)
    ]


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
    want, weather_service, storage_root, cam_names, camera_ids, categories, weather_visible=True
) -> list:
    """Everything from the un-windowed sources, fetched once, filtered
    to camera + category here since their own readers don't take those
    knobs (see ``._weather_readers``).

    ``weather_visible`` (see ``_outdoor_scope_ok``) gates the cam_id=""
    recap/manual/episode items when ``camera_ids`` is a real filter;
    it is irrelevant — and safe to leave at its default — whenever
    ``camera_ids`` is falsy, since ``_cam_scoped_ok`` short-circuits to
    True before ever looking at it (the shape ``count_library_facets``
    relies on when it gathers the unfiltered candidate superset)."""
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
        it
        for it in out
        if _cam_scoped_ok(it, camera_ids, weather_visible) and _matches_categories(it, categories)
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
            # `weather_candidates` is shared with the episode-footage
            # index (`weather_episodes._footage.build_footage_index`),
            # where `kind` intentionally carries the specific weather
            # type (thunder / heavy_rain / sun_timelapse_rise / ...) so
            # footage tiles can be grouped by it. This feed's own kind
            # vocabulary (`KINDS` above) has no such per-type slots —
            # every weather sighting is ONE library kind, "sighting" —
            # so it is normalised here, at the merge boundary, instead
            # of inside the shared reader. The specific type still
            # survives in `extra.event_type` (`_category_of` above
            # already reads it from there for the categories filter,
            # which is silently a no-op without this normalisation).
            for it in sightings:
                it["kind"] = "sighting"
            # `weather_candidates` pads its OWN query by `_SIGHTING_PAD_H`
            # on each side (see that function's docstring) and returns
            # whatever the service hands back inside that padded window
            # without re-clipping — right for the widen loop's own
            # `[lo, hi]` steps (an over-fetch here just means an item
            # surfaces one widen step earlier, harmless since `matched`
            # only ever grows), wrong for an explicit `since`/`until`
            # the caller set: without `_overlaps` below, a sighting up to
            # `_SIGHTING_PAD_H` outside that bound would leak into the
            # page.
            out.extend(
                it
                for it in sightings
                if _overlaps(it, lo, hi)
                and _cam_scoped_ok(it, camera_ids)
                and _matches_categories(it, categories)
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
    since: datetime | None = None,
    until: datetime | None = None,
    before=None,
    limit=30,
) -> dict:
    """One merged, newest-first page across whichever ``kinds`` are asked for.

    ``since``/``until`` clip the page to an explicit window — see the
    module docstring's "Windowing" section for exactly how they interact
    with the widen loop. Both inclusive at the boundary; both default to
    ``None`` ("unbounded"), which reproduces the pre-Stage-7 behaviour
    exactly.

    Returns ``{"items": [...], "next_cursor": str | None, "degraded": [...]}``.
    ``next_cursor`` is ``None`` once no more items exist (or, past
    ``_WINDOW_STEPS_DAYS``'s reach, are no longer being looked for — see
    the module docstring). ``degraded`` names sources that failed to
    read rather than being silently dropped, mirroring
    ``weather_episodes.build_footage_index``'s own convention.
    """
    want = _resolve_want(kinds, label, labels)
    cam_ids, cam_names = _resolve_cameras(cameras, camera_ids)

    cursor_start, cursor_id = _decode_cursor(before) if before else (None, None)
    hi = cursor_start if cursor_start is not None else datetime.now()
    if until is not None:
        hi = min(hi, until)

    degraded: list = []
    # Computed ONCE per request (not per item) — whether the active
    # camera_ids filter includes at least one outdoor camera, or has no
    # filter at all. Gates every cam_id="" recap/manual/episode item
    # `_flat_candidates` gathers below; motion/sighting/timelapse items
    # always carry a real cam_id and are unaffected (see
    # `_outdoor_scope_ok`/`_cam_scoped_ok`).
    weather_visible = _outdoor_scope_ok(cameras, camera_ids)
    flat = _flat_candidates(
        want, weather_service, storage_root, cam_names, camera_ids, categories, weather_visible
    )

    matched = _widen_matches(
        want=want,
        store=store,
        weather_service=weather_service,
        cam_ids=cam_ids,
        cam_names=cam_names,
        camera_ids=camera_ids,
        label=label,
        labels=labels,
        categories=categories,
        flat=flat,
        hi=hi,
        since=since,
        degraded=degraded,
        # Stop as soon as one page's worth (past the cursor) is in hand
        # — the early-stop behaviour this function has always had; see
        # `_widen_matches`'s own docstring for the exhaustive counterpart.
        keep_widening=lambda m: len(_eligible_items(m, cursor_start, cursor_id)) <= limit,
    )
    eligible = _eligible_items(matched, cursor_start, cursor_id)
    eligible.sort(key=_sort_key, reverse=True)
    page = eligible[:limit]
    next_cursor = _encode_cursor(page[-1]) if len(eligible) > limit and page else None
    return {
        "items": [_public_item(it) for it in page],
        "next_cursor": next_cursor,
        "degraded": degraded,
    }
