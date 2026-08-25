"""The tracker must return the detections it actually matched.

``associate_detections`` runs ``nms_per_label`` at its entry, which
returns a NEW list **regrouped by label** (it buckets into a
``by_label`` dict, then flattens). Every ``di`` produced afterwards
therefore indexes the *post-NMS* list.

Both live callers indexed the *pre-NMS* list with those indices:

  * ``LiveTracker.step``            -> ``detections[di]``
  * ``routes/coral_test_detection`` -> ``raw[di]`` and ``di_to_num[di]``

So the wrong Detection object came back whenever NMS suppressed a box
**or** whenever more than one label was present in the frame — the
latter needs no suppression at all, just interleaved labels, which is
the common case at a feeder (bird + squirrel) or a garden (person +
cat). Downstream that means the second-stage classifiers get handed the
wrong crop, events carry the wrong label/score, and the simulator's
track badges attach to the wrong boxes.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.tracker_core import LiveTracker, TrackerState, associate_detections, nms_per_label


@dataclass
class FakeDet:
    label: str
    score: float
    bbox: tuple[int, int, int, int]


def test_nms_regroups_by_label_even_with_nothing_suppressed():
    """The precondition for the bug — worth pinning explicitly."""
    dets = [
        FakeDet("person", 0.90, (0, 0, 50, 50)),
        FakeDet("bird", 0.88, (500, 500, 550, 550)),
        FakeDet("person", 0.86, (900, 900, 950, 950)),
    ]
    out = nms_per_label(dets, 0.6)
    assert len(out) == 3, "no box overlaps, so nothing may be suppressed"
    assert [d.label for d in out] != [d.label for d in dets], (
        "nms_per_label buckets by label, so the order changes — this is what "
        "made positional indices unsafe"
    )


def test_step_returns_the_objects_it_matched_not_shuffled_ones():
    tracker = LiveTracker(camera_id="cam-test", spawn_default=0.50, iou_threshold=0.3)
    dets = [
        FakeDet("person", 0.90, (0, 0, 50, 50)),
        FakeDet("bird", 0.88, (500, 500, 550, 550)),
        FakeDet("person", 0.86, (900, 900, 950, 950)),
    ]
    survivors = tracker.step(list(dets), t_s=0.0, fps=3.0)

    # Every returned object must be one of the inputs, by identity.
    for s in survivors:
        assert any(s is d for d in dets), "returned a detection that was never passed in"

    # And each returned detection's label must match the track it was
    # associated with — the concrete symptom of the index mix-up.
    assert {(s.label, s.bbox) for s in survivors} <= {(d.label, d.bbox) for d in dets}


def test_associate_returns_detection_objects_paired_with_their_track():
    """The label on the detection must equal the label on its track."""
    state = TrackerState()
    dets = [
        FakeDet("person", 0.90, (0, 0, 50, 50)),
        FakeDet("bird", 0.88, (500, 500, 550, 550)),
        FakeDet("person", 0.86, (900, 900, 950, 950)),
    ]
    matches = associate_detections(state, list(dets), frame_idx=0, t_s=0.0)

    assert matches, "three confirmed detections must spawn tracks"
    for det, track in matches:
        assert not isinstance(det, int), (
            "associate_detections must yield the Detection object, not an index — "
            "indices refer to the post-NMS list and mislead every caller"
        )
        assert det.label == track.label, (
            f"detection {det.label!r} paired with track {track.label!r} — "
            "the index/object mix-up"
        )


def test_suppressed_duplicate_never_comes_back():
    """A box NMS removed must not reappear via a stale index."""
    keep = FakeDet("person", 0.95, (100, 100, 200, 200))
    dupe = FakeDet("person", 0.60, (105, 105, 205, 205))  # high IoU -> suppressed
    far = FakeDet("person", 0.90, (900, 100, 1000, 200))

    tracker = LiveTracker(camera_id="cam-test", spawn_default=0.50, iou_threshold=0.3)
    survivors = tracker.step([keep, dupe, far], t_s=0.0, fps=3.0)

    assert all(s is not dupe for s in survivors), "the NMS-suppressed box came back"


@pytest.mark.parametrize(
    "labels",
    [
        ["bird", "squirrel", "bird"],
        ["person", "cat", "person", "cat"],
        ["squirrel", "bird", "cat", "person"],
    ],
)
def test_label_integrity_across_mixed_frames(labels):
    """Realistic mixed-species frames: a feeder, a garden, a busy scene."""
    dets = [
        FakeDet(lbl, 0.90 - i * 0.01, (i * 400, i * 200, i * 400 + 60, i * 200 + 60))
        for i, lbl in enumerate(labels)
    ]
    state = TrackerState()
    matches = associate_detections(state, list(dets), frame_idx=0, t_s=0.0)
    for det, track in matches:
        assert det.label == track.label
