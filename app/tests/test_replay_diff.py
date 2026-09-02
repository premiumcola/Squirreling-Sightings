"""The pure half of the clip-replay feature.

`diff_detections` is what a future optimisation sweep leans on: run one
clip N times with N tunings, diff each result against the baseline, keep
the tuning whose diff reads best. That loop runs with no Flask app, no
camera and no TPU, so every function exercised here is pure and every
test below constructs its inputs as plain dicts.

The property the whole thing rests on is the reconciliation invariant:
every input detection lands in exactly one bucket. If that ever breaks,
a sweep silently loses objects and reports a tuning as better than it is.
"""

from __future__ import annotations

import pytest

from app.replay import bbox_tuple, diff_detections, iou, normalise_detection, track_to_detection


def _det(label, score, box=None):
    d = {"label": label, "score": score}
    if box is not None:
        x1, y1, x2, y2 = box
        d["bbox"] = {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
    return d


def _assert_reconciles(diff):
    """Every input lands in exactly one bucket — the invariant a sweep
    depends on. Stated once, asserted from every test."""
    c = diff["counts"]
    matched = c["class_changed"] + c["score_changed"] + c["unchanged"]
    assert c["appeared"] + matched == c["after"], f"after side does not reconcile: {c}"
    assert c["disappeared"] + matched == c["before"], f"before side does not reconcile: {c}"


# ── bbox normalisation ────────────────────────────────────────────────


def test_bbox_tuple_accepts_all_three_spellings_the_codebase_carries():
    want = (1.0, 2.0, 3.0, 4.0)
    assert bbox_tuple({"x1": 1, "y1": 2, "x2": 3, "y2": 4}) == want
    assert bbox_tuple([1, 2, 3, 4]) == want
    assert bbox_tuple((1, 2, 3, 4)) == want


@pytest.mark.parametrize(
    "bad",
    [None, {}, {"x1": 1, "y1": 2}, [1, 2, 3], "1,2,3,4", {"x1": "a", "y1": 2, "x2": 3, "y2": 4}],
)
def test_bbox_tuple_returns_none_rather_than_raising(bad):
    assert bbox_tuple(bad) is None


def test_iou_is_zero_when_either_box_is_missing():
    box = {"x1": 0, "y1": 0, "x2": 10, "y2": 10}
    assert iou(box, None) == 0.0
    assert iou(None, box) == 0.0


def test_iou_of_identical_boxes_is_one_and_of_disjoint_boxes_is_zero():
    a = {"x1": 0, "y1": 0, "x2": 10, "y2": 10}
    assert iou(a, a) == pytest.approx(1.0)
    assert iou(a, {"x1": 100, "y1": 100, "x2": 110, "y2": 110}) == 0.0


def test_iou_of_half_overlapping_boxes():
    a = {"x1": 0, "y1": 0, "x2": 10, "y2": 10}
    b = {"x1": 5, "y1": 0, "x2": 15, "y2": 10}
    # intersection 50, union 150
    assert iou(a, b) == pytest.approx(50 / 150)


def test_degenerate_box_does_not_divide_by_zero():
    flat = {"x1": 5, "y1": 5, "x2": 5, "y2": 5}
    assert iou(flat, flat) == 0.0


# ── detection normalisation ───────────────────────────────────────────


def test_normalise_detection_survives_a_malformed_archived_row():
    out = normalise_detection({"label": None, "score": "not-a-number", "bbox": "nonsense"})
    assert out == {"label": "?", "score": 0.0, "bbox": None}


def test_normalise_detection_survives_a_non_dict():
    assert normalise_detection(None)["label"] == "?"
    assert normalise_detection("bird")["score"] == 0.0


# ── track collapsing ──────────────────────────────────────────────────


def test_track_collapses_to_its_best_frame():
    track = {
        "label": "bird",
        "best_score": 0.82,
        "best_frame": 50,
        "samples": [
            {"f": 25, "score": 0.4, "bbox": {"x1": 0, "y1": 0, "x2": 5, "y2": 5}},
            {"f": 50, "score": 0.82, "bbox": {"x1": 10, "y1": 10, "x2": 20, "y2": 20}},
        ],
    }
    out = track_to_detection(track)
    assert out == {"label": "bird", "score": 0.82, "bbox": (10.0, 10.0, 20.0, 20.0)}


def test_track_whose_best_frame_is_missing_from_samples_falls_back_to_top_score():
    track = {
        "label": "cat",
        "best_score": 0.7,
        "best_frame": 999,
        "samples": [
            {"f": 1, "score": 0.2, "bbox": {"x1": 0, "y1": 0, "x2": 2, "y2": 2}},
            {"f": 2, "score": 0.7, "bbox": {"x1": 3, "y1": 3, "x2": 9, "y2": 9}},
        ],
    }
    assert track_to_detection(track)["bbox"] == (3.0, 3.0, 9.0, 9.0)


def test_track_with_no_samples_still_yields_a_comparable_detection():
    out = track_to_detection({"label": "person", "best_score": 0.9, "samples": []})
    assert out["label"] == "person" and out["score"] == 0.9 and out["bbox"] is None


# ── the diff ──────────────────────────────────────────────────────────


def test_two_empty_sets_report_no_change():
    diff = diff_detections([], [])
    assert diff["counts"]["before"] == 0 and diff["counts"]["after"] == 0
    _assert_reconciles(diff)


def test_none_inputs_are_treated_as_empty():
    _assert_reconciles(diff_detections(None, None))


def test_identical_sets_are_all_unchanged():
    dets = [_det("bird", 0.7, (0, 0, 10, 10)), _det("cat", 0.6, (50, 50, 60, 60))]
    diff = diff_detections(dets, list(dets))
    assert diff["counts"]["unchanged"] == 2
    assert diff["counts"]["appeared"] == diff["counts"]["disappeared"] == 0
    _assert_reconciles(diff)


def test_an_object_only_in_the_replay_appeared():
    diff = diff_detections([], [_det("squirrel", 0.6, (0, 0, 10, 10))])
    assert diff["counts"]["appeared"] == 1
    assert diff["appeared"][0]["label"] == "squirrel"
    _assert_reconciles(diff)


def test_an_object_only_in_the_original_disappeared():
    diff = diff_detections([_det("squirrel", 0.6, (0, 0, 10, 10))], [])
    assert diff["counts"]["disappeared"] == 1
    assert diff["disappeared"][0]["label"] == "squirrel"
    _assert_reconciles(diff)


def test_same_box_different_label_is_a_class_change_not_a_swap():
    # The reason matching is spatial. A label-first matcher would report
    # this as one disappearance plus one appearance and hide the finding.
    diff = diff_detections(
        [_det("bird", 0.6, (0, 0, 10, 10))],
        [_det("squirrel", 0.8, (1, 1, 11, 11))],
    )
    assert diff["counts"]["class_changed"] == 1
    assert diff["counts"]["appeared"] == 0 and diff["counts"]["disappeared"] == 0
    pair = diff["class_changed"][0]
    assert pair["before"]["label"] == "bird" and pair["after"]["label"] == "squirrel"
    _assert_reconciles(diff)


def test_a_meaningful_confidence_move_is_reported_with_its_delta():
    diff = diff_detections(
        [_det("bird", 0.50, (0, 0, 10, 10))],
        [_det("bird", 0.75, (0, 0, 10, 10))],
    )
    assert diff["counts"]["score_changed"] == 1
    assert diff["score_changed"][0]["delta"] == pytest.approx(0.25)
    _assert_reconciles(diff)


def test_a_confidence_move_within_model_noise_counts_as_unchanged():
    diff = diff_detections(
        [_det("bird", 0.70, (0, 0, 10, 10))],
        [_det("bird", 0.72, (0, 0, 10, 10))],
    )
    assert diff["counts"]["unchanged"] == 1 and diff["counts"]["score_changed"] == 0


def test_the_noise_epsilon_is_tunable_for_a_sweep_that_wants_every_wobble():
    diff = diff_detections(
        [_det("bird", 0.70, (0, 0, 10, 10))],
        [_det("bird", 0.72, (0, 0, 10, 10))],
        score_epsilon=0.001,
    )
    assert diff["counts"]["score_changed"] == 1


def test_a_box_that_moved_too_far_reads_as_appear_plus_disappear():
    diff = diff_detections(
        [_det("bird", 0.6, (0, 0, 10, 10))],
        [_det("bird", 0.6, (500, 500, 510, 510))],
    )
    assert diff["counts"]["appeared"] == 1 and diff["counts"]["disappeared"] == 1
    assert diff["counts"]["unchanged"] == 0
    _assert_reconciles(diff)


def test_a_loose_iou_threshold_pairs_boxes_a_strict_one_splits():
    before = [_det("bird", 0.6, (0, 0, 10, 10))]
    after = [_det("bird", 0.6, (7, 0, 17, 10))]  # iou = 3/17 ≈ 0.18
    assert diff_detections(before, after)["counts"]["disappeared"] == 1
    assert diff_detections(before, after, iou_threshold=0.1)["counts"]["unchanged"] == 1


def test_boxless_sides_fall_back_to_label_matching():
    # Archived events from before boxes were stored must still diff.
    diff = diff_detections([_det("bird", 0.5)], [_det("bird", 0.9)])
    assert diff["counts"]["score_changed"] == 1
    _assert_reconciles(diff)


def test_boxless_detections_of_different_labels_do_not_pair_up():
    diff = diff_detections([_det("bird", 0.5)], [_det("person", 0.9)])
    assert diff["counts"]["appeared"] == 1 and diff["counts"]["disappeared"] == 1
    _assert_reconciles(diff)


def test_each_detection_is_matched_at_most_once():
    # Two replay boxes overlap the single original. Only the better
    # overlap may pair; the other must be reported as newly appeared.
    diff = diff_detections(
        [_det("bird", 0.6, (0, 0, 10, 10))],
        [_det("bird", 0.6, (0, 0, 10, 10)), _det("bird", 0.6, (2, 2, 12, 12))],
    )
    assert diff["counts"]["unchanged"] == 1 and diff["counts"]["appeared"] == 1
    _assert_reconciles(diff)


def test_the_best_overlap_wins_the_pairing():
    diff = diff_detections(
        [_det("bird", 0.6, (0, 0, 10, 10))],
        [_det("cat", 0.6, (4, 4, 14, 14)), _det("dog", 0.6, (0, 0, 10, 10))],
    )
    # The exact-overlap "dog" must take the pair, so the class change is
    # bird -> dog and "cat" is the one left over as appeared.
    assert diff["class_changed"][0]["after"]["label"] == "dog"
    assert diff["appeared"][0]["label"] == "cat"
    _assert_reconciles(diff)


def test_a_realistic_tuning_sweep_result_reconciles():
    before = [
        _det("bird", 0.61, (10, 10, 60, 60)),
        _det("cat", 0.55, (200, 100, 260, 170)),
        _det("person", 0.90, (400, 50, 460, 300)),
    ]
    after = [
        _det("bird", 0.63, (11, 11, 61, 61)),  # unchanged
        _det("squirrel", 0.71, (202, 102, 262, 172)),  # class change
        _det("person", 0.45, (401, 51, 461, 301)),  # score drop
        _det("dog", 0.33, (600, 400, 640, 440)),  # newly appeared
    ]
    diff = diff_detections(before, after)
    c = diff["counts"]
    assert (c["unchanged"], c["class_changed"], c["score_changed"]) == (1, 1, 1)
    assert (c["appeared"], c["disappeared"]) == (1, 0)
    _assert_reconciles(diff)


def test_diff_does_not_mutate_its_inputs():
    before = [_det("bird", 0.6, (0, 0, 10, 10))]
    after = [_det("cat", 0.9, (0, 0, 10, 10))]
    snapshot = (repr(before), repr(after))
    diff_detections(before, after)
    assert (repr(before), repr(after)) == snapshot
