"""SMALL-1 · the ROI mode has to actually magnify.

`tiled_detect(mode="roi")` crops the motion box with a 25 % pad and hands
the crop to the detector, which letterboxes it into the model's square
input. Whether that is a 8x zoom or no zoom at all depends entirely on how
large the motion box happened to be — and the number appeared nowhere, so
the mode the whole small-object category rests on was neither visible nor
tunable.

Magnification here is linear gain *relative to the full-frame pass*: both
passes letterbox into the same model input, so it is the ratio of the
longer edges. That is the same definition the existing tiling suite uses
for the 2x2 grid (`2560 / tile_width` ~ 1.74x).
"""

from __future__ import annotations

import numpy as np
import pytest

from app.detection_tiling import (
    magnification,
    normalise_mode,
    split_for_magnification,
    tiled_detect,
)

FRAME_W, FRAME_H = 2560, 1440


class _Det:
    def __init__(self, label, score, bbox):
        self.label = label
        self.score = score
        self.bbox = bbox


class _FakeDetector:
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
    return np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)


# ── magnification ─────────────────────────────────────────────────────


def test_a_tight_crop_magnifies_a_lot():
    assert magnification(FRAME_W, FRAME_H, (1142, 642, 1458, 918)) == pytest.approx(8.1, abs=0.1)


def test_a_crop_that_spans_the_frame_magnifies_not_at_all():
    assert magnification(FRAME_W, FRAME_H, (0, 0, FRAME_W, FRAME_H)) == pytest.approx(1.0)


# ── split_for_magnification ───────────────────────────────────────────


def test_a_crop_that_already_zooms_enough_is_left_alone():
    region = (1000, 500, 1800, 1100)  # 800x600 → 3.2x
    assert split_for_magnification(region, FRAME_W, FRAME_H, 1.5) == [region]


def test_a_crop_that_does_not_zoom_is_split_until_it_does():
    region = (242, 0, 2358, 1440)  # 2116x1440 → 1.21x, below the floor
    parts = split_for_magnification(region, FRAME_W, FRAME_H, 1.5)

    assert len(parts) > 1
    for p in parts:
        assert magnification(FRAME_W, FRAME_H, p) >= 1.5


def test_the_split_stays_inside_the_original_crop():
    region = (242, 0, 2358, 1440)
    for x1, y1, x2, y2 in split_for_magnification(region, FRAME_W, FRAME_H, 1.5):
        assert region[0] <= x1 < x2 <= region[2]
        assert region[1] <= y1 < y2 <= region[3]


def test_the_number_of_parts_is_capped():
    """Each part is a CPU inference. An unbounded split would make the
    rescue cost unpredictable, which is worse than a smaller zoom."""
    region = (0, 0, FRAME_W, FRAME_H)
    assert len(split_for_magnification(region, FRAME_W, FRAME_H, 8.0)) <= 4


# ── tiled_detect ──────────────────────────────────────────────────────


def test_roi_reports_its_magnification(frame):
    _merged, diag = tiled_detect(
        frame=frame, detector=_FakeDetector(), mode="roi", motion_box=(1200, 700, 200, 160)
    )

    assert diag["magnification"] == [pytest.approx(8.1, abs=0.1)]
    assert diag["crop_px"] == [(316, 276)]
    assert diag["min_magnification"] == 1.5


def test_a_wide_motion_box_is_split_instead_of_wasting_one_flat_pass(frame):
    """The acceptance case. A motion box spanning most of the frame used to
    produce ONE crop at 1.21x — an inference that saw the subject at the
    same resolution the full-frame pass already did, and could not possibly
    find anything new."""
    det = _FakeDetector()
    _merged, diag = tiled_detect(det, frame, "roi", motion_box=(600, 300, 1400, 900))

    assert diag["tiles"] > 1, "one flat crop here is a wasted inference"
    assert len(det.calls) == 1 + diag["tiles"], "full frame plus one call per part"
    for m in diag["magnification"]:
        assert m >= 1.5


def test_a_small_subject_is_not_split(frame):
    """The case that matters at the feeder must stay a single tight crop."""
    det = _FakeDetector()
    _merged, diag = tiled_detect(det, frame, "roi", motion_box=(1200, 700, 200, 160))

    assert diag["tiles"] == 1
    assert len(det.calls) == 2


def test_a_split_subject_is_not_double_counted(frame):
    """Two parts that cut the same animal must merge back to one box.

    Splitting a crop creates new seams, and a seam is where a naive tiling
    implementation reports one squirrel twice. The parts of the crop for
    this motion box overlap in x 1142..1458 and y 612..828; a subject at
    frame (1200, 650)-(1400, 800) therefore falls inside two of them.
    """
    det = _FakeDetector(
        per_call=[
            [],  # full frame: nothing
            [_Det("squirrel", 0.80, (958, 650, 1158, 800))],  # part 1, local coords
            [_Det("squirrel", 0.60, (58, 650, 258, 800))],  # part 2, same animal
            [],
            [],
        ]
    )
    merged, diag = tiled_detect(det, frame, "roi", motion_box=(600, 300, 1400, 900))

    assert diag["raw"] == 2
    assert len(merged) == 1, "the seam duplicate must collapse"
    assert merged[0].score == 0.80
    assert merged[0].bbox == (1200, 650, 1400, 800), "and it must be in frame coordinates"


def test_a_supplied_full_frame_pass_is_not_repeated(frame):
    """The live loop already ran the full-frame detect. Running it again
    inside the rescue is a second CPU inference for an identical result —
    with the TPU down that is the largest single cost in this path."""
    already = [_Det("cat", 0.30, (100, 100, 200, 200))]
    det = _FakeDetector()

    merged, _diag = tiled_detect(
        det, frame, "roi", motion_box=(1200, 700, 200, 160), full_dets=already
    )

    assert len(det.calls) == 1, "only the ROI crop, no repeated full-frame pass"
    assert det.calls[0] == (276, 316), "and the one call is the crop"
    assert merged[0] is already[0], "the caller's detections travel through unchanged"


# ── normalise_mode ────────────────────────────────────────────────────


def test_unset_stays_off():
    assert normalise_mode(None) == "off"
    assert normalise_mode("") == "off"
    assert normalise_mode("  OFF ") == "off"


def test_a_typo_no_longer_disables_the_rescue_silently(caplog):
    """`roi_mode: "ROI "` or `"2×2"` used to read exactly like `off`: the
    rescue was disabled and nothing said so."""
    with caplog.at_level("WARNING"):
        assert normalise_mode("2×2") == "roi"

    assert "unknown roi_mode" in caplog.text


def test_valid_modes_pass_through_untouched():
    for mode in ("roi", "2x2", "3x3"):
        assert normalise_mode(mode.upper()) == mode
