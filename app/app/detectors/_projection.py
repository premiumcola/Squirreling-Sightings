"""Pure cost arithmetic for the tiling modes — no hardware, no I/O.

Everything the telemetry panel and the simulator's affordability gate say
about "can this box run 3×3?" is computed here, so the number under the
mode switch, the number in the Debug tab and the number the backend gates
on can never disagree.

Two invoke counts per mode, and they are NOT the same number:

  * production (`prod_invokes`) — `camera_runtime/_main_loop._roi_rescue`
    hands its already-computed full-frame pass to `tiled_detect` via
    ``full_dets=``, so a rescue costs the tile inferences only.
  * simulator  (`sim_invokes`)  — `routes/coral_test_detection` calls
    `tiled_detect` without ``full_dets``, so the full pass is run again
    and the tick costs 1 + tiles.

Reporting one number for both is how an operator ends up tuning the
production pipeline against a measurement of the simulator.
"""

from __future__ import annotations

# Tiles per mode. ``roi`` is a RANGE: split_for_magnification returns 1–4
# parts depending on how big the motion box is, so a point estimate there
# would be a fiction. Everything downstream carries it as (lo, hi).
MODE_TILES: dict[str, tuple[int, int]] = {
    "off": (0, 0),
    "roi": (1, 4),
    "2x2": (4, 4),
    "3x3": (9, 9),
}

# Duty-cycle bands. 0.85 rather than 1.0 because three cameras whose
# frame intervals drift into phase stall each other well before the device
# is actually saturated — that is exactly what `wait_p95` makes visible.
DUTY_TIGHT = 0.60
DUTY_OVER = 0.85

# Cooldown ceiling on the production rescue path (_RESCUE_MIN_INTERVAL_S
# = 1.5 s in camera_runtime/_main_loop), expressed as a rate.
MAX_RESCUE_RATE_PER_S = 1.0 / 1.5

# Crop area the tile pass has to colour-convert and letterbox, as a
# multiple of one full frame. tile_regions pads each tile by TILE_OVERLAP
# on every inner edge and clamps at the frame border, so the total is NOT
# (1 + 2·0.15)² — the outer tiles lose their outward padding.
#   2×2: each tile 0.575 W → 1.15 W × 1.15 H = 1.32
#   3×3: 0.383 / 0.433 / 0.383 → 1.20 W × 1.20 H = 1.44
MODE_PREP_FACTOR: dict[str, float] = {"off": 1.0, "roi": 1.15, "2x2": 1.32, "3x3": 1.44}


def tiles_for_mode(mode: str) -> tuple[int, int]:
    """(lo, hi) tile count for a mode. Unknown modes cost nothing extra."""
    return MODE_TILES.get(mode, (0, 0))


def prod_invokes(mode: str) -> tuple[int, int]:
    """Inferences one production rescue spends — tiles only, the full-frame
    pass is reused."""
    return tiles_for_mode(mode)


def sim_invokes(mode: str) -> tuple[int, int]:
    """Inferences one simulator tick spends — full-frame pass PLUS tiles."""
    lo, hi = tiles_for_mode(mode)
    return lo + 1, hi + 1


def duty(cameras: list[dict], invoke_s: float, mode: str) -> tuple[float, float]:
    """Fraction of the accelerator consumed, as (lo, hi).

    ``cameras`` is a list of ``{"fps": float, "rescue_rate": float}``. Only
    the `invoke` bucket counts: `pre`/`post` are host CPU and `wait` is
    time spent queueing, neither occupies the device.

    Valid on the TPU tier, where one process-wide lock serialises every
    camera onto one stick. On the CPU tier the interpreters run in
    parallel and there is no single denominator — callers must report
    per-camera loop occupancy instead.
    """
    if invoke_s <= 0:
        return 0.0, 0.0
    lo_n, hi_n = prod_invokes(mode)
    lo = hi = 0.0
    for cam in cameras:
        fps = max(0.0, float(cam.get("fps") or 0.0))
        rate = min(MAX_RESCUE_RATE_PER_S, max(0.0, float(cam.get("rescue_rate") or 0.0)))
        lo += (fps + rate * lo_n) * invoke_s
        hi += (fps + rate * hi_n) * invoke_s
    return round(lo, 4), round(hi, 4)


def stall_ms(mode: str, invoke_ms: float, prep_ms: float) -> tuple[int, int]:
    """Extra wall-time a single rescue frame costs, as (lo, hi) ms.

    On the CPU tier this — not the duty cycle — is the number that hurts:
    the tile inferences run serially inside one frame, so 3×3 stretches
    that one frame by nine invokes while the loop's other frames are
    untouched.
    """
    lo_n, hi_n = prod_invokes(mode)
    prep_extra = max(0.0, MODE_PREP_FACTOR.get(mode, 1.0) - 1.0) * max(0.0, prep_ms)
    return (
        int(round(lo_n * max(0.0, invoke_ms) + prep_extra)),
        int(round(hi_n * max(0.0, invoke_ms) + prep_extra)),
    )


def affordable_invoke_ms(cameras: list[dict], mode: str, ceiling: float = DUTY_OVER) -> int:
    """How expensive ONE inference may be before ``mode`` breaks the budget.

    The inverse of `duty`, and the far more useful direction: "3×3 works
    while an inference stays under 32 ms — measured: 24.8 ms" is an answer,
    where "27.9 % duty" is a number the operator still has to interpret.
    Worst case (the hi tile count) so the answer is the safe one.
    """
    _lo_n, hi_n = prod_invokes(mode)
    denom = 0.0
    for cam in cameras:
        fps = max(0.0, float(cam.get("fps") or 0.0))
        rate = min(MAX_RESCUE_RATE_PER_S, max(0.0, float(cam.get("rescue_rate") or 0.0)))
        denom += fps + rate * hi_n
    if denom <= 0:
        return 0
    return int(round(ceiling / denom * 1000.0))


def duty_verdict(duty_hi: float) -> str:
    """'ok' | 'tight' | 'over' for a worst-case duty fraction."""
    if duty_hi > DUTY_OVER:
        return "over"
    if duty_hi > DUTY_TIGHT:
        return "tight"
    return "ok"
