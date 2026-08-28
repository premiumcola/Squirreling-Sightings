"""Admission control for the Simulieren endpoint.

Two defects made 3×3 take the camera down, and both are here because
`routes/coral_test_detection.py` is already far past the file ceiling.

1. **No in-flight guard.** Flask cannot cancel a request. When the
   frontend's watchdog aborted a slow tick and re-issued it, the aborted
   handler kept running all ten inferences and only discovered the closed
   socket at the final write — so every retry ADDED a live inference job.
   The per-camera detector is one object behind one lock
   (`camera_runtime/runtime.py` builds one `CoralObjectDetector` per cam),
   so k overlapping requests each take k× as long, and the camera's own
   alarm loop queues behind all of them. That is the feedback loop that
   ended with the decoder more than `_LAG_RECONNECT_S` behind live and the
   RTSP stream genuinely torn down. A non-blocking single-slot semaphore
   per camera ends it regardless of what the client does.

2. **No honest refusal.** A mode the hardware cannot afford produced a
   never-completing tick, and the frontend blamed the camera for it. The
   affordability check below extrapolates the cost of a tiled mode from
   what THIS camera measured on a cheaper mode and refuses up front, with
   the arithmetic in the message. Refusing loudly beats hanging quietly:
   a wrong error message cost this project four months once already.

Both numbers the gate needs are MEASURED, never guessed:

  * cost per inference — the handler reports the wall-time it spent AND
    how many inferences it actually ran (`tiled_detect` returns the tile
    count, and ``roi`` really does vary between 2 and 5 per tick). The
    ring stores the quotient, so a measurement taken in any mode converts
    to any other without a convention to get backwards.
  * the ceiling — `MAX_CAPTURE_LAG_S`, the endpoint's own definition of
    "too far behind live to be a live view". A tick whose inference alone
    outlasts the freshness contract the same handler enforces on its
    frames cannot produce a live picture by construction.

The first version of this module got both wrong: it divided by the LOW
invoke count and multiplied by the HIGH one (2.5× off for ``roi``), and
it capped at a guessed 8 000 ms per tick — a bar that needed a single
inference to cost 800 ms, so on a 5950X the refusal, its German text and
its fallback button were all unreachable code.
"""

from __future__ import annotations

import logging
import threading
from collections import deque

from ..detectors._projection import sim_invokes

log = logging.getLogger(__name__)

# One slot per camera. Non-blocking: a second concurrent Simulieren
# request for the same camera is refused, never queued — queueing is what
# lets a wedged client pile up inference threads.
_SLOT_GUARD = threading.Lock()
_SLOTS: dict[str, threading.Semaphore] = {}

# Rolling measured cost PER INFERENCE per (cam_id, mode). Small window:
# the question is "what does this cost right now", not "this hour".
_COST_WINDOW = 8
_COST_GUARD = threading.Lock()
_COSTS: dict[tuple[str, str], deque] = {}

# How far behind live the decoder may be before the handler refuses a
# frame as stale. Owned here rather than in coral_test_detection because
# the affordability ceiling below is the same quantity seen from the
# other end — see TICK_CEILING_MS.
MAX_CAPTURE_LAG_S = 2.0

# Ceiling for the INFERENCE half of one simulator tick.
#
# Derived, not chosen. The handler already refuses any frame whose pixels
# trail real time by more than `MAX_CAPTURE_LAG_S`, and prints "Stream-
# Puffer hinkt zurück" when none arrives in time. A tick whose inference
# alone costs more than that lag budget cannot deliver a picture inside
# it: by the time the boxes are computed the frame they belong to has
# already aged past the bar the same handler applies to every frame it
# serves. So the mode is not slow, it is incapable of the contract.
#
# The number this replaces (8 000 ms) was a guess about per-invoke cost
# and needed one inference to take 800 ms before it could ever fire. This
# one is a budget for the whole tick and is therefore correct on both
# hardware tiers without knowing which one is running: on the TPU
# (coco_ssd 10.5 ms, efficientdet_lite0 40.4 ms — measured 2026-08-28)
# even 3×3 lands at 105–404 ms and is never refused, while a several-
# hundred-ms CPU invoke breaks the budget at ten invokes and not at five.
TICK_CEILING_MS = int(MAX_CAPTURE_LAG_S * 1000)


class _Slot:
    """Context manager around the per-camera semaphore. ``acquired`` says
    whether the caller may proceed; releasing is unconditional-safe."""

    def __init__(self, sem: threading.Semaphore, acquired: bool):
        self._sem = sem
        self.acquired = acquired

    def __enter__(self) -> _Slot:
        return self

    def __exit__(self, *_exc) -> None:
        if self.acquired:
            self.acquired = False
            self._sem.release()


def sim_slot(cam_id: str) -> _Slot:
    """Try to claim this camera's single simulator slot without blocking."""
    with _SLOT_GUARD:
        sem = _SLOTS.get(cam_id)
        if sem is None:
            sem = threading.Semaphore(1)
            _SLOTS[cam_id] = sem
    return _Slot(sem, sem.acquire(blocking=False))


def record_cost(cam_id: str, mode: str, inference_ms: float, invokes: int) -> None:
    """Remember what ONE inference cost on this camera.

    ``invokes`` is the count the handler actually ran for this tick —
    ``1 + len(regions)`` out of `tiled_detect`'s diag, not a table lookup.
    ``roi`` splits into 1–4 crops depending on the motion box, so its tick
    is anywhere between 2 and 5 inferences and the table cannot say which
    one this tick paid for. Dividing here, once, by the true count is what
    makes every stored sample the same unit.
    """
    n = max(1, int(invokes or 1))
    key = (cam_id, mode)
    with _COST_GUARD:
        ring = _COSTS.get(key)
        if ring is None:
            ring = deque(maxlen=_COST_WINDOW)
            _COSTS[key] = ring
        ring.append(float(inference_ms) / n)


def measured_per_invoke_ms(cam_id: str, mode: str) -> float | None:
    """Mean measured ms for ONE inference in (cam, mode), or None."""
    with _COST_GUARD:
        ring = _COSTS.get((cam_id, mode))
        samples = list(ring) if ring else []
    if not samples:
        return None
    return sum(samples) / len(samples)


def _per_invoke_ms(cam_id: str, mode: str) -> float | None:
    """Cost of ONE inference on this camera, for judging ``mode``.

    The mode's OWN measurement wins whenever it exists. Only 3x3 can say
    what 3x3 costs — its per-invoke figure carries the crop and letterbox
    overhead of its own tiling, which no other mode pays.

    The cheapest other measurement stands in only while the mode has
    never run. That optimism is deliberate and bounded: a mode has to be
    allowed once in order to be measured at all, and the very next tick
    replaces the stand-in with its own figure.

    The previous version took the cross-mode minimum unconditionally. It
    read well — "an optimistic estimate can only cause a mode to be
    ALLOWED and then measured properly" — but it never corrected itself.
    One cheap `off` sample sat in the ring and disarmed the refusal
    permanently, even after 3x3 had measured itself at five seconds a
    tick. An estimate that cannot be revised by measurement is not an
    estimate.
    """
    own = measured_per_invoke_ms(cam_id, mode)
    if own is not None:
        return own
    best: float | None = None
    for other in ("off", "roi", "2x2", "3x3"):
        per = measured_per_invoke_ms(cam_id, other)
        if per is None:
            continue
        if best is None or per < best:
            best = per
    return best


def affordability(cam_id: str, mode: str) -> dict:
    """Can this camera run ``mode`` right now?

    Returns ``{"ok", "estimated_ms", "per_invoke_ms", "invokes"}``.
    ``ok`` is False only when there IS a measurement and it projects past
    `TICK_CEILING_MS` — an unmeasured camera is always allowed to try
    once, which is what produces the measurement.

    The projection uses the HIGH invoke count, and the measurement it
    projects from was divided by the invoke count that was actually run.
    Same unit on both sides: the estimate for a mode measured in that
    same mode reproduces the measurement exactly.
    """
    _lo_n, hi_n = sim_invokes(mode)
    per = _per_invoke_ms(cam_id, mode)
    if per is None:
        return {"ok": True, "estimated_ms": None, "per_invoke_ms": None, "invokes": hi_n}
    estimated = per * hi_n
    return {
        "ok": estimated <= TICK_CEILING_MS,
        "estimated_ms": int(round(estimated)),
        "per_invoke_ms": int(round(per)),
        "invokes": hi_n,
    }


def refusal_payload(cam_id: str, mode: str, verdict: dict) -> dict:
    """German refusal body for an unaffordable mode.

    Names the mode, the arithmetic and the way out. Deliberately NOT a
    connection error: the camera is fine, the request is too expensive.
    """
    label = {"roi": "ROI", "2x2": "2×2", "3x3": "3×3"}.get(mode, mode)
    est_s = (verdict.get("estimated_ms") or 0) / 1000.0
    per = verdict.get("per_invoke_ms") or 0
    log.warning(
        "[test-detection] cam=%s mode=%s refused: geschätzt %d ms "
        "(%d Inferenzen à ~%d ms) über Deckel %d ms",
        cam_id,
        mode,
        verdict.get("estimated_ms") or 0,
        verdict.get("invokes") or 0,
        per,
        TICK_CEILING_MS,
    )
    return {
        "ok": False,
        "code": "mode_too_expensive",
        "error": (
            f"{label} kostet auf dieser Hardware {verdict.get('invokes')} Inferenzen "
            f"pro Bild — geschätzt {est_s:.1f} s je Tick (~{per} ms je Inferenz). "
            f"Der Deckel liegt bei {TICK_CEILING_MS / 1000:.1f} s, weil ein Bild "
            "danach älter ist, als der Frische-Vertrag dieser Ansicht erlaubt. "
            "Die Kamera ist in Ordnung; der Modus ist zu teuer. "
            "Mit Coral-TPU oder auf dem Sub-Stream wird er tragbar."
        ),
        "mode": mode,
        "estimated_ms": verdict.get("estimated_ms"),
        "per_invoke_ms": per,
        "invokes": verdict.get("invokes"),
        "ceiling_ms": TICK_CEILING_MS,
    }


def busy_payload(cam_id: str) -> dict:
    """German 'previous analysis still running' body."""
    log.info("[test-detection] cam=%s busy — vorherige Analyse läuft noch", cam_id)
    return {
        "ok": False,
        "code": "busy",
        "error": "Simulation läuft noch — die vorherige Analyse ist nicht abgeschlossen.",
    }
