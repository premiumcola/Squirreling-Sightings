"""Fold per-event replay comparisons into the one report the operator reads.

Pure — dicts in, dicts out. No store, no filesystem, no detector — so
the arithmetic that answers "did anything actually get better" is
testable without a TPU, without video and without a storage root.

Consumes `replay/_report.py::build_comparison` output verbatim; every
key read here is one that function documents.

ON THE TWO COUNTS THAT LOOK ALIKE BUT ARE NOT
---------------------------------------------
`birds_gained` compares two DIFFERENT kinds of number unless the clip
had a tracks.json sidecar:

  * the replay side is always a whole-clip track count — the replay
    walks up to REPLAY_MAX_SAMPLES frames and reports the tracks it
    accumulated;
  * the original side is a whole-clip track count ONLY when a sidecar
    existed (`tracks_comparable`). Otherwise it falls back to the
    event's own `detections`, which camera_runtime/_loop_stages.py:127
    froze from the SINGLE frame where recording started.

A gain measured against that single frame is therefore expected and
says little. A gain measured track-against-track is a real finding.
Both are counted, and `basis` on every row says which one it was, so
the report can lead with the honest number (`birds_gained_strict`)
instead of the flattering one.

ON SPECIES
----------
The replay does NOT classify species — `replay/_run.py` runs detector →
tracker → clean → payload, and `_diff.py::track_to_detection` collapses
a track to `{label, score, bbox}`. There is no species in a replay
result and this module must not pretend otherwise. What it can report
is `species_nameable`: the replay sees birds in a clip that carries no
`bird_species` yet, i.e. a clip the EXISTING "Vogelarten nachträglich
bestimmen" sweep (bird_species_backfill.py) could now put a name on.
That is a pointer to work, not a claim that a name was won.
"""

from __future__ import annotations

from ._consts import BIRD_LABELS, MAX_DETAIL_ROWS, MAX_MOVERS


def count_birds(items) -> int:
    """Bird-labelled entries in a normalised detection/track list."""
    return sum(1 for d in items or [] if (d.get("label") or "") in BIRD_LABELS)


#: Diff buckets whose entries carry BOTH sides of a matched pair. Every
#: original-side item lands in exactly one of these or in `disappeared`
#: — the reconciliation invariant `_diff.py::diff_detections` documents
#: and tests.
_PAIRED_BUCKETS = ("class_changed", "score_changed", "unchanged")


def _before_side(diff: dict):
    """The original-side entries of a diff, reassembled.

    `build_comparison` publishes the original TRACK list only as a diff,
    never as a list of its own (`before` carries `track_count`, not
    `tracks`). Counting birds on that side therefore means walking the
    buckets rather than reading a list.
    """
    yield from (diff or {}).get("disappeared") or []
    for bucket in _PAIRED_BUCKETS:
        for pair in (diff or {}).get(bucket) or []:
            yield pair.get("before") or {}


def _before_birds(comparison: dict) -> tuple[int, str]:
    """``(count, basis)`` for the original side — tracks when a sidecar
    gave us a whole-clip baseline, else the event's frozen detections."""
    track_diff = (comparison.get("diff") or {}).get("tracks")
    if comparison.get("tracks_comparable") and track_diff is not None:
        return count_birds(list(_before_side(track_diff))), "tracks"
    return count_birds((comparison.get("before") or {}).get("detections")), "detections"


def _biggest_move(diff: dict) -> float:
    """Largest absolute score delta among matched detections, 0.0 when
    nothing moved."""
    moves = (diff or {}).get("score_changed") or []
    best = 0.0
    for m in moves:
        delta = abs(float(m.get("delta") or 0.0))
        if delta > best:
            best = delta
    return round(best, 4)


def summarise_event(camera_id: str, event_id: str, event: dict, comparison: dict) -> dict:
    """One report row for one replayed clip. Pure."""
    det_diff = (comparison.get("diff") or {}).get("detections") or {}
    counts = det_diff.get("counts") or {}
    before_birds, basis = _before_birds(comparison)
    after_birds = count_birds((comparison.get("after") or {}).get("detections"))
    species = (event.get("bird_species") or "").strip() or None
    return {
        "camera_id": camera_id,
        "event_id": event_id,
        "changed": bool(comparison.get("changed")),
        "basis": basis,
        "birds_before": before_birds,
        "birds_after": after_birds,
        "birds_gained": max(0, after_birds - before_birds),
        "birds_lost": max(0, before_birds - after_birds),
        "appeared": int(counts.get("appeared") or 0),
        "disappeared": int(counts.get("disappeared") or 0),
        "alert_changed": bool(comparison.get("alert_changed")),
        "species_before": species,
        # "the replay sees a bird here and the event has no name for it"
        "species_nameable": bool(after_birds and not species),
        "top_move": _biggest_move(det_diff),
    }


def movers_from(camera_id: str, event_id: str, comparison: dict) -> list[dict]:
    """Flatten one comparison's score movements into mover rows."""
    det_diff = (comparison.get("diff") or {}).get("detections") or {}
    out: list[dict] = []
    for m in det_diff.get("score_changed") or []:
        after = m.get("after") or {}
        before = m.get("before") or {}
        out.append(
            {
                "camera_id": camera_id,
                "event_id": event_id,
                "label": after.get("label") or before.get("label") or "",
                "before": float(before.get("score") or 0.0),
                "after": float(after.get("score") or 0.0),
                "delta": round(float(m.get("delta") or 0.0), 4),
            }
        )
    return out


def fold(rows: list[dict], movers: list[dict], *, errors: int = 0) -> dict:
    """The aggregate the dashboard shows. Pure.

    `birds_gained_strict` is the honest headline: clips where a
    whole-clip track baseline existed AND the replay still found more
    birds. `birds_gained_events` includes the snapshot-baseline clips —
    useful, but inflated by construction (see the module docstring).
    """
    ranked = sorted(movers, key=lambda m: abs(m["delta"]), reverse=True)[:MAX_MOVERS]
    return {
        "examined": len(rows),
        "errors": int(errors),
        "changed": sum(1 for r in rows if r["changed"]),
        "unchanged": sum(1 for r in rows if not r["changed"]),
        "birds_gained_events": sum(1 for r in rows if r["birds_gained"] > 0),
        "birds_gained_strict": sum(
            1 for r in rows if r["birds_gained"] > 0 and r["basis"] == "tracks"
        ),
        "birds_lost_events": sum(1 for r in rows if r["birds_lost"] > 0),
        "lost_events": sum(1 for r in rows if r["disappeared"] > 0),
        "alert_changed_events": sum(1 for r in rows if r["alert_changed"]),
        "species_nameable_events": sum(1 for r in rows if r["species_nameable"]),
        "tracks_comparable_events": sum(1 for r in rows if r["basis"] == "tracks"),
        "movers": ranked,
        "detail": rows[:MAX_DETAIL_ROWS],
        "detail_truncated": len(rows) > MAX_DETAIL_ROWS,
    }
