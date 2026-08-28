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

# Rolling measured inference wall-time per (cam_id, mode). Small window:
# the question is "what does this cost right now", not "this hour".
_COST_WINDOW = 8
_COST_GUARD = threading.Lock()
_COSTS: dict[tuple[str, str], deque] = {}

# Hard ceiling for one simulator tick's inference. Above this the view is
# not slow, it is broken: the bbox hold-time tops out at 1.5 s, so frames
# arriving 8 s apart show a still picture with boxes that vanish between
# them, and every client-side watchdog in existence fires.
TICK_CEILING_MS = 8000


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


def record_cost(cam_id: str, mode: str, inference_ms: float) -> None:
    """Remember what one tick of ``mode`` actually cost on this camera."""
    key = (cam_id, mode)
    with _COST_GUARD:
        ring = _COSTS.get(key)
        if ring is None:
            ring = deque(maxlen=_COST_WINDOW)
            _COSTS[key] = ring
        ring.append(float(inference_ms))


def measured_cost_ms(cam_id: str, mode: str) -> float | None:
    """Mean measured inference ms for (cam, mode), or None if never run."""
    with _COST_GUARD:
        ring = _COSTS.get((cam_id, mode))
        samples = list(ring) if ring else []
    if not samples:
        return None
    return sum(samples) / len(samples)


def _per_invoke_ms(cam_id: str) -> float | None:
    """Cost of ONE inference on this camera, from whichever mode has been
    measured. Divides each mode's measurement by that mode's invoke count
    so a measurement taken in any mode converts to any other."""
    best: float | None = None
    for mode in ("off", "roi", "2x2", "3x3"):
        got = measured_cost_ms(cam_id, mode)
        if got is None:
            continue
        lo_n, _hi_n = sim_invokes(mode)
        per = got / max(1, lo_n)
        # Prefer the cheapest mode's estimate: it carries the least
        # tiling-overhead contamination per invoke.
        if best is None or per < best:
            best = per
    return best


def affordability(cam_id: str, mode: str) -> dict:
    """Can this camera run ``mode`` right now?

    Returns ``{"ok", "estimated_ms", "per_invoke_ms", "invokes"}``.
    ``ok`` is False only when there IS a measurement and it projects past
    `TICK_CEILING_MS` — an unmeasured camera is always allowed to try
    once, which is what produces the measurement.
    """
    lo_n, hi_n = sim_invokes(mode)
    per = _per_invoke_ms(cam_id)
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
            f"Das ist mehr als der Deckel von {TICK_CEILING_MS / 1000:.0f} s. "
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
