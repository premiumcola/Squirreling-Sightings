"""How busy the accelerator is — a ~10 s rolling window, computed on read.

``timing_breakdown`` says how long ONE inference takes. It cannot say
whether the TPU has headroom: 12 ms per inference is idle at 3 Hz and
saturated at 80 Hz. The busy ratio here is the sum of inference time in
the window over the wall time of the window — the number that decides
whether a fourth camera or a shorter analysis interval fits.

No thread, no timer: every ``_record_timing`` call appends one
``(t_end, duration)`` pair, and reading prunes what fell out of the
window. Timestamps come from the caller so the class is testable with
any monotonic clock.
"""

from __future__ import annotations

import time
from collections import deque

from ._describe import iter_stages

WINDOW_S = 10.0

_EMPTY = {"count": 0, "busy_s": 0.0, "span_s": 0.0, "mean_ms": None, "per_s": 0.0, "busy": 0.0}


class RollingUtilisation:
    """One interpreter's inference load over the last ``window_s``."""

    def __init__(self, window_s: float = WINDOW_S, clock=time.perf_counter):
        self.window_s = float(window_s)
        self._clock = clock
        self._born = clock()
        self._samples: deque[tuple[float, float]] = deque()

    def record(self, duration_s: float, at: float | None = None) -> None:
        """One finished inference of ``duration_s`` that ended at ``at``
        (clock units; defaults to now)."""
        t = self._clock() if at is None else float(at)
        self._samples.append((t, max(0.0, float(duration_s))))
        self._prune(t)

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_s
        samples = self._samples
        while samples and samples[0][0] < cutoff:
            samples.popleft()

    def snapshot(self, now: float | None = None) -> dict:
        """``count`` / ``busy_s`` / ``span_s`` are the raw ingredients so
        several snapshots can be summed exactly (see ``combine``);
        ``mean_ms`` / ``per_s`` / ``busy`` are the readouts.

        ``span_s`` is the window, or the interpreter's age while it is
        younger than the window — dividing three seconds of samples by
        ten would report a freshly started camera as a third as busy as
        it is."""
        now = self._clock() if now is None else float(now)
        self._prune(now)
        span = min(self.window_s, max(now - self._born, 0.0))
        return _readouts(
            count=len(self._samples),
            busy_s=sum(d for _t, d in self._samples),
            span_s=span,
        )


def _readouts(*, count: int, busy_s: float, span_s: float) -> dict:
    if span_s <= 0.0:
        return dict(_EMPTY)
    return {
        "count": int(count),
        "busy_s": round(busy_s, 4),
        "span_s": round(span_s, 3),
        "mean_ms": round(busy_s / count * 1000.0, 1) if count else None,
        "per_s": round(count / span_s, 2),
        "busy": round(min(1.0, busy_s / span_s), 3),
    }


def combine(parts: list[dict]) -> dict:
    """The load of several interpreters that share ONE device.

    Inferences on the shared TPU serialise behind the process-wide lock,
    so their busy times add; the wall time is the longest span any of
    them has been alive for, capped at the window. Capped at 100 % — a
    sum above it means the clock and the lock disagree, not a device
    that is more than fully busy."""
    parts = [p for p in parts if p]
    if not parts:
        return dict(_EMPTY)
    return _readouts(
        count=sum(int(p.get("count") or 0) for p in parts),
        busy_s=sum(float(p.get("busy_s") or 0.0) for p in parts),
        span_s=max(float(p.get("span_s") or 0.0) for p in parts),
    )


def tpu_utilisation(rt) -> dict | None:
    """One camera's load on the TPU — every stage of its cascade that
    runs there, combined. None while nothing of that camera is on the
    TPU (CPU fallback, or detection off)."""
    parts = [
        st.timing.utilisation()
        for st in iter_stages(rt)
        if st.backend.get("device") == "tpu" and hasattr(st.timing, "utilisation")
    ]
    return combine(parts) if parts else None


def fleet_tpu_utilisation(runtimes: dict) -> dict:
    """Per camera and total, for the status endpoints."""
    cameras = {}
    for cam_id, rt in (runtimes or {}).items():
        util = tpu_utilisation(rt)
        if util is not None:
            cameras[cam_id] = util
    return {
        "window_s": WINDOW_S,
        "total": combine(list(cameras.values())),
        "cameras": cameras,
    }
