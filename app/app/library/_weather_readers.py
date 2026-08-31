"""Recap / manual-event / episode readers, normalised like ``_footage_sources``.

Three of the six kinds the Mediathek + Wetter-Ereignisse merge folds
into one feed — motion and weather sightings already have normalised
readers (``._motion_reader`` and
``weather_episodes._footage_sources.weather_candidates`` respectively,
and the daily timelapse MP4s are covered by that module's
``timelapse_candidates``). Same candidate shape everywhere: ``kind``,
``cam_id``, ``cam_name``, ``start``, ``end``, ``video_url``,
``thumb_url``, ``missing_media``, ``extra``.

None of the three sources here are windowed at their own read layer:

* ``WeatherService.list_recaps()`` globs every recap manifest — at most
  a handful per year (quarterly + Q4 + annual), so this is not the
  "years-deep tree" problem the motion reader solves;
* ``WeatherService.list_manual_events()`` globs every user-saved chart
  range — operator-curated, so bounded by hand, not by retention;
* ``weather_episodes.list_episodes()`` folds ONE append-only ledger
  file — already the cheapest read the episode archive offers (see
  that package's ``_store.list_episodes`` docstring: the existing list
  route "has to stay a single append-only file read"). There is no
  per-record file to skip the way a motion day-folder can be skipped.

Filtering to a window therefore happens HERE, in memory, after one full
read. Narrowing the read itself would mean changing
``list_recaps``/``list_manual_events``'s contracts (adding since/until
params they don't have today) or the episode ledger's file layout —
both are decisions for whoever owns those call sites next, not a
drive-by in a read-model merge; see the Stage-3 report. ``library._feed``
takes advantage of the "already cheap" fact: it reads each of these
three exactly ONCE per request no matter how many times its own
window-widening loop runs, because re-fetching would not make any of
them cheaper the way a narrower motion query does.
"""

from __future__ import annotations

from datetime import timedelta

from ..weather_service._consts import _safe_dt


def _overlaps(start, end, since, until) -> bool:
    if since is not None and end < since:
        return False
    return not (until is not None and start > until)


def recap_candidates(weather_service, since=None, until=None) -> list:
    """Quarterly / Q4 / annual highlight reels, normalised.

    A recap spans every camera, so ``cam_id``/``cam_name`` are empty —
    there is no single camera to attribute a cross-property reel to.
    ``start``/``end`` come from ``period_start``/``period_end`` (calendar
    DATES, not timestamps); the end is stretched to 23:59:59 of that day
    so a recap covering "2026-06-01..2026-06-30" is treated as covering
    the whole 30th rather than vanishing at its midnight.
    """
    if weather_service is None:
        return []
    out: list = []
    for m in weather_service.list_recaps() or []:
        start = _safe_dt(m.get("period_start") or "")
        end_day = _safe_dt(m.get("period_end") or "")
        if start is None or end_day is None:
            continue
        end = end_day + timedelta(days=1) - timedelta(seconds=1)
        if not _overlaps(start, end, since, until):
            continue
        rid = m.get("id")
        if not isinstance(rid, str) or not rid:
            continue
        out.append(
            {
                "kind": "recap",
                "cam_id": "",
                "cam_name": "",
                "start": start,
                "end": end,
                "video_url": "/api/weather/recaps/{}/clip".format(rid),
                "thumb_url": "",
                "missing_media": not m.get("clip_path"),
                "extra": {
                    "recap_id": rid,
                    "period_label": m.get("period_label"),
                    "n_clips": m.get("n_clips"),
                    "duration_s": m.get("duration_s"),
                },
            }
        )
    return out


def manual_event_candidates(weather_service, since=None, until=None) -> list:
    """User-saved chart ranges, normalised.

    A manual event is a named window over the weather curves, not a
    clip — ``video_url``/``thumb_url`` are always empty and
    ``missing_media`` is always True. There is nothing "missing" in the
    usual sense; the flag still means "no player for this card" to the
    client, the same signal it gives for any other kind.
    """
    if weather_service is None:
        return []
    out: list = []
    for m in weather_service.list_manual_events() or []:
        start = _safe_dt(m.get("range_start") or "")
        end = _safe_dt(m.get("range_end") or "")
        if start is None or end is None:
            continue
        if not _overlaps(start, end, since, until):
            continue
        mid = m.get("id")
        if not isinstance(mid, str) or not mid:
            continue
        out.append(
            {
                "kind": "manual",
                "cam_id": "",
                "cam_name": "",
                "start": start,
                "end": end,
                "video_url": "",
                "thumb_url": "",
                "missing_media": True,
                "extra": {
                    "manual_event_id": mid,
                    "name": m.get("name"),
                    "categories": m.get("categories"),
                    "characteristic": m.get("characteristic"),
                },
            }
        )
    return out


def episode_candidates(storage_root, since=None, until=None) -> list:
    """Archived storm episodes, normalised, WITHOUT their curve samples.

    ``weather_episodes.list_episodes`` already strips the sample array
    by default — this reader inherits that discipline rather than
    opting back in, matching ``/api/weather/episodes``'s own list route
    (see ``routes/weather_episodes.py::api_weather_episodes_list`` for
    why: the curve slice is the bulk of a record and would make a list
    view megabytes).

    An episode carries no clip of its own — the footage that overlaps
    its window lives in the four media stores
    ``weather_episodes.build_footage_index`` already knows how to find
    (``/api/weather/episodes/<id>/footage``); this reader only surfaces
    the storm RECORD itself as one feed card, so ``video_url``/
    ``thumb_url`` are empty and ``missing_media`` is always True.

    Deferred import, on purpose: ``weather_episodes`` imports
    ``library._motion_reader`` at ITS module load time (via
    ``_footage_sources.py``), so importing ``weather_episodes`` back at
    THIS module's load time would close an import cycle. A function-
    local import breaks it — by the time this function actually runs,
    both packages have finished loading (the same pattern already used
    in ``weather_service/_history.py`` for the same reason).
    """
    from ..weather_episodes import list_episodes

    if storage_root is None:
        return []
    out: list = []
    for rec in list_episodes(storage_root):
        start = _safe_dt(rec.get("started_at") or "")
        end = _safe_dt(rec.get("ended_at") or "")
        if start is None or end is None:
            continue
        if not _overlaps(start, end, since, until):
            continue
        eid = rec.get("id")
        if not isinstance(eid, str) or not eid:
            continue
        out.append(
            {
                "kind": "episode",
                "cam_id": "",
                "cam_name": "",
                "start": start,
                "end": end,
                "video_url": "",
                "thumb_url": "",
                "missing_media": True,
                "extra": dict(rec),
            }
        )
    return out
