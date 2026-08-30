"""Tiling / ROI detection — coordinate math and merge behaviour.

`detection_tiling.py` is pure coordinate transformation and had no tests
at all, while being the mechanism the whole small-object plan rests on.
The two things that break in every naive tiling implementation are
covered here explicitly: boxes that never get mapped back out of tile
space, and a subject straddling a tile seam being counted twice.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.bbox_utils import containment, iou
from app.detection_tiling import (
    MERGE_CONTAIN,
    MERGE_IOU,
    detect_region,
    nms_merge,
    tile_regions,
    tiled_detect,
)


class _Det:
    def __init__(self, label, score, bbox):
        self.label = label
        self.score = score
        self.bbox = bbox


class _FakeDetector:
    """Returns a fixed box per call, recording what it was asked to look at."""

    def __init__(self, per_call=None):
        self.calls = []
        self._per_call = per_call or []

    def detect_frame_raw(self, frame, threshold=0.0):
        self.calls.append(frame.shape[:2])
        idx = len(self.calls) - 1
        if idx < len(self._per_call):
            return list(self._per_call[idx])
        return []


@pytest.fixture
def frame():
    return np.zeros((1440, 2560, 3), dtype=np.uint8)


# ── tile_regions ──────────────────────────────────────────────────────


@pytest.mark.parametrize("gx,gy,expected", [(2, 2, 4), (3, 3, 9), (1, 1, 1)])
def test_tile_count(gx, gy, expected):
    assert len(tile_regions(2560, 1440, gx, gy)) == expected


def test_tiles_stay_inside_the_frame():
    for x1, y1, x2, y2 in tile_regions(2560, 1440, 3, 3):
        assert 0 <= x1 < x2 <= 2560
        assert 0 <= y1 < y2 <= 1440


def test_tiles_overlap_so_a_seam_subject_is_not_split():
    """Without overlap, an animal on a tile border is cut in half and
    neither half looks like an animal."""
    regions = tile_regions(2560, 1440, 2, 2)
    top_left, top_right = regions[0], regions[1]
    assert top_left[2] > top_right[0], "adjacent tiles must overlap horizontally"


def test_tiles_cover_the_whole_frame():
    regions = tile_regions(2560, 1440, 2, 2)
    assert min(r[0] for r in regions) == 0
    assert min(r[1] for r in regions) == 0
    assert max(r[2] for r in regions) == 2560
    assert max(r[3] for r in regions) == 1440


def test_magnification_is_modest_for_a_grid():
    """Why the roadmap prefers roi over 2x2/3x3: on a 2560x1440 frame a
    2x2 tile is only ~1.7x larger relative to the model input."""
    x1, y1, x2, y2 = tile_regions(2560, 1440, 2, 2)[0]
    linear_gain = 2560 / (x2 - x1)
    assert 1.5 < linear_gain < 2.0


# ── detect_region ─────────────────────────────────────────────────────


def test_region_boxes_are_mapped_back_to_frame_coordinates(frame):
    """The classic tiling bug: boxes returned in tile space."""
    det = _FakeDetector(per_call=[[_Det("squirrel", 0.8, (10, 20, 60, 80))]])
    out = detect_region(det, frame, (1000, 500, 1400, 900), 0.2)

    assert out[0].bbox == (1010, 520, 1060, 580), "bbox must be offset by the region origin"


def test_empty_region_yields_nothing(frame):
    det = _FakeDetector(per_call=[[_Det("x", 0.9, (0, 0, 5, 5))]])
    assert detect_region(det, frame, (100, 100, 100, 100), 0.2) == []


def test_detector_sees_only_the_crop(frame):
    det = _FakeDetector()
    detect_region(det, frame, (0, 0, 640, 360), 0.2)
    assert det.calls == [(360, 640)], "the detector must receive the crop, not the frame"


# ── nms_merge ─────────────────────────────────────────────────────────


def test_seam_duplicate_collapses_to_the_best_box():
    a = _Det("squirrel", 0.91, (100, 100, 200, 200))
    b = _Det("squirrel", 0.55, (105, 105, 205, 205))
    kept = nms_merge([a, b])

    assert len(kept) == 1
    assert kept[0].score == 0.91, "the higher-scoring box must survive"


def test_distinct_subjects_both_survive():
    a = _Det("squirrel", 0.9, (100, 100, 200, 200))
    b = _Det("squirrel", 0.8, (900, 100, 1000, 200))
    assert len(nms_merge([a, b])) == 2


def test_different_labels_on_the_same_patch_are_kept():
    """Cross-label suppression is deliberately NOT done here — the
    wildlife stage decides between cat and squirrel later."""
    a = _Det("cat", 0.9, (100, 100, 200, 200))
    b = _Det("squirrel", 0.85, (102, 102, 202, 202))
    assert len(nms_merge([a, b])) == 2


def test_merge_of_nothing_is_nothing():
    assert nms_merge([]) == []


# ── nms_merge · the containment gate ──────────────────────────────────
#
# The field case, on "Squirrel Town 'Nut Bar'" (3840x2160, roi_mode 2x2):
# ONE person reported as two stacked `person` boxes, every frame. The
# 2x2 tiles are (0,0,2208,1242) / (1632,0,3840,1242) / (0,918,2208,2160)
# / (1632,918,3840,2160) — a standing person crosses the horizontal seam
# band y in [918, 1242], so the top tile reports head+torso while the
# full-frame pass reports the whole body.


def test_real_seam_split_person_collapses_to_one():
    """The reported bug: a 2x2 tile seam cuts a standing person in half.

    Geometry from the operator's frame — partial 876x645, full 1148x1200,
    overlap 324k px^2. The two passes disagree on where the subject starts
    (the tile pass runs at ~1.74x the full pass's effective resolution and
    draws the raised arm the letterboxed full-frame pass smeared away), so
    the partial is NOT a clean subset of the full box.

    IoU = 0.20, which is why the old IoU-only gate kept both. Containment
    = 0.57 — plainly one subject.
    """
    partial = (1144, 205, 2020, 850)  # 876 x 645, head+torso, top tile
    full = (1300, 400, 2448, 1600)  # 1148 x 1200, whole body, full frame

    assert iou(partial, full) < MERGE_IOU, "must not be an IoU catch — that is the bug"
    assert containment(partial, full) >= MERGE_CONTAIN

    kept = nms_merge([_Det("person", 0.77, partial), _Det("person", 0.91, full)])

    assert len(kept) == 1, "one person must not be reported as two boxes"
    assert kept[0].score == 0.91, "the higher-scoring box must survive"


def test_two_people_one_behind_the_other_both_survive():
    """Two adults at the feeder, one standing a step behind and to the
    right of the other so their shoulders overlap in image space.

    Safe on BOTH axes by construction: containment 0.29 is far under the
    0.50 gate, and the boxes are comparable in size (area ratio 0.81), so
    the size guard keeps the containment gate off entirely.
    """
    front = (1000, 500, 1560, 1900)  # 560 x 1400
    behind = (1420, 540, 1900, 1860)  # 480 x 1320

    assert containment(front, behind) < MERGE_CONTAIN

    kept = nms_merge([_Det("person", 0.88, front), _Det("person", 0.71, behind)])
    assert len(kept) == 2


def test_comparable_size_boxes_are_never_merged_by_containment():
    """Two squirrels at one feeder — the case the size guard exists for.

    Equal-sized boxes overlapping at containment 0.55 (over the 0.50 gate)
    but IoU 0.38 (under the 0.45 gate). Without the guard the containment
    gate would have quietly lowered the same-label bar for comparable
    subjects from IoU 0.45 to 0.33, swallowing one of the two animals.
    """
    a = (1200, 900, 1600, 1300)
    b = (1380, 900, 1780, 1300)

    assert containment(a, b) > MERGE_CONTAIN, "containment alone would merge these"
    assert iou(a, b) < MERGE_IOU, "IoU alone would not"

    kept = nms_merge([_Det("squirrel", 0.83, a), _Det("squirrel", 0.79, b)])
    assert len(kept) == 2, "the size guard must protect two comparable subjects"


def test_containment_gate_brackets_its_threshold():
    """Pin MERGE_CONTAIN: 0.60 inside merges, 0.40 inside does not.

    Both pairs are small-inside-large at area ratio 0.225 — under the size
    guard, so the containment gate is live for both — and both sit well
    under the IoU gate, so only MERGE_CONTAIN decides. A future change to
    the constant moves one of these.
    """
    assert MERGE_CONTAIN == 0.50

    big = (1000, 400, 1800, 1600)  # 800 x 1200
    inside_60 = (1200, 1240, 1560, 1840)  # 360 x 600, containment 0.60
    inside_40 = (1200, 1360, 1560, 1960)  # 360 x 600, containment 0.40

    assert containment(inside_60, big) == pytest.approx(0.60)
    assert containment(inside_40, big) == pytest.approx(0.40)
    assert iou(inside_60, big) < MERGE_IOU and iou(inside_40, big) < MERGE_IOU

    assert len(nms_merge([_Det("person", 0.9, big), _Det("person", 0.6, inside_60)])) == 1
    assert len(nms_merge([_Det("person", 0.9, big), _Det("person", 0.6, inside_40)])) == 2


# ── tiled_detect ──────────────────────────────────────────────────────


def test_mode_off_runs_only_the_full_frame(frame):
    det = _FakeDetector()
    merged, diag = tiled_detect(det, frame, "off")

    assert len(det.calls) == 1
    assert diag["tiles"] == 0
    assert diag["mode"] == "off"
    assert merged == []


def test_2x2_runs_full_frame_plus_four_tiles(frame):
    det = _FakeDetector()
    _merged, diag = tiled_detect(det, frame, "2x2")

    assert diag["tiles"] == 4
    assert len(det.calls) == 5, "one full-frame pass plus one per tile"


def test_roi_uses_the_motion_box(frame):
    det = _FakeDetector()
    _merged, diag = tiled_detect(det, frame, "roi", motion_box=(1200, 700, 200, 160))

    assert diag["tiles"] == 1
    assert len(det.calls) == 2
    # The ROI crop must be far smaller than the frame — that is the zoom.
    roi_shape = det.calls[1]
    assert roi_shape[0] < 500 and roi_shape[1] < 700


def test_roi_without_motion_box_degrades_to_full_frame_only(frame):
    det = _FakeDetector()
    _merged, diag = tiled_detect(det, frame, "roi", motion_box=None)

    assert diag["tiles"] == 0
    assert len(det.calls) == 1


def test_tile_hit_recovers_what_the_full_frame_missed(frame):
    """The reason tiling exists: full frame sees nothing, a tile sees it."""
    det = _FakeDetector(
        per_call=[
            [],  # full frame: nothing
            [_Det("squirrel", 0.76, (10, 10, 60, 60))],  # first tile: found it
        ]
    )
    merged, diag = tiled_detect(det, frame, "roi", motion_box=(1200, 700, 200, 160))

    assert len(merged) == 1
    assert merged[0].label == "squirrel"
    assert diag["tile_hits"] == [1]
    assert diag["raw"] == 1 and diag["merged"] == 1


def test_diag_counts_raw_before_and_merged_after(frame):
    """A seam duplicate must show up as raw=2, merged=1."""
    dup = (1210, 710, 1260, 760)
    det = _FakeDetector(
        per_call=[
            [_Det("squirrel", 0.80, dup)],
            [_Det("squirrel", 0.60, (5, 5, 55, 55))],
        ]
    )
    _merged, diag = tiled_detect(det, frame, "roi", motion_box=(1200, 700, 200, 160))

    assert diag["raw"] == 2
    assert diag["merged"] <= diag["raw"]
