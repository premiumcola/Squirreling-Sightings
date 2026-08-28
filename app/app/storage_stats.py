"""Roll-ups over the event store: the Statistik range view and the
Telegram daily / weekly summary.

Carved out of ``storage.py`` — ``stats_range`` alone was 84 lines
against an 80-line ceiling, in a file 54% over its own.

The colour map that used to live inline here was the second of three
label vocabularies in the codebase (it knew fox / hedgehog / marten;
``media_index._visible`` did not, so a fox got a chart segment and no
badge). Both now read :mod:`app.app.labels`.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from .labels import MOTION_LABEL, label_color


def _is_timelapse(event: dict) -> bool:
    return event.get("type") == "timelapse" or "timelapse" in (event.get("labels") or [])


def _segment(label: str, count: int) -> dict:
    return {
        "label": label,
        "label_de": label,
        "count": count,
        "color": label_color(label),
    }


def _tally(events: list) -> tuple:
    """One pass over the events. Returns the five counters the payload
    is assembled from."""
    by_day: dict = defaultdict(Counter)
    by_hour: Counter = Counter()
    top: Counter = Counter()
    species_top: Counter = Counter()
    cat_names: Counter = Counter()
    media = Counter()
    for event in events:
        stamp = event.get("time", "")
        day = stamp[:10] if len(stamp) >= 10 else "unbekannt"
        hour = stamp[11:13] if len(stamp) >= 13 else "??"
        for label in event.get("labels", []) or [MOTION_LABEL]:
            by_day[day][label] += 1
            top[label] += 1
        if event.get("bird_species"):
            species_top[event["bird_species"]] += 1
        if event.get("cat_name"):
            cat_names[event["cat_name"]] += 1
        by_hour[hour] += 1
        if event.get("snapshot_url"):
            media["photos"] += 1
        if event.get("video_url"):
            media["videos"] += 1
    return by_day, by_hour, top, species_top, cat_names, media


def stats_range(
    store,
    camera_id: str,
    label: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """Per-day / per-hour / per-label breakdown for the Statistik view."""
    events = store.list_events(camera_id, label=label, start=start, end=end, limit=5000)
    by_day, by_hour, top, species_top, cat_names, media = _tally(events)
    day_items = []
    for day in sorted(by_day.keys()):
        segments = [_segment(lab, count) for lab, count in by_day[day].most_common()]
        day_items.append(
            {
                "day": day,
                "total": sum(seg["count"] for seg in segments),
                "segments": segments,
            }
        )
    return {
        "total_events": len(events),
        "photos": media["photos"],
        "videos": media["videos"],
        "top_objects": [_segment(lab, cnt) for lab, cnt in top.most_common(8)],
        "top_bird_species": [
            {"label": lab, "count": cnt} for lab, cnt in species_top.most_common(8)
        ],
        "top_cat_names": [{"label": lab, "count": cnt} for lab, cnt in cat_names.most_common(8)],
        "by_day": day_items,
        "by_hour": [{"hour": h, "count": by_hour[h]} for h in sorted(by_hour.keys())],
    }


def aggregate_summary(store, days: int = 1) -> dict:
    """Sightings roll-up behind the Telegram daily / weekly report.

    Timelapse entries are excluded: they are one rendered video per
    window, not a sighting, and counting them made the report claim
    events on a day the camera saw nothing.
    """
    start = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    per_camera: dict = {}
    top: Counter = Counter()
    bird_species: Counter = Counter()
    cat_names: Counter = Counter()
    total = 0
    events_dir = store.events_dir
    for cam_dir in sorted(events_dir.iterdir()) if events_dir.exists() else []:
        if not cam_dir.is_dir():
            continue
        events = [
            e
            for e in store.list_events(cam_dir.name, start=start, limit=5000)
            if not _is_timelapse(e)
        ]
        total += len(events)
        per_camera[cam_dir.name] = len(events)
        for event in events:
            for label in event.get("labels", []) or [MOTION_LABEL]:
                top[label] += 1
            if event.get("bird_species"):
                bird_species[event["bird_species"]] += 1
            if event.get("cat_name"):
                cat_names[event["cat_name"]] += 1
    return {
        "days": days,
        "total_events": total,
        "per_camera": per_camera,
        "top_objects": top.most_common(8),
        "top_bird_species": bird_species.most_common(8),
        "top_cat_names": cat_names.most_common(8),
    }
