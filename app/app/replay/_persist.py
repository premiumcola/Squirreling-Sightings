"""Store a replay run under its event without disturbing the event.

A replay is a QUESTION about a clip, not a correction of it. The
event's own ``detections`` are what the camera actually reported and
what every downstream consumer — the Telegram history, the achievement
counters, the sightings registry — has already agreed on. Overwriting
them from a speculative re-run would rewrite history to match a
hypothesis. So the run lands in its own ``replays`` list and nothing
else on the document is touched; applying a result is a separate,
explicit act that this module deliberately does not perform.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ._consts import REPLAY_HISTORY_CAP, REPLAY_SCHEMA

log = logging.getLogger(__name__)


def build_entry(*, settings: dict, replay: dict, comparison: dict) -> dict:
    """One history entry — small enough that five of them under an
    event do not slow the Mediathek's card render.

    Carries the settings fingerprint rather than the settings: the full
    set is already in ``provenance`` for the stored case, and for a
    custom sweep the hash is what identifies the run. Only the
    overridden keys are named, because those are what a later run wants
    to know it is comparing against.
    """
    return {
        "schema": REPLAY_SCHEMA,
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "settings_source": settings.get("source"),
        "settings_basis": settings.get("basis"),
        "settings_hash": settings.get("hash"),
        "overridden": settings.get("overridden") or [],
        "note": settings.get("note"),
        "frames_analysed": replay.get("frames_analysed"),
        "frames_available": replay.get("frames_available"),
        "truncated": replay.get("truncated"),
        "duration_ms": replay.get("duration_ms"),
        "detector": replay.get("detector"),
        # The second stage, stored beside the detector for the same
        # reason: a species list read a month later is only meaningful
        # next to what produced it and on which device.
        "classifier": replay.get("classifier"),
        "classified": replay.get("classified"),
        "frames_classified": replay.get("frames_classified"),
        "crops_classified": replay.get("crops_classified"),
        "classify_truncated": replay.get("classify_truncated"),
        "species": replay.get("species") or [],
        "species_gained": comparison.get("species", {}).get("gained") or [],
        "gates": replay.get("gates"),
        "detections": replay.get("detections") or [],
        "tracks": replay.get("tracks") or [],
        "counts": {
            "detections": comparison["diff"]["detections"]["counts"],
            # None when the clip carried no tracks.json to compare
            # against — a later run must be able to tell "no change"
            # from "no baseline".
            "tracks": (comparison["diff"]["tracks"] or {}).get("counts"),
        },
        "alert": comparison["after"]["alert"],
        "alert_changed": comparison["alert_changed"],
        "changed": comparison["changed"],
    }


def append_replay(store, camera_id: str, event_id: str, entry: dict) -> list:
    """Append ``entry`` to the event's replay history, oldest dropped.

    Read-modify-write against the freshly-loaded document — the same
    idiom `_achievement.update_event_achievement` uses — because
    `EventStore.update_event` replaces the whole file. Building the
    payload from anything cached would silently drop whatever else was
    written to the event since it was read.

    Returns the resulting history. Failure to persist is logged and
    swallowed: the operator asked to SEE a comparison, and losing the
    archive copy is not a reason to fail the answer.
    """
    try:
        ev = store.get_event(camera_id, event_id)
        if not ev:
            return []
        history = list(ev.get("replays") or [])
        history.append(entry)
        history = history[-REPLAY_HISTORY_CAP:]
        ev["replays"] = history
        store.update_event(camera_id, event_id, ev)
        return history
    except Exception as e:
        log.warning("[tracking] cam=%s replay history not stored: %s", camera_id, e)
        return []
