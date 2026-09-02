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


def event_species(event: dict) -> list[str]:
    """Every species name the ORIGINAL event already carries.

    Two places hold one: the event-level ``bird_species`` headline
    (bird_species_rank.py picks it) and the per-detection ``species``
    field. Both are read because they can disagree — a multi-species
    event has one headline and several detections, and "did the replay
    find a name we did not have" has to be asked against everything
    already known, not just the headline.
    """
    names = []
    headline = (event.get("bird_species") or "").strip()
    if headline:
        names.append(headline)
    for det in event.get("detections") or []:
        if not isinstance(det, dict):
            continue
        name = (det.get("species") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def species_diff(before_names, after_species) -> dict:
    """What the replay's species list adds to what the event knew.

    ``gained`` is the honest headline: names the replay produced that
    the event did not already hold. ``kept`` is the confirmation case —
    the replay independently reached a name the event already had,
    which is evidence the stored name was right rather than a new
    finding. Neither is a claim that a name is CORRECT; both are claims
    about what the current models say today.
    """
    known = {n.strip() for n in before_names or [] if n and n.strip()}
    gained, kept = [], []
    for row in after_species or []:
        name = (row.get("species") or "").strip()
        if not name:
            continue
        target = kept if name in known else gained
        if name not in target:
            target.append(name)
    return {
        "before": sorted(known),
        "after": [r.get("species") for r in after_species or [] if r.get("species")],
        "gained": gained,
        "kept": kept,
        "detail": list(after_species or []),
    }


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
    COMPARABLE axis moved, the alert verdict changed, or the replay put
    a species name on the clip that the event did not already have. An
    un-indexed clip contributes no track baseline and therefore cannot
    make the answer "changed" on its own.

    A gained species counts as a change even when every box stayed
    exactly where it was, because it is a different ANSWER about the
    same clip: "ein Vogel" and "eine Amsel" are not the same finding,
    and a report that called that pair identical would hide the thing
    this replay exists to produce.
    """
    before = original_side(event, sidecar_tracks)
    # Both keys hold ONE entry per replayed track, and both sides of a
    # diff have to be in the same shape. `original_side` puts the
    # sidecar's tracks through `track_to_detection` (label + score +
    # bbox), and `replay["detections"]` is that exact collapse of the
    # replay's own tracks — so it is what the track axis compares
    # against. `replay["tracks"]` is the COMPACT form built for the
    # event JSON (`_run._COMPACT_TRACK_KEYS`): no `score`, no `bbox`.
    # Handing that to the diff made `normalise_detection` read every
    # replayed track as score 0.0 with no box, so the track axis of
    # every replay of an indexed clip reported a full-score drop and
    # `changed` could never come back False.
    replayed = replay.get("detections") or []
    after = {"detections": replayed, "tracks": replayed}
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
    species = species_diff(event_species(event), replay.get("species"))
    return {
        "species": species,
        # Whether the replay actually RAN the second stage. A run with
        # classification switched off must not read as "no species
        # found" — an empty list means two different things and the
        # report has to be able to tell them apart.
        "classified": bool(replay.get("classified")),
        "classifier": replay.get("classifier"),
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
        "species_gained": bool(species["gained"]),
        "changed": bool(moved) or alert_changed or bool(species["gained"]),
    }
