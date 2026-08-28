"""The tiling-cost arithmetic, pinned against hand-computed values.

No Coral, no camera: `detectors/_projection` is deliberately pure so the
numbers the panel prints and the numbers the simulator's admission gate
refuses on can be checked without hardware.

Reference load throughout: three cameras at 2.86 Hz (the 350 ms schema
default) with the rescue running at its cooldown ceiling of 1/1.5 s.
"""

from __future__ import annotations

import pytest

from app.detectors import _projection as P

_LOAD = [{"fps": 2.86, "rescue_rate": 0.667}] * 3


def test_production_reuses_the_full_pass_and_the_simulator_does_not():
    """`_roi_rescue` hands its full-frame pass to tiled_detect via
    full_dets=; the sim endpoint does not. Reporting one number for both
    is how a measurement of the simulator ends up tuning production."""
    assert P.prod_invokes("3x3") == (9, 9)
    assert P.sim_invokes("3x3") == (10, 10)
    assert P.prod_invokes("off") == (0, 0)
    assert P.sim_invokes("off") == (1, 1)


def test_roi_is_a_range_not_a_point():
    """split_for_magnification returns 1–4 parts depending on the motion
    box, so a point estimate there would be a fiction."""
    assert P.tiles_for_mode("roi") == (1, 4)
    lo, hi = P.duty(_LOAD, 0.0105, "roi")
    assert lo < hi


@pytest.mark.parametrize(
    "invoke_ms,mode,expected_pct",
    [
        # coco_ssd_edgetpu, measured 10.5 ms on the box 2026-08-28.
        (10.5, "off", 9.0),
        (10.5, "2x2", 17.4),
        (10.5, "3x3", 27.9),
        # efficientdet_lite0_edgetpu, 40.4 ms — same hardware, same
        # cameras, and 3x3 no longer fits. The model is half the answer.
        (40.4, "3x3", 107.4),
    ],
)
def test_duty_matches_the_measured_model_timings(invoke_ms, mode, expected_pct):
    _lo, hi = P.duty(_LOAD, invoke_ms / 1000.0, mode)
    assert round(hi * 100, 1) == pytest.approx(expected_pct, abs=0.2)


def test_affordable_invoke_is_the_inverse_of_duty():
    """The useful direction: "3x3 works while one inference stays under
    32 ms" is checkable against a number already on screen."""
    got = {m: P.affordable_invoke_ms(_LOAD, m) for m in ("off", "roi", "2x2", "3x3")}
    assert got == {"off": 99, "roi": 51, "2x2": 51, "3x3": 32}


def test_the_prep_factor_is_clamped_at_the_frame_border():
    """tile_regions pads 15 % per inner edge and clamps at the border, so
    the crop area is 1.32x / 1.44x a frame — NOT (1 + 2*0.15)**2 = 1.69.
    2x2 and 3x3 barely differ in preparation; they differ in invokes."""
    assert P.MODE_PREP_FACTOR["2x2"] == pytest.approx(1.32)
    assert P.MODE_PREP_FACTOR["3x3"] == pytest.approx(1.44)
    lo_2, _ = P.stall_ms("2x2", 24.8, 9.4)
    lo_3, _ = P.stall_ms("3x3", 24.8, 9.4)
    # Nine serial invokes against four — the tiling overhead is not what
    # separates them.
    assert lo_3 > 2 * lo_2 * 0.9


def test_verdict_bands():
    assert P.duty_verdict(0.28) == "ok"
    assert P.duty_verdict(0.70) == "tight"
    assert P.duty_verdict(1.07) == "over"


def test_a_camera_that_never_rescues_costs_the_same_in_every_mode():
    """Duty is driven by the rescue RATE, not by the mode being selected.
    A mode nothing triggers is free."""
    idle = [{"fps": 2.86, "rescue_rate": 0.0}] * 3
    assert P.duty(idle, 0.0105, "off") == P.duty(idle, 0.0105, "3x3")
