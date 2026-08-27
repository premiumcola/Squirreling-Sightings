"""SMALL-3 · the wildlife motion floor was dead on arrival.

`_motion_detect` runs a cheap changed-pixel pre-check before findContours.
It was a flat 0.5 % of the frame — 18 432 px on 2560x1440 — while the
wildlife area floor it precedes sits at 5 266 px (0.1 % at the default
sensitivity). A factor of 3.5, so the smaller floor could never fire: an
11 000 px squirrel at the feeder cleared `wl_min_area` and was thrown away
by the pre-check anyway, and the wildlife stage was never even offered the
blob. The pre-check was not an early-out but a hidden third threshold that
silently overrode both configured ones.

The numbers in these tests are the measured ones, not nominal: a 105x105
rectangle blurs and dilates to 13 193 changed pixels / 12 970 contour area,
which lands squarely between the wildlife floor and the old flat gate —
the exact band that was unreachable.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.camera_runtime._motion import MotionMixin

FRAME_H, FRAME_W = 1440, 2560
FRAME_AREA = FRAME_H * FRAME_W

# The two floors this test is about, at the schema-default sensitivities.
OLD_FLAT_GATE = int(FRAME_AREA * 0.005)  # 18 432 px
WL_MIN_AREA = int(FRAME_AREA * 0.001 / 0.7)  # 5 266 px
NORMAL_MIN_AREA = int(FRAME_AREA * 0.005 / 0.5)  # 36 864 px


class _Cam(MotionMixin):
    """Minimal MotionMixin host — no camera, no capture, no threads."""

    def __init__(self, **cfg):
        self.cfg = {"motion_enabled": True, "motion_sensitivity": 0.5}
        self.cfg.update(cfg)
        self.global_cfg = {"processing": {"motion": {"enabled": True, "blur_size": 15}}}
        self.prev_gray = None
        self._mask_image = None
        self._zone_image = None

    def _ensure_mask_image(self):
        pass

    def _ensure_zone_image(self):
        pass


def _blank():
    return np.zeros((FRAME_H, FRAME_W, 3), np.uint8)


def _moved(w, h):
    """A blank frame with one bright w x h rectangle — a subject appearing."""
    f = _blank()
    f[600 : 600 + h, 900 : 900 + w] = 255
    return f


def _detect(cam, frame_w, frame_h):
    """Prime prev_gray, then run the frame that carries the subject."""
    cam._motion_detect(_blank())
    return cam._motion_detect(_moved(frame_w, frame_h))


def test_the_two_floors_really_do_contradict_each_other():
    """The premise, pinned as arithmetic so it cannot rot silently."""
    assert WL_MIN_AREA < OLD_FLAT_GATE
    assert OLD_FLAT_GATE / WL_MIN_AREA > 3.0, "the wildlife floor was unreachable by 3.5x"


def test_a_squirrel_sized_blob_is_offered_to_the_wildlife_stage():
    """The whole point: ~11 000 px of subject must reach the wildlife path.

    Against the old flat gate this frame changed 13 193 px — under 18 432,
    so `_motion_detect` returned (…, False, []) and the D1 blob tracker
    never saw it.
    """
    labels, bbox, wildlife_low, blobs = _detect(_Cam(), 105, 105)

    assert wildlife_low is True, "a subject above wl_min_area must reach the wildlife stage"
    assert len(blobs) == 1, "the D1 blob tracker needs the blob to escalate"
    assert labels == [] and bbox is None, "it must NOT be promoted to normal motion"


def test_noise_below_the_wildlife_floor_is_still_rejected():
    """The floor moved down to wl_min_area, not to zero."""
    _labels, _bbox, wildlife_low, blobs = _detect(_Cam(), 40, 40)

    assert wildlife_low is False
    assert blobs == []


def test_normal_motion_is_untouched():
    """Regression guard: the normal-motion path decides event recording and
    alerts. At the schema-default sensitivity its floor (36 864 px) already
    sat ABOVE the old flat gate, so nothing about it may change."""
    labels, bbox, _wildlife_low, _blobs = _detect(_Cam(), 250, 250)

    assert labels == ["motion"]
    assert bbox is not None
    assert NORMAL_MIN_AREA > OLD_FLAT_GATE, "which is why the normal path is unaffected"


def test_a_camera_can_opt_back_out_per_camera():
    """A security camera wants the opposite trade from the feeder.

    No new setting is needed: the pre-check now derives from the existing
    per-camera knobs, so wildlife_motion_sensitivity=0.2 puts wl_min_area at
    exactly the old 18 432 px and restores the previous deafness for that
    camera alone.
    """
    assert int(FRAME_AREA * 0.001 / 0.2) == OLD_FLAT_GATE

    _labels, _bbox, wildlife_low, blobs = _detect(_Cam(wildlife_motion_sensitivity=0.2), 105, 105)

    assert wildlife_low is False
    assert blobs == []


@pytest.mark.parametrize("killswitch", [{"motion_enabled": False}])
def test_the_kill_switch_still_short_circuits(killswitch):
    assert _detect(_Cam(**killswitch), 250, 250) == ([], None, False, [])
