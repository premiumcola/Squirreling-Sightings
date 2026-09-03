"""Re-evaluate every quest against the current event index.

``evaluate_quests`` is idempotent — running it twice in a row produces
the same dict — so the three trigger points (inline after a motion event,
the hourly timer, the manual Re-Eval button) cannot diverge.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from ._catalogue import QUESTS
from ._matching import _all_motion_events_in_window, _event_matches
from ._windows import _quest_id_with_year, _resolve_window, _window_logical_end

log = logging.getLogger("app.quests")


def _frozen_entry(quest_def: dict, qid: str, existing: dict) -> dict:
    """The entry for a quest whose window is not open right now.

    Keeps any prior progress as-is: don't recount, don't reset. Catalogue
    text is refreshed so a wording change reaches an out-of-season quest.
    """
    return {
        **existing,
        "id": qid,
        "title": quest_def["title"],
        "icon": quest_def["icon"],
        "description": quest_def["description"],
        "target": quest_def["target"],
        "progress": existing.get("progress", 0),
        "window": existing.get("window", {"from": None, "to": None}),
        "criteria": quest_def["criteria"],
        "completed_at": existing.get("completed_at"),
        "notified_at": existing.get("notified_at"),
    }


def _stored_window_has_closed(window_name: str, existing: dict, now: datetime) -> bool:
    """True when the STORED entry describes a window that is already over.

    The monthly quests share one id per year, so April's pass would
    otherwise write straight over March's result and the archiver, which
    runs immediately after the evaluator, would never see a closed window
    to move out. The caller leaves such an entry untouched for one pass.

    Deliberately False for a completed entry: ``archive_closed_quests``
    skips anything carrying ``completed_at``, so holding one back would
    freeze it on its old window forever instead of moving it on.
    """
    if existing.get("completed_at"):
        return False
    stored_from_str = (existing.get("window") or {}).get("from")
    try:
        stored_from = datetime.fromisoformat(stored_from_str) if stored_from_str else None
    except ValueError:
        stored_from = None
    stored_end = _window_logical_end(window_name, stored_from)
    return stored_end is not None and now > stored_end


def _progress_for(events: list, criteria: dict) -> int:
    """Count what this quest's criteria are actually asking for."""
    if criteria.get("count_distinct_species"):
        species_seen: set[str] = set()
        for ev in events:
            if not _event_matches(ev, criteria):
                continue
            sp = (ev.get("bird_species") or "").strip()
            if sp:
                species_seen.add(sp.lower())
        return len(species_seen)
    if criteria.get("count_distinct_days"):
        # "Stammgast" — sightings on distinct calendar days within the
        # window. Any event counts (no label filter), but a label filter
        # still applies if present.
        days_seen: set[str] = set()
        has_filter = bool(
            criteria.get("label") or criteria.get("labels") or criteria.get("hour_in")
        )
        for ev in events:
            if has_filter and not _event_matches(ev, criteria):
                continue
            day = (ev.get("time") or "")[:10]  # "YYYY-MM-DD"
            if len(day) == 10:
                days_seen.add(day)
        return len(days_seen)
    return sum(1 for ev in events if _event_matches(ev, criteria))


def _notify_completions(quests: dict, notify: Callable[[dict], None], now: datetime) -> None:
    """Fire the callback for every quest that just completed and has not
    been notified yet.

    ``notified_at`` is marked here so a successful caller-save persists
    it; if the caller crashes before writing, the next eval re-fires.
    """
    for qid in list(quests.keys()):
        q = quests[qid]
        if q.get("completed_at") and not q.get("notified_at"):
            try:
                notify(q)
                q["notified_at"] = now.isoformat(timespec="seconds")
            except Exception as e:
                log.warning("[quests] notify callback failed for %s: %s", qid, e)


def evaluate_quests(
    store,
    achievements_data: dict,
    cam_ids: list[str],
    storage_root: Path,
    now: datetime | None = None,
    notify: Callable[[dict], None] | None = None,
) -> tuple[dict, list[str]]:
    """Re-evaluate every quest against the current event index.

    Args:
        store:               EventStore — used to list motion events.
        achievements_data:   Existing achievements dict (loaded by caller,
                             saved by caller — this fn does NOT touch disk).
        cam_ids:             Every configured camera id; quests aggregate
                             across all of them.
        storage_root:        Path used for weather sightings + history.
        now:                 Override "now" for tests. Defaults to
                             `datetime.now()`.
        notify:              Optional callback(quest_dict) fired exactly
                             once per quest as it transitions to
                             completed (completed_at just set, notified_at
                             still None). The callback is responsible for
                             marking notified_at on the returned dict —
                             we do that here so a caller that fails to
                             persist the dict gets a re-notify on the
                             next eval.

    Returns: (updated_achievements, newly_completed_ids).
    """
    now = now or datetime.now()
    data = dict(achievements_data) if achievements_data else {}
    quests = dict(data.get("quests") or {})
    newly_completed: list[str] = []

    for quest_def in QUESTS:
        window_name = quest_def["window"]
        start_dt, end_dt = _resolve_window(window_name, now)
        qid = _quest_id_with_year(quest_def["id"], now, window_name)
        existing = quests.get(qid) or {}
        if start_dt is None or end_dt is None:
            quests[qid] = _frozen_entry(quest_def, qid, existing)
            continue
        if _stored_window_has_closed(window_name, existing, now):
            quests[qid] = existing
            continue

        criteria = quest_def["criteria"]
        events = _all_motion_events_in_window(store, start_dt, end_dt, cam_ids)
        progress = min(_progress_for(events, criteria), quest_def["target"])

        completed_at = existing.get("completed_at")
        if not completed_at and progress >= quest_def["target"]:
            completed_at = now.isoformat(timespec="seconds")
            newly_completed.append(qid)

        quests[qid] = {
            "id": qid,
            "title": quest_def["title"],
            "icon": quest_def["icon"],
            "description": quest_def["description"],
            "target": quest_def["target"],
            "progress": progress,
            "window": {
                "from": start_dt.isoformat(timespec="seconds"),
                "to": end_dt.isoformat(timespec="seconds"),
            },
            "criteria": criteria,
            "completed_at": completed_at,
            "notified_at": existing.get("notified_at"),
        }

    if notify:
        _notify_completions(quests, notify, now)

    data["quests"] = quests
    return data, newly_completed
