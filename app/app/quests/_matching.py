"""Event selection: which stored motion events count towards a quest."""

from __future__ import annotations

import logging
from datetime import datetime

log = logging.getLogger("app.quests")


def _event_matches(ev: dict, criteria: dict) -> bool:
    """Does a motion-event dict match the quest's criteria?

    Supported criteria keys:
      - "label":  single label that must appear in event.labels
      - "labels": list of labels — match if ANY appears in event.labels
      - "hour_in": list of ints (0–23) — match only when the event hour
                   is one of them
      - "event_type": handled separately (in evaluator) — never reaches
                      this matcher
      - "count_distinct_species": handled separately

    `criteria` keys not listed here are ignored.
    """
    ev_labels = set(ev.get("labels", []) or [])
    if "label" in criteria:
        if criteria["label"] not in ev_labels:
            return False
    if "labels" in criteria:
        wanted = set(criteria["labels"] or [])
        if not (wanted & ev_labels):
            return False
    if "hour_in" in criteria:
        try:
            ev_hour = int((ev.get("time") or "")[11:13])
        except ValueError:
            return False
        if ev_hour not in criteria["hour_in"]:
            return False
    return True


def _all_motion_events_in_window(
    store, start_dt: datetime, end_dt: datetime, cam_ids: list[str]
) -> list[dict]:
    """Pull every motion event across all cameras within the window.

    Done once per evaluation pass and reused for every quest, so the
    expensive disk walk happens at most once per call. limit=10000 is a
    safety bound — even on a busy multi-cam install we never approach
    that within a single year window.
    """
    out: list[dict] = []
    start_iso = start_dt.isoformat(timespec="seconds")
    end_iso = end_dt.isoformat(timespec="seconds")
    for cam_id in cam_ids:
        try:
            evs = store.list_events(cam_id, start=start_iso, end=end_iso, limit=10000)
        except Exception as e:
            log.debug("[quests] list_events(%s) failed: %s", cam_id, e)
            continue
        out.extend(evs)
    return out
