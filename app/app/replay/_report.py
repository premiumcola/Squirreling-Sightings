"""Assemble the before/after comparison. Pure — no I/O, no detector.

The comparison IS the feature. Storing what a clip was recorded with is
only useful if you can ask "and what would a different setting have
made of it?", and that question is answered by putting the original
result and the replay result side by side and naming the difference.

Two axes are compared because the pipeline has two outputs and they
fail differently:

  * detections — what the model saw. Moves when a confidence threshold
    or the object filter moves.
  * tracks — what survived association and the cleanup sweeps. Moves
    when a spawn/IoU/grace knob moves, and can change while detections
    stay identical.

A tuning change that alters one and not the other is the interesting
case, and a single merged number would hide it.
"""

from __future__ import annotations

from ._alarm import alert_preview
from ._diff import diff_detections, normalise_detection, track_to_detection


def _labels(items) -> list[str]:
    return [str(d.get("label")) for d in (items or []) if isinstance(d, dict) and d.get("label")]


def _moved(diff: dict) -> int:
    """How many objects one axis reports as anything other than
    unchanged. The number behind the ``changed`` boolean."""
    c = diff["counts"]
    return c["appeared"] + c["disappeared"] + c["class_changed"] + c["score_changed"]


def original_side(event: dict, sidecar_tracks) -> dict:
    """What the event already holds, in the replay's shape.

    ``detections`` lives on the event JSON; ``tracks`` only ever lived
    in the ``*.tracks.json`` sidecar. Pass ``None`` for a clip that was
    never indexed — that is NOT the same as a clip indexed to zero
    tracks, and conflating them would make every replay of an
    un-indexed clip announce that its tracks had "appeared", which is
    an artefact of the missing baseline rather than anything the
    settings did.
    """
    detections = [normalise_detection(d) for d in (event.get("detections") or [])]
    if sidecar_tracks is None:
        return {"detections": detections, "tracks": None, "track_count": None}
    tracks = list(sidecar_tracks)
    return {
        "detections": detections,
        "tracks": [track_to_detection(t) for t in tracks],
        "track_count": len(tracks),
    }


def build_comparison(
    *,
    event: dict,
    sidecar_tracks,
    replay: dict,
    alarm_profile,
) -> dict:
    """The whole answer: both sides, both diffs, and the alert verdict.

    ``changed`` is the one boolean the UI needs to decide between "das
    Ergebnis ist identisch" and rendering the detail — true when a
    COMPARABLE axis moved or the alert verdict changed. An un-indexed
    clip contributes no track baseline and therefore cannot make the
    answer "changed" on its own.
    """
    before = original_side(event, sidecar_tracks)
    after = {
        "detections": replay.get("detections") or [],
        "tracks": replay.get("tracks") or [],
    }
    det_diff = diff_detections(before["detections"], after["detections"])
    tracks_comparable = before["tracks"] is not None
    trk_diff = diff_detections(before["tracks"], after["tracks"]) if tracks_comparable else None

    alert_before = alert_preview(alarm_profile, _labels(before["detections"]))
    alert_after = alert_preview(alarm_profile, _labels(after["detections"]))
    # Level, not just notify: a drop from "alarm" to "info" leaves
    # notify True on both sides while being exactly the kind of
    # regression an operator tuning thresholds needs to see.
    alert_changed = (
        alert_before["level"] != alert_after["level"]
        or alert_before["notify"] != alert_after["notify"]
    )

    moved = _moved(det_diff) + (_moved(trk_diff) if trk_diff else 0)
    return {
        "before": {
            "detections": before["detections"],
            "detection_count": len(before["detections"]),
            "track_count": before["track_count"],
            "alert": alert_before,
        },
        "after": {
            "detections": after["detections"],
            "detection_count": len(after["detections"]),
            "track_count": len(after["tracks"]),
            "alert": alert_after,
        },
        "diff": {"detections": det_diff, "tracks": trk_diff},
        "tracks_comparable": tracks_comparable,
        "alert_changed": alert_changed,
        "changed": bool(moved) or alert_changed,
    }
