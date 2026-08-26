"""Wildlife second stage: crop selection and gating.

The behavioural change under test: the classifier used to receive the
FULL frame. `WildlifeClassifier` wraps an ImageNet MobileNet — a
whole-image classifier that assumes one dominant subject. On a
2560x1440 feeder scene a squirrel covers a few percent of the pixels,
and squeezing that into 224x224 buries it in background. The offline
Coral test panel always cropped to a bbox first, which is why its
accuracy never transferred to the live path.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.camera_runtime._wildlife_stage import WildlifeStageMixin


class _Stage(WildlifeStageMixin):
    """Bare harness — the crop/gate helpers only touch these attrs."""

    def __init__(self, wildlife_available=True):
        self.camera_id = "cam-test"
        self.cfg = {}

        class _WL:
            available = wildlife_available

        self.wildlife_classifier = _WL()


class _Det:
    def __init__(self, label, score):
        self.label = label
        self.score = score


@pytest.fixture
def frame():
    # 1440x2560 (h, w) — the real Reolink main-stream shape.
    return np.zeros((1440, 2560, 3), dtype=np.uint8)


# ── crop selection ────────────────────────────────────────────────────


def test_motion_box_yields_a_real_crop(frame):
    stage = _Stage()
    crop, box = stage._wildlife_crop(frame, (1200, 700, 200, 160))

    assert box is not None
    assert (
        crop.shape[0] < frame.shape[0] and crop.shape[1] < frame.shape[1]
    ), "a motion box must produce a crop, not the whole frame — that was the bug"


def test_crop_covers_the_motion_box_with_padding(frame):
    stage = _Stage()
    mx, my, mw, mh = 1200, 700, 200, 160
    _crop, (x1, y1, x2, y2) = stage._wildlife_crop(frame, (mx, my, mw, mh))

    assert x1 <= mx and y1 <= my, "crop must not clip the motion box"
    assert x2 >= mx + mw and y2 >= my + mh
    assert (x2 - x1) > mw and (y2 - y1) > mh, "padding must widen the box"


def test_no_motion_box_falls_back_to_full_frame(frame):
    """Previous behaviour must be preserved where we have no better guess."""
    stage = _Stage()
    crop, box = stage._wildlife_crop(frame, None)

    assert box is None
    assert crop.shape == frame.shape


@pytest.mark.parametrize("bad", [(10, 10, 0, 50), (10, 10, 50, 0), (0, 0, -5, -5), ()])
def test_degenerate_boxes_fall_back_to_full_frame(frame, bad):
    stage = _Stage()
    crop, box = stage._wildlife_crop(frame, bad)
    assert box is None
    assert crop.shape == frame.shape


def test_tiny_box_is_grown_to_a_usable_minimum(frame):
    """A 12px blob upscaled to 224x224 is mush — context has to come along."""
    stage = _Stage()
    _crop, (x1, y1, x2, y2) = stage._wildlife_crop(frame, (1000, 500, 12, 12))

    assert (x2 - x1) >= 96 and (y2 - y1) >= 96


def test_crop_is_clamped_to_frame_bounds(frame):
    """A box at the very corner must not produce negative or OOB indices."""
    stage = _Stage()
    crop, (x1, y1, x2, y2) = stage._wildlife_crop(frame, (0, 0, 40, 40))

    assert x1 >= 0 and y1 >= 0
    assert x2 <= frame.shape[1] and y2 <= frame.shape[0]
    assert crop.size > 0


def test_box_at_far_corner_stays_in_bounds(frame):
    stage = _Stage()
    h, w = frame.shape[:2]
    crop, (x1, y1, x2, y2) = stage._wildlife_crop(frame, (w - 30, h - 30, 30, 30))

    assert x2 <= w and y2 <= h
    assert crop.size > 0


def test_crop_is_much_smaller_than_the_frame_for_a_typical_subject(frame):
    """The whole point: the subject must dominate what the model sees."""
    stage = _Stage()
    crop, _box = stage._wildlife_crop(frame, (1200, 700, 180, 140))

    frame_px = frame.shape[0] * frame.shape[1]
    crop_px = crop.shape[0] * crop.shape[1]
    assert crop_px < frame_px * 0.05, (
        f"crop is {crop_px / frame_px:.1%} of the frame — the subject would still "
        "be diluted at 224x224"
    )


# ── gating ────────────────────────────────────────────────────────────


def test_gate_closed_without_motion():
    stage = _Stage()
    assert not stage._wildlife_gate_open([], motion_confirmed=False, wildlife_motion_only=False)


def test_gate_open_on_confirmed_motion():
    stage = _Stage()
    assert stage._wildlife_gate_open([], motion_confirmed=True, wildlife_motion_only=False)


def test_gate_closed_when_classifier_unavailable():
    stage = _Stage(wildlife_available=False)
    assert not stage._wildlife_gate_open([], motion_confirmed=True, wildlife_motion_only=False)


@pytest.mark.parametrize("label", ["bird", "dog", "person"])
def test_gate_closed_on_hard_skip_labels(label):
    """These read as themselves to COCO — no point second-guessing."""
    stage = _Stage()
    assert not stage._wildlife_gate_open(
        [_Det(label, 0.7)], motion_confirmed=True, wildlife_motion_only=False
    )


def test_confident_cat_closes_the_gate():
    stage = _Stage()
    assert not stage._wildlife_gate_open(
        [_Det("cat", 0.95)], motion_confirmed=True, wildlife_motion_only=False
    )


def test_soft_cat_leaves_the_gate_open():
    """COCO calls frontal squirrels 'cat' — wildlife must get its say."""
    stage = _Stage()
    assert stage._wildlife_gate_open(
        [_Det("cat", 0.60)], motion_confirmed=True, wildlife_motion_only=False
    )


# ── positional gating: a blocker only blocks where it actually is ─────


class _BoxDet:
    def __init__(self, label, score, bbox):
        self.label = label
        self.score = score
        self.bbox = bbox


# The crop the wildlife stage would classify — a squirrel on the ground.
CROP = (1100, 800, 1500, 1100)


def test_bird_far_from_the_crop_no_longer_blocks():
    """The feeder case: a bird up at the feeder, a squirrel on the ground.

    The whole frame used to be skipped because a bird was detected
    somewhere in it, discarding a squirrel the classifier would never
    have seen the bird in.
    """
    stage = _Stage()
    bird_at_feeder = _BoxDet("bird", 0.8, (200, 100, 320, 240))

    assert stage._wildlife_gate_open(
        [bird_at_feeder],
        motion_confirmed=True,
        wildlife_motion_only=False,
        crop_box=CROP,
    )


def test_bird_inside_the_crop_still_blocks():
    stage = _Stage()
    bird_on_subject = _BoxDet("bird", 0.8, (1150, 850, 1350, 1000))

    assert not stage._wildlife_gate_open(
        [bird_on_subject],
        motion_confirmed=True,
        wildlife_motion_only=False,
        crop_box=CROP,
    )


@pytest.mark.parametrize("label", ["dog", "person"])
def test_other_blockers_are_positional_too(label):
    stage = _Stage()
    far = _BoxDet(label, 0.9, (0, 0, 150, 300))
    near = _BoxDet(label, 0.9, (1150, 850, 1400, 1080))

    assert stage._wildlife_gate_open(
        [far], motion_confirmed=True, wildlife_motion_only=False, crop_box=CROP
    )
    assert not stage._wildlife_gate_open(
        [near], motion_confirmed=True, wildlife_motion_only=False, crop_box=CROP
    )


def test_confident_cat_on_the_crop_still_blocks():
    stage = _Stage()
    cat = _BoxDet("cat", 0.96, (1150, 850, 1400, 1080))

    assert not stage._wildlife_gate_open(
        [cat], motion_confirmed=True, wildlife_motion_only=False, crop_box=CROP
    )


def test_confident_cat_elsewhere_does_not_block():
    stage = _Stage()
    cat = _BoxDet("cat", 0.96, (0, 0, 200, 200))

    assert stage._wildlife_gate_open(
        [cat], motion_confirmed=True, wildlife_motion_only=False, crop_box=CROP
    )


def test_without_a_crop_box_the_old_frame_wide_rule_applies():
    """Callers with no crop keep the conservative behaviour."""
    stage = _Stage()
    bird = _BoxDet("bird", 0.8, (0, 0, 50, 50))

    assert not stage._wildlife_gate_open(
        [bird], motion_confirmed=True, wildlife_motion_only=False, crop_box=None
    )


def test_blocker_without_a_bbox_does_not_crash():
    stage = _Stage()
    weird = _Det("bird", 0.8)  # no bbox attribute

    assert stage._wildlife_gate_open(
        [weird], motion_confirmed=True, wildlife_motion_only=False, crop_box=CROP
    )


# ── _covers ───────────────────────────────────────────────────────────


def test_covers_requires_a_real_overlap():
    stage = _Stage()
    assert not stage._covers((0, 0, 100, 100), (200, 200, 300, 300))
    assert stage._covers((210, 210, 290, 290), (200, 200, 300, 300))


def test_covers_uses_containment_not_iou():
    """A small box fully inside a large region has a low IoU but is
    unambiguously in the way — containment is the right measure."""
    stage = _Stage()
    small_inside = (1200, 900, 1240, 940)
    assert stage._covers(small_inside, CROP)


def test_covers_handles_missing_boxes():
    stage = _Stage()
    assert not stage._covers(None, CROP)
    assert not stage._covers((0, 0, 10, 10), None)
